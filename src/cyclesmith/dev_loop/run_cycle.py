"""Run deterministic goal-driven dev-loop cycles.

This runner orchestrates existing autonomy-lite artifacts instead of replacing
Planner/Worker/Judge roles. It handles:

- Goal loading (`reports/dev_loop/goal.json`)
- Deterministic ticket selection (`IN_PROGRESS` first, then top-most `TODO`)
- Cycle scaffolding (`reports/dev_loop/<cycle_id>/cycle_context.json`)
- Judge-driven ticket transitions + follow-up ticket insertion
- Memory ingest/validate + profile-based prune cadence
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class TaskType(StrEnum):
    FEATURE = "FEATURE"
    IMPROVEMENT = "IMPROVEMENT"
    BUG = "BUG"
    CHORE = "CHORE"
    INVESTIGATION = "INVESTIGATION"
    REFACTOR = "REFACTOR"
    DOCS = "DOCS"
    PERFORMANCE = "PERFORMANCE"
    SECURITY = "SECURITY"
    TEST = "TEST"


class TicketStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    WIP = "WIP"
    BLOCKED = "BLOCKED"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GoalCompletionMode(StrEnum):
    TARGET_TICKETS_CLOSED = "target_tickets_closed"
    NO_OPEN_TICKETS = "no_open_tickets"


class PruneProfile(StrEnum):
    FAST_LOCAL = "fast-local"
    SHARED_BRANCH = "shared-branch"
    CI_MAIN = "ci-main"


TRANSITION_RULES: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.TODO: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.WIP,
        TicketStatus.BLOCKED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.IN_PROGRESS: {
        TicketStatus.TODO,
        TicketStatus.BLOCKED,
        TicketStatus.REVIEW,
        TicketStatus.COMPLETED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.WIP: {
        TicketStatus.TODO,
        TicketStatus.BLOCKED,
        TicketStatus.REVIEW,
        TicketStatus.COMPLETED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.BLOCKED: {
        TicketStatus.TODO,
        TicketStatus.IN_PROGRESS,
        TicketStatus.WIP,
        TicketStatus.CANCELLED,
    },
    TicketStatus.REVIEW: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.WIP,
        TicketStatus.COMPLETED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.COMPLETED: set(),
    TicketStatus.CANCELLED: set(),
}


PRUNE_POLICY: dict[PruneProfile, tuple[int, int, bool, bool]] = {
    # (cadence_cycles, max_cycle_lag, stale_unknown, dry_run)
    PruneProfile.FAST_LOCAL: (5, 8, False, True),
    PruneProfile.SHARED_BRANCH: (2, 5, True, False),
    PruneProfile.CI_MAIN: (1, 3, True, False),
}


@dataclass(frozen=True)
class TicketRow:
    task_type: TaskType
    task: str
    description: str
    status: TicketStatus

    def to_markdown_row(self) -> str:
        return (
            f"| {self.task_type.value} | {self.task} | {self.description} | {self.status.value} |"
        )


@dataclass(frozen=True)
class TicketsDocument:
    prefix_lines: list[str]
    header_line: str
    separator_line: str
    rows: list[TicketRow]
    suffix_lines: list[str]


@dataclass(frozen=True)
class GoalConfig:
    version: int
    goal_id: str
    objective: str
    completion_mode: GoalCompletionMode
    target_tickets: list[str]
    max_cycles: int
    prune_profile: PruneProfile
    stop_conditions: list[str]


@dataclass(frozen=True)
class RunnerState:
    version: int
    goal_id: str
    current_cycle_id: str | None
    current_ticket: str | None
    cycles_started: int
    cycles_finalized: int
    history: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "goal_id": self.goal_id,
            "current_cycle_id": self.current_cycle_id,
            "current_ticket": self.current_ticket,
            "cycles_started": self.cycles_started,
            "cycles_finalized": self.cycles_finalized,
            "history": self.history,
        }


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _expect_string(obj: dict[str, Any], key: str, context: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string.")
    return value


def _expect_int(obj: dict[str, Any], key: str, context: str) -> int:
    value = obj.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{context}.{key} must be an integer.")
    return value


def _expect_string_list(obj: dict[str, Any], key: str, context: str) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{context}.{key} must be a list.")
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{context}.{key}[{index}] must be a non-empty string.")
        out.append(item)
    return out


def _read_json_object(path: Path, *, context: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{context} file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{context} root must be an object: {path}")
    return raw


def _parse_goal(path: Path) -> GoalConfig:
    raw = _read_json_object(path, context="goal")
    version = _expect_int(raw, "version", "goal")
    if version != 1:
        raise ValueError(f"goal.version must be 1, found {version}")

    goal_id = _expect_string(raw, "goal_id", "goal")
    objective = _expect_string(raw, "objective", "goal")
    completion_mode_text = _expect_string(raw, "completion_mode", "goal")
    max_cycles = _expect_int(raw, "max_cycles", "goal")
    if max_cycles <= 0:
        raise ValueError("goal.max_cycles must be > 0")
    prune_profile_text = _expect_string(raw, "prune_profile", "goal")
    target_tickets = _expect_string_list(raw, "target_tickets", "goal")
    stop_conditions = _expect_string_list(raw, "stop_conditions", "goal")

    try:
        completion_mode = GoalCompletionMode(completion_mode_text)
    except ValueError as exc:
        raise ValueError(f"goal.completion_mode unsupported value: {completion_mode_text}") from exc
    try:
        prune_profile = PruneProfile(prune_profile_text)
    except ValueError as exc:
        raise ValueError(f"goal.prune_profile unsupported value: {prune_profile_text}") from exc

    if completion_mode == GoalCompletionMode.TARGET_TICKETS_CLOSED and not target_tickets:
        raise ValueError("goal.target_tickets must be non-empty for target_tickets_closed mode.")

    return GoalConfig(
        version=version,
        goal_id=goal_id,
        objective=objective,
        completion_mode=completion_mode,
        target_tickets=target_tickets,
        max_cycles=max_cycles,
        prune_profile=prune_profile,
        stop_conditions=stop_conditions,
    )


def _default_state(goal_id: str) -> RunnerState:
    return RunnerState(
        version=1,
        goal_id=goal_id,
        current_cycle_id=None,
        current_ticket=None,
        cycles_started=0,
        cycles_finalized=0,
        history=[],
    )


def _load_state(path: Path, goal_id: str) -> RunnerState:
    if not path.exists():
        return _default_state(goal_id)

    raw = _read_json_object(path, context="state")
    version = _expect_int(raw, "version", "state")
    if version != 1:
        raise ValueError(f"state.version must be 1, found {version}")
    raw_goal_id = _expect_string(raw, "goal_id", "state")
    if raw_goal_id != goal_id:
        raise ValueError(f"state.goal_id ({raw_goal_id}) does not match goal.goal_id ({goal_id})")

    current_cycle_id_value = raw.get("current_cycle_id")
    current_ticket_value = raw.get("current_ticket")
    if current_cycle_id_value is None:
        current_cycle_id: str | None = None
    elif isinstance(current_cycle_id_value, str) and current_cycle_id_value.strip():
        current_cycle_id = current_cycle_id_value
    else:
        raise ValueError("state.current_cycle_id must be null or non-empty string.")

    if current_ticket_value is None:
        current_ticket: str | None = None
    elif isinstance(current_ticket_value, str) and current_ticket_value.strip():
        current_ticket = current_ticket_value
    else:
        raise ValueError("state.current_ticket must be null or non-empty string.")

    if (current_cycle_id is None) != (current_ticket is None):
        raise ValueError(
            "state.current_cycle_id and state.current_ticket must be both null or both set."
        )

    cycles_started = _expect_int(raw, "cycles_started", "state")
    cycles_finalized = _expect_int(raw, "cycles_finalized", "state")
    if cycles_started < 0 or cycles_finalized < 0:
        raise ValueError("state cycle counters must be >= 0.")

    history_value = raw.get("history")
    if not isinstance(history_value, list):
        raise ValueError("state.history must be a list.")
    history: list[dict[str, str]] = []
    for index, entry in enumerate(history_value):
        if not isinstance(entry, dict):
            raise ValueError(f"state.history[{index}] must be an object.")
        normalized: dict[str, str] = {}
        for key, value in entry.items():
            if not isinstance(key, str):
                raise ValueError(f"state.history[{index}] contains non-string key.")
            if not isinstance(value, str):
                raise ValueError(f"state.history[{index}].{key} must be a string.")
            normalized[key] = value
        history.append(normalized)

    return RunnerState(
        version=version,
        goal_id=raw_goal_id,
        current_cycle_id=current_cycle_id,
        current_ticket=current_ticket,
        cycles_started=cycles_started,
        cycles_finalized=cycles_finalized,
        history=history,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")


def _write_state(path: Path, state: RunnerState) -> None:
    _write_json(path, state.to_dict())


def _split_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
    return cells


def _parse_tickets(path: Path) -> TicketsDocument:
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = -1
    for index, line in enumerate(lines):
        if line.strip() == "| Task Type | Task | Description | Status |":
            header_index = index
            break
    if header_index < 0:
        raise ValueError("Could not find ticket table header in tickets.md")

    if header_index + 1 >= len(lines):
        raise ValueError("tickets.md missing table separator line.")
    separator_line = lines[header_index + 1]
    if not separator_line.strip().startswith("| ---"):
        raise ValueError("tickets.md has invalid table separator line.")

    rows: list[TicketRow] = []
    cursor = header_index + 2
    while cursor < len(lines):
        cells = _split_row(lines[cursor])
        if cells is None:
            break
        if len(cells) != 4:
            raise ValueError(f"Invalid ticket table row at line {cursor + 1}.")
        task_type_text, task, description, status_text = cells
        try:
            task_type = TaskType(task_type_text)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported task type in tickets row {cursor + 1}: {task_type_text}"
            ) from exc
        try:
            status = TicketStatus(status_text)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported ticket status in row {cursor + 1}: {status_text}"
            ) from exc
        rows.append(
            TicketRow(task_type=task_type, task=task, description=description, status=status)
        )
        cursor += 1

    return TicketsDocument(
        prefix_lines=lines[:header_index],
        header_line=lines[header_index],
        separator_line=separator_line,
        rows=rows,
        suffix_lines=lines[cursor:],
    )


def _write_tickets(path: Path, tickets: TicketsDocument) -> None:
    out_lines: list[str] = []
    out_lines.extend(tickets.prefix_lines)
    out_lines.append(tickets.header_line)
    out_lines.append(tickets.separator_line)
    out_lines.extend(row.to_markdown_row() for row in tickets.rows)
    out_lines.extend(tickets.suffix_lines)
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def _find_ticket_index(rows: list[TicketRow], title: str) -> int | None:
    for index, row in enumerate(rows):
        if row.task == title:
            return index
    return None


def _transition_status(current: TicketStatus, next_status: TicketStatus) -> None:
    if current == next_status:
        return
    allowed = TRANSITION_RULES[current]
    if next_status not in allowed:
        raise ValueError(f"Invalid status transition: {current.value} -> {next_status.value}")


def _replace_status(
    rows: list[TicketRow], index: int, next_status: TicketStatus
) -> list[TicketRow]:
    current_row = rows[index]
    _transition_status(current_row.status, next_status)
    updated_row = TicketRow(
        task_type=current_row.task_type,
        task=current_row.task,
        description=current_row.description,
        status=next_status,
    )
    updated = list(rows)
    updated[index] = updated_row
    return updated


def _select_ticket(rows: list[TicketRow]) -> tuple[int, bool]:
    in_progress = [
        index for index, row in enumerate(rows) if row.status == TicketStatus.IN_PROGRESS
    ]
    if len(in_progress) > 1:
        raise ValueError("tickets.md must contain at most one IN_PROGRESS ticket.")
    if len(in_progress) == 1:
        return in_progress[0], False

    for index, row in enumerate(rows):
        if row.status == TicketStatus.TODO:
            return index, True
    raise ValueError(
        "No runnable ticket found. Require one IN_PROGRESS or at least one TODO ticket."
    )


def _is_closed_status(status: TicketStatus) -> bool:
    return status in {TicketStatus.REVIEW, TicketStatus.COMPLETED, TicketStatus.CANCELLED}


def _is_goal_complete(goal: GoalConfig, rows: list[TicketRow]) -> bool:
    if goal.completion_mode == GoalCompletionMode.NO_OPEN_TICKETS:
        return all(_is_closed_status(row.status) for row in rows)

    status_by_title = {row.task: row.status for row in rows}
    for title in goal.target_tickets:
        status = status_by_title.get(title)
        if status is None:
            raise ValueError(f"goal.target_tickets contains missing ticket title: {title}")
        if not _is_closed_status(status):
            return False
    return True


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        return "goal"
    return slug[:24]


def _next_cycle_id(cycles_root: Path, goal_id: str) -> str:
    cycles_root.mkdir(parents=True, exist_ok=True)
    date_prefix = datetime.now(UTC).strftime("%Y%m%d")
    slug = _slugify(goal_id)
    pattern = re.compile(rf"^{date_prefix}-{re.escape(slug)}-(\d{{2}})$")
    max_seen = 0
    for item in cycles_root.iterdir():
        if not item.is_dir():
            continue
        match = pattern.fullmatch(item.name)
        if match is None:
            continue
        max_seen = max(max_seen, int(match.group(1)))
    return f"{date_prefix}-{slug}-{max_seen + 1:02d}"


def _start_cycle(
    *,
    goal: GoalConfig,
    state: RunnerState,
    tickets_path: Path,
    cycles_root: Path,
) -> tuple[RunnerState, str]:
    tickets = _parse_tickets(tickets_path)
    index, promote = _select_ticket(tickets.rows)
    rows = list(tickets.rows)

    if promote:
        rows = _replace_status(rows, index, TicketStatus.IN_PROGRESS)
    selected = rows[index]

    cycle_id = _next_cycle_id(cycles_root, goal.goal_id)
    cycle_dir = cycles_root / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)

    cycle_context = {
        "version": 1,
        "generated_at": _utc_now_iso(),
        "goal": {
            "goal_id": goal.goal_id,
            "objective": goal.objective,
            "completion_mode": goal.completion_mode.value,
            "target_tickets": goal.target_tickets,
            "max_cycles": goal.max_cycles,
            "prune_profile": goal.prune_profile.value,
            "stop_conditions": goal.stop_conditions,
        },
        "ticket": {
            "type": selected.task_type.value,
            "title": selected.task,
            "status": selected.status.value,
        },
        "next_expected_artifacts": ["planner.json", "worker.json", "judge.json"],
        "required_cycle_checks": [
            "cyclesmith validate -- --cycle-dir <cycle_id> --validate-schema",
            (
                "cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json "
                "ingest --cycle-dir <cycle_id>"
            ),
            "cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json validate",
        ],
    }
    _write_json(cycle_dir / "cycle_context.json", cycle_context)

    updated_tickets = TicketsDocument(
        prefix_lines=tickets.prefix_lines,
        header_line=tickets.header_line,
        separator_line=tickets.separator_line,
        rows=rows,
        suffix_lines=tickets.suffix_lines,
    )
    _write_tickets(tickets_path, updated_tickets)

    new_state = RunnerState(
        version=state.version,
        goal_id=state.goal_id,
        current_cycle_id=cycle_id,
        current_ticket=selected.task,
        cycles_started=state.cycles_started + 1,
        cycles_finalized=state.cycles_finalized,
        history=state.history,
    )
    return new_state, selected.task


def _run_subprocess(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _run_checked(command: list[str], *, context: str) -> None:
    result = _run_subprocess(command)
    if result.returncode == 0:
        return
    output = result.stdout.strip()
    if result.stderr.strip():
        output = f"{output}\n{result.stderr.strip()}".strip()
    raise ValueError(f"{context} failed (exit={result.returncode}):\n{output}")


def _load_judge(path: Path) -> tuple[str, str, TicketStatus, str, list[dict[str, str]]]:
    judge = _read_json_object(path, context="judge artifact")
    cycle_id = _expect_string(judge, "cycle_id", "judge")
    ticket_title = _expect_string(judge, "ticket_title", "judge")
    transition_text = _expect_string(judge, "ticket_transition", "judge")
    verdict = _expect_string(judge, "verdict", "judge")

    try:
        transition = TicketStatus(transition_text)
    except ValueError as exc:
        raise ValueError(f"judge.ticket_transition unsupported value: {transition_text}") from exc
    if transition not in {TicketStatus.REVIEW, TicketStatus.IN_PROGRESS, TicketStatus.BLOCKED}:
        raise ValueError(
            f"judge.ticket_transition must be REVIEW/IN_PROGRESS/BLOCKED, found {transition}"
        )

    follow_up_value = judge.get("follow_up_tickets")
    if not isinstance(follow_up_value, list):
        raise ValueError("judge.follow_up_tickets must be a list.")
    follow_ups: list[dict[str, str]] = []
    for index, item in enumerate(follow_up_value):
        if not isinstance(item, dict):
            raise ValueError(f"judge.follow_up_tickets[{index}] must be an object.")
        task_type = _expect_string(item, "task_type", f"judge.follow_up_tickets[{index}]")
        task = _expect_string(item, "task", f"judge.follow_up_tickets[{index}]")
        description = _expect_string(item, "description", f"judge.follow_up_tickets[{index}]")
        status = _expect_string(item, "status", f"judge.follow_up_tickets[{index}]")
        try:
            TaskType(task_type)
        except ValueError as exc:
            raise ValueError(
                f"judge.follow_up_tickets[{index}].task_type unsupported value: {task_type}"
            ) from exc
        if status != TicketStatus.TODO.value:
            raise ValueError(f"judge.follow_up_tickets[{index}].status must be TODO.")
        follow_ups.append(
            {
                "task_type": task_type,
                "task": task,
                "description": description,
                "status": status,
            }
        )
    return cycle_id, ticket_title, transition, verdict, follow_ups


def _merge_follow_ups(
    rows: list[TicketRow], follow_ups: list[dict[str, str]]
) -> tuple[list[TicketRow], int]:
    updated_rows = list(rows)
    existing_titles = {row.task for row in updated_rows}
    added = 0
    for follow_up in follow_ups:
        title = follow_up["task"]
        if title in existing_titles:
            continue
        updated_rows.append(
            TicketRow(
                task_type=TaskType(follow_up["task_type"]),
                task=title,
                description=follow_up["description"],
                status=TicketStatus.TODO,
            )
        )
        existing_titles.add(title)
        added += 1
    return updated_rows, added


def _maybe_prune_memory(
    *,
    goal: GoalConfig,
    finalized_count: int,
    current_cycle: str,
    memory_path: Path,
    cycles_root: Path,
) -> tuple[bool, list[str]]:
    cadence, max_lag, stale_unknown, dry_run = PRUNE_POLICY[goal.prune_profile]
    if finalized_count % cadence != 0:
        return False, []

    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "memory_snapshot.py"),
        "--memory",
        str(memory_path),
        "prune-stale",
        "--current-cycle",
        current_cycle,
        "--max-cycle-lag",
        str(max_lag),
        "--cycles-root",
        str(cycles_root),
    ]
    if stale_unknown:
        command.append("--stale-unknown")
    if dry_run:
        command.append("--dry-run")

    _run_checked(command, context="memory prune")
    return True, command


def _finalize_cycle(
    *,
    goal: GoalConfig,
    state: RunnerState,
    tickets_path: Path,
    cycles_root: Path,
    memory_path: Path,
) -> RunnerState:
    if state.current_cycle_id is None or state.current_ticket is None:
        raise ValueError("No active cycle to finalize.")

    cycle_dir = cycles_root / state.current_cycle_id
    for name in ("planner.json", "worker.json", "judge.json"):
        artifact = cycle_dir / name
        if not artifact.exists():
            raise ValueError(f"Cycle {state.current_cycle_id} is waiting for artifact: {artifact}")

    validator_script = Path(__file__).resolve().parent / "validate_cycle_artifacts.py"
    _run_checked(
        [
            sys.executable,
            str(validator_script),
            "--cycle-dir",
            str(cycle_dir),
            "--tickets",
            str(tickets_path),
            "--validate-schema",
        ],
        context="cycle artifact validation",
    )

    cycle_id, ticket_title, transition, verdict, follow_ups = _load_judge(cycle_dir / "judge.json")
    if cycle_id != state.current_cycle_id:
        raise ValueError(
            f"judge.cycle_id mismatch: expected {state.current_cycle_id}, found {cycle_id}"
        )
    if ticket_title != state.current_ticket:
        raise ValueError(
            f"judge.ticket_title mismatch: expected {state.current_ticket}, found {ticket_title}"
        )

    tickets = _parse_tickets(tickets_path)
    ticket_index = _find_ticket_index(tickets.rows, ticket_title)
    if ticket_index is None:
        raise ValueError(f"Ticket not found in tickets.md: {ticket_title}")

    transitioned_rows = _replace_status(tickets.rows, ticket_index, transition)
    merged_rows, follow_up_added = _merge_follow_ups(transitioned_rows, follow_ups)
    _write_tickets(
        tickets_path,
        TicketsDocument(
            prefix_lines=tickets.prefix_lines,
            header_line=tickets.header_line,
            separator_line=tickets.separator_line,
            rows=merged_rows,
            suffix_lines=tickets.suffix_lines,
        ),
    )

    memory_script = Path(__file__).resolve().parent / "memory_snapshot.py"
    _run_checked(
        [
            sys.executable,
            str(memory_script),
            "--memory",
            str(memory_path),
            "ingest",
            "--cycle-dir",
            str(cycle_dir),
        ],
        context="memory ingest",
    )
    _run_checked(
        [
            sys.executable,
            str(memory_script),
            "--memory",
            str(memory_path),
            "validate",
        ],
        context="memory validate",
    )

    next_finalized = state.cycles_finalized + 1
    pruned, prune_command = _maybe_prune_memory(
        goal=goal,
        finalized_count=next_finalized,
        current_cycle=cycle_id,
        memory_path=memory_path,
        cycles_root=cycles_root,
    )

    runner_sync = {
        "version": 1,
        "synced_at": _utc_now_iso(),
        "cycle_id": cycle_id,
        "ticket_title": ticket_title,
        "verdict": verdict,
        "ticket_transition": transition.value,
        "follow_up_tickets_added": follow_up_added,
        "memory_ingest": True,
        "memory_prune_triggered": pruned,
        "memory_prune_command": prune_command,
    }
    _write_json(cycle_dir / "runner_sync.json", runner_sync)

    history = list(state.history)
    history.append(
        {
            "cycle_id": cycle_id,
            "ticket_title": ticket_title,
            "verdict": verdict,
            "ticket_transition": transition.value,
            "synced_at": _utc_now_iso(),
        }
    )

    return RunnerState(
        version=state.version,
        goal_id=state.goal_id,
        current_cycle_id=None,
        current_ticket=None,
        cycles_started=state.cycles_started,
        cycles_finalized=next_finalized,
        history=history,
    )


def _status_summary(*, goal: GoalConfig, state: RunnerState, rows: list[TicketRow]) -> str:
    counts: dict[TicketStatus, int] = {status: 0 for status in TicketStatus}
    for row in rows:
        counts[row.status] += 1
    goal_complete = _is_goal_complete(goal, rows)
    return (
        "[runner] status: "
        f"goal_id={goal.goal_id}, complete={str(goal_complete).lower()}, "
        f"current_cycle={state.current_cycle_id or 'none'}, "
        f"current_ticket={state.current_ticket or 'none'}, "
        f"started={state.cycles_started}, finalized={state.cycles_finalized}, "
        f"todo={counts[TicketStatus.TODO]}, in_progress={counts[TicketStatus.IN_PROGRESS]}, "
        f"review={counts[TicketStatus.REVIEW]}, blocked={counts[TicketStatus.BLOCKED]}"
    )


def _run_loop(
    *,
    goal_path: Path,
    state_path: Path,
    tickets_path: Path,
    cycles_root: Path,
    memory_path: Path,
    max_actions: int,
) -> int:
    if max_actions <= 0:
        raise ValueError("--max-actions must be > 0.")

    goal = _parse_goal(goal_path)
    state = _load_state(state_path, goal.goal_id)
    actions = 0

    while actions < max_actions:
        tickets = _parse_tickets(tickets_path)
        if _is_goal_complete(goal, tickets.rows):
            print(f"[runner] Goal complete: {goal.goal_id}")
            _write_state(state_path, state)
            print(_status_summary(goal=goal, state=state, rows=tickets.rows))
            return 0

        if state.cycles_started >= goal.max_cycles and state.current_cycle_id is None:
            raise ValueError(
                f"goal.max_cycles reached ({goal.max_cycles}); no additional cycles can be started."
            )

        if state.current_cycle_id is not None:
            cycle_dir = cycles_root / state.current_cycle_id
            has_all_artifacts = all(
                (cycle_dir / name).exists()
                for name in ("planner.json", "worker.json", "judge.json")
            )
            if not has_all_artifacts:
                print(
                    "[runner] Waiting for role artifacts in "
                    f"{cycle_dir}. Expected planner.json, worker.json, judge.json."
                )
                _write_state(state_path, state)
                print(_status_summary(goal=goal, state=state, rows=tickets.rows))
                return 0
            state = _finalize_cycle(
                goal=goal,
                state=state,
                tickets_path=tickets_path,
                cycles_root=cycles_root,
                memory_path=memory_path,
            )
            _write_state(state_path, state)
            actions += 1
            continue

        state, selected_ticket = _start_cycle(
            goal=goal,
            state=state,
            tickets_path=tickets_path,
            cycles_root=cycles_root,
        )
        _write_state(state_path, state)
        actions += 1
        print(f"[runner] Started cycle {state.current_cycle_id} for ticket: {selected_ticket}")

    tickets = _parse_tickets(tickets_path)
    print(_status_summary(goal=goal, state=state, rows=tickets.rows))
    return 0


def _init_goal(path: Path, tickets_path: Path, goal_id: str, objective: str) -> int:
    tickets = _parse_tickets(tickets_path)
    default_targets = [
        row.task
        for row in tickets.rows
        if row.status in {TicketStatus.TODO, TicketStatus.IN_PROGRESS}
    ]
    payload = {
        "version": 1,
        "goal_id": goal_id,
        "objective": objective,
        "completion_mode": GoalCompletionMode.TARGET_TICKETS_CLOSED.value,
        "target_tickets": default_targets,
        "max_cycles": 20,
        "prune_profile": PruneProfile.SHARED_BRANCH.value,
        "stop_conditions": [
            "same ticket receives three consecutive rework verdicts",
            "two consecutive cycles produce failing required checks",
            "operator requests pause",
        ],
    }
    _write_json(path, payload)
    print(f"[runner] Goal file written: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic goal-driven dev-loop cycles.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Run start/finalize loop for up to --max-actions."
    )
    run_parser.add_argument(
        "--goal",
        type=Path,
        default=Path("reports/dev_loop/goal.json"),
        help="Path to goal configuration JSON.",
    )
    run_parser.add_argument(
        "--state",
        type=Path,
        default=Path("reports/dev_loop/runner_state.json"),
        help="Path to runner state JSON.",
    )
    run_parser.add_argument(
        "--tickets",
        type=Path,
        default=Path("tickets.md"),
        help="Path to tickets markdown file.",
    )
    run_parser.add_argument(
        "--cycles-root",
        type=Path,
        default=Path("reports/dev_loop"),
        help="Directory that stores cycle folders.",
    )
    run_parser.add_argument(
        "--memory",
        type=Path,
        default=Path("reports/dev_loop/memory_snapshot.json"),
        help="Path to memory snapshot JSON.",
    )
    run_parser.add_argument(
        "--max-actions",
        type=int,
        default=2,
        help="Maximum automation actions for this invocation.",
    )

    init_goal_parser = subparsers.add_parser(
        "init-goal",
        help="Write a goal file template seeded from open tickets.",
    )
    init_goal_parser.add_argument(
        "--goal",
        type=Path,
        default=Path("reports/dev_loop/goal.json"),
        help="Output goal file path.",
    )
    init_goal_parser.add_argument(
        "--tickets",
        type=Path,
        default=Path("tickets.md"),
        help="Path to tickets markdown file.",
    )
    init_goal_parser.add_argument(
        "--goal-id",
        type=str,
        default="cyclesmith-dev-loop-goal",
        help="Goal id slug.",
    )
    init_goal_parser.add_argument(
        "--objective",
        type=str,
        default=(
            "Advance target tickets through planner/worker/judge cycles with QA and memory sync."
        ),
        help="Top-level objective text.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run cycle runner CLI.

    Args:
        argv: Optional argument list. Uses process arguments when omitted.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            return _run_loop(
                goal_path=args.goal,
                state_path=args.state,
                tickets_path=args.tickets,
                cycles_root=args.cycles_root,
                memory_path=args.memory,
                max_actions=args.max_actions,
            )
        if args.command == "init-goal":
            return _init_goal(
                path=args.goal,
                tickets_path=args.tickets,
                goal_id=args.goal_id,
                objective=args.objective,
            )
        raise ValueError(f"Unsupported command: {args.command}")
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[runner] ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

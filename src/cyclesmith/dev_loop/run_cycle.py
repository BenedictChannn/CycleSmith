"""Run deterministic goal-driven dev-loop cycles.

This runner orchestrates existing autonomy-lite artifacts instead of replacing
Planner/Worker/Judge roles. It handles:

- Goal loading (`reports/dev_loop/goal.json`)
- Deterministic ticket selection (`IN_PROGRESS` first, then top-most `TODO`)
- Cycle scaffolding (`reports/dev_loop/<cycle_id>/cycle_context.json`)
- Optional command-driven planner/worker/judge role execution
- Judge-driven ticket transitions + follow-up ticket insertion
- Memory ingest/validate + profile-based prune cadence
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from cyclesmith.dev_loop.ticket_backends import (
    TRANSITION_RULES,
    TaskType,
    TicketBackend,
    TicketBackendKind,
    TicketRow,
    TicketsDocument,
    TicketStatus,
    resolve_ticket_backend,
)


class GoalCompletionMode(StrEnum):
    TARGET_TICKETS_CLOSED = "target_tickets_closed"
    NO_OPEN_TICKETS = "no_open_tickets"


class PolicyPack(StrEnum):
    FAST_LOCAL = "fast-local"
    SHARED_BRANCH = "shared-branch"
    CI_MAIN = "ci-main"


class SelectionPolicy(StrEnum):
    IN_PROGRESS_THEN_TODO = "in_progress_then_todo"
    TODO_THEN_IN_PROGRESS = "todo_then_in_progress"


class RoleName(StrEnum):
    PLANNER = "planner"
    WORKER = "worker"
    JUDGE = "judge"


@dataclass(frozen=True)
class RoleCommands:
    planner: tuple[str, ...] | None
    worker: tuple[str, ...] | None
    judge: tuple[str, ...] | None

    def for_role(self, role: RoleName) -> tuple[str, ...] | None:
        if role == RoleName.PLANNER:
            return self.planner
        if role == RoleName.WORKER:
            return self.worker
        if role == RoleName.JUDGE:
            return self.judge
        raise ValueError(f"Unsupported role: {role.value}")

    def configured_roles(self) -> list[str]:
        configured: list[str] = []
        if self.planner is not None:
            configured.append(RoleName.PLANNER.value)
        if self.worker is not None:
            configured.append(RoleName.WORKER.value)
        if self.judge is not None:
            configured.append(RoleName.JUDGE.value)
        return configured

    def mode(self) -> str:
        if self.planner is None and self.worker is None and self.judge is None:
            return "manual"
        return "command"


ROLE_SEQUENCE: tuple[tuple[RoleName, str], ...] = (
    (RoleName.PLANNER, "planner.json"),
    (RoleName.WORKER, "worker.json"),
    (RoleName.JUDGE, "judge.json"),
)


@dataclass(frozen=True)
class PolicyPackConfig:
    selection_policy: SelectionPolicy
    prune_cadence_cycles: int
    prune_max_cycle_lag: int
    prune_stale_unknown: bool
    prune_dry_run: bool
    min_follow_up_tickets: int


POLICY_PACKS: dict[PolicyPack, PolicyPackConfig] = {
    PolicyPack.FAST_LOCAL: PolicyPackConfig(
        selection_policy=SelectionPolicy.TODO_THEN_IN_PROGRESS,
        prune_cadence_cycles=5,
        prune_max_cycle_lag=8,
        prune_stale_unknown=False,
        prune_dry_run=True,
        min_follow_up_tickets=1,
    ),
    PolicyPack.SHARED_BRANCH: PolicyPackConfig(
        selection_policy=SelectionPolicy.IN_PROGRESS_THEN_TODO,
        prune_cadence_cycles=2,
        prune_max_cycle_lag=5,
        prune_stale_unknown=True,
        prune_dry_run=False,
        min_follow_up_tickets=1,
    ),
    PolicyPack.CI_MAIN: PolicyPackConfig(
        selection_policy=SelectionPolicy.IN_PROGRESS_THEN_TODO,
        prune_cadence_cycles=1,
        prune_max_cycle_lag=3,
        prune_stale_unknown=True,
        prune_dry_run=False,
        min_follow_up_tickets=1,
    ),
}


@dataclass(frozen=True)
class OperatorFeedback:
    feedback_id: str
    target_ticket: str
    summary: str
    required_planner_action: str


@dataclass(frozen=True)
class GoalConfig:
    version: int
    goal_id: str
    objective: str
    completion_mode: GoalCompletionMode
    target_tickets: list[str]
    max_cycles: int
    policy_pack: PolicyPack
    stop_conditions: list[str]
    role_commands: RoleCommands


@dataclass(frozen=True)
class RunnerState:
    version: int
    goal_id: str
    current_cycle_id: str | None
    current_ticket: str | None
    pending_feedback_id: str | None
    last_consumed_feedback_id: str | None
    cycles_started: int
    cycles_finalized: int
    history: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "goal_id": self.goal_id,
            "current_cycle_id": self.current_cycle_id,
            "current_ticket": self.current_ticket,
            "pending_feedback_id": self.pending_feedback_id,
            "last_consumed_feedback_id": self.last_consumed_feedback_id,
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


def _normalize_command_tokens(tokens: list[Any], *, context: str) -> tuple[str, ...]:
    if not tokens:
        raise ValueError(f"{context} must be a non-empty list of command tokens.")
    normalized: list[str] = []
    for index, token in enumerate(tokens):
        if not isinstance(token, str) or not token.strip():
            raise ValueError(f"{context}[{index}] must be a non-empty string.")
        normalized.append(token)
    return tuple(normalized)


def _parse_role_commands(raw: Any) -> RoleCommands:
    if raw is None:
        return RoleCommands(planner=None, worker=None, judge=None)
    if not isinstance(raw, dict):
        raise ValueError("goal.role_commands must be an object when provided.")

    allowed_keys = {RoleName.PLANNER.value, RoleName.WORKER.value, RoleName.JUDGE.value}
    for key in raw:
        if key not in allowed_keys:
            raise ValueError(f"goal.role_commands contains unsupported key: {key}")

    planner: tuple[str, ...] | None = None
    worker: tuple[str, ...] | None = None
    judge: tuple[str, ...] | None = None

    planner_value = raw.get(RoleName.PLANNER.value)
    if planner_value is not None:
        if not isinstance(planner_value, list):
            raise ValueError("goal.role_commands.planner must be a list of command tokens.")
        planner = _normalize_command_tokens(planner_value, context="goal.role_commands.planner")

    worker_value = raw.get(RoleName.WORKER.value)
    if worker_value is not None:
        if not isinstance(worker_value, list):
            raise ValueError("goal.role_commands.worker must be a list of command tokens.")
        worker = _normalize_command_tokens(worker_value, context="goal.role_commands.worker")

    judge_value = raw.get(RoleName.JUDGE.value)
    if judge_value is not None:
        if not isinstance(judge_value, list):
            raise ValueError("goal.role_commands.judge must be a list of command tokens.")
        judge = _normalize_command_tokens(judge_value, context="goal.role_commands.judge")

    return RoleCommands(planner=planner, worker=worker, judge=judge)


def _resolve_role_commands(
    *,
    goal_role_commands: RoleCommands,
    planner_override: list[str] | None,
    worker_override: list[str] | None,
    judge_override: list[str] | None,
) -> RoleCommands:
    planner = (
        _normalize_command_tokens(planner_override, context="--planner-command")
        if planner_override is not None
        else goal_role_commands.planner
    )
    worker = (
        _normalize_command_tokens(worker_override, context="--worker-command")
        if worker_override is not None
        else goal_role_commands.worker
    )
    judge = (
        _normalize_command_tokens(judge_override, context="--judge-command")
        if judge_override is not None
        else goal_role_commands.judge
    )
    return RoleCommands(planner=planner, worker=worker, judge=judge)


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

    policy_pack_value = raw.get("policy_pack")
    if isinstance(policy_pack_value, str) and policy_pack_value.strip():
        policy_pack_text = policy_pack_value
    else:
        policy_pack_text = _expect_string(raw, "prune_profile", "goal")

    target_tickets = _expect_string_list(raw, "target_tickets", "goal")
    stop_conditions = _expect_string_list(raw, "stop_conditions", "goal")
    role_commands = _parse_role_commands(raw.get("role_commands"))

    try:
        completion_mode = GoalCompletionMode(completion_mode_text)
    except ValueError as exc:
        raise ValueError(f"goal.completion_mode unsupported value: {completion_mode_text}") from exc
    try:
        policy_pack = PolicyPack(policy_pack_text)
    except ValueError as exc:
        raise ValueError(f"goal.policy_pack unsupported value: {policy_pack_text}") from exc

    if completion_mode == GoalCompletionMode.TARGET_TICKETS_CLOSED and not target_tickets:
        raise ValueError("goal.target_tickets must be non-empty for target_tickets_closed mode.")

    return GoalConfig(
        version=version,
        goal_id=goal_id,
        objective=objective,
        completion_mode=completion_mode,
        target_tickets=target_tickets,
        max_cycles=max_cycles,
        policy_pack=policy_pack,
        stop_conditions=stop_conditions,
        role_commands=role_commands,
    )


def _default_state(goal_id: str) -> RunnerState:
    return RunnerState(
        version=1,
        goal_id=goal_id,
        current_cycle_id=None,
        current_ticket=None,
        pending_feedback_id=None,
        last_consumed_feedback_id=None,
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
    pending_feedback_id_value = raw.get("pending_feedback_id")
    last_consumed_feedback_id_value = raw.get("last_consumed_feedback_id")

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

    if pending_feedback_id_value is None:
        pending_feedback_id: str | None = None
    elif isinstance(pending_feedback_id_value, str) and pending_feedback_id_value.strip():
        pending_feedback_id = pending_feedback_id_value
    else:
        raise ValueError("state.pending_feedback_id must be null or non-empty string.")

    if last_consumed_feedback_id_value is None:
        last_consumed_feedback_id: str | None = None
    elif (
        isinstance(last_consumed_feedback_id_value, str) and last_consumed_feedback_id_value.strip()
    ):
        last_consumed_feedback_id = last_consumed_feedback_id_value
    else:
        raise ValueError("state.last_consumed_feedback_id must be null or non-empty string.")

    if current_cycle_id is None and pending_feedback_id is not None:
        raise ValueError("state.pending_feedback_id cannot be set when no active cycle exists.")

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
        pending_feedback_id=pending_feedback_id,
        last_consumed_feedback_id=last_consumed_feedback_id,
        cycles_started=cycles_started,
        cycles_finalized=cycles_finalized,
        history=history,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")


def _write_state(path: Path, state: RunnerState) -> None:
    _write_json(path, state.to_dict())


def _load_operator_feedback(path: Path) -> OperatorFeedback | None:
    if not path.exists():
        return None
    raw = _read_json_object(path, context="operator feedback")
    version = _expect_int(raw, "version", "operator_feedback")
    if version != 1:
        raise ValueError("operator_feedback.version must be 1.")
    feedback_id = _expect_string(raw, "feedback_id", "operator_feedback")
    target_ticket = _expect_string(raw, "target_ticket", "operator_feedback")
    summary = _expect_string(raw, "summary", "operator_feedback")
    required_planner_action = _expect_string(raw, "required_planner_action", "operator_feedback")
    return OperatorFeedback(
        feedback_id=feedback_id,
        target_ticket=target_ticket,
        summary=summary,
        required_planner_action=required_planner_action,
    )


def _feedback_applies(feedback: OperatorFeedback, ticket_title: str) -> bool:
    return feedback.target_ticket == "*" or feedback.target_ticket == ticket_title


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


def _select_ticket(rows: list[TicketRow], *, selection_policy: SelectionPolicy) -> tuple[int, bool]:
    in_progress = [
        index for index, row in enumerate(rows) if row.status == TicketStatus.IN_PROGRESS
    ]
    if len(in_progress) > 1:
        raise ValueError("tickets.md must contain at most one IN_PROGRESS ticket.")
    if len(in_progress) == 1:
        return in_progress[0], False

    todo_indexes = [index for index, row in enumerate(rows) if row.status == TicketStatus.TODO]
    wip_indexes = [index for index, row in enumerate(rows) if row.status == TicketStatus.WIP]

    if selection_policy == SelectionPolicy.IN_PROGRESS_THEN_TODO:
        if todo_indexes:
            return todo_indexes[0], True
        if wip_indexes:
            return wip_indexes[0], False
    elif selection_policy == SelectionPolicy.TODO_THEN_IN_PROGRESS:
        if wip_indexes:
            return wip_indexes[0], False
        if todo_indexes:
            return todo_indexes[0], True
    else:
        raise ValueError(f"Unsupported selection policy: {selection_policy.value}")

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
    ticket_backend: TicketBackend,
    operator_feedback_path: Path,
    role_commands: RoleCommands,
) -> tuple[RunnerState, str]:
    policy_pack = POLICY_PACKS[goal.policy_pack]
    tickets = ticket_backend.load(tickets_path)
    index, promote = _select_ticket(
        tickets.rows,
        selection_policy=policy_pack.selection_policy,
    )
    rows = list(tickets.rows)

    if promote:
        rows = _replace_status(rows, index, TicketStatus.IN_PROGRESS)
    selected = rows[index]

    cycle_id = _next_cycle_id(cycles_root, goal.goal_id)
    cycle_dir = cycles_root / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)

    operator_feedback = _load_operator_feedback(operator_feedback_path)
    pending_feedback_id: str | None = None
    if (
        operator_feedback is not None
        and _feedback_applies(operator_feedback, selected.task)
        and operator_feedback.feedback_id != state.last_consumed_feedback_id
    ):
        pending_feedback_id = operator_feedback.feedback_id

    cycle_context = {
        "version": 1,
        "generated_at": _utc_now_iso(),
        "goal": {
            "goal_id": goal.goal_id,
            "objective": goal.objective,
            "completion_mode": goal.completion_mode.value,
            "target_tickets": goal.target_tickets,
            "max_cycles": goal.max_cycles,
            "policy_pack": goal.policy_pack.value,
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
        "role_execution": {
            "mode": role_commands.mode(),
            "configured_roles": role_commands.configured_roles(),
        },
    }
    if operator_feedback is not None and pending_feedback_id is not None:
        cycle_context["operator_feedback"] = {
            "feedback_id": operator_feedback.feedback_id,
            "target_ticket": operator_feedback.target_ticket,
            "summary": operator_feedback.summary,
            "required_planner_action": operator_feedback.required_planner_action,
        }
    _write_json(cycle_dir / "cycle_context.json", cycle_context)

    updated_tickets = TicketsDocument(
        prefix_lines=tickets.prefix_lines,
        header_line=tickets.header_line,
        separator_line=tickets.separator_line,
        rows=rows,
        suffix_lines=tickets.suffix_lines,
    )
    ticket_backend.save(tickets_path, updated_tickets)

    new_state = RunnerState(
        version=state.version,
        goal_id=state.goal_id,
        current_cycle_id=cycle_id,
        current_ticket=selected.task,
        pending_feedback_id=pending_feedback_id,
        last_consumed_feedback_id=state.last_consumed_feedback_id,
        cycles_started=state.cycles_started + 1,
        cycles_finalized=state.cycles_finalized,
        history=state.history,
    )
    return new_state, selected.task


def _run_subprocess(
    command: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, env=env)


def _run_checked(command: list[str], *, context: str) -> None:
    result = _run_subprocess(command)
    if result.returncode == 0:
        return
    output = result.stdout.strip()
    if result.stderr.strip():
        output = f"{output}\n{result.stderr.strip()}".strip()
    raise ValueError(f"{context} failed (exit={result.returncode}):\n{output}")


def _next_missing_role(cycle_dir: Path) -> RoleName | None:
    for role, artifact_name in ROLE_SEQUENCE:
        if not (cycle_dir / artifact_name).exists():
            return role
    return None


def _missing_artifacts(cycle_dir: Path) -> list[str]:
    missing: list[str] = []
    for _, artifact_name in ROLE_SEQUENCE:
        if not (cycle_dir / artifact_name).exists():
            missing.append(artifact_name)
    return missing


def _run_role_command(
    *,
    role: RoleName,
    command: tuple[str, ...],
    goal: GoalConfig,
    state: RunnerState,
    cycle_dir: Path,
    tickets_path: Path,
    tickets_backend_kind: TicketBackendKind,
    operator_feedback_path: Path,
) -> None:
    if state.current_cycle_id is None or state.current_ticket is None:
        raise ValueError("No active cycle available for role execution.")

    env = dict(os.environ)
    env["CYCLESMITH_ROLE"] = role.value
    env["CYCLESMITH_GOAL_ID"] = goal.goal_id
    env["CYCLESMITH_CYCLE_ID"] = state.current_cycle_id
    env["CYCLESMITH_CYCLE_DIR"] = str(cycle_dir)
    env["CYCLESMITH_TICKET_TITLE"] = state.current_ticket
    env["CYCLESMITH_TICKETS_PATH"] = str(tickets_path)
    env["CYCLESMITH_TICKETS_BACKEND"] = tickets_backend_kind.value
    env["CYCLESMITH_OPERATOR_FEEDBACK_PATH"] = str(operator_feedback_path)
    if state.pending_feedback_id is not None:
        env["CYCLESMITH_PENDING_FEEDBACK_ID"] = state.pending_feedback_id

    result = _run_subprocess(list(command), env=env)
    if result.returncode == 0:
        print(f"[runner] Executed {role.value} role command for cycle {state.current_cycle_id}.")
        return

    output = result.stdout.strip()
    if result.stderr.strip():
        output = f"{output}\n{result.stderr.strip()}".strip()
    raise ValueError(f"{role.value} role command failed (exit={result.returncode}):\n{output}")


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
    policy_pack = POLICY_PACKS[goal.policy_pack]
    if finalized_count % policy_pack.prune_cadence_cycles != 0:
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
        str(policy_pack.prune_max_cycle_lag),
        "--cycles-root",
        str(cycles_root),
    ]
    if policy_pack.prune_stale_unknown:
        command.append("--stale-unknown")
    if policy_pack.prune_dry_run:
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
    ticket_backend: TicketBackend,
    tickets_backend_kind: TicketBackendKind,
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
            "--tickets-backend",
            tickets_backend_kind.value,
            "--validate-schema",
        ],
        context="cycle artifact validation",
    )

    if state.pending_feedback_id is not None:
        planner_raw = _read_json_object(cycle_dir / "planner.json", context="planner artifact")
        refs = planner_raw.get("operator_feedback_refs")
        if not isinstance(refs, list):
            raise ValueError(
                "planner.operator_feedback_refs must be a list when operator feedback is pending."
            )
        normalized_refs = [ref for ref in refs if isinstance(ref, str)]
        if state.pending_feedback_id not in normalized_refs:
            raise ValueError(
                "planner must acknowledge pending operator feedback via "
                f"operator_feedback_refs containing {state.pending_feedback_id}."
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

    required_follow_up_count = POLICY_PACKS[goal.policy_pack].min_follow_up_tickets
    if transition != TicketStatus.REVIEW and len(follow_ups) < required_follow_up_count:
        raise ValueError(
            "policy pack requires at least "
            f"{required_follow_up_count} follow_up_tickets for non-pass transitions."
        )

    tickets = ticket_backend.load(tickets_path)
    ticket_index = _find_ticket_index(tickets.rows, ticket_title)
    if ticket_index is None:
        raise ValueError(f"Ticket not found in tickets.md: {ticket_title}")

    transitioned_rows = _replace_status(tickets.rows, ticket_index, transition)
    merged_rows, follow_up_added = _merge_follow_ups(transitioned_rows, follow_ups)
    ticket_backend.save(
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
        pending_feedback_id=None,
        last_consumed_feedback_id=(
            state.pending_feedback_id
            if state.pending_feedback_id is not None
            else state.last_consumed_feedback_id
        ),
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
    ticket_backend: TicketBackend,
    tickets_backend_kind: TicketBackendKind,
    operator_feedback_path: Path | None,
    planner_command_override: list[str] | None,
    worker_command_override: list[str] | None,
    judge_command_override: list[str] | None,
    max_actions: int,
) -> int:
    if max_actions <= 0:
        raise ValueError("--max-actions must be > 0.")

    goal = _parse_goal(goal_path)
    role_commands = _resolve_role_commands(
        goal_role_commands=goal.role_commands,
        planner_override=planner_command_override,
        worker_override=worker_command_override,
        judge_override=judge_command_override,
    )
    state = _load_state(state_path, goal.goal_id)
    actions = 0
    resolved_operator_feedback_path = (
        operator_feedback_path
        if operator_feedback_path is not None
        else cycles_root / "operator_feedback.json"
    )

    while actions < max_actions:
        tickets = ticket_backend.load(tickets_path)
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
            pending_role = _next_missing_role(cycle_dir)
            if pending_role is not None:
                role_command = role_commands.for_role(pending_role)
                if role_command is not None:
                    _run_role_command(
                        role=pending_role,
                        command=role_command,
                        goal=goal,
                        state=state,
                        cycle_dir=cycle_dir,
                        tickets_path=tickets_path,
                        tickets_backend_kind=tickets_backend_kind,
                        operator_feedback_path=resolved_operator_feedback_path,
                    )
                    actions += 1
                    continue

                missing_artifacts = _missing_artifacts(cycle_dir)
                print(
                    "[runner] Waiting for role artifacts in "
                    f"{cycle_dir}. Missing: {', '.join(missing_artifacts)}."
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
                ticket_backend=ticket_backend,
                tickets_backend_kind=tickets_backend_kind,
            )
            _write_state(state_path, state)
            actions += 1
            continue

        state, selected_ticket = _start_cycle(
            goal=goal,
            state=state,
            tickets_path=tickets_path,
            cycles_root=cycles_root,
            ticket_backend=ticket_backend,
            operator_feedback_path=resolved_operator_feedback_path,
            role_commands=role_commands,
        )
        _write_state(state_path, state)
        actions += 1
        print(f"[runner] Started cycle {state.current_cycle_id} for ticket: {selected_ticket}")

    tickets = ticket_backend.load(tickets_path)
    print(_status_summary(goal=goal, state=state, rows=tickets.rows))
    return 0


def _init_goal(
    path: Path,
    tickets_path: Path,
    goal_id: str,
    objective: str,
    ticket_backend: TicketBackend,
) -> int:
    tickets = ticket_backend.load(tickets_path)
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
        "policy_pack": PolicyPack.SHARED_BRANCH.value,
        "prune_profile": PolicyPack.SHARED_BRANCH.value,
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
        help="Path to tickets file.",
    )
    run_parser.add_argument(
        "--tickets-backend",
        type=str,
        default=TicketBackendKind.MARKDOWN.value,
        choices=[kind.value for kind in TicketBackendKind],
        help="Ticket backend type.",
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
        "--operator-feedback",
        type=Path,
        default=None,
        help="Optional operator feedback contract path.",
    )
    run_parser.add_argument(
        "--planner-command",
        nargs="+",
        default=None,
        help=(
            "Optional command tokens to execute planner role automatically. "
            "Runner sets CYCLESMITH_* env vars for cycle context."
        ),
    )
    run_parser.add_argument(
        "--worker-command",
        nargs="+",
        default=None,
        help=(
            "Optional command tokens to execute worker role automatically. "
            "Runner sets CYCLESMITH_* env vars for cycle context."
        ),
    )
    run_parser.add_argument(
        "--judge-command",
        nargs="+",
        default=None,
        help=(
            "Optional command tokens to execute judge role automatically. "
            "Runner sets CYCLESMITH_* env vars for cycle context."
        ),
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
        help="Path to tickets file.",
    )
    init_goal_parser.add_argument(
        "--tickets-backend",
        type=str,
        default=TicketBackendKind.MARKDOWN.value,
        choices=[kind.value for kind in TicketBackendKind],
        help="Ticket backend type.",
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
        ticket_backend_kind = TicketBackendKind(args.tickets_backend)
        ticket_backend = resolve_ticket_backend(ticket_backend_kind)

        if args.command == "run":
            return _run_loop(
                goal_path=args.goal,
                state_path=args.state,
                tickets_path=args.tickets,
                cycles_root=args.cycles_root,
                memory_path=args.memory,
                ticket_backend=ticket_backend,
                tickets_backend_kind=ticket_backend_kind,
                operator_feedback_path=args.operator_feedback,
                planner_command_override=args.planner_command,
                worker_command_override=args.worker_command,
                judge_command_override=args.judge_command,
                max_actions=args.max_actions,
            )
        if args.command == "init-goal":
            return _init_goal(
                path=args.goal,
                tickets_path=args.tickets,
                goal_id=args.goal_id,
                objective=args.objective,
                ticket_backend=ticket_backend,
            )
        raise ValueError(f"Unsupported command: {args.command}")
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[runner] ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

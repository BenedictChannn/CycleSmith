from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cyclesmith.dev_loop import run_cycle
from tests.utils import runtime_dir


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_tickets(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    lines = [
        "| Task Type | Task | Description | Status |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {task_type} | {task} | {description} | {status} |"
        for task_type, task, description, status in rows
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _ticket_status_by_title(path: Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped == "| --- | --- | --- | --- |":
            continue
        cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
        if len(cells) != 4 or cells[0] == "Task Type":
            continue
        statuses[cells[1]] = cells[3]
    return statuses


def test_run_cycle_start_then_finalize() -> None:
    with runtime_dir("cyclesmith-runner") as root:
        tickets_path = root / "tickets.md"
        goal_path = root / "reports" / "dev_loop" / "goal.json"
        state_path = root / "reports" / "dev_loop" / "runner_state.json"
        cycles_root = root / "reports" / "dev_loop"
        memory_path = root / "reports" / "dev_loop" / "memory_snapshot.json"

        _write_tickets(
            tickets_path,
            [
                ("FEATURE", "Example in-progress ticket", "Example", "TODO"),
                ("FEATURE", "Example follow-up ticket", "Example", "TODO"),
            ],
        )
        _write_json(
            goal_path,
            {
                "version": 1,
                "goal_id": "smoke-goal",
                "objective": "Run smoke cycle.",
                "completion_mode": "target_tickets_closed",
                "target_tickets": ["Example in-progress ticket"],
                "max_cycles": 10,
                "prune_profile": "shared-branch",
                "stop_conditions": ["manual pause"],
            },
        )
        _write_json(
            memory_path,
            {
                "version": 1,
                "updated_at": "2026-02-13T00:00:00Z",
                "current_focus": "smoke",
                "items": [],
            },
        )

        start_result = run_cycle.main(
            [
                "run",
                "--goal",
                str(goal_path),
                "--state",
                str(state_path),
                "--tickets",
                str(tickets_path),
                "--cycles-root",
                str(cycles_root),
                "--memory",
                str(memory_path),
                "--max-actions",
                "1",
            ]
        )
        assert start_result == 0

        state = json.loads(state_path.read_text(encoding="utf-8"))
        cycle_id = state["current_cycle_id"]
        assert isinstance(cycle_id, str)
        cycle_dir = cycles_root / cycle_id
        assert (cycle_dir / "cycle_context.json").exists()

        _write_json(
            cycle_dir / "planner.json",
            {
                "cycle_id": cycle_id,
                "ticket": {
                    "type": "FEATURE",
                    "title": "Example in-progress ticket",
                    "status_before": "IN_PROGRESS",
                },
                "objective": "Complete smoke ticket.",
                "scope_in": ["src/cyclesmith/dev_loop/run_cycle.py"],
                "scope_out": ["unrelated"],
                "steps": [
                    {
                        "id": "S1",
                        "action": "Implement",
                        "files": ["src/cyclesmith/dev_loop/run_cycle.py"],
                        "validation": ["uv run pytest -q"],
                    }
                ],
                "risks": ["none"],
                "handoff_constraints": ["none"],
                "next_role": "WORKER",
            },
        )
        _write_json(
            cycle_dir / "worker.json",
            {
                "cycle_id": cycle_id,
                "ticket_title": "Example in-progress ticket",
                "step_results": [
                    {
                        "step_id": "S1",
                        "status": "done",
                        "notes": "Implemented.",
                        "files_touched": ["src/cyclesmith/dev_loop/run_cycle.py"],
                        "commands_run": ["uv run pytest -q"],
                    }
                ],
                "checks": {
                    "ruff_check": "pass",
                    "ruff_format": "pass",
                    "ty_check": "pass",
                    "pytest": "pass",
                    "rust_checks": "pass",
                },
                "result_status": "implemented",
                "blockers": [],
                "next_role": "JUDGE",
            },
        )
        _write_json(
            cycle_dir / "judge.json",
            {
                "cycle_id": cycle_id,
                "ticket_title": "Example in-progress ticket",
                "findings": [],
                "qa_verification": [
                    {"command": "uv run pytest -q", "result": "pass", "evidence": "ok"}
                ],
                "verdict": "pass",
                "ticket_transition": "REVIEW",
                "follow_up_tickets": [],
                "next_cycle_focus": "continue",
            },
        )

        finalize_result = run_cycle.main(
            [
                "run",
                "--goal",
                str(goal_path),
                "--state",
                str(state_path),
                "--tickets",
                str(tickets_path),
                "--cycles-root",
                str(cycles_root),
                "--memory",
                str(memory_path),
                "--max-actions",
                "1",
            ]
        )
        assert finalize_result == 0
        statuses = _ticket_status_by_title(tickets_path)
        assert statuses["Example in-progress ticket"] == "REVIEW"

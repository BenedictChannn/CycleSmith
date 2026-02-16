from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from cyclesmith.dev_loop import run_cycle
from tests.utils import runtime_dir


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_tickets_md(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    lines = [
        "| Task Type | Task | Description | Status |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {task_type} | {task} | {description} | {status} |"
        for task_type, task, description, status in rows
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _status_by_title_md(path: Path) -> dict[str, str]:
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


def _valid_worker(cycle_id: str, ticket_title: str) -> dict[str, Any]:
    return {
        "cycle_id": cycle_id,
        "ticket_title": ticket_title,
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
    }


def _valid_judge(cycle_id: str, ticket_title: str) -> dict[str, Any]:
    return {
        "cycle_id": cycle_id,
        "ticket_title": ticket_title,
        "findings": [],
        "qa_verification": [{"command": "uv run pytest -q", "result": "pass", "evidence": "ok"}],
        "verdict": "pass",
        "ticket_transition": "REVIEW",
        "follow_up_tickets": [],
        "next_cycle_focus": "continue",
    }


def _write_role_driver(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "import json\n"
            "import os\n"
            "from pathlib import Path\n\n"
            "role = os.environ['CYCLESMITH_ROLE']\n"
            "cycle_dir = Path(os.environ['CYCLESMITH_CYCLE_DIR'])\n"
            "cycle_id = os.environ['CYCLESMITH_CYCLE_ID']\n"
            "ticket_title = os.environ['CYCLESMITH_TICKET_TITLE']\n"
            "feedback_id = os.environ.get('CYCLESMITH_PENDING_FEEDBACK_ID')\n\n"
            "if role == 'planner':\n"
            "    payload = {\n"
            "        'cycle_id': cycle_id,\n"
            "        'ticket': {\n"
            "            'type': 'CHORE',\n"
            "            'title': ticket_title,\n"
            "            'status_before': 'IN_PROGRESS',\n"
            "        },\n"
            "        'objective': 'Auto plan ticket.',\n"
            "        'scope_in': ['src/cyclesmith/dev_loop/run_cycle.py'],\n"
            "        'scope_out': ['unrelated'],\n"
            "        'steps': [\n"
            "            {\n"
            "                'id': 'S1',\n"
            "                'action': 'Implement',\n"
            "                'files': ['src/cyclesmith/dev_loop/run_cycle.py'],\n"
            "                'validation': ['uv run pytest -q'],\n"
            "            }\n"
            "        ],\n"
            "        'risks': ['none'],\n"
            "        'handoff_constraints': ['none'],\n"
            "        'next_role': 'WORKER',\n"
            "    }\n"
            "    if feedback_id:\n"
            "        payload['operator_feedback_refs'] = [feedback_id]\n"
            "    filename = 'planner.json'\n"
            "elif role == 'worker':\n"
            "    payload = {\n"
            "        'cycle_id': cycle_id,\n"
            "        'ticket_title': ticket_title,\n"
            "        'step_results': [\n"
            "            {\n"
            "                'step_id': 'S1',\n"
            "                'status': 'done',\n"
            "                'notes': 'Implemented.',\n"
            "                'files_touched': ['src/cyclesmith/dev_loop/run_cycle.py'],\n"
            "                'commands_run': ['uv run pytest -q'],\n"
            "            }\n"
            "        ],\n"
            "        'checks': {\n"
            "            'ruff_check': 'pass',\n"
            "            'ruff_format': 'pass',\n"
            "            'ty_check': 'pass',\n"
            "            'pytest': 'pass',\n"
            "            'rust_checks': 'pass',\n"
            "        },\n"
            "        'result_status': 'implemented',\n"
            "        'blockers': [],\n"
            "        'next_role': 'JUDGE',\n"
            "    }\n"
            "    filename = 'worker.json'\n"
            "elif role == 'judge':\n"
            "    payload = {\n"
            "        'cycle_id': cycle_id,\n"
            "        'ticket_title': ticket_title,\n"
            "        'findings': [],\n"
            "        'qa_verification': [\n"
            "            {\n"
            "                'command': 'uv run pytest -q',\n"
            "                'result': 'pass',\n"
            "                'evidence': 'ok',\n"
            "            }\n"
            "        ],\n"
            "        'verdict': 'pass',\n"
            "        'ticket_transition': 'REVIEW',\n"
            "        'follow_up_tickets': [],\n"
            "        'next_cycle_focus': 'continue',\n"
            "    }\n"
            "    filename = 'judge.json'\n"
            "else:\n"
            "    raise ValueError(f'Unsupported role: {role}')\n\n"
            "(cycle_dir / filename).write_text(json.dumps(payload), encoding='utf-8')\n"
        ),
        encoding="utf-8",
    )


def test_run_cycle_can_execute_role_commands_end_to_end() -> None:
    with runtime_dir("cyclesmith-runner-role-commands") as root:
        tickets_path = root / "tickets.md"
        goal_path = root / "reports" / "dev_loop" / "goal.json"
        state_path = root / "reports" / "dev_loop" / "runner_state.json"
        cycles_root = root / "reports" / "dev_loop"
        memory_path = root / "reports" / "dev_loop" / "memory_snapshot.json"
        feedback_path = root / "reports" / "dev_loop" / "operator_feedback.json"
        role_driver = root / "scripts" / "role_driver.py"
        title = "Autonomous command ticket"

        _write_role_driver(role_driver)
        _write_tickets_md(
            tickets_path,
            [
                ("CHORE", title, "Example", "TODO"),
            ],
        )
        _write_json(
            goal_path,
            {
                "version": 1,
                "goal_id": "role-command-goal",
                "objective": "role command test",
                "completion_mode": "target_tickets_closed",
                "target_tickets": [title],
                "max_cycles": 10,
                "policy_pack": "shared-branch",
                "prune_profile": "shared-branch",
                "stop_conditions": ["manual pause"],
                "role_commands": {
                    "planner": [sys.executable, str(role_driver)],
                    "worker": [sys.executable, str(role_driver)],
                    "judge": [sys.executable, str(role_driver)],
                },
            },
        )
        _write_json(
            memory_path,
            {
                "version": 1,
                "updated_at": "2026-02-16T00:00:00Z",
                "current_focus": "smoke",
                "items": [],
            },
        )
        _write_json(
            feedback_path,
            {
                "version": 1,
                "feedback_id": "OFB-AUTO-1",
                "target_ticket": title,
                "summary": "Must be acknowledged by planner.",
                "required_planner_action": "Include ref",
            },
        )

        result = run_cycle.main(
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
                "--operator-feedback",
                str(feedback_path),
                "--max-actions",
                "5",
            ]
        )
        assert result == 0

        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["current_cycle_id"] is None
        assert state["cycles_started"] == 1
        assert state["cycles_finalized"] == 1
        assert state["last_consumed_feedback_id"] == "OFB-AUTO-1"
        assert len(state["history"]) == 1

        cycle_id = state["history"][0]["cycle_id"]
        cycle_dir = cycles_root / cycle_id
        assert (cycle_dir / "planner.json").exists()
        assert (cycle_dir / "worker.json").exists()
        assert (cycle_dir / "judge.json").exists()
        assert (cycle_dir / "runner_sync.json").exists()

        cycle_context = json.loads((cycle_dir / "cycle_context.json").read_text(encoding="utf-8"))
        assert cycle_context["role_execution"]["mode"] == "command"
        assert cycle_context["role_execution"]["configured_roles"] == [
            "planner",
            "worker",
            "judge",
        ]

        statuses = _status_by_title_md(tickets_path)
        assert statuses[title] == "REVIEW"


def test_run_cycle_enforces_operator_feedback_consumption() -> None:
    with runtime_dir("cyclesmith-runner-feedback") as root:
        tickets_path = root / "tickets.md"
        goal_path = root / "reports" / "dev_loop" / "goal.json"
        state_path = root / "reports" / "dev_loop" / "runner_state.json"
        cycles_root = root / "reports" / "dev_loop"
        memory_path = root / "reports" / "dev_loop" / "memory_snapshot.json"
        feedback_path = root / "reports" / "dev_loop" / "operator_feedback.json"
        title = "Feedback-aware ticket"

        _write_tickets_md(
            tickets_path,
            [
                ("CHORE", title, "Example", "TODO"),
                ("FEATURE", "Spare ticket", "Example", "TODO"),
            ],
        )
        _write_json(
            goal_path,
            {
                "version": 1,
                "goal_id": "feedback-goal",
                "objective": "feedback test",
                "completion_mode": "target_tickets_closed",
                "target_tickets": [title],
                "max_cycles": 10,
                "policy_pack": "shared-branch",
                "prune_profile": "shared-branch",
                "stop_conditions": ["manual pause"],
            },
        )
        _write_json(
            memory_path,
            {
                "version": 1,
                "updated_at": "2026-02-16T00:00:00Z",
                "current_focus": "smoke",
                "items": [],
            },
        )
        _write_json(
            feedback_path,
            {
                "version": 1,
                "feedback_id": "OFB-1",
                "target_ticket": title,
                "summary": "must be acknowledged",
                "required_planner_action": "include ref",
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
                "--operator-feedback",
                str(feedback_path),
                "--max-actions",
                "1",
            ]
        )
        assert start_result == 0

        state = json.loads(state_path.read_text(encoding="utf-8"))
        cycle_id = state["current_cycle_id"]
        cycle_dir = cycles_root / cycle_id
        assert state["pending_feedback_id"] == "OFB-1"

        _write_json(
            cycle_dir / "planner.json",
            {
                "cycle_id": cycle_id,
                "ticket": {
                    "type": "CHORE",
                    "title": title,
                    "status_before": "IN_PROGRESS",
                },
                "objective": "Implement",
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
        _write_json(cycle_dir / "worker.json", _valid_worker(cycle_id, title))
        _write_json(cycle_dir / "judge.json", _valid_judge(cycle_id, title))

        finalize_without_ack = run_cycle.main(
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
                "--operator-feedback",
                str(feedback_path),
                "--max-actions",
                "1",
            ]
        )
        assert finalize_without_ack == 1

        planner = json.loads((cycle_dir / "planner.json").read_text(encoding="utf-8"))
        planner["operator_feedback_refs"] = ["OFB-1"]
        _write_json(cycle_dir / "planner.json", planner)

        finalize_with_ack = run_cycle.main(
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
                "--operator-feedback",
                str(feedback_path),
                "--max-actions",
                "1",
            ]
        )
        assert finalize_with_ack == 0

        updated_state = json.loads(state_path.read_text(encoding="utf-8"))
        assert updated_state["last_consumed_feedback_id"] == "OFB-1"
        assert updated_state["pending_feedback_id"] is None
        statuses = _status_by_title_md(tickets_path)
        assert statuses[title] == "REVIEW"


def test_run_cycle_supports_json_ticket_backend() -> None:
    with runtime_dir("cyclesmith-runner-json") as root:
        tickets_path = root / "tickets.json"
        goal_path = root / "reports" / "dev_loop" / "goal.json"
        state_path = root / "reports" / "dev_loop" / "runner_state.json"
        cycles_root = root / "reports" / "dev_loop"
        memory_path = root / "reports" / "dev_loop" / "memory_snapshot.json"
        title = "JSON backend ticket"

        _write_json(
            tickets_path,
            {
                "version": 1,
                "tickets": [
                    {
                        "task_type": "CHORE",
                        "task": title,
                        "description": "Example",
                        "status": "TODO",
                    },
                    {
                        "task_type": "FEATURE",
                        "task": "Another ticket",
                        "description": "Example",
                        "status": "TODO",
                    },
                ],
            },
        )
        _write_json(
            goal_path,
            {
                "version": 1,
                "goal_id": "json-goal",
                "objective": "json backend test",
                "completion_mode": "target_tickets_closed",
                "target_tickets": [title],
                "max_cycles": 10,
                "policy_pack": "shared-branch",
                "prune_profile": "shared-branch",
                "stop_conditions": ["manual pause"],
            },
        )
        _write_json(
            memory_path,
            {
                "version": 1,
                "updated_at": "2026-02-16T00:00:00Z",
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
                "--tickets-backend",
                "json",
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
        cycle_dir = cycles_root / cycle_id

        _write_json(
            cycle_dir / "planner.json",
            {
                "cycle_id": cycle_id,
                "ticket": {
                    "type": "CHORE",
                    "title": title,
                    "status_before": "IN_PROGRESS",
                },
                "objective": "Implement",
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
        _write_json(cycle_dir / "worker.json", _valid_worker(cycle_id, title))
        _write_json(cycle_dir / "judge.json", _valid_judge(cycle_id, title))

        finalize_result = run_cycle.main(
            [
                "run",
                "--goal",
                str(goal_path),
                "--state",
                str(state_path),
                "--tickets",
                str(tickets_path),
                "--tickets-backend",
                "json",
                "--cycles-root",
                str(cycles_root),
                "--memory",
                str(memory_path),
                "--max-actions",
                "1",
            ]
        )
        assert finalize_result == 0

        tickets = json.loads(tickets_path.read_text(encoding="utf-8"))
        rows = {row["task"]: row["status"] for row in tickets["tickets"]}
        assert rows[title] == "REVIEW"


def test_fast_local_policy_prefers_wip_when_no_in_progress() -> None:
    with runtime_dir("cyclesmith-runner-policy") as root:
        tickets_path = root / "tickets.md"
        goal_path = root / "reports" / "dev_loop" / "goal.json"
        state_path = root / "reports" / "dev_loop" / "runner_state.json"
        cycles_root = root / "reports" / "dev_loop"
        memory_path = root / "reports" / "dev_loop" / "memory_snapshot.json"

        _write_tickets_md(
            tickets_path,
            [
                ("CHORE", "WIP ticket", "Example", "WIP"),
                ("CHORE", "TODO ticket", "Example", "TODO"),
            ],
        )
        _write_json(
            goal_path,
            {
                "version": 1,
                "goal_id": "policy-goal",
                "objective": "policy test",
                "completion_mode": "target_tickets_closed",
                "target_tickets": ["WIP ticket"],
                "max_cycles": 5,
                "policy_pack": "fast-local",
                "prune_profile": "fast-local",
                "stop_conditions": ["manual pause"],
            },
        )
        _write_json(
            memory_path,
            {
                "version": 1,
                "updated_at": "2026-02-16T00:00:00Z",
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
        assert state["current_ticket"] == "WIP ticket"

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cyclesmith.dev_loop import validate_cycle_artifacts
from tests.utils import runtime_dir


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_validate_artifacts_passes_for_valid_bundle() -> None:
    with runtime_dir("cyclesmith-validate") as root:
        cycle_dir = root / "reports" / "dev_loop" / "cycle-001"
        tickets_path = root / "tickets.md"
        schema_dir = Path(__file__).resolve().parents[1] / "schemas" / "dev_loop"

        tickets_path.write_text(
            "\n".join(
                [
                    "| Task Type | Task | Description | Status |",
                    "| --- | --- | --- | --- |",
                    "| FEATURE | Example in-progress ticket | Example | IN_PROGRESS |",
                ]
            ),
            encoding="utf-8",
        )
        _write_json(
            cycle_dir / "planner.json",
            {
                "cycle_id": "cycle-001",
                "ticket": {
                    "type": "FEATURE",
                    "title": "Example in-progress ticket",
                    "status_before": "IN_PROGRESS",
                },
                "objective": "Validate smoke bundle.",
                "scope_in": ["src/cyclesmith/dev_loop/validate_cycle_artifacts.py"],
                "scope_out": ["unrelated changes"],
                "steps": [
                    {
                        "id": "S1",
                        "action": "Run validator",
                        "files": ["src/cyclesmith/dev_loop/validate_cycle_artifacts.py"],
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
                "cycle_id": "cycle-001",
                "ticket_title": "Example in-progress ticket",
                "step_results": [
                    {
                        "step_id": "S1",
                        "status": "done",
                        "notes": "Ran validation.",
                        "files_touched": ["src/cyclesmith/dev_loop/validate_cycle_artifacts.py"],
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
                "cycle_id": "cycle-001",
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

        result = validate_cycle_artifacts.main(
            [
                "--cycle-dir",
                str(cycle_dir),
                "--tickets",
                str(tickets_path),
                "--validate-schema",
                "--schema-dir",
                str(schema_dir),
            ]
        )
        assert result == 0


def test_validate_artifacts_fails_for_mismatched_step_ids() -> None:
    with runtime_dir("cyclesmith-validate") as root:
        cycle_dir = root / "reports" / "dev_loop" / "cycle-001"
        tickets_path = root / "tickets.md"

        tickets_path.write_text(
            "\n".join(
                [
                    "| Task Type | Task | Description | Status |",
                    "| --- | --- | --- | --- |",
                    "| FEATURE | Example in-progress ticket | Example | IN_PROGRESS |",
                ]
            ),
            encoding="utf-8",
        )
        _write_json(
            cycle_dir / "planner.json",
            {
                "cycle_id": "cycle-001",
                "ticket": {
                    "type": "FEATURE",
                    "title": "Example in-progress ticket",
                    "status_before": "IN_PROGRESS",
                },
                "objective": "Validate smoke bundle.",
                "scope_in": ["src/cyclesmith/dev_loop/validate_cycle_artifacts.py"],
                "scope_out": ["unrelated changes"],
                "steps": [
                    {
                        "id": "S1",
                        "action": "Run validator",
                        "files": ["src/cyclesmith/dev_loop/validate_cycle_artifacts.py"],
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
                "cycle_id": "cycle-001",
                "ticket_title": "Example in-progress ticket",
                "step_results": [
                    {
                        "step_id": "S2",
                        "status": "done",
                        "notes": "Ran validation.",
                        "files_touched": ["src/cyclesmith/dev_loop/validate_cycle_artifacts.py"],
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
                "cycle_id": "cycle-001",
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

        result = validate_cycle_artifacts.main(
            [
                "--cycle-dir",
                str(cycle_dir),
                "--tickets",
                str(tickets_path),
            ]
        )
        assert result == 1

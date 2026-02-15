from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cyclesmith.dev_loop import memory_snapshot
from tests.utils import runtime_dir


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_memory_ingest_then_validate() -> None:
    with runtime_dir("cyclesmith-memory") as root:
        memory_path = root / "reports" / "dev_loop" / "memory_snapshot.json"
        cycle_dir = root / "reports" / "dev_loop" / "cycle-001"

        _write_json(
            memory_path,
            {
                "version": 1,
                "updated_at": "2026-02-13T00:00:00Z",
                "current_focus": "initial",
                "items": [],
            },
        )
        _write_json(
            cycle_dir / "worker.json",
            {
                "cycle_id": "cycle-001",
                "ticket_title": "Example in-progress ticket",
                "step_results": [],
                "checks": {
                    "ruff_check": "pass",
                    "ruff_format": "pass",
                    "ty_check": "pass",
                    "pytest": "pass",
                    "rust_checks": "pass",
                },
                "result_status": "partial",
                "blockers": ["API quota limits"],
                "next_role": "JUDGE",
            },
        )
        _write_json(
            cycle_dir / "judge.json",
            {
                "cycle_id": "cycle-001",
                "ticket_title": "Example in-progress ticket",
                "findings": [
                    {
                        "severity": "high",
                        "where": "src/foo.py:10",
                        "issue": "Regression in parser",
                        "required_action": "Fix parser behavior",
                    }
                ],
                "qa_verification": [],
                "verdict": "rework",
                "ticket_transition": "IN_PROGRESS",
                "follow_up_tickets": [
                    {
                        "task_type": "BUG",
                        "task": "Fix parser regression",
                        "description": "Resolve broken parser behavior.",
                        "status": "TODO",
                    }
                ],
                "next_cycle_focus": "repair parser",
            },
        )

        ingest_result = memory_snapshot.main(
            ["--memory", str(memory_path), "ingest", "--cycle-dir", str(cycle_dir)]
        )
        validate_result = memory_snapshot.main(["--memory", str(memory_path), "validate"])

        updated = _read_json(memory_path)
        assert ingest_result == 0
        assert validate_result == 0
        assert len(updated["items"]) == 3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cyclesmith.dev_loop.ticket_backends import TicketBackendKind
from cyclesmith.dev_loop.workflow_compliance import run_compliance_checks
from tests.utils import runtime_dir


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_tickets(path: Path, ticket_title: str) -> None:
    path.write_text(
        "\n".join(
            [
                "| Task Type | Task | Description | Status |",
                "| --- | --- | --- | --- |",
                f"| CHORE | {ticket_title} | CI and compliance gates | IN_PROGRESS |",
                "| FEATURE | Add operator feedback ingestion for cycle runner | TODO work | TODO |",
            ]
        ),
        encoding="utf-8",
    )


def _write_memory(path: Path) -> None:
    _write_json(
        path,
        {
            "version": 1,
            "updated_at": "2026-02-16T00:00:00Z",
            "current_focus": "self-hosting workflow hardening",
            "items": [],
        },
    )


def _write_cycle(
    cycle_dir: Path,
    ticket_title: str,
    *,
    mismatched_step_ids: bool,
    include_runner_sync: bool,
) -> None:
    _write_json(
        cycle_dir / "planner.json",
        {
            "cycle_id": cycle_dir.name,
            "ticket": {
                "type": "CHORE",
                "title": ticket_title,
                "status_before": "IN_PROGRESS",
            },
            "objective": "Add CI + workflow compliance gate.",
            "scope_in": [
                ".github/workflows/ci.yml",
                "scripts/check_workflow_compliance.py",
                "src/cyclesmith/dev_loop/workflow_compliance.py",
            ],
            "scope_out": ["operator feedback ingestion"],
            "steps": [
                {
                    "id": "S1",
                    "action": "Add CI workflow and compliance checker.",
                    "files": [
                        ".github/workflows/ci.yml",
                        "scripts/check_workflow_compliance.py",
                        "src/cyclesmith/dev_loop/workflow_compliance.py",
                    ],
                    "validation": [
                        "uv run ruff check .",
                        "uv run ty check .",
                        "uv run pytest -q",
                    ],
                }
            ],
            "risks": ["Missing policy coupling could allow bypasses."],
            "handoff_constraints": ["No schema changes in this cycle."],
            "next_role": "WORKER",
        },
    )

    worker_step_id = "S2" if mismatched_step_ids else "S1"
    _write_json(
        cycle_dir / "worker.json",
        {
            "cycle_id": cycle_dir.name,
            "ticket_title": ticket_title,
            "step_results": [
                {
                    "step_id": worker_step_id,
                    "status": "done",
                    "notes": "Implemented CI and checker.",
                    "files_touched": [
                        ".github/workflows/ci.yml",
                        "scripts/check_workflow_compliance.py",
                        "src/cyclesmith/dev_loop/workflow_compliance.py",
                    ],
                    "commands_run": [
                        "uv run ruff check .",
                        "uv run ty check .",
                        "uv run pytest -q",
                    ],
                }
            ],
            "checks": {
                "ruff_check": "pass",
                "ruff_format": "pass",
                "ty_check": "pass",
                "pytest": "pass",
                "rust_checks": "pass",
            },
            "result_status": "partial",
            "blockers": [],
            "next_role": "JUDGE",
        },
    )

    _write_json(
        cycle_dir / "judge.json",
        {
            "cycle_id": cycle_dir.name,
            "ticket_title": ticket_title,
            "findings": [
                {
                    "severity": "medium",
                    "where": ".github/settings",
                    "issue": "Required check configuration is not stored in repo.",
                    "required_action": (
                        "Configure protected branch required checks in GitHub settings."
                    ),
                }
            ],
            "qa_verification": [
                {
                    "command": "uv run pytest -q",
                    "result": "pass",
                    "evidence": "Workflow checker tests pass.",
                }
            ],
            "verdict": "rework",
            "ticket_transition": "IN_PROGRESS",
            "follow_up_tickets": [
                {
                    "task_type": "CHORE",
                    "task": "Configure protected branch required status checks",
                    "description": "Enforce quality + workflow gates in repo settings.",
                    "status": "TODO",
                }
            ],
            "next_cycle_focus": "Finalize branch protection settings and docs.",
        },
    )

    if include_runner_sync:
        _write_json(
            cycle_dir / "runner_sync.json",
            {
                "version": 1,
                "synced_at": "2026-02-16T00:00:00Z",
                "cycle_id": cycle_dir.name,
                "ticket_title": ticket_title,
                "verdict": "rework",
                "ticket_transition": "IN_PROGRESS",
                "follow_up_tickets_added": 1,
                "memory_ingest": True,
                "memory_prune_triggered": False,
                "memory_prune_command": [],
            },
        )


def _run(
    *,
    repo_root: Path,
    changed_paths: list[str],
) -> list[str]:
    return run_compliance_checks(
        repo_root=repo_root,
        changed_paths=changed_paths,
        tickets_path=repo_root / "tickets.md",
        tickets_backend_kind=TicketBackendKind.MARKDOWN,
        cycles_root=repo_root / "reports" / "dev_loop",
        memory_path=repo_root / "reports" / "dev_loop" / "memory_snapshot.json",
        schema_dir=Path(__file__).resolve().parents[1] / "schemas" / "dev_loop",
    )


def test_compliance_passes_for_valid_cycle_backed_change() -> None:
    with runtime_dir("cyclesmith-compliance") as root:
        ticket_title = "Add CI workflow for lint, type, and smoke tests"
        cycle_id = "20260216-selfhost-ci-01"
        cycle_dir = root / "reports" / "dev_loop" / cycle_id

        _write_tickets(root / "tickets.md", ticket_title)
        _write_memory(root / "reports" / "dev_loop" / "memory_snapshot.json")
        _write_cycle(
            cycle_dir,
            ticket_title,
            mismatched_step_ids=False,
            include_runner_sync=True,
        )

        errors = _run(
            repo_root=root,
            changed_paths=[
                "src/cyclesmith/cli.py",
                "tickets.md",
                f"reports/dev_loop/{cycle_id}/planner.json",
                f"reports/dev_loop/{cycle_id}/worker.json",
                f"reports/dev_loop/{cycle_id}/judge.json",
                f"reports/dev_loop/{cycle_id}/runner_sync.json",
                "reports/dev_loop/memory_snapshot.json",
            ],
        )
        assert errors == []


def test_compliance_fails_when_runner_sync_missing() -> None:
    with runtime_dir("cyclesmith-compliance") as root:
        ticket_title = "Add CI workflow for lint, type, and smoke tests"
        cycle_id = "20260216-selfhost-ci-01"
        cycle_dir = root / "reports" / "dev_loop" / cycle_id

        _write_tickets(root / "tickets.md", ticket_title)
        _write_memory(root / "reports" / "dev_loop" / "memory_snapshot.json")
        _write_cycle(
            cycle_dir,
            ticket_title,
            mismatched_step_ids=False,
            include_runner_sync=False,
        )

        errors = _run(
            repo_root=root,
            changed_paths=[
                "src/cyclesmith/cli.py",
                "tickets.md",
                f"reports/dev_loop/{cycle_id}/planner.json",
                f"reports/dev_loop/{cycle_id}/worker.json",
                f"reports/dev_loop/{cycle_id}/judge.json",
                "reports/dev_loop/memory_snapshot.json",
            ],
        )
        assert any("runner_sync.json" in error for error in errors)


def test_compliance_fails_when_validator_fails() -> None:
    with runtime_dir("cyclesmith-compliance") as root:
        ticket_title = "Add CI workflow for lint, type, and smoke tests"
        cycle_id = "20260216-selfhost-ci-01"
        cycle_dir = root / "reports" / "dev_loop" / cycle_id

        _write_tickets(root / "tickets.md", ticket_title)
        _write_memory(root / "reports" / "dev_loop" / "memory_snapshot.json")
        _write_cycle(
            cycle_dir,
            ticket_title,
            mismatched_step_ids=True,
            include_runner_sync=True,
        )

        errors = _run(
            repo_root=root,
            changed_paths=[
                "src/cyclesmith/cli.py",
                "tickets.md",
                f"reports/dev_loop/{cycle_id}/planner.json",
                f"reports/dev_loop/{cycle_id}/worker.json",
                f"reports/dev_loop/{cycle_id}/judge.json",
                f"reports/dev_loop/{cycle_id}/runner_sync.json",
                "reports/dev_loop/memory_snapshot.json",
            ],
        )
        assert any("artifact validator failed" in error for error in errors)


def test_compliance_fails_when_tickets_not_changed() -> None:
    with runtime_dir("cyclesmith-compliance") as root:
        ticket_title = "Add CI workflow for lint, type, and smoke tests"
        cycle_id = "20260216-selfhost-ci-01"
        cycle_dir = root / "reports" / "dev_loop" / cycle_id

        _write_tickets(root / "tickets.md", ticket_title)
        _write_memory(root / "reports" / "dev_loop" / "memory_snapshot.json")
        _write_cycle(
            cycle_dir,
            ticket_title,
            mismatched_step_ids=False,
            include_runner_sync=True,
        )

        errors = _run(
            repo_root=root,
            changed_paths=[
                "src/cyclesmith/cli.py",
                f"reports/dev_loop/{cycle_id}/planner.json",
                f"reports/dev_loop/{cycle_id}/worker.json",
                f"reports/dev_loop/{cycle_id}/judge.json",
                f"reports/dev_loop/{cycle_id}/runner_sync.json",
                "reports/dev_loop/memory_snapshot.json",
            ],
        )
        assert any("tickets.md" in error for error in errors)


def test_compliance_fails_when_cycle_changes_without_memory_update() -> None:
    with runtime_dir("cyclesmith-compliance") as root:
        ticket_title = "Add CI workflow for lint, type, and smoke tests"
        cycle_id = "20260216-selfhost-ci-01"
        cycle_dir = root / "reports" / "dev_loop" / cycle_id

        _write_tickets(root / "tickets.md", ticket_title)
        _write_memory(root / "reports" / "dev_loop" / "memory_snapshot.json")
        _write_cycle(
            cycle_dir,
            ticket_title,
            mismatched_step_ids=False,
            include_runner_sync=True,
        )

        errors = _run(
            repo_root=root,
            changed_paths=[
                "src/cyclesmith/cli.py",
                "tickets.md",
                f"reports/dev_loop/{cycle_id}/planner.json",
                f"reports/dev_loop/{cycle_id}/worker.json",
                f"reports/dev_loop/{cycle_id}/judge.json",
                f"reports/dev_loop/{cycle_id}/runner_sync.json",
            ],
        )
        assert any("memory snapshot updates" in error for error in errors)


def test_compliance_allows_maintenance_only_changes() -> None:
    with runtime_dir("cyclesmith-compliance") as root:
        errors = _run(
            repo_root=root,
            changed_paths=[
                "reports/dev_loop/strict_report.json",
                "uv.lock",
            ],
        )
        assert errors == []


def test_compliance_fails_without_runner_cycle_for_non_maintenance_changes() -> None:
    with runtime_dir("cyclesmith-compliance") as root:
        ticket_title = "Add CI workflow for lint, type, and smoke tests"
        _write_tickets(root / "tickets.md", ticket_title)
        _write_memory(root / "reports" / "dev_loop" / "memory_snapshot.json")

        errors = _run(
            repo_root=root,
            changed_paths=[
                "src/cyclesmith/cli.py",
                "tickets.md",
            ],
        )
        assert any("touched finalized runner cycle directory" in error for error in errors)

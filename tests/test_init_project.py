from __future__ import annotations

from cyclesmith.init_project import initialize_project
from tests.utils import runtime_dir


def test_initialize_project_creates_expected_files() -> None:
    with runtime_dir("cyclesmith-init") as tmp_path:
        summary = initialize_project(target=tmp_path, force=False)
        assert summary.created_count > 0
        assert summary.skipped_count == 0
        assert (tmp_path / ".githooks" / "pre-commit").exists()
        assert (tmp_path / "docs" / "autonomy-lite" / "operator_runbook.md").exists()
        assert (tmp_path / "schemas" / "dev_loop" / "planner.schema.json").exists()
        assert (tmp_path / "reports" / "dev_loop" / "example_cycle" / "planner.json").exists()


def test_initialize_project_skips_existing_without_force() -> None:
    with runtime_dir("cyclesmith-init") as tmp_path:
        (tmp_path / ".githooks").mkdir(parents=True, exist_ok=True)
        precommit_path = tmp_path / ".githooks" / "pre-commit"
        precommit_path.write_text("custom\n", encoding="utf-8")

        summary = initialize_project(target=tmp_path, force=False)
        assert summary.skipped_count >= 1
        assert precommit_path.read_text(encoding="utf-8") == "custom\n"


def test_initialize_project_overwrites_existing_with_force() -> None:
    with runtime_dir("cyclesmith-init") as tmp_path:
        (tmp_path / ".githooks").mkdir(parents=True, exist_ok=True)
        precommit_path = tmp_path / ".githooks" / "pre-commit"
        precommit_path.write_text("custom\n", encoding="utf-8")

        summary = initialize_project(target=tmp_path, force=True)
        assert summary.created_count > 0
        assert "cyclesmith.cli enforce-ticket-loop" in precommit_path.read_text(encoding="utf-8")

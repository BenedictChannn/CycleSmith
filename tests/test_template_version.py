from __future__ import annotations

import json

import pytest

from cyclesmith import cli
from cyclesmith.init_project import initialize_project
from cyclesmith.template_version import (
    TemplateStatus,
    assess_template_status,
    template_metadata_path,
)
from tests.utils import runtime_dir


def test_template_status_not_initialized() -> None:
    with runtime_dir("cyclesmith-template-status") as root:
        report = assess_template_status(repo_root=root)
        assert report.status == TemplateStatus.NOT_INITIALIZED
        assert report.repo_template_version is None


def test_template_status_up_to_date_after_init() -> None:
    with runtime_dir("cyclesmith-template-status") as root:
        initialize_project(target=root, force=False)
        report = assess_template_status(repo_root=root)
        assert report.status == TemplateStatus.UP_TO_DATE
        assert report.sync_mode is not None


def test_template_status_partial_sync_when_files_skipped() -> None:
    with runtime_dir("cyclesmith-template-status") as root:
        hook_path = root / ".githooks" / "pre-commit"
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        hook_path.write_text("custom\n", encoding="utf-8")
        initialize_project(target=root, force=False)
        report = assess_template_status(repo_root=root)
        assert report.status == TemplateStatus.PARTIAL_SYNC


def test_template_status_reports_upgrade_available() -> None:
    with runtime_dir("cyclesmith-template-status") as root:
        initialize_project(target=root, force=False)
        metadata_path = template_metadata_path(root)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["template_version"] = "0.0.1"
        metadata["sync_mode"] = "full"
        metadata_path.write_text(f"{json.dumps(metadata, indent=2)}\n", encoding="utf-8")

        report = assess_template_status(repo_root=root)
        assert report.status == TemplateStatus.UPGRADE_AVAILABLE


def test_template_status_cli_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    with runtime_dir("cyclesmith-template-status-cli") as root:
        initialize_project(target=root, force=False)
        result = cli.main(["template-status", "--repo-root", str(root), "--json"])
        assert result == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["status"] == TemplateStatus.UP_TO_DATE.value

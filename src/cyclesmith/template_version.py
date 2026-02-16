"""Template version metadata and upgrade status helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from cyclesmith import __version__

TEMPLATE_METADATA_SCHEMA_VERSION = 1
TEMPLATE_METADATA_RELATIVE_PATH = Path(".cyclesmith") / "template_version.json"
CURRENT_TEMPLATE_VERSION = __version__


class TemplateSyncMode(StrEnum):
    FULL = "full"
    PARTIAL = "partial"


class TemplateStatus(StrEnum):
    NOT_INITIALIZED = "not_initialized"
    PARTIAL_SYNC = "partial_sync"
    UP_TO_DATE = "up_to_date"
    UPGRADE_AVAILABLE = "upgrade_available"
    LOCAL_AHEAD = "local_ahead"
    VERSION_MISMATCH = "version_mismatch"


@dataclass(frozen=True)
class TemplateMetadata:
    version: int
    template_version: str
    toolkit_version: str
    updated_at: str
    sync_mode: TemplateSyncMode

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "template_version": self.template_version,
            "toolkit_version": self.toolkit_version,
            "updated_at": self.updated_at,
            "sync_mode": self.sync_mode.value,
        }


@dataclass(frozen=True)
class TemplateStatusReport:
    status: TemplateStatus
    repo_root: Path
    metadata_path: Path
    current_template_version: str
    repo_template_version: str | None
    sync_mode: TemplateSyncMode | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "repo_root": self.repo_root.as_posix(),
            "metadata_path": self.metadata_path.as_posix(),
            "current_template_version": self.current_template_version,
            "repo_template_version": self.repo_template_version,
            "sync_mode": self.sync_mode.value if self.sync_mode is not None else None,
            "message": self.message,
        }


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def template_metadata_path(repo_root: Path) -> Path:
    return repo_root / TEMPLATE_METADATA_RELATIVE_PATH


def write_template_metadata(*, repo_root: Path, sync_mode: TemplateSyncMode) -> TemplateMetadata:
    metadata = TemplateMetadata(
        version=TEMPLATE_METADATA_SCHEMA_VERSION,
        template_version=CURRENT_TEMPLATE_VERSION,
        toolkit_version=__version__,
        updated_at=_utc_now_iso(),
        sync_mode=sync_mode,
    )
    metadata_path = template_metadata_path(repo_root)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(f"{json.dumps(metadata.to_dict(), indent=2)}\n", encoding="utf-8")
    return metadata


def _expect_non_empty_string(payload: dict[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string.")
    return value


def load_template_metadata(*, repo_root: Path) -> TemplateMetadata | None:
    metadata_path = template_metadata_path(repo_root)
    if not metadata_path.exists():
        return None

    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("template metadata root must be an object.")

    version = raw.get("version")
    if version != TEMPLATE_METADATA_SCHEMA_VERSION:
        raise ValueError(
            "template metadata version must be "
            f"{TEMPLATE_METADATA_SCHEMA_VERSION}, found {version}."
        )
    template_version = _expect_non_empty_string(raw, "template_version", "template_metadata")
    toolkit_version = _expect_non_empty_string(raw, "toolkit_version", "template_metadata")
    updated_at = _expect_non_empty_string(raw, "updated_at", "template_metadata")
    sync_mode_text = _expect_non_empty_string(raw, "sync_mode", "template_metadata")
    try:
        sync_mode = TemplateSyncMode(sync_mode_text)
    except ValueError as exc:
        raise ValueError(
            f"template_metadata.sync_mode unsupported value: {sync_mode_text}"
        ) from exc

    return TemplateMetadata(
        version=version,
        template_version=template_version,
        toolkit_version=toolkit_version,
        updated_at=updated_at,
        sync_mode=sync_mode,
    )


def _parse_version(value: str) -> tuple[int, ...] | None:
    parts = value.split(".")
    parsed: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        parsed.append(int(part))
    return tuple(parsed)


def _compare_versions(left: str, right: str) -> int | None:
    left_parts = _parse_version(left)
    right_parts = _parse_version(right)
    if left_parts is None or right_parts is None:
        return None
    max_len = max(len(left_parts), len(right_parts))
    left_norm = left_parts + (0,) * (max_len - len(left_parts))
    right_norm = right_parts + (0,) * (max_len - len(right_parts))
    if left_norm < right_norm:
        return -1
    if left_norm > right_norm:
        return 1
    return 0


def assess_template_status(*, repo_root: Path) -> TemplateStatusReport:
    metadata_path = template_metadata_path(repo_root)
    metadata = load_template_metadata(repo_root=repo_root)
    if metadata is None:
        return TemplateStatusReport(
            status=TemplateStatus.NOT_INITIALIZED,
            repo_root=repo_root,
            metadata_path=metadata_path,
            current_template_version=CURRENT_TEMPLATE_VERSION,
            repo_template_version=None,
            sync_mode=None,
            message=(
                "Template metadata missing. Run `cyclesmith init --target .` to initialize "
                "or upgrade repo templates."
            ),
        )

    if metadata.sync_mode == TemplateSyncMode.PARTIAL:
        return TemplateStatusReport(
            status=TemplateStatus.PARTIAL_SYNC,
            repo_root=repo_root,
            metadata_path=metadata_path,
            current_template_version=CURRENT_TEMPLATE_VERSION,
            repo_template_version=metadata.template_version,
            sync_mode=metadata.sync_mode,
            message=(
                "Template sync is partial. Re-run `cyclesmith init --target . --force` "
                "to apply full template updates."
            ),
        )

    comparison = _compare_versions(metadata.template_version, CURRENT_TEMPLATE_VERSION)
    if comparison == 0:
        status = TemplateStatus.UP_TO_DATE
        message = "Repository template version matches current CycleSmith template version."
    elif comparison is not None and comparison < 0:
        status = TemplateStatus.UPGRADE_AVAILABLE
        message = (
            "Repository template version is behind current CycleSmith templates. "
            "Run `cyclesmith init --target . --force` in a feature branch."
        )
    elif comparison is not None and comparison > 0:
        status = TemplateStatus.LOCAL_AHEAD
        message = (
            "Repository template version is newer than this toolkit build. "
            "Upgrade your local CycleSmith package."
        )
    else:
        status = TemplateStatus.VERSION_MISMATCH
        message = (
            "Template versions cannot be ordered automatically. "
            "Review metadata and update manually if needed."
        )

    return TemplateStatusReport(
        status=status,
        repo_root=repo_root,
        metadata_path=metadata_path,
        current_template_version=CURRENT_TEMPLATE_VERSION,
        repo_template_version=metadata.template_version,
        sync_mode=metadata.sync_mode,
        message=message,
    )

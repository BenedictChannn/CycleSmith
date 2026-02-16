"""Initialize a repository with CycleSmith templates."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from cyclesmith.template_version import (
    CURRENT_TEMPLATE_VERSION,
    TEMPLATE_METADATA_RELATIVE_PATH,
    TemplateSyncMode,
    write_template_metadata,
)


@dataclass(frozen=True)
class InitSummary:
    """Summary of files written or skipped during initialization.

    Attributes:
        created_count: Number of files written.
        skipped_count: Number of existing files skipped.
        target_root: Target repository path initialized.
        template_version: Version of the template bundle written to metadata.
        sync_mode: Whether initialization was full or partial.
        metadata_path: Path to template metadata file.
    """

    created_count: int
    skipped_count: int
    target_root: Path
    template_version: str
    sync_mode: TemplateSyncMode
    metadata_path: Path


def _iter_template_files(
    template_root: Traversable,
    relative_root: Path = Path(),
) -> list[tuple[Traversable, Path]]:
    files: list[tuple[Traversable, Path]] = []
    for child in template_root.iterdir():
        relative_path = relative_root / child.name
        if child.is_file():
            files.append((child, relative_path))
            continue
        files.extend(_iter_template_files(child, relative_path))
    return sorted(files, key=lambda item: str(item[1]))


def _copy_template_tree(
    *, template_root: Traversable, target_root: Path, force: bool
) -> tuple[int, int]:
    created_count = 0
    skipped_count = 0

    for source_file, relative_path in _iter_template_files(template_root):
        destination = target_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not force:
            skipped_count += 1
            continue
        destination.write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")
        created_count += 1

    return created_count, skipped_count


def initialize_project(*, target: Path, force: bool) -> InitSummary:
    """Copy bundled templates into the target repository.

    Args:
        target: Repository path to initialize.
        force: Whether to overwrite files that already exist.

    Returns:
        A summary describing created and skipped files.
    """
    target_root = target.resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    template_root = resources.files("cyclesmith.templates").joinpath("project")
    try:
        # Validate template availability before copy.
        next(template_root.iterdir())
    except StopIteration:
        raise FileNotFoundError("CycleSmith template package directory is empty.") from None

    created_count, skipped_count = _copy_template_tree(
        template_root=template_root,
        target_root=target_root,
        force=force,
    )

    sync_mode = TemplateSyncMode.FULL if skipped_count == 0 else TemplateSyncMode.PARTIAL
    write_template_metadata(repo_root=target_root, sync_mode=sync_mode)

    return InitSummary(
        created_count=created_count,
        skipped_count=skipped_count,
        target_root=target_root,
        template_version=CURRENT_TEMPLATE_VERSION,
        sync_mode=sync_mode,
        metadata_path=target_root / TEMPLATE_METADATA_RELATIVE_PATH,
    )

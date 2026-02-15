"""Manage durable dev-loop memory snapshots.

This script provides two operations:

- `validate`: verify snapshot schema and invariants.
- `ingest`: merge durable signals from cycle artifacts into memory.
- `prune-stale`: mark old active items as stale based on cycle lag.
- `ingest-batch`: replay multiple cycle updates deterministically.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class MemoryKind(StrEnum):
    DECISION = "decision"
    RISK = "risk"
    REGRESSION = "regression"
    ENVIRONMENT = "environment"
    OPPORTUNITY = "opportunity"
    TODO_HINT = "todo_hint"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    STALE = "stale"


class MemoryConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


CONFIDENCE_RANK: dict[MemoryConfidence, int] = {
    MemoryConfidence.LOW: 1,
    MemoryConfidence.MEDIUM: 2,
    MemoryConfidence.HIGH: 3,
}


@dataclass(frozen=True)
class MemoryItem:
    id: str
    title: str
    kind: MemoryKind
    status: MemoryStatus
    confidence: MemoryConfidence
    detail: str
    source_cycle: str
    source_file: str
    last_verified_cycle: str
    tags: list[str]

    def key(self) -> tuple[MemoryKind, str]:
        return (self.kind, self.title.strip().lower())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind.value,
            "status": self.status.value,
            "confidence": self.confidence.value,
            "detail": self.detail,
            "source_cycle": self.source_cycle,
            "source_file": self.source_file,
            "last_verified_cycle": self.last_verified_cycle,
            "tags": self.tags,
        }


@dataclass(frozen=True)
class MemorySnapshot:
    version: int
    updated_at: str
    current_focus: str
    items: list[MemoryItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "current_focus": self.current_focus,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class CandidateItem:
    title: str
    kind: MemoryKind
    confidence: MemoryConfidence
    detail: str
    source_cycle: str
    source_file: str
    tags: list[str]

    def key(self) -> tuple[MemoryKind, str]:
        return (self.kind, self.title.strip().lower())


class StrictErrorCode(StrEnum):
    SELECTION_FAILURE = "selection_failure"
    SCHEMA_FAILURE = "schema_failure"


@dataclass(frozen=True)
class StrictFailure:
    cycle_dir: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "cycle_dir": self.cycle_dir,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StrictBatchReport:
    generated_at: str
    code: StrictErrorCode
    message: str
    cycles_root: str
    requested_cycle_dirs: list[str]
    failures: list[StrictFailure]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "command": "ingest-batch",
            "strict": True,
            "generated_at": self.generated_at,
            "error_code": self.code.value,
            "message": self.message,
            "cycles_root": self.cycles_root,
            "requested_cycle_dirs": self.requested_cycle_dirs,
            "failures": [failure.to_dict() for failure in self.failures],
        }


class StrictBatchError(ValueError):
    """Raised when strict ingest-batch validation fails."""

    def __init__(
        self,
        *,
        code: StrictErrorCode,
        message: str,
        failures: list[StrictFailure],
    ) -> None:
        super().__init__(message)
        self.code = code
        self.failures = failures


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json_object(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def _expect_string(
    obj: dict[str, Any],
    key: str,
    context: str,
) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string.")
    return value


def _expect_string_list(
    obj: dict[str, Any],
    key: str,
    context: str,
) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{context}.{key} must be a list.")
    strings: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{context}.{key}[{index}] must be a non-empty string.")
        strings.append(item)
    return strings


def _parse_memory_item(item: dict[str, Any], index: int) -> MemoryItem:
    context = f"memory.items[{index}]"
    item_id = _expect_string(item, "id", context)
    if re.fullmatch(r"MEM-\d{4}", item_id) is None:
        raise ValueError(f"{context}.id must match pattern MEM-####.")

    title = _expect_string(item, "title", context)
    detail = _expect_string(item, "detail", context)
    source_cycle = _expect_string(item, "source_cycle", context)
    source_file = _expect_string(item, "source_file", context)
    last_verified_cycle = _expect_string(item, "last_verified_cycle", context)
    tags = _expect_string_list(item, "tags", context)

    kind_text = _expect_string(item, "kind", context)
    status_text = _expect_string(item, "status", context)
    confidence_text = _expect_string(item, "confidence", context)

    try:
        kind = MemoryKind(kind_text)
    except ValueError as exc:
        raise ValueError(f"{context}.kind has unsupported value: {kind_text}") from exc
    try:
        status = MemoryStatus(status_text)
    except ValueError as exc:
        raise ValueError(f"{context}.status has unsupported value: {status_text}") from exc
    try:
        confidence = MemoryConfidence(confidence_text)
    except ValueError as exc:
        raise ValueError(f"{context}.confidence has unsupported value: {confidence_text}") from exc

    return MemoryItem(
        id=item_id,
        title=title,
        kind=kind,
        status=status,
        confidence=confidence,
        detail=detail,
        source_cycle=source_cycle,
        source_file=source_file,
        last_verified_cycle=last_verified_cycle,
        tags=tags,
    )


def _parse_snapshot(path: Path) -> MemorySnapshot:
    raw = _read_json_object(path)
    version = raw.get("version")
    if not isinstance(version, int):
        raise ValueError("memory.version must be an integer.")
    if version != 1:
        raise ValueError(f"memory.version must be 1, found {version}.")

    updated_at = _expect_string(raw, "updated_at", "memory")
    current_focus = _expect_string(raw, "current_focus", "memory")

    items_value = raw.get("items")
    if not isinstance(items_value, list):
        raise ValueError("memory.items must be a list.")

    items: list[MemoryItem] = []
    seen_ids: set[str] = set()
    seen_keys: set[tuple[MemoryKind, str]] = set()
    for index, item_value in enumerate(items_value):
        if not isinstance(item_value, dict):
            raise ValueError(f"memory.items[{index}] must be an object.")
        item = _parse_memory_item(item_value, index)
        if item.id in seen_ids:
            raise ValueError(f"memory.items has duplicate id: {item.id}")
        if item.key() in seen_keys:
            raise ValueError(
                f"memory.items has duplicate semantic key: {item.kind.value}:{item.title}"
            )
        seen_ids.add(item.id)
        seen_keys.add(item.key())
        items.append(item)

    return MemorySnapshot(
        version=version,
        updated_at=updated_at,
        current_focus=current_focus,
        items=items,
    )


def _empty_snapshot(focus: str) -> MemorySnapshot:
    return MemorySnapshot(
        version=1,
        updated_at=_utc_now_iso(),
        current_focus=focus,
        items=[],
    )


def _next_memory_id(items: list[MemoryItem]) -> str:
    max_seen = 0
    for item in items:
        match = re.fullmatch(r"MEM-(\d{4})", item.id)
        if match is None:
            continue
        max_seen = max(max_seen, int(match.group(1)))
    return f"MEM-{max_seen + 1:04d}"


def _higher_confidence(
    left: MemoryConfidence,
    right: MemoryConfidence,
) -> MemoryConfidence:
    return left if CONFIDENCE_RANK[left] >= CONFIDENCE_RANK[right] else right


def _dedup_tags(tags: list[str]) -> list[str]:
    deduped = sorted({tag.strip() for tag in tags if tag.strip()})
    return deduped


def _ordered_known_cycles(cycles_root: Path) -> list[str]:
    """Return known cycle ids sorted oldest to newest.

    Args:
        cycles_root: Root directory containing cycle subdirectories.

    Returns:
        Sorted cycle-id list (oldest first).
    """
    if not cycles_root.exists() or not cycles_root.is_dir():
        raise ValueError(f"cycles_root does not exist or is not a directory: {cycles_root}")

    cycle_names = [path.name for path in cycles_root.iterdir() if path.is_dir()]
    return sorted(cycle_names)


def _load_cycle_file(cycle_dir: Path, filename: str) -> dict[str, Any]:
    path = cycle_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing cycle artifact: {path}")
    return _read_json_object(path)


def _cycle_artifact_paths(cycle_dir: Path) -> tuple[Path, Path]:
    """Return expected worker/judge artifact paths for a cycle directory."""
    return (cycle_dir / "worker.json", cycle_dir / "judge.json")


def _resolve_batch_cycle_dirs(
    *,
    cycles_root: Path,
    explicit_cycle_dirs: list[Path],
    strict: bool,
) -> tuple[list[Path], int]:
    """Resolve cycle directories for batch ingest.

    Args:
        cycles_root: Root directory for cycle discovery.
        explicit_cycle_dirs: Explicitly provided cycle directories.
        strict: Whether missing artifacts should fail the command.

    Returns:
        Tuple of `(resolved_cycle_dirs, skipped_count)`.

    Raises:
        ValueError: If strict mode is enabled and selected cycles are invalid.
    """
    if explicit_cycle_dirs:
        selected = sorted(explicit_cycle_dirs, key=lambda item: item.name)
    else:
        selected = _ordered_known_cycles(cycles_root=cycles_root)
        selected = [cycles_root / name for name in selected]

    resolved: list[Path] = []
    skipped = 0
    failures: list[StrictFailure] = []

    for cycle_dir in selected:
        if not cycle_dir.exists() or not cycle_dir.is_dir():
            if strict:
                failures.append(
                    StrictFailure(
                        cycle_dir=cycle_dir.as_posix(),
                        reason="not a directory",
                    )
                )
            else:
                print(f"[memory] WARN: skipping non-directory cycle path: {cycle_dir}")
                skipped += 1
            continue

        worker_path, judge_path = _cycle_artifact_paths(cycle_dir)
        missing: list[str] = []
        if not worker_path.exists():
            missing.append("worker.json")
        if not judge_path.exists():
            missing.append("judge.json")
        if missing:
            if strict:
                failures.append(
                    StrictFailure(
                        cycle_dir=cycle_dir.as_posix(),
                        reason=f"missing required artifacts ({', '.join(missing)})",
                    )
                )
            else:
                print(
                    "[memory] WARN: skipping cycle without required artifacts: "
                    f"{cycle_dir} ({', '.join(missing)})"
                )
                skipped += 1
            continue

        resolved.append(cycle_dir)

    if failures:
        joined_failures = "; ".join(
            f"{failure.cycle_dir}: {failure.reason}" for failure in failures
        )
        raise StrictBatchError(
            code=StrictErrorCode.SELECTION_FAILURE,
            message=f"strict cycle selection failed: {joined_failures}",
            failures=failures,
        )

    return resolved, skipped


def _build_candidates(cycle_dir: Path) -> list[CandidateItem]:
    worker = _load_cycle_file(cycle_dir, "worker.json")
    judge = _load_cycle_file(cycle_dir, "judge.json")

    cycle_id = _expect_string(judge, "cycle_id", "judge")
    candidates: list[CandidateItem] = []

    worker_cycle_id = _expect_string(worker, "cycle_id", "worker")
    if worker_cycle_id != cycle_id:
        raise ValueError("worker.cycle_id must match judge.cycle_id during memory ingest.")

    blockers_value = worker.get("blockers")
    if not isinstance(blockers_value, list):
        raise ValueError("worker.blockers must be a list.")
    for index, blocker_value in enumerate(blockers_value):
        if not isinstance(blocker_value, str) or not blocker_value.strip():
            raise ValueError(f"worker.blockers[{index}] must be a non-empty string.")
        title = blocker_value.strip()
        candidates.append(
            CandidateItem(
                title=title,
                kind=MemoryKind.ENVIRONMENT,
                confidence=MemoryConfidence.MEDIUM,
                detail=f"Worker blocker recorded in cycle {cycle_id}: {title}",
                source_cycle=cycle_id,
                source_file=f"{cycle_dir.as_posix()}/worker.json",
                tags=["blocker", "worker"],
            )
        )

    findings_value = judge.get("findings")
    if not isinstance(findings_value, list):
        raise ValueError("judge.findings must be a list.")
    for index, finding_value in enumerate(findings_value):
        if not isinstance(finding_value, dict):
            raise ValueError(f"judge.findings[{index}] must be an object.")
        severity = _expect_string(finding_value, "severity", f"judge.findings[{index}]")
        issue = _expect_string(finding_value, "issue", f"judge.findings[{index}]")
        where = _expect_string(finding_value, "where", f"judge.findings[{index}]")
        action = _expect_string(finding_value, "required_action", f"judge.findings[{index}]")

        if severity == "high":
            kind = MemoryKind.REGRESSION
            confidence = MemoryConfidence.HIGH
        elif severity == "medium":
            kind = MemoryKind.REGRESSION
            confidence = MemoryConfidence.MEDIUM
        elif severity == "low":
            kind = MemoryKind.RISK
            confidence = MemoryConfidence.MEDIUM
        else:
            raise ValueError(f"judge.findings[{index}].severity has unsupported value: {severity}")

        candidates.append(
            CandidateItem(
                title=issue,
                kind=kind,
                confidence=confidence,
                detail=f"{where}: {action}",
                source_cycle=cycle_id,
                source_file=f"{cycle_dir.as_posix()}/judge.json",
                tags=["finding", severity],
            )
        )

    follow_ups = judge.get("follow_up_tickets")
    if not isinstance(follow_ups, list):
        raise ValueError("judge.follow_up_tickets must be a list.")
    for index, follow_up_value in enumerate(follow_ups):
        if not isinstance(follow_up_value, dict):
            raise ValueError(f"judge.follow_up_tickets[{index}] must be an object.")
        task_type = _expect_string(
            follow_up_value,
            "task_type",
            f"judge.follow_up_tickets[{index}]",
        )
        task = _expect_string(follow_up_value, "task", f"judge.follow_up_tickets[{index}]")
        description = _expect_string(
            follow_up_value,
            "description",
            f"judge.follow_up_tickets[{index}]",
        )
        status = _expect_string(follow_up_value, "status", f"judge.follow_up_tickets[{index}]")
        if status != "TODO":
            raise ValueError(
                f"judge.follow_up_tickets[{index}].status must be TODO for memory ingest."
            )
        candidates.append(
            CandidateItem(
                title=task,
                kind=MemoryKind.TODO_HINT,
                confidence=MemoryConfidence.MEDIUM,
                detail=description,
                source_cycle=cycle_id,
                source_file=f"{cycle_dir.as_posix()}/judge.json",
                tags=["follow-up", task_type.lower()],
            )
        )

    return candidates


def _ingest_candidates(
    snapshot: MemorySnapshot,
    candidates: list[CandidateItem],
) -> tuple[MemorySnapshot, int, int]:
    items = list(snapshot.items)
    index_by_key: dict[tuple[MemoryKind, str], int] = {
        item.key(): idx for idx, item in enumerate(items)
    }

    added = 0
    updated = 0
    for candidate in candidates:
        key = candidate.key()
        if key in index_by_key:
            idx = index_by_key[key]
            existing = items[idx]
            merged_confidence = _higher_confidence(existing.confidence, candidate.confidence)
            merged_tags = _dedup_tags(existing.tags + candidate.tags)
            merged = MemoryItem(
                id=existing.id,
                title=existing.title,
                kind=existing.kind,
                status=MemoryStatus.ACTIVE,
                confidence=merged_confidence,
                detail=candidate.detail,
                source_cycle=existing.source_cycle,
                source_file=existing.source_file,
                last_verified_cycle=candidate.source_cycle,
                tags=merged_tags,
            )
            items[idx] = merged
            updated += 1
            continue

        new_item = MemoryItem(
            id=_next_memory_id(items),
            title=candidate.title,
            kind=candidate.kind,
            status=MemoryStatus.ACTIVE,
            confidence=candidate.confidence,
            detail=candidate.detail,
            source_cycle=candidate.source_cycle,
            source_file=candidate.source_file,
            last_verified_cycle=candidate.source_cycle,
            tags=_dedup_tags(candidate.tags),
        )
        items.append(new_item)
        index_by_key[new_item.key()] = len(items) - 1
        added += 1

    updated_snapshot = MemorySnapshot(
        version=snapshot.version,
        updated_at=_utc_now_iso(),
        current_focus=snapshot.current_focus,
        items=items,
    )
    return updated_snapshot, added, updated


def _write_snapshot(path: Path, snapshot: MemorySnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = snapshot.to_dict()
    path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")


def _write_strict_batch_report(
    *,
    report_path: Path | None,
    error: StrictBatchError,
    cycles_root: Path,
    requested_cycle_dirs: list[Path],
) -> None:
    """Write a machine-readable report for strict ingest-batch failures.

    Args:
        report_path: Optional output file path.
        error: Strict validation error details.
        cycles_root: Root used for cycle discovery.
        requested_cycle_dirs: Explicit cycle directories requested by caller.
    """
    if report_path is None:
        return

    report = StrictBatchReport(
        generated_at=_utc_now_iso(),
        code=error.code,
        message=str(error),
        cycles_root=cycles_root.as_posix(),
        requested_cycle_dirs=[path.as_posix() for path in requested_cycle_dirs],
        failures=error.failures,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"{json.dumps(report.to_dict(), indent=2)}\n",
        encoding="utf-8",
    )
    print(f"[memory] strict report written: {report_path}")


def _validate_command(memory_path: Path) -> int:
    snapshot = _parse_snapshot(memory_path)
    active = sum(item.status == MemoryStatus.ACTIVE for item in snapshot.items)
    resolved = sum(item.status == MemoryStatus.RESOLVED for item in snapshot.items)
    stale = sum(item.status == MemoryStatus.STALE for item in snapshot.items)
    print(
        "[memory] valid: "
        f"total={len(snapshot.items)}, active={active}, resolved={resolved}, stale={stale}"
    )
    return 0


def _ingest_command(memory_path: Path, cycle_dir: Path, focus: str | None) -> int:
    if memory_path.exists():
        snapshot = _parse_snapshot(memory_path)
    else:
        snapshot = _empty_snapshot(focus=focus or "unspecified")

    if focus is not None:
        snapshot = MemorySnapshot(
            version=snapshot.version,
            updated_at=snapshot.updated_at,
            current_focus=focus,
            items=snapshot.items,
        )

    candidates = _build_candidates(cycle_dir)
    updated_snapshot, added, updated = _ingest_candidates(snapshot, candidates)
    _write_snapshot(memory_path, updated_snapshot)
    print(
        "[memory] ingest complete: "
        f"added={added}, updated={updated}, total={len(updated_snapshot.items)}"
    )
    return 0


def _ingest_batch_command(
    *,
    memory_path: Path,
    cycles_root: Path,
    cycle_dirs: list[Path],
    focus: str | None,
    strict: bool,
) -> int:
    """Ingest multiple cycle directories in deterministic order."""
    if memory_path.exists():
        snapshot = _parse_snapshot(memory_path)
    else:
        snapshot = _empty_snapshot(focus=focus or "unspecified")

    if focus is not None:
        snapshot = MemorySnapshot(
            version=snapshot.version,
            updated_at=snapshot.updated_at,
            current_focus=focus,
            items=snapshot.items,
        )

    ordered_cycle_dirs, skipped = _resolve_batch_cycle_dirs(
        cycles_root=cycles_root,
        explicit_cycle_dirs=cycle_dirs,
        strict=strict,
    )

    if not ordered_cycle_dirs:
        raise ValueError("No cycle directories found for ingest-batch.")

    total_added = 0
    total_updated = 0
    updated_snapshot = snapshot
    schema_skipped = 0
    for cycle_dir in ordered_cycle_dirs:
        try:
            candidates = _build_candidates(cycle_dir)
        except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
            if strict:
                raise StrictBatchError(
                    code=StrictErrorCode.SCHEMA_FAILURE,
                    message=f"strict schema validation failed for {cycle_dir}: {exc}",
                    failures=[
                        StrictFailure(
                            cycle_dir=cycle_dir.as_posix(),
                            reason=str(exc),
                        )
                    ],
                ) from exc
            print(f"[memory] WARN: skipping invalid cycle payload {cycle_dir}: {exc}")
            schema_skipped += 1
            continue
        updated_snapshot, added, updated = _ingest_candidates(updated_snapshot, candidates)
        total_added += added
        total_updated += updated

    _write_snapshot(memory_path, updated_snapshot)
    joined_cycles = ", ".join(path.name for path in ordered_cycle_dirs)
    print(
        "[memory] ingest-batch complete: "
        f"cycles={len(ordered_cycle_dirs)} [{joined_cycles}], "
        f"added={total_added}, updated={total_updated}, "
        f"selection_skipped={skipped}, schema_skipped={schema_skipped}, "
        f"total={len(updated_snapshot.items)}"
    )
    return 0


def _prune_stale_items(
    snapshot: MemorySnapshot,
    *,
    current_cycle: str,
    max_cycle_lag: int,
    known_cycles: list[str],
    stale_unknown: bool,
) -> tuple[MemorySnapshot, int, int]:
    """Mark old active memory items as stale.

    Args:
        snapshot: Current memory snapshot.
        current_cycle: Cycle id considered "now".
        max_cycle_lag: Maximum allowed lag in number of cycles.
        known_cycles: Ordered cycle ids, oldest to newest.
        stale_unknown: Whether to stale active items with unknown cycle ids.

    Returns:
        Tuple of `(updated_snapshot, stale_marked_count, unknown_cycle_count)`.

    Raises:
        ValueError: If current_cycle is not present in known_cycles.
    """
    if max_cycle_lag < 0:
        raise ValueError("max_cycle_lag must be >= 0.")

    cycle_index = {cycle_id: index for index, cycle_id in enumerate(known_cycles)}
    current_index = cycle_index.get(current_cycle)
    if current_index is None:
        raise ValueError(f"current_cycle not found in known cycles: {current_cycle}")

    stale_marked = 0
    unknown_active = 0
    updated_items: list[MemoryItem] = []
    for item in snapshot.items:
        if item.status != MemoryStatus.ACTIVE:
            updated_items.append(item)
            continue

        verified_index = cycle_index.get(item.last_verified_cycle)
        if verified_index is None:
            unknown_active += 1
            if stale_unknown:
                updated_items.append(
                    MemoryItem(
                        id=item.id,
                        title=item.title,
                        kind=item.kind,
                        status=MemoryStatus.STALE,
                        confidence=item.confidence,
                        detail=item.detail,
                        source_cycle=item.source_cycle,
                        source_file=item.source_file,
                        last_verified_cycle=item.last_verified_cycle,
                        tags=item.tags,
                    )
                )
                stale_marked += 1
            else:
                updated_items.append(item)
            continue

        cycle_lag = current_index - verified_index
        if cycle_lag > max_cycle_lag:
            updated_items.append(
                MemoryItem(
                    id=item.id,
                    title=item.title,
                    kind=item.kind,
                    status=MemoryStatus.STALE,
                    confidence=item.confidence,
                    detail=item.detail,
                    source_cycle=item.source_cycle,
                    source_file=item.source_file,
                    last_verified_cycle=item.last_verified_cycle,
                    tags=item.tags,
                )
            )
            stale_marked += 1
            continue

        updated_items.append(item)

    updated_snapshot = MemorySnapshot(
        version=snapshot.version,
        updated_at=_utc_now_iso(),
        current_focus=snapshot.current_focus,
        items=updated_items,
    )
    return updated_snapshot, stale_marked, unknown_active


def _prune_command(
    *,
    memory_path: Path,
    current_cycle: str,
    max_cycle_lag: int,
    cycles_root: Path,
    stale_unknown: bool,
    dry_run: bool,
) -> int:
    """Execute stale-memory pruning against the snapshot file."""
    snapshot = _parse_snapshot(memory_path)
    known_cycles = _ordered_known_cycles(cycles_root)
    if not known_cycles:
        raise ValueError(f"No cycle directories found in {cycles_root}")

    updated_snapshot, stale_marked, unknown_active = _prune_stale_items(
        snapshot,
        current_cycle=current_cycle,
        max_cycle_lag=max_cycle_lag,
        known_cycles=known_cycles,
        stale_unknown=stale_unknown,
    )

    if not dry_run:
        _write_snapshot(memory_path, updated_snapshot)

    mode = "dry-run" if dry_run else "applied"
    print(
        "[memory] prune complete: "
        f"mode={mode}, stale_marked={stale_marked}, "
        f"unknown_active={unknown_active}, total={len(updated_snapshot.items)}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and update dev-loop memory snapshots.")
    parser.add_argument(
        "--memory",
        type=Path,
        default=Path("reports/dev_loop/memory_snapshot.json"),
        help="Path to the memory snapshot file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="Validate snapshot schema and invariants.")

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest durable signals from a cycle directory.",
    )
    ingest_parser.add_argument(
        "--cycle-dir",
        type=Path,
        required=True,
        help="Path to cycle directory containing worker.json and judge.json.",
    )
    ingest_parser.add_argument(
        "--focus",
        type=str,
        help="Optional updated value for memory.current_focus.",
    )

    batch_parser = subparsers.add_parser(
        "ingest-batch",
        help="Ingest multiple cycle directories in deterministic sorted order.",
    )
    batch_parser.add_argument(
        "--cycles-root",
        type=Path,
        default=Path("reports/dev_loop"),
        help="Root directory used for cycle discovery when --cycle-dir is not provided.",
    )
    batch_parser.add_argument(
        "--cycle-dir",
        type=Path,
        action="append",
        default=[],
        help="Explicit cycle directory to include. Repeat for multiple directories.",
    )
    batch_parser.add_argument(
        "--focus",
        type=str,
        help="Optional updated value for memory.current_focus.",
    )
    batch_parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Fail when selected cycle directories are missing artifacts or contain invalid schemas."
        ),
    )
    batch_parser.add_argument(
        "--strict-report",
        type=Path,
        help="Optional path for machine-readable strict failure report output (requires --strict).",
    )

    prune_parser = subparsers.add_parser(
        "prune-stale",
        help="Mark active items as stale when cycle lag exceeds threshold.",
    )
    prune_parser.add_argument(
        "--current-cycle",
        type=str,
        required=True,
        help="Current cycle id used as pruning reference point.",
    )
    prune_parser.add_argument(
        "--max-cycle-lag",
        type=int,
        default=5,
        help="Maximum allowed lag (in cycle count) before active items become stale.",
    )
    prune_parser.add_argument(
        "--cycles-root",
        type=Path,
        default=Path("reports/dev_loop"),
        help="Root directory that contains cycle folders.",
    )
    prune_parser.add_argument(
        "--stale-unknown",
        action="store_true",
        help="Also stale active items whose last_verified_cycle is not in known cycle folders.",
    )
    prune_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute pruning outcome without writing changes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run memory snapshot CLI.

    Args:
        argv: Optional argument list. Uses process arguments when omitted.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    strict_report_path: Path | None = None
    strict_cycles_root = Path("reports/dev_loop")
    strict_cycle_dirs: list[Path] = []

    try:
        if args.command == "validate":
            return _validate_command(memory_path=args.memory)
        if args.command == "ingest":
            return _ingest_command(
                memory_path=args.memory,
                cycle_dir=args.cycle_dir,
                focus=args.focus,
            )
        if args.command == "prune-stale":
            return _prune_command(
                memory_path=args.memory,
                current_cycle=args.current_cycle,
                max_cycle_lag=args.max_cycle_lag,
                cycles_root=args.cycles_root,
                stale_unknown=args.stale_unknown,
                dry_run=args.dry_run,
            )
        if args.command == "ingest-batch":
            strict_report_path = args.strict_report
            strict_cycles_root = args.cycles_root
            strict_cycle_dirs = list(args.cycle_dir)
            if strict_report_path is not None and not args.strict:
                raise ValueError("--strict-report requires --strict.")
            return _ingest_batch_command(
                memory_path=args.memory,
                cycles_root=args.cycles_root,
                cycle_dirs=args.cycle_dir,
                focus=args.focus,
                strict=args.strict,
            )
        raise ValueError(f"Unsupported command: {args.command}")
    except StrictBatchError as exc:
        _write_strict_batch_report(
            report_path=strict_report_path,
            error=exc,
            cycles_root=strict_cycles_root,
            requested_cycle_dirs=strict_cycle_dirs,
        )
        print(f"[memory] ERROR: {exc}")
        return 1
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[memory] ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

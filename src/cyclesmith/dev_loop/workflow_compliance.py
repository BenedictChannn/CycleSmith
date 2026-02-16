"""Enforce CycleSmith self-hosting workflow compliance for repository changes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

from cyclesmith.dev_loop import memory_snapshot, validate_cycle_artifacts
from cyclesmith.dev_loop.ticket_backends import TicketBackendKind

MAINTENANCE_ALLOWED_PREFIXES = ("reports/",)
MAINTENANCE_ALLOWED_EXACT = {"Cargo.lock", "uv.lock"}
REQUIRED_CYCLE_FILES = ("planner.json", "worker.json", "judge.json", "runner_sync.json")
ZERO_SHA = "0" * 40
RUNNER_CYCLE_PATTERN = re.compile(r"^\d{8}-[a-z0-9-]+-\d{2}$")


def _to_posix_path(path: str) -> str:
    return path.replace("\\", "/")


def _normalize_changed_paths(changed_paths: list[str]) -> list[str]:
    normalized = sorted({_to_posix_path(path).strip() for path in changed_paths if path.strip()})
    return normalized


def _to_repo_relative(path: Path, repo_root: Path) -> str:
    relative = path.resolve().relative_to(repo_root.resolve()) if path.is_absolute() else path
    return _to_posix_path(relative.as_posix())


def _is_maintenance_only_path(path: str) -> bool:
    if path in MAINTENANCE_ALLOWED_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in MAINTENANCE_ALLOWED_PREFIXES)


def _has_non_maintenance_changes(changed_paths: list[str], tickets_rel: str) -> bool:
    non_ticket_paths = [path for path in changed_paths if path != tickets_rel]
    if not non_ticket_paths:
        return False
    return any(not _is_maintenance_only_path(path) for path in non_ticket_paths)


def _detect_touched_runner_cycles(changed_paths: list[str], cycles_root_rel: str) -> list[str]:
    cycle_ids: set[str] = set()
    cycles_parts = PurePosixPath(cycles_root_rel).parts
    for path in changed_paths:
        parts = PurePosixPath(path).parts
        if len(parts) < len(cycles_parts) + 2:
            continue
        if parts[: len(cycles_parts)] != cycles_parts:
            continue
        cycle_id = parts[len(cycles_parts)]
        if RUNNER_CYCLE_PATTERN.fullmatch(cycle_id) is None:
            continue
        cycle_ids.add(cycle_id)
    return sorted(cycle_ids)


def _validate_runner_state_file(state_path: Path, cycles_root_path: Path) -> list[str]:
    errors: list[str] = []
    if not state_path.exists():
        return [f"runner state file listed in changes but missing on disk: {state_path}"]

    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"runner state file is not valid JSON: {state_path} ({exc})"]
    if not isinstance(raw, dict):
        return [f"runner state root must be an object: {state_path}"]

    version = raw.get("version")
    goal_id = raw.get("goal_id")
    current_cycle_id = raw.get("current_cycle_id")
    current_ticket = raw.get("current_ticket")

    if version != 1:
        errors.append(f"runner state version must be 1: {state_path}")
    if not isinstance(goal_id, str) or not goal_id.strip():
        errors.append(f"runner state goal_id must be a non-empty string: {state_path}")

    cycle_is_string = isinstance(current_cycle_id, str) and bool(current_cycle_id.strip())
    cycle_is_none = current_cycle_id is None
    if not cycle_is_string and not cycle_is_none:
        errors.append(
            f"runner state current_cycle_id must be null or non-empty string: {state_path}"
        )

    ticket_is_string = isinstance(current_ticket, str) and bool(current_ticket.strip())
    ticket_is_none = current_ticket is None
    if not ticket_is_string and not ticket_is_none:
        errors.append(f"runner state current_ticket must be null or non-empty string: {state_path}")

    if cycle_is_string != ticket_is_string:
        errors.append(
            "runner state current_cycle_id/current_ticket must both be null or both be set."
        )

    if cycle_is_string:
        cycle_dir = cycles_root_path / str(current_cycle_id)
        if not cycle_dir.exists() or not cycle_dir.is_dir():
            errors.append(
                f"runner state current_cycle_id directory does not exist: {cycle_dir.as_posix()}"
            )
    return errors


def _run_cycle_validator(
    cycle_dir: Path,
    tickets_path: Path,
    tickets_backend_kind: TicketBackendKind,
    schema_dir: Path,
) -> str | None:
    validator_rc = validate_cycle_artifacts.main(
        [
            "--cycle-dir",
            str(cycle_dir),
            "--tickets",
            str(tickets_path),
            "--tickets-backend",
            tickets_backend_kind.value,
            "--validate-schema",
            "--schema-dir",
            str(schema_dir),
        ]
    )
    if validator_rc != 0:
        return f"artifact validator failed for cycle: {cycle_dir.as_posix()}"
    return None


def _run_memory_validate(memory_path: Path) -> str | None:
    memory_rc = memory_snapshot.main(["--memory", str(memory_path), "validate"])
    if memory_rc != 0:
        return f"memory validate failed: {memory_path.as_posix()}"
    return None


def _run_strict_memory_replay(
    memory_path: Path, cycles_root: Path, cycle_dirs: list[Path]
) -> str | None:
    if not memory_path.exists():
        return f"memory snapshot missing: {memory_path.as_posix()}"
    temp_memory_path = cycles_root / ".memory_replay_tmp.json"
    replay_rc = 1
    try:
        temp_memory_path.write_text(memory_path.read_text(encoding="utf-8"), encoding="utf-8")
        args = [
            "--memory",
            str(temp_memory_path),
            "ingest-batch",
            "--cycles-root",
            str(cycles_root),
            "--strict",
        ]
        for cycle_dir in cycle_dirs:
            args.extend(["--cycle-dir", str(cycle_dir)])
        replay_rc = memory_snapshot.main(args)
    except OSError as exc:
        return f"strict memory ingest-batch replay setup failed: {exc}"
    finally:
        if temp_memory_path.exists():
            temp_memory_path.unlink()
    if replay_rc != 0:
        return "strict memory ingest-batch replay failed for touched cycle directories."
    return None


def _git_changed_paths(repo_root: Path, base_ref: str | None, head_ref: str) -> list[str]:
    normalized_base = base_ref
    if normalized_base == ZERO_SHA:
        normalized_base = None
    if normalized_base is None:
        probe = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD~1"],
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            raise ValueError("Unable to infer base ref from HEAD~1. Pass --base-ref explicitly.")
        normalized_base = probe.stdout.strip()

    diff_proc = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", normalized_base, head_ref],
        check=False,
        capture_output=True,
        text=True,
    )
    if diff_proc.returncode != 0:
        stderr = diff_proc.stderr.strip()
        raise ValueError(
            f"git diff failed for {normalized_base}..{head_ref}: {stderr or 'unknown error'}"
        )
    paths = [line.strip() for line in diff_proc.stdout.splitlines() if line.strip()]
    return _normalize_changed_paths(paths)


def run_compliance_checks(
    *,
    repo_root: Path,
    changed_paths: list[str],
    tickets_path: Path,
    tickets_backend_kind: TicketBackendKind,
    cycles_root: Path,
    memory_path: Path,
    schema_dir: Path,
) -> list[str]:
    """Run self-hosting workflow checks for the provided changed path set.

    Args:
        repo_root: Repository root path.
        changed_paths: Changed file paths relative to repo root.
        tickets_path: Path to `tickets.md`.
        cycles_root: Path to `reports/dev_loop`.
        memory_path: Path to memory snapshot file.
        schema_dir: Path to schema directory used by artifact validator.

    Returns:
        A list of human-readable error messages. Empty list means compliance pass.
    """
    errors: list[str] = []
    normalized_paths = _normalize_changed_paths(changed_paths)

    tickets_rel = _to_repo_relative(tickets_path, repo_root)
    cycles_rel = _to_repo_relative(cycles_root, repo_root)
    memory_rel = _to_repo_relative(memory_path, repo_root)
    changed_set = set(normalized_paths)

    has_non_maintenance = _has_non_maintenance_changes(normalized_paths, tickets_rel=tickets_rel)
    if has_non_maintenance and tickets_rel not in changed_set:
        errors.append("Non-maintenance changes require tickets.md to be updated in the same diff.")

    touched_cycle_ids = _detect_touched_runner_cycles(normalized_paths, cycles_root_rel=cycles_rel)
    touched_cycle_dirs = [cycles_root / cycle_id for cycle_id in touched_cycle_ids]

    if has_non_maintenance and not touched_cycle_dirs:
        errors.append(
            "Non-maintenance changes require at least one touched finalized runner cycle directory."
        )

    for cycle_dir in touched_cycle_dirs:
        missing = [name for name in REQUIRED_CYCLE_FILES if not (cycle_dir / name).exists()]
        if missing:
            errors.append(
                "Cycle directory missing required files "
                f"({', '.join(missing)}): {cycle_dir.as_posix()}"
            )
            continue
        validator_error = _run_cycle_validator(
            cycle_dir=cycle_dir,
            tickets_path=tickets_path,
            tickets_backend_kind=tickets_backend_kind,
            schema_dir=schema_dir,
        )
        if validator_error is not None:
            errors.append(validator_error)

    if touched_cycle_dirs and memory_rel not in changed_set:
        errors.append(
            "Touched runner cycle directories require memory snapshot updates in the same diff."
        )

    if touched_cycle_dirs:
        replay_error = _run_strict_memory_replay(
            memory_path=memory_path,
            cycles_root=cycles_root,
            cycle_dirs=touched_cycle_dirs,
        )
        if replay_error is not None:
            errors.append(replay_error)

    if memory_rel in changed_set or touched_cycle_dirs:
        if not memory_path.exists():
            errors.append(f"Memory snapshot file not found: {memory_path.as_posix()}")
        else:
            memory_error = _run_memory_validate(memory_path)
            if memory_error is not None:
                errors.append(memory_error)

    runner_state_rel = _to_posix_path((Path(cycles_rel) / "runner_state.json").as_posix())
    if runner_state_rel in changed_set:
        errors.extend(_validate_runner_state_file(cycles_root / "runner_state.json", cycles_root))

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check CycleSmith self-hosting workflow compliance against changed paths."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root directory.",
    )
    parser.add_argument(
        "--tickets",
        type=Path,
        default=Path("tickets.md"),
        help="Path to tickets file.",
    )
    parser.add_argument(
        "--tickets-backend",
        type=str,
        default=TicketBackendKind.MARKDOWN.value,
        choices=[kind.value for kind in TicketBackendKind],
        help="Ticket backend type.",
    )
    parser.add_argument(
        "--cycles-root",
        type=Path,
        default=Path("reports/dev_loop"),
        help="Path to root cycle directory.",
    )
    parser.add_argument(
        "--memory",
        type=Path,
        default=Path("reports/dev_loop/memory_snapshot.json"),
        help="Path to memory snapshot JSON file.",
    )
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=Path("schemas/dev_loop"),
        help="Path to artifact schema directory.",
    )
    parser.add_argument(
        "--base-ref",
        type=str,
        help="Git base ref/sha for changed file detection.",
    )
    parser.add_argument(
        "--head-ref",
        type=str,
        default="HEAD",
        help="Git head ref/sha for changed file detection.",
    )
    parser.add_argument(
        "--changed-path",
        action="append",
        default=[],
        help="Explicit changed path (repeatable). If provided, git diff is not used.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run workflow compliance checks.

    Args:
        argv: Optional argument list. Uses process arguments when omitted.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    tickets_path = (repo_root / args.tickets).resolve()
    tickets_backend_kind = TicketBackendKind(args.tickets_backend)
    cycles_root = (repo_root / args.cycles_root).resolve()
    memory_path = (repo_root / args.memory).resolve()
    schema_dir = (repo_root / args.schema_dir).resolve()

    try:
        if args.changed_path:
            changed_paths = _normalize_changed_paths(list(args.changed_path))
        else:
            changed_paths = _git_changed_paths(
                repo_root=repo_root,
                base_ref=args.base_ref,
                head_ref=args.head_ref,
            )
    except ValueError as exc:
        print(f"[workflow-compliance] ERROR: {exc}")
        return 1

    errors = run_compliance_checks(
        repo_root=repo_root,
        changed_paths=changed_paths,
        tickets_path=tickets_path,
        tickets_backend_kind=tickets_backend_kind,
        cycles_root=cycles_root,
        memory_path=memory_path,
        schema_dir=schema_dir,
    )
    if errors:
        for error in errors:
            print(f"[workflow-compliance] ERROR: {error}")
        return 1

    print(
        f"[workflow-compliance] OK: changed_paths={len(changed_paths)}, repo={repo_root.as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

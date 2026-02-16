"""Install repository-managed git hooks into `.git/hooks`."""

from __future__ import annotations

import argparse
from pathlib import Path


def _copy_hook(source: Path, destination: Path) -> None:
    """Copy a hook template into the active git hooks directory.

    Args:
        source: Path to a tracked hook template under `.githooks`.
        destination: Path to write inside `.git/hooks`.
    """
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    destination.chmod(0o755)


def _resolve_repo_root(path: Path) -> Path:
    """Resolve and validate repository root for hook installation.

    Args:
        path: Candidate repository path.

    Returns:
        Normalized repository root path.

    Raises:
        FileNotFoundError: If repository path does not exist.
        ValueError: If repository does not contain `.git`.
    """
    repo_root = path.resolve()
    if not repo_root.exists():
        raise FileNotFoundError(f"Repository root does not exist: {repo_root}")
    if not (repo_root / ".git").exists():
        raise ValueError(f"Repository root is missing .git directory: {repo_root}")
    return repo_root


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for hook installation."""
    parser = argparse.ArgumentParser(
        description="Install CycleSmith-managed local git hooks into .git/hooks."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root containing .githooks and .git.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Install required local git hooks for CycleSmith guardrails.

    The installer copies tracked hook templates from `.githooks/` to `.git/hooks/`
    and marks them executable.

    Installed hooks:
        - `pre-commit`: runs `scripts/enforce_ticket_loop.py`
        - `commit-msg`: removes Cursor co-author trailers from commit messages

    Returns:
        Process exit code. Returns `0` on success.

    Raises:
        ValueError: If the provided repository path is not a git repository.
        FileNotFoundError: If one or more expected hook templates are missing.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = _resolve_repo_root(args.repo_root)
    source_dir = repo_root / ".githooks"
    target_dir = repo_root / ".git" / "hooks"
    target_dir.mkdir(parents=True, exist_ok=True)

    installed = []
    for hook in ("pre-commit", "commit-msg"):
        source = source_dir / hook
        if not source.exists():
            raise FileNotFoundError(f"Missing hook template: {source}")
        destination = target_dir / hook
        _copy_hook(source, destination)
        installed.append(destination)

    print("Installed hooks:")
    for path in installed:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

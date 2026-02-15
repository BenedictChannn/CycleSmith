"""CycleSmith command-line entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from cyclesmith.dev_loop import memory_snapshot, run_cycle, validate_cycle_artifacts
from cyclesmith.hooks import enforce_ticket_loop, install_hooks
from cyclesmith.init_project import initialize_project


def _add_runner_subcommand(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "runner",
        help="Run or initialize deterministic cycle runner state.",
    )
    parser.add_argument("runner_args", nargs=argparse.REMAINDER, help="Arguments for runner.")


def _add_validate_subcommand(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("validate", help="Validate planner/worker/judge artifacts.")
    parser.add_argument(
        "validate_args",
        nargs=argparse.REMAINDER,
        help="Arguments for artifact validator.",
    )


def _add_memory_subcommand(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("memory", help="Manage durable memory snapshot.")
    parser.add_argument("memory_args", nargs=argparse.REMAINDER, help="Arguments for memory tool.")


def _add_init_subcommand(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("init", help="Initialize a repository with CycleSmith files.")
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("."),
        help="Repository path to initialize.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in target repository.",
    )
    parser.add_argument(
        "--install-hooks",
        action="store_true",
        help="Install git hooks after template initialization.",
    )


def _add_install_hooks_subcommand(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("install-hooks", help="Install managed git hooks.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root containing .githooks and .git.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build top-level CLI parser."""
    parser = argparse.ArgumentParser(description="CycleSmith autonomy-loop toolkit.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_init_subcommand(subparsers)
    _add_install_hooks_subcommand(subparsers)
    _add_runner_subcommand(subparsers)
    _add_validate_subcommand(subparsers)
    _add_memory_subcommand(subparsers)
    subparsers.add_parser(
        "enforce-ticket-loop",
        help="Run ticket-loop pre-commit enforcement checks.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run CycleSmith CLI.

    Args:
        argv: Optional argument list. Uses process args when omitted.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        summary = initialize_project(target=args.target, force=args.force)
        print(
            "[cyclesmith] init complete: "
            f"target={summary.target_root}, created={summary.created_count}, "
            f"skipped={summary.skipped_count}"
        )
        if args.install_hooks:
            return install_hooks.main(["--repo-root", str(args.target)])
        return 0

    if args.command == "install-hooks":
        return install_hooks.main(["--repo-root", str(args.repo_root)])

    if args.command == "runner":
        runner_args: list[str] = args.runner_args
        if runner_args and runner_args[0] == "--":
            runner_args = runner_args[1:]
        return run_cycle.main(runner_args)

    if args.command == "validate":
        validate_args: list[str] = args.validate_args
        if validate_args and validate_args[0] == "--":
            validate_args = validate_args[1:]
        return validate_cycle_artifacts.main(validate_args)

    if args.command == "memory":
        memory_args: list[str] = args.memory_args
        if memory_args and memory_args[0] == "--":
            memory_args = memory_args[1:]
        return memory_snapshot.main(memory_args)

    if args.command == "enforce-ticket-loop":
        return enforce_ticket_loop.main()

    raise ValueError(f"Unsupported command: {args.command}")

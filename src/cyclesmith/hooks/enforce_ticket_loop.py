from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Never


@dataclass(frozen=True)
class TicketSummary:
    total: int
    in_progress: int
    completed: int
    todo: int


MAINTENANCE_ALLOWED_PREFIXES = ("reports/",)


MAINTENANCE_ALLOWED_EXACT = {
    "Cargo.lock",
    "uv.lock",
}


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _try_git_show(spec: str) -> str | None:
    result = subprocess.run(
        ["git", "show", spec],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_tickets_markdown(markdown_text: str) -> TicketSummary:
    total = 0
    in_progress = 0
    completed = 0
    todo = 0

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue

        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) != 4:
            continue
        if cells[0] == "Task Type":
            continue
        if all(set(cell) <= {"-"} for cell in cells):
            continue

        status = cells[3]
        total += 1
        if status == "IN_PROGRESS":
            in_progress += 1
        elif status == "COMPLETED":
            completed += 1
        elif status == "TODO":
            todo += 1

    return TicketSummary(
        total=total,
        in_progress=in_progress,
        completed=completed,
        todo=todo,
    )


def _staged_files() -> list[str]:
    output = _run_git("diff", "--cached", "--name-only")
    return [line.strip() for line in output.splitlines() if line.strip()]


def _is_maintenance_only(paths: list[str]) -> bool:
    if not paths:
        return False
    for path in paths:
        if path in MAINTENANCE_ALLOWED_EXACT:
            continue
        if any(path.startswith(prefix) for prefix in MAINTENANCE_ALLOWED_PREFIXES):
            continue
        return False
    return True


def _fail(message: str) -> Never:
    print(f"[ticket-loop] {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    staged = _staged_files()
    if not staged:
        return 0

    tickets_path = "tickets.md"
    tickets_staged = tickets_path in staged
    staged_non_ticket = [path for path in staged if path != tickets_path]

    if staged_non_ticket and not tickets_staged:
        if _is_maintenance_only(staged_non_ticket):
            print(
                f"[ticket-loop] OK (maintenance-only): files={', '.join(sorted(staged_non_ticket))}"
            )
            return 0
        _fail("Code/doc changes detected but tickets.md is not staged.")

    if not tickets_staged:
        return 0

    staged_tickets = _try_git_show(":tickets.md")
    if staged_tickets is None:
        _fail("Unable to read staged tickets.md from index.")
    assert staged_tickets is not None

    previous_tickets = _try_git_show("HEAD:tickets.md")
    if previous_tickets is None:
        previous_tickets = ""

    current_summary = _parse_tickets_markdown(staged_tickets)
    previous_summary = _parse_tickets_markdown(previous_tickets)

    terminal_mode = current_summary.todo == 0 and current_summary.in_progress == 0
    if terminal_mode:
        if current_summary.completed != current_summary.total:
            _fail(
                "Terminal mode requires all tickets to be COMPLETED "
                "when no TODO/IN_PROGRESS remain."
            )
        print(
            "[ticket-loop] OK (terminal mode): "
            f"total={current_summary.total}, completed={current_summary.completed}"
        )
        return 0

    if current_summary.total < previous_summary.total:
        _fail(
            f"Ticket count decreased ({previous_summary.total} -> {current_summary.total}). "
            "Ticket count must be non-decreasing."
        )

    if current_summary.in_progress != 1:
        _fail(f"Expected exactly one IN_PROGRESS ticket, found {current_summary.in_progress}.")

    if current_summary.todo == 0:
        _fail("No TODO tickets remain. Keep the loop alive by adding follow-up work.")

    completed_delta = current_summary.completed - previous_summary.completed
    if completed_delta > 0 and current_summary.total == previous_summary.total:
        _fail(
            "One or more tickets were completed without adding new tickets. "
            "Add at least one new TODO/IN_PROGRESS ticket when closing work."
        )

    print(
        "[ticket-loop] OK: "
        f"total={previous_summary.total}->{current_summary.total}, "
        f"in_progress={current_summary.in_progress}, "
        f"completed={previous_summary.completed}->{current_summary.completed}, "
        f"todo={current_summary.todo}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

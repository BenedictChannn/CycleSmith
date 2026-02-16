from __future__ import annotations

import json

from cyclesmith.dev_loop.ticket_backends import (
    TaskType,
    TicketBackendKind,
    TicketRow,
    TicketsDocument,
    TicketStatus,
    resolve_ticket_backend,
)
from tests.utils import runtime_dir


def test_markdown_backend_load_and_save_roundtrip() -> None:
    with runtime_dir("cyclesmith-ticket-backend") as root:
        tickets_path = root / "tickets.md"
        tickets_path.write_text(
            "\n".join(
                [
                    "# Tickets",
                    "",
                    "| Task Type | Task | Description | Status |",
                    "| --- | --- | --- | --- |",
                    "| CHORE | T1 | D1 | IN_PROGRESS |",
                    "",
                    "## Backlog",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        backend = resolve_ticket_backend(TicketBackendKind.MARKDOWN)
        loaded = backend.load(tickets_path)
        assert len(loaded.rows) == 1
        assert loaded.rows[0].task == "T1"

        updated = TicketsDocument(
            rows=loaded.rows
            + [
                TicketRow(
                    task_type=TaskType.BUG,
                    task="T2",
                    description="D2",
                    status=TicketStatus.TODO,
                )
            ],
            prefix_lines=loaded.prefix_lines,
            header_line=loaded.header_line,
            separator_line=loaded.separator_line,
            suffix_lines=loaded.suffix_lines,
        )
        backend.save(tickets_path, updated)
        reloaded = backend.load(tickets_path)
        assert [row.task for row in reloaded.rows] == ["T1", "T2"]


def test_json_backend_load_and_save_roundtrip() -> None:
    with runtime_dir("cyclesmith-ticket-backend") as root:
        tickets_path = root / "tickets.json"
        payload = {
            "version": 1,
            "tickets": [
                {
                    "task_type": "CHORE",
                    "task": "T1",
                    "description": "D1",
                    "status": "IN_PROGRESS",
                }
            ],
        }
        tickets_path.write_text(json.dumps(payload), encoding="utf-8")

        backend = resolve_ticket_backend(TicketBackendKind.JSON)
        loaded = backend.load(tickets_path)
        assert loaded.rows[0].status == TicketStatus.IN_PROGRESS

        updated = TicketsDocument(
            rows=[
                TicketRow(
                    task_type=TaskType.CHORE,
                    task="T1",
                    description="D1",
                    status=TicketStatus.REVIEW,
                )
            ],
            prefix_lines=[],
            header_line="",
            separator_line="",
            suffix_lines=[],
        )
        backend.save(tickets_path, updated)
        reloaded = backend.load(tickets_path)
        assert reloaded.rows[0].status == TicketStatus.REVIEW


def test_json_backend_rejects_invalid_payload() -> None:
    with runtime_dir("cyclesmith-ticket-backend") as root:
        tickets_path = root / "tickets.json"
        tickets_path.write_text(
            json.dumps({"version": 1, "tickets": [{"task_type": "NOPE"}]}),
            encoding="utf-8",
        )
        backend = resolve_ticket_backend(TicketBackendKind.JSON)
        try:
            backend.load(tickets_path)
        except ValueError as exc:
            assert "task" in str(exc) or "unsupported" in str(exc)
        else:
            raise AssertionError("Expected ValueError for invalid tickets.json payload.")

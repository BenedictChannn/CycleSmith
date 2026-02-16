"""Typed ticket backend interface with markdown and JSON implementations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class TaskType(StrEnum):
    FEATURE = "FEATURE"
    IMPROVEMENT = "IMPROVEMENT"
    BUG = "BUG"
    CHORE = "CHORE"
    INVESTIGATION = "INVESTIGATION"
    REFACTOR = "REFACTOR"
    DOCS = "DOCS"
    PERFORMANCE = "PERFORMANCE"
    SECURITY = "SECURITY"
    TEST = "TEST"


class TicketStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    WIP = "WIP"
    BLOCKED = "BLOCKED"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


TRANSITION_RULES: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.TODO: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.WIP,
        TicketStatus.BLOCKED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.IN_PROGRESS: {
        TicketStatus.TODO,
        TicketStatus.BLOCKED,
        TicketStatus.REVIEW,
        TicketStatus.COMPLETED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.WIP: {
        TicketStatus.TODO,
        TicketStatus.BLOCKED,
        TicketStatus.REVIEW,
        TicketStatus.COMPLETED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.BLOCKED: {
        TicketStatus.TODO,
        TicketStatus.IN_PROGRESS,
        TicketStatus.WIP,
        TicketStatus.CANCELLED,
    },
    TicketStatus.REVIEW: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.WIP,
        TicketStatus.COMPLETED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.COMPLETED: set(),
    TicketStatus.CANCELLED: set(),
}


class TicketBackendKind(StrEnum):
    MARKDOWN = "markdown"
    JSON = "json"


@dataclass(frozen=True)
class TicketRow:
    task_type: TaskType
    task: str
    description: str
    status: TicketStatus

    def to_markdown_row(self) -> str:
        return (
            f"| {self.task_type.value} | {self.task} | {self.description} | {self.status.value} |"
        )

    def to_json_dict(self) -> dict[str, str]:
        return {
            "task_type": self.task_type.value,
            "task": self.task,
            "description": self.description,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class TicketsDocument:
    rows: list[TicketRow]
    prefix_lines: list[str]
    header_line: str
    separator_line: str
    suffix_lines: list[str]


class TicketBackend(Protocol):
    def load(self, path: Path) -> TicketsDocument:
        """Load ticket document from disk."""

    def save(self, path: Path, tickets: TicketsDocument) -> None:
        """Persist ticket document to disk."""


def _split_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped.split("|")[1:-1]]


class MarkdownTicketBackend:
    """Default markdown ticket backend (`tickets.md`)."""

    TABLE_HEADER = "| Task Type | Task | Description | Status |"

    def load(self, path: Path) -> TicketsDocument:
        lines = path.read_text(encoding="utf-8").splitlines()
        header_index = -1
        for index, line in enumerate(lines):
            if line.strip() == self.TABLE_HEADER:
                header_index = index
                break
        if header_index < 0:
            raise ValueError("Could not find ticket table header in markdown tickets file.")

        if header_index + 1 >= len(lines):
            raise ValueError("Tickets markdown is missing table separator line.")

        separator_line = lines[header_index + 1]
        if not separator_line.strip().startswith("| ---"):
            raise ValueError("Tickets markdown has invalid table separator line.")

        rows: list[TicketRow] = []
        cursor = header_index + 2
        while cursor < len(lines):
            cells = _split_row(lines[cursor])
            if cells is None:
                break
            if len(cells) != 4:
                raise ValueError(f"Invalid tickets markdown row at line {cursor + 1}.")
            task_type_text, task, description, status_text = cells
            try:
                task_type = TaskType(task_type_text)
            except ValueError as exc:
                raise ValueError(
                    f"Unsupported task type in tickets row {cursor + 1}: {task_type_text}"
                ) from exc
            try:
                status = TicketStatus(status_text)
            except ValueError as exc:
                raise ValueError(
                    f"Unsupported ticket status in row {cursor + 1}: {status_text}"
                ) from exc
            rows.append(
                TicketRow(
                    task_type=task_type,
                    task=task,
                    description=description,
                    status=status,
                )
            )
            cursor += 1

        return TicketsDocument(
            rows=rows,
            prefix_lines=lines[:header_index],
            header_line=lines[header_index],
            separator_line=separator_line,
            suffix_lines=lines[cursor:],
        )

    def save(self, path: Path, tickets: TicketsDocument) -> None:
        out_lines: list[str] = []
        out_lines.extend(tickets.prefix_lines)
        out_lines.append(tickets.header_line or self.TABLE_HEADER)
        out_lines.append(tickets.separator_line or "| --- | --- | --- | --- |")
        out_lines.extend(row.to_markdown_row() for row in tickets.rows)
        out_lines.extend(tickets.suffix_lines)
        path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


class JsonTicketBackend:
    """Strict JSON ticket backend (`tickets.json`)."""

    def load(self, path: Path) -> TicketsDocument:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("tickets.json root must be an object.")

        version = raw.get("version")
        if version != 1:
            raise ValueError("tickets.json version must be 1.")

        tickets_value = raw.get("tickets")
        if not isinstance(tickets_value, list):
            raise ValueError("tickets.json tickets must be a list.")

        rows: list[TicketRow] = []
        for index, ticket in enumerate(tickets_value):
            if not isinstance(ticket, dict):
                raise ValueError(f"tickets.json tickets[{index}] must be an object.")
            task_type_text = ticket.get("task_type")
            task = ticket.get("task")
            description = ticket.get("description")
            status_text = ticket.get("status")
            if not isinstance(task_type_text, str):
                raise ValueError(f"tickets.json tickets[{index}].task_type must be a string.")
            if not isinstance(task, str) or not task.strip():
                raise ValueError(f"tickets.json tickets[{index}].task must be a non-empty string.")
            if not isinstance(description, str):
                raise ValueError(f"tickets.json tickets[{index}].description must be a string.")
            if not isinstance(status_text, str):
                raise ValueError(f"tickets.json tickets[{index}].status must be a string.")
            try:
                task_type = TaskType(task_type_text)
            except ValueError as exc:
                raise ValueError(
                    f"tickets.json tickets[{index}].task_type has unsupported value: "
                    f"{task_type_text}"
                ) from exc
            try:
                status = TicketStatus(status_text)
            except ValueError as exc:
                raise ValueError(
                    f"tickets.json tickets[{index}].status has unsupported value: {status_text}"
                ) from exc
            rows.append(
                TicketRow(
                    task_type=task_type,
                    task=task,
                    description=description,
                    status=status,
                )
            )

        return TicketsDocument(
            rows=rows,
            prefix_lines=[],
            header_line="",
            separator_line="",
            suffix_lines=[],
        )

    def save(self, path: Path, tickets: TicketsDocument) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "tickets": [row.to_json_dict() for row in tickets.rows],
        }
        path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")


def resolve_ticket_backend(kind: TicketBackendKind) -> TicketBackend:
    if kind == TicketBackendKind.MARKDOWN:
        return MarkdownTicketBackend()
    if kind == TicketBackendKind.JSON:
        return JsonTicketBackend()
    raise ValueError(f"Unsupported ticket backend: {kind}")

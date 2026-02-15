from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


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


class WorkerStepStatus(StrEnum):
    DONE = "done"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_RUN = "not_run"


class WorkerResultStatus(StrEnum):
    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class Verdict(StrEnum):
    PASS = "pass"
    REWORK = "rework"
    BLOCKED = "blocked"


class TicketTransition(StrEnum):
    REVIEW = "REVIEW"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"


class FindingSeverity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class PlannerArtifact:
    cycle_id: str
    ticket_title: str
    status_before: TicketStatus
    step_ids: list[str]
    next_role: str


@dataclass(frozen=True)
class WorkerArtifact:
    cycle_id: str
    ticket_title: str
    step_ids: list[str]
    checks: dict[str, CheckStatus]
    result_status: WorkerResultStatus
    blockers: list[str]
    next_role: str


@dataclass(frozen=True)
class JudgeArtifact:
    cycle_id: str
    ticket_title: str
    finding_severities: list[FindingSeverity]
    verdict: Verdict
    ticket_transition: TicketTransition
    follow_up_tickets: list[dict[str, str]]


REQUIRED_CHECK_KEYS = (
    "ruff_check",
    "ruff_format",
    "ty_check",
    "pytest",
    "rust_checks",
)


def _read_schema_object(path: Path, errors: list[str]) -> dict[str, Any] | None:
    """Read and validate a JSON schema object from disk.

    Args:
        path: Path to schema JSON file.
        errors: Mutable list used for diagnostics.

    Returns:
        Parsed schema object when present and valid, otherwise `None`.
    """
    if not path.exists():
        errors.append(f"Missing schema file: {path}")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"Invalid JSON in schema file {path}: {exc}")
        return None
    if not isinstance(data, dict):
        errors.append(f"Schema file {path} must be a JSON object.")
        return None
    return data


def _json_pointer(path_parts: Iterable[Any]) -> str:
    tokens: list[str] = []
    for part in path_parts:
        token = str(part).replace("~", "~0").replace("/", "~1")
        tokens.append(token)
    if not tokens:
        return "/"
    return "/" + "/".join(tokens)


def _decode_json_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _resolve_schema_ref(root_schema: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None

    current: Any = root_schema
    for raw_token in ref[2:].split("/"):
        token = _decode_json_pointer_token(raw_token)
        if not isinstance(current, dict):
            return None
        if token not in current:
            return None
        current = current[token]

    if not isinstance(current, dict):
        return None
    return current


def _validate_schema_node(
    *,
    artifact_name: str,
    value: Any,
    schema_node: dict[str, Any],
    root_schema: dict[str, Any],
    path_parts: tuple[Any, ...],
    errors: list[str],
) -> None:
    pointer = _json_pointer(path_parts)

    ref = schema_node.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_schema_ref(root_schema, ref)
        if resolved is None:
            errors.append(
                f"{artifact_name} schema validation failed at {pointer}: unresolved $ref {ref}"
            )
            return
        _validate_schema_node(
            artifact_name=artifact_name,
            value=value,
            schema_node=resolved,
            root_schema=root_schema,
            path_parts=path_parts,
            errors=errors,
        )
        return

    if "const" in schema_node and value != schema_node["const"]:
        errors.append(
            f"{artifact_name} schema validation failed at {pointer}: expected const "
            f"{schema_node['const']!r}"
        )

    enum_values = schema_node.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        errors.append(
            f"{artifact_name} schema validation failed at {pointer}: value must be one of "
            f"{enum_values!r}"
        )

    schema_type = schema_node.get("type")
    if not isinstance(schema_type, str):
        return

    if schema_type == "string":
        if not isinstance(value, str):
            errors.append(
                f"{artifact_name} schema validation failed at {pointer}: expected type string"
            )
            return
        min_length = schema_node.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(
                f"{artifact_name} schema validation failed at {pointer}: "
                f"string length must be >= {min_length}"
            )
        return

    if schema_type == "array":
        if not isinstance(value, list):
            errors.append(
                f"{artifact_name} schema validation failed at {pointer}: expected type array"
            )
            return
        min_items = schema_node.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(
                f"{artifact_name} schema validation failed at {pointer}: "
                f"array length must be >= {min_items}"
            )
        item_schema = schema_node.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_schema_node(
                    artifact_name=artifact_name,
                    value=item,
                    schema_node=item_schema,
                    root_schema=root_schema,
                    path_parts=(*path_parts, index),
                    errors=errors,
                )
        return

    if schema_type == "object":
        if not isinstance(value, dict):
            errors.append(
                f"{artifact_name} schema validation failed at {pointer}: expected type object"
            )
            return

        required_keys = schema_node.get("required")
        if isinstance(required_keys, list):
            for raw_required_key in required_keys:
                if not isinstance(raw_required_key, str):
                    continue
                if raw_required_key not in value:
                    required_pointer = _json_pointer((*path_parts, raw_required_key))
                    errors.append(
                        f"{artifact_name} schema validation failed at {required_pointer}: "
                        "missing required property"
                    )

        properties = schema_node.get("properties")
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key not in value:
                    continue
                if not isinstance(child_schema, dict):
                    continue
                _validate_schema_node(
                    artifact_name=artifact_name,
                    value=value[key],
                    schema_node=child_schema,
                    root_schema=root_schema,
                    path_parts=(*path_parts, key),
                    errors=errors,
                )

            if schema_node.get("additionalProperties") is False:
                for key in value:
                    if key in properties:
                        continue
                    extra_pointer = _json_pointer((*path_parts, key))
                    errors.append(
                        f"{artifact_name} schema validation failed at {extra_pointer}: "
                        "additional property is not allowed"
                    )


def _validate_artifact_schema(
    *,
    artifact_name: str,
    payload: dict[str, Any],
    schema: dict[str, Any],
    errors: list[str],
) -> None:
    """Append schema validation failures for one artifact payload."""
    _validate_schema_node(
        artifact_name=artifact_name,
        value=payload,
        schema_node=schema,
        root_schema=schema,
        path_parts=(),
        errors=errors,
    )


def _validate_schemas(
    *,
    schema_dir: Path,
    planner_raw: dict[str, Any],
    worker_raw: dict[str, Any],
    judge_raw: dict[str, Any],
    errors: list[str],
) -> None:
    """Validate cycle artifact payloads against JSON schema files."""
    planner_schema = _read_schema_object(schema_dir / "planner.schema.json", errors)
    worker_schema = _read_schema_object(schema_dir / "worker.schema.json", errors)
    judge_schema = _read_schema_object(schema_dir / "judge.schema.json", errors)

    if planner_schema is None or worker_schema is None or judge_schema is None:
        return

    _validate_artifact_schema(
        artifact_name="planner",
        payload=planner_raw,
        schema=planner_schema,
        errors=errors,
    )
    _validate_artifact_schema(
        artifact_name="worker",
        payload=worker_raw,
        schema=worker_schema,
        errors=errors,
    )
    _validate_artifact_schema(
        artifact_name="judge",
        payload=judge_raw,
        schema=judge_schema,
        errors=errors,
    )


def _parse_tickets(markdown_text: str) -> dict[str, TicketStatus]:
    status_by_title: dict[str, TicketStatus] = {}
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
        title = cells[1]
        status_text = cells[3]
        try:
            status = TicketStatus(status_text)
        except ValueError:
            continue
        status_by_title[title] = status
    return status_by_title


def _read_json_object(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.exists():
        errors.append(f"Missing required artifact: {path}")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"Invalid JSON in {path}: {exc}")
        return None
    if not isinstance(data, dict):
        errors.append(f"Artifact {path} must be a JSON object.")
        return None
    return data


def _expect_string(
    obj: dict[str, Any],
    key: str,
    context: str,
    errors: list[str],
) -> str | None:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{context}.{key} must be a non-empty string.")
        return None
    return value


def _expect_string_list(
    obj: dict[str, Any],
    key: str,
    context: str,
    errors: list[str],
) -> list[str] | None:
    value = obj.get(key)
    if not isinstance(value, list):
        errors.append(f"{context}.{key} must be a list.")
        return None
    strings: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{context}.{key}[{index}] must be a non-empty string.")
            continue
        strings.append(item)
    return strings


def _parse_planner(
    planner: dict[str, Any],
    errors: list[str],
) -> PlannerArtifact | None:
    cycle_id = _expect_string(planner, "cycle_id", "planner", errors)

    ticket_value = planner.get("ticket")
    if not isinstance(ticket_value, dict):
        errors.append("planner.ticket must be an object.")
        return None

    ticket_type = _expect_string(ticket_value, "type", "planner.ticket", errors)
    ticket_title = _expect_string(ticket_value, "title", "planner.ticket", errors)
    status_before_text = _expect_string(ticket_value, "status_before", "planner.ticket", errors)

    if ticket_type is not None:
        try:
            TaskType(ticket_type)
        except ValueError:
            errors.append(f"planner.ticket.type has unsupported value: {ticket_type}")

    status_before: TicketStatus | None = None
    if status_before_text is not None:
        try:
            status_before = TicketStatus(status_before_text)
        except ValueError:
            errors.append(
                f"planner.ticket.status_before has unsupported value: {status_before_text}"
            )

    steps_value = planner.get("steps")
    if not isinstance(steps_value, list) or not steps_value:
        errors.append("planner.steps must be a non-empty list.")
        return None

    step_ids: list[str] = []
    for index, step_item in enumerate(steps_value):
        if not isinstance(step_item, dict):
            errors.append(f"planner.steps[{index}] must be an object.")
            continue
        step_id = _expect_string(step_item, "id", f"planner.steps[{index}]", errors)
        _expect_string(step_item, "action", f"planner.steps[{index}]", errors)
        _expect_string_list(step_item, "files", f"planner.steps[{index}]", errors)
        _expect_string_list(step_item, "validation", f"planner.steps[{index}]", errors)
        if step_id is not None:
            step_ids.append(step_id)

    if len(step_ids) != len(set(step_ids)):
        errors.append("planner.steps contains duplicate step ids.")

    next_role = _expect_string(planner, "next_role", "planner", errors)
    if next_role is not None and next_role != "WORKER":
        errors.append("planner.next_role must be WORKER.")

    _expect_string(planner, "objective", "planner", errors)
    _expect_string_list(planner, "scope_in", "planner", errors)
    _expect_string_list(planner, "scope_out", "planner", errors)
    _expect_string_list(planner, "risks", "planner", errors)
    _expect_string_list(planner, "handoff_constraints", "planner", errors)

    if (
        cycle_id is None
        or ticket_title is None
        or status_before is None
        or next_role is None
        or not step_ids
    ):
        return None

    return PlannerArtifact(
        cycle_id=cycle_id,
        ticket_title=ticket_title,
        status_before=status_before,
        step_ids=step_ids,
        next_role=next_role,
    )


def _parse_worker(worker: dict[str, Any], errors: list[str]) -> WorkerArtifact | None:
    cycle_id = _expect_string(worker, "cycle_id", "worker", errors)
    ticket_title = _expect_string(worker, "ticket_title", "worker", errors)

    step_results = worker.get("step_results")
    if not isinstance(step_results, list) or not step_results:
        errors.append("worker.step_results must be a non-empty list.")
        return None

    step_ids: list[str] = []
    for index, item in enumerate(step_results):
        if not isinstance(item, dict):
            errors.append(f"worker.step_results[{index}] must be an object.")
            continue
        step_id = _expect_string(item, "step_id", f"worker.step_results[{index}]", errors)
        status_text = _expect_string(item, "status", f"worker.step_results[{index}]", errors)
        _expect_string(item, "notes", f"worker.step_results[{index}]", errors)
        _expect_string_list(item, "files_touched", f"worker.step_results[{index}]", errors)
        _expect_string_list(item, "commands_run", f"worker.step_results[{index}]", errors)
        if step_id is not None:
            step_ids.append(step_id)
        if status_text is not None:
            try:
                WorkerStepStatus(status_text)
            except ValueError:
                errors.append(
                    f"worker.step_results[{index}].status has unsupported value: {status_text}"
                )

    if len(step_ids) != len(set(step_ids)):
        errors.append("worker.step_results contains duplicate step ids.")

    checks_value = worker.get("checks")
    if not isinstance(checks_value, dict):
        errors.append("worker.checks must be an object.")
        return None

    checks: dict[str, CheckStatus] = {}
    for key in REQUIRED_CHECK_KEYS:
        value = checks_value.get(key)
        if not isinstance(value, str):
            errors.append(f"worker.checks.{key} must be a string enum value.")
            continue
        try:
            checks[key] = CheckStatus(value)
        except ValueError:
            errors.append(f"worker.checks.{key} has unsupported value: {value}")

    result_status_text = _expect_string(worker, "result_status", "worker", errors)
    result_status: WorkerResultStatus | None = None
    if result_status_text is not None:
        try:
            result_status = WorkerResultStatus(result_status_text)
        except ValueError:
            errors.append(f"worker.result_status has unsupported value: {result_status_text}")

    blockers = _expect_string_list(worker, "blockers", "worker", errors)
    next_role = _expect_string(worker, "next_role", "worker", errors)
    if next_role is not None and next_role != "JUDGE":
        errors.append("worker.next_role must be JUDGE.")

    if (
        cycle_id is None
        or ticket_title is None
        or result_status is None
        or blockers is None
        or next_role is None
        or not step_ids
    ):
        return None

    return WorkerArtifact(
        cycle_id=cycle_id,
        ticket_title=ticket_title,
        step_ids=step_ids,
        checks=checks,
        result_status=result_status,
        blockers=blockers,
        next_role=next_role,
    )


def _parse_judge(judge: dict[str, Any], errors: list[str]) -> JudgeArtifact | None:
    cycle_id = _expect_string(judge, "cycle_id", "judge", errors)
    ticket_title = _expect_string(judge, "ticket_title", "judge", errors)

    findings_value = judge.get("findings")
    if not isinstance(findings_value, list):
        errors.append("judge.findings must be a list.")
        return None
    finding_severities: list[FindingSeverity] = []
    for index, item in enumerate(findings_value):
        if not isinstance(item, dict):
            errors.append(f"judge.findings[{index}] must be an object.")
            continue
        severity_text = _expect_string(item, "severity", f"judge.findings[{index}]", errors)
        _expect_string(item, "where", f"judge.findings[{index}]", errors)
        _expect_string(item, "issue", f"judge.findings[{index}]", errors)
        _expect_string(item, "required_action", f"judge.findings[{index}]", errors)
        if severity_text is not None:
            try:
                finding_severities.append(FindingSeverity(severity_text))
            except ValueError:
                errors.append(
                    f"judge.findings[{index}].severity has unsupported value: {severity_text}"
                )

    qa_verification = judge.get("qa_verification")
    if not isinstance(qa_verification, list):
        errors.append("judge.qa_verification must be a list.")
        return None
    for index, item in enumerate(qa_verification):
        if not isinstance(item, dict):
            errors.append(f"judge.qa_verification[{index}] must be an object.")
            continue
        _expect_string(item, "command", f"judge.qa_verification[{index}]", errors)
        result_text = _expect_string(item, "result", f"judge.qa_verification[{index}]", errors)
        _expect_string(item, "evidence", f"judge.qa_verification[{index}]", errors)
        if result_text is not None:
            try:
                CheckStatus(result_text)
            except ValueError:
                errors.append(
                    f"judge.qa_verification[{index}].result has unsupported value: {result_text}"
                )

    verdict_text = _expect_string(judge, "verdict", "judge", errors)
    verdict: Verdict | None = None
    if verdict_text is not None:
        try:
            verdict = Verdict(verdict_text)
        except ValueError:
            errors.append(f"judge.verdict has unsupported value: {verdict_text}")

    transition_text = _expect_string(judge, "ticket_transition", "judge", errors)
    transition: TicketTransition | None = None
    if transition_text is not None:
        try:
            transition = TicketTransition(transition_text)
        except ValueError:
            errors.append(f"judge.ticket_transition has unsupported value: {transition_text}")

    follow_up_value = judge.get("follow_up_tickets")
    if not isinstance(follow_up_value, list):
        errors.append("judge.follow_up_tickets must be a list.")
        return None
    follow_up_tickets: list[dict[str, str]] = []
    for index, item in enumerate(follow_up_value):
        if not isinstance(item, dict):
            errors.append(f"judge.follow_up_tickets[{index}] must be an object.")
            continue
        task_type = _expect_string(item, "task_type", f"judge.follow_up_tickets[{index}]", errors)
        task = _expect_string(item, "task", f"judge.follow_up_tickets[{index}]", errors)
        description = _expect_string(
            item,
            "description",
            f"judge.follow_up_tickets[{index}]",
            errors,
        )
        status = _expect_string(item, "status", f"judge.follow_up_tickets[{index}]", errors)

        if task_type is not None:
            try:
                TaskType(task_type)
            except ValueError:
                errors.append(
                    f"judge.follow_up_tickets[{index}].task_type has unsupported value: {task_type}"
                )
        if status is not None and status != TicketStatus.TODO.value:
            errors.append(f"judge.follow_up_tickets[{index}].status must be TODO.")
        if task_type and task and description and status:
            follow_up_tickets.append(
                {
                    "task_type": task_type,
                    "task": task,
                    "description": description,
                    "status": status,
                }
            )

    _expect_string(judge, "next_cycle_focus", "judge", errors)

    if cycle_id is None or ticket_title is None or verdict is None or transition is None:
        return None

    return JudgeArtifact(
        cycle_id=cycle_id,
        ticket_title=ticket_title,
        finding_severities=finding_severities,
        verdict=verdict,
        ticket_transition=transition,
        follow_up_tickets=follow_up_tickets,
    )


def _validate_cross_artifacts(
    planner: PlannerArtifact,
    worker: WorkerArtifact,
    judge: JudgeArtifact,
    ticket_status_by_title: dict[str, TicketStatus],
    errors: list[str],
) -> None:
    if planner.cycle_id != worker.cycle_id or planner.cycle_id != judge.cycle_id:
        errors.append("cycle_id mismatch across planner/worker/judge artifacts.")

    if planner.ticket_title != worker.ticket_title or planner.ticket_title != judge.ticket_title:
        errors.append("ticket title mismatch across planner/worker/judge artifacts.")

    if planner.status_before != TicketStatus.IN_PROGRESS:
        errors.append("planner.ticket.status_before must be IN_PROGRESS.")

    if planner.ticket_title not in ticket_status_by_title:
        errors.append(f"planner ticket title not found in tickets.md: {planner.ticket_title}")

    planner_steps = set(planner.step_ids)
    worker_steps = set(worker.step_ids)
    if planner_steps != worker_steps or len(planner.step_ids) != len(worker.step_ids):
        errors.append("worker.step_results step_ids must match planner.steps ids exactly.")

    if worker.result_status == WorkerResultStatus.BLOCKED and not worker.blockers:
        errors.append("worker.result_status=blocked requires at least one blocker.")

    has_failed_check = any(status == CheckStatus.FAIL for status in worker.checks.values())
    has_missing_check = any(status == CheckStatus.NOT_RUN for status in worker.checks.values())

    if worker.result_status == WorkerResultStatus.IMPLEMENTED and (
        has_failed_check or has_missing_check
    ):
        errors.append("worker.result_status=implemented requires all checks to be pass.")

    if judge.verdict == Verdict.PASS:
        if judge.ticket_transition != TicketTransition.REVIEW:
            errors.append("judge.verdict=pass requires ticket_transition=REVIEW.")
        if FindingSeverity.HIGH in judge.finding_severities:
            errors.append("judge.verdict=pass cannot include high-severity findings.")
        if has_failed_check or has_missing_check:
            errors.append("judge.verdict=pass requires all worker checks to pass.")

    if judge.verdict == Verdict.REWORK and judge.ticket_transition != TicketTransition.IN_PROGRESS:
        errors.append("judge.verdict=rework requires ticket_transition=IN_PROGRESS.")

    if judge.verdict == Verdict.BLOCKED and judge.ticket_transition != TicketTransition.BLOCKED:
        errors.append("judge.verdict=blocked requires ticket_transition=BLOCKED.")

    if judge.verdict != Verdict.PASS and not judge.follow_up_tickets:
        errors.append("judge.verdict!=pass requires at least one follow_up_ticket.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate planner/worker/judge cycle artifacts.")
    parser.add_argument(
        "--cycle-dir",
        type=Path,
        required=True,
        help="Directory that contains planner.json, worker.json, and judge.json.",
    )
    parser.add_argument(
        "--tickets",
        type=Path,
        default=Path("tickets.md"),
        help="Path to tickets.md used for ticket-title validation.",
    )
    parser.add_argument(
        "--validate-schema",
        action="store_true",
        help="Validate role artifacts against JSON schemas in --schema-dir.",
    )
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=Path("schemas/dev_loop"),
        help="Directory containing planner.schema.json, worker.schema.json, and judge.schema.json.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run cycle artifact validator CLI.

    Args:
        argv: Optional argument list. Uses process arguments when omitted.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    errors: list[str] = []
    if not args.cycle_dir.exists() or not args.cycle_dir.is_dir():
        errors.append(f"Cycle directory does not exist: {args.cycle_dir}")
        for error in errors:
            print(f"[dev-loop] ERROR: {error}")
        return 1

    if not args.tickets.exists():
        errors.append(f"tickets.md not found: {args.tickets}")
        for error in errors:
            print(f"[dev-loop] ERROR: {error}")
        return 1

    ticket_status_by_title = _parse_tickets(args.tickets.read_text(encoding="utf-8"))

    planner_raw = _read_json_object(args.cycle_dir / "planner.json", errors)
    worker_raw = _read_json_object(args.cycle_dir / "worker.json", errors)
    judge_raw = _read_json_object(args.cycle_dir / "judge.json", errors)

    if planner_raw is None or worker_raw is None or judge_raw is None:
        for error in errors:
            print(f"[dev-loop] ERROR: {error}")
        return 1

    if args.validate_schema:
        _validate_schemas(
            schema_dir=args.schema_dir,
            planner_raw=planner_raw,
            worker_raw=worker_raw,
            judge_raw=judge_raw,
            errors=errors,
        )

    planner = _parse_planner(planner_raw, errors)
    worker = _parse_worker(worker_raw, errors)
    judge = _parse_judge(judge_raw, errors)

    if planner is not None and worker is not None and judge is not None:
        _validate_cross_artifacts(planner, worker, judge, ticket_status_by_title, errors)

    if errors:
        print("[dev-loop] Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    if planner is None:
        raise RuntimeError("Planner artifact unexpectedly missing after successful validation.")

    print(f"[dev-loop] Cycle artifacts are valid: {planner.cycle_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

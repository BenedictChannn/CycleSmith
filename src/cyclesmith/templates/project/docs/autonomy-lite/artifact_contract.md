# Autonomy Artifact Contract

This contract defines cycle artifact structure and strict validation rules.

## Directory Layout

For each cycle id:

- `reports/dev_loop/<cycle_id>/planner.json`
- `reports/dev_loop/<cycle_id>/worker.json`
- `reports/dev_loop/<cycle_id>/judge.json`

All files must be valid UTF-8 JSON objects.

## JSON Schemas

Machine-readable schemas are versioned in:

- `schemas/dev_loop/planner.schema.json`
- `schemas/dev_loop/worker.schema.json`
- `schemas/dev_loop/judge.schema.json`

Validate a cycle bundle against these schemas by running:

```bash
cyclesmith validate -- --cycle-dir reports/dev_loop/<cycle_id> --validate-schema
```

## Cross-Artifact Invariants

1. `planner.cycle_id == worker.cycle_id == judge.cycle_id`.
2. `planner.ticket.title == worker.ticket_title == judge.ticket_title`.
3. Worker step ids must exactly match planner step ids.
4. Judge verdict must be consistent with worker checks and blockers.
5. Judge transition must match verdict:
   - `pass -> REVIEW`
   - `rework -> IN_PROGRESS`
   - `blocked -> BLOCKED`
6. When operator feedback is pending for a cycle, planner must include matching
   ids in `planner.operator_feedback_refs`.

## Ticket Invariants

- Planner ticket title must exist in `tickets.md`.
- Planner ticket status before cycle must be `IN_PROGRESS`.
- Follow-up tickets from judge output must use status `TODO`.

## Command Gate Invariants

Worker must report all quality gate commands:

- `uv run ruff check .`
- `uv run ruff format .`
- `uv run ty check .`
- `uv run pytest -q`
- one Rust check command path (`cargo test ...` or explicit documented skip reason)

## Invalid Cycle Conditions

A cycle is invalid when any condition occurs:

- missing artifact file
- schema field missing
- unsupported enum value
- cross-artifact mismatch
- verdict/transition mismatch
- ticket title not found in `tickets.md`

Invalid cycles must not update ticket status.

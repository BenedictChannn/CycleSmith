# Runbook Quickstart

## Local Setup

1. `uv sync`
2. `cyclesmith install-hooks`

## Start Or Continue Work

1. Ensure `tickets.md` has exactly one `IN_PROGRESS` ticket.
2. `cyclesmith runner -- run --goal reports/dev_loop/goal.json --max-actions 1`
3. Fill planner/worker/judge artifacts for the active cycle directory.
4. `cyclesmith runner -- run --goal reports/dev_loop/goal.json --max-actions 1`

## Before Commit

1. `cyclesmith validate -- --cycle-dir reports/dev_loop/<cycle_id> --validate-schema`
2. `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json ingest --cycle-dir reports/dev_loop/<cycle_id>`
3. `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json validate`
4. `uv run ruff check .`
5. `uv run ty check .`
6. `uv run pytest -q`


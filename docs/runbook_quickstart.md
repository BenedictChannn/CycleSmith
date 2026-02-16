# Runbook Quickstart

## Local Setup

1. `uv sync`
2. `cyclesmith install-hooks`

## Start Or Continue Work

1. Ensure `tickets.md` has exactly one `IN_PROGRESS` ticket.
2. Start/finalize loop:
   - `cyclesmith runner -- run --goal reports/dev_loop/goal.json --max-actions 1`
3. Execute roles:
   - Manual mode: fill planner/worker/judge artifacts for the active cycle directory.
   - Command mode: configure `goal.json.role_commands` (or pass `--planner-command/--worker-command/--judge-command`) and run with enough actions to complete the sequence.
4. Re-run loop:
   - `cyclesmith runner -- run --goal reports/dev_loop/goal.json --max-actions 1`

## Before Commit

1. `cyclesmith validate -- --cycle-dir reports/dev_loop/<cycle_id> --validate-schema`
2. `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json ingest --cycle-dir reports/dev_loop/<cycle_id>`
3. `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json validate`
4. `uv run ruff check .`
5. `uv run ty check .`
6. `uv run pytest -q`

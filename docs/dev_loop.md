# CycleSmith Dev Loop (Self-Hosted)

CycleSmith is developed using the same Planner -> Worker -> Judge workflow it
provides to other repositories.

## Canonical Flow

1. Keep exactly one `IN_PROGRESS` ticket in `tickets.md`.
2. Initialize goal config (first run or when objective changes):
   - `cyclesmith runner -- init-goal --goal reports/dev_loop/goal.json --tickets tickets.md --goal-id cyclesmith-self-host-goal --objective "Build CycleSmith with CycleSmith"`
3. Run deterministic start/finalize loop:
   - `cyclesmith runner -- run --goal reports/dev_loop/goal.json --max-actions 2`
4. Validate role artifacts:
   - `cyclesmith validate -- --cycle-dir reports/dev_loop/<cycle_id> --validate-schema`
5. Ingest + validate durable memory:
   - `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json ingest --cycle-dir reports/dev_loop/<cycle_id>`
   - `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json validate`
6. Run QA gates:
   - `uv run ruff check .`
   - `uv run ty check .`
   - `uv run pytest -q`

## Commit And PR Invariants

1. Non-maintenance changes must update `tickets.md`.
2. Non-maintenance changes must include at least one touched finalized cycle
   directory under `reports/dev_loop/<cycle_id>/` where cycle IDs match the
   runner naming format (`YYYYMMDD-<slug>-<nn>`).
3. Finalized cycle directories must contain:
   - `planner.json`
   - `worker.json`
   - `judge.json`
   - `runner_sync.json`
4. If runner cycle directories are touched, the same diff must also update
   `reports/dev_loop/memory_snapshot.json`.
5. CI must pass both required jobs:
   - `quality`
   - `workflow_compliance`

## Recovery Rules

1. Never overwrite historical cycle artifacts.
2. If a cycle is invalid, keep artifacts for audit and start a new cycle ID.
3. Keep blocked or rework tickets in `BLOCKED`/`IN_PROGRESS` with explicit
   follow-up TODOs.


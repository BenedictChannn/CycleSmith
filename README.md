# CycleSmith

CycleSmith is a reusable planner-worker-judge development loop toolkit.

Read first: `START_HERE.md`.

## What it Provides

- deterministic cycle runner (`run`, `init-goal`)
- strict artifact validator (planner, worker, judge)
- durable memory snapshot manager (`validate`, `ingest`, `ingest-batch`, `prune-stale`)
- git hook installer + ticket-loop enforcement
- workflow compliance checker for self-hosted development
- project bootstrap templates (`docs`, schemas, sample cycle bundle, hooks, reports scaffold)

## Install

```bash
uv sync
```

## CLI

```bash
cyclesmith init --target . --install-hooks
cyclesmith runner -- init-goal --goal reports/dev_loop/goal.json
cyclesmith runner -- run --goal reports/dev_loop/goal.json --max-actions 2
cyclesmith validate -- --cycle-dir reports/dev_loop/example_cycle --validate-schema
cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json validate
```

## Self-Hosted Workflow

CycleSmith is built with CycleSmith. For any non-maintenance change:

1. Update `tickets.md`.
2. Include at least one finalized cycle under `reports/dev_loop/<cycle_id>/`.
3. Update `reports/dev_loop/memory_snapshot.json` when runner cycle artifacts change.

Local compliance check:

```bash
uv run python scripts/check_workflow_compliance.py --base-ref HEAD~1 --head-ref HEAD
```

## Planning Docs

- `START_HERE.md`
- `tickets.md`
- `docs/dev_loop.md`
- `docs/runbook_quickstart.md`
- `docs/benchmark_protocol.md`
- `docs/roadmap.md`
- `docs/plans/phase2_plan.md`
- `docs/migration/streamsafe_context.md`

## Quality Checks

```bash
uv run ruff check .
uv run ruff check . --fix
uv run ruff format .
uv run ty check .
uv run pytest -q
```

# Contributor Runbook For Multi-Repo Adoption

This runbook is the standard rollout procedure for adopting CycleSmith in an
existing repository.

## 1) Bootstrap The Repository

1. Install CycleSmith dependencies:
   - `uv sync`
2. Initialize files and hooks:
   - `cyclesmith init --target . --install-hooks`
3. Verify template metadata:
   - `cyclesmith template-status --repo-root .`
4. Confirm required files exist:
   - `START_HERE.md`
   - `tickets.md`
   - `reports/dev_loop/goal.json`
   - `reports/dev_loop/memory_snapshot.json`
   - `schemas/dev_loop/*.schema.json`
   - `docs/autonomy-lite/*`

## 2) Configure Goal And Ticket Policy

1. Keep exactly one `IN_PROGRESS` ticket at a time.
2. Initialize or refresh goal configuration:
   - `cyclesmith runner -- init-goal --goal reports/dev_loop/goal.json`
3. Select policy pack in `reports/dev_loop/goal.json`:
   - `fast-local`
   - `shared-branch`
   - `ci-main`
4. Optional: configure role command execution by adding `role_commands` in
   `reports/dev_loop/goal.json`.

## 3) Run Development Cycles

1. Start/finalize loop:
   - `cyclesmith runner -- run --goal reports/dev_loop/goal.json --max-actions 2`
2. Manual mode:
   - produce `planner.json`, `worker.json`, `judge.json` in active cycle dir.
3. Command mode:
   - configure role commands and run enough actions to execute
     `planner -> worker -> judge -> finalize`.
4. Validate artifacts:
   - `cyclesmith validate -- --cycle-dir reports/dev_loop/<cycle_id> --validate-schema`
5. Sync memory:
   - `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json ingest --cycle-dir reports/dev_loop/<cycle_id>`
   - `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json validate`

## 4) CI And Branch Safety

1. Add CI workflow (already included from template):
   - required jobs: `quality`, `workflow_compliance`.
2. In GitHub branch protection, require status checks before merge:
   - `quality`
   - `workflow_compliance`
3. Disallow direct pushes to protected branches where applicable.

## 5) Template Upgrades

1. Create a feature branch for template upgrades.
2. Check current status:
   - `cyclesmith template-status --repo-root .`
3. Apply latest templates:
   - `cyclesmith init --target . --force`
4. Re-check status and expect `up_to_date`.
5. Review local customizations in any conflicted files before merge.

## 6) PR Requirements

For non-maintenance changes:

1. Update `tickets.md`.
2. Include at least one finalized runner cycle directory under
   `reports/dev_loop/<cycle_id>/`.
3. Update `reports/dev_loop/memory_snapshot.json` when cycle artifacts change.
4. Ensure CI passes with the same local gates:
   - `uv run ruff check .`
   - `uv run ruff format .`
   - `uv run ty check .`
   - `uv run pytest -q`

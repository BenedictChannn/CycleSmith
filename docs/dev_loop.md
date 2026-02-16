# CycleSmith Dev Loop (Self-Hosted)

CycleSmith is developed using the same Planner -> Worker -> Judge workflow it
provides to other repositories.

## Canonical Flow

1. Keep exactly one `IN_PROGRESS` ticket in `tickets.md`.
2. Initialize goal config (first run or when objective changes):
   - `cyclesmith runner -- init-goal --goal reports/dev_loop/goal.json --tickets tickets.md --tickets-backend markdown --goal-id cyclesmith-self-host-goal --objective "Build CycleSmith with CycleSmith"`
3. Run deterministic start/finalize loop:
   - `cyclesmith runner -- run --goal reports/dev_loop/goal.json --tickets tickets.md --tickets-backend markdown --max-actions 2`
4. Produce role artifacts:
   - Manual mode: fill `planner.json`, `worker.json`, `judge.json` in the active cycle directory.
   - Command mode: configure role commands so runner executes `planner -> worker -> judge` automatically.
5. Validate role artifacts:
   - `cyclesmith validate -- --cycle-dir reports/dev_loop/<cycle_id> --validate-schema`
6. Ingest + validate durable memory:
   - `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json ingest --cycle-dir reports/dev_loop/<cycle_id>`
   - `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json validate`
7. Run QA gates:
   - `uv run ruff check .`
   - `uv run ty check .`
   - `uv run pytest -q`
8. Check template upgrade state when updating toolkit versions:
   - `cyclesmith template-status --repo-root .`

## Role Execution Modes

Runner supports two execution modes:

1. `manual` (default): runner starts/finalizes cycles and waits for role artifacts.
2. `command`: runner invokes configured role commands when artifacts are missing.

Configure command mode via `goal.json.role_commands`:

```json
{
  "role_commands": {
    "planner": ["python", "scripts/role_driver.py"],
    "worker": ["python", "scripts/role_driver.py"],
    "judge": ["python", "scripts/role_driver.py"]
  }
}
```

CLI overrides are also available:

- `--planner-command <tokens...>`
- `--worker-command <tokens...>`
- `--judge-command <tokens...>`

When runner executes a role command, it sets environment variables:

- `CYCLESMITH_ROLE`
- `CYCLESMITH_GOAL_ID`
- `CYCLESMITH_CYCLE_ID`
- `CYCLESMITH_CYCLE_DIR`
- `CYCLESMITH_TICKET_TITLE`
- `CYCLESMITH_TICKETS_PATH`
- `CYCLESMITH_TICKETS_BACKEND`
- `CYCLESMITH_OPERATOR_FEEDBACK_PATH`
- `CYCLESMITH_PENDING_FEEDBACK_ID` (only when feedback is pending)

## Policy Packs

`goal.json.policy_pack` selects enum-backed workflow defaults:

1. `fast-local`: prefer `WIP` over `TODO` when no `IN_PROGRESS`; prune every 5 cycles (dry-run).
2. `shared-branch`: use `IN_PROGRESS` first then `TODO`; prune every 2 cycles.
3. `ci-main`: use `IN_PROGRESS` first then `TODO`; prune every cycle.

`goal.json.prune_profile` is still accepted for compatibility, but `policy_pack`
is canonical.

## Ticket Backends

Runner/validator support explicit backend selection:

1. `markdown` (default): `tickets.md`
2. `json`: `tickets.json`

JSON backend shape:

```json
{
  "version": 1,
  "tickets": [
    {
      "task_type": "CHORE",
      "task": "Example task",
      "description": "Example description",
      "status": "TODO"
    }
  ]
}
```

## Optional Operator Feedback

If `reports/dev_loop/operator_feedback.json` is present and applies to the
selected ticket, runner requires planner acknowledgement:

1. Feedback contract is defined in `docs/operator_feedback_contract.md`.
2. `planner.json` must include `operator_feedback_refs` with the pending
   `feedback_id`.

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

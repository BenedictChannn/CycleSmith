# Autonomy Lite (Planner -> Worker -> Judge)

This package defines a strict, file-driven execution loop that mirrors long-running agent operations without introducing a separate application runtime.

## Goal

Run repeatable implementation cycles where:

1. `Planner` translates one active ticket into a constrained implementation plan.
2. `Worker` executes only the approved plan.
3. `Judge` reviews output and decides whether the ticket can move forward.

The loop is deterministic because each role has a fixed input set, fixed output schema, and fixed transition rules.

## Required Inputs

- `tickets.md`
- `START_HERE.md`
- `docs/dev_loop.md`
- `docs/benchmark_protocol.md` (when benchmark-facing code is touched)
- `docs/runbook_quickstart.md`
- `reports/dev_loop/goal.json` (for goal-driven continuous runner mode)

## Required Artifacts Per Cycle

Create a cycle folder:

- `reports/dev_loop/<cycle_id>/planner.json`
- `reports/dev_loop/<cycle_id>/worker.json`
- `reports/dev_loop/<cycle_id>/judge.json`

Artifact schemas and transition rules are defined in `docs/autonomy-lite/artifact_contract.md`.

## Role Specs

- `docs/autonomy-lite/role_planner.md`
- `docs/autonomy-lite/role_worker.md`
- `docs/autonomy-lite/role_judge.md`
- `docs/autonomy-lite/operator_runbook.md`
- `docs/autonomy-lite/memory_snapshot_contract.md`

## Example Bundle

Use the committed reference bundle for validator dry runs:

- `reports/dev_loop/example_cycle/planner.json`
- `reports/dev_loop/example_cycle/worker.json`
- `reports/dev_loop/example_cycle/judge.json`

## Enforcement

Validate artifacts after each cycle:

- `cyclesmith validate -- --cycle-dir reports/dev_loop/<cycle_id> --validate-schema`
- `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json ingest --cycle-dir reports/dev_loop/<cycle_id>`
- `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json validate`
- `cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json ingest-batch --strict --strict-report reports/dev_loop/strict_report.json --cycles-root reports/dev_loop` (for parallel cycle replay + machine-readable strict failure report)
- `cyclesmith runner -- run --goal reports/dev_loop/goal.json --max-actions 2` (for deterministic ticket selection + cycle start/finalize orchestration)

If validation fails, the cycle is invalid and cannot advance ticket status.

# Role Contract: Worker

The Worker executes the Planner output and records exact implementation evidence.

## Non-negotiable Rules

- Execute only the plan in `planner.json`.
- Do not introduce unrelated refactors.
- Do not skip required checks without recording why.
- Do not change the role schema fields.
- Do not edit `planner.json`.

## Inputs

- `reports/dev_loop/<cycle_id>/planner.json`
- Ticket and project docs referenced by planner scope
- Current branch working tree

## Procedure (Must Follow In Order)

1. Read `planner.json` and restate the objective internally.
2. Execute steps in order (`S1`, `S2`, ...).
3. Record each step result as `done`, `blocked`, or `skipped`.
4. Run quality gates and Rust checks relevant to touched code.
5. Produce `worker.json` with files touched, checks, blockers, and result status.

## Required Output File

- `reports/dev_loop/<cycle_id>/worker.json`

## Required Output Schema

```json
{
  "cycle_id": "string",
  "ticket_title": "string",
  "step_results": [
    {
      "step_id": "S1",
      "status": "done|blocked|skipped",
      "notes": "string",
      "files_touched": ["string"],
      "commands_run": ["string"]
    }
  ],
  "checks": {
    "ruff_check": "pass|fail|not_run",
    "ruff_format": "pass|fail|not_run",
    "ty_check": "pass|fail|not_run",
    "pytest": "pass|fail|not_run",
    "rust_checks": "pass|fail|not_run"
  },
  "result_status": "implemented|partial|blocked",
  "blockers": ["string"],
  "next_role": "JUDGE"
}
```

## Output Quality Gates

- Every planner step id must appear exactly once in `step_results`.
- `result_status=blocked` requires non-empty `blockers`.
- If any critical check fails, `result_status` cannot be `implemented`.
- `next_role` must be exactly `JUDGE`.


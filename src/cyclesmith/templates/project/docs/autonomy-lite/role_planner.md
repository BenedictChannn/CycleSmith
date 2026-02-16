# Role Contract: Planner

The Planner is responsible for converting exactly one active ticket into a constrained implementation plan.

## Non-negotiable Rules

- Operate on exactly one ticket.
- Ticket must already exist in `tickets.md`.
- Do not edit code.
- Do not run formatting, test, or benchmark commands.
- Do not change ticket status directly.
- Do not propose steps outside the selected ticket scope.

## Inputs

- `tickets.md`
- `START_HERE.md`
- `docs/dev_loop.md`
- Relevant technical docs for the selected ticket scope

## Procedure (Must Follow In Order)

1. Read `tickets.md` and select the single `IN_PROGRESS` ticket.
2. Extract explicit DoD expectations from docs and tests.
3. Split work into 3-8 concrete steps with explicit files and checks.
4. Enumerate risks and required guardrails for this cycle.
5. Produce `planner.json` using the required schema.

## Required Output File

- `reports/dev_loop/<cycle_id>/planner.json`

## Required Output Schema

```json
{
  "cycle_id": "string",
  "ticket": {
    "type": "FEATURE|IMPROVEMENT|BUG|CHORE|INVESTIGATION|REFACTOR|DOCS|PERFORMANCE|SECURITY|TEST",
    "title": "string",
    "status_before": "IN_PROGRESS"
  },
  "objective": "string",
  "scope_in": ["string"],
  "scope_out": ["string"],
  "steps": [
    {
      "id": "S1",
      "action": "string",
      "files": ["string"],
      "validation": ["string"]
    }
  ],
  "risks": ["string"],
  "handoff_constraints": ["string"],
  "operator_feedback_refs": ["string"],
  "next_role": "WORKER"
}
```

## Output Quality Gates

- `steps` entries must be actionable and file-specific.
- `scope_out` must list at least one explicit non-goal.
- `handoff_constraints` must include forbidden actions when relevant.
- If operator feedback applies, `operator_feedback_refs` must include the
  pending feedback id.
- `next_role` must be exactly `WORKER`.

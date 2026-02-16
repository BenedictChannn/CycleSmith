# Role Contract: Judge

The Judge decides whether the Worker output is acceptable and which ticket transition is allowed.

## Non-negotiable Rules

- Review against planner scope, not personal preference.
- Prioritize correctness, regressions, and missing validation evidence.
- Use explicit severity labels for every finding.
- Do not edit implementation code in this role.
- Do not mark pass if required checks failed or were skipped without justification.

## Inputs

- `reports/dev_loop/<cycle_id>/planner.json`
- `reports/dev_loop/<cycle_id>/worker.json`
- Git diff for the cycle
- Test outputs and benchmark outputs (if run)

## Procedure (Must Follow In Order)

1. Verify worker execution stayed within planner scope.
2. Evaluate check outcomes and test evidence.
3. Record findings with severity and required action.
4. Decide verdict and allowed ticket transition.
5. Generate follow-up tickets when unresolved work remains.
6. Produce `judge.json`.

## Required Output File

- `reports/dev_loop/<cycle_id>/judge.json`

## Required Output Schema

```json
{
  "cycle_id": "string",
  "ticket_title": "string",
  "findings": [
    {
      "severity": "high|medium|low",
      "where": "path:line",
      "issue": "string",
      "required_action": "string"
    }
  ],
  "qa_verification": [
    {
      "command": "string",
      "result": "pass|fail|not_run",
      "evidence": "string"
    }
  ],
  "verdict": "pass|rework|blocked",
  "ticket_transition": "REVIEW|IN_PROGRESS|BLOCKED",
  "follow_up_tickets": [
    {
      "task_type": "FEATURE|IMPROVEMENT|BUG|CHORE|INVESTIGATION|REFACTOR|DOCS|PERFORMANCE|SECURITY|TEST",
      "task": "string",
      "description": "string",
      "status": "TODO"
    }
  ],
  "next_cycle_focus": "string"
}
```

## Output Quality Gates

- `verdict=pass` requires:
  - no `high` severity findings
  - no failed required checks
  - ticket transition set to `REVIEW`
- `verdict=rework` requires transition `IN_PROGRESS`.
- `verdict=blocked` requires transition `BLOCKED`.
- Follow-up tickets are mandatory when findings are unresolved.


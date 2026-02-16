# Operator Feedback Contract

`reports/dev_loop/operator_feedback.json` is an optional operator-to-runner
contract used to force planner acknowledgement in the next cycle.

## Schema

```json
{
  "version": 1,
  "feedback_id": "OFB-20260216-01",
  "target_ticket": "*",
  "summary": "string",
  "required_planner_action": "string"
}
```

## Semantics

1. `feedback_id` must be unique for each new operator directive.
2. `target_ticket` can be:
   - `*` (applies to whichever ticket runner selects next)
   - an exact ticket title
3. If feedback applies to the selected ticket, runner sets a pending feedback
   requirement for that cycle.
4. Finalization fails unless `planner.json.operator_feedback_refs` includes the
   pending `feedback_id`.


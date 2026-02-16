# Operator Feedback Contract

`reports/dev_loop/operator_feedback.json` is optional. When present and
applicable, planner must acknowledge it in `planner.json.operator_feedback_refs`
before runner finalization can succeed.

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

## Rule

If feedback applies to the active ticket, planner must include the matching
`feedback_id` in `operator_feedback_refs`.


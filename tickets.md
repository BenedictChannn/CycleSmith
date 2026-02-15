# CYCLESMITH Tickets

| Task Type | Task | Description | Status |
| --- | --- | --- | --- |
| FEATURE | Bootstrap CycleSmith reusable dev-loop toolkit | Create package scaffold, reusable runner/validator/memory modules, templates, and CLI entrypoints | COMPLETED |
| TEST | Add deterministic smoke coverage for toolkit workflows | Add runtime tests for init/hooks/validator/memory/runner behavior | COMPLETED |
| DOCS | Port Streamsafe context and planning into CycleSmith | Add migration notes, roadmap, phase plan, and startup handoff docs for standalone development | COMPLETED |
| CHORE | Add CI workflow for lint, type, and smoke tests | Add GitHub Actions pipeline for `ruff`, `ty`, and `pytest` gates on push/PR | IN_PROGRESS |
| FEATURE | Add operator feedback ingestion for cycle runner | Support optional `operator_feedback.json` in runner finalize/start cycle flow and enforce planner consumption | TODO |
| IMPROVEMENT | Add planner policy packs for multi-project defaults | Provide profile-based defaults for ticket selection, prune cadence, and follow-up generation | TODO |
| FEATURE | Add ticket backend abstraction | Allow markdown (default) and JSON backends behind a strict typed interface without dynamic attributes | TODO |
| DOCS | Add contributor runbook for using CycleSmith across repos | Document rollout checklist and migration strategy for adopting templates in existing projects | TODO |

---

## Backlog (Future Ideas)

- [FEATURE] GitHub issue sync adapter for tickets
- [IMPROVEMENT] Branch/PR automation helpers
- [FEATURE] Long-run campaign orchestration with pause/resume and bounded budgets


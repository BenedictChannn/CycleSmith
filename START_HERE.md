# START HERE - CYCLESMITH Agent Handoff

This is the first file to read before continuing implementation in CycleSmith.

## 1) Immediate Objective

- Continue development directly in this repository.
- Work from `tickets.md` with the single `IN_PROGRESS` ticket first.
- Keep each PR scoped to one logical unit.

## 2) Required Read Order

1. `tickets.md`
2. `README.md`
3. `docs/dev_loop.md`
4. `docs/runbook_quickstart.md`
5. `docs/benchmark_protocol.md`
6. `docs/operator_feedback_contract.md`
7. `docs/roadmap.md`
8. `docs/plans/phase2_plan.md`
9. `docs/plans/phase3_plan.md`
10. `docs/contributor_runbook.md`
11. `docs/template_versioning.md`
12. `docs/migration/streamsafe_context.md`
13. `src/cyclesmith/templates/project/docs/autonomy-lite/README.md`
14. `src/cyclesmith/templates/project/docs/autonomy-lite/artifact_contract.md`
15. `src/cyclesmith/templates/project/docs/autonomy-lite/operator_runbook.md`
16. `src/cyclesmith/templates/project/docs/autonomy-lite/memory_snapshot_contract.md`

## 3) Execution Rules

- Use conventional commits: `type(scope): summary`.
- Do not mix unrelated work in a single commit.
- Keep ticket count non-decreasing.
- When closing an implementation ticket, add follow-up work if any meaningful next step remains.
- Do not use `getattr`, `setattr`, or `hasattr`.

## 4) Validation Commands

Preferred:

- `uv run ruff check .`
- `uv run ruff check . --fix`
- `uv run ruff format .`
- `uv run ty check .`
- `uv run pytest -q`
- `uv run python scripts/check_workflow_compliance.py --base-ref HEAD~1 --head-ref HEAD`

Current environment fallback (when uv dependency resolution is blocked):

- `C:/Users/bened/Documents/benedict_codebases/stream_safe/.venv/Scripts/ruff.exe check src tests pyproject.toml README.md schemas`
- `C:/Users/bened/Documents/benedict_codebases/stream_safe/.venv/Scripts/ruff.exe format src tests`
- `C:/Users/bened/Documents/benedict_codebases/stream_safe/.venv/Scripts/ty.exe check .`
- `C:/Users/bened/Documents/benedict_codebases/stream_safe/.venv/Scripts/pytest.exe -q -p no:tmpdir`

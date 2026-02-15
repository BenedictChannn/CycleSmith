# START HERE - CYCLESMITH Agent Handoff

This is the first file to read before continuing implementation in CycleSmith.

## 1) Immediate Objective

- Continue development directly in this repository.
- Work from `tickets.md` with the single `IN_PROGRESS` ticket first.
- Keep each PR scoped to one logical unit.

## 2) Required Read Order

1. `tickets.md`
2. `README.md`
3. `docs/roadmap.md`
4. `docs/plans/phase2_plan.md`
5. `docs/migration/streamsafe_context.md`
6. `src/cyclesmith/templates/project/docs/autonomy-lite/README.md`
7. `src/cyclesmith/templates/project/docs/autonomy-lite/artifact_contract.md`
8. `src/cyclesmith/templates/project/docs/autonomy-lite/operator_runbook.md`
9. `src/cyclesmith/templates/project/docs/autonomy-lite/memory_snapshot_contract.md`

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

Current environment fallback (when uv dependency resolution is blocked):

- `C:/Users/bened/Documents/benedict_codebases/stream_safe/.venv/Scripts/ruff.exe check src tests pyproject.toml README.md schemas`
- `C:/Users/bened/Documents/benedict_codebases/stream_safe/.venv/Scripts/ruff.exe format src tests`
- `C:/Users/bened/Documents/benedict_codebases/stream_safe/.venv/Scripts/ty.exe check .`
- `C:/Users/bened/Documents/benedict_codebases/stream_safe/.venv/Scripts/pytest.exe -q -p no:tmpdir`


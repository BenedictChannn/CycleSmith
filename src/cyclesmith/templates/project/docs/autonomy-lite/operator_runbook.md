# Autonomy Lite Operator Runbook

This runbook is the required operating procedure for Planner -> Worker -> Judge loops.

## 1) Preconditions

1. Branch is feature-scoped and active.
2. Hooks are installed:
   - `cyclesmith install-hooks`
3. Exactly one ticket is `IN_PROGRESS` in `tickets.md`.
4. You have read:
   - `START_HERE.md`
   - `docs/dev_loop.md`
   - `docs/autonomy-lite/artifact_contract.md`

## 2) Cycle Setup

1. Create a cycle id:
   - format: `YYYYMMDD-<short-scope>-<nn>`
   - example: `20260213-devloop-01`
2. Create cycle directory:
   - `mkdir reports/dev_loop/<cycle_id>`
3. Copy starting shape from:
   - `reports/dev_loop/example_cycle/`

## 2.1) Goal-Driven Runner Mode (Recommended)

Use the runner when you want deterministic ticket pickup and continuous cycle
handoff until a goal target is closed:

```bash
cyclesmith runner -- run --goal reports/dev_loop/goal.json --max-actions 2
```

Runner behavior:

1. If an active cycle already has `planner.json`, `worker.json`, and `judge.json`, it finalizes the cycle (validator, ticket transition, follow-up tickets, memory sync).
2. If no active cycle exists, it selects ticket by policy (`IN_PROGRESS` first, else top-most `TODO`) and scaffolds the next cycle.
3. It writes `reports/dev_loop/runner_state.json` and per-cycle `runner_sync.json` for traceability.

Goal file initialization:

```bash
cyclesmith runner -- init-goal --goal reports/dev_loop/goal.json
```

## 3) Planner Execution (Mandatory Output)

1. Read `tickets.md`; use the single `IN_PROGRESS` ticket only.
2. Create `reports/dev_loop/<cycle_id>/planner.json`.
3. Ensure planner output includes:
   - explicit in-scope files
   - explicit out-of-scope constraints
   - 3-8 ordered steps with ids `S1..Sn`
   - `next_role=WORKER`
4. Planner must not edit implementation code.

## 4) Worker Execution (Mandatory Output)

1. Execute planner steps in order.
2. Create `reports/dev_loop/<cycle_id>/worker.json`.
3. Record for each step:
   - `done|blocked|skipped`
   - files touched
   - commands run
4. Record quality gates in `checks`:
   - `ruff_check`
   - `ruff_format`
   - `ty_check`
   - `pytest`
   - `rust_checks`
5. Worker must not modify planner scope or schema fields.

## 5) Judge Execution (Mandatory Output)

1. Compare worker output against planner scope.
2. Create `reports/dev_loop/<cycle_id>/judge.json`.
3. Record findings with severity (`high|medium|low`) and required action.
4. Set verdict:
   - `pass` -> transition `REVIEW`
   - `rework` -> transition `IN_PROGRESS`
   - `blocked` -> transition `BLOCKED`
5. If verdict is not `pass`, add at least one follow-up TODO ticket.

## 6) Validation Gate (Hard Requirement)

Run:

```bash
cyclesmith validate -- --cycle-dir reports/dev_loop/<cycle_id> --validate-schema
```

Rules:

1. If validator fails, do not transition ticket status.
2. Fix artifacts or implementation evidence until validator passes.
3. Re-run validator after every artifact edit.

## 6.1) Memory Gate (Hard Requirement)

Update and validate durable memory after judge output is finalized:

```bash
cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json ingest --cycle-dir reports/dev_loop/<cycle_id>
cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json validate
```

Rules:

1. Keep memory entries high-signal and provenance-backed.
2. Do not store raw chain-of-thought or free-form reasoning transcripts.
3. If memory validation fails, fix snapshot data before commit.

Optional cleanup (recommended every few cycles):

```bash
cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json prune-stale --current-cycle <cycle_id> --max-cycle-lag 5 --cycles-root reports/dev_loop
```

Cadence policy by workflow profile:

1. `fast-local`: run every 5 cycles with `--max-cycle-lag 8`, start with `--dry-run`.
2. `shared-branch`: run every 2 cycles (and before PR) with `--max-cycle-lag 5 --stale-unknown`.
3. `ci-main`: run every cycle with `--max-cycle-lag 3 --stale-unknown`.

Parallel-cycle merge (when multiple branches produced cycle artifacts):

```bash
cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json ingest-batch --strict --strict-report reports/dev_loop/strict_report.json --cycles-root reports/dev_loop
```

## 7) QA Gate (Hard Requirement)

Run:

```bash
uv run ruff check .
uv run ruff check . --fix
uv run ruff format .
uv run ty check .
uv run pytest -q
# Optional, only if repository contains Rust crates:
# cargo test
```

Notes:

1. If QA fails, Judge verdict must not be `pass`.
2. Rust command may use documented platform equivalent in CI/Linux.

## 8) Commit Gate

Before commit:

1. Update `tickets.md`.
2. Append one entry to `docs/agent_execution_log.md`.
3. Ensure `tickets.md` is staged with implementation changes.

Then commit with conventional format:

- `feat(dev-loop): ...`
- `chore(dev-loop): ...`
- `docs(dev-loop): ...`

## 9) Recovery Procedure

Use this when cycle state is invalid or inconsistent.

1. Preserve artifacts in `reports/dev_loop/<cycle_id>/`.
2. Set ticket status:
   - `IN_PROGRESS` if rework is possible now
   - `BLOCKED` if waiting on external dependency
3. Add follow-up TODO ticket with root cause and acceptance check.
4. Start a new cycle id for the next attempt; never overwrite past cycle artifacts.

## 10) Prohibited Actions

1. No out-of-scope implementation without ticket updates.
2. No schema edits to role artifacts mid-cycle.
3. No `getattr`, `setattr`, `hasattr`.
4. No silent skipping of required checks.
5. No marking `pass` with unresolved high-severity findings.

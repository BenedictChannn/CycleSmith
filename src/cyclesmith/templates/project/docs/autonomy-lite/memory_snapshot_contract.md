# Memory Snapshot Contract

`reports/dev_loop/memory_snapshot.json` is the durable, machine-readable memory for autonomy cycles.

It stores only high-signal context that should survive across cycles:

- durable decisions
- known regressions and risks
- environment quirks
- forward-looking opportunities and TODO hints

It must not contain free-form internal reasoning transcripts.

## Design Principles

1. Agent-efficient:
   - compact schema
   - deterministic enums
   - stable field names for reliable parsing and low token cost
2. Human-auditable:
   - explicit provenance (`source_cycle`, `source_file`)
   - explicit confidence and status
3. Tool-agnostic:
   - no Codex/Cursor-specific fields
   - any agent or human can read and update the same file format

## Top-Level Schema

```json
{
  "version": 1,
  "updated_at": "2026-02-13T00:00:00Z",
  "current_focus": "string",
  "items": []
}
```

### Fields

- `version`:
  - integer
  - currently fixed to `1`
- `updated_at`:
  - UTC timestamp in ISO-8601 with `Z` suffix
- `current_focus`:
  - short string describing the current execution focus
- `items`:
  - list of memory items (possibly empty)

## Memory Item Schema

```json
{
  "id": "MEM-0001",
  "title": "Use scripts/cargo_msvc.cmd for rust checks on Windows",
  "kind": "environment",
  "status": "active",
  "confidence": "high",
  "detail": "PATH resolves link.exe to Git utility in this environment; rust builds should run via scripts/cargo_msvc.cmd.",
  "source_cycle": "20260213-devloop-01",
  "source_file": "docs/agent_execution_log.md",
  "last_verified_cycle": "20260213-devloop-01",
  "tags": ["windows", "rust", "toolchain"]
}
```

### Allowed Enums

- `kind`:
  - `decision`
  - `risk`
  - `regression`
  - `environment`
  - `opportunity`
  - `todo_hint`
- `status`:
  - `active`
  - `resolved`
  - `stale`
- `confidence`:
  - `low`
  - `medium`
  - `high`

## Invariants

1. `id` values are unique.
2. `title`, `detail`, `source_cycle`, and `source_file` are non-empty strings.
3. `tags` is a list of non-empty strings.
4. Only `active` items should affect planning decisions directly.
5. `resolved` and `stale` items remain for historical traceability.

## Update Rule

Use `cyclesmith memory` to update/validate this file:

- `validate`: check schema and invariants
- `ingest`: pull durable memory from a cycle's `worker.json` and `judge.json`
- `prune-stale`: mark old active items as stale based on cycle lag
- `ingest-batch`: replay multiple cycle artifacts deterministically

Pruning example:

```bash
cyclesmith memory -- \
  --memory reports/dev_loop/memory_snapshot.json \
  prune-stale \
  --current-cycle 20260213-devloop-01 \
  --max-cycle-lag 5 \
  --cycles-root reports/dev_loop
```

Parallel-cycle merge pattern:

```bash
cyclesmith memory -- \
  --memory reports/dev_loop/memory_snapshot.json \
  ingest-batch \
  --strict \
  --strict-report reports/dev_loop/strict_report.json \
  --cycles-root reports/dev_loop
```

`ingest-batch` avoids manual merge conflicts by replaying cycle artifacts in deterministic directory-name order.
`--strict` makes the command fail when selected cycle directories are missing required artifacts or contain invalid schema payloads.
`--strict-report` writes machine-readable failure details (`error_code`, per-cycle reasons) for CI/local triage.

## Prune Cadence Policy

Run `prune-stale` on a fixed cadence so active memory does not drift across long autonomy runs.

| Profile | Run cadence | `--max-cycle-lag` | `--stale-unknown` | Mode |
| --- | --- | --- | --- | --- |
| `fast-local` | every 5 cycles | `8` | omit | start with `--dry-run`, then apply |
| `shared-branch` | every 2 cycles and before opening PR | `5` | set | apply |
| `ci-main` | every cycle in CI/dev-loop checks | `3` | set | apply |

Recommended commands:

```bash
# fast-local
cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json prune-stale --current-cycle <cycle_id> --max-cycle-lag 8 --cycles-root reports/dev_loop --dry-run

# shared-branch
cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json prune-stale --current-cycle <cycle_id> --max-cycle-lag 5 --cycles-root reports/dev_loop --stale-unknown

# ci-main
cyclesmith memory -- --memory reports/dev_loop/memory_snapshot.json prune-stale --current-cycle <cycle_id> --max-cycle-lag 3 --cycles-root reports/dev_loop --stale-unknown
```

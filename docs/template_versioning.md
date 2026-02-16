# Template Versioning And Upgrade Path

CycleSmith writes template metadata into each initialized repository:

- `.cyclesmith/template_version.json`

This metadata is the source of truth for upgrade safety checks.

## Metadata Contract

```json
{
  "version": 1,
  "template_version": "0.1.0",
  "toolkit_version": "0.1.0",
  "updated_at": "2026-02-16T00:00:00Z",
  "sync_mode": "full"
}
```

Fields:

1. `version`: metadata schema version (currently `1`).
2. `template_version`: template bundle version that was last applied.
3. `toolkit_version`: CycleSmith package version used for initialization.
4. `updated_at`: UTC timestamp for metadata write.
5. `sync_mode`:
   - `full`: all tracked template files were applied.
   - `partial`: one or more files were skipped during init (usually because
     `--force` was not used and local files already existed).

## Check Upgrade Status

```bash
cyclesmith template-status --repo-root .
cyclesmith template-status --repo-root . --json
```

Status values:

1. `up_to_date`
2. `upgrade_available`
3. `partial_sync`
4. `local_ahead`
5. `version_mismatch`
6. `not_initialized`

## Recommended Upgrade Workflow

1. Create a feature branch.
2. Inspect current status:
   - `cyclesmith template-status --repo-root .`
3. Apply latest templates:
   - `cyclesmith init --target . --force`
4. Re-run status check and confirm `up_to_date`.
5. Resolve any merge conflicts or intentional local customizations.
6. Run quality gates and open a PR.

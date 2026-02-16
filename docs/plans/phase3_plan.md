# Phase 3 Plan - Multi-Repo Adoption

## Goal

Prove CycleSmith can be adopted safely across repositories with predictable
upgrade behavior and low operator friction.

## Scope

1. Reference adoption run:
   - apply CycleSmith in at least one external repository
   - run one full cycle and verify gates/runner behavior
   - capture migration notes and required template adjustments
2. Upgrade strategy:
   - template metadata contract + status command
   - documented upgrade workflow for maintainers
3. Automation helpers:
   - branch/PR helper commands for cycle completion handoff
   - optional GitHub issue sync adapter for ticket mirroring

## Out Of Scope

- hosted control plane
- organization-wide policy enforcement service
- repository-specific benchmark content logic

## Acceptance Criteria

- external repo adoption documented with concrete outcomes
- `cyclesmith template-status` provides actionable upgrade state
- contributor runbook includes repeatable upgrade and migration steps
- branch/PR helper workflow defined and tested

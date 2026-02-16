# Phase 2 Plan - Execution Hardening

## Goal

Make CycleSmith production-ready for daily use across repositories by improving
workflow reliability, CI confidence, and operator control.

## Scope

1. CI gates:
   - add workflow for `ruff`, `ty`, `pytest`
   - add workflow-compliance gate enforcing cycle artifacts, memory sync, and ticket coupling
   - ensure deterministic execution on Windows/Linux runners
2. Operator feedback ingestion:
   - optional `operator_feedback.json` contract
   - planner consumption requirement in next cycle
3. Planner policy packs:
   - profile defaults for selection/pruning/follow-up behavior
   - explicit enum-backed profiles
4. Ticket backend boundaries:
   - typed backend interface
   - markdown backend retained as default implementation

## Out of Scope

- cloud-hosted orchestration control plane
- repository-specific benchmark logic
- direct dependency on Streamsafe internals

## Acceptance Criteria

- CI passes on PRs with same gates used locally
- non-maintenance PRs fail when workflow-compliance invariants are violated
- runner can consume operator feedback without breaking existing flows
- policy packs selectable via explicit profile enum
- all new behavior covered by tests and reflected in docs/tickets

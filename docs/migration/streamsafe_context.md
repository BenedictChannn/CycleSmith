# Migration Context - From Streamsafe to CycleSmith

## Why This Migration Exists

The autonomy-loop system started inside `stream_safe` as product-local tooling.
CycleSmith is now the dedicated internal product for reusable dev-loop
orchestration across projects.

## What Was Ported

- deterministic cycle runner logic
- planner/worker/judge artifact validator
- durable memory snapshot ingest/validate/prune flows
- ticket-loop enforcement and hook installer
- artifact schemas and operator-facing autonomy docs
- example cycle bundle and goal/memory scaffolds

## What Was Intentionally Not Ported

- Streamsafe benchmark logic and acceptance comparator details
- Streamsafe-specific Rust/Python runtime integrations
- product-specific performance/security tickets

## Active Continuity Decisions

1. CycleSmith is now the source of truth for loop tooling evolution.
2. Streamsafe may consume CycleSmith templates/features, but should not own core
   loop logic changes.
3. New platform capabilities should be implemented in CycleSmith first, then
   adopted downstream.

## Open Items Carried Forward

- operator feedback ingestion in runner cycles
- policy-pack defaults for multi-repo usage
- CI workflow hardening for quality gates
- backend abstraction for ticket storage


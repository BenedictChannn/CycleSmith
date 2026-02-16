# Benchmark Protocol

CycleSmith is primarily a workflow toolkit. Benchmark checks are required only
when a cycle touches benchmark-facing code paths in a downstream repository.

## Rules

1. If no benchmark-facing code changed, record benchmark checks as `not_run`
   with an explicit reason in worker/judge evidence.
2. If benchmark-facing code changed, run the repository-specific benchmark
   command and attach command + result evidence in `judge.json.qa_verification`.
3. A `pass` verdict is invalid when required benchmark checks fail.


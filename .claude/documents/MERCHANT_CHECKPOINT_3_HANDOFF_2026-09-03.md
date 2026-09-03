# Merchant Checkpoint 3 Handoff — 2026-09-03

## Baseline

- Branch: `feat/workspace-rag`
- Starting commit: `168973f` (`Check point 2`)
- Target: Merchant Checkpoint 3

## Completed

- PostgreSQL migration `0001_initial_schema`
- Fourteen Merchant business tables
- PostgreSQL database client
- Merchant repository
- Deterministic project checker
- INTERNAL alert worker
- Alert deduplication and retry lifecycle
- Runtime/test migration role separation
- Bootstrap migration-history permission repair
- Pytest integration-marker registration

## Database state

### Test

- Database: `coding_agent_merchant_test`
- User: `merchant_test`
- Migration version: `1`
- Pending migrations: `0`

### Runtime

- Database: `coding_agent_merchant`
- Migration owner: `merchant_owner`
- Read-only status user: `merchant_app`
- Migration version: `1`
- Pending migrations: `0`
- Business tables: `14`
- Runtime business records: `0`

Migration checksum:

`8ff45d352766953f18ec0378c74cc280571641d40bcf5f4e27c5bedc700e51f1`

## Verification

- Root tests: `269 passed`
- unittest subtests: `21 passed`
- RAG tests: `414 passed`, `12 skipped`
- Structural tests: `74/74 passed`
- Root and RAG dependency checks: passed
- Python compilation: passed
- Git whitespace validation: passed
- Test and runtime migration status: healthy
- Runtime read-only repository/checker/worker smoke: passed
- Runtime database remains empty

Known unrelated warning:

- Starlette/httpx deprecation warning in the RAG virtual environment

## Safety contracts

- Runtime migration apply uses `merchant_owner`.
- Runtime status and plan use read-only `merchant_app`.
- `merchant_app` receives only `SELECT` on migration history.
- Test and runtime databases remain isolated.
- Checker operations do not mutate workflow state.
- Worker supports only INTERNAL delivery.
- EMAIL and SLACK continue to fail closed.

## Checkpoint 4 boundary

Checkpoint 4 should implement the workflow engine:

- Workflow-template loading
- Template and dependency validation
- Project creation from templates
- State-transition validation
- Gate enforcement
- Optimistic concurrency or stale-update protection
- Deterministic workflow tests

Do not add the public project CLI yet; that belongs to Checkpoint 5.
Do not enable EMAIL or SLACK delivery without explicit adapters and credentials.

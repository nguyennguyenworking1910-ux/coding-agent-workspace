# Database Environments and Migrations

## 1. Environments

| Target | Database / user | Used for | Writes |
|---|---|---|---|
| `runtime` | `MERCHANT_DB_NAME` / `MERCHANT_DB_USER` (owner `MERCHANT_OWNER_USER` for migrations) | Production Merchant state | **Disabled in code** (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`); the agent adapter is read-only for runtime |
| `test` | `coding_agent_merchant_test` / `merchant_test` | Local MVP lifecycle, automated PostgreSQL tests, live acceptance | Confirmed Direct EXECUTE and isolated test fixtures only |

Locally the test database runs in the Docker container `coding-agent-rag-db` (port 5434); Docker
Desktop must be running. All connection settings come from the repository-root `.env`
(`MERCHANT_DB_HOST`, `MERCHANT_DB_PORT`, `MERCHANT_TEST_DB_NAME`, `MERCHANT_TEST_USER`,
`MERCHANT_TEST_PASSWORD`, …). `migrate.py` refuses `coding_agent_rag` and `MERCHANT_ADMIN_DB`.

The test database holds **accepted live-acceptance records** (for example Projects A and D of the
Local MVP acceptance). Never modify or delete them; automated tests create and clean up their own
`PYTEST_*`-prefixed fixtures and must scope assertions to them.

How the target is chosen for an agent run, and how it is bound into every write, is in
[trusted execution](../architecture/trusted-execution.md#5-database-isolation-and-attribution).

## 2. Migrations

Forward-only SQL files in `.claude/clients/merchant/migrations/`, run by `migrate.py`, which
records each file's SHA-256 over its **exact bytes** in `merchant_ops.schema_migrations`.

| Version | File | Purpose | Test DB | Runtime |
|---|---|---|---|---|
| 1 | `0001_initial_schema.sql` (CRLF) | Schema, enums, workflow tables | applied | applied |
| 2 | `0002_add_project_payment_period.sql` (CRLF) | Payment period | applied | applied (CP9) |
| 3 | `0003_add_cli_write_grants.sql` | CLI write grants | applied | applied (CP9) |
| 4 | `0004_add_alert_delivery_leases.sql` | Alert delivery leases | applied | applied (CP10) |
| 5 | `005_merchant_execution_ledger.sql` (CRLF) | Execution ledger | applied | see `--status` |
| 6 | `006_merchant_execution_claims.sql` (CRLF) | Execution claims | applied | see `--status` |
| 7 | `007_procurement_reference_uniqueness.sql` | Unique procurement reference | applied | **not authorized** |
| 8 | `008_document_file_metadata.sql` | `document_files`, evidence status, immutability | applied | **not authorized** |
| 9 | `009_metadata_only_revisions.sql` | `METADATA_ONLY` revisions | applied | **not authorized** |
| 10 | `010_operator_attested_lifecycle.sql` | `recorded_by`, `decided_at`, decision immutability, signing attestation | applied | **not authorized** |
| 11 | `011_reused_revision_binding.sql` | Immutable reused-revision binding | applied | **not authorized** |

Rules:

- **Never edit an applied migration.** Its recorded checksum is fixed. `.gitattributes` pins each
  file's checkout line endings to the applied bytes (0001, 0002, 005, 006 CRLF; all others LF).
- Add a change as the next numbered file. Apply it to the test database first, with a dry run
  and RED/GREEN tests; a runtime migration needs separate owner approval.
- `migrate.py` does not load `.env` by itself. Load it (e.g. with `python-dotenv`) before running.

```bash
python .claude/clients/merchant/migrate.py --status --database test   # read-only
python .claude/clients/merchant/migrate.py --plan   --database test   # read-only: pending files
python .claude/clients/merchant/migrate.py --apply  --database test   # writes; test DB only
```

## 3. Integrity checks

- **Checksums:** the SHA-256 of every file in `migrations/` must equal the `checksum` recorded for
  its version in `merchant_ops.schema_migrations`. The migration tests
  (`tests/merchant/test_migrations.py`, `test_master_migration_010_postgres.py`, …) verify this.
- **Read-only snapshot:** per-table row counts and a hash of sorted `to_jsonb` rows of every
  `merchant_ops` table, taken before and after a change, prove accepted records are untouched.
  The [cleanup report](../development/repository-cleanup-report.md) shows an example.
- **Receipts** can be rebuilt from PostgreSQL alone (`attempt_evidence.recover_*`).

## 4. Backup and recovery

- Back up the managed document store (outside the repository) **before** the database snapshot
  (DEC-D4a); orphan cleanup is manual.
- An interrupted write is never assumed rolled back: its outcome is read from the claim and
  ledger (FAILED only when fenced, SUCCEEDED only with committed evidence, otherwise UNCERTAIN).
- Alert-worker recovery: [merchant alert operations](merchant-alert-operations.md).

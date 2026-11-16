# Backup and Restore

Where recovery material lives, what has and has not been verified, and the rules for handling
it. Database environments and migrations: [database and migrations](database-and-migrations.md).

## 1. Principles

- **Git is not a database backup.** It recovers source, migrations and documentation only.
- Database dumps, document-store objects, credentials and session state are **never committed**
  (`.gitignore`: `.env*`, `*.bak`, `.claude/runtime/`, `.claude/runtime_backup_*/`, caches).
- Keep database backups **outside the repository**, named
  `<database>_<environment>_<YYYYMMDD-HHMM>_<format>.dump` (for example
  `coding_agent_merchant_runtime_20260909-1430_custom.dump`), with their SHA-256 and size
  recorded next to the evidence that depends on them.
- Never restore into or overwrite `coding_agent_merchant` or `coding_agent_merchant_test`. Verify a
  restore only in a disposable, isolated database, and only with explicit approval.
- Agents never create, restore, truncate or delete database backups. These are operator actions.

## 2. Inventory (as of 2026-11-16)

| Material | Location | Evidence | Verified now? |
|---|---|---|---|
| Runtime DB backup before CP9 runtime mutation (custom format) | Outside the repository (private; passed to `inspect_runtime_backup` via `MERCHANT_RUNTIME_BACKUP_FILE`) | `backup_sha256 5567a6ac9508490085382b58a6b8395e37814a698c0eb024577e94abaab2e145`, 53,606 bytes ([CP9 handoff §3](../../archive/checkpoints/MERCHANT_CHECKPOINT_9_HANDOFF_2026-09-08.md)) | **No** — not accessed during cleanup |
| Runtime DB backup before migration 4 (CP10 Gate 10.7, custom format, restore listing verified then) | Outside the repository (private) | `backup_sha256 7745c7855d6fb0549c1e81c58af5e67a9c7da4289af0c8980ffff784045068be` ([CP10 handoff](../../archive/checkpoints/MERCHANT_CHECKPOINT_10_HANDOFF_2026-09-09.md)) | **No** |
| Test DB (`coding_agent_merchant_test`), including accepted live records (Projects A, D and earlier NL acceptances) | Docker container `coding-agent-rag-db` | Read-only content snapshot hash `4d5716a99a295710…` (18 `merchant_ops` tables) | Yes: custom-format dump of 2026-11-16 14:55, SHA-256 `dfcecd94…3e02c`, `pg_restore --list` and a restore into a throwaway container verified ([cleanup report §12](../development/repository-cleanup-report.md#12-local-v10-release-gate--backup-and-full-regression-cp12hlocal-v1-release-gate)) |
| Managed document store | `MERCHANT_DOCUMENT_STORE` (outside the repository) | — (no managed uploads implemented yet) | n/a |
| Execution history (claims, ledger, events) | Inside each database | Receipts rebuildable via `attempt_evidence.recover_*` | Covered by the database backup only |
| Session run state and pending confirmations | `.claude/runtime/` (git-ignored) | All pending records spent and expired | Not a backup; do not delete while a session runs |

Test-database backups are stored in `%USERPROFILE%\Backups\coding-agent-merchant\`. Procedure
(from Git Bash, stream the dump to avoid paths inside the container):

```bash
docker exec coding-agent-rag-db pg_dump -U <superuser> -d coding_agent_merchant_test -Fc > <backup-dir>/coding_agent_merchant_test_test_<YYYYMMDD-HHMM>_custom.dump
sha256sum <file>
docker exec -i coding-agent-rag-db pg_restore --list < <file>   # the archive listing must parse
```

Equivalent PowerShell form:

```powershell
docker exec coding-agent-rag-db pg_dump -U <owner> -d coding_agent_merchant_test -Fc -f /tmp/t.dump
docker cp coding-agent-rag-db:/tmp/t.dump <backup-dir>\coding_agent_merchant_test_<YYYYMMDD-HHMM>_custom.dump
Get-FileHash <backup-dir>\coding_agent_merchant_test_<...>.dump -Algorithm SHA256
pg_restore --list <file>    # integrity: the archive listing must parse
```

## 3. Order of a backup

1. Back up the managed document store (DEC-D4a), then the database.
2. Record database, environment, timestamp, format, SHA-256 and size.
3. Verify with `pg_restore --list`; a full restore test only into a disposable database.

## 4. Recovery of an interrupted write

An interrupted Merchant write is never assumed rolled back. Read its outcome from the claim and
ledger: FAILED only when fenced, SUCCEEDED only with committed evidence, otherwise UNCERTAIN
([trusted execution](../architecture/trusted-execution.md)). Alert-worker recovery:
[merchant alert operations](merchant-alert-operations.md).

## 5. Local recovery artifacts kept in the repository folder (git-ignored)

| Artifact | Why kept |
|---|---|
| `.gate11-pass-backup/` (6 files, 2026-09-18) | Snapshot of a passing Gate 11 state; `gate11-passing-full.diff` and its `team_lifecycle.py` exist nowhere else |
| 4 `*.bak` files (`cli.py.checkpoint3a`, `merchant_direct_recovery.py.pre17b3`, `merchant_reserved_execution.py.pre17b3`, `team_result_hook.py.pre17c5`) | Contents not found in Git history |
| `checkpoint_12h8_full_regression.log` | Only record of the CP12H.8 regression run (UTF-16) |
| `.claude/worktrees/testing-docs` (registered, locked by a Claude session) | Branch `worktree-testing-docs` (`8dae64f`) is not merged |

Review these and delete them manually once they are no longer wanted.

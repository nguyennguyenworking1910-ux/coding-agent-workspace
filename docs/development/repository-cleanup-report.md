# Repository Cleanup Report — CP12H.REPO-CLEANUP (2026-11-16)

Documentation and repository consolidation after the Local MVP live acceptance. No live
`/solve` write, no runtime database access, no migration, no push. `RUNTIME_DIRECT_EXECUTE_ENABLED`
remains `False`.

## 1. Starting state

| Item | Value |
|---|---|
| Branch | `feat/cp7-9-merchant-reliability` |
| HEAD at start | `b585de2` (matches the reported baseline) |
| Uncommitted work found | Automatic Step promotion (`dependencies.py`, `transition_repository.py`, `test_dependencies.py`) written during live acceptance |
| Untracked | none; ignored local files only (`.bak` copies, `checkpoint_12h8_full_regression.log`, `.claude/runtime/`, `.env`, caches) — left untouched |
| Baseline regression (with the uncommitted change) | **10 failed**, 4816 passed, 21 skipped, 1 xfailed (747 s) — not the reported 4825/0 |

The 10 baseline failures had two causes, neither introduced by the cleanup:

- **4 from the uncommitted promotion change:** the ordinary-step pipeline test still expected a
  manual PENDING → READY step (`ALREADY_IN_STATUS`), and three approval-concurrency tests counted
  STEP events, to which promotion adds one.
- **6 from the accepted live records:** reuse and migration-010 tests asserted *global* counts
  ("no Project has a reused binding", "no approval has `recorded_by`") that stopped holding once
  Projects A and D existed.

Review of the uncommitted change also found a defect: `recover_step_update_receipts(<promoted
step>)` matched the predecessor's ledger row through the promotion event's `xmin` and raised
`EvidenceBindingError` (confirmed RED).

## 2. Commits

| Commit | Content |
|---|---|
| `1f7fb4c` feat(merchant): promote ready successors when a step completes | Preserves the owner's promotion change; tags promotion events `promoted_after_step_id`; both Step receipt readers ignore them; tests assert promotion, tagging, same transaction and no misattributed recovery |
| `8c09bf4` test(merchant): scope PostgreSQL assertions to fixture-owned rows | Reuse tests count the fixture Merchant's bindings; the 010 test checks rows created before 010 was applied. No assertion removed, no record touched |
| `33308c4` docs: consolidate documentation into docs/ and archive checkpoint history | New `docs/` tree, archive moves, README/CLAUDE rewrite, reference updates |
| `c2774d0` refactor(agents): describe automatic step promotion to merchant-manager | One instruction bullet |
| `f0a00bd` chore(repo): remove verified obsolete files | `team_state_cli.py`, `requirements.txt`, tracked runtime backup |
| (this report) | docs: add repository cleanup report |

Nothing was pushed. No tag was created.

## 3. Directory structure

Before (Markdown only):

```text
README.md  CLAUDE.md  PONYTAIL_AUDIT.md
cp12h*.md                       47 checkpoint reports and runbooks at the repository root
.claude/documents/              23 files: current guides mixed with CP3–CP11 plans/handoffs and roadmaps
.claude/agents/*.md, .claude/commands/*.md, .claude/agents/tools/bigquery/**/*.md   (12, load-bearing)
```

After:

```text
README.md  CLAUDE.md
docs/
  README.md                     index + subject ownership map
  architecture/                 system-overview.md, trusted-execution.md
  merchant/                     project-lifecycle.md, project-manager-design.md
  operations/                   local-setup.md, database-and-migrations.md, live-acceptance.md,
                                merchant-alert-operations.md, scheduler.md, bigquery.md, rag.md
  development/                  testing.md, decision-register.md, checkpoint-history.md,
                                repository-cleanup-report.md
archive/checkpoints/            14 CP3–CP11 reports, roadmaps, audit (unchanged)
archive/checkpoints/cp12h/      46 CP12H reports (unchanged)
.claude/agents/*.md, .claude/commands/*.md, bigquery reference *.md   (12, unchanged locations)
```

`.claude/documents/` no longer exists. The target layout's `contributing.md`,
`workflow-templates.md`, `document-lifecycle.md`, `procurement.md`, `step-state-machine.md`,
`merchant-activation.md`, `configuration.md`, `backup-restore.md`, `troubleshooting.md` and
`database-architecture.md` were **not** created as separate files: their content is short enough
to live as sections of `project-lifecycle.md`, `database-and-migrations.md`, `local-setup.md` and
`testing.md`, and empty placeholders were out of scope.

## 4. Markdown inventory and actions

| | Before | After |
|---|---|---|
| Tracked `.md` files | 85 | 90 (2 root + 16 docs + 12 load-bearing + 60 archived) |
| `.md` files presented as current documentation (root + `.claude/documents/` / `docs/`) | 73 | 18 |
| Historical reports among them | 61 (mixed with current guides) | 0 (all in `archive/`) |
| `CLAUDE.md` lines | 503 | 242 |
| Architecture document lines | 732 (`ARCHITECTURE.md`) | 165 (`system-overview.md`) |

The file count rises by five because history was archived (evidence kept) rather than deleted,
and new canonical documents replaced explanations that were repeated across reports.

| Action | Files |
|---|---|
| **KEEP** (location unchanged) | 8 agent definitions, `solve.md`, `schedule-agent.md`, 2 BigQuery reference files |
| **REWRITE** | `README.md`, `CLAUDE.md`, `ARCHITECTURE.md` → `docs/architecture/system-overview.md`, `.claude/documents/README.md` → `docs/README.md` |
| **MOVE** (links fixed, content kept) | `SETUP.md` → `operations/local-setup.md`; `SCHEDULE_CLI.md` → `operations/scheduler.md`; `BIGQUERY_INTEGRATION.md` → `operations/bigquery.md`; `RAG_INTEGRATION.md` → `operations/rag.md`; `MERCHANT_ALERT_OPERATIONS.md` → `operations/merchant-alert-operations.md`; `MERCHANT_PROJECT_MANAGER.md` → `merchant/project-manager-design.md` (status banner); `cp12h_master_live_acceptance_runbook.md` → `operations/live-acceptance.md` (status banner) |
| **MERGE** (new canonical docs) | CLAUDE.md Merchant boundary + MASTER §1/§5 → `trusted-execution.md`; MASTER report + simplified policy + runbook findings → `project-lifecycle.md`; NL4D register + simplified policy → `decision-register.md`; all checkpoint reports → `checkpoint-history.md`; scattered test/migration knowledge → `testing.md`, `database-and-migrations.md` |
| **ARCHIVE** (byte-identical renames) | `MERCHANT_CHECKPOINT_{3,5,6,7,8,9,10}_*`, CP8–CP10 plans, both roadmaps, `ORCHESTRATION_LIFECYCLE_FIX_2026-09-10.md`, `PONYTAIL_AUDIT.md` (14); every other `cp12h*.md` (46) |
| **DELETE** | `AGENT_INITIALIZATION.md` (restated ARCHITECTURE.md; its only consumers were `system_test.py` checks, now pointed at the new docs); `EXAMPLES_GUIDE.md` (stale: `python3`, `requirements.txt`, wrong run directory; `scheduler_example.py` documents itself) |

Archived reports are kept because they hold irreplaceable acceptance evidence (run ids,
transaction ids, database hashes), and the 89 tests in the checkpoint documentation test files
pin their text. Links inside the
archive are historical and not maintained.

## 5. Documentation ownership map

See [docs/README.md — Subject ownership](../README.md#subject-ownership). Duplicated or
contradictory guidance resolved:

- "All `.md` files go in `.claude/documents/`" (ARCHITECTURE, AGENT_INITIALIZATION, system_init,
  bug-fixer, coder, solve) contradicted 47 root reports; replaced by one placement rule (docs/,
  archive/, load-bearing locations), enforced by `system_test.py`, which now also scans the root.
- The proposal/apply contract appeared in current-looking documents; it is now only in the
  archive and flagged as superseded in `project-manager-design.md`.
- Withdrawn policies (S1, S2, D1, G1, G2) are listed once, as withdrawn, in the decision register.
- Install instructions disagreed (`requirements.txt` vs `pip install -e .`); now `pip install -e .`
  everywhere.

## 6. Agent instructions

| File | Change |
|---|---|
| all 8 agent definitions | Required-reading path → `docs/architecture/system-overview.md` |
| `bug-fixer.md`, `coder.md` | Documentation-placement rule updated |
| `merchant-manager.md` | Paths; one bullet on automatic READY promotion |
| `group-sales-manager.md`, `schedule-agent.md` | Doc paths |
| `solve.md` | Architecture path; "Architectural boundaries" now names `hooks`/`system` and `docs/` |

All agent definitions are still loaded (registered in `agents.json`, found by `system_test.py`).
No agent was merged or removed. `merchant-manager.md` and `solve.md` were otherwise left intact:
their content was reviewed and found current (their `--propose`/`--apply` mentions are
prohibitions), and the 93 tests in files that read them pin much of their wording. **Fingerprints changed: start a fresh Claude
Code session before live `/solve` use.**

## 7. Dead code and file removals

| Item | Evidence | Action |
|---|---|---|
| `.claude/hooks/team_state_cli.py` | No importer, no test, no hook registration, not in any allowlist; could allocate team state outside hooks | Removed |
| `.claude/agents/requirements.txt` | Stale duplicate of `pyproject.toml`; would install an incompatible psycopg | Removed |
| `.claude/runtime_backup_20260921_155111/` | Tracked generated team state and confirmations | Untracked, ignored, local copy kept |
| Legacy proposal/apply code | Engine `propose_*` functions are the active pure API; legacy CLI modes are rejected at the adapter and still covered by rejection tests | Kept — removal would change the CLI contract |
| `bq_test.py`, `scheduler_example.py`, `merchant_activation_preflight.py` | Unreferenced by code but documented developer/operator tools | Kept |
| Ignored local files (`*.bak`, old regression log) | Local, not in Git | Not touched; delete manually if wanted |

## 8. Known findings (reconciled)

| Finding | Status |
|---|---|
| F1 signing-gate ordering | **FIXED** (`b585de2`) |
| F7 two integration Projects per Merchant | **OPEN** — owner decision |
| Step completion without PO/Payment Request records (F8a) | **ACCEPTED_LIMITATION** |
| Revision created after signing-gate completion (F8b) | **ACCEPTED_LIMITATION** |
| Existing-document reuse shadowed by an own revision (F8c) | **ACCEPTED_LIMITATION** |
| Existing-document reuse selection (several candidates → UUID required) | **ACCEPTED_LIMITATION** (by design) |
| PENDING → READY guidance | **FIXED** (`1f7fb4c`, documented; agent instruction `c2774d0`) |
| Automatic Step promotion observed in live acceptance | **FIXED** — committed with a receipt-recovery correction (`1f7fb4c`) |
| Typed Merchant Create scope exception (F3) | **ACCEPTED_LIMITATION** |
| Natural-language wording limits | **ACCEPTED_LIMITATION** |

Details: [project lifecycle §7](../merchant/project-lifecycle.md#7-known-findings-and-limitations).

## 9. Validation

| Check | Result |
|---|---|
| Baseline full suite (before any change) | 10 failed / 4816 passed / 21 skipped / 1 xfailed — causes in §1 |
| The 6 previously failing PostgreSQL files after `1f7fb4c` + `8c09bf4` | **94 passed**, 0 failed (incl. RED proof that recovery misattributed without the fix) |
| Documentation, agent-contract, intent and RAG-doc tests after the move | **212 passed** (one README line-wrap failure fixed before commit) |
| Final full suite on `f0a00bd` | **Incomplete:** Claude Code stopped it at **87 % with 0 failures** because the machine ran low on memory (not a test failure). Superseded by the complete run on `ab112d0` (§12). |
| `python .claude/system_test.py` | **84/84 passed** (83 before the root-Markdown check was added) |
| `py_compile` + import of every hook, `system/`, `system_init`, scheduler | all pass; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean on every commit |
| Active Markdown links, anchors and backticked repo paths | **0 problems** (archive excluded by policy; git-ignored credential paths whitelisted) |
| Migration files vs `schema_migrations` checksums (001–011) | all 11 identical; no diff under `migrations/` since `b585de2` |
| Read-only test-DB snapshot (18 `merchant_ops` tables: row counts + hash of sorted rows) | **identical** before and after (total `4d5716a99a295710…`); 0 `PYTEST*` Merchants, 0 pytest claims left, all 58 claims COMPLETED |
| Pending confirmations in `.claude/runtime/` | all CONFIRMED (spent) and expired; none live |
| Runtime database | not accessed |

The complete single-process regression is recorded in §12.

## 10. Local v1.0 readiness

**Conditionally ready for the Local v1.0 release-hardening checkpoint.** Superseded by the
release-gate decision in §12.

- Ready: one authoritative documentation tree, clean working tree, invariants unchanged
  (runtime disabled, migrations byte-identical, accepted records untouched), the previously
  uncommitted promotion change committed with its recovery defect fixed.
- Condition: one complete full-suite run with 0 failures (the final run stopped at 87 % for
  memory with no failure).
- Before live `/solve`: start a fresh Claude Code session (agent definitions changed).
- Open owner decisions carried forward: F7, DEC-P1b, the DEC-D4g type list.

## 11. Backup and temporary file cleanup (additional scope)

Scope: the repository folder only (`.git`, `.venv`, `rag-server/.venv` excluded). Searched for
`*.bak *.backup *.old *.orig *.tmp *.temp *.swp *.dump *.gz *.zip *.tar *.log *.sql *.lock` and
`backup*/ snapshots/ logs/ tmp/ temp/` directories. No `.dump`, `.gz`, `.zip`, `.tar`, `.orig`,
`.old`, `.swp` or `.tmp` file exists. Every `.sql` file is an active migration or query template;
none is a database backup.

Recoverability test for local copies: the Git blob hash of each file was looked up among all
objects reachable in the repository history. Present → the exact content is recoverable from Git.

### Classification

| Artifact | Size | Modified | Git | Class |
|---|---|---|---|---|
| `.claude/clients/merchant/migrations/*.sql` (001–011) | 48 KB | 09-03…11-12 | tracked | KEEP_ACTIVE (checksums unchanged) |
| `rag-server/migrations/001_initial.sql`, `bigquery/templates/groupsale_usage_monthly.sql` | 14 KB | — | tracked | KEEP_ACTIVE |
| `coding_agent_workspace.egg-info/` | 15 KB | — | ignored | KEEP_ACTIVE (editable install) |
| `rag-server/.model-cache/` | 4.3 GB | — | ignored | KEEP_ACTIVE (RAG embedding model) |
| `.claude/runtime/` | — | — | ignored | KEEP_ACTIVE / KEEP_AUDIT (session run state; all pending records spent and expired) |
| `.claude/scheduled_tasks.lock` | 124 B | 11-12 | ignored | KEEP_ACTIVE (Claude Code harness lock) |
| `.claude/runtime_backup_20260921_155111/` (9 files) | 12 KB | 09-21 | ignored since `f0a00bd` | DELETE_SAFE — every file is in Git history (e.g. `git show b585de2:<path>`) |
| 14 `*.bak` source copies listed below | 360 KB | 09-07…10-15 | ignored | DELETE_SAFE — exact content in Git history |
| `.gate11-pass-backup/` (6 files) | 348 KB | 09-18 | ignored (`.git/info/exclude`) | REVIEW_REQUIRED — `gate11-passing-full.diff` and `team_lifecycle.py` are not in Git |
| `.claude/agents/tools/merchant/cli.py.checkpoint3a.bak`, `.claude/hooks/merchant_direct_recovery.py.pre17b3.bak`, `.claude/hooks/merchant_reserved_execution.py.pre17b3.bak`, `.claude/hooks/team_result_hook.py.pre17c5.bak` | 87 KB | 10-13…10-14 | ignored | REVIEW_REQUIRED — content not in Git history |
| `checkpoint_12h8_full_regression.log` | 650 KB | 09-29 | ignored | REVIEW_REQUIRED / KEEP_AUDIT — only record of the CP12H.8 run (2764 passed) |
| `.claude/worktrees/testing-docs` | empty dir | 07-30 | registered worktree, **locked** by a Claude session | REVIEW_REQUIRED — branch `worktree-testing-docs` (`8dae64f`) not merged; not pruned |
| `__pycache__/` (19 dirs, 495 `.pyc`), `.pytest_cache/`, `.ruff_cache/` | 15.8 MB | — | ignored | DELETE_SAFE — generated |
| External runtime DB backups (CP9 `5567a6ac…`, CP10 `7745c785…`) | — | 09-08, 09-09 | outside repository | KEEP_RECOVERY — not accessed, **not verified** in this cleanup |

### Files removed (exact paths)

```text
.claude/agents/tools/merchant/agent_cli.py.checkpoint3d2.bak
.claude/agents/tools/merchant/cli.py.checkpoint2a.bak
.claude/agents/tools/merchant/write_commands.py.checkpoint1.bak
.claude/clients/merchant/merchant_repository.py.checkpoint3d5g4.bak
.claude/hooks/intent_envelope_bridge.py.checkpoint22h.bak
.claude/hooks/intent_gate.py.checkpoint3d.bak
.claude/hooks/merchant_tool_result_contract.py.checkpoint3d5d2.bak
.claude/hooks/policy_gate.py.checkpoint3d.bak
.claude/hooks/teammate_idle_orchestrator.py.checkpoint3d5f6.bak
.claude/hooks/teammate_idle_orchestrator.py.pre17c5.bak
.claude/hooks/team_result_contract.py.checkpoint3d5c.bak
rag-server/tests/test_chat_ingestion_cli.py.bak
tests/merchant/test_merchant_agent_cli.py.checkpoint3d3.bak
tests/merchant/test_merchant_cli.py.checkpoint3c.bak
.claude/runtime_backup_20260921_155111/debug-intent-envelope.json
.claude/runtime_backup_20260921_155111/manual-hook-test.json
.claude/runtime_backup_20260921_155111/merchant_confirmation/3547d3dc-be05-40fc-ae3f-ee54e280d9cd.json
.claude/runtime_backup_20260921_155111/merchant_confirmation/c686a9d7-d075-4080-a6cb-74157bf11adf.json
.claude/runtime_backup_20260921_155111/pending_team_results/c28f85fbd4c622ffb0a82ebaf85341c3a69c1dd6d82614c97cb0d82a9211a66e.json
.claude/runtime_backup_20260921_155111/team_hook_debug.jsonl
.claude/runtime_backup_20260921_155111/team_state/3547d3dc-be05-40fc-ae3f-ee54e280d9cd.json
.claude/runtime_backup_20260921_155111/team_state/aca327cc-ab80-4535-943c-95eb5638e707.json
.claude/runtime_backup_20260921_155111/team_state/c686a9d7-d075-4080-a6cb-74157bf11adf.json
.pytest_cache/   .ruff_cache/   (all files)
__pycache__/*.pyc in: ./ .claude/ .claude/agents/ .claude/agents/team/ .claude/agents/tools/
  .claude/agents/tools/{bigquery,merchant,rag,scheduler}/ .claude/clients/ .claude/clients/merchant/
  .claude/examples/ .claude/hooks/ .claude/scripts/ .claude/system/ .claude/workers/
  rag-server/app/ tests/ tests/merchant/
```

Deletion used this explicit 530-file list, file by file; directories were removed only once
empty. `.pyc` files are regenerated by Python on import (the active session's hooks recreated
87 during the run, as expected).

### Space

| | KiB (repository folder excluding `.git`, venvs, model cache) |
|---|---|
| Before | 28,729 |
| After | 13,095 |
| Reclaimed | ≈ 15,634 (≈ 15.3 MiB; 16,186,226 bytes in the deleted files) |

### `.gitignore` additions

`.ruff_cache/`, `*.backup`, `*.old`, `*.orig`, `*.dump`, `*.sql.gz` (earlier in this checkpoint:
`.claude/runtime_backup_*/`). `*.sql` is deliberately **not** ignored; migrations stay tracked
(verified with `git check-ignore`).

### Backup/restore readiness

Documented in [backup and restore](../operations/backup-restore.md).

- During §11 itself no database backup was created, restored, verified or deleted; no database
  write was made. The test-database backup was created and verified afterwards (§12).
- Runtime backups exist only as recorded evidence (CP9, CP10); their current integrity is
  **unverified**.
- **There is no backup of `coding_agent_merchant_test`**, which holds the accepted live-acceptance
  records. Recommended operator action: a custom-format `pg_dump` stored outside the repository,
  with its SHA-256 recorded (procedure in the backup document).

### Verification after this cleanup

- Migrations: no diff since `b585de2`; all 11 SHA-256 values unchanged.
- REVIEW_REQUIRED files still present; no recovery copy deleted.
- Active links/paths: 0 problems. `system_test.py`: 83/83. All hooks import;
  `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.
- Test DB read-only snapshot: identical to the pre-cleanup snapshot. Runtime DB not accessed;
  no live `/solve`.
- Full regression: §12.

## 12. Local v1.0 release gate — backup and full regression (CP12H.LOCAL-V1-RELEASE-GATE)

Run on `ab112d0` with a clean working tree.

### Environment and resources

| Item | Value |
|---|---|
| Host | Windows 11 Pro 10.0.26200, 15.7 GB RAM, Python 3.11.9 (`.venv`) |
| Free RAM at preflight | 1.22 GB (8.2 GB commit headroom); 248 GB free disk |
| Free RAM during the run | 0.53–0.70 GB, sampled every 4 minutes; no process was terminated |
| Concurrent work | No other Python or pytest process; 5 Claude Code processes and Chrome open (not touched) |
| PostgreSQL | Container `coding-agent-rag-db` (pgvector pg16.15); no client connections at preflight |

### Test-database backup

| Item | Value |
|---|---|
| Source | `coding_agent_merchant_test`, read via `pg_dump -Fc` (one consistent snapshot) |
| File | `%USERPROFILE%\Backups\coding-agent-merchant\coding_agent_merchant_test_test_20261116-1455_custom.dump` (outside the repository; not committed) |
| Size | 112,857 bytes |
| SHA-256 | `dfcecd94b712718f389d098f06b1bc96a17cf3735dde92489b73f0479c33e02c` |
| Archive check | `pg_restore --list` parses: custom format, gzip, 146 TOC entries, 18 `merchant_ops` table-data entries; listing saved next to the dump (`.list`) |
| Restore test | Restored with `pg_restore --no-owner --no-privileges --exit-on-error` into a **throwaway container** (same image, no published port, removed afterwards). Exit 0. Neither the runtime nor the test database was restored into or overwritten |
| Content check | Per-table row count + MD5 of sorted `to_jsonb` rows for all 18 tables: **identical** between source and restored copy (58 claims, 42 ledger rows, 7 projects, 140 steps, 57 events, 11 migrations) |
| Not covered | Roles, ownership and grants were skipped in the restore test (the throwaway server has no Merchant roles); they are in the archive but were not restore-tested |

The test database was read before and after the dump: its snapshot is unchanged
(`4d5716a99a295710…`).

### Full regression

| Item | Value |
|---|---|
| Command | `.venv\Scripts\python.exe -m pytest -q` (one process, no parallelism, no partitioning) |
| Duration | 665.5 s (14:57–15:08 +07:00) |
| Result | **4826 passed, 21 skipped, 1 xfailed, 97 subtests passed, 0 failed, 0 errors** |
| Exit code | **0** |
| Skips/xfail | Same counts as the untouched baseline (§9); no test was skipped, marked or weakened for this run |

### Final verification

| Check | Result |
|---|---|
| `python .claude/system_test.py` | all passed |
| `compileall` of `.claude/`, `tests/`, `rag-server/app/`; import of every hook | pass; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean |
| Migration files 001–011 vs `schema_migrations` checksums | all 11 identical |
| Active documentation links | 0 problems |
| Test-DB snapshot after the regression | **identical** to the pre-cleanup snapshot (`4d5716a99a295710…`) |
| Execution claims | 58, all `COMPLETED` |
| Orphan ledger rows (ledger without a claim) | 0 |
| `PYTEST*` merchants left by the suite | 0 |
| Accepted Projects | Live A (`IN_PROGRESS`, v2) and Live D (`COMPLETED`, v3) unchanged, along with the other 5 earlier acceptance Projects |
| Pending confirmations (`.claude/runtime/`) | 42 records, all `CONFIRMED`; none live |
| Runtime database / live `/solve` | not accessed / not run |

### Remaining findings

Unchanged from §8: **F7 (two integration Projects per Merchant) is OPEN** for an owner decision;
F8a/b/c, F3, existing-document reuse selection and NL wording limits are ACCEPTED_LIMITATION. Also
open: DEC-P1b, the DEC-D4g type list, and the REVIEW_REQUIRED local artifacts in §11. Runtime
backups (CP9, CP10) remain unverified.

### Decision

**Local v1.0: GO** for the test-database Local MVP scope. Both release blockers are closed: a
verified, restorable backup of the test database exists outside the repository, and the full
suite passes in one run. Not included: runtime Direct EXECUTE (still disabled), runtime
migrations 007–011, and F7. Start a fresh Claude Code session before live `/solve`.

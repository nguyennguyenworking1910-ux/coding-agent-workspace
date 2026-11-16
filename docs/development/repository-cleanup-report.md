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
| Final full suite on `f0a00bd` | **Incomplete:** Claude Code stopped it at **87 % with 0 failures** because the machine ran low on memory (not a test failure). The remaining ~13 % were not re-run. |
| `python .claude/system_test.py` | **84/84 passed** (83 before the root-Markdown check was added) |
| `py_compile` + import of every hook, `system/`, `system_init`, scheduler | all pass; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean on every commit |
| Active Markdown links, anchors and backticked repo paths | **0 problems** (archive excluded by policy; git-ignored credential paths whitelisted) |
| Migration files vs `schema_migrations` checksums (001–011) | all 11 identical; no diff under `migrations/` since `b585de2` |
| Read-only test-DB snapshot (18 `merchant_ops` tables: row counts + hash of sorted rows) | **identical** before and after (total `4d5716a99a295710…`); 0 `PYTEST*` Merchants, 0 pytest claims left, all 58 claims COMPLETED |
| Pending confirmations in `.claude/runtime/` | all CONFIRMED (spent) and expired; none live |
| Runtime database | not accessed |

The final regression must be re-run to completion when memory allows:
`.venv\Scripts\python.exe -m pytest -q` (one process only).

## 10. Local v1.0 readiness

**Conditionally ready for the Local v1.0 release-hardening checkpoint.**

- Ready: one authoritative documentation tree, clean working tree, invariants unchanged
  (runtime disabled, migrations byte-identical, accepted records untouched), the previously
  uncommitted promotion change committed with its recovery defect fixed.
- Condition: one complete full-suite run with 0 failures (the final run stopped at 87 % for
  memory with no failure).
- Before live `/solve`: start a fresh Claude Code session (agent definitions changed).
- Open owner decisions carried forward: F7, DEC-P1b, the DEC-D4g type list.

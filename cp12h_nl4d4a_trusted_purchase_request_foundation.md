# CP12H.NL4D4A — Trusted Purchase Request Confirmation & Test-Only Execution Foundation

Baseline `448003be64076e01350b4f55cc83a28787cde06a`, branch `feat/cp7-9-merchant-reliability`.
Date 2026-11-11.

- **Committed after final acceptance (§15.9); not pushed.**
- **No live `/solve` Purchase Request write** was performed.
- **Runtime Direct EXECUTE is still disabled:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.
- **Production database:** never connected to.
- **Unrelated work preserved:** the uncommitted `cp12h_nl4d_decision_register.md` is untouched.

## 1. Architecture and exact data flow

**There is no new database writer.** The confirmed Purchase Request (PR):
- runs through the existing `procurement update` command;
- writes through the existing `MerchantProcurementRepository.record_procurement`, the only procurement writer;
- uses the unchanged scoped Direct EXECUTE pipeline that NL4C2A uses for Step Updates.

| # | Stage | Code | New in NL4D4A |
|---|---|---|---|
| 1 | **Run A, preview (read-only).** The `evidence preview` CLI resolves the trusted operator from local configuration and judges the request:<br>• the domain engine;<br>• DEC-P1a, a duplicate within the Merchant;<br>• DEC-P1c, a replacement.<br>A valid *new* PR on the test database carries `requested_operation` (NOT_AUTHORIZED). | `read_commands.evidence_preview` → `evidence_preview._procurement` / `_purchase_request_operation` → `purchase_request.build_operation` | **yes** |
| 2 | **Capture.** PostToolUse(Bash) captures the exact CLI JSON from merchant-manager's verified pane. It checks:<br>• the operation is consistent with the output;<br>• its operator equals the operator **the hook resolves itself**.<br>Only then does it record a pending PR. | `merchant_preview_delivery.record_read_evidence` → `_evidence_operation_consistent` → `pending.record_pending_purchase_request` | **yes** |
| 3 | **Confirmation.** The user types `/solve Xác nhận ghi nhận [<project id>]`. The hook spends exactly one live record into a `merchant_scope`.<br>It refuses **without spending** when:<br>• the target is not test;<br>• the operator is missing, invalid or changed. | `intent_gate.confirm_pending_purchase_request` → `pending.resolve(kind=purchase_request, allowed=…)` | **yes** |
| 4 | **Typed scope.** A typed `--merchant-scope ["procurement","update",…]` is refused on both targets. | `intent_gate.run` | **yes** |
| 5 | **Scope validation.** The scope must be the preview's canonical argv; `external_id` is business text, not a target UUID. | `merchant_runtime_handoff.validate_direct_scope` / `_require_canonical_purchase_request_argv` | **yes** |
| 6 | **Dispatch and staging.** These are unchanged:<br>• policy-gate dispatch receipt;<br>• teammate reuse;<br>• pane identity;<br>• staging and completeness evidence. | `policy_gate`, `team_result_hook`, `merchant_runtime_handoff_gate` | — |
| 7 | **Preflight** (read-only; nothing spent):<br>a. target allowlist;<br>b. terminal marker;<br>c. **confirmed PR record** for this run, with the same argv, target, Project, reference and operator;<br>d. **operator re-resolved**;<br>e. database identity;<br>f. **the DEC-P1a unique index exists**;<br>g. **`verify_purchase_request`**. | `merchant_direct_handoff.preflight_direct_execute` → `_confirmed_purchase_request_operation`, `_verify_purchase_request` | **yes** |
| 8 | **Execution and spend.** A `direct_scope_execution` record is set to EXECUTING, then the one-use spend runs, then `invoke_authorized_scope_apply`. | unchanged | — |
| 9 | **One evidence-bound transaction:**<br>a. claim and ledger insert;<br>b. lock the Project, its revisions and its procurement rows;<br>c. **precondition**: operator re-resolved, then `verify_purchase_request` on the same connection;<br>d. engine plan (INSERT);<br>e. INSERT the record (now with `merchant_id`);<br>f. PROCUREMENT event, with `triggered_by` = operator;<br>g. ledger result and claim COMPLETED;<br>h. commit. | `attempt_evidence._BoundConnection`, `write_adapters._record_confirmed_purchase_request`, `record_procurement(precondition=…)` | precondition hook, merchant column |
| 10 | **Settlement** comes from committed evidence: a missing claim is fenced and a rollback is never inferred. | `settle_scope_execution` | — |
| 11 | **Receipt.** On SUCCEEDED, a receipt is built from ledger, claim, procurement row and event (one `xmin`), checked against the confirmed operation, and persisted. | `_record_purchase_request_receipt` → `attempt_evidence.purchase_request_receipt` | **yes** |
| 12 | **Release.** The teammate's `TEAM_RESULT_JSON` must agree with the evidence; TeammateIdle releases only on SUCCEEDED. | unchanged | — |

## 2. Applied policies

Each approved owner decision and how it is applied:

- **DEC-A0** (trusted local operator):
  - comes from `MERCHANT_OPERATOR_ID` (process environment, or the untracked repository `.env`) via `operator_identity.trusted_operator_id()`;
  - must be one canonical lowercase UUID, and not the nil UUID;
  - is checked at preview, capture, confirmation, preflight and in the write transaction;
  - is persisted as `project_events.triggered_by`;
  - is bound into the operation, the argv, the basis hash, the ledger payload hash and the receipt.
- **DEC-P1a** (one reference per Merchant, type and reference):
  - the preview reports `PROCUREMENT_REFERENCE_DUPLICATE` (BLOCKED, any type, any target);
  - `verify_purchase_request` checks again in preflight and in the transaction;
  - the **database-level unique index** from migration 007 is the final guarantee.
- **DEC-P1c** (no reference replacement):
  - the preview reports `PROCUREMENT_REFERENCE_REPLACEMENT_UNSUPPORTED` when a Project's PR already has another reference;
  - the confirmed path is **create-only**: any existing PR record is refused with `PURCHASE_REQUEST_ALREADY_RECORDED` or the replacement code;
  - general procurement updates are not enabled.
- **DEC-P2** (PR allowed when `requires_procurement=false`):
  - allowed, with the informational note `PROCUREMENT_NOT_REQUIRED`;
  - no Step, dependency or workflow change: tested by comparing every step before and after.

Nothing else was decided or introduced:
- **Not added:**
  - no reference format rule;
  - no case folding;
  - no approval, revision, signing, Purchase Order or Payment Request execution.
- **Not confirmable:** Purchase Orders and Payment Requests still preview only, and their operation is always null.

## 3. Identity trust model

**What it is.** The recording operator is an attribution of *which local operator recorded the evidence*. It is not proof that any external approver authorized anything.

**Where it is checked:**

| Point | Check | Refusal |
|---|---|---|
| Preview (CLI) | resolved from configuration only; the request text cannot supply it (tested with a UUID, a name and a `--operator-id` string inside the request) | no operation; `confirmation_blockers: [OPERATOR_IDENTITY_*]` |
| Capture (hook) | the operation's operator must equal the hook's own resolution | UNVERIFIED; no pending record |
| Confirmation (gate) | `require_operator(record.operator_id)` | refused, **record stays PENDING** |
| Preflight | the record and argv must match; the operator is re-resolved | `OPERATOR_IDENTITY_UNAVAILABLE`, `_INVALID` or `_CHANGED`; nothing spent |
| Transaction | the adapter re-resolves (twice: once before calling the repository, once inside the precondition) and refuses a mismatch with the payload | whole transaction rolled back; attempt FAILED and fenced |
| Receipt | `triggered_by` of the event must equal the confirmed operator | `UNRECONCILED` |

**Where the operator can and cannot come from:**
- **Teammate input:** a teammate cannot supply the operator. A `--operator-id` in an execute request that differs from the confirmed record is `PURCHASE_REQUEST_CONFIRMATION_MISMATCH`.
- **CLI argument:** `--operator-id` names only the *expected* operator; the written value is always the trusted configuration.

**Limitations:**
- Any process running as the same OS user can edit `.env` or the environment. That includes teammates with general Bash, such as `coder` and `bug-fixer`.
- This is the same workstation trust boundary as the database credentials. It is not authentication, and there is no identity table.
- `MERCHANT_OPERATOR_ID` is **not yet set** in your local configuration; you must choose the value before NL4D4B.

## 4. Schema and migration assessment

**Audit before the change (read-only):**
- `procurement_records` stores only `project_id`; the Merchant is resolved through the Project.
- It has 0 rows on the test database, so there are no duplicates.
- There are no views, rules or triggers on the table.
- The owner is `merchant_test`.
- `merchant_app` has table-level INSERT and UPDATE, which covers new columns.

**Migration `007_procurement_reference_uniqueness.sql`:**
1. Add `merchant_id UUID`.
2. Backfill it from each row's own Project (derived; no business value is changed or deleted).
3. Set it `NOT NULL`.
4. Add a unique index on `projects (id, merchant_id)`.
5. Add the composite foreign key `procurement_records (project_id, merchant_id) → projects (id, merchant_id) ON UPDATE CASCADE`, which pins each row to its Project's Merchant.
6. Add the partial unique index `(merchant_id, procurement_type, external_id) WHERE external_id IS NOT NULL`.

**Safety properties:**
- **Fail closed:** if a duplicate existed, step 6 would fail and the whole migration would roll back. Nothing is merged or deleted.
- **Reversible manually:** the runner is forward-only, so the reversal SQL is documented in the migration header (drop the index, the foreign key, the column and the Project index, then delete `schema_migrations` row 7).

**How it was validated and applied:**
1. **Dry run first**, in a transaction that was always rolled back on the test database (PostgreSQL DDL is transactional). It confirmed:
   - backfill OK;
   - a duplicate within the Merchant is rejected;
   - a mismatched Merchant is rejected by the foreign key;
   - a missing Merchant is rejected;
   - schema and hash are unchanged after rollback.
2. **Planned, then applied** with the project runner (`migrate.py --plan` then `--apply --database test`).
   - Exactly one migration was pending (version 7) and there were no checksum conflicts.
   - Applied to `coding_agent_merchant_test` only. Runtime is not migrated.

**Compatibility:**
- **Reads:** every read selects explicit columns or joins through the Project, so they work on both schemas. The Step basis is unaffected.
- **Writes:** the procurement INSERT now names `merchant_id`, so on an un-migrated database it fails closed.
- **Execution:** the preflight refuses execution with `PROCUREMENT_REFERENCE_CONSTRAINT_MISSING` when the index is absent.

## 5. Reference uniqueness implementation

**Three layers:**
1. **Preview.** `procurement_reference_holders(merchant, type, reference)` is an exact-match read through the Project, in both `MerchantReadRepository` and `TransactionDetailReader`. A holder on another Project gives BLOCKED.
2. **Preflight and transaction.** `verify_purchase_request` reads the holders again, and they are included in the basis hash. In the transaction, the Project and its procurement rows are locked first.
3. **Database.** The partial unique index is the only layer that covers two *different* Projects, which lock different rows. In the concurrency test, both transactions pass the application check (a barrier holds them until both have passed); the index commits exactly one, and the other gets `ProcurementConflictError` with its claim and ledger rolled back.

**Matching rules:**
- **Exact match:** `PR-001` and `pr-001` are distinct. P1 decided "exact, no format pattern".
- **Reuse across Merchants:** the same reference at another Merchant is allowed (tested).
- **Reuse across types:** the same reference for another procurement type of the same Merchant is allowed (tested).

## 6. Immutable PR semantics

**Create-only:**
- The confirmed path accepts only an engine plan with `operation == INSERT` and the exact reference.
- Any existing PR record on the Project refuses the operation:
  - with a reference: `…REPLACEMENT_UNSUPPORTED` or `…ALREADY_RECORDED`;
  - status only: `…ALREADY_RECORDED`.
- The canonical argv has no `--status`, `--expected-version`, `--procurement-id`, `--document-type` or `--triggered-by`. The payload check rejects any extra field, except the `procurement_id` that the CLI itself generates at execution.

**Untouched:**
- No other procurement row, status or metadata is touched.
- No Step status is changed (tested).

**Retries:**
- **Same task:** a duplicate same-operation retry is stopped by the claim on the operation key (tested with a replayed execute request and with 4 concurrent claims: 1 write).
- **Across runs:** stopped by create-only plus the basis.

**Preview change to an accepted NL4D3 behaviour:** a new reference on a Project whose PR already has one was previewed as a valid UPDATE in NL4D3. It is now BLOCKED (DEC-P1c). The test was updated intentionally.

## 7. Confirmation contract

**`requested_operation` fields** (`purchase_request.validate_operation` rejects any edit, truncation, retarget or reorder):

| Field | Meaning |
|---|---|
| `command`, `operation`, `status` | `procurement update`, `RECORD_PURCHASE_REQUEST`, always `NOT_AUTHORIZED` |
| `database_target` | `test` only |
| `procurement_type` | `PURCHASE_REQUEST` |
| `merchant_id`, `merchant_code` | the Project's Merchant (the code is re-checked) |
| `project_id`, `project_title`, `project_version` | the Project; the version is also covered by the basis |
| `requires_procurement` | informational (DEC-P2) |
| `reference` | the exact reference (one argv-safe token of 100 characters or fewer; NFC) |
| `operator_id` | the trusted operator |
| `expected_basis` | sha256 of: operation (type, reference, operator), the Project row (version, status, Merchant fields), every procurement row of the Project, and every holder of the reference in the Merchant |
| `argv` | `procurement update <P> --type PURCHASE_REQUEST --external-id <ref> --merchant-code <C> --operator-id <O> --expected-basis <H>` |

**Pending store** (`<owner>.pending_purchase_request.json`, separate from the Project and Step stores):
- **Lifetime:** owner session, 15-minute TTL, single use under a file lock.
- **Phrases:** `Xác nhận ghi nhận` / `Confirm record`, and `Hủy ghi nhận` / `Cancel record`, with an optional "Purchase Request" noun and an id prefix.
- **Any extra word is not a confirmation:** a different reference, "trên database runtime" or "rồi xóa …".
- **Rejected entry paths:**
  - a bare phrase without `/solve` gets guidance only;
  - a scheduled prompt (`CronCreate`, `ScheduleWakeup`, `RemoteTrigger`) is denied.
- **Kinds stay separate:** a PR record never confirms a Project create or a Step Update, and neither of those stores can authorize a PR (tested).

**Read-only flags.** The preview stays read-only: `read_only: true`, `executable: false`, `authorization: null`. `confirmation_available` is true only when an operation is present. `confirmation_blockers` names why there is no operation:
- `RUNTIME_EXECUTION_DISABLED`;
- `PURCHASE_REQUEST_ALREADY_RECORDED`;
- `OPERATOR_IDENTITY_*`.

## 8. Exact execution authorization

**Allowlist:**
- `TEST_MODE_COMMANDS` is `{merchant create, project create, step update, procurement update}`.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False` is unchanged.
- `procurement update` runs only when **all** of these hold:
  - the run has its own confirmed PR record;
  - the argv equals that record's canonical operation;
  - the target is test;
  - the operator still matches;
  - the unique index exists.

**Not enabled, and tested:**
- general procurement update: a typed scope is refused, and a non-canonical argv is rejected at scope validation;
- Purchase Order and Payment Request: never confirmable;
- `document approve` and `document revision-create`: not in test mode;
- signing: no command;
- runtime: refused at preview, gate and preflight.

## 9. RED/GREEN evidence

**New tests:**

| File | Tests | Database |
|---|---|---|
| `tests/merchant/test_nl4d4a_purchase_request.py` | 86 | none |
| `tests/merchant/test_nl4d4a_purchase_request_postgres.py` | 20 | end-to-end through the real hooks, on disposable `PYTEST_NL4D4A_` fixtures |

**RED/GREEN results:**

| Run | Setup | Result |
|---|---|---|
| RED 1 | new modules removed, wiring at HEAD | both files fail at collection (`ImportError: purchase_request`) |
| RED 2 | new modules kept, the 12 wiring files at HEAD | unit **76 failed, 9 errors, 1 passed**; PostgreSQL **19 failed, 1 passed** |
| GREEN | sources restored (`cmp` byte-identical) | **106 passed** (86 + 20) |

The two tests that pass under RED cover boundaries that already held:
- runtime disabled and no other evidence write in test mode;
- the database itself rejecting a duplicate (migration 007 was already applied).

The test database hash was unchanged across RED 2.

**Coverage of the Phase 8 list:**

| Required | Test(s) |
|---|---|
| Valid PR confirmation | PG `…recorded_once_with_a_reconciled_receipt`; unit `valid_confirmation_yields_the_recorded_scope` |
| Missing / malformed operator | unit `missing_or_malformed_operator_identity_is_refused` (9 cases), `operator_change_after_confirmation…` |
| Operator substitution | unit gate (refused unspent) and preflight; PG `[operator-substituted]`, `operator_substitution_inside_the_transaction` |
| Duplicate Merchant/type/reference | unit preview/verify; PG `[duplicate-in-merchant]`, `database_itself_rejects…` |
| Same reference, other Project of the same Merchant | the same tests (blocked) |
| Same reference, other Merchant | unit `same_reference_at_another_merchant_is_allowed`; PG `…another_merchant_is_recorded` |
| Reference replacement | unit preview/verify; PG `[replacement]`, `[record-exists]` |
| Concurrent duplicate creation | PG `concurrent_duplicate_references_on_two_projects_commit_at_most_once`, `two_claims_for_one_operation_write_once` |
| Stale Project version / changed basis | PG `[project-version]`, `change_between_preflight_and_write…[project-version]`; unit verify |
| Wrong database target | unit `changed_scope_is_refused[runtime]`, `runtime_preview_is_never_confirmable` |
| Expired pending / wrong session / replay | unit `expired…`, `wrong_session…`, `replayed…`; PG replay |
| Handwritten scope | unit `a_handwritten_scope_is_never_authority` (both targets) |
| Model-generated actor ID | unit `changed_scope_is_refused[actor]`; PG `a_model_generated_actor_cannot_be_executed` |
| Mixed destructive request | unit `no_other_evidence_write_is_ever_confirmable[…xóa…]`, `edited_or_mixed_confirmation…` |
| Runtime write attempt | unit preflight `[runtime]`, `runtime_stays_disabled…` |
| Crash before commit | PG `crash_before_commit_rolls_back_everything` |
| Crash after commit | PG `crash_after_commit_settles_from_evidence_and_recovers_from_postgres` |
| Failed ledger persistence | PG `failed_ledger_persistence_rolls_back_the_record` |
| Forged success report | PG `…refused_before_any_spend` (EXECUTE_SUCCESS denied), `contradictory terminal` in the success test |
| Recovery from PostgreSQL alone | PG `recover_purchase_request_receipts` in the success and crash-after-commit tests |
| `requires_procurement=false` warning | unit `requires_procurement_false_is_allowed…`; PG preview note |
| No unintended Step transition | PG success test (every step equal before and after) |

**Intentional updates to accepted tests.** Each follows from an approved decision or the new migration.

| File | Change |
|---|---|
| `test_nl4d3_evidence_write_previews.py` | a PR reference change is now BLOCKED (DEC-P1c); `procurement update` is in test mode, and the typed scope is refused at the gate |
| `test_nl4c2a_step_execution.py` | the allowlist set includes `procurement update` |
| `test_nl2_project_create.py` | the allowlist set includes `procurement update` |
| `test_nl4d2_fix1_evidence_routing.py` | the allowlist set includes `procurement update` |
| `test_alert_delivery_lease_migration.py` | the runner discovers migration 7 |
| `test_project_payment_period_migration.py` | the runner discovers migration 7 (found by the first full run, §11) |
| `test_procurement_repository.py` | the INSERT parameters include the Project's `merchant_id` |
| `test_nl4d2_evidence_discovery.py` | the `EvidenceReader` test double gains the new holder read (no assertion changed) |
| `test_nl4d3_evidence_write_previews_postgres.py` | an autouse fixture unsets `MERCHANT_OPERATOR_ID`, so its "grants nothing" assertions do not depend on local configuration |

## 10. Concurrency, crash and replay results

| Case | Result |
|---|---|
| 4 concurrent claims, same operation key | 1 write, 1 COMPLETED claim |
| 2 Projects, same Merchant and reference, both past the application check | exactly 1 commit; the other gets `ProcurementConflictError` (unique index), and its claim and ledger rolled back |
| Replayed execute request in the task | no second write |
| Replayed `/solve Xác nhận ghi nhận` | blocked; run unchanged |
| State change after confirmation (6 kinds) | `PREFLIGHT:<reason>`; nothing spent, claimed or written |
| Change between preflight and write (duplicate, Project version) | in-transaction refusal; FAILED; claim REVOKED; nothing written |
| Operator swapped between preflight and write | in-transaction refusal; FAILED; REVOKED |
| Crash before commit (after INSERT, before event) | full rollback; FAILED; REVOKED |
| Ledger completion failure | the INSERT rolled back with the evidence; FAILED; REVOKED |
| Crash after commit, before delivery | settled SUCCEEDED from evidence; no run-state receipt; recovered from PostgreSQL alone; a retry writes nothing |

## 11. Full regression

Run sequentially, with no live `/solve` and no concurrent PostgreSQL process.

- **Targeted:** NL4D4A, 106 passed.
- **NL1–NL4D4A, procurement and end-to-end suites, in one process:** 1120 passed, 1 skipped, 1 failed.
  - The failure was one more exact allowlist-set assertion (`test_nl4d2_fix1_evidence_routing.py`), updated as in §9.
- **Full suite**, run alone, with runtime credentials blanked:
  - **First run:** 4525 passed, 20 skipped, 1 xfailed, **1 failed**. The failure was `test_project_payment_period_migration.py::test_migrations_are_discovered_in_version_order`, a second hard-coded migration list missing version 7. It was updated as in §9.
  - **Final run:** **4526 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests passed), in 6 min 43 s.
  - **Arithmetic:** 4526 = the accepted baseline of 4420 + the 106 new NL4D4A tests.
- **Other checks:**
  - `python .claude/system_test.py`: ALL TESTS PASSED.
  - Hook compile and import smoke (`intent_gate`, `policy_gate`, `merchant_direct_handoff`, `merchant_pending_confirmation`, `merchant_preview_delivery`, `team_result_hook`, every `.claude/hooks/*.py`): OK. `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.
  - `git diff --check`: clean (only the usual CRLF notices).

## 12. Database integrity

**Hashes** (from `db_integrity.py`, which hashes every `merchant_ops` table):

| Point | Hash | Note |
|---|---|---|
| Before NL4D4A | `ba419be9d17a7a6719f1ca864ff5bdc1fe01848a7ad65a857e023715d028a319` | the accepted baseline |
| After migration 007 | `60ea5bc9b4297182f895deadf83d82b905b8c0e0ae380d368910167795e3b3d4` | only `schema_migrations` gained row 7; every business table count is identical and `procurement_records` is empty, so the column addition changes no row; see the equivalence check below |
| After the GREEN PostgreSQL runs | `60ea5bc9…` | identical |
| After RED 2 | `60ea5bc9…` | identical |
| After the final full suite | `60ea5bc9…` | identical |

**Equivalence check:** re-hashing the test database exactly as `db_integrity.py` does reproduces the NL4D3 baseline `ba419be9…` **exactly**, with two adjustments:
- `schema_migrations` restricted to versions 1–6;
- `procurement_records` read without the new `merchant_id` column.

So the only change to the test database is migration 007 itself. No business row changed.

**Counts and leftovers:**
- Merchants 2, Projects 4, steps 92, events 9, claims 20, ledger 4, procurement 0, `PYTEST%` Merchants 0.
- No leftover fixtures, no orphan claims, no new ledger rows.

**Untouched:**
- The NL2/NL3/NL4C acceptance Projects, including NL4C2B `8dd4c68d-…`. The NL4D3 PostgreSQL previews only read it.
- No manual cleanup was done.

**Pending confirmations:**
- The live state directory holds only three earlier, already-CONFIRMED and expired records (NL3 and NL4C2B acceptances), untouched.
- There is no Purchase Request store.

**Production:** the database was never constructed or connected. Every test repository is `role="test"`, and `.env` runtime passwords were blanked for all runs.

## 13. Remaining risks

1. **Operator trust is local.** Same-OS-user processes, including teammates with general Bash, can change `.env` or the environment. It is attribution, not authentication.
2. **Runtime schema.** Runtime is not migrated. Runtime writes are disabled, the preflight requires the index, and the INSERT now names `merchant_id`, so an un-migrated runtime fails closed. A runtime migration needs separate approval.
3. **General engine path.** DEC-P1c is enforced in the preview and the confirmed path only. The general `procurement update` engine path still permits a reference change. It is not executable: the typed scope is refused and the preflight requires the confirmed record. It is reachable only by a raw developer CLI against the test database.
4. **Status-only PR records.** A PR record that has a status but no reference cannot get its first reference through this path (create-only). That needs a decision if such records ever exist; none exist today.
5. **Agent wording not updated.** `merchant-manager.md` and `solve.md` do not yet tell the teammate or lead to offer `/solve Xác nhận ghi nhận`. This was deliberately deferred so running teammates don't become STALE_DEFINITION. It is required for NL4D4B.
6. **Spent before dispatch.** The pending record is spent at confirmation, as in NL3 and NL4C. A refused dispatch then needs a new preview.
7. **Receipt on the normal path only.** After a crash between commit and settlement, the attempt settles SUCCEEDED from evidence, and the receipt is rebuilt with `recover_purchase_request_receipts`.
8. **Strict basis.** Any change to the Project row or its procurement rows, or a new holder of the reference, invalidates a confirmation. Records of *other* references on *other* Projects do not.
9. **Exact-match uniqueness.** It is case- and format-sensitive, as decided. `PR-001` and `pr-001` can coexist.
10. **Event privacy.** The PROCUREMENT event records `external_id_recorded`, not the reference itself (the existing design). The receipt reads the reference from the stored row.

## 14. GO / NO-GO

- **NL4D4A:** GO for your acceptance review. It is not committed.
- **NL4D4B (controlled live acceptance on the test database):** NO-GO until all of these are done:
  1. you accept NL4D4A and authorize the commit separately;
  2. you set `MERCHANT_OPERATOR_ID` (a UUID you choose) in the untracked `.env`;
  3. `merchant-manager.md` and the `solve.md` evidence section are updated so that a confirmable test-database PR preview offers `/solve Xác nhận ghi nhận`, and a fresh Claude Code session is started;
  4. a designated throwaway Project on `coding_agent_merchant_test` is used (never the NL2/NL3/NL4C acceptance Projects), with the integrity hash taken before and after;
  5. one preview, one confirmation and one execution are run. Check:
     - the receipt is RECONCILED;
     - exactly one PROCUREMENT event, with `triggered_by` equal to the operator;
     - the claim is COMPLETED;
     - a replayed confirmation is refused;
  6. no other PostgreSQL test process runs during the live run.
- **Runtime/production Purchase Request, Purchase Order, Payment Request, approval, revision or signing execution:** NO-GO. These are outside this checkpoint.

## 15. Final acceptance (security review, migration acceptance, commit)

This section records the final review run before the commit. No live `/solve` write was performed, agent instructions were not changed, and runtime Direct EXECUTE stays disabled.

### 15.1 Implementation review against the approved decisions

I re-read every source, migration and test change, plus `cp12h_nl4d_decision_register.md`.

| Decision | Where it is enforced | Verdict |
|---|---|---|
| DEC-A0, trusted operator attribution | `operator_identity.py`: environment or untracked `.env` only, canonical non-nil UUID. Checked at preview, capture, gate, preflight and in the transaction. Written as `project_events.triggered_by`. | matches |
| DEC-P1a, unique (merchant, type, reference) | preview block, `verify_purchase_request` (preflight and in the transaction), migration 007's partial unique index | matches |
| DEC-P1c, PR create-only, no replacement | the preview blocks a replacement; the confirmed path accepts only an INSERT plan and refuses any existing PR record | matches |
| DEC-P2, PR allowed with `PROCUREMENT_NOT_REQUIRED` | the preview note; no Step or workflow change | matches |

**Not enabled:**
- approval, revision, signing, Purchase Order and Payment Request execution;
- any runtime write.

`document approve` and `document revision-create` are not in `TEST_MODE_COMMANDS`. PO and Payment Request previews never carry an operation.

**Review conclusion:** no defect found that requires a code change. The unchanged nuances are listed in §15.7.

### 15.2 Migration 007 review and Merchant ownership

`scratchpad/nl4d4a_migration_audit.py` passed **20/20** checks against the real test database. Every mutating check ran in a transaction that was always rolled back. The integrity hash was `60ea5bc9…` before and after.

| # | Requirement | Evidence |
|---|---|---|
| 1 | Each record's Merchant matches its Project's Merchant | stored records: 0 (none mismatched); the composite FK `(project_id, merchant_id) → projects(id, merchant_id) ON UPDATE CASCADE` exists and is validated (`convalidated = true`) |
| 2 | Existing records backfilled correctly | after the documented reversal, 3 seeded pre-migration rows got their own Project's Merchant |
| 3 | No inconsistent ownership can persist | the database refused all of these (FK / NOT NULL violations):<br>• an INSERT naming another Merchant;<br>• an INSERT without a Merchant;<br>• an UPDATE moving a row to another Merchant's Project;<br>• an UPDATE of `merchant_id` alone. |
| 4 | Uniqueness enforced transactionally | duplicate INSERT and colliding reference UPDATE refused (`UniqueViolation`); the PG concurrency test commits at most one of two racing transactions |
| 5 | Duplicates detected before migration | the read-only pre-migration audit query (run before applying: 0 rows, 0 duplicates) detects a seeded duplicate |
| 6 | Existing records and statuses preserved | all 8 original columns of the seeded rows are identical before and after the migration (statuses included) |
| 7 | Migration metadata consistent | `schema_migrations` row 7 checksum `d3c475c1…` equals the file's SHA-256; the runner `--plan` reports applied 1–7, nothing pending, no checksum conflicts |
| 8 | Runtime unmigrated and disabled | the runner was only ever invoked with `--database test`; the runtime database was never connected to, so its schema was not inspected; `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; the preflight refuses without the index (`PROCUREMENT_REFERENCE_CONSTRAINT_MISSING`) and a procurement INSERT without the column fails closed |
| 9 | Rerun is safe and predictable | the runner skips applied versions and refuses edited files by checksum; re-executing the SQL by hand fails at its first statement (`DuplicateColumn`) and changes nothing |
| — | Fail closed on an existing duplicate | the migration fails with `UniqueViolation`, leaves no partial column and merges or deletes nothing |
| — | Documented reversal | the reversal SQL in the migration header runs cleanly (inside the rolled-back audit) |

**Ownership is enforced by the database,** not only by application convention. Every reachable write path is covered by the same foreign key:
- the repository INSERT, which passes the plan's Merchant;
- the repository UPDATE, which never changes `project_id` or `merchant_id`;
- any raw SQL.

A Project's Merchant change cascades to its procurement rows, and is refused if that would create a duplicate reference.

### 15.3 Authorization boundaries

**Allowed:** only a trusted NL4D4A PR confirmation can authorize a test-only PR create. The preflight requires all of the following:
- this run's own CONFIRMED PR record (owner session and `confirmed_run_id`);
- its canonical argv, equal to the staged argv;
- the test target;
- the same Project, reference and operator.

**Refused:**
- **Handwritten scopes:** `--merchant-scope ["procurement","update",…]` is blocked at the intent gate on both targets.
- **General update bypass:** a procurement scope without the preview fields has no confirmed record, so the preflight refuses it. A confirmed-looking payload must be the canonical argv (scope validation), and `verify_purchase_request` rejects any extra field (`--status`, `--expected-version`, `--triggered-by` and so on).
- **Reference overwrite:** the newly enabled path is INSERT-only. An existing PR record refuses with `…REPLACEMENT_UNSUPPORTED` or `…ALREADY_RECORDED`, and the unique index backs it.
- **Model-generated operator:** never trusted. An edited `--operator-id` gives `PURCHASE_REQUEST_CONFIRMATION_MISMATCH`, and an operator named in the request text is ignored.
- **Cross-kind authorization:** Project and Step stores never authorize a PR, and the reverse.

**Operator source:** only local configuration. An operator change after the preview makes the pending record unusable:
- the capture is UNVERIFIED;
- the confirmation is refused and the record stays PENDING until it expires;
- the preflight refuses;
- an in-transaction change is refused.

**Runtime:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`. The preview, gate and preflight all refuse runtime.

**Other write gates:** unchanged. They are covered by the NL2–NL4D3 regression: Project create, Step update, completeness, pane identity, staging, terminal consistency.

### 15.4 Execution and receipt evidence

All of these come from the existing automated tests, re-run in this phase.

| Property | Test (PostgreSQL unless noted) |
|---|---|
| Single-use confirmation | replayed `/solve Xác nhận ghi nhận` blocked; unit tests for replay, expiry and wrong session |
| Exact Project, Merchant and reference binding | canonical argv, basis and record checks; unit `changed_scope_is_refused[actor,reference,runtime]` |
| Revalidation before spend | `…refused_before_any_spend[6 cases]` (nothing spent, claimed or written) |
| Revalidation under locks | `change_between_preflight_and_write…[duplicate-reference, project-version]`, `operator_substitution_inside_the_transaction` (FAILED, claim REVOKED) |
| Atomic record + event + claim + ledger | crash before commit; failed ledger persistence (full rollback, fenced) |
| Durable operator attribution | the event's `triggered_by` equals the operator; the receipt's `operator_id` |
| Exactly once | replayed execute request; 4 concurrent claims give 1 write; two-Project race gives 1 commit |
| Post-commit crash recovery | `crash_after_commit…` settled SUCCEEDED from evidence; a retry writes nothing |
| Reconstructed PostgreSQL receipt | `recover_purchase_request_receipts` equals the run-state receipt (event, record, transaction, attempt, operator, reference) |
| No unintended Step transition | every step's status and version are equal before and after |

### 15.5 Final regression

Run sequentially, with no live `/solve` and no concurrent PostgreSQL process.

| Run | Result |
|---|---|
| NL4D4A unit | 86 passed |
| NL4D4A PostgreSQL | 20 passed |
| NL1–NL4D3, procurement, migration and direct-execute end-to-end suites | 1022 passed, 1 skipped |
| Full suite | **4526 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests), 7 min 06 s; equals the expected accepted regression |
| `system_test.py` | ALL TESTS PASSED |
| Hook compile/import smoke | 63 files compiled (every `.claude/hooks/*.py` plus the NL4D4A modules); `intent_gate`, `policy_gate`, `merchant_direct_handoff`, `merchant_pending_confirmation`, `merchant_preview_delivery` and `team_result_hook` import; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean |

### 15.6 Database integrity (final)

- **Hash:** `60ea5bc9b4297182f895deadf83d82b905b8c0e0ae380d368910167795e3b3d4`, unchanged from the post-migration baseline after the migration audit, the targeted runs, the NL regression and the full suite.
- **Equivalence:** the pre-migration re-hash (§12) still reproduces `ba419be9…` exactly.
- **Counts:**
  - Merchants 2, Projects 4, steps 92, events 9, procurement 0, `schema_migrations` 7;
  - claims 20, **all COMPLETED** (no ACTIVE or orphan claim);
  - ledger 4 (no new rows); 0 `pytest:` claims or ledger rows; 0 `PYTEST%` Merchants.
- **Acceptance Projects unchanged:**
  - NL2 `30fffeaf-…` "Beta Nguyễn Văn Cừ" PLANNED v1;
  - NL3 `ba5cc7ec-…` PLANNED v1;
  - NL4C2B `8dd4c68d-…` PLANNED v1, whose step 1 `98dc77cf-…` is **IN_PROGRESS, version 2**.
- **Pending confirmations:** no Purchase Request store exists. The three earlier records are unchanged (all CONFIRMED and expired).
- **Production:** never connected to.

### 15.7 Remaining risks

The risks in §13 stand. These are the points most relevant to acceptance:

1. **The trusted operator is a workstation boundary.** It is not authentication or approver authorization.
2. **The runtime schema is unmigrated and was not inspected,** because production was never connected. Applying 007 there needs a separate, approved runtime migration plan, starting with the read-only duplicate audit (§15.2 #5).
3. **The general engine path is not executable.** P1c is enforced on the enabled path, and the unique index applies everywhere, but the general engine still permits a reference change.
4. **An operator change leaves the pending record PENDING but unusable** until its 15-minute expiry, rather than deleting it.
5. **The decision register stays an uncommitted local file.** `cp12h_nl4d_decision_register.md` still marks A0, P1a, P1c and P2 as PROPOSED, so I left it out of this commit (§15.9). The approvals are recorded in this report.

### 15.8 GO / NO-GO

- **NL4D4A: GO.** Every security, migration and regression gate passed, so it is committed (§15.9).
- **NL4D4B (controlled live acceptance on the test database): NO-GO until all of these are done:**
  1. you set `MERCHANT_OPERATOR_ID` (a UUID you choose) in the untracked `.env`. It is not committed and must never be;
  2. `merchant-manager.md` and the `solve.md` evidence section are updated so that a confirmable test-database PR preview offers `/solve Xác nhận ghi nhận`, then a fresh Claude Code session is started. This was not done here, as instructed;
  3. a designated throwaway Project on `coding_agent_merchant_test` is used (never the NL2/NL3/NL4C acceptance Projects), with the integrity hash taken before and after;
  4. one preview, one confirmation and one execution are run. Check:
     - the receipt is RECONCILED;
     - exactly one PROCUREMENT event, with `triggered_by` equal to the operator;
     - the claim is COMPLETED;
     - a replayed confirmation is refused;
     - an independent read-only PostgreSQL verification agrees;
  5. no other PostgreSQL test process runs during the live run.
- **Runtime and production:** NO-GO. Applying migration 007 to runtime, or any runtime write, needs a separate approval.

### 15.9 Commit

**Commit:** `feat(merchant): add trusted test-only purchase request foundation`. Its hash is in the session report, because a file cannot contain the hash of the commit that adds it. Nothing was pushed.

**Staged by name (28 files; no `git add -A`):**
- **Source (12 modified):**
  - `.claude/agents/tools/merchant/`: `cli.py`, `evidence_preview.py`, `read_commands.py`, `write_adapters.py`;
  - `.claude/clients/merchant/`: `attempt_evidence.py`, `procurement_repository.py`, `read_repository.py`;
  - `.claude/hooks/`: `intent_gate.py`, `merchant_direct_handoff.py`, `merchant_pending_confirmation.py`, `merchant_preview_delivery.py`;
  - `.claude/system/merchant_runtime_handoff.py`.
- **Source (3 new):**
  - `.claude/agents/tools/merchant/purchase_request.py`;
  - `.claude/clients/merchant/operator_identity.py`;
  - `.claude/clients/merchant/migrations/007_procurement_reference_uniqueness.sql`.
- **Docs:** `CLAUDE.md` (the NL4D4A paragraph) and this report.
- **Tests (9 modified):** `test_alert_delivery_lease_migration.py`, `test_nl2_project_create.py`, `test_nl4c2a_step_execution.py`, `test_nl4d2_evidence_discovery.py`, `test_nl4d2_fix1_evidence_routing.py`, `test_nl4d3_evidence_write_previews.py`, `test_nl4d3_evidence_write_previews_postgres.py`, `test_procurement_repository.py`, `test_project_payment_period_migration.py`.
- **Tests (2 new):** `test_nl4d4a_purchase_request.py`, `test_nl4d4a_purchase_request_postgres.py`.

**Not staged:**
- `.env` and the operator configuration (not set, and never committed);
- `.claude/runtime/*` local state;
- scratchpad scripts;
- `cp12h_nl4d_decision_register.md`, an uncommitted NL4D-DEC deliverable that still says PROPOSED (§15.7 #5).

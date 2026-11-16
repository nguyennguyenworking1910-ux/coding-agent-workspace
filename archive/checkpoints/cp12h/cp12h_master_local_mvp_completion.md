# CP12H.MASTER — Complete Merchant Project Lifecycle for Local MVP

Branch `feat/cp7-9-merchant-reliability`. Date 2026-11-12.

**State of the work:**
- Committed in this program (Phase A): `4d7dbb9` (migration 008), `f644988` (migration 009 + policy), `1ba8348` (migration line-ending pin).
- Implementation (Phases B–K): reviewed and committed in CP12H.MASTER-FINAL (§14).
- **Runtime:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False` throughout. The runtime database was never connected or migrated. Nothing was pushed.
- **Live acceptance:** **not performed.** No live `/solve` was run, and no confirmation was typed by the user. §12 is the runbook.

---

## 1. Final architecture

There is **one writer.** Every new write runs through the existing trusted Direct EXECUTE pipeline:

1. **NL request.** The intent gate (`project_nl`) classifies the request as EVIDENCE_WRITE and runs it as a read-only `merchant_read`.
2. **`evidence preview`.** It judges the request with the domain engines and builds a `requested_operation` (NOT_AUTHORIZED) through `lifecycle_operation.build_operation`.
3. **Verified capture.** The PostToolUse hook (`merchant_preview_delivery`) creates the **lifecycle pending record**: session-owned, 15 minutes, single use, keyed by `operation_id`.
4. **User confirmation.** The user types `/solve Xác nhận thực hiện <code>`. The intent gate (`confirm_pending_lifecycle`) spends the record into a scope.
5. **Preflight** (`merchant_direct_handoff._confirmed_lifecycle_operation` and `_verify_lifecycle`) checks:
   - the confirmed record for *this* run, with the identical argv;
   - the trusted operator, unchanged;
   - schema ≥ 010 and the reference index;
   - `lifecycle_operation.verify`: re-read, re-judge, recompute the basis.
6. **Write transaction** (`evidence_bound_repository`): claim + ledger + mutation + event. The write adapter `_confirmed_lifecycle` passes a `precondition` that runs `verify` again **under the repository locks**.
7. **Receipt.** `attempt_evidence.lifecycle_receipt` reconciles it from the ledger, claim, the single event and the entity row of one `xmin`. `recover_lifecycle_receipt` rebuilds it from PostgreSQL alone.

**Steps** use the existing NL4C Step Update pipeline. A gate Step with no stored-evidence evaluator is completed by a confirmed operation carrying `gate_attestation: OPERATOR_ATTESTED`.

**The Purchase Request path (NL4D4A) is unchanged:** its own store, `/solve Xác nhận ghi nhận`, and its own receipt.

**New and changed components:**

| Component | Role |
|---|---|
| `.claude/agents/tools/merchant/lifecycle_operation.py` (new) | judge, basis, canonical argv, validation, payload mapping and `verify` for all 7 lifecycle operations |
| `evidence_preview.py` | revision (metadata-only), decision, signing, PO/Payment Request, Project start and completion previews; operation building |
| `project_nl.py` | classifies signing and Project start/completion; names end at an ISO date; a second recorded operation makes the request MIXED |
| `step_preview.py` | attested gates; the final-Step rule; the activation note |
| `write_adapters.py`, `cli.py`, `cli_contract.py`, `completeness.py` | `document sign`; binding flags; `--gate-attestation`; the confirmed-lifecycle executor |
| Repositories (document, approval, signing, transition, read) | in-transaction `precondition`; `evidence_status`, `recorded_by`/`decided_at`, `signing_attestation`; evidence labels read via `to_jsonb` (NULL on the runtime schema) |
| Hooks (`intent_gate`, `merchant_pending_confirmation`, `merchant_direct_handoff`, `merchant_preview_delivery`, `policy_gate`), `system/merchant_runtime_handoff.py` | the fourth pending store, the phrases, preflight, receipts, canonical-argv validation |
| `attempt_evidence.py` | `lifecycle_receipt`, `recover_lifecycle_receipt` |

## 2. Implemented business operations (test database only)

| Operation | Example request | Command | Rules enforced (preview, preflight and in the transaction) |
|---|---|---|---|
| Start Project | "Bắt đầu Project X trên database test" | `project update --status IN_PROGRESS` | PLANNED → IN_PROGRESS; exact version |
| Metadata-only revision | "Tạo phiên bản hợp đồng mới cho Project X …" | `document revision-create` | METADATA_ONLY, hash `metadata-only:<id>`; supersedes the active unsigned revision; **a signed active revision is never superseded** (D4e); a typed hash is refused |
| Approval / rejection | "Legal đã phê duyệt …", "Partner đã từ chối …, ghi chú: …" | `document approve` | one role and one final decision; latest active unsigned revision; optional note and ISO date (not in the future); `approved_by` NULL, `recorded_by` = operator; a decided row is immutable (trigger) |
| Operator-attested signing | "Ghi nhận hợp đồng của Project X đã ký" | `document sign` (new) | the existing gate (3 × APPROVED + Purchase Request if required); a REJECTED role blocks it; already signed fails; `signing_attestation = OPERATOR_ATTESTED_SIGNED` |
| Purchase Request | "Ghi nhận Purchase Request PR-… cho …" | `procurement update` | **unchanged NL4D4A** (`/solve Xác nhận ghi nhận`) |
| Purchase Order / Payment Request | "Ghi nhận Purchase Order PO-… cho …" | `procurement update --type PURCHASE_ORDER/PAYMENT_REQUEST` | create-only; exact reference; unique per (Merchant, type, reference); existing prerequisites (signed revision; PO for the Payment Request) |
| Complete a gate Step without an evaluator | "Hoàn thành bước 22 của Project X …" | `step update … --gate-attestation OPERATOR_ATTESTED` | completion only (starting needs nothing); predecessors; **final Step only when every other Step is COMPLETED or legitimately SKIPPED** |
| Complete Project | "Hoàn tất Project X trên database test" | `project update --status COMPLETED` | every Step COMPLETED, SKIPPED or SUPERSEDED; the final Step COMPLETED; IN_PROGRESS; exact version. Never implied by completing a Step. |

## 3. Policy simplifications (owner-approved DEC-SIMPLIFY, -a, -b)

- **Confirmation is the authority.** No upload, approver verification, role accounts or second operator.
- **Superseded proposals:** S1, S2, D1a/b, G1 and G2 (register updated, history kept).
- **Legacy and metadata-only revisions** may satisfy ordinary workflow gates. They are labelled and never presented as verified files.
- **Gate attestation.** An evaluator-less APPROVAL_GATE guards **completion only** (P7). Before this, such Steps could not even start: every transition demanded a gate result.
- **Merchant activation.** Completing "Activate Merchant" activates the Merchant in the same transaction. The activation prerequisites are re-checked there, so it is refused atomically if they don't hold. The preview states it (`MERCHANT_ACTIVATION_IN_SAME_TRANSACTION`). Before this, every INTEGRATION_NEW_MERCHANT completion was blocked.

## 4. Migration history (test database)

| Version | Change | Checksum | Commit |
|---|---|---|---|
| 008 | `document_files`, evidence classification, composite FK, immutability triggers | `83547cf8…` | `4d7dbb9` |
| 009 | `METADATA_ONLY` class and its content marker | `c4cd03a3…` | `f644988` |
| — | `.gitattributes`: pin each migration's checkout line endings to the applied bytes. A fresh checkout reproduced none of the LF migrations' checksums before; every checksum matches now. | — | `1ba8348` |
| **010** | `document_approvals.recorded_by` and `decided_at` (CHECK: decisions only); trigger `document_approvals_decision_immutable`; `document_revisions.signing_attestation` (CHECK: `OPERATOR_ATTESTED_SIGNED` only, on signed rows); the extended `reject_document_evidence_change` (a signed revision stays signed as recorded) | `6a7821a19877458cc297dad0f814a0ab358baf99d9849a8c020903cd1a95858d` | **uncommitted** |

**Migration 010 evidence:**
- Dry run 9/9 PASS (rolled back; hash unchanged).
- `--plan` showed exactly 010 pending; `--apply` succeeded.
- RED was 18 failed / 1 passed; GREEN all passed.

## 5. Trusted execution contracts

- **Operation** (`validate_operation`): command and kind consistent, NOT_AUTHORIZED, test target, canonical UUIDs, non-nil operator, exact param set per kind, and argv equal to `canonical_argv`. Any edit is rejected; there are 8 tampering cases in the tests.
- **Basis:** sha256 over the operation, its params and the operator, the Project row, and the steps, dependencies, revisions, approvals, procurement records and reference holders. Any change refuses the operation with `LIFECYCLE_BASIS_CHANGED`.
- **Payload:** the strict field allowlist per kind (`params_from_payload`). A metadata-only revision's hash must be its marker. A CLI-generated `procurement_id` is allowed, as for the Purchase Request.
- **Refusals before any spend:**
  - `LIFECYCLE_CONFIRMATION_REQUIRED` / `_MISMATCH`;
  - an operator reason;
  - `LIFECYCLE_SCHEMA_MISSING`;
  - a re-judgement reason (`LIFECYCLE_BASIS_CHANGED`, `APPROVAL_REJECTED_BLOCKS_SIGNING`, …).
- **In the transaction:** a change between the preflight and the write fails the attempt, which is fenced with a REVOKED claim.
- **Runtime target:** these commands keep their earlier contract there, and runtime stays disabled in code. The new rules bind the test database (`is_lifecycle_attempt(..., database_target)`).
- **Receipt:** exactly one Project event in the ledger's transaction, of the expected entity and event type, with `triggered_by` = the operator, and the entity row written in the same transaction holding the confirmed values (for example `approved_by IS NULL`, `recorded_by` = the operator, METADATA_ONLY).

## 6. Natural-language integration

- **Classification:** signing ("ký", "đã ký", "sign", "signed") and Project start and completion ("Bắt đầu / Khởi động / Begin / Kick off project", "Hoàn tất / Hoàn thành / Đóng / Complete / Close / Finish project") are EVIDENCE_WRITE.
- **Step nouns win:** "Hoàn thành bước Complete project …" stays a Step Update.
- **Names** end at an ISO date (and at "ngày" or "dated"), and at "as" or "signed".
- **Second operations:** "… và ghi nhận …" is MIXED, one operation per preview.
- **Document type:** the documented alias "hợp đồng" / "contract" → CONTRACT. Otherwise an explicit type (DEC-D4g list still pending).
- **Notes** come after "ghi chú:" / "notes:" / "lý do:" (quoted or to the end; a trailing database-target phrase is removed). They are carried as `decision_note`, because `notes` is a redacted field name. Stored notes stay redacted on reads.
- **Dates:** one ISO date is the decision or signing date; two ask; a future date is refused.
- **Refusals:**
  - negated requests yield nothing;
  - a runtime target is refused with `RUNTIME_EXECUTION_DISABLED`;
  - a missing operator is refused with `OPERATOR_IDENTITY_NOT_RESOLVED`;
  - ambiguous roles or document types ask;
  - a missing reference asks;
  - a duplicate reference is BLOCKED.
- **Confirmation phrases:** exact `/solve Xác nhận thực hiện [<code>]`, `Hủy thực hiện`, `confirm operation` / `cancel operation`. A lifecycle phrase never confirms another kind, nor the reverse. Scheduled prompts are denied.
- **Agent docs:** `merchant-manager.md` and `solve.md` are updated. The teammate never confirms, never names an approver, and offers no scope.
- **Start vs create (fixed in CP12H.MASTER-FINAL, RED/GREEN).** "Start / Begin / Kick off project X" and "Bắt đầu / Khởi động Project X" start an existing Project. Only an article or "new" before the noun ("Start a new project …"), or a Project type, makes it a creation; "Tạo / Create project …" is unchanged. "Khởi động" is never read as "đóng" (close).
- **Exact Merchant for writes (fixed in CP12H.MASTER-FINAL).** A write preview refuses a Merchant phrase of which only a leading part names a Merchant ("Merchant Beta Khác Cinemas" never binds Beta Cinemas). Reads keep ignoring trailing field words.

## 7. RED/GREEN tests

| Suite | Result |
|---|---|
| `test_master_migration_010_postgres.py` (new) | RED 18 failed / 1 passed → GREEN 19 passed |
| `test_master_lifecycle_contract.py` (new, no DB) | 43 passed |
| `test_master_lifecycle_postgres.py` (new, full hooks) | 20 passed |
| `test_master_final_routing.py` (new) | RED 3 failed / 12 passed → GREEN 15 passed |
| 008 suite (+3 concurrency cases) / 009 suite | 45 / 19 passed |

**`test_master_lifecycle_postgres.py` covers:**
- **Full lifecycles:**
  - cinema opening: start, revision, three approvals, signing gate, signing, PO, Payment Request, attested Steps 21–22, completion, 11 claims;
  - media top-up with procurement, through the unchanged Purchase Request path;
  - Merchant integration, with four attested gates and **Merchant activation**.
- **Rejection:**
  - PARTNER REJECTED blocks signing;
  - a decision is final;
  - a new revision starts a new cycle;
  - a signed revision is never superseded.
- **Authority and staleness:**
  - replayed confirmation;
  - stale preview, refused before spend;
  - changed operator;
  - model-edited argv;
  - a typed scope;
  - a wrong Project.
- **Failure and recovery:**
  - a change between preflight and write, refused in the transaction (REVOKED);
  - a crash before commit, rolled back;
  - a crash after commit, settled from evidence, with recovery;
  - four concurrent executions write once.

**Existing tests changed on purpose** (each states the owner-approved change in a comment):
- exact `TEST_MODE_COMMANDS` / `WRITE_COMMANDS` / completeness sets;
- NL4D3 previews (no POLICY_UNDECIDED; metadata-only; signing is a previewed write);
- NL4B/NL4C evaluator-less gates (attested instead of never READY);
- the integration Step block;
- the NL4C2B concurrency scenarios: a raw APPROVED→REJECTED flip is now refused by the database (migration 010). They use the owner-only removal instead, and assert the refusal.
- a typed test-target `project update` is refused at the intent gate;
- the migration lists, and the "last migration" assertions of 008/009.

**Defects found and fixed during the program:**
- the `document approve` completeness contract named `revision_id`, while the payload carries `document_revision_id`, so no approve scope could ever pass;
- `notes` / redaction collisions;
- the final Step was defined by "no successor", which misfires on SKIPPED conditional Steps; it is now the highest-numbered Step;
- the migration line-ending checksum hazard.

## 8. Full regression

Run sequentially; runtime credentials blanked; no live `/solve`. Runs 1 and 2 found the regressions listed in §7, which were investigated and fixed or restated. Final:

| Check | Result |
|---|---|
| Full pytest (final, CP12H.MASTER-FINAL) | **4797 passed, 21 skipped, 1 xfailed, 0 failed** (97 subtests), 8 min 55 s. Before the program: 4695. CP12H.MASTER: 4776. MASTER-FINAL added 21 tests. |
| New suites | migration 010 (19), lifecycle contract (43), lifecycle end-to-end (14), 008 concurrency cases (+3) |
| Existing suites | Purchase Request, Step Update, Project Create, evidence preview and all migration suites, all within the full run |
| `system_test.py` | ALL TESTS PASSED |
| Hook compile and import (hooks, merchant tools, clients) | OK; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean |

## 9. Database integrity (test database, read-only)

| Item | Value |
|---|---|
| Post-009 baseline before 010 | `ada0d51db2c2c0cab3b73c608625e1a4cddc1a2d6ec318f7f3878ec9d496483e` (re-verified independently) |
| Hash after the 010 dry run (rolled back) | `ada0d51d…`, unchanged |
| **Post-010 full hash (new baseline)** | **`fa9cba01f51974d8836921e348f9154dfcf4223c0545c38a774cdf51dbd6371a`** |
| Equivalence: excluding only `schema_migrations` row 10 | **`ada0d51d…`**, reproduced exactly: no business row changed |
| Hash after every test run | unchanged (all fixtures removed; 0 `PYTEST` Merchants, 0 test claims) |
| Migrations | 1–10, nothing pending, no checksum conflict; a fresh checkout of each file reproduces its applied checksum |
| Accepted records | 22 claims, all COMPLETED; 6 ledger rows, 0 orphans; NL4C2B Step 1 IN_PROGRESS v2; NL2/NL3/NL4D4B Projects and PR-NL4D4B-001 untouched; 0 revisions, approvals and files |
| Runtime database | not connected, not migrated |

## 10. End-to-end results

All three end-to-end lifecycle tests pass on `coding_agent_merchant_test` with disposable `PYTEST_MASTER_` fixtures. The fixtures are removed after every test; the check is "no residue: 0 Merchants, 0 claims with the test key prefix".

Every write:
- was previewed by the CLI and captured by the trusted hook;
- was confirmed by a `/solve` phrase through the real intent gate (simulated prompts in tests, never a live session);
- was executed once;
- left exactly one COMPLETED claim and a reconciled receipt, recoverable from PostgreSQL alone.

## 11. Security and remaining limitations

**Preserved:**
- exact Merchant and Project identity (`--merchant-code` re-checked);
- trusted operator attribution;
- read-only previews;
- session-bound single-use confirmations;
- canonical argv;
- basis revalidation (preflight + transaction);
- atomic claim/ledger/mutation/event;
- exactly-once execution, fencing and UNCERTAIN semantics;
- PostgreSQL receipts;
- no typed or model-built scopes;
- runtime disabled.

**Limitations:**
1. **No live acceptance yet** (§12).
2. **Ordinary Steps.** A dedicated end-to-end test drives ordinary Steps through the full confirmed Step Update pipeline: start, completion and READY on a successor, each with a reconciled receipt and PostgreSQL recovery, plus a refused missing-predecessor start. Attested and final Steps also run through it. The long lifecycle tests still advance their remaining ordinary Steps with repository fixtures, for speed.
3. **MEDIA_TOP_UP_EXISTING_DOCUMENT is supported since CP12H.MASTER-FIX (§15).** The earlier blocker, a cross-Project signed revision for the PO prerequisite, was resolved by the owner's approval of signed revision reuse for the Local Test MVP.
4. **DEC-D4g canonical document-type list:** still undefined (pattern plus the "hợp đồng" → CONTRACT alias).
5. **The owner can still bypass immutability.** It is enforced by triggers, which the owner role can drop; DELETE of approvals is not granted to the app role.
6. **Recorded decisions and signatures are attestations**, not verified facts (labelled everywhere).
7. **Step previews** ("… của Merchant …") still use the read-side Merchant matching. The Merchant code is still bound in the operation and re-checked in the transaction.
8. **Managed file upload (NL4D5A2/A3)** remains optional and unimplemented.
9. **Runtime database** is unmigrated (schema 1–7); `runtime_readiness.EXPECTED_TABLES` is unchanged.

## 12. Live acceptance runbook (user-driven; one operation at a time)

**Not performed.** This is the procedure for you to run. Automated tests are not live acceptance.

### Prerequisites

- A **fresh** Claude Code session inside psmux. The agent docs and hooks changed, so a reused teammate would be stale.
- Docker test DB up (`coding-agent-rag-db`, port 5434).
- `MERCHANT_OPERATOR_ID` set in `.env` (fingerprint `210a4c001d41`).
- Migrations 1–10 applied, with nothing pending.
- `python .claude/system_test.py` passes.
- **No PostgreSQL tests running during the session.**

### Rules for every step

1. Type the request exactly as shown (keep `trên database test`).
2. Read the preview: outcome, `summary`, `policy_notes`, Project, Merchant and the recording-operator status.
3. Type **only** the confirmation the preview offers.
4. Read back PostgreSQL (below) before the next step.
5. **Never retry** a refused, failed or uncertain result. Re-preview instead.

### Commands

The dedicated Project is **"Beta MASTER Live Nguyễn Văn Cừ"**, an OPENING_NEW_CINEMA Project for Merchant NL2_LIVE_BETA (Beta Cinemas) **with procurement**. It never touches the NL2, NL3, NL4C2B or NL4D4B Projects. Below, `P` means `Project Beta MASTER Live Nguyễn Văn Cừ`.

| # | You type | Then confirm with | Expected result |
|---|---|---|---|
| 1 | `/solve Tạo project mở rạp Beta MASTER Live Nguyễn Văn Cừ cho Beta Cinemas, cần mua sắm, trên database test` | `/solve Xác nhận tạo <id>` | Project PLANNED; Steps instantiated; Steps 6–7 (PR) active |
| 2 | `/solve Bắt đầu P trên database test` | `/solve Xác nhận thực hiện <code>` | IN_PROGRESS, `PROJECT_STARTED` |
| 3 | `/solve Tạo phiên bản hợp đồng mới cho P trên database test` | `/solve Xác nhận thực hiện <code>` | revision 1, `METADATA_ONLY`, hash `metadata-only:<id>` |
| 4 | `/solve Legal đã phê duyệt hợp đồng của P trên database test, ghi chú: đồng ý` | `/solve Xác nhận thực hiện <code>` | LEGAL APPROVED; `approved_by` NULL; `recorded_by` = the operator |
| 5 | `/solve Kế toán đã phê duyệt hợp đồng của P trên database test` | same | ACCOUNTING APPROVED |
| 6 | `/solve Partner đã phê duyệt hợp đồng của P trên database test` | same | PARTNER APPROVED |
| 7 | `/solve Ghi nhận Purchase Request PR-MASTER-001 cho P trên database test` | `/solve Xác nhận ghi nhận <project code>` | PR v1 (NL4D4A path) |
| 8 | For each of Steps 1–8, in order: `/solve Bắt đầu bước N của P trên database test`, then `/solve Hoàn thành bước N của P trên database test`. A PENDING Step first needs `/solve Đánh dấu bước N của P là sẵn sàng trên database test`. | `/solve Xác nhận cập nhật <code>` after each | Steps COMPLETED. Steps 5 (Partner approval) and 8 (signing gate) are judged from the recorded evidence. Complete Step 8 **before** signing. |
| 9 | `/solve Ghi nhận hợp đồng của P đã ký trên database test` | `/solve Xác nhận thực hiện <code>` | `signed`, `signing_attestation = OPERATOR_ATTESTED_SIGNED` |
| 10 | `/solve Ghi nhận Purchase Order PO-MASTER-001 cho P trên database test` | same | PO v1 |
| 11 | `/solve Ghi nhận Payment Request PAY-MASTER-001 cho P trên database test` | same | Payment Request v1 |
| 12 | Steps 9–20, as in row 8 | `/solve Xác nhận cập nhật <code>` | COMPLETED |
| 13 | Steps 21 and 22: start them, then `/solve Hoàn thành bước 21 của P trên database test`. Its preview shows `gate_attestation: OPERATOR_ATTESTED`. Step 22 is final and is READY only when every other Step is done. | `/solve Xác nhận cập nhật <code>` | COMPLETED; the Step event carries `gate_attestation` |
| 14 | `/solve Hoàn tất P trên database test` | `/solve Xác nhận thực hiện <code>` | COMPLETED, `PROJECT_COMPLETED` |

### Independent read-back after each write

Read-only, on `coding_agent_merchant_test`. Ask Claude to run it, or use `psql`:

```sql
-- the Project and its newest events (one new event per confirmed write)
SELECT id, status, version FROM merchant_ops.projects WHERE title = 'Beta MASTER Live Nguyễn Văn Cừ';
SELECT event_type, entity_type, triggered_by, created_at FROM merchant_ops.project_events
 WHERE project_id = '<project id>' ORDER BY created_at DESC LIMIT 3;
-- evidence
SELECT revision_number, evidence_status, signed, signing_attestation, superseded_by
  FROM merchant_ops.document_revisions WHERE project_id = '<project id>';
SELECT approver_role, approval_status, approved_by, recorded_by, decided_at
  FROM merchant_ops.document_approvals a JOIN merchant_ops.document_revisions d
    ON d.id = a.document_revision_id WHERE d.project_id = '<project id>';
SELECT procurement_type, external_id, version FROM merchant_ops.procurement_records
 WHERE project_id = '<project id>';
-- exactly one new COMPLETED claim and ledger row per confirmed write, in the same transaction
SELECT c.claim_status, l.result->>'command' AS command, c.xmin = l.xmin AS same_tx
  FROM merchant_ops.merchant_execution_claims c JOIN merchant_ops.merchant_execution_ledger l
    USING (operation_key) ORDER BY c.created_at DESC LIMIT 3;
```

**Expected after each write:**
- exactly one new event, with `triggered_by` = the operator (fingerprint `210a4c001d41`);
- one new COMPLETED claim with `same_tx = true`;
- no change to any other Project.

### Final receipt reconciliation

From PostgreSQL alone:
- `attempt_evidence.recover_lifecycle_receipt(repo, operation)` for every lifecycle operation;
- `recover_purchase_request_receipts(repo, project_id)`;
- `recover_step_update_receipts(repo, step_id)` for the Steps.

Each must match the run-state receipt the hook recorded (status `RECONCILED`).

**Final checks:**
- the integrity hash changes only by this Project's rows;
- the 22 earlier claims are still COMPLETED;
- NL4C2B Step 1 is still IN_PROGRESS v2;
- PR-NL4D4B-001 still exists exactly once.

**Optional negative checks:**
- On a second disposable Project: a Partner rejection (`… đã từ chối …`), then a signing preview. Expected: BLOCKED `APPROVAL_REJECTED_BLOCKS_SIGNING`.
- A repeated `/solve Xác nhận thực hiện <same code>`. Expected: "no pending operation", nothing written.

## 13. Local MVP release readiness

**Startup:**
1. Start Docker Desktop (test DB container `coding-agent-rag-db`, port 5434).
2. Start psmux and an interactive `claude` with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (project settings).
3. Run `python .claude/system_test.py`.

**Environment validation:**
- `.env` holds the test credentials and `MERCHANT_OPERATOR_ID` (canonical UUID). Never print its value; use the fingerprint.
- Runtime credentials are not needed for the MVP.

**Migration status:**
- Load `.env` with dotenv (`migrate.py` does not), set `MERCHANT_TEST_DB_NAME` and `MERCHANT_TEST_USER`, then run `migrate.py --plan --database test` via `runpy`.
- Expect applied 1–10, nothing pending, and no checksum conflicts (line endings are pinned by `.gitattributes`).

**Operator identity:** `MERCHANT_OPERATOR_ID` in the untracked `.env`. A change makes every pending confirmation refuse (re-preview).

**Backup and restore (DEC-D4a):**
1. Pause writes.
2. `pg_dump` `coding_agent_merchant_test`.
3. Keep the dump with the migration list and the integrity hash.
4. Restore into an isolated database, then compare the hash.

With no managed files in use there is no file-store gap. Before managed uploads (NL4D5A3), adopt the two-pass procedure in the NL4D5A1b report §12.

**Safe shutdown:**
- let any running `/solve` finish;
- pending confirmations expire after 15 minutes and are never executed later;
- stop Claude Code, then Docker.

**Receipt recovery:**
- `attempt_evidence.recover_lifecycle_receipt(repo, operation)`;
- `recover_purchase_request_receipts(repo, project_id)`;
- `recover_step_update_receipts(repo, step_id)`.

Each reads PostgreSQL only.

**Stale teammates:**
- a changed `merchant-manager.md` changes the teammate fingerprint, so start a fresh session;
- a FAILED or UNCERTAIN task is never reused, so start a new `/solve`.

**PostgreSQL test isolation:**
- tests take an advisory lock (`0x4E4C3443`), and a second process exits;
- never run tests concurrently with live `/solve`;
- fixtures use `PYTEST_*` prefixes and clean up.

**Known limitations:** see §11.

**Readiness verdict:** **GO for user-driven live acceptance (§12) on the test database.** The implementation, migrations, automated end-to-end acceptance and full regression are complete. **Not yet "released":** live acceptance has not been performed (only the user can run and confirm it), and Existing-Document Media is blocked on an owner decision. The implementation is committed in CP12H.MASTER-FINAL. Runtime (production) stays NO-GO.

**Remaining blockers:** live acceptance (§12) by the user; the owner's review and commit of this working tree.

## 14. CP12H.MASTER-FINAL review (2026-11-12)

### Inventory audit

There are 22 implementation files, 18 test files, 3 documents (`CLAUDE.md`, `merchant-manager.md`, `solve.md`), migration 010 and this report. Every change belongs to the approved lifecycle.

**Confirmed:**
1. **Nothing old was weakened.** The NL4C Step Update and NL4D4A Purchase Request contracts and suites are unchanged in behaviour.
2. **No runtime write was added.** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; the new rules bind only the test target.
3. **The general `procurement update` is not a bypass.** A typed scope is refused at the intent gate. On the test database the preflight requires either the confirmed Purchase Request record or, for `--type PURCHASE_ORDER/PAYMENT_REQUEST`, the confirmed lifecycle record with the identical argv. Every path is create-only.
4. **No approver attribution.** The confirmed path never passes `acted_by` (the repository refuses `recorded_by` together with `acted_by`), and the receipt asserts `approved_by IS NULL`.
5. **No model-built identity or scope is trusted.** The operator, Project, Merchant and argv come only from the verified record and trusted configuration.

### Migration 010 audit

- **Recorder and approver are separate:** `recorded_by` versus `approved_by`, which may stay NULL.
- **Decision dates:** `decided_at` exists only on decisions (CHECK); APPROVED also sets `approved_at`.
- **Decisions are immutable:** UPDATE is refused by trigger; DELETE is not granted to the app role.
- **Signing is labelled:** `signing_attestation` is only `OPERATOR_ATTESTED_SIGNED`, only on signed rows.
- **A signed revision stays signed as recorded:** the extended 008 trigger.
- **Compatibility:** every 008/009 constraint is unchanged (dry run 9/9); FKs are untouched.
- **Checksum:** `6a7821a1…`, equal to the LF bytes; pinned by `.gitattributes` (`*.sql eol=lf`).
- **History:** 1–10 without gaps.
- **Business data:** none changed (equivalence reproduces `ada0d51d…`).
- **Not re-applied.**

### Defects found and fixed in this checkpoint

| Defect | Fix | Tests |
|---|---|---|
| "Start project X" read as Project creation | `_PROJECT_START`; creation only with an article, "new" or a type | `test_master_final_routing.py` (RED 3 → GREEN) |
| "Khởi động dự án" (start) read as "đóng" (close), i.e. completion | negative lookbehind | same |
| "… rồi hoàn tất …" not detected as a second operation | `_FURTHER_ACTION` extended | same |
| A write preview bound a *different* Merchant by a leading-name match ("Merchant Beta Khác Cinemas" → Beta Cinemas) | `resolve_merchant_phrase(exact=True)` for write previews | `test_reference_project_and_merchant_errors_never_yield_an_operation` |

### Coverage added

- **Ordinary Steps through the full confirmed pipeline:** start, complete, READY; reconciled receipts; PostgreSQL recovery; a missing-predecessor start refused.
- **Existing-document media:** fail-closed test (§11, item 3).
- **Failure cases:**
  - expired confirmation;
  - another session confirming;
  - ledger failure (rolled back, REVOKED);
  - duplicate PO reference;
  - ambiguous, missing and wrong-Merchant Project;
  - premature completion.

**Phase G checklist:** every item now has a test:
- wrong Project or Merchant; missing or ambiguous Project;
- operator substitution; handwritten scope; edited payload;
- replay; expiry; wrong session; stale basis;
- concurrency; crash before and after commit; ledger failure; recovery;
- duplicate reference;
- immutable decision; rejection blocks signing; supersede refusal;
- missing predecessor; premature completion.

### Supported workflows, end to end (PLANNED → COMPLETED)

| Workflow | Result |
|---|---|
| A. Opening New Cinema | PASS |
| B. Media Top-Up with procurement | PASS |
| C. Merchant Integration with activation | PASS |
| D. Existing-Document Media | PASS since CP12H.MASTER-FIX (§15) |

### GO / NO-GO

- **GO for user-driven live acceptance (§12) of workflows A–D** on the test database, in a fresh session (D: §15).
- **NO-GO:**
  - runtime Direct EXECUTE and runtime migration;
  - any claim of live acceptance before you run §12.

## 15. CP12H.MASTER-FIX — signed revision reuse across Projects (2026-11-12)

### Approved policy (Local Test MVP)

A MEDIA_TOP_UP_EXISTING_DOCUMENT Project may reuse an existing signed **CONTRACT** revision of **another Project of the same Merchant**, bound at its confirmed creation. You don't upload, approve or sign again.

### Data model

- **Existing relationship:** `projects.reused_document_revision_id`, with FK `projects_reused_document_revision_fk`. The source Project is reached through the revision's own `project_id`.
- **Migration 011 `reused_revision_binding`** (test DB only):
  - checksum `566cc50479047de360444a5317d701e062e08677582a9ecaaf0f43b6b04b66bc`, LF bytes (pinned);
  - trigger `projects_reused_revision_binding`. At insert, the bound revision must be a signed (`signed`, `signed_at`), non-superseded CONTRACT revision of **another Project of the same Merchant**. After insert, the binding can never be added, replaced or removed.
- **Migration evidence:** RED 7 failed / 3 passed → GREEN 10 passed; dry run 5/5; `--plan` showed exactly 011 pending.
- **Nothing is duplicated:** no revision, approval, signature or file is copied.

### Eligibility

One rule in `document_reuse.reuse_blocker`, used by the preview, the Project-create assessment, procurement and the lifecycle judge. The revision must:
- exist;
- belong to the same Merchant, in another Project;
- be a CONTRACT;
- be signed;
- not be superseded (conservative: a superseded signed revision is not reusable);
- have no REJECTED decision.

The rule keeps the source's own attestation (`OPERATOR_ATTESTED_SIGNED`, or `UNSPECIFIED_LEGACY_SIGNING` for legacy signing) and never upgrades it. A matching hash never authorizes reuse; only the bound id does.

### Exact selection and confirmation binding

- **Parsing.** The Project-create preview reads the reuse clause ("sử dụng hợp đồng đã ký [của Project A]", "using the signed contract from Project A", "dùng hợp đồng hiện có"), the payment period ("kỳ thanh toán 3", "payment period 3") and an optional revision UUID. It removes them before names are extracted. "Project media" and "existing-document media" are media types.
- **Selection.**
  - exactly one eligible candidate → proposed;
  - several → asks, with candidates;
  - none → names the missing prerequisite.
- **What the preview shows** (`reused_document`): source Project, revision id, type, number, signed status and attestation, plus the relationship.
- **Binding.** The exact revision id is in the operation's argv (`--reused-document-revision-id`). The revision's full state (signed, superseded, decisions, attestation) is in the basis. It is re-verified in the preflight and again inside the create transaction (FOR SHARE), so any change refuses the operation before spend.

### Procurement compatibility

A PO or Payment Request accepts:
- **(A)** the Project's own active revision, with the rules unchanged; or
- **(B)** only when the Project has no active revision of its own: the revision bound on the committed Project row, locked FOR SHARE in the write transaction, and still eligible.

A revision named in a request is never used. Exact references, create-only behaviour, Merchant-scoped uniqueness and the other prerequisites are unchanged.

### Tests

| Suite | Result |
|---|---|
| `test_master_fix_migration_011_postgres.py` (new) | 10 tests |
| `test_master_fix_reuse_postgres.py` (new) | 14 tests |

**`test_master_fix_reuse_postgres.py` covers:**
- **Full workflow D:** source revision → three approvals → operator-attested signing → confirmed create binding the revision → start → attested Step 1 → PO and Payment Request on the reused contract → attested final Step → completion. Receipts are rebuilt from PostgreSQL; the source revision and decisions are byte-identical before and after.
- **Selection:** one, several (then by Project or by id) and no eligible revision; Vietnamese and English requests.
- **Ineligible sources:** rejected, superseded, unsigned, foreign Merchant.
- **Authority and failure:**
  - a handwritten or forged binding (not spent);
  - a source change after the preview (refused before spend; replay finds nothing);
  - concurrent creates of one operation (exactly one link);
  - a PO ledger failure (rolled back, REVOKED);
  - a Project with its own signed revision keeps the existing rules.

**Changed on purpose:** the earlier existing-document fail-closed test now asserts the PO is valid on the bound revision; the migration lists include 011.

### Full regression

| Check | Result |
|---|---|
| Full pytest | **4821 passed, 21 skipped, 1 xfailed, 0 failed** (97 subtests), 7 min 27 s. Previously 4797; +24 new tests. |
| Suites outside `tests/merchant` and agent-definition tests, re-run after the docs changed | 856 and 96 passed |
| `system_test.py` | ALL TESTS PASSED |
| Hook compile and import | OK; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean |

### Database integrity (read-only, 15/15 PASS)

| Item | Value |
|---|---|
| Identity | `coding_agent_merchant_test` / `merchant_test` |
| Migrations | 1–11, every checksum equal to its file; nothing pending |
| **New post-011 baseline** | **`c79ecc6728fac8fcca237b7e036544728e07fcd6fb0e2d8e1efa3e920dd7c201`** |
| Equivalence: excluding only migration row 11 | `fa9cba01…`, reproduced exactly (no business row changed) |
| Accepted records | 5 accepted Projects, NL4C2B Step 1 (IN_PROGRESS v2) and PR-NL4D4B-001 unchanged |
| Claims and ledger | 22 claims COMPLETED; no orphan ledger row |
| Residue | no fixtures, no reused bindings, no revisions, approvals or files; no active pending confirmation |
| Runtime | not touched |

### Remaining limitations

- A superseded signed revision is not reusable (a conservative rule; an owner decision could relax it).
- Only CONTRACT revisions are reusable.
- The binding is fixed at creation, so changing it means a new Project.
- The DB trigger enforces Merchant, signed, CONTRACT and current; the "no REJECTED decision" rule is enforced in the application (preview, preflight and transaction).

### GO / NO-GO

- **GO for user-driven live acceptance of workflows A–D** (§12; for D, create the destination with "Tạo Project media <tên> cho <Merchant> kỳ thanh toán <n>, sử dụng hợp đồng đã ký của Project <nguồn> trên database test" after signing the source contract).
- **NO-GO:** runtime Direct EXECUTE and runtime migration.

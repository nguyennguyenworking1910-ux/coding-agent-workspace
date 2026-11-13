# CP12H.MASTER — Live Acceptance Runbook (workflows A–D, test database)

> **Use §10 (Risk-Based Live Smoke Acceptance, added by CP12H.MASTER-LIVE-SMOKE) for Local MVP acceptance.** It needs 40 core confirmed writes instead of about 211. §4–§8 stay as the optional exhaustive reference. One correction to them: a contract is signed only after its signing-gate Step is COMPLETED. Since CP12H.MASTER-FIX-F1 the system enforces this. An early signing preview is BLOCKED with `SIGNING_GATE_STEP_NOT_COMPLETED` (see §10.1, finding F1, FIXED).

Prepared 2026-11-13 by CP12H.MASTER-LIVE-PREFLIGHT. This checkpoint was **read-only**: no code changed, no Project created, no Merchant write, no live `/solve`, no commit. It supersedes the runbook in `cp12h_master_local_mvp_completion.md` §12, because the new one covers workflows A–D and fixes the wording findings in §4.0.

## 1. Expected Git baseline

| Item | Value |
|---|---|
| Branch | `feat/cp7-9-merchant-reliability` |
| HEAD | `e209d5da591b225032d719314cf8ec3f86138233` (`feat(merchant): support signed revision reuse across projects`) |
| Working tree | clean (this runbook is the only new, untracked file) |
| Regression at HEAD | re-run 2026-11-13: **4821 passed, 21 skipped, 1 xfailed, 0 failed**; `system_test.py` ALL PASSED; `git diff --check` clean |
| Runtime Direct EXECUTE | `RUNTIME_DIRECT_EXECUTE_ENABLED = False` (`.claude/hooks/merchant_direct_handoff.py:69`) |

Before starting, `git rev-parse HEAD` must print the hash above. If it doesn't, stop and re-run this preflight.

## 2. Database integrity results (2026-11-13, read-only, 20/20 PASS)

The check used a `read_only=True` connection (`transaction_read_only = on`) with role `test`. It ran no cleanup and no repair.

| # | Check | Result |
|---|---|---|
| 1 | Identity | `coding_agent_merchant_test` / `merchant_test`, read-only transaction |
| 2 | Migrations 1–11 applied in order (`executed_at` ascending) | PASS |
| 3 | Every applied checksum equals its committed file | PASS (0 mismatches) |
| 4 | Pending migrations | none (11 files, 11 applied) |
| 5 | Full integrity hash | **`c79ecc6728fac8fcca237b7e036544728e07fcd6fb0e2d8e1efa3e920dd7c201`**, equal to the accepted post-011 baseline |
| 5b | The same hash excluding only migration row 11 | `fa9cba01…`, equal to the post-010 baseline (no business row changed by 011) |
| 6 | Leftover fixtures | 0 `PYTEST%` Merchants or Projects; 0 `pytest:` claims or ledger rows; 0 revisions, approvals, files or reuse bindings |
| 7 | Claims and ledger | 22 claims, all `COMPLETED`; 6 ledger rows, 0 orphans; 0 non-terminal claims |
| 8 | Pending confirmations | none active (`.claude/runtime/*.pending_*.json`) |
| 9 | Accepted Projects | 5, unchanged (below) |
| 10 | `PR-NL4D4B-001` | exactly once |
| 11 | NL4C2B Step 1 | `IN_PROGRESS`, version 2 |
| 12 | Runtime Direct EXECUTE | `False` |
| — | Other sessions on the test DB | none (`pg_stat_activity`) |
| — | Trusted operator | `MERCHANT_OPERATOR_ID` set; fingerprint `210a4c001d41` (the value is never printed) |

**Row counts at baseline:** merchants 2, projects 5, project_steps 114, project_step_dependencies 114, project_events 11, procurement_records 1, claims 22, ledger 6, document_* 0, integration_identifiers 0, merchant_contacts 0, alert_deliveries 0, schema_migrations 11, workflow_templates 4 (64 steps, 68 dependencies).

**Accepted Projects (do not touch):**

| Project | Type | Status / version | Merchant |
|---|---|---|---|
| Manual Integration Test 20260915110525 | INTEGRATION_NEW_MERCHANT | IN_PROGRESS v2 | TEST_CLI_20260915110525 (ONBOARDING) |
| Beta Nguyễn Văn Cừ | OPENING_NEW_CINEMA | PLANNED v1 | NL2_LIVE_BETA (Beta Cinemas, ACTIVE) |
| Beta NL3 Confirmation Test | OPENING_NEW_CINEMA | PLANNED v1 | NL2_LIVE_BETA |
| Beta NL4C2B Step Acceptance (`8dd4c68d…`) | OPENING_NEW_CINEMA | PLANNED v1 | NL2_LIVE_BETA |
| Beta NL4D4B PR Acceptance (`6dfa1a96…`) | OPENING_NEW_CINEMA | PLANNED v1 | NL2_LIVE_BETA |

**Hash method.** For each `merchant_ops` base table: `SELECT count(*) AS n, coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '') AS h FROM merchant_ops.<table> x`. Then take sha256 of `json.dumps({table: {n, h}}, sort_keys=True)`.

## 3. Migration 011 checksum

| Item | Value |
|---|---|
| File | `.claude/clients/merchant/migrations/011_reused_revision_binding.sql` |
| Applied checksum (`schema_migrations` row 11) | `566cc50479047de360444a5317d701e062e08677582a9ecaaf0f43b6b04b66bc` |
| Checksum of the committed file (`migrate._calculate_checksum`) | identical |
| Line endings | LF, pinned by `.gitattributes` (`1ba8348`) |
| Runtime database | not migrated, not connected |

## 4. Workflow commands

### 4.0 Wording rules (found by dry-running the read-only previews)

The read-only preview functions were called directly as library code. That path has no hook and creates no pending record, so the dry runs authorized nothing.

1. **Use no hyphens in titles.** `LIVE-A` is normalized to `LIVE A`, and a later reference to the hyphenated name would not match. The titles below avoid hyphens.
2. **New-document media needs "gia hạn hợp đồng" or "new document".** "hợp đồng mới" is **not** recognized, and the preview asks which media template to use. (NL gap. Not fixed here; this checkpoint is read-only.)
3. **An integration Project needs an explicit procurement answer** ("không cần mua sắm"), otherwise the preview asks.
4. **INTEGRATION_NEW_MERCHANT requires an ONBOARDING Merchant.** Beta Cinemas is ACTIVE (`MERCHANT_PRECONDITION`, BLOCKED). Workflow C therefore first creates a disposable Merchant. `merchant create` defaults to ONBOARDING. Never use `TEST_CLI_20260915110525`: it is accepted data with its own Project.
5. **Write Step requests with the Merchant name:** `… bước N của Project <title> của Merchant <merchant> trên database test`.
6. **Keep `trên database test`** in every request.

### 4.1 Disposable acceptance identities

| Workflow | Project title | Merchant | Template | Steps |
|---|---|---|---|---|
| A | `Beta Live A Lê Lợi` | Beta Cinemas (`NL2_LIVE_BETA`) | OPENING_NEW_CINEMA_STANDARD, **no procurement** (Steps 6–7 SKIPPED) | 22 (20 active) |
| B | `Beta Live B Q4` | Beta Cinemas | MEDIA_TOP_UP_NEW_DOCUMENT (procurement fixed true), period 1 | 12 |
| C | `Master Live C Integration` | **new** `MASTERLIVEC1` / `Master Live C Pay` | INTEGRATION_NEW_MERCHANT_STANDARD, no procurement (Steps 9–10 SKIPPED) | 26 (24 active) |
| D | `Beta Live D Q4` | Beta Cinemas | MEDIA_TOP_UP_EXISTING_DOCUMENT, period 2, **reuses A's signed contract** | 4 |

**Required operations per workflow.** These come from the templates; nothing is invented.

| Operation | A | B | C | D |
|---|---|---|---|---|
| Merchant create | – | – | ✔ | – |
| Project create | ✔ | ✔ | ✔ | ✔ (binds A's revision) |
| Start Project | ✔ | ✔ | ✔ | ✔ |
| Metadata-only revision + LEGAL/ACCOUNTING/PARTNER APPROVED | ✔ | ✔ | ✔ | – (reused) |
| Purchase Request | – (no procurement) | ✔ (Steps 6–7 mandatory) | – | – |
| Operator-attested signing | ✔ | ✔ | ✔ | – (reused) |
| Purchase Order, Payment Request (template Steps) | ✔ (10, 11) | ✔ (10, 11) | ✔ (13, 14) | ✔ (2, 3) |
| Attested evaluator-less gates | 21, 22 | 12 | 3, 24, 25 (activation), 26 | 1, 4 |
| Gates judged from evidence | 5, 8 | 5, 8 | 8, 11 | – |
| Complete Project | ✔ | ✔ | ✔ | ✔ |

**Recommended order: A → D → B → C.** D needs A's signed contract, so A must be at least signed first. One operation at a time; no parallel `/solve` runs.

**Volume warning.** Every non-root Step needs three confirmed writes (ready → start → complete), and a root Step needs two. Each write is a preview `/solve` plus a confirmation `/solve`. Approximate confirmed writes: **A ≈ 69, B ≈ 45, C ≈ 81, D ≈ 16** (≈ 211 in total, ≈ 420 `/solve` runs). D plus A is the full reuse path; B and C add the PR path and Merchant activation.

### 4.2 Confirmation syntax

| Operation kind | Preview request starts with | Confirm with (type exactly; the id comes from the preview) | Cancel |
|---|---|---|---|
| Merchant create | – (typed scope only) | `/solve --confirm --merchant-target test --merchant-scope ["merchant","create","--code","MASTERLIVEC1","--name","Master Live C Pay"] Create test merchant MASTERLIVEC1` | – |
| Project create | `/solve Tạo project …` | `/solve Xác nhận tạo <first 8 of project_id>` | `/solve Hủy tạo <id>` |
| Lifecycle (start/complete Project, revision, approval, signing, PO, Payment Request) | `/solve Bắt đầu Project …`, `/solve Tạo phiên bản …`, `/solve Legal đã phê duyệt …`, `/solve Ghi nhận …` | `/solve Xác nhận thực hiện <first 8 of operation_id>` | `/solve Hủy thực hiện <id>` |
| Step Update (ready, start, complete, attested gate) | `/solve Đánh dấu / Bắt đầu / Hoàn thành bước N …` | `/solve Xác nhận cập nhật <first 8 of step_id>` | `/solve Hủy cập nhật <id>` |
| Purchase Request | `/solve Ghi nhận Purchase Request …` | `/solve Xác nhận ghi nhận <first 8 of project_id>` | `/solve Hủy ghi nhận <id>` |

- **Confirming a Project create.** The preview's `confirmation_command` is the equivalent typed `--merchant-scope` with `--project-id` and `--expected-basis`. Either form works. Prefer `Xác nhận tạo`, which the earlier live acceptances used.
- Every pending record is session-bound, single use, and expires in 15 minutes.
- A confirmation of one kind never confirms another.
- A bare phrase without `/solve` is not a confirmation.

### 4.3 Step procedure (used by every workflow)

`S` = `của Project <title> của Merchant <merchant name> trên database test`

| State of Step N | Request | Then |
|---|---|---|
| PENDING | `/solve Đánh dấu bước N của Project <title> của Merchant <merchant> là sẵn sàng trên database test` | `/solve Xác nhận cập nhật <id>` |
| READY | `/solve Bắt đầu bước N S` | same |
| IN_PROGRESS | `/solve Hoàn thành bước N S` | same |

- **Root Steps** (no predecessor) are READY at creation: A 1; B 1 and 6; C 1 and 2; D 1.
- **Ordering.** A Step is ready only when its direct predecessors are COMPLETED or SKIPPED. Otherwise the preview is BLOCKED with `UNMET_DEPENDENCIES` and nothing is written.
- **Attested gates.** On a gate with no evaluator, the *completion* preview shows `gate_attestation: OPERATOR_ATTESTED`. Starting it needs no attestation.
- **The final Step** (highest number) is READY only when every other Step is COMPLETED or SKIPPED.

### 4.4 Workflow A — Opening New Cinema (`Beta Live A Lê Lợi`)

`P` = `Project Beta Live A Lê Lợi trên database test`; `S` = `của Project Beta Live A Lê Lợi của Merchant Beta Cinemas trên database test`.

| # | You type | Confirm | Expected |
|---|---|---|---|
| A1 | `/solve Tạo project mở rạp Beta Live A Lê Lợi cho Beta Cinemas, không cần mua sắm, trên database test` | `Xác nhận tạo` | Preview: OPENING_NEW_CINEMA_STANDARD, `NL2_LIVE_BETA`, `--no-requires-procurement` (dry-run READY). Project PLANNED v1; 22 Steps; 1 READY; 6, 7 SKIPPED |
| A2 | `/solve Bắt đầu P` | `Xác nhận thực hiện` | IN_PROGRESS v2, `PROJECT_STARTED` |
| A3 | `/solve Tạo phiên bản hợp đồng mới cho P` | same | revision 1 CONTRACT, `METADATA_ONLY`, hash `metadata-only:<id>` |
| A4 | `/solve Legal đã phê duyệt hợp đồng của P, ghi chú: đồng ý` (expands to `… Beta Live A Lê Lợi trên database test, ghi chú: đồng ý`; the note is optional and must come last) | same | LEGAL APPROVED, `approved_by` NULL, `recorded_by` = operator |
| A5 | `/solve Kế toán đã phê duyệt hợp đồng của P` | same | ACCOUNTING APPROVED |
| A6 | `/solve Partner đã phê duyệt hợp đồng của P` | same | PARTNER APPROVED |
| A7 | Steps **1, 2, 3, 4, 5, 8** via §4.3 | `Xác nhận cập nhật` | COMPLETED. 5 (Partner gate) and 8 (signing gate) are judged from evidence. **Complete 8 before signing** (the gate requires an unsigned revision) |
| A8 | `/solve Ghi nhận hợp đồng của P đã ký` | `Xác nhận thực hiện` | `signed = true`, `signing_attestation = OPERATOR_ATTESTED_SIGNED` |
| — | *Now run workflow D (§4.7), then continue here.* | | |
| A9 | Step **9** (Sign document) | `Xác nhận cập nhật` | COMPLETED |
| A10 | `/solve Ghi nhận Purchase Order PO-LIVEA-001 cho P` | `Xác nhận thực hiện` | PURCHASE_ORDER `PO-LIVEA-001` v1 |
| A11 | Step **10** | `Xác nhận cập nhật` | COMPLETED |
| A12 | `/solve Ghi nhận Payment Request PAY-LIVEA-001 cho P` | `Xác nhận thực hiện` | PAYMENT_REQUEST `PAY-LIVEA-001` v1 |
| A13 | Steps **11, 12–20** | `Xác nhận cập nhật` | COMPLETED |
| A14 | Step **21** (Complete UAT acceptance): start, then complete | same | the completion preview shows `OPERATOR_ATTESTED`; the STEP_COMPLETED event carries `gate_attestation` |
| A15 | Step **22** (Complete project, final): ready, start, complete | same | attested; READY only after all others are done |
| A16 | `/solve Hoàn tất P` | `Xác nhận thực hiện` | Project COMPLETED, `PROJECT_COMPLETED` (completing Step 22 does not do this) |

### 4.5 Workflow B — Media Top-Up, new document (`Beta Live B Q4`)

`P` = `Project Beta Live B Q4 trên database test`; `S` = `của Project Beta Live B Q4 của Merchant Beta Cinemas trên database test`.

| # | You type | Confirm | Expected |
|---|---|---|---|
| B1 | `/solve Tạo Project media Beta Live B Q4 cho Beta Cinemas kỳ thanh toán 1, gia hạn hợp đồng, trên database test` | `Xác nhận tạo` | Preview: MEDIA_TOP_UP_NEW_DOCUMENT, `--requires-procurement`, `--payment-period-number 1` (dry-run READY). 12 Steps; 1 and 6 READY |
| B2 | `/solve Bắt đầu P` | `Xác nhận thực hiện` | IN_PROGRESS |
| B3 | revision, then Legal, Kế toán, Partner approvals (as A3–A6, with B's `P`) | same | revision 1 METADATA_ONLY; 3 × APPROVED |
| B4 | `/solve Ghi nhận Purchase Request PR-LIVEB-001 cho P` | **`/solve Xác nhận ghi nhận <first 8 of project_id>`** | PURCHASE_REQUEST `PR-LIVEB-001` v1 (NL4D4A path) |
| B5 | Steps **1, 2, 3, 4, 5, 6, 7, 8** | `Xác nhận cập nhật` | COMPLETED (5 and 8 judged from evidence; 8 before signing) |
| B6 | `/solve Ghi nhận hợp đồng của P đã ký` | `Xác nhận thực hiện` | OPERATOR_ATTESTED_SIGNED |
| B7 | Step 9; `Ghi nhận Purchase Order PO-LIVEB-001 cho P`; Step 10; `Ghi nhận Payment Request PAY-LIVEB-001 cho P`; Step 11 | as for A9–A13 | PO and Payment Request v1; Steps COMPLETED |
| B8 | Step **12** (Close payment period, final): ready, start, complete | `Xác nhận cập nhật` | attested |
| B9 | `/solve Hoàn tất P` | `Xác nhận thực hiện` | COMPLETED; procurement = PR, PO, Payment Request |

### 4.6 Workflow C — Merchant Integration (`Master Live C Integration`)

`P` = `Project Master Live C Integration trên database test`; `S` = `của Project Master Live C Integration của Merchant Master Live C Pay trên database test`.

| # | You type | Confirm | Expected |
|---|---|---|---|
| C0 | `/solve --confirm --merchant-target test --merchant-scope ["merchant","create","--code","MASTERLIVEC1","--name","Master Live C Pay"] Create test merchant MASTERLIVEC1` | (it is the confirmation) | Merchant `MASTERLIVEC1`, ONBOARDING, v1. The run reports a verified Create receipt |
| C1 | `/solve Tạo project tích hợp merchant Master Live C Integration cho Master Live C Pay, không cần mua sắm, trên database test` | `Xác nhận tạo` | Preview: INTEGRATION_NEW_MERCHANT_STANDARD, `MASTERLIVEC1`, no procurement. **Not dry-run** (the Merchant doesn't exist yet). Check the title and Merchant code before confirming. 26 Steps; 1, 2 READY; 9, 10 SKIPPED |
| C2 | `/solve Bắt đầu P` | `Xác nhận thực hiện` | IN_PROGRESS |
| C3 | Steps **1, 2**, then Step **3** (Validate Master Merchant identity): start, then complete | `Xác nhận cập nhật` | 3 is attested |
| C4 | revision, then the three approvals (as A3–A6, with C's `P`) | `Xác nhận thực hiện` | METADATA_ONLY; 3 × APPROVED |
| C5 | Steps **4, 5, 6, 7, 8, 11** | `Xác nhận cập nhật` | COMPLETED (8 and 11 judged from evidence; 11 before signing) |
| C6 | `/solve Ghi nhận hợp đồng của P đã ký` | `Xác nhận thực hiện` | OPERATOR_ATTESTED_SIGNED |
| C7 | Step 12; `PO-LIVEC-001`; Step 13; `PAY-LIVEC-001`; Step 14; Steps **15–23** | as A9–A13 | COMPLETED |
| C8 | Step **24** (Complete UAT acceptance) | `Xác nhận cập nhật` | attested |
| C9 | Step **25** (Activate Merchant) | same | The preview shows `MERCHANT_ACTIVATION_IN_SAME_TRANSACTION`. After it, `MASTERLIVEC1` is **ACTIVE** in the same transaction as the Step |
| C10 | Step **26** (final) | same | attested |
| C11 | `/solve Hoàn tất P` | `Xác nhận thực hiện` | COMPLETED |

### 4.7 Workflow D — Existing-Document Media (`Beta Live D Q4`), after A8

`P` = `Project Beta Live D Q4 trên database test`; `S` = `của Project Beta Live D Q4 của Merchant Beta Cinemas trên database test`.

| # | You type | Confirm | Expected |
|---|---|---|---|
| D0 | Record A's revision first (read-back §5, query R2): its `id`, `signed = true`, `superseded_by` NULL, attestation, and its 3 approvals | – | the source baseline |
| D1 | `/solve Tạo Project media Beta Live D Q4 cho Beta Cinemas kỳ thanh toán 2, sử dụng hợp đồng đã ký của Project Beta Live A Lê Lợi trên database test` | `Xác nhận tạo` | Preview `reused_document` shows source Project `Beta Live A Lê Lợi`, A's revision id, CONTRACT, revision 1, signed, `OPERATOR_ATTESTED_SIGNED`. The argv carries `--reused-document-revision-id <A rev id>`. *Dry run before A is signed: NEEDS_CLARIFICATION "Sign the contract first", as designed.* After confirming: `projects.reused_document_revision_id` = A's revision id; 4 Steps; Step 1 READY |
| D2 | `/solve Bắt đầu P` | `Xác nhận thực hiện` | IN_PROGRESS |
| D3 | Step **1** (Validate existing signed document): start, then complete | `Xác nhận cập nhật` | attested |
| D4 | Step 2: ready, start; `/solve Ghi nhận Purchase Order PO-LIVED-001 cho P` (`Xác nhận thực hiện`); complete Step 2 | | PO v1, accepted on the **bound** revision (D has no revision of its own) |
| D5 | Step 3: ready, start; `/solve Ghi nhận Payment Request PAY-LIVED-001 cho P`; complete Step 3 | | Payment Request v1 |
| D6 | Step **4** (Close payment period, final): ready, start, complete | `Xác nhận cập nhật` | attested |
| D7 | `/solve Hoàn tất P` | `Xác nhận thực hiện` | COMPLETED |
| D8 | Re-run query R2 for A's revision | – | **byte-identical** to D0: no new revision, approval or signature anywhere for D |

**Optional negative checks (D).** Each is a preview only; none writes anything.
- `/solve Tạo Project media Beta Live D2 cho Beta Cinemas kỳ thanh toán 3, sử dụng hợp đồng đã ký hiện có trên database test` → after A is signed, exactly one candidate is proposed. Don't confirm it, or cancel it.
- A repeated `/solve Xác nhận tạo <same id>` → "no pending operation", nothing written.

## 5. Expected database changes and read-back after each write

### Expected change per confirmed write

| Operation | Rows that change |
|---|---|
| Merchant create | +1 `merchants` (ONBOARDING); +1 COMPLETED claim (verified Create receipt) |
| Project create | +1 `projects` (PLANNED v1), +N `project_steps` and their dependencies, +1 `PROJECT_CREATED` event, +1 COMPLETED claim. D only: `reused_document_revision_id` set; **no** revision or approval row |
| Start / complete Project | `projects.status` and `version` +1; +1 `PROJECT_STARTED` / `PROJECT_COMPLETED` event |
| Revision | +1 `document_revisions` (METADATA_ONLY, `metadata-only:<id>`) |
| Approval | +1 `document_approvals` (APPROVED, `approved_by` NULL, `recorded_by` = operator, `decided_at` set) |
| Signing | that revision: `signed = true`, `signed_at`, `signing_attestation = OPERATOR_ATTESTED_SIGNED` |
| PR / PO / Payment Request | +1 `procurement_records` (exact reference, v1) |
| Step Update | that Step's `status` and `version` +1; +1 STEP event (attested gates: `new_values.gate_attestation = OPERATOR_ATTESTED`). C Step 25 also sets the Merchant to ACTIVE |
| Every lifecycle, Step or PR write | +1 event (`triggered_by` = operator), +1 COMPLETED claim and +1 ledger row in the **same transaction** |

### Read-back (read-only, `coding_agent_merchant_test`; ask Claude to run it, or use `psql`)

```sql
-- R1 Project and its newest events
SELECT id, status, version, reused_document_revision_id FROM merchant_ops.projects WHERE title = '<title>';
SELECT event_type, entity_type, triggered_by, created_at FROM merchant_ops.project_events
 WHERE project_id = '<project id>' ORDER BY created_at DESC LIMIT 3;
-- R2 evidence (for D's source, use A's project id)
SELECT id, revision_number, evidence_status, signed, signed_at, signing_attestation, superseded_by
  FROM merchant_ops.document_revisions WHERE project_id = '<project id>';
SELECT approver_role, approval_status, approved_by, recorded_by, decided_at
  FROM merchant_ops.document_approvals a JOIN merchant_ops.document_revisions d ON d.id = a.document_revision_id
 WHERE d.project_id = '<project id>';
-- R3 procurement and Steps
SELECT procurement_type, external_id, version FROM merchant_ops.procurement_records WHERE project_id = '<project id>';
SELECT sequence_number, status, version FROM merchant_ops.project_steps WHERE project_id = '<project id>' ORDER BY 1;
-- R4 newest claims: one new COMPLETED claim per write; a ledger row shares its transaction
SELECT c.claim_status, l.result->>'command' AS command, c.xmin = l.xmin AS same_tx
  FROM merchant_ops.merchant_execution_claims c LEFT JOIN merchant_ops.merchant_execution_ledger l USING (operation_key)
 ORDER BY c.created_at DESC LIMIT 3;
-- R5 Merchant (C)
SELECT code, account_status, version FROM merchant_ops.merchants WHERE code = 'MASTERLIVEC1';
```

**Pass criteria after each write:**
- exactly the change in the table above;
- one new event with `triggered_by` = operator (fingerprint `210a4c001d41`);
- one new COMPLETED claim (`same_tx = true` where a ledger row exists);
- no change to any other Project, in particular the 5 accepted ones and A's revision during D.

## 6. Execution boundaries (verified 2026-11-13)

| Boundary | State |
|---|---|
| Trusted operator | `MERCHANT_OPERATOR_ID` in the untracked `.env`, fingerprint `210a4c001d41`. A change refuses every pending confirmation (re-preview) |
| Test-only gates | `TEST_MODE_COMMANDS` = document approve, document revision-create, document sign, merchant create, procurement update, project create, project update, step update. Typed lifecycle, Step and procurement scopes are refused; only confirmed pending records reach them |
| Runtime | `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; a runtime target is refused with `RUNTIME_EXECUTION_DISABLED`; the runtime DB is unmigrated (schema 1–7) |
| Teammate freshness | `merchant-manager.md`, `solve.md` and hooks last changed in `e209d5d`. **Start a fresh Claude Code session in psmux**; never reuse a FAILED or UNCERTAIN teammate |
| Agent Teams | `.claude/settings.json`: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, `teammateMode: tmux` |
| Concurrency | no other DB session and no pytest process at check time. **Run no PostgreSQL tests during the session** (advisory lock `0x4E4C3443`) |
| Exactly once | one confirmation spends one pending record into one attempt. Success, mismatch, failure, expiry and uncertainty all consume it |
| No automatic retry | failed or uncertain executions are never retried by the system; you re-preview |

## 7. Failure and recovery

| Situation | What it means | Do |
|---|---|---|
| Preview BLOCKED / NEEDS_CLARIFICATION | nothing pending, nothing written | fix the wording (§4.0) or the prerequisite; preview again |
| "No pending operation" on confirm | expired (15 min), already spent, or another session's record | preview again; never re-type an old scope |
| Refused before spend (`LIFECYCLE_BASIS_CHANGED`, `LIFECYCLE_CONFIRMATION_MISMATCH`, operator reason, `UNMET_DEPENDENCIES`) | nothing spent, nothing written | read back R1–R4 to confirm; re-preview |
| FAILED (fenced, REVOKED claim) | the attempt is consumed; the mutation did not commit | read back (expect a REVOKED claim and no business change); re-preview for a fresh attempt |
| **UNCERTAIN** | the outcome is unknown | **stop.** Do not retry. Read back R1–R4. Recover the receipt from PostgreSQL: `attempt_evidence.recover_lifecycle_receipt(repo, operation)`, `recover_step_update_receipts(repo, step_id)`, `recover_purchase_request_receipts(repo, project_id)`. Continue only once the evidence shows SUCCEEDED (move on) or no committed write (re-preview) |
| Teammate pane / backend gate FAILED | the task cannot deliver or be reused | stop it; start a new `/solve` (fresh session if the docs changed) |
| Wrong Project or Merchant created | no delete path exists | leave it, record it in the acceptance report, use a new title; any cleanup is a separate owner decision |
| Integrity drift outside the acceptance Projects | unexpected | stop; re-run §2; report |

## 8. Final acceptance checklist

- [ ] HEAD is `e209d5d…`, the tree is clean, and the session is fresh in psmux. No pytest is running.
- [ ] Pre-run §2 re-run: hash `c79ecc67…`, 22 claims, nothing pending.
- [ ] A: COMPLETED; 20 Steps COMPLETED, 6–7 SKIPPED; revision signed `OPERATOR_ATTESTED_SIGNED`; 3 APPROVED; PO and Payment Request v1.
- [ ] D: COMPLETED; `reused_document_revision_id` = A's revision; PO and Payment Request on the bound revision; **0** revisions or approvals of its own; A's revision and approvals byte-identical before and after.
- [ ] B: COMPLETED; PR, PO and Payment Request v1; 12 Steps COMPLETED.
- [ ] C: `MASTERLIVEC1` ACTIVE (set in Step 25's transaction); Project COMPLETED; 24 Steps COMPLETED, 9–10 SKIPPED.
- [ ] Every write: one event (`triggered_by` = operator), one COMPLETED claim, `same_tx` true where a ledger row exists.
- [ ] Receipts: each run-state receipt is `RECONCILED`, and the PostgreSQL recovery functions reproduce it.
- [ ] Claims: 22 + (number of confirmed writes), all COMPLETED except attempts reported FAILED (REVOKED); no orphan ledger rows.
- [ ] Unchanged: the 5 accepted Projects (status and version as in §2), NL4C2B Step 1 IN_PROGRESS v2, `PR-NL4D4B-001` exactly once, `TEST_CLI_20260915110525` ONBOARDING.
- [ ] Integrity: excluding the rows of the 4 acceptance Projects, Merchant `MASTERLIVEC1` and their claims, ledger rows and events, the hash reproduces `c79ecc67…`.
- [ ] No active pending confirmation at the end; `RUNTIME_DIRECT_EXECUTE_ENABLED` still `False`.
- [ ] Results recorded in a live-acceptance report (`cp12h_master_live_acceptance.md`).

## 9. GO / NO-GO

- **GO for user-driven live acceptance of workflows A–D on `coding_agent_merchant_test`.** Conditions: a fresh psmux session, the wording in §4, order A → D → B → C, one operation at a time, a read-back after every write.
- **Caveats, not blockers:**
  - C1 could not be dry-run, because its Merchant is created in C0.
  - The "hợp đồng mới" wording gap (§4.0 item 2) is a known NL limitation. Use "gia hạn hợp đồng".
  - The volume is about 211 confirmed writes. If that is too much for one session, A + D is the minimum that proves the reuse path end to end.
- **NO-GO:**
  - runtime Direct EXECUTE and the runtime migration;
  - any claim of live acceptance before these steps are actually run and read back.

## 10. Risk-Based Live Smoke Acceptance (CP12H.MASTER-LIVE-SMOKE, 2026-11-13)

Planning only. Nothing was executed, nothing changed in any engine, migration or authorization path, and nothing was committed.

**Baseline:**
- HEAD `e209d5da591b225032d719314cf8ec3f86138233`.
- Pre-live hash `c79ecc6728fac8fcca237b7e036544728e07fcd6fb0e2d8e1efa3e920dd7c201` (`cp12h_master_local_mvp_completion.md` §15).
- Preflight 20/20 PASS (§2).
- Regression 4821 / 21 / 1 / 0.

### 10.1 Findings from the source review

| # | Finding | Effect on the plan |
|---|---|---|
| F1 — **FIXED** (CP12H.MASTER-FIX-F1) | `document sign` checked the approvals (and the PR, if required) but **not** the signing-gate Step. That Step refuses a signed revision (`gates.py:297`, `DOCUMENT_ALREADY_SIGNED`), and a signed revision can't be superseded (DEC-D4e). Signing first therefore left the Project permanently unable to complete. **Fix:** the signing judge (`lifecycle_operation.judge`, used by the preview, the preflight and the in-transaction precondition) refuses with `SIGNING_GATE_STEP_NOT_COMPLETED` until every signing-gate Step of the Project is COMPLETED. The Step is found by template metadata (Step 8 in cinema and new-document media, 11 in integration), never by number. Regression: 4825 passed / 0 failed. | The smoke order is unchanged (A's Steps 1–5 and 8 before A12). The order is now **enforced**: an early signing preview is BLOCKED and creates no pending confirmation. That is not a stop condition, since nothing is written. |
| F7 (Phase 4 audit, **open**, not on the A + D path) | A Merchant can have two open INTEGRATION_NEW_MERCHANT Projects: create rejects only duplicate titles (`project_preview._duplicates`). When the first completes "Activate Merchant", the Merchant is ACTIVE, and the second Project's activation Step is refused forever (`merchant_engine.py:393`: only ONBOARDING can be activated). That Project can never complete. | Not fixed: it needs an owner decision, either refusing a second open integration Project per Merchant at create, or letting activation accept an already-ACTIVE Merchant. Never create two integration Projects for one Merchant. Optional C0–C1 creates only one. |
| F8 (Phase 4 audit, consistency, **not** a deadlock) | (a) The ordinary Steps "Sign document", "Create Purchase Order" and "Create Payment Request" can complete without the matching record, so a Project could complete with no signature or PO. (b) A revision created after the signing gate completed is signed without the gate Step re-evaluating it. Signing still re-checks the same approvals and PR itself, so the effective prerequisites hold. (c) An Existing-Document Media Project that registers a revision of its own shadows its reused binding for PO and Payment Request (rule A before B). It recovers through its own approvals and signing, so no deadlock. | Documented only (business policy). In the smoke test, record each PO and Payment Request before completing its Step, as §10.3 already does. |
| F2 | Purchase Order and Payment Request depend on evidence (a signed own revision or the bound reused revision; a PO before the Payment Request) and a non-terminal Project, not on Step state. | D's PO and Payment Request are recorded while their Steps are IN_PROGRESS, which mirrors the workflow. |
| F3 | Typed scopes are refused at the intent gate for `document revision-create/approve/sign`, `project update` (test), `procurement update` and `step update` (`intent_gate.py:1057–1087`). `merchant create` has no preview path. Its authority is the user's own typed `/solve --confirm --merchant-target test --merchant-scope [...]`, the documented mechanism in `CLAUDE.md`, validated by the intent gate (scheduled prompts excluded), the completeness contract and the reserved Create executor. It was live-accepted in CP12H.5B. That Merchant row is no longer in the test DB, so the evidence is historical only. | The C Merchant create is **optional** and authorized only if **you decide** to type it. The text in this runbook grants nothing. |
| F4 | "Activate Merchant" (C Step 25) depends on Steps 14, 17 and 24, which means essentially the whole 26-Step workflow (≈ 81 writes). | No minimal live activation test exists. Activation stays **AUTOMATED_E2E only** (limitation L1). |
| F5 | Wording verified by read-only dry run (§4.0): no hyphens in titles; "gia hạn hợp đồng" for new-document media; "không cần mua sắm" for no procurement; D needs A signed first. | Used verbatim below. |
| F6 | Read-only uniqueness check: titles `Beta Live A Lê Lợi`, `Beta Live D Q4`, `Beta Live B Q4`, `Master Live C Integration`; references `PO-LIVED-001`, `PAY-LIVED-001`, `PR-LIVEB-001`; Merchant `MASTERLIVEC1` / `Master Live C Pay`. | All **unused**. |

### 10.2 Coverage matrix (automated vs live)

| Operation | Automated coverage | Prior live evidence | New in MASTER? | New trust boundary? | Minimum live smoke | Depends on |
|---|---|---|---|---|---|---|
| Project create (NL, `Xác nhận tạo`) | NL2/NL3 suites, `test_master_lifecycle_postgres` | **Yes**: NL3, NL4D4B (`6dfa1a96`) | no | no | A1 | – |
| Project create **with signed-revision reuse** | `test_master_fix_reuse_postgres` (14), migration 011 (10) | none | **yes** | **yes** (cross-Project binding, trigger, FOR SHARE) | D1 | A signed |
| Start Project | lifecycle E2E A–D | none | **yes** | yes (4th pending store) | A2, D2 | create |
| METADATA_ONLY revision | lifecycle E2E, migration 009 | none | **yes** | yes | A3 | A |
| LEGAL / ACCOUNTING / PARTNER APPROVED | lifecycle E2E, migration 010 | none | **yes** | yes (`recorded_by`, immutable decision) | A4–A6 | A3 |
| Operator-attested signing | lifecycle E2E, rejection cases | none | **yes** | yes (`signing_attestation`) | A12 | A4–A6, Step 8 (F1) |
| Purchase Request | NL4D4A suites, lifecycle B | **Yes**: NL4D4B `PR-NL4D4B-001` | no | no | **none** (reuse evidence) | – |
| Purchase Order | lifecycle E2E A–D, duplicate reference | none | **yes** | yes (lifecycle store; bound-revision prerequisite) | D5 | D1 |
| Payment Request | lifecycle E2E A–D | none | **yes** | yes | D8 | D5 |
| Step Update, ordinary start | NL4C2A/B, `test_ordinary_steps…` | **Yes**: NL4C2B (READY→IN_PROGRESS) | no | no | A7 | – |
| Step Update, ordinary ready / complete | `test_ordinary_steps…` | none | partly | no | A7–A11, D4–D9 | predecessors |
| Gate judged from evidence (Partner, signing gate) | lifecycle E2E (fixture advance), NL4C suites | none | partly | no | A10, A11 | approvals |
| Operator-attested gate completion | lifecycle E2E A–D | none | **yes** | yes (`gate_attestation`) | D3, D11 | Step IN_PROGRESS |
| Final-Step rule + Project completion | lifecycle E2E A–D, premature completion | none | **yes** | yes | D11, D12 | all Steps terminal |
| Merchant create (typed, test) | 5B/5C suites | **Yes** (CP12H.5B, historical) | no | no | optional C0 | your typed scope (F3) |
| Integration create on an ONBOARDING Merchant | lifecycle C | none | no | no | optional C1 | C0 |
| Merchant activation in the Step transaction | lifecycle C | none | **yes** | yes | **not feasible minimally** (F4) | ≈ 80 writes |
| Media new-document create (PR fixed) | lifecycle B | none | no | no | optional B1 | – |

**Selection rule.** Exercise live every **new** operation and every **new trust boundary**. Reuse the earlier live acceptances for Project create, Purchase Request and the Step start. Leave the activation chain to automated E2E.

### 10.3 Plan and order

| Part | Purpose | Confirmed writes |
|---|---|---|
| **Core A** (`Beta Live A Lê Lợi`, Beta Cinemas, no procurement) | source contract: create, start, revision, 3 approvals, the Step path to the signing gate, signing | **24** |
| **Core D** (`Beta Live D Q4`, Beta Cinemas, period 2) | reuse binding, start, attested gate, ordinary Steps, PO, Payment Request, final Step, **Project completion** | **16** |
| **Total core** | | **40 confirmed writes, ≈ 80 `/solve` runs** (a preview plus a confirmation each) |
| Optional C0–C1 | typed test Merchant create + integration create on ONBOARDING | 2 |
| Optional B1–B2 | media new-document create + PR on that variant | 2 |

**Order:** A1 → A12, then D1 → D12. Run D1 **only after** A12's read-back shows the signature committed. Optional parts come after the core, in any order. One operation at a time.

**Dependencies:**
- Both core Projects use Beta Cinemas (`NL2_LIVE_BETA`, ACTIVE).
- D binds A's revision, so A must not be superseded (it can't be once signed) and must have no REJECTED decision.
- A is left IN_PROGRESS with Steps 1–5 and 8 COMPLETED and Steps 9–22 open. It stays valid and completable later through §4.4 (A9 onward).

`S(X)` = `của Project X của Merchant Beta Cinemas trên database test`. Confirmation codes are the first 8 characters of the id the preview shows (§4.2).

#### Core A — source contract (24 writes)

| # | You type | Confirm with | Expected mutation |
|---|---|---|---|
| A1 | `/solve Tạo project mở rạp Beta Live A Lê Lợi cho Beta Cinemas, không cần mua sắm, trên database test` | `/solve Xác nhận tạo <project_id[:8]>` | +1 Project PLANNED v1 (OPENING_NEW_CINEMA_STANDARD, `requires_procurement` false), 22 Steps (1 READY, 6–7 SKIPPED), `PROJECT_CREATED` |
| A2 | `/solve Bắt đầu Project Beta Live A Lê Lợi trên database test` | `/solve Xác nhận thực hiện <operation_id[:8]>` | Project IN_PROGRESS v2, `PROJECT_STARTED` |
| A3 | `/solve Tạo phiên bản hợp đồng mới cho Project Beta Live A Lê Lợi trên database test` | same form | +1 revision CONTRACT #1, METADATA_ONLY, `content_hash = metadata-only:<id>`, unsigned |
| A4 | `/solve Legal đã phê duyệt hợp đồng của Project Beta Live A Lê Lợi trên database test` | same form | +1 approval LEGAL APPROVED, `approved_by` NULL, `recorded_by` = operator, `decided_at` set |
| A5 | `/solve Kế toán đã phê duyệt hợp đồng của Project Beta Live A Lê Lợi trên database test` | same form | +1 ACCOUNTING APPROVED |
| A6 | `/solve Partner đã phê duyệt hợp đồng của Project Beta Live A Lê Lợi trên database test` | same form | +1 PARTNER APPROVED |
| A7 | Step 1 (READY): `/solve Bắt đầu bước 1 S(Beta Live A Lê Lợi)`, then `/solve Hoàn thành bước 1 S(…)` | `/solve Xác nhận cập nhật <step_id[:8]>` after each | Step 1 IN_PROGRESS, then COMPLETED (2 writes) |
| A8 | Steps 2 and 3, each: `/solve Đánh dấu bước N của Project Beta Live A Lê Lợi của Merchant Beta Cinemas là sẵn sàng trên database test`, then `Bắt đầu bước N S(…)`, then `Hoàn thành bước N S(…)` | same | READY → IN_PROGRESS → COMPLETED (6 writes) |
| A9 | Step 4, same three requests | same | 3 writes |
| A10 | Step 5 (Record Partner approval, gate judged from evidence), same three requests | same | 3 writes; the preview shows the gate MET from PARTNER APPROVED |
| A11 | Step 8 (Validate signing gate, judged from evidence; predecessors 5 and 7 SKIPPED), same three requests | same | 3 writes; gate MET (3 × APPROVED, unsigned revision, no PR required). **Must be COMPLETED before A12.** Since F1 is fixed, an A12 preview before this is BLOCKED with `SIGNING_GATE_STEP_NOT_COMPLETED` naming Step 8, and nothing is pending |
| A12 | `/solve Ghi nhận hợp đồng của Project Beta Live A Lê Lợi đã ký trên database test` | `/solve Xác nhận thực hiện <operation_id[:8]>` | revision #1 `signed = true`, `signed_at` set, `signing_attestation = OPERATOR_ATTESTED_SIGNED` |

#### Core D — Existing-Document Media, end to end (16 writes)

| # | You type | Confirm with | Expected mutation |
|---|---|---|---|
| D0 | Read-only: snapshot A's revision row and its 3 approval rows (R2, `SELECT *`) | – | the source baseline |
| D1 | `/solve Tạo Project media Beta Live D Q4 cho Beta Cinemas kỳ thanh toán 2, sử dụng hợp đồng đã ký của Project Beta Live A Lê Lợi trên database test` | `/solve Xác nhận tạo <project_id[:8]>` | **Before confirming, check** the preview's `reused_document`: source Project `Beta Live A Lê Lợi`; revision id = A's revision #1; CONTRACT; signed; `OPERATOR_ATTESTED_SIGNED`. The argv must carry `--reused-document-revision-id <that id>`. After: +1 Project PLANNED (MEDIA_TOP_UP_EXISTING_DOCUMENT, period 2, `reused_document_revision_id` = A's revision), 4 Steps (1 READY), **no** revision or approval row |
| D2 | `/solve Bắt đầu Project Beta Live D Q4 trên database test` | `/solve Xác nhận thực hiện <operation_id[:8]>` | IN_PROGRESS v2 |
| D3 | Step 1 (Validate existing signed document, no evaluator): `Bắt đầu bước 1 S(Beta Live D Q4)`, then `Hoàn thành bước 1 S(…)` | `/solve Xác nhận cập nhật <step_id[:8]>` | 2 writes; the completion preview shows `gate_attestation: OPERATOR_ATTESTED`, and so does its STEP_COMPLETED event |
| D4 | Step 2 (Create Purchase Order, ordinary): `Đánh dấu … là sẵn sàng …`, then `Bắt đầu bước 2 S(…)` | same | 2 writes |
| D5 | `/solve Ghi nhận Purchase Order PO-LIVED-001 cho Project Beta Live D Q4 trên database test` | `/solve Xác nhận thực hiện <operation_id[:8]>` | +1 PURCHASE_ORDER `PO-LIVED-001` v1, accepted on the **bound** revision |
| D6 | `/solve Hoàn thành bước 2 S(Beta Live D Q4)` | `/solve Xác nhận cập nhật` | Step 2 COMPLETED |
| D7 | Step 3 (Create Payment Request): ready, then start | same | 2 writes |
| D8 | `/solve Ghi nhận Payment Request PAY-LIVED-001 cho Project Beta Live D Q4 trên database test` | `/solve Xác nhận thực hiện` | +1 PAYMENT_REQUEST `PAY-LIVED-001` v1 |
| D9 | `/solve Hoàn thành bước 3 S(Beta Live D Q4)` | `/solve Xác nhận cập nhật` | COMPLETED |
| D10 | Step 4 (Close payment period, final): ready, then start | same | 2 writes |
| D11 | `/solve Hoàn thành bước 4 S(Beta Live D Q4)` | same | COMPLETED, `gate_attestation: OPERATOR_ATTESTED` (final Step: every other Step done) |
| D12 | `/solve Hoàn tất Project Beta Live D Q4 trên database test` | `/solve Xác nhận thực hiện` | Project COMPLETED, `PROJECT_COMPLETED` |
| D13 | Read-only: repeat D0 | – | A's revision and approvals **byte-identical** to D0 |

D tally: create 1, start 1, Step writes 11 (Step 1: 2; Steps 2–4: 3 each), PO 1, Payment Request 1, completion 1 = **16**.

#### Optional parts (only if you choose)

| # | You type | Confirm | Expected |
|---|---|---|---|
| C0 | `/solve --confirm --merchant-target test --merchant-scope ["merchant","create","--code","MASTERLIVEC1","--name","Master Live C Pay"] Create test merchant MASTERLIVEC1`. **This line is your typed authorization (F3)**; it creates a real row on the test DB. | itself | +1 Merchant ONBOARDING v1, a verified Create receipt |
| C1 | `/solve Tạo project tích hợp merchant Master Live C Integration cho Master Live C Pay, không cần mua sắm, trên database test` | `/solve Xác nhận tạo` | +1 Project INTEGRATION_NEW_MERCHANT_STANDARD (26 Steps; 9–10 SKIPPED). Not dry-runnable before C0; check the preview's Merchant code is `MASTERLIVEC1`. Activation is **not** exercised (F4) |
| B1 | `/solve Tạo Project media Beta Live B Q4 cho Beta Cinemas kỳ thanh toán 1, gia hạn hợp đồng, trên database test` | `/solve Xác nhận tạo` | +1 Project MEDIA_TOP_UP_NEW_DOCUMENT, `requires_procurement` true, period 1 (dry-run READY) |
| B2 | `/solve Ghi nhận Purchase Request PR-LIVEB-001 cho Project Beta Live B Q4 trên database test` | `/solve Xác nhận ghi nhận <project_id[:8]>` | +1 PURCHASE_REQUEST v1 (the accepted NL4D4A path on the media variant) |

### 10.4 Baseline capture and read-back after each write

**Before A1:**
1. Re-run the §2 integrity check (expect `c79ecc67…`, 22 claims, nothing pending).
2. Save a **per-table snapshot** `{table: (count, md5)}` using the §2 hash method.

**After every confirmed write**, stop. Before the next operation, run read-only:

1. **Exactly one mutation.** Take a new per-table snapshot and diff it against the previous one. Only the expected tables may differ:
   - lifecycle, Step or PR write: the entity table + `project_events` + `merchant_execution_claims` + `merchant_execution_ledger`;
   - create: `projects`, `project_steps`, `project_step_dependencies`, `project_events`, claims;
   - C0: `merchants` and claims.

   The expected row counts must change by exactly the amounts in §5. Then replace the saved snapshot.
2. **Entity:** queries R1–R3 (§5) show the change in the "Expected mutation" column.
3. **Event, claim, ledger:**
   - one new `project_events` row of the expected type, with `triggered_by` = operator;
   - R4 shows one new COMPLETED claim and, for lifecycle, Step and PR writes, a ledger row with `same_tx = true`.
4. **Receipt from PostgreSQL alone:**
   - `attempt_evidence.recover_lifecycle_receipt(repo, operation)` (A2–A6, A12, D2, D5, D8, D12);
   - `recover_step_update_receipts(repo, step_id)` (Step writes);
   - `recover_purchase_request_receipts(repo, project_id)` (B2).

   Its `event_id`, `transaction_id`, `operation_key` and `execution_attempt_id` must equal the run-state receipt (`RECONCILED`). For creates, use the verified Create receipt the run reports.
5. **Operator:** `triggered_by` / `recorded_by` must have the operator fingerprint `210a4c001d41` (sha256[:12]; never print the UUID). `approved_by` stays NULL.
6. **Nothing else changed:**
   - the 5 accepted Projects keep their status and version;
   - NL4C2B Step 1 is IN_PROGRESS v2;
   - `PR-NL4D4B-001` exists once;
   - during D, A's rows change only as listed (they shouldn't change at all).

### 10.5 Stop conditions

Stop immediately, with no next operation, no retry and no re-confirmation, when:
- a run reports **UNCERTAIN**. Reconstruct the receipt (step 4), inspect R1–R4, and continue only once the evidence is definitive (§7);
- a run reports **FAILED** or a REVOKED claim appears. Read back, then decide. A fresh preview is a new attempt, never a retry of the old one;
- the read-back shows more or other changes than expected, a missing event, claim or ledger row, `same_tx = false`, or the wrong operator;
- D1's preview names a different source Project or revision, or no `--reused-document-revision-id`. Cancel with `/solve Hủy tạo <id>`;
- any accepted Project, NL4C2B Step 1 or `PR-NL4D4B-001` changes;
- a teammate pane or backend gate fails;
- a preview offers a confirmation for an operation you didn't request.

A BLOCKED or NEEDS_CLARIFICATION preview is **not** a stop: nothing was written. Fix the wording or finish the missing prerequisite (for example, `SIGNING_GATE_STEP_NOT_COMPLETED` means finish A11 first), and never bypass a prerequisite.

**Baseline for this plan (after CP12H.MASTER-FIX-F1):** HEAD is the F1 commit, the regression is 4825 passed / 21 skipped / 1 xfailed / 0 failed, and the DB hash is still `c79ecc67…` (the fix has no migration). The 40-write estimate is unchanged: the fix enforces the order the plan already used.

### 10.6 PASS / FAIL criteria

| Label | Meaning | Status |
|---|---|---|
| **AUTOMATED_E2E_PASS** | Workflows A–D completed in isolated automated integration tests | **Already met**: 4825 / 0 failed after CP12H.MASTER-FIX-F1 (lifecycle A, B, C; reuse D; F1 completion test) |
| **LIVE_SMOKE_PASS** | Every core write (A1–A12, D1–D12, 40 writes) executed exactly once through real user confirmations, and each passed every §10.4 check; D13 byte-identical; no stop condition hit | pending your run |
| **FULL_LIVE_E2E_PASS** | An entire Project completed through real user confirmations, every required Step included | The core plan earns it **for workflow D only** (D1–D12 cover every D Step and completion, with the source contract produced live in A). It is **not** earned for A, B or C |

**FAIL:** any stop condition that ends without definitive evidence; a duplicate write; a mutation outside the expected tables; a receipt that can't be reconstructed; operator mismatch; a change to the source revision; a change to accepted data.

**Never** report LIVE_SMOKE_PASS as FULL_LIVE_E2E_PASS, and never report a FULL_LIVE_E2E_PASS for A, B or C from this plan.

**Remaining live limitations** (covered by automated E2E only):
- **L1:** Merchant activation (C Step 25).
- **L2:** Project completion for A, B and C.
- **L3:** the Purchase Request → signing-gate interaction on a procurement Project.
- **L4:** rejection blocking signing (optional negative check, §4.7).

# CP12H.NL4D4B-LIVE — Purchase Request Live Acceptance

**Verdict: EXECUTED_AND_VERIFIED.** The confirmed Purchase Request `PR-NL4D4B-001` was recorded on `coding_agent_merchant_test` exactly once, through the trusted pipeline, bound to the configured recording operator.

**Context:**
- **Branch:** `feat/cp7-9-merchant-reliability`.
- **Code under test:** `23f1f6d` (NL4D4A), `b66c0c0` (decision register) and `2b50e40` (agent instructions).
- **Live sessions:** lead `3d6eb3a4-4f38-4629-bbf4-61171ee27c37`; merchant-manager transcript `4db6bc7b-247f-440a-ada4-c7e2c0a56b3f`.
- **Live run:** 2026-11-11, 09:51–10:00 UTC (16:51–17:00 +07).

**How this was verified:**
- Verification was independent and read-only:
  - a `merchant_test` session with `transaction_read_only = on`;
  - local state files and transcripts were read only.
- No write, replay, retry, repair or cleanup was attempted.
- Production was never connected.
- The operator UUID appears only as its SHA-256 fingerprint, `210a4c001d41`.

## 1. Verified facts

| # | Fact | Source |
|---|---|---|
| 1 | One confirmed Project creation: "Beta NL4D4B PR Acceptance", `6dfa1a96-095c-5f61-b74c-f5c28e0e6b66` | §2.1, §3.1 |
| 2 | One confirmed Purchase Request creation | §2.2, §3.2 |
| 3 | Exact reference `PR-NL4D4B-001` | §3.2 |
| 4 | Correct Project and Merchant: `NL2_LIVE_BETA` (`6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f`), `requires_procurement = false` | §3.1 |
| 5 | Trusted recording operator: fingerprint `210a4c001d41` = configured | §3.3, §5 |
| 6 | One PR row (the only procurement row in the database), version 1 | §3.2 |
| 7 | One matching `PROCUREMENT_CREATED` event | §3.3 |
| 8 | One COMPLETED execution claim for the attempt | §3.3 |
| 9 | One matching ledger entry | §3.3 |
| 10 | Row, event, claim and ledger all written by PostgreSQL transaction **43076** | §3.3 |
| 11 | Receipt reconstructed from PostgreSQL alone, matching every record and the confirmed operation | §3.4 |
| 12 | No Step mutations | §3.5 |
| 13 | No duplicate procurement reference within the Merchant and type | §3.2 |
| 14 | No unexpected evidence writes: excluding exactly this run's rows reproduces the pre-run hash | §3.6 |
| 15 | No unauthorized scope and no retry | §2, §5 |

## 2. Original live execution evidence (session records)

### 2.1 Project create

1. **09:51:56:** the user typed `/solve Tạo Project mở rạp Beta NL4D4B PR Acceptance cho Merchant Beta Cinemas trên database test, không cần Purchase Requisition`. The teammate ran `agent_cli.py project preview … --test-database` and reported READY_FOR_CONFIRMATION, with nothing created.
2. **09:54:38:** the user confirmed with `/solve Xác nhận tạo 6dfa1a96`. The pending Project-create record went to CONFIRMED (`confirmed_run_id 0cc8a708-…`).
3. **09:55:16:** the teammate sent one execute request. Its argv is byte-identical to the confirmed record's canonical argv:
   - `--merchant-code NL2_LIVE_BETA`;
   - `--no-requires-procurement`;
   - `--expected-basis 667ba2e8…`.
4. **09:55:26:** reported `EXECUTE_SUCCESS`.

### 2.2 Purchase Request

1. **09:56:37: refused premature confirmation.** See §5.
2. **09:56:58:** the user typed `/solve Ghi nhận Purchase Request số PR-NL4D4B-001 cho Project Beta NL4D4B PR Acceptance trên database test`.
   - The teammate ran `agent_cli.py evidence preview … --test-database` and reported PREVIEW_VALID, with nothing recorded.
   - The trusted capture created one pending Purchase Request (source run `62e63009-…`) with:
     - reference `PR-NL4D4B-001`;
     - Project `6dfa1a96-…`;
     - test database;
     - operator fingerprint `210a4c001d41`;
     - expected basis `1deb052d…`.
3. **09:59:06:** the user confirmed with `/solve Xác nhận ghi nhận 6dfa1a96`. The intent gate's system message: "Confirmed Purchase Request 'PR-NL4D4B-001' for Project 'Beta NL4D4B PR Acceptance' (NL2_LIVE_BETA, project_id 6dfa1a96-…), recorded by operator ‹fp 210a4c001d41› on the test database. It runs once now." The record went to CONFIRMED (`confirmed_run_id 17405bb6-…`).
4. **09:59:39:** the teammate sent **one** `procurement update` execute request. Its argv is byte-identical to the confirmed record's canonical argv, and the operator in it is the configured one.
5. **09:59:49:** reported `EXECUTE_SUCCESS` — "The attempt is spent and was not retried."

**Teammate surface for the whole run.** The teammate ran exactly 4 literal `agent_cli.py` commands:
- `project preview --test-database`;
- `completeness check` (Project);
- `evidence preview --test-database`;
- `completeness check` (procurement).

It sent 6 messages. It ran no other shell command, file write or SQL.

## 3. Independent PostgreSQL read-back

### 3.1 Session, Project and Merchant

- **Session:** `coding_agent_merchant_test` / `merchant_test` / `transaction_read_only = on`.
- **Project:** `6dfa1a96-…` "Beta NL4D4B PR Acceptance":
  - Merchant `6e0c1a2b-…` = `NL2_LIVE_BETA`;
  - `OPENING_NEW_CINEMA` / `OPENING_NEW_CINEMA_STANDARD`;
  - PLANNED v1;
  - `requires_procurement = false` (DEC-P2 exercised);
  - created 16:55:17 +07.
- **Project-create evidence:**
  - claim and ledger `merchant-scope:v1:5cf813f3…`, command `project create`;
  - attempt `46b4b4e2-…`;
  - transaction 43075, the same transaction as its `PROJECT_CREATED` event.

### 3.2 Purchase Request record

| Field | Value |
|---|---|
| id | `dfe8157b-12c3-4e9c-83c8-354f8adf9cb1` |
| merchant_id | `6e0c1a2b-…` (the Project's Merchant; enforced by the composite FK) |
| procurement_type / external_id | `PURCHASE_REQUEST` / `PR-NL4D4B-001` (exact) |
| status / version | null / **1** |
| created / transaction | 16:59:44.976 +07 / **43076** |

**Totals:**
- the database holds **1** procurement row: no Purchase Order and no Payment Request;
- holders of (`NL2_LIVE_BETA`, `PURCHASE_REQUEST`, `PR-NL4D4B-001`): exactly 1.

### 3.3 Event, claim and ledger (transaction 43076)

| Record | Value |
|---|---|
| Event | `34c7c5df-037b-4c0d-9a97-9f40aac88a59`, `PROCUREMENT_CREATED`, entity `dfe8157b-…`. Old `{external_id_recorded: false, version: null}` → new `{external_id_recorded: true, version: 1, status: null}`. `triggered_by` fingerprint **`210a4c001d41`**. |
| Claim | `merchant-scope:v1:fc70a61ffc1412eaef1315e4567dd93fe0478e538121d8e957979efdd386dfee`. **COMPLETED**, generation 1, attempt `bcb977fc-55a9-4e63-8d42-3585cefcc6bd`, payload hash `0783bd3560799612a8ac56a65db534a24f6956434fd2b1afce6e45de572ec883`. |
| Ledger | same key and payload hash; `result = {command: "procurement update", execution_attempt_id: "bcb977fc-…"}` |

The Project has two events in total: `PROJECT_CREATED` (transaction 43075, no operator) and this one.

### 3.4 Receipt reconstructed from PostgreSQL alone

`attempt_evidence.recover_purchase_request_receipts(repository, '6dfa1a96-…')` returned **exactly one** `purchase_request_receipt_v1`.

| Field | Receipt | Persisted record | Confirmed operation |
|---|---|---|---|
| merchant_id | `6e0c1a2b-…` | Project and row | `NL2_LIVE_BETA` (`6e0c1a2b-…`) |
| project_id | `6dfa1a96-…` | row and event | `6dfa1a96-…` |
| procurement_type | `PURCHASE_REQUEST` | row | `PURCHASE_REQUEST` |
| reference | `PR-NL4D4B-001` | row `external_id` | `PR-NL4D4B-001` |
| operator | fp `210a4c001d41` | event `triggered_by` | fp `210a4c001d41` |
| procurement_id / record_version | `dfe8157b-…` / 1 | row | — |
| event_id | `34c7c5df-…` | event | — |
| execution_attempt_id | `bcb977fc-…` | claim and ledger | — |
| operation_key / payload_hash | `…fc70a61f…` / `0783bd35…` | claim and ledger | — |
| claim_status / ledger_command | COMPLETED / `procurement update` | claim and ledger | `procurement update` |
| transaction_id | 43076 | row, event, claim and ledger `xmin` | — |

The function returns a receipt only if all of these hold:
- the claim and ledger name the same attempt and payload hash;
- the claim is COMPLETED;
- there is exactly one `PROCUREMENT_CREATED` event in the ledger's transaction;
- the record was written by that same transaction;
- the event and record Merchants agree;
- the version is 1.

### 3.5 Steps

All 22 steps equal the fresh no-procurement template state:
- step 1 READY;
- steps 6–7 SKIPPED;
- every other step PENDING;
- all at version 1.

No step has `actual_start` or `actual_completion`, and the Project has no STEP event.

### 3.6 Exactly once and integrity (final read-only check before commit)

| Check | Result |
|---|---|
| Database identity | `coding_agent_merchant_test` / `merchant_test`, read-only |
| Full-database hash | **`99abfa8e56c2da686b276127310d7e28ae4c80ab78b351b78f8a407b38f33f8a`**, unchanged since the live run (the new baseline) |
| Delta check | excluding only this run's rows reproduces the pre-run baseline `60ea5bc9b4297182f895deadf83d82b905b8c0e0ae380d368910167795e3b3d4` exactly. The excluded rows are:<br>• 1 Project, 22 steps, 22 dependencies;<br>• 2 events;<br>• 1 procurement row;<br>• 2 claims and 2 ledger rows (Project create and Purchase Request). |
| Claims | 22, **all COMPLETED**; none ACTIVE or REVOKED |
| Ledger | 6 rows; **0 orphan** (every ledger row has its claim) |
| Pending confirmations | 5 records across the live and earlier sessions, all CONFIRMED (each spent once) and expired; none PENDING |
| Acceptance records | NL2 `30fffeaf-…`, NL3 `ba5cc7ec-…` and NL4C2B `8dd4c68d-…` are all PLANNED v1, `updated_at` unchanged |
| NL4C2B step 1 | `98dc77cf-…` **IN_PROGRESS v2** |
| Migration 007 | applied (versions 1–7); the unique index is valid; the composite FK is validated |
| Other database sessions or tests | none |

## 4. Known deviations from the runbook

1. **A1 wording.** "…không cần Purchase Requisition" was used instead of "…không cần mua sắm". The result is still correct: `requires_procurement = false`.
2. **B1 wording.** "Ghi nhận Purchase Request **số** PR-NL4D4B-001 …" was used. The reference was still extracted exactly.
3. **A3 and C1 checks not run during the live session.** The scripted checks were replaced by this independent read-back.
4. **C2 replay and C3 re-preview not exercised live.** They were deliberately not run in this verification either. Replay refusal is covered by the automated tests.
5. **Lead memory edits.** At the end of the live run, the lead session edited its own memory files, which are outside the repository and the database.

## 5. Security boundaries

| Boundary | Evidence |
|---|---|
| Operator from trusted configuration | `.env` operator fingerprint `210a4c001d41` equals the pending record, the operation, the executed argv, the event's `triggered_by` and the receipt |
| No model-supplied operator | no prompt named an operator; the executed argv is byte-identical to the confirmed record; trusted code resolved the operator at capture, gate, preflight and in the transaction (NL4D4B-PREP §11.1) |
| No handwritten procurement scope | no `--merchant-scope` was typed; the scope came only from the user's `/solve Xác nhận ghi nhận 6dfa1a96` and the verified record |
| No retry | one execute request per write, and the report says "not retried"; no second row, event, claim or ledger exists |
| Runtime Direct EXECUTE disabled | `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; every request targeted `test` |
| No production connection | all teammate reads used `--test-database`; hook writes use only the test-target repository; this verification used only `role="test"` |

**Fail-closed evidence (premature confirmation).** At 09:56:37 the user typed `/solve Xác nhận ghi nhận` **before** any Purchase Request preview existed. The intent gate refused it: "There is no pending Purchase Request for this session to confirm … Nothing was recorded." Nothing was dispatched, spent or written. This is additional live evidence that the confirmation cannot act without a trusted pending record.

## 6. Remaining limitations

1. **No pre-write Step snapshot.** It was not taken during the live run. This is a limitation of the evidence, not a failed test. Step integrity is shown instead by:
   - every step's equality with the template's initial state;
   - the absence of STEP events and timestamps;
   - the delta hash (§3.6).
2. **The run-state copy of the receipt is gone.** `merchant_purchase_request_receipt` was cleared with the session's run state, so it could not be compared. The PostgreSQL reconstruction (§3.4) is authoritative and complete.
3. **Replay was not exercised live** (§4.4). It relies on the automated tests.
4. **Operator trust is a workstation boundary.** It is attribution, not authentication: any same-user process can edit `.env`.
5. **Scope:** test database only. Runtime is unmigrated and disabled.

## 7. Final NL4D4B acceptance verdict

**EXECUTED_AND_VERIFIED. NL4D4B is accepted.** The test-only Purchase Request path (DEC-A0, P1a, P1c, P2) is verified live end to end:
- read-only preview;
- trusted pending record;
- the user's own confirmation;
- preflight;
- evidence-bound transaction;
- durable PostgreSQL receipt.

The new test-database baseline is `99abfa8e…`.

**Still NO-GO:**
- runtime/production Direct EXECUTE;
- migration 007 on runtime;
- Purchase Order, Payment Request, document revision, approval and signing execution;
- NL4D5A, until it is planned and approved.

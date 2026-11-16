# CP12H.NL4C2B — Independent Live Step Update Verification

> **Final NL4C status (committed together as `feat(merchant): enable trusted test-only step updates`).**
> - **Execution:** Step Update runs **only on the test database** (`coding_agent_merchant_test`), only from the user's own `/solve Xác nhận cập nhật` of a verified preview. **Production (runtime) Direct EXECUTE is disabled in code** (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`).
> - **Automated regression:** the final full suite is in the NL4C commit summary.
> - **Live acceptance:** one user-confirmed Step Update (step 1 READY → IN_PROGRESS of Project `8dd4c68d-…`) returned EXECUTE_SUCCESS, and an **independent read-only PostgreSQL verification** found it EXECUTED_AND_VERIFIED (`cp12h_nl4c2b_live_acceptance.md`).
> - **`confirmation_available`:** `true` only for a READY test-database preview. It means the user may confirm; it never means a write is authorized. This supersedes any "always false" wording below.
> - **Known limitations:** see the "Remaining risks" section of each report.

**Verdict: EXECUTED_AND_VERIFIED.** The user-confirmed Step Update committed **exactly once**:
- **Change:** step 1 of Project `8dd4c68d-76a9-571b-ad08-a864d7fcf7a5` moved READY → IN_PROGRESS on `coding_agent_merchant_test`.
- **Evidence:** a single PostgreSQL transaction (`xid 27067`) that also committed its execution claim and ledger row.

**How this was verified:**
- Read-only: a `SET TRANSACTION READ ONLY` session; no records were retried, created, updated, cleaned up or repaired.
- Nothing is committed or pushed.
- The queries were run by a local, uncommitted read-only script. Every value below is quoted from its output; §4–§6 name the tables and the recovery function they came from.

## 1. Database identity and read-only transaction

| Setting | Value |
|---|---|
| `current_database()` | `coding_agent_merchant_test` |
| `current_user` | `merchant_test` |
| `transaction_read_only` (start / end) | `on` / `on` |
| `default_transaction_read_only` | `on` |
| `txid_current_if_assigned()` (start / end) | `NULL` / `NULL` (no transaction ID assigned, so nothing was written) |

## 2–3. Project and Step rows

**Project `8dd4c68d-76a9-571b-ad08-a864d7fcf7a5`:**
- title "Beta NL4C2B Step Acceptance", status PLANNED, **version 1**;
- `updated_at` is `15:58:29`, its creation time, so the Project row was not changed (a Step transition never updates `projects`);
- Merchant `6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f` (`NL2_LIVE_BETA`), Merchant version 1.

**Step `98dc77cf-39d2-5f3f-b3a3-9e8e762d39c7`:**

| Field | Value |
|---|---|
| Project | `8dd4c68d-…` |
| `sequence_number` | 1 |
| `step_name` | "Draft or renew document" |
| status | **IN_PROGRESS** |
| version | **2** |
| `actual_start` | 2026-11-09 17:11:55.884711+07 |
| `actual_completion` | NULL |
| `updated_at` | 2026-11-09 17:11:55.785661+07 |
| `xmin` | **27067** |

**Other steps of the Project:** all are PENDING version 1, except the optional steps 6 and 7 (SKIPPED version 1 from creation). The NL2/NL3 Projects have the same creation-time shape. **No other step was changed.**

## 4. Step events

There is exactly one STEP event for the Project. The Project has 2 events in total: `PROJECT_CREATED` at 15:58:29 and this one.

| Field | Value |
|---|---|
| `event_id` | `97bea570-3d2c-4fce-8d7b-b2d3f0ba5295` |
| `event_type` | `STEP_STARTED` |
| `entity_id` | `98dc77cf-…` |
| `merchant_id` | `6e0c1a2b-…` |
| `old_values` | `{status: READY, version: 1, actual_start: null, actual_completion: null}` |
| `new_values` | `{status: IN_PROGRESS, version: 2, actual_start: 2026-11-09T10:11:55.884711Z, actual_completion: null}` |
| `change_summary` | "Project step status changed from READY to IN_PROGRESS" |
| `created_at` | 2026-11-09 17:11:55.785661+07 |
| `xmin` | **27067** |

## 5. Execution claim and durable ledger

**Ledger row** written by the same transaction as the event (`xmin = 27067`); it is the **only** `step update` ledger row in the database:
- `operation_key`: `merchant-scope:v1:72e7ae4a1ca4e22669c87ee529866fe3d9a52943701c5136279dcb7e4d68dccf`
- `payload_hash`: `11fec903a0b46017f69fe13aff2f203e28f0a5063272fe83de17cb00cdb62822`
- `result`: `{command: "step update", execution_attempt_id: "b5dcf4d1-d23c-42fe-91bc-72dcbc40177e"}`

**Claim** for that key:
- `payload_hash`: same as the ledger
- `execution_attempt_id`: `b5dcf4d1-d23c-42fe-91bc-72dcbc40177e`
- `claim_status`: **COMPLETED**
- `claim_generation`: 1
- `claimed_at` = `updated_at` = 17:11:55.785661+07
- `xmin`: **27067**

## 6. Receipt rebuilt from PostgreSQL alone

`recover_step_update_receipts(repository, "98dc77cf-…")` returned exactly **1** receipt. Its fields are compared with the other sources in §7.

## 7. Cross-source comparison

Four sources were compared:
- **Confirmed pending record:** the session's trusted Step store.
- **Database rows:** step, event, ledger and claim.
- **Rebuilt receipt:** the §6 output.
- **Team-state history:** the session's `completed_scope_execution_history`.

| Field | Pending record (confirmed) | Database rows | Rebuilt receipt | Team-state history |
|---|---|---|---|---|
| Merchant | `6e0c1a2b-…` / `NL2_LIVE_BETA` | event `merchant_id` `6e0c1a2b-…` | `6e0c1a2b-…` | — |
| Project | `8dd4c68d-…` (version 1) | step / event `8dd4c68d-…` | `8dd4c68d-…` | — |
| Step / number | `98dc77cf-…` / 1 | `98dc77cf-…` / 1 | `98dc77cf-…` / 1 | — |
| Previous → new status | READY → IN_PROGRESS | event old/new READY → IN_PROGRESS; row IN_PROGRESS | READY → IN_PROGRESS | — |
| Previous → new version | `--expected-version 1` | event 1 → 2; row 2 | 1 → 2 | — |
| Event ID | — | `97bea570-…` | `97bea570-…` | — |
| Attempt ID | — | claim and ledger `b5dcf4d1-…` | `b5dcf4d1-…` | `b5dcf4d1-…`, command `step update`, SUCCEEDED |
| Operation key | — | `merchant-scope:v1:72e7ae4a…` | same | (derived) |
| Payload hash | — | claim = ledger `11fec903…` | `11fec903…` | — |
| Run | confirmed for run `01f456a9-ee99-4186-8b67-16fa10da526a` | — | — | run `01f456a9-…` |
| Database target | `test` | `coding_agent_merchant_test` | — | — |
| Transaction | — | step, event, claim and ledger all `xmin 27067` | `transaction_id 27067` | — |

**All sources agree. There is no contradiction.**

## 8–9. Exactly one committed transition; no duplicates or inconsistencies

**One transition:**
- one STEP event for the step;
- the step version is 2, so it went 1 → 2 exactly once;
- one `step update` ledger row and one claim, all written by transaction 27067.

**Change in the whole database since the pre-test baseline:**

| Table | Baseline (NL4C2B-FIX) | Now | Change |
|---|---|---|---|
| projects | 4 | 4 | 0 |
| project_steps | 92 | 92 | 0 |
| project_events | 8 | 9 | **+1** |
| merchant_execution_claims | 19 | 20 | **+1** |
| merchant_execution_ledger | 3 | 4 | **+1** |
| merchants | 2 | 2 | 0 |

**No duplicate or unresolved state:**
- No duplicate mutation.
- All 20 claims are COMPLETED; there are 0 ACTIVE or unresolved claims and 0 REVOKED fences.
- 0 ledger rows with a NULL result, and 0 ledger rows without a claim.

## 10. Pending confirmation consumed once

**The Step store:** session `e88039bd-…` (`.claude/runtime/e88039bd-….pending_step.json`) holds exactly **1** record:
- status **CONFIRMED**, for step `98dc77cf-…`, on the test database;
- `confirmed_run_id` `01f456a9-…`, the same run as the execution;
- created 17:10:08, confirmed 17:10:54, expires 17:25:08.

**Earlier preview:** a 16:44 preview record was replaced by the 17:10 preview of the same step, by design. That earlier record was never confirmed.

**User action:** the transcript shows exactly one `/solve Xác nhận cập nhật 98dc77cf`, typed by the user at 17:10:59 (UTC 10:10:59). Its envelope `raw_request` is "Xác nhận cập nhật 98dc77cf", with `risk_level` external_write.

**Teammate:** merchant-manager is `IDLE_REUSABLE`, with no open `direct_scope_execution`. Its history holds the SUCCEEDED `step update` (`b5dcf4d1-…`, run `01f456a9-…`).

**Note:** the run's state file was not kept after the run ended, so the run-state copy of the receipt (`merchant_step_update_receipt`) cannot be inspected. This does not weaken the verdict: the authoritative receipt was rebuilt independently from PostgreSQL (§6) and matches every other source.

## 11. NL2 and NL3 acceptance Projects unchanged

| Project | Status / version | `updated_at` | Non-PENDING steps | Events |
|---|---|---|---|---|
| `30fffeaf-…` "Beta Nguyễn Văn Cừ" (NL2) | PLANNED / 1 | 2026-11-04 13:44:38 (creation) | 1 READY v1; 6, 7 SKIPPED v1 | 1 |
| `ba5cc7ec-…` "Beta NL3 Confirmation Test" (NL3) | PLANNED / 1 | 2026-11-04 17:00:59 (creation) | 1 READY v1; 6, 7 SKIPPED v1 | 1 |

## 12. Runtime Direct EXECUTE

`RUNTIME_DIRECT_EXECUTE_ENABLED = False` (`.claude/hooks/merchant_direct_handoff.py:65`).

## Verdict

**EXECUTED_AND_VERIFIED:**
- **Exactly one committed transition**, for the expected Project, Step and target.
- **Atomic:** database transaction 27067 holds the step update, the STEP_STARTED event, the COMPLETED claim and the ledger row.
- **Consistent:** the confirmed pending record, the PostgreSQL rows, the rebuilt receipt and the team-state history agree on Merchant, Project, Step, statuses, versions, event ID, attempt ID, operation key and payload hash.
- **No side effects:** no duplicates, no unresolved claims, and the acceptance Projects are unchanged.

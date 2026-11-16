# CP12H.NL2 — Final Database Read-Back Acceptance

Date: 2026-11-04
Mode: read-only. The session used `default_transaction_read_only=on` (`transaction_read_only = on` confirmed), connecting through `MerchantDatabaseClient(RepositoryConfig.from_env("test")).connection(read_only=True)`.
Nothing was written, cleaned up, retried or re-created.

## 1. Database identity

| Check | Expected | Actual |
|---|---|---|
| `current_database()` | `coding_agent_merchant_test` | `coding_agent_merchant_test` ✅ |
| `current_user` | `merchant_test` | `merchant_test` ✅ |
| `transaction_read_only` | `on` | `on` ✅ |

## 2. Merchant

| Field | Value |
|---|---|
| id | `6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f` ✅ |
| code | `NL2_LIVE_BETA` ✅ |
| name | Beta Cinemas |
| account_status | ACTIVE |
| created_at | 2026-11-01 14:07:39.998057+00 (fixture, version 1; this run did not change it) |
| Projects owned | 1 |

## 3. Project (`merchant_ops.projects`)

Exactly **1** row has id `30fffeaf-e6b5-5119-b078-52c934e1821e`.

| Field | Expected | Actual |
|---|---|---|
| merchant_id | 6e0c1a2b-… (NL2_LIVE_BETA) | `6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f` ✅ |
| title | Beta Nguyễn Văn Cừ | `Beta Nguyễn Văn Cừ` ✅ (UTF-8 intact; exactly 1 project has this title) |
| project_type | OPENING_NEW_CINEMA | `OPENING_NEW_CINEMA` ✅ |
| workflow_variant | OPENING_NEW_CINEMA_STANDARD | `OPENING_NEW_CINEMA_STANDARD` ✅ |
| requires_procurement | false | `false` ✅ |
| status | valid initial state | `PLANNED` ✅ |
| workflow_template_version_id | — | `a3cc7546-6b0f-58a7-b78d-8e7a3289dc10` (OPENING_NEW_CINEMA_STANDARD v1, active, 22 template steps) |
| started_at / completed_at | null | null ✅ |
| payment_period_number | — | null |
| reused_document_revision_id | — | null |
| version | 1 | 1 ✅ |
| created_at = updated_at | — | 2026-11-04 06:44:38.420165+00 |
| created_by | — | null (see discrepancies) |

Related rows: `procurement_records` = 0 and `document_revisions` = 0. Both are expected for a new Project without procurement.

## 4. Workflow and step state (`merchant_ops.project_steps`)

There are 22 step rows, one for each of the 22 template steps, and every row has a `template_step_id`. There are 22 `project_step_dependencies`. All steps have `version = 1`, and none has a scheduled or actual date.

Status totals: **READY 1, PENDING 19, SKIPPED 2**.

| # | Branch | Step | Template type | Status |
|---|---|---|---|---|
| 1 | document_branch | Draft or renew document | SEQUENTIAL | READY |
| 2 | document_review_branch | Legal review | PARALLEL_BRANCH | PENDING |
| 3 | document_review_branch | Accounting review | PARALLEL_BRANCH | PENDING |
| 4 | document_branch | Send reviewed revision to Partner | SEQUENTIAL | PENDING |
| 5 | document_branch | Record Partner approval | APPROVAL_GATE | PENDING |
| 6 | procurement_branch | Create Purchase Request | CONDITIONAL (optional, `requires_procurement`) | **SKIPPED** ✅ |
| 7 | procurement_branch | Record Purchase Request number | CONDITIONAL (optional, `requires_procurement`) | **SKIPPED** ✅ |
| 8 | document_branch | Validate signing gate | APPROVAL_GATE | PENDING |
| 9 | document_branch | Sign document | SEQUENTIAL | PENDING |
| 10 | payment_branch | **Create Purchase Order** | SEQUENTIAL, required, unconditional | PENDING ✅ |
| 11 | payment_branch | **Create Payment Request** | SEQUENTIAL, required, unconditional | PENDING ✅ |
| 12–14 | production_branch | Production agent / service list / send to Partner | PARALLEL_BRANCH | PENDING |
| 15–20 | uat_branch | UAT agent, Product ID, MID, send, JIRA, test | PARALLEL_BRANCH | PENDING |
| 21 | uat_branch | Complete UAT acceptance | APPROVAL_GATE | PENDING |
| 22 | — | Complete project | APPROVAL_GATE | PENDING |

- Steps 6–7 are SKIPPED. Both are the only `CONDITIONAL` template steps, and their condition `requires_procurement` is false.
- The Purchase Order (10) and Payment Request (11) steps are present and PENDING. In the template they are non-optional and have no condition key, so they are still available downstream of signing.

## 5. Execution evidence

### Execution claim (`merchant_execution_claims`)

| Field | Value |
|---|---|
| operation_key | `merchant-scope:v1:275d64823683bc8a8841ceee22f47e5b1eea16399e41e0b3b9e5488f019525ef` |
| payload_hash | `c9a07d175e9cab396b1b8d409522155504c0d2b9d16df030c788413849f29203` |
| execution_attempt_id | `d6ef63b0-8fbc-4d53-b1a2-c0caeafe7a8d` |
| claim_generation | 1 |
| claim_status | `COMPLETED` |
| claimed_at = updated_at | 2026-11-04 06:44:38.420165+00 |

Only one claim has this payload_hash. It is also the only claim created or updated on 2026-11-04. The table holds 17 claims in total, and all of them are COMPLETED, so there are no EXECUTING, REVOKED or other unsettled claims.

### Durable ledger (`merchant_execution_ledger`)

There is exactly one ledger row for this operation key and payload hash:
`result = {"command": "project create", "execution_attempt_id": "d6ef63b0-8fbc-4d53-b1a2-c0caeafe7a8d"}` and `created_at = 2026-11-04 06:44:38.420165+00`.

### Project events (`project_events`)

There is exactly one event for the Project, and it is the only event for the Merchant:

- id `354dfd29-bda9-4ad2-9b0c-1122927ca131`, `PROJECT_CREATED` / `PROJECT`, entity_id = Project id
- summary: "Merchant project created from immutable workflow template"
- new_values: `status=PLANNED, step_count=22, dependency_count=22, project_type=OPENING_NEW_CINEMA, workflow_variant=OPENING_NEW_CINEMA_STANDARD, requires_procurement=false, payment_period_number=null, workflow_template_version_id=a3cc7546-…`
- created_at 2026-11-04 06:44:38.420165+00

### Single-transaction atomicity

The project row, the 22 steps, the event, the claim and the ledger row all carry the same timestamp, **`06:44:38.420165+00`**. PostgreSQL's `now()` is the transaction start time, so all of them were committed in one transaction. The claim, the ledger row and the mutation were therefore committed together. This Project is also the newest one in the database (`max(projects.created_at)`).

### Run / task / command binding (independent recomputation)

Team state `.claude/runtime/team_state/49f7c713-4d84-4b3c-8461-b21c69ec5b5f.json` → `merchant-manager.completed_scope_execution_history[0]`:

| Field | Value |
|---|---|
| owner session | `49f7c713-4d84-4b3c-8461-b21c69ec5b5f` |
| run_id | `1ef22eb1-7bc4-481e-a6e6-573dfa93fe70` |
| task_id | `1ef22eb1-7bc4-481e-a6e6-573dfa93fe70:merchant-manager` |
| command | `project create` |
| scope_hash | `c9a07d17…9203` |
| confirmation_hash | `9f905ffc75cb7d0f3319d0997142cd2fa3094d7d6821f1910cabb0c4ac54bb80` |
| execution_attempt_id | `d6ef63b0-8fbc-4d53-b1a2-c0caeafe7a8d` |
| status | `SUCCEEDED` (teammate now `IDLE_REUSABLE`) |

- I recomputed the operation key as `sha256({owner_session_id, teammate_name, run_id, task_id, command, scope_hash})`, following `merchant_attempt_resolution.scope_attempt_identity`. The result is `merchant-scope:v1:275d6482…25ef`, which **matches the DB claim** ✅.
- I recomputed the scope hash with `_direct_scope_hash(argv, "test")` from the previewed `requested_operation.argv`. Those preview sessions are `3a21ef05…` and `44beb2f5…`, and they hold the same argv. The result is `c9a07d17…9203`, which **matches the claim payload_hash, the ledger row and the team-state scope_hash** ✅. The database target `test` is part of that hash.
- The authorized argv was: `project create --merchant-id 6e0c1a2b-… --type OPENING_NEW_CINEMA --variant OPENING_NEW_CINEMA_STANDARD --title "Beta Nguyễn Văn Cừ" --project-id 30fffeaf-… --expected-basis 2f26fb44…3ea5 --merchant-code NL2_LIVE_BETA --no-requires-procurement`. Every argument matches the persisted row.

### Idempotency / replay marker

- The operation key does not include the attempt id. A replay of the same owner/run/task/command/scope would therefore produce the same key and collide with the existing claim before any mutation.
- There is one claim, one ledger row, one Project, one event and one attempt id. No second attempt and no fence (REVOKED) exist.

**Conclusion: exactly one Project creation was committed for the authorized execution.**

## 6. Discrepancies / observations (non-blocking)

1. **The ledger `result` does not contain the Project id.** It holds only `command` and `execution_attempt_id`. The link from ledger to Project rests on the shared transaction timestamp and the matching scope hash, not on a stored key. This is acceptable evidence, but a future hardening step could record `project_id` in the ledger result.
2. **`projects.created_by` and `project_events.triggered_by` are null.** No actor UUID is recorded, so the actor is identified only by the claim and the team state. This matches the current schema behaviour for Direct EXECUTE.
3. The claim status is called `COMPLETED`, not `COMMITTED`. This is a naming difference only.
4. Run/task binding exists only in local team-state JSON, not in PostgreSQL. It is bound to the database through the operation-key hash, which I recomputed and which matches.

There are no discrepancies in any expected field.

## 7. Verdict

**GO — NL2 final acceptance.** Every check passed:

- database identity
- Project identity and fields
- 22 steps, with 6–7 SKIPPED and PO/PR available
- one claim, one ledger row and one event in a single transaction
- operation key and scope hash recomputed independently and matching

No writes, cleanup or retries were performed. The Beta fixture, the Project and the claim history were left in place. Nothing was committed or pushed.

# CP12H.NL3 — Final Live Database Acceptance

Date: 2026-11-04 · Branch `feat/cp7-9-merchant-reliability` (uncommitted NL3 + NL3A changes on `96c3c0e`)

This was a read-only verification. Nothing was written, retried, recreated or cleaned up, and nothing was committed or pushed. Local state files were only read.

## 1. Database identity

All database reads used one session opened with `MerchantDatabaseClient(RepositoryConfig.from_env("test")).connection(read_only=True)`.

| Check | Expected | Actual |
|---|---|---|
| `current_database()` | `coding_agent_merchant_test` | `coding_agent_merchant_test` ✅ |
| `current_user` | `merchant_test` | `merchant_test` ✅ |
| `transaction_read_only` | `on` | `on` ✅ |

## 2. Project read-back

Exactly **1** row exists with id `ba5cc7ec-bd78-5582-84e2-46b16037444c`, and exactly 1 Project has the title `Beta NL3 Confirmation Test`. It is the only Project created after 07:00Z.

| Field | Expected | Actual |
|---|---|---|
| merchant | `NL2_LIVE_BETA` / `6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f` | same ✅ (Merchant "Beta Cinemas", version 1, unchanged) |
| title | Beta NL3 Confirmation Test | `Beta NL3 Confirmation Test` ✅ |
| project_type | OPENING_NEW_CINEMA | ✅ |
| workflow_variant | OPENING_NEW_CINEMA_STANDARD | ✅ (template `a3cc7546-…`, v1, 22 steps) |
| requires_procurement | false | `false` ✅ |
| status | PLANNED | `PLANNED` ✅, version 1, `started_at` and `completed_at` null |
| created_at | — | `2026-11-04 10:00:59.927255+00` |

**Steps.** There are 22 rows, all linked to template steps, with 22 step dependencies. Status counts are READY 1, PENDING 19, SKIPPED 2.

| # | Step | Template | Status |
|---|---|---|---|
| 1 | Draft or renew document | SEQUENTIAL | **READY** ✅ |
| 2–5 | Legal review, Accounting review, Send revision, Record Partner approval | — | PENDING |
| 6 | Create Purchase Request | CONDITIONAL, optional, `requires_procurement` | **SKIPPED** ✅ |
| 7 | Record Purchase Request number | CONDITIONAL, optional, `requires_procurement` | **SKIPPED** ✅ |
| 8–9 | Validate signing gate, Sign document | — | PENDING |
| 10 | Create Purchase Order | SEQUENTIAL, **required**, no condition | **PENDING** ✅ |
| 11 | Create Payment Request | SEQUENTIAL, **required**, no condition | **PENDING** ✅ |
| 12–22 | Production, UAT and Complete project | — | PENDING |

**Event.** Exactly one event references the Project, and no other event does: `71c25c54-0038-4d06-aee4-a3363dba7c87` `PROJECT_CREATED`. Its `new_values` are:

- `status=PLANNED`
- `step_count=22`
- `dependency_count=22`
- `requires_procurement=false`
- `workflow_variant=OPENING_NEW_CINEMA_STANDARD`
- `workflow_template_version_id=a3cc7546-…`

## 3. Trusted execution evidence

| Evidence | Value |
|---|---|
| Claim | `merchant-scope:v1:b34215e33ed57c97fe42a53db20795793b1cf74c11fd45bb0c58e2c56c53dbdb`, payload `9ad36169d9fc1267f0348dc9c5ba4c147e947ac3ff444505a8fbb7b491110f91`, attempt `9a75f3ad-219d-4187-af12-e9a486d626e6`, generation 1, **COMPLETED** |
| Ledger | Exactly one row for that key and payload: `{"command":"project create","execution_attempt_id":"9a75f3ad-…"}` |
| Team-state history (`team_state/841cb7d1-….json`) | run `0ea18bd8-b63d-4ca7-b2e5-2e81ba211116`, task `…:merchant-manager`, command `project create`, scope_hash `9ad36169…`, confirmation_hash `bc91746f…`, attempt `9a75f3ad-…`, **SUCCEEDED**. The teammate is now `IDLE_REUSABLE` and its result arrived by `sendmessage`. |
| Attempt id | The same in the claim, the ledger and the team-state history ✅ |
| Transaction | The Project, its steps, the event, the claim and the ledger row all share `10:00:59.927255+00`, one PostgreSQL transaction. This is supporting evidence only; identity is proven by the hashes below. |

### Independent hash recomputation

| Hash | Recomputed from | Result | Matches |
|---|---|---|---|
| Scope hash | `_direct_scope_hash(pending.operation.argv, "test")` | `9ad36169d9fc1267f0348dc9c5ba4c147e947ac3ff444505a8fbb7b491110f91` | claim payload ✅, ledger payload ✅, team-state `scope_hash` ✅, envelope `merchant_scope.scope_hash` ✅ |
| Operation key | `sha256({owner_session_id: 841cb7d1-…, teammate_name: merchant-manager, run_id: 0ea18bd8-…, task_id: 0ea18bd8-…:merchant-manager, command: project create, scope_hash})` | `merchant-scope:v1:b34215e33ed57c97fe42a53db20795793b1cf74c11fd45bb0c58e2c56c53dbdb` | claim key ✅, ledger key ✅ |
| Expected basis | the pending operation | `b6afd2881b1645b77d1ea70f354a747c84b50e5756b4098cb81024373019a395` | brief ✅ |

### No second attempt or unexpected mutation

Compared with the RC1 baseline snapshot (taken before NL3), the whole-database count changes are exactly one creation:

| Table | Change |
|---|---|
| projects | +1 |
| project_steps | +22 |
| project_step_dependencies | +22 |
| project_events | +1 |
| merchant_execution_claims | +1 |
| merchant_execution_ledger | +1 |
| every other table, merchants included | 0 |

All 18 claims are `COMPLETED`, with no EXECUTING or REVOKED claims and no second claim for this payload.

## 4. Conversational confirmation evidence

The evidence comes from three sources:

- the pending store `.claude/runtime/841cb7d1-….pending_project.json` (1 record)
- the team state
- the lead transcript `841cb7d1-….jsonl`

| Requirement | Evidence | Result |
|---|---|---|
| The record came from verified preview output | The record's `source_run_id`/`source_task_id` (`0f2f9ccc-…`) equal the team-state `project_preview_evidence` run and task. That evidence is **`status: VERIFIED`**, `outcome: READY_FOR_CONFIRMATION`, `database_target: test`, and its `requested_operation` is **byte-equal** to the record's operation. The operation passes `validate_requested_operation` (canonical argv and confirmation command). | ✅ |
| Exact expected Project | The record's `project_id` is `ba5cc7ec-…`. The user typed the id prefix `ba5cc7ec`. Merchant `NL2_LIVE_BETA` matched by **NAME**, so no candidate confirmation was needed. | ✅ |
| Session ownership | The record's `owner_session_id` and the store file are both `841cb7d1-…`, the session of the confirming prompt. | ✅ |
| Consumed once | `status: CONFIRMED`, `confirmed_run_id: 0ea18bd8-…`, which equals the envelope `run_id`, the team-state run and the operation-key run. There is one record and one claim. | ✅ |
| Within expiry | created 09:46:58.367Z, confirmed 09:59:59.320Z (781 s), expiry 10:01:58.367Z (900 s) | ✅ |
| User approval, not model or teammate | Transcript row 80 is the **`origin: human`** prompt `/solve xác nhận tạo ba5cc7ec`. Row 83 is the hook's own `systemMessage`: "Confirmed Project create 'Beta NL3 Confirmation Test' for Merchant NL2_LIVE_BETA (project_id ba5cc7ec-…) on the test database. It runs once now." Row 84 is the `UserPromptSubmit` envelope with `raw_request: "xác nhận tạo ba5cc7ec"` and `conversational_confirmation`. None of the 5 teammate messages contains a confirmation phrase. The lead used only Agent ×1 (preview spawn), SendMessage ×1 (reuse), Read ×2 and ToolSearch ×1, with **no scheduling tool**. | ✅ |
| No stale or mismatched operation | The envelope's `merchant_scope.argv` is byte-equal to the record argv, with target `test`. The preview basis was rechecked by the existing preflight and transaction, and the commit succeeded with basis `b6afd288…`. | ✅ |
| Existing Direct EXECUTE pipeline | Envelope `operations: [merchant_execute]`, `selected_agents: [merchant-manager]`. Then the teammate's `MERCHANT_EXECUTE_REQUEST_JSON` (row 134), the verified pane `27260:%9` bound to the task, the scope execution history, the operation-key claim and ledger, and the final `EXECUTE_SUCCESS` report (row 139) and idle release (row 145). | ✅ |

### What cannot be independently proven after the fact

- **The confirmation run's state file** (`.claude/runtime/841cb7d1-….json`) no longer exists; run state is cleared when a run ends. Its handoff record, reservation and spent-authority fields cannot be read back. Their effects are proven by the claim, the ledger, the team-state history and the matching hashes.
- **Pane verification during the *preview* run.** The teammate record now holds the confirm task's pane binding. The preview's pane check is shown only indirectly: the evidence is `VERIFIED`, which the capture code sets only after `verified_teammate_pane` succeeds.
- **Approval source.** The `UserPromptSubmit` payload itself carries no origin flag. Human authorship is shown by the transcript's `origin: human` on row 80.

## 5. Regression preservation (NL2 Project `30fffeaf-e6b5-5119-b078-52c934e1821e`)

I compared each section field by field with the RC1 baseline snapshot:

| Item | Result |
|---|---|
| Merchant `NL2_LIVE_BETA` | unchanged |
| Project `30fffeaf-…` (all columns) | unchanged |
| Its 22 steps | unchanged |
| Its 22 dependencies | unchanged |
| Its `PROJECT_CREATED` event | unchanged |
| Its claim `merchant-scope:v1:275d6482…` and the other 16 historical claims (all 17 baseline claims) | unchanged |
| Its ledger row | unchanged |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` (`merchant_direct_handoff.py:63`) |

## 6. Discrepancies and limitations

There are no discrepancies in any expected field, hash or count.

Observations, none of them blocking:

1. `projects.created_by` and `project_events.triggered_by` are null, so no actor UUID is recorded. This is the same as NL2.
2. The ledger `result` has no `project_id`. The ledger is tied to the Project by the operation key, the scope hash and the transaction.
3. The run committed at 10:00:59, about 60 s before the record would have expired. Expiry limits *confirmation* only, and the confirmation was at 09:59:59.
4. The lowercase `xác nhận tạo` with an id prefix was accepted, as designed (accent and case folded, whole prompt).
5. The partial-proof items in §4.

## 7. Verdict

**GO — NL3 final acceptance.** Every check passed:

- database identity
- the Project and all 22 step states, with PR steps 6–7 SKIPPED and Purchase Order and Payment Request (10–11) required and PENDING
- one event, one COMPLETED claim and one ledger row
- independently recomputed scope hash and operation key
- a human-typed, single-use, in-expiry, session-owned confirmation of a VERIFIED preview, executed through the existing Direct EXECUTE pipeline
- no extra mutation
- the NL2 Project preserved

Runtime (production) Direct EXECUTE remains disabled.

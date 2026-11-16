# CP12H.NL4D1 — Evidence & Approval Domain Readiness Audit

Baseline `b0860a7a30e8c0b655d369dcc8309382a46734e3`, branch `feat/cp7-9-merchant-reliability`. Date 2026-11-09.

This is an investigation only:
- no code, schema or database change;
- not committed, not pushed;
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

Every rule below is quoted from the code or the schema; nothing is invented. Where the domain is silent, this report says **"not defined"** and lists it as a decision for the owner.

## 1. Existing domain capability map

### 1.1 Entities and layers

| Concern | Domain engine (pure) | Repository (locks + event) | CLI command | Write adapter | Direct EXECUTE test mode |
|---|---|---|---|---|---|
| Document revision | `document_engine.propose_document_revision` | `MerchantDocumentRepository.create_revision` | `document revision-create <project_id> --type --content-hash [--effective-date --expiry-date --created-by --revision-id]` | `create_revision` | **no** |
| Approval | `approval_engine.propose_document_approval` | `MerchantApprovalRepository.record_approval` | `document approve <revision_id> --role {LEGAL,ACCOUNTING,PARTNER} --status {PENDING,APPROVED,REJECTED} [--expected-status --occurred-at --acted-by --notes --approval-id]` | `approve_document` | **no** |
| Signing | `signing_engine.propose_document_signing` (runs the signing gate) | `MerchantSigningRepository.sign_document` | **none** | **none** | **no** |
| Procurement (PR / PO / Payment Request) | `procurement_engine.propose_procurement_mutation` | `MerchantProcurementRepository.record_procurement` | `procurement update <project_id> --type {PURCHASE_REQUEST,PURCHASE_ORDER,PAYMENT_REQUEST} [--external-id --status --expected-version --document-type --triggered-by --procurement-id]` | `update_procurement` | **no** |
| Step transition | `engine.propose_step_transition` (+ gates) | `MerchantStepTransitionRepository.transition_step` | `step update` | `update_step` | **yes** (NL4C; confirmed preview only) |
| Project transition / completion | `project_engine.propose_project_transition` | `MerchantProjectTransitionRepository` | `project update` | `update_project` | **no** |

### 1.2 Reads and NL support

**Read commands:**

| Command | Status |
|---|---|
| `document resolve --project-id/--merchant-id --query` | exists, but not in the NL routing |
| `project show` | full detail including revisions, approvals and procurement; `content_hash` and `notes` are redacted |
| `project history` | events |
| `project blockers` | checker alert types `BLOCKED`, `MISSING_GATE` |
| `project status` (NL4A) | evidence **counts** only: number of revisions, approvals and procurement records |
| `step preview` (NL4B) | gate result for step 5 and step 8 |

**Checker alert codes** (`checker.py`), which already describe missing evidence:
- `MISSING_DOCUMENT_REVISION`, `UNSIGNED_DOCUMENT`, `INVALID_SIGNED_DOCUMENT`, `MISSING_PURCHASE_REQUEST`, `MISSING_GATE`, `INCOMPLETE_MANUAL_GATE`;
- for reused documents: `MISSING_REUSED_DOCUMENT`, `MISSING_REUSED_DOCUMENT_EVIDENCE`, `UNSIGNED_REUSED_DOCUMENT`, `SUPERSEDED_REUSED_DOCUMENT`, `EXPIRED_REUSED_DOCUMENT`;
- `DOCUMENT_NOT_EFFECTIVE`, `INVALID_PAYMENT_PERIOD`.

**NL parser (`project_nl`):** kinds are PROJECT_CREATE, MERCHANT_CREATE, PROJECT_STATUS, PROJECT_LIST, STEP_UPDATE and MIXED. **There is no evidence, approval or procurement kind.**

### 1.3 Execution evidence (shared)

- `attempt_evidence.evidence_bound_repository` wraps **any** single-transaction repository write: the claim and the ledger are inserted, the mutation runs, then the ledger result is written and the claim completed, all in one transaction. A duplicate operation key is refused before mutation.
- `resolve_attempt` and fences are generic. `step_update_receipt` and `recover_step_update_receipts` are Step-specific (they reconcile a STEP event); evidence writes would need their own receipt reconciler (DOCUMENT/APPROVAL/PROCUREMENT events).
- Each evidence repository inserts a `project_events` row in the same transaction. Event types:
  - `DOCUMENT_REVISION_CREATED` (and supersede);
  - `DOCUMENT_APPROVAL_REQUESTED`, `DOCUMENT_APPROVED`, `DOCUMENT_REJECTED`;
  - `DOCUMENT_SIGNED`;
  - procurement events.

## 2. Workflow: OPENING_NEW_CINEMA_STANDARD (template v1)

### 2.1 The 22 steps

| # | Key | Type | Name | Branch | Notes |
|---|---|---|---|---|---|
| 1 | `draft_document` | SEQUENTIAL | Draft or renew document | document_branch | |
| 2 | `legal_review` | PARALLEL_BRANCH | Legal review | document_review_branch | no gate |
| 3 | `accounting_review` | PARALLEL_BRANCH | Accounting review | document_review_branch | no gate |
| 4 | `send_reviewed_revision_to_partner` | SEQUENTIAL | Send reviewed revision to Partner | document_branch | |
| 5 | `record_partner_approval` | **APPROVAL_GATE** | Record Partner approval | document_branch | DB gate `RECORD PARTNER APPROVAL` |
| 6 | `create_purchase_request` | CONDITIONAL, optional | Create Purchase Request | procurement_branch | `requires_procurement` |
| 7 | `record_purchase_request_number` | CONDITIONAL, optional | Record Purchase Request number | procurement_branch | `requires_procurement` |
| 8 | `validate_signing_gate` | **APPROVAL_GATE** | Validate signing gate | document_branch | DB gate `VALIDATE SIGNING GATE` |
| 9 | `sign_document` | SEQUENTIAL | Sign document | document_branch | no gate |
| 10 | `create_purchase_order` | SEQUENTIAL | Create Purchase Order | payment_branch | no gate |
| 11 | `create_payment_request` | SEQUENTIAL | Create Payment Request | payment_branch | no gate |
| 12 | `create_production_agent` | PARALLEL_BRANCH | Create Production agent | production_branch | |
| 13 | `configure_production_service_list` | PARALLEL_BRANCH | Configure Production service list | production_branch | |
| 14 | `send_production_information` | PARALLEL_BRANCH | Send Production information to Partner | production_branch | |
| 15 | `configure_uat_agent` | PARALLEL_BRANCH | Configure UAT agent | uat_branch | |
| 16 | `configure_uat_product` | PARALLEL_BRANCH | Configure UAT Product ID or orderGroupID | uat_branch | |
| 17 | `configure_uat_identity` | PARALLEL_BRANCH | Configure UAT MID or partnerCode | uat_branch | |
| 18 | `send_uat_information` | PARALLEL_BRANCH | Send UAT information to Partner | uat_branch | |
| 19 | `create_uat_jira_ticket` | PARALLEL_BRANCH | Create UAT JIRA ticket | uat_branch | |
| 20 | `run_uat_test` | PARALLEL_BRANCH | Run UAT test | uat_branch | |
| 21 | `complete_uat_acceptance` | **APPROVAL_GATE** | Complete UAT acceptance | uat_branch | **no DB evaluator** |
| 22 | `complete_project` | **APPROVAL_GATE** | Complete project | — | **no DB evaluator** |

Step UUIDs are deterministic per Project (`template_uuid` / project factory). The live acceptance Project's step 1, for example, is `98dc77cf-39d2-5f3f-b3a3-9e8e762d39c7`.

### 2.2 Dependency diagram (24 template edges, all `MUST_COMPLETE_BEFORE`)

```text
                 ┌─> 2 Legal review ─────┐
1 Draft/renew ───┤                       ├─> 4 Send to Partner ─> 5 [GATE] Partner approval ─┐
                 └─> 3 Accounting review ┘                                                   │
                                                                                             ▼
6 Create PR (cond.) ─> 7 Record PR number (cond.) ─────────────────────────────> 8 [GATE] Signing gate
                                                                                             │
                                                                                             ▼
                                                                                      9 Sign document
                         ┌───────────────────────────────────────────────────────────────────┤
                         ▼                                       ▼                           ▼
              10 Create PO ─> 11 Create Payment Req.   12 Prod agent ─> 13 Prod services   15 UAT agent ─> 16 UAT product ─> 17 UAT identity
                         │                                       └─> 14 Send Prod info       ─> 18 Send UAT info ─> 19 UAT JIRA ─> 20 Run UAT
                         │                                                   │                                                        │
                         │                                                   │                         21 [GATE] UAT acceptance <─────┘
                         └──────────────── 11 ──────────────> 22 [GATE] Complete project <── 14 ──────────── 21
```

**Variants.** Readiness requires every **transitive** predecessor to be COMPLETED (`dependencies.py`); SKIPPED does **not** satisfy a dependency.
- **No procurement** (`requires_procurement = false`): the Project factory creates steps 6 and 7 as SKIPPED and **omits the edges 6→7 and 7→8**, leaving 22 stored edges (verified read-only on `8dd4c68d-…`: 22 edges, with 5→8 and no 7→8).
- **With procurement:** all 24 edges are stored. Steps 6 → 7 must be COMPLETED before 8.

**Parallel structure:**
- 2 ∥ 3 (review branch);
- after 9, three independent branches: payment (10→11), production (12→13→14) and UAT (15→…→21);
- they join at 22.

### 2.3 Transition conditions (the code's own rules)

- **Status machine:** `validate_step_transition` (no implicit reopen). The guarded UPDATE checks `status` and `version`.
- **Dependencies:** apply to READY, IN_PROGRESS and COMPLETED. All transitive predecessors must be COMPLETED.
- **Gates:** any `APPROVAL_GATE` step is gate-checked on **every** transition, including PENDING→READY (observed in NL4C2B-PREP: step 5 could not even become READY without a revision).

| Step | Gate | Rule |
|---|---|---|
| 5 | `evaluate_approval_gate(required_roles=("PARTNER",))` | The **latest non-superseded revision** (optionally of one `document_type`) must have a PARTNER approval with `approval_status = APPROVED` and `approved_at` set. No revision gives `MISSING_DOCUMENT_REVISION`; otherwise `MISSING_REQUIRED_APPROVALS`. |
| 8 | `evaluate_signing_gate` | The same approval gate with **LEGAL, ACCOUNTING and PARTNER** all APPROVED on the latest revision. If `requires_procurement`, a PURCHASE_REQUEST record with a non-blank `external_id` is also required (`MISSING_PURCHASE_REQUEST`). The latest revision must not already be signed (`DOCUMENT_ALREADY_SIGNED`). |
| 21, 22 | none | No database evaluator: `gate_result` is None, so `WorkflowGateNotMetError("A gate result is required for this transition")`. **These steps can never transition through the CLI.** |

- **Merchant activation** happens on a step transition only for the canonical `INTEGRATION_NEW_MERCHANT_STANDARD` activation step to COMPLETED; never in this template.
- **Project completion** (`project_engine._validate_project_completion`) requires every step to be COMPLETED, SKIPPED or SUPERSEDED. Because steps 21 and 22 can't move, **an OPENING_NEW_CINEMA_STANDARD Project cannot be completed through the CLI today.**

## 3. Evidence and approval requirements

| Evidence | Rule (from the engines) |
|---|---|
| Document revision | Per `document_type` (`^[A-Z][A-Z0-9_]{0,99}$`, for example `CONTRACT`), `revision_number` increments. A new revision supersedes the active one of that type (`superseded_by`). At most one active revision per type, and it must be the highest number. `content_hash` is required free text; it is **not** a stored file and not checked against one. `expiry_date` must be after `effective_date`. Refused for COMPLETED or CANCELLED Projects. |
| Approval | One row per (revision, role) (`document_approvals_role_unique`). Only on the **latest active, unsigned** revision. Without a row, any status may be inserted. With a row, `--expected-status` is required and must match. PENDING → APPROVED or REJECTED only. **APPROVED and REJECTED are final** (`ApprovalFinalizedError`). |
| Signing | Only the latest active unsigned revision. The full signing gate (above) must be met. Sets `signed` and `signed_at`, with a `DOCUMENT_SIGNED` event. |
| Purchase Request | One record per (project, type) (`procurement_records_project_type_unique_idx`). No prerequisite. |
| Purchase Order | Needs a **signed** active latest revision. With procurement, it also needs a recorded PR `external_id`. |
| Payment Request | Needs a signed revision and a recorded PO `external_id`. |
| Step 9 "Sign document", step 10 "Create PO", step 11 "Create Payment Request" | **No gate.** Completing them does **not** check for a signature, PO or Payment Request record. The domain does not link these steps to their evidence. |

## 4. Gap analysis

### 4.1 NL capability matrix (current state)

Legend: ✅ supported · ◐ partial or indirect · ❌ not supported.

| Business action | Read-only query | Preview | Trusted confirmation | Test-only execution | Durable event / audit | Runtime execution |
|---|---|---|---|---|---|---|
| Register document revision ("upload") | ◐ `project show` / `document resolve` (no NL) | ❌ | ❌ | ❌ (CLI exists, not in test mode) | ✅ repository event | ❌ (disabled) |
| Submit Legal review (LEGAL approval) | ◐ `project show` | ❌ | ❌ | ❌ | ✅ | ❌ |
| Submit Accounting review (ACCOUNTING approval) | ◐ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Record Partner approval (PARTNER approval) | ◐; step 5 gate visible in `step preview` | ❌ | ❌ | ❌ | ✅ | ❌ |
| Update approval status (PENDING → APPROVED/REJECTED) | ◐ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Register evidence (generic) | ◐ evidence counts in `project status` | ❌ | ❌ | ❌ | ◐ only revision/approval/procurement exist; **no generic evidence entity** | ❌ |
| Sign document | ◐ `signed` flag in `project show` | ❌ | ❌ | ❌ (**no CLI / adapter**) | ✅ repository event | ❌ (also needs a DB grant) |
| Attach Purchase Order reference | ◐ | ❌ | ❌ | ❌ | ✅ | ❌; **blocked in practice**: needs a signed revision, and signing is unreachable |
| Attach Payment Request reference | ◐ | ❌ | ❌ | ❌ | ✅ | ❌; same, plus needs a PO |
| Attach Purchase Request number | ◐ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Complete a step that requires evidence (5, 8) | ✅ `step preview` gate | ✅ `step preview` | ✅ NL4C | ✅ NL4C | ✅ | ❌ |
| Complete step 21 or 22 | ✅ (reported `NO_DATABASE_GATE_EVALUATOR`) | ◐ always BLOCKED | ❌ | ❌ (**impossible**) | — | ❌ |
| Query missing documents and approvals | ◐ `project blockers` and checker codes; `step preview` per gate; **no NL "what's missing" view** | — | — | — | — | — |

### 4.2 Gaps, by category

**Missing NL / read (no domain change needed):**

| ID | Gap |
|---|---|
| G1 | No NL kind or read for evidence and approval status per gate ("Còn thiếu phê duyệt nào?"). |
| G2 | `document resolve` is not in NL routing. |
| G3 | `project status` gives counts, not the missing roles or documents per gate. |

**Missing write paths (domain exists, pipeline does not):**

| ID | Gap |
|---|---|
| G4 | No preview, `requested_operation`, basis hash, pending kind or receipt for `document revision-create`, `document approve` or `procurement update`. |
| G5 | None of those three commands is in `TEST_MODE_COMMANDS`. |

**Domain gaps (need an owner decision; do not invent):**

| ID | Gap |
|---|---|
| D1 | **Signing has no CLI command or write adapter.** `MerchantSigningRepository` is tested but unreachable. The runtime role `merchant_app` also has **no UPDATE grant** on `document_revisions.signed/signed_at` (only `superseded_by`), so runtime signing would also need a migration. Consequence: PO and Payment Request records can never be created through the CLI. |
| D2 | **Steps 21 "Complete UAT acceptance" and 22 "Complete project" have no database gate evaluator**, so they can never transition and an OPENING_NEW_CINEMA_STANDARD Project can never complete through the CLI. What evidence satisfies them is **not defined**. |
| D3 | Steps 9, 10 and 11 are not linked to their evidence (signature, PO, Payment Request). Whether completing them should require that evidence is **not defined**. |
| D4 | There is no generic "evidence" entity: no file, URL, storage reference or MIME type, only `content_hash`. "Upload" means registering a hash. Real file storage is **not defined**. |
| D5 | Legal and Accounting **review** are plain steps 2–3, while Legal and Accounting **approvals** are separate revision records required only at step 8. Whether completing step 2 or 3 should require the matching approval is **not defined**. |

## 5. Security risks

| # | Risk | Current state | Implication for NL4D |
|---|---|---|---|
| S1 | **Approval actor authorization** | `--acted-by` / `approved_by` is an optional, unverified UUID. Anyone holding a write scope can record a PARTNER, LEGAL or ACCOUNTING decision. No actor-to-role binding exists. | An NL "record Partner approval" confirmed by the operator is the operator attesting on the Partner's behalf. Needs an explicit policy decision (who may attest which role; must `acted_by` be the session user?) **before** any approval write is enabled. |
| S2 | **Approvals are irreversible** | APPROVED and REJECTED are final; the remedy is a new revision (which supersedes and voids old approvals). | Confirmation must state finality. A mistaken REJECTED can only be undone by re-issuing the document. This raises the bar above Step Update. |
| S3 | **Revision identity** | A revision is identified by UUID (client-suppliable `--revision-id`) or by type and number. `content_hash` is unverified free text, redacted in reads. | The preview must bind the exact revision UUID, the latest-active status and the hash. A swapped or superseded revision must refuse, as the approval engine already does. |
| S4 | **Concurrency** | All evidence writers lock Project `FOR UPDATE` → revisions → approvals → procurement (consistent order; NL4C2B-PREP tests). Approval updates need `--expected-status`; procurement uses `--expected-version`. **Revision creation has no expected-version**: it supersedes whatever is active at commit time. | A confirmed revision-create must re-judge a basis (active revision ID and number) in the transaction, like NL4C1's precondition, or a concurrent revision would be silently superseded. |
| S5 | **Atomicity** | Each repository write is one transaction with its event; `evidence_bound_repository` adds the claim and ledger to the same transaction. | Reusable unchanged. |
| S6 | **Audit immutability** | `merchant_app` has INSERT-only on `project_events` (no UPDATE or DELETE). `document_approvals` and `procurement_records` have table-wide `UPDATE` for `merchant_app`, so immutability of past decisions rests on the engines, not on privileges. | Accept for the test database; consider column-level grants before any runtime enablement. |
| S7 | **Idempotency / replay** | Claim and ledger keys are per (owner, teammate, run, task, scope). Client-supplied `--revision-id` / `--approval-id` / `--procurement-id` give natural idempotency keys. | Prefer server-generated, preview-bound IDs inside `requested_operation`, as Project create does. |
| S8 | **Direct EXECUTE boundary** | Runtime is disabled; test mode allows `merchant create`, `project create` and `step update` only. A typed Step scope is refused. | Every new command needs the NL4C pattern: no typed scope, a confirmed pending record of its own kind, a basis re-judged before spend and in the transaction, and a receipt reconciler. |
| S9 | **Sensitive fields** | `content_hash` and `notes` are in `SENSITIVE_FIELD_NAMES` (redacted in reads and confirmations). | A preview must not echo them in clear; bind them by hash in the basis. |

**What can reuse the NL4C confirmation architecture safely (most to least):**
1. **Procurement update** (has an expected version; single row per type).
2. **Approval PENDING → final** (has an expected status). Gated by S1/S2 policy.
3. **Document revision-create.** Needs a new basis on the active revision (S4).
4. **Signing.** Needs D1 (a new command and adapter, plus a grant for runtime).

## 6. Recommended NL4D checkpoint sequence (adjusted to the findings)

| Checkpoint | Scope | Writes? | Needs an owner decision first? |
|---|---|---|---|
| **NL4D2 — Read-only evidence and approval discovery** | 1. A `project evidence --request` (or `project status` extension) that, per document type, lists the latest active revision (ID, number, signed, effective and expiry dates, hash redacted), approvals per role and status, procurement records, and **per gate** (steps 5, 8) the exact missing roles and records, using `resolve_database_gate` / `evaluate_*_gate` and checker codes. 2. Flag steps 21 and 22 as "no evaluator". 3. NL kind for questions ("Project X còn thiếu phê duyệt nào?"), delivered like NL4A (`MERCHANT_…_JSON` capture). | none | no |
| **NL4D3 — Evidence previews** | 1. `approval preview`, `procurement preview` and `revision preview` from NL. 2. Each binds Merchant, Project, revision, role and type exactly, re-runs the engine on a read snapshot, and returns a NOT_AUTHORIZED `requested_operation` with a basis hash (revision row, approvals, procurement, Project version). 3. Ambiguous or partial matches never bind. 4. States finality for approvals (S2). | none | S1 wording only |
| **NL4D-DEC — Domain decisions (owner)** | Decide S1 (who may attest LEGAL, ACCOUNTING and PARTNER; `acted_by` binding), D1 (signing command, and its runtime grant), D2 (evaluators for steps 21 and 22), D3/D5 (whether completing steps 2, 3, 9, 10 and 11 requires evidence), D4 (file storage or hash only). | none | **yes** |
| **NL4D4 — Trusted test-only procurement write** | 1. `procurement update` only: a pending kind `procurement`, a confirmation phrase, a test-mode allowlist, a preflight requiring the confirmed record, an in-transaction basis precondition, and a procurement receipt reconciler. 2. Purchase Request first, since it has no signing prerequisite. | test DB | after NL4D-DEC (S1 not needed) |
| **NL4D5 — Approval and revision confirmation and execution** | 1. `document approve` (one role per confirmation; final statuses called out). 2. Then `document revision-create` (basis = active revision). 3. Same NL4C pattern, a receipt per kind, approval-concurrency tests. | test DB | S1, S2 |
| **NL4D5b — Signing (if D1 is approved)** | `document sign` CLI and adapter over the existing engine/repository, plus a migration grant for runtime (runtime stays disabled). | test DB | D1 |
| **NL4D6 — Lifecycle acceptance** | On one disposable test Project, user-confirmed only: revision → LEGAL/ACCOUNTING/PARTNER approvals → step 5 → (PR if procurement) → step 8 → sign → PO → Payment Request, with independent PostgreSQL verification per write. Steps 21 and 22 only if D2 is resolved. | test DB | all above |

## 7. Acceptance criteria

**NL4D2:**
1. Read-only: a fake reader refuses non-read APIs, and a PostgreSQL snapshot is identical before and after.
2. For a test Project with a known revision and approval set, the output matches `evaluate_approval_gate` / `evaluate_signing_gate` exactly (missing roles, `MISSING_DOCUMENT_REVISION`, `MISSING_PURCHASE_REQUEST`, `DOCUMENT_ALREADY_SIGNED`) for both procurement variants.
3. Steps 21 and 22 are reported as `NO_DATABASE_GATE_EVALUATOR`, never as satisfiable.
4. `content_hash` and `notes` are never shown in clear.
5. Delivered only as the CLI-captured object (policy-gate verified); no confirmation, argv or scope is offered.
6. NL routing: evidence questions route to the read and never to `merchant_execute`; the NL1–NL4C suites are unchanged.

**NL4D3 onwards:**
- every NL4C guarantee per new kind, plus finality messaging (S2) and a basis on the active revision (S4);
- separate pending stores; typed scope refused;
- runtime stays disabled.

## 8. Verification performed (read-only)

**Code inspection:**
- templates, dependencies, `engine`, `gates`, `gate_resolver`, the `document`/`approval`/`signing`/`procurement`/`project` engines;
- the evidence repositories, CLI parser and contract, completeness and write adapters;
- `checker`, `read_commands`, `project_status`;
- migrations 0001 and 0003 (grants and unique indexes).

**Database:**
- read-only queries on `coding_agent_merchant_test` (dependency edges of `8dd4c68d-…` and per-Project edge counts: 22 / 22 / 22 / 26; evidence table columns).
- The integrity hash was `ba419be9d17a7a6719f1ca864ff5bdc1fe01848a7ad65a857e023715d028a319` before and after.

**Tests, run one after another, all passed:**

| Suite | Result |
|---|---|
| approval engine | 23 |
| approval repository | 15 |
| blocker gate calculation | 25 |
| checker | 20 |
| dependencies | 31 |
| document engine | 17 |
| document repository | 13 |
| document revision resolver | 40 |
| gate resolver | 13 |
| gates | 28 |
| procurement engine | 23 |
| procurement repository | 16 |
| project engine | 39 |
| signing engine | 19 |
| signing repository | 14 |
| workflow templates | 26 |
| engine | 33 |
| NL4C2B approval concurrency (PostgreSQL) | 6 |

The opt-in `*_live` suites were not run.

**State:**
- No database mutation, no schema change, no production access.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.
- Working tree clean apart from this report. HEAD `b0860a7`.
- NL2/NL3 acceptance Projects and the NL4C2B accepted step are unchanged (hash unchanged).

## 9. GO/NO-GO

- **NL4D2 (read-only evidence and approval discovery):** **GO.** It needs no schema change, no new write and no owner decision, and it reuses existing gate evaluators and checker codes.
- **NL4D4 / NL4D5 writes:** **NO-GO until the NL4D-DEC decisions (S1, S2 wording, D1–D5) are made.** In particular, no approval may be recorded on someone's behalf until the actor-attestation policy is decided.
- **Completing an OPENING_NEW_CINEMA_STANDARD Project end to end:** **NO-GO** until D2 (evaluators for steps 21 and 22) and D1 (signing) are resolved.
- **Runtime execution of any of these:** **NO-GO** (disabled; signing would also need a grant migration).

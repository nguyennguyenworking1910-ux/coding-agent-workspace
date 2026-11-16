# CP12H.NL4D-SIMPLIFY — User-Confirmation-First Local MVP Policy

Branch `feat/cp7-9-merchant-reliability`, HEAD `c7f0933`. Date 2026-11-12.

**Scope:** policy and design only.
- No code, schema, grant or data change.
- Nothing committed or pushed.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

**Working tree:** NL4D5A1b (migration 008, its tests and its report) is still uncommitted. Its final acceptance was stopped by the owner before it ran, and this document does not change it.

**Product direction (owner, 2026-11-12):**

```
natural-language request
  -> exact read-only preview
  -> explicit user confirmation (/solve Xác nhận …)
  -> trusted atomic execution (claim + ledger + mutation + event, one transaction)
  -> PostgreSQL audit and receipt
```

The **confirmation** is the authority for an ordinary approval, signing or status change. Uploading evidence becomes optional. The single local operator (DEC-A0) is the recorder of every action. The system records what that operator confirms, and never claims more than that.

**Sources read:**
- `cp12h_nl4d_decision_register.md` and `cp12h_nl4d5a_document_revision_design.md`;
- the NL4D5A1b report and migration 008;
- `gates.py`, `gate_resolver.py` and `engine.py` (`_validate_gate`);
- `transition_repository.transition_step` and `step_preview._gate`;
- `approval_engine`, `signing_engine` and `procurement_engine._require_signed_document`;
- `workflow_templates.py`;
- `evidence_preview.py`;
- `cli_contract.WRITE_COMMANDS` and `merchant_direct_handoff.TEST_MODE_COMMANDS`.

---

## 1. Current restrictions (facts)

### 1.1 Where the workflow is blocked today

| # | Restriction | Where | Effect |
|---|---|---|---|
| R1 | An APPROVAL_GATE Step **without a database evaluator** can never complete. `transition_step` forces `gate_required` but passes no gate result, and `_validate_gate` refuses that. | `gate_resolver.DATABASE_VERIFIABLE_GATE_NAMES` (only "Record Partner approval" and "Validate signing gate"); `step_preview._gate` reports `NO_DATABASE_GATE_EVALUATOR` | **No Project of any template can complete.** The blocked Steps are listed below this table. |
| R2 | An approval can be recorded only on the **latest active, unsigned document revision**, and a revision needs a `content_hash`. | `approval_engine._require_latest_active_revision`; `document_engine` | Before approving, the user must create a revision. NL4D5A planned to make that revision a managed file upload. |
| R3 | No approval write is reachable: `document approve` is not in `TEST_MODE_COMMANDS`, and the preview ends `POLICY_UNDECIDED` (`APPROVAL_ATTESTATION_POLICY_UNDECIDED`). | `evidence_preview._approval`; `merchant_direct_handoff` | Steps gated on approvals (Partner approval, signing gate) cannot be satisfied. |
| R4 | Signing has no CLI command, write adapter or confirmation flow. | `signing_engine`, `MerchantSigningRepository.sign_document` | The signing gate cannot be passed, so Purchase Orders and Payment Requests are blocked. |
| R5 | A Purchase Order and a Payment Request need a **signed** latest revision, and a PO number for the Payment Request. Only the Purchase Request path is enabled. | `procurement_engine._require_signed_document`; NL4D4A | PO and Payment Request cannot be recorded. |
| R6 | The approval engine uses one value for both the approver and the recorder: `acted_by` becomes both `approved_by` and the event's `triggered_by`. | `approval_engine.propose_document_approval` | Recording the operator would falsely store them as the approver. |

**Steps blocked by R1, all APPROVAL_GATE Steps with no evaluator:**

| Template | Blocked Steps |
|---|---|
| `OPENING_NEW_CINEMA_STANDARD` | Complete UAT acceptance; Complete project |
| `INTEGRATION_NEW_MERCHANT_STANDARD` | Validate Master Merchant identity; Complete UAT acceptance; Activate Merchant; Complete project |
| `MEDIA_TOP_UP_NEW_DOCUMENT` | Close payment period |
| `MEDIA_TOP_UP_EXISTING_DOCUMENT` | Validate existing signed document; Close payment period |

### 1.2 Proposed (not yet approved) restrictions that would add work

These are PROPOSED in the decision register and not implemented:

| Item | What it would require |
|---|---|
| **DEC-S1a/b** | a per-role operator mapping, and **at least two distinct operators** across LEGAL, ACCOUNTING and PARTNER |
| **DEC-S2a/b** | an `approval_attestations` table, with **evidence required** for APPROVED and REJECTED (a managed file for PARTNER) |
| **DEC-D1a/b** | a `document_signatures` table plus an upload of the **signed file** |
| **DEC-G1a–c** | new evidence gates on Steps 2, 3, 9, 10 and 11, and a new template version |
| **DEC-G2a** | a `UAT_ACCEPTANCE` document revision with a PARTNER approval and evidence |

### 1.3 Classification of every rule

| Rule | Class | Simplified MVP |
|---|---|---|
| Claim, ledger, mutation and event in one transaction; fencing; UNCERTAIN never retried | Technical integrity protection | **Keep** |
| Preview → pending record → own-prompt confirmation; typed scope refused; single use; 15 minutes | Technical integrity protection (this is the authority) | **Keep** |
| Basis hash re-judged in the preflight and inside the transaction | Technical integrity protection | **Keep** |
| Trusted operator from local configuration (DEC-A0) | Technical integrity protection (attribution) | **Keep** |
| Step dependency readiness (`evaluate_dependency_readiness`) | Essential workflow dependency | **Keep** |
| Approval on the latest active unsigned revision; one row per (revision, role); APPROVED and REJECTED final | Essential workflow dependency (what is approved) | **Keep**, but the revision may be metadata-only (§2) |
| Signing gate: LEGAL, ACCOUNTING and PARTNER APPROVED (+ a Purchase Request when procurement is required) | Essential workflow dependency | **Keep**: each approval is one cheap confirmation |
| PO needs a signed revision; Payment Request needs the PO | Essential workflow dependency | **Keep** |
| Partner-approval gate (Step "Record Partner approval") | Essential workflow dependency | **Keep** |
| Unique `(merchant_id, procurement_type, reference)`; no reference replacement (P1a, P1c) | Technical integrity protection | **Keep** |
| Migration 008 constraints (SHA-256 format, derived key, uniqueness, immutability, MANAGED ⇔ file) | Technical integrity protection | **Keep, unchanged** |
| DEC-D4f: legacy and hash-only revisions are never verified evidence | Technical integrity protection (truthful labels) | **Keep** |
| R1: an evaluator-less APPROVAL_GATE never completes | No rule intended this; it is an **unimplemented gap** | **Replace** with an operator-attested completion on confirmation (§2, P7) |
| R3: approvals stay POLICY_UNDECIDED | Waiting on a proposed business restriction (S1/S2) | **Replace** with operator-recorded approval (P1) |
| R4: no signing write path | Missing implementation | **Add** an operator-attested signing write (P4) |
| DEC-S1 per-role operators; DEC-S1b two operators | Proposed business restriction | **Withdraw** for the Local MVP |
| DEC-S2 mandatory attestation evidence | Optional evidence collection | **Withdraw**; notes are optional |
| DEC-D1 signed-file upload; `document_signatures` | Optional evidence collection | **Withdraw**; may come back as an optional attachment |
| DEC-G1 new evidence gates on 2, 3, 9–11 | Proposed business restriction | **Withdraw** (the Steps stay ungated as today) |
| DEC-G2a UAT document + PARTNER evidence | Optional evidence collection | **Withdraw**; replaced by P7 |
| NL4D5A1b report §13 item 4: consumers must refuse `UNVERIFIED_LEGACY` | Proposed restriction that comes from the "managed evidence" direction | **Replace** with a labelling rule (P6) |

---

## 2. Simplified Local MVP policy (DEC-SIMPLIFY — OWNER_APPROVED, LOCAL TEST MVP, 2026-11-12; with DEC-SIMPLIFY-a and -b, see CP12H.NL4D-S1)

**P1. Approval recording.**
- The local operator may record a LEGAL, ACCOUNTING or PARTNER decision (APPROVED or REJECTED) after an explicit confirmation of an exact preview.
- **One role and one decision per confirmation.** The confirmation text states that the decision is final.

**P2. Evidence is optional.** An approval may carry:
- optional `notes`, already redacted in reads;
- an optional decision date (`--occurred-at`; the default is the write time).

No file, external reference or attestation row is required.

**P3. No false authentication.**
- `approved_by` stays **NULL**: the actual approver is not known to the system.
- The recording operator is stored only as `project_events.triggered_by`.
- The event's `new_values` carry `"attestation": "OPERATOR_RECORDED"`.
- Previews, receipts and status reads say "recorded by the local operator", never "approved by".

**P4. Signing is operator-attested.**
- After an explicit confirmation, the operator may mark the latest active revision as signed, with an optional `signed_at` date.
- The existing signing gate must hold.
- The event `DOCUMENT_SIGNED` carries `"attestation": "OPERATOR_ATTESTED"` and **no** cryptographic or file claim.
- No `document_signatures` table is created.

**P5. Uploading files is optional.**
- A revision may be created **metadata-only**: a document type and an optional label, no file.
- A managed file (NL4D5A3) remains optional wherever the workflow permits.
- No Step, approval, signing or procurement rule requires a MANAGED revision.

**P6. Metadata-only revisions stay distinguishable.**
- `evidence_status` keeps saying what is true:
  - `MANAGED`: a verified stored file;
  - otherwise **not verified**.
- Every preview, receipt and status read shows the label.
- A non-MANAGED revision is never described as having a verified file, and a shared hash still grants nothing.
- **Recommended:** a new value `METADATA_ONLY`, for revisions recorded through a confirmed metadata-only write. `UNVERIFIED_LEGACY` then means only rows of unknown provenance (existing rows and any untrusted path). This needs migration 009 (§5). Without it, metadata-only revisions are stored as `UNVERIFIED_LEGACY`, which is truthful but misleading.

**P7. Project completion needs no extra evidence.**
- An APPROVAL_GATE Step **with no database evaluator** may be completed through the existing confirmed Step Update.
- The confirmation states that the operator attests the gate.
- The Step event records `"gate": "OPERATOR_ATTESTED"`.
- Dependency readiness still applies, so "Complete project" still needs all its predecessors completed or skipped.
- Steps with a database evaluator (Partner approval, signing gate) still need their recorded evidence. Under P1 and P4 that evidence is a few confirmations.
- "Activate Merchant" completes the Step only. It does **not** change `merchants.account_status`, which stays the separate `merchant activate` command and is not enabled here.

**P8. All protections are kept.** Every write uses the NL4C/NL4D4A pattern:
1. a verified preview with an exact `requested_operation` and basis hash;
2. a session-owned, single-use, 15-minute pending record of its own kind;
3. the user's own `/solve Xác nhận …`;
4. a re-judge in the preflight and under the locks inside the transaction;
5. claim + ledger + mutation + event in one transaction;
6. a receipt reconciled from PostgreSQL;
7. typed scopes refused, and runtime disabled.

**What does not change:** a confirmation still authorizes exactly one previewed operation. There is no batch "approve everything" confirmation, no implicit approval (never inferred from a Step, message or model), and no role system.

---

## 3. Existing rules to preserve

- Migration 008, as written and applied to the test database:
  - `document_files` and all its CHECK, UNIQUE and immutability rules;
  - the composite FK;
  - the evidence-column immutability trigger;
  - the SELECT-only grant.
  - **No constraint is removed or weakened.**
- DEC-A0 (operator attribution only), P1a/P1c (reference uniqueness, no replacement) and P2.
- DEC-D4 and D4a–g for managed files: they apply whenever a file **is** uploaded. D4d (reject identical content) applies to MANAGED revisions only, since metadata-only revisions have no content.
- DEC-D4e: a signed revision is not superseded.
- The approval finality (APPROVED and REJECTED are final), uniqueness per (revision, role), and the latest-revision rule.
- The signing gate and the PO/Payment Request prerequisites.
- Lock order Project → revision → approval → procurement.
- The append-only `project_events`, the claim fencing and the UNCERTAIN semantics.
- Test database only; runtime Direct EXECUTE disabled; no production grant change.

---

## 4. Changes to the Decision Register (to record after owner approval)

| ID | Current status | Proposed change |
|---|---|---|
| **DEC-SIMPLIFY** (new) | — | Adopt P1–P8 for the Local MVP: confirmation is the authority, evidence is optional, and attestation is labelled |
| DEC-S1a/b | PROPOSED | **WITHDRAWN for the Local MVP.** A single operator may record any role. No separation of duties. |
| DEC-S2a/b | PROPOSED | **WITHDRAWN for the Local MVP.** There is no attestation table and no evidence requirement. `approved_by` stays NULL, `triggered_by` is the operator, and the event carries `OPERATOR_RECORDED`. |
| DEC-D1a/b/c | PROPOSED | **Replaced by P4**: operator-attested signing flag; no signature table or signed-file upload. D1c (runtime grant) stays deferred. |
| DEC-G1a/b/c | PROPOSED | **WITHDRAWN.** Steps 2, 3 and 9–11 stay ungated, as today. |
| DEC-G2a/b | PROPOSED | **Replaced by P7.** Evaluator-less gates are completed by an operator attestation on confirmation; completion still follows dependency readiness. |
| DEC-D4f | APPROVED | Unchanged. Clarify that it is a **labelling** rule: non-MANAGED revisions are never shown as verified files, and they **may** satisfy ordinary workflow gates. |
| DEC-D4g | APPROVED | Unchanged for managed uploads. Metadata-only revisions use the same canonical type list once it is identified. Until then: the existing pattern, plus a type that the user names explicitly in the preview. |
| **DEC-SIMPLIFY-a** (new) | — | Add `METADATA_ONLY` to `evidence_status` (migration 009)? Recommended **yes**. |
| **DEC-SIMPLIFY-b** (new) | — | May a REJECTED Partner decision be recorded, given that it is final and blocks the signing gate until a new revision exists? Recommended **yes**, with the finality warning in the confirmation. |
| P1b | PROPOSED | Unchanged: no format rule. |

The NL4D5A1b report's NL4D5A2 prerequisite 3 ("make approval, signing and gates fail closed on `UNVERIFIED_LEGACY`") is **superseded by P6** if DEC-SIMPLIFY is approved.

---

## 5. Domain and schema impacts

### 5.1 Compatibility

| Area | Impact |
|---|---|
| **Migration 008** | None. Commit it as planned, after its stopped final acceptance is completed. It does not block any simplified flow: confirmed writes insert revisions with no file link, so the FK and file checks do not apply. |
| **`document_files`** | Unchanged and unused until optional uploads (NL4D5A3). It stays SELECT-only for the app role. |
| **`document_revisions`** | Metadata-only rows: `content_hash = 'metadata-only:<revision id>'`. That is non-blank, never SHA-shaped, unique per row and immutable (trigger). `evidence_status`, `document_file_id` and `original_file_name` keep NULL or their defaults. Optional migration 009 widens the `evidence_status` CHECK (below). |
| **Approval engine** | Separate the recorder from the approver: add `recorded_by` (sets only `triggered_by`) and stop copying it into `approved_by`. Optional `notes` and `occurred_at`. Add an optional `precondition` on `record_approval`. |
| **Signing engine** | The gate is unchanged. Pass the operator as `triggered_by` only (`signed_by` is not set as a signatory claim). Add a `precondition` on `sign_document`. |
| **Procurement** | `_require_signed_document` is unchanged and accepts any signed revision, whatever its `evidence_status` (P6). Extend the NL4D4A path to PURCHASE_ORDER and PAYMENT_REQUEST: same pending kind, P1a uniqueness, no replacement. |
| **Step completion** | `transition_step`: when `database_gate_kind` is `None`, an APPROVAL_GATE is satisfied **only** by a confirmed operation carrying `gate_attestation = OPERATOR_ATTESTED`, bound into the basis hash and the pending record. `step_preview` reports `OPERATOR_ATTESTATION_REQUIRED` instead of `NO_DATABASE_GATE_EVALUATOR`. Evaluated gates are unchanged. |
| **Existing confirmed Purchase Request execution** | Unchanged. The NL4D4B live record and its receipt stay valid, and the PR stays create-only. |
| **Accepted records** | None modified: the NL2/NL3/NL4C/NL4D4B acceptance Projects, the 22 claims, the ledger, and NL4C2B Step 1 IN_PROGRESS v2. |

### 5.2 Schema

| Change | Needed? |
|---|---|
| Migration 009 `evidence_status_metadata_only`:<br>• `ALTER TABLE … DROP CONSTRAINT document_revisions_evidence_status_check, ADD CONSTRAINT … CHECK (evidence_status IN ('UNVERIFIED_LEGACY','METADATA_ONLY','MANAGED'))`;<br>• the default stays `UNVERIFIED_LEGACY`.<br>The MANAGED ⇔ file rule, the filename rule and the immutability trigger already hold for the new value. | Only if DEC-SIMPLIFY-a is approved |
| `approval_attestations`, `document_signatures`, `operators`, `operator_roles` | **No.** All withdrawn. |
| Grants | None on the test database (the owner role writes). Runtime grants stay deferred. |

---

## 6. Minimal implementation roadmap (test database only; each step uses the NL4C/NL4D4A pattern)

| Checkpoint | Delivers | Main changes | Unblocks |
|---|---|---|---|
| **S0** | Finish NL4D5A1b acceptance and commit 008. Record DEC-SIMPLIFY in the register. | none (acceptance + docs) | baseline |
| **S1 — Metadata-only revision** | Confirm "create a CONTRACT revision" with no file | `evidence preview` emits `requested_operation` for revisions; `revision` pending kind; `precondition` on `create_revision` (basis = active revision id/number); `document revision-create` in `TEST_MODE_COMMANDS`; receipt. Optional migration 009. | R2 |
| **S2 — Approval confirmation** | "Legal approved the contract" → preview → confirm | P1–P3: replaces `POLICY_UNDECIDED` with a requested operation; engine recorder/approver split; `approval` pending kind; `precondition`; `document approve` in test mode; receipt. | R3, R6, Partner-approval gate |
| **S3 — Signing confirmation** | "The contract is signed" → preview → confirm | P4: `document sign` CLI + adapter over `sign_document`; `signing` pending kind; gate re-judged in the transaction; receipt. | R4, signing gate |
| **S4 — Blocked Steps** | Complete UAT acceptance and Complete project (and the other evaluator-less gates) | P7: attestation flag in `step preview`, the basis and `transition_step`; no template version change | R1 |
| **S5 — PO and Payment Request** | Record PO and Payment Request numbers | Extend the NL4D4A procurement path to both types | R5 |
| **S6 — End-to-end acceptance** | One disposable test Project to COMPLETED, every write confirmed by the user, verified independently in PostgreSQL | none | — |
| **Later, optional** | Managed file upload (NL4D5A2/A3) attached to a revision | the existing design; never required by a gate | — |

**Not built:** role systems, separation of duties, attestation or signature tables, mandatory uploads, multi-operator flows, batch confirmations, runtime enablement.

S1 → S2 → S3 must be sequential (domain dependencies). S4 and S5 are independent of each other after S3; S4's Partner/signing gates need S2/S3, and its evaluator-less part needs nothing.

---

## 7. Regression requirements (each checkpoint)

1. **RED → GREEN** at the real entry points (intent gate → preview → capture → pending → confirmation → preflight → transaction), Vietnamese and English.
2. **Refused unspent:**
   - a typed scope;
   - a confirmation of another kind;
   - an expired or foreign pending record;
   - a scheduled prompt;
   - a model-supplied actor or approver;
   - a changed basis (in the preflight and inside the transaction).
3. **Truthful labels:**
   - `approved_by` is NULL;
   - `triggered_by` is the operator fingerprint;
   - the event `attestation` value is set;
   - a non-MANAGED revision is never reported as verified;
   - a SHA-shaped `content_hash` on a non-MANAGED row is still labelled unverified.
4. **Atomicity and exactly-once:** mutation + event + claim + ledger together; replay refused; fencing and UNCERTAIN under injected failures.
5. **Gates:**
   - evaluated gates still refuse missing approvals or signing;
   - an evaluator-less gate refuses a Step Update **without** a confirmed attestation;
   - dependency readiness is unchanged.
6. **Migration 008 suite** (42 tests) and, if adopted, migration 009 tests on the same rolled-back pattern.
7. **The existing NL4C Step Update and NL4D4A Purchase Request suites** are unchanged and green.
8. **Full suite** run alone (PostgreSQL tests sequential, never concurrent with live `/solve`), `system_test.py`, hook compile/import, `git diff --check`.
9. **Integrity:** the test database hash changes only by the confirmed rows; the accepted records are unchanged.
10. **Runtime:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False` throughout.

---

## 8. GO / NO-GO

- **Simplified policy: GO for owner review.** It removes the evidence, role and multi-operator requirements that would only add work, and keeps every integrity protection.
- **S0 (finish NL4D5A1b acceptance, commit 008): GO** when you authorize resuming it.
- **S1–S6 implementation: NO-GO until:**
  1. **DEC-SIMPLIFY (P1–P8)** is approved, with DEC-SIMPLIFY-a (`METADATA_ONLY`) and DEC-SIMPLIFY-b (REJECTED recordable) answered;
  2. the register is updated as in §4;
  3. S0 is done;
  4. each checkpoint is explicitly authorized in turn.
- **Still NO-GO:** runtime migration, runtime Direct EXECUTE, and any production grant.

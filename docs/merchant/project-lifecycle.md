# Merchant Project Lifecycle (Local MVP)

The current, owner-approved way a Merchant Project moves from creation to completion on the
**test database**. Runtime (production) Direct EXECUTE is disabled in code
(`RUNTIME_DIRECT_EXECUTE_ENABLED = False`); nothing here writes to the runtime database.

Related documents:

- How a confirmed write is executed and verified: [trusted execution](../architecture/trusted-execution.md)
- Full data model and original domain design: [project manager design](project-manager-design.md)
- Why each rule exists: [decision register](../development/decision-register.md)
- Driving a live acceptance run: [live acceptance runbook](../operations/live-acceptance.md)

## 1. Policy: confirmation is the authority

Owner-approved **DEC-SIMPLIFY** (Local Test MVP, 2026-11-12), with DEC-SIMPLIFY-a
(metadata-only revisions) and DEC-SIMPLIFY-b (APPROVED and REJECTED decisions):

| Rule | Meaning |
|---|---|
| P1 Approval recording | The local operator records one LEGAL, ACCOUNTING or PARTNER decision (APPROVED or REJECTED) per confirmation of an exact preview. The decision is final. |
| P2 Evidence is optional | Optional notes and an optional decision date. No file, external reference or attestation row is required. |
| P3 No false authentication | `approved_by` stays NULL; the operator is stored as `recorded_by` / `project_events.triggered_by`; events carry `OPERATOR_RECORDED`. Output says "recorded by the local operator", never "approved by". |
| P4 Operator-attested signing | After confirmation the latest active revision is marked signed (`OPERATOR_ATTESTED_SIGNED`). The signing gate must hold. No signature table, no cryptographic claim. |
| P5 Uploads are optional | A revision may be metadata-only (document type + optional label). No rule requires a managed file. |
| P6 Truthful labels | `evidence_status` is `MANAGED` only for a verified stored file; `METADATA_ONLY` and `UNVERIFIED_LEGACY` are never shown as verified. |
| P7 Completion needs no extra evidence | An APPROVAL_GATE Step with no database evaluator completes through a confirmed Step Update carrying `gate_attestation: OPERATOR_ATTESTED`. Dependency readiness still applies. |
| P8 All protections kept | Verified preview → single-use pending record → the user's own `/solve Xác nhận …` → re-judge in preflight and in the transaction → claim + ledger + mutation + event in one transaction → receipt from PostgreSQL. |

**Withdrawn — do not reintroduce without a new owner decision:** mandatory approval evidence
(S2), per-role operators and two-person approval (S1), mandatory signed-document upload (D1),
extra evidence gates on Steps 2, 3 and 9–11 (G1), and UAT/Partner evidence for Steps 21–22 (G2).

There is no batch confirmation, no implicit approval, and no role system.

## 2. Workflow templates

Four standard templates (version 1), materialised per Project:

| Template | Project type | Steps | Notes |
|---|---|---|---|
| `MEDIA_TOP_UP_NEW_DOCUMENT` | MEDIA_TOP_UP | 12 | Document, reviews, Partner approval, PR, signing gate, sign, PO, Payment Request, close period |
| `MEDIA_TOP_UP_EXISTING_DOCUMENT` | MEDIA_TOP_UP | 4 | Reuses a signed CONTRACT revision of another Project of the same Merchant (§6) |
| `OPENING_NEW_CINEMA_STANDARD` | OPENING_NEW_CINEMA | 22 | Steps 6–7 (Purchase Request) are CONDITIONAL; signing gate is Step 8 |
| `INTEGRATION_NEW_MERCHANT_STANDARD` | INTEGRATION_NEW_MERCHANT | 26 | Steps 9–10 CONDITIONAL; signing gate Step 11; Step 25 activates the Merchant |

A no-procurement Project marks its CONDITIONAL Purchase Request Steps SKIPPED and drops their
dependency edges. The template defines which Step is the signing gate by metadata, never by
number.

## 3. Step and Project state machines

Step transitions (`state_machine.STEP_TRANSITIONS`):

```text
PENDING     -> READY | BLOCKED | SKIPPED | SUPERSEDED
READY       -> IN_PROGRESS | BLOCKED | SKIPPED | SUPERSEDED
IN_PROGRESS -> BLOCKED | COMPLETED | SUPERSEDED
BLOCKED     -> READY | SUPERSEDED
COMPLETED   -> SUPERSEDED            (reopen to READY is a separate, guarded path)
SKIPPED, SUPERSEDED: terminal        (reopen SKIPPED -> READY is guarded)
```

Project transitions: `PLANNED -> IN_PROGRESS | CANCELLED`, `IN_PROGRESS -> BLOCKED | ON_HOLD |
COMPLETED | CANCELLED`, with `COMPLETED -> IN_PROGRESS` only as a guarded reopen.

**Dependency readiness.** A Step may start only when every predecessor is COMPLETED or
SKIPPED. When a Step is completed, every PENDING successor whose predecessors are now all
satisfied is promoted to READY **in the same transaction**, with its own `STEP_READY` event
tagged `promoted_after_step_id`. BLOCKED Steps are never promoted. A Step that was not promoted
(for example one whose other predecessors are still open) still moves PENDING → READY through
an ordinary confirmed Step Update.

**Final Step rule.** The final Step (highest sequence) completes only when every other Step is
COMPLETED or legitimately SKIPPED.

## 4. Operations and their confirmations

Every write starts as a read-only preview of a natural-language request on the test database.
The preview's `requested_operation` is NOT_AUTHORIZED; only the user's own confirmation
phrase spends it, once, within 15 minutes, in the same session.

| Operation | Example request | Command | Confirm with |
|---|---|---|---|
| Create Project | "Tạo Project media … cho … kỳ thanh toán 1, gia hạn hợp đồng, trên database test" | `project create` | `/solve Xác nhận tạo [<id>]` |
| Start Project | "Bắt đầu Project X trên database test" | `project update --status IN_PROGRESS` | `/solve Xác nhận thực hiện <code>` |
| Metadata-only revision | "Tạo phiên bản hợp đồng mới cho Project X …" | `document revision-create` | `/solve Xác nhận thực hiện <code>` |
| Approval / rejection | "Legal đã phê duyệt …" | `document approve` | `/solve Xác nhận thực hiện <code>` |
| Operator-attested signing | "Ghi nhận hợp đồng của Project X đã ký" | `document sign` | `/solve Xác nhận thực hiện <code>` |
| Purchase Request | "Ghi nhận Purchase Request PR-… cho …" | `procurement update` | `/solve Xác nhận ghi nhận` |
| Purchase Order / Payment Request | "Ghi nhận Purchase Order PO-… cho …" | `procurement update --type …` | `/solve Xác nhận thực hiện <code>` |
| Step Update (incl. gate attestation) | "Hoàn thành bước 8 của Project X …" | `step update` | `/solve Xác nhận cập nhật [<step id>]` |
| Complete Project | "Hoàn tất Project X trên database test" | `project update --status COMPLETED` | `/solve Xác nhận thực hiện <code>` |
| Create Merchant (test) | — (no preview path) | `merchant create` | the user's own typed `/solve --confirm --merchant-target test --merchant-scope [...]` |

Cancel phrases: `Hủy tạo`, `Hủy cập nhật`, `Hủy ghi nhận`, `Hủy thực hiện <code>`.

Key rules enforced in the preview, the preflight and again inside the write transaction:

- **Revisions.** A metadata-only revision supersedes the active unsigned revision. A signed
  active revision is never superseded (DEC-D4e). A typed content hash is refused.
- **Approvals.** One role and one final decision per revision; latest active unsigned revision
  only; decided rows are immutable (migration 010 trigger).
- **Signing.** Requires 3 × APPROVED, the Purchase Request when procurement is required, no
  REJECTED role, **and** every signing-gate Step COMPLETED (`SIGNING_GATE_STEP_NOT_COMPLETED`
  otherwise).
- **Procurement.** Create-only; exact reference; unique per (Merchant, type, reference)
  (migration 007); a PO needs a signed revision (own, or the bound reused one); a Payment
  Request needs a PO. Existing references are never replaced (DEC-P1c). A Purchase Request on
  a no-procurement Project is allowed with `PROCUREMENT_NOT_REQUIRED` (DEC-P2).
- **Project completion.** Every Step COMPLETED, SKIPPED or SUPERSEDED, the final Step
  COMPLETED, Project IN_PROGRESS, exact version. Never implied by completing a Step.

## 5. Merchant activation

- Completing Step 25 "Activate Merchant" of an INTEGRATION_NEW_MERCHANT Project activates the
  Merchant (ONBOARDING → ACTIVE) in the same transaction, re-checking the activation
  prerequisites there; the preview states `MERCHANT_ACTIVATION_IN_SAME_TRANSACTION`.
- The standalone commands `merchant activate` (one Merchant) and `merchant activate-all`
  (manifest-bound batch with drift rejection) remain Direct EXECUTE commands with a typed scope;
  see [project manager design](project-manager-design.md).

## 6. Signed revision reuse (Existing-Document Media)

A `MEDIA_TOP_UP_EXISTING_DOCUMENT` Project binds, at its confirmed creation, one signed CONTRACT
revision of **another Project of the same Merchant** (`projects.reused_document_revision_id`,
migration 011). Nothing is copied and the source is never changed.

- Eligible: exists, same Merchant, other Project, CONTRACT, signed, not superseded, no REJECTED
  decision (`document_reuse.reuse_blocker`).
- Exactly one eligible candidate is proposed; several require the revision UUID in the request.
- The binding is immutable after insert (trigger). Changing it means a new Project.
- Its PO and Payment Request accept the bound revision only while the Project has no active
  revision of its own.

Example: "Tạo Project media <tên> cho <Merchant> kỳ thanh toán <n>, sử dụng hợp đồng đã ký của
Project <nguồn> trên database test".

## 7. Known findings and limitations

Status as of the repository cleanup (2026-11-16):

| ID | Finding | Status |
|---|---|---|
| F1 | Signing before the signing-gate Step completed could deadlock a Project | **FIXED** (`b585de2`): signing requires the signing-gate Step COMPLETED |
| F7 | A Merchant can have two open INTEGRATION_NEW_MERCHANT Projects; after the first activates the Merchant, the second can never complete | **OPEN** — needs an owner decision (refuse a second open integration Project at create, or let activation accept an ACTIVE Merchant). Never create two. |
| F8a | Ordinary Steps "Sign document", "Create Purchase Order", "Create Payment Request" can complete without the matching record | **ACCEPTED_LIMITATION** (business policy; signing and procurement re-check their own prerequisites). Record the PO / Payment Request before completing its Step. |
| F8b | A revision created after the signing gate completed is signed without the gate Step re-evaluating | **ACCEPTED_LIMITATION** — signing re-checks the same approvals and PR itself |
| F8c | An Existing-Document Project that registers its own revision shadows its reused binding | **ACCEPTED_LIMITATION** — recovers through its own approvals and signing |
| — | PENDING → READY needed one manual confirmed Step Update per successor | **FIXED** in this cleanup's checkpoint: automatic promotion on predecessor completion (§3) |
| F3 | `merchant create` has no preview path; its authority is the user's typed scope | **ACCEPTED_LIMITATION** (documented typed-scope exception) |
| F4 | No minimal live test of Merchant activation (≈ 80 writes) | **ACCEPTED_LIMITATION** — covered by automated E2E only |
| — | Natural-language wording: hyphens in titles are normalised; "hợp đồng mới" is not read as new-document media (use "gia hạn hợp đồng"); no-procurement needs "không cần mua sắm" | **ACCEPTED_LIMITATION** |
| — | Canonical document-type list (DEC-D4g) undefined; managed file upload unimplemented | **ACCEPTED_LIMITATION** |
| — | Immutability is trigger-enforced; the database owner role can drop triggers | **ACCEPTED_LIMITATION** |
| — | Migrations 007–011 are applied to the test database only; runtime Direct EXECUTE is disabled | **ACCEPTED_LIMITATION** (by design until separately approved) |

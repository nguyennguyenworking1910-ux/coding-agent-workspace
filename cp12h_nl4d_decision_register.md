# CP12H.NL4D-DEC — Evidence, Approval, Signing & Procurement Decision Register

Baseline `448003be64076e01350b4f55cc83a28787cde06a`, branch `feat/cp7-9-merchant-reliability`. Date 2026-11-11.

**Scope.** Documentation only:
- no code, schema, grant or permission change;
- no write; committed on its own as documentation after the NL4D4A approvals (2026-11-11), not pushed;
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

**Status.** Every policy below is PROPOSED, except the four Local Test MVP decisions the owner **APPROVED on 2026-11-11**: DEC-A0, DEC-P1a, DEC-P1c and DEC-P2. They are implemented in commit `23f1f6dd2d892dd534638c325a149f4d5783db51` (CP12H.NL4D4A, test database only).

The approved wording is the owner's own; where it differs from the recommended default, the approval governs. The other owner decisions in §4 remain PROPOSED, including:
- DEC-P1b;
- S1 and S2 (approval attestation);
- D1 (signing);
- D4 (document storage);
- G1 and G2 (Step completion gates).

Each item lists the owner decision it needs (§4). A recommendation is only a default to accept, change or reject.

**Sources read:**
- the reports: NL4D1 audit, NL4D2, NL4D3, NL4D3-FIX1;
- `migrations/0001_initial_schema.sql`, `0003_add_cli_write_grants.sql`, `005`, `006`;
- `bootstrap.py`;
- the engines: `document_engine`, `approval_engine`, `signing_engine`, `procurement_engine`;
- `gates.py`, `gate_resolver.py`, `workflow_templates.py`;
- the repositories: `document`, `approval`, `signing`, `procurement`, `transition`;
- `write_adapters.py`, `attempt_evidence.py`;
- the hooks: `merchant_pending_confirmation.py`, `merchant_direct_handoff.py`, `merchant_preview_delivery.py`.

---

## 1. Existing behavior (facts, not proposals)

### 1.1 Data model

| Table | Columns that matter | Constraints | Runtime grants (`merchant_app`) |
|---|---|---|---|
| `document_revisions` | `id`, `project_id`, `document_type VARCHAR(100)`, `revision_number`, `content_hash TEXT NOT NULL`, `signed`, `signed_at`, `effective_date`, `expiry_date`, `superseded_by`, `created_at`, `created_by UUID` | unique `(project_id, document_type, revision_number)`; `signed ⇔ signed_at`; `expiry > effective`; self-FK `superseded_by` | SELECT, INSERT, **UPDATE (superseded_by) only**. No UPDATE of `signed` / `signed_at` |
| `document_approvals` | `id`, `document_revision_id`, `approver_role`, `approval_status`, `approved_at`, `approved_by UUID`, `notes`, `created_at` | role ∈ {LEGAL, ACCOUNTING, PARTNER}; status ∈ {PENDING, APPROVED, REJECTED}; APPROVED ⇒ `approved_at`; unique `(revision, role)` | SELECT, INSERT, **UPDATE (whole table)** |
| `procurement_records` | `id`, `project_id`, `procurement_type`, `external_id VARCHAR(100)`, `status VARCHAR(50)`, `version` | type ∈ {PURCHASE_REQUEST, PURCHASE_ORDER, PAYMENT_REQUEST}; **unique `(project_id, procurement_type)`** (0003); **no uniqueness on `external_id`** | SELECT, INSERT, **UPDATE (whole table)** |
| `project_events` | `event_type`, `entity_type` ∈ {MERCHANT, PROJECT, STEP, DOCUMENT, PROCUREMENT}, `entity_id`, `old_values`/`new_values` JSONB, `triggered_by UUID` | entity/project consistency check | **INSERT only** (append-only for the app role) |
| `merchant_execution_claims` / `_ledger` | per-attempt claim and ledger, `payload_hash` SHA-256 | claim state machine incl. REVOKED fence | as NL4C (reused) |
| `merchant_contacts` | `merchant_id`, `contact_type` ∈ {PRIMARY, BILLING, TECHNICAL}, `name`, `email`, `phone` (PII) | — | INSERT |

**Missing tables:**
- **No identity table.** `approved_by`, `created_by` and `triggered_by` are UUIDs with **no foreign key**: any UUID is accepted and nothing ties it to a person or a role.
- **No file or storage table:** `content_hash` is the only link to a document's content.
- **No signature table.** Signing is a flag on the revision, and `signed_by` exists only as the event's `triggered_by`.

**Test database.** `coding_agent_merchant_test` is owned by `merchant_test` (bootstrap). The test role therefore has owner privileges, which is how the NL4C test-only writes run. Runtime grants are the narrower `merchant_app` set above.

### 1.2 Domain rules (pure engines; all writes lock Project → revision → approval → procurement `FOR UPDATE`)

| Area | Rule (existing) |
|---|---|
| Revision | Refused on COMPLETED or CANCELLED Projects. `document_type` matches `^[A-Z][A-Z0-9_]{0,99}$`. `content_hash` is any non-blank text. The new number is `max + 1` and supersedes the active one of that type. At most one active revision per type, and it must be the highest number. **No expected version**: it supersedes whatever is active at commit. |
| Approval | Only the **latest active, unsigned** revision. One row per (revision, role). A new row takes any status. An existing row needs `expected_status`; only PENDING → APPROVED/REJECTED is allowed, and **APPROVED and REJECTED are final**. `acted_by` is optional and unverified, stored as `approved_by` (only when APPROVED). |
| Signing (`signing_engine`, `MerchantSigningRepository`) | The latest active unsigned revision. The full signing gate must be met: LEGAL, ACCOUNTING and PARTNER APPROVED on that revision, plus a PR with `external_id` when `requires_procurement`. Sets `signed`/`signed_at`, with event `DOCUMENT_SIGNED`. **No CLI command, no write adapter, and no runtime UPDATE grant.** |
| Procurement | One record per (project, type). A new record needs `status` or `external_id`; an update needs `expected_version` and must change something. `external_id` is non-blank and ≤ 100 characters, with no other format rule. A PR has no prerequisite. A PO needs a **signed** latest active revision, plus the PR number when `requires_procurement`. A Payment Request needs a signed revision and the PO number. **An UPDATE writes `status = plan.status`**, so `None` clears it (found in NL4D3). |
| Gates (`gate_resolver`) | Step 5: PARTNER APPROVED on the latest revision. Step 8: the full signing gate. **Steps 21 and 22 have no evaluator**, so they can never transition. Steps 2, 3, 9, 10 and 11 have **no gate**: they complete without any evidence. |
| Workflow | For `OPENING_NEW_CINEMA_STANDARD`, a no-procurement Project gets steps 6–7 SKIPPED and edges 6→7 and 7→8 dropped. |

### 1.3 Write path and authority (existing)

- **CLI:** `document revision-create`, `document approve` and `procurement update` exist in `WRITE_COMMANDS`, with write adapters (`create_revision`, `approve_document`, `update_procurement`). **None is in `TEST_MODE_COMMANDS`** (`merchant create`, `project create`, `step update`), so Direct EXECUTE refuses them on both targets.
- **NL previews (NL4D3):** `evidence preview` judges all seven operations read-only, with no `requested_operation`, basis authority or pending record. Approvals end `POLICY_UNDECIDED`.
- **NL4C pattern, the template for any new write:**
  1. a VERIFIED preview capture creates a session-owned, 15-minute, single-use pending record of its own kind;
  2. the user's own `/solve Xác nhận …` prompt turns it into a scope;
  3. the preflight re-judges the basis before any spend, and again inside the write transaction (a `precondition`);
  4. the write runs in `evidence_bound_repository` (claim + ledger + mutation + event in one transaction);
  5. a receipt is reconciled from the durable evidence.

  A typed scope for the kind is refused.
- **Repositories accepting an in-transaction precondition:** only `MerchantStepTransitionRepository.transition_step` and Project create. **`record_procurement`, `create_revision`, `record_approval` and `sign_document` do not.**

---

## 2–3. Decisions: options, tradeoffs and recommended defaults

Each entry: **Existing** · **Options** · **Tradeoffs** · **Recommended default (PROPOSED)** · **Owner decision** (ID in §4).

### A0 — Recording actor (prerequisite for every evidence write)

- **Existing:** no identity. Writes carry an optional, unverified `created_by` / `acted_by` / `triggered_by` UUID.
- **Options:**
  - (a) No actor (as today).
  - (b) **A per-workstation operator identity, configured outside the model's reach.** For example, a `MERCHANT_OPERATOR_ID` in the local `.env` that the trusted hook reads, never a CLI argument or model text. It must be registered in a new `merchant_ops.operators` table.
  - (c) SSO / OS user mapping.
- **Tradeoffs:**
  - (a) gives an audit with no "who".
  - (b) is local-first, cheap and unspoofable by the model, but still trusts the workstation user.
  - (c) is the strongest, but has no infrastructure here.
- **Recommended:** (b). The trusted handoff, not the payload, supplies the recording actor. The model or teammate can never supply or override it.
- **Owner:** **DEC-A0**. **APPROVED 2026-11-11**, implemented in `23f1f6d`.
  - **Approved decision:** a trusted local recording operator ID from controlled local configuration.
  - **Where it may not come from:** the natural-language request, teammate output, or an arbitrary CLI argument.
  - **Requirements:**
    - validated by trusted code;
    - bound to the operation, the durable audit evidence and the receipt;
    - fails closed when unavailable or inconsistent.
  - **What it is:** attribution only, not proof of external approver authorization.
  - **As implemented:**
    - `MERCHANT_OPERATOR_ID` (canonical UUID) in the environment or the untracked `.env`;
    - stored as `project_events.triggered_by`;
    - **no `operators` table** (not part of the approval).

### S1 — Who may record LEGAL, ACCOUNTING and PARTNER approvals

- **Existing:** any writer may record any role; `acted_by` is unverified.
- **Options:**
  - (a) Any operator records any role (attestation on someone's behalf).
  - (b) **Operators are authorized per role**: an `operator_roles` mapping, for example a Legal coordinator records LEGAL.
  - (c) Only the approver themself records it (needs approver accounts).
- **Tradeoffs:**
  - (a) is fastest, but one operator can satisfy the whole signing gate alone.
  - (b) bounds who can attest without needing approver accounts.
  - (c) is ideal, but not feasible locally, since PARTNER approvers are external.
- **Recommended:** (b), plus **separation of duties**: one operator cannot record all three roles for the same revision; at least two distinct operators are needed. PARTNER is always an attestation of an external decision, so it requires evidence (S2).
- **Owner:** **DEC-S1a** (who may record each role), **DEC-S1b** (separation of duties: yes/no, how many distinct operators).

### S2 — Verifying and auditing the approver, recorder, evidence and date

- **Existing:**
  - `approved_at` defaults to the write time unless `--occurred-at` is given;
  - `approved_by` is free;
  - `notes` is free text and redacted in reads;
  - there is no evidence link.
- **Options:**
  - (a) Keep the current columns.
  - (b) **A new append-only `approval_attestations` row per decision**, with:
    - the **actual approver**: a `merchant_contacts` id for PARTNER, an `operators` id for internal roles, or a named external person;
    - the **recording actor**: from A0;
    - **`decided_at`** (the real decision date) separate from **`recorded_at`** (the write time);
    - an **evidence reference**: a managed document (D4) and its SHA-256, or an external reference (email Message-ID or ticket);
    - an evidence kind (EMAIL, SIGNED_LETTER, MEETING_MINUTES, SYSTEM_EXPORT).
  - (c) Overload `notes`.
- **Tradeoffs:**
  - (a) cannot answer "who decided, when, based on what";
  - (c) is unstructured and redacted;
  - (b) needs a migration, but is append-only and auditable.
- **Recommended:** (b), with these rules:
  - `decided_at` ≤ `recorded_at`, and ≥ the revision's `created_at`;
  - evidence is **required** for APPROVED and REJECTED;
  - **no implicit approvals**: never inferred from a step completing, a message or a model.
- **Owner:** **DEC-S2a** (required fields and evidence kinds), **DEC-S2b** (is an external reference without a stored file acceptable?).

### D1 — Recording an externally signed document

- **Existing:**
  - signing exists only as engine + repository (a gate-checked flag);
  - there is no CLI, adapter or runtime grant;
  - PO and Payment Request depend on it;
  - nothing records *what* was signed or by whom.
- **Options:**
  - (a) Expose `document sign` as a flag flip.
  - (b) **External signing evidence.** The signed copy (from the partner, or e-signature output) is registered as evidence of the **same** revision: SHA-256 of the signed file, signatories, signing date, and a recording actor. The existing `sign_document` then flips the flag in the same transaction, only when the signing gate is met.
  - (c) The signed copy becomes a new revision (it would supersede the approved revision and void its approvals: wrong).
- **Tradeoffs:**
  - (a) is trivial but unverifiable;
  - (c) breaks the approval model;
  - (b) keeps the approvals and adds verifiable evidence.
- **Recommended:** (b), with a new `document_signatures` table:
  - `revision_id` unique;
  - `signed_file_sha256`;
  - `signed_at`;
  - `signatories` JSON (references to contacts and operators);
  - `recorded_by`;
  - `evidence_document_id`.

  The existing gate is unchanged. The runtime grant `UPDATE (signed, signed_at)` stays a **separate, later** owner decision, because runtime remains disabled.
- **Owner:** **DEC-D1a** (accept (b)), **DEC-D1b** (must the signed file's content be verified against the approved revision, or only stored?), **DEC-D1c** (runtime grant, deferred).

### D4 — Local document storage, metadata, hashing and integrity

- **Existing:** `content_hash TEXT` is free text and nothing stores a file.
- **Options:**
  - (a) Hash only: the user supplies the hash.
  - (b) **A managed local store.** The trusted pipeline copies a user-named local file into a content-addressed, write-once directory outside the repository, computes SHA-256 itself and records metadata.
  - (c) An external DMS or object store.
- **Tradeoffs:**
  - (a) is unverifiable, since the model or user could type any hash;
  - (c) has no infrastructure;
  - (b) is local and verifiable, but needs a file-ingest path that is safe against path traversal and symlinks, plus an orphan policy.
- **Recommended:** (b).
  - **Location:** `MERCHANT_EVIDENCE_STORE` (outside the git tree, not synced), with the file at `sha256/<aa>/<hash>`, read-only after write.
  - **Hash:** `content_hash` stored as `sha256:<64 hex>`. A `CHECK … NOT VALID` constraint applies it to new rows only.
  - **New columns:** `byte_size`, `media_type` (allowlisted: PDF, DOCX, PNG, JPEG), `storage_key`, `original_filename_hash`. The filename is sensitive, so only its hash is stored.
  - **Write order:**
    1. the hash is computed by trusted code, never taken from text;
    2. the file is placed in the store **before** the DB transaction, idempotently by hash;
    3. the DB row is committed with the hash;
    4. an unreferenced file is reported, never auto-deleted while possibly in flight.
  - **Integrity on read:** re-hash on demand (`document verify`).
- **Owner:** **DEC-D4a** (store location and backup), **DEC-D4b** (allowed media types and size limit), **DEC-D4c** (keep the original filename, or only its hash).

### P1 — Valid procurement references and uniqueness

- **Existing:**
  - `external_id` is non-blank and ≤ 100 characters;
  - one record per (project, type);
  - **the same reference can appear on two Projects**;
  - NL4D3-FIX1 reads a reference as one whole word (an extraction limit, not a domain rule).
- **Options:**
  - (a) No format rule and no uniqueness (as today).
  - (b) **A per-type format pattern** (for example `^PR-[A-Z0-9-]+$`), configurable.
  - (c) **Uniqueness of `(procurement_type, external_id)` across Projects**, as a partial unique index.
  - (d) Both.
- **Tradeoffs:**
  - (b) catches typos, but the ERP's real formats are unknown here;
  - (c) prevents attaching one PO to two Projects, but breaks if one PR legitimately covers several Projects.
- **Recommended:**
  - (c) only, as a **case-sensitive exact** partial unique index, with references stored exactly as typed (NFC);
  - no format pattern until the ERP formats are provided;
  - **replacing** an existing reference is allowed only through the explicit update path, with `expected_version` and a confirmation that names the old and new values.
- **Owner:** **DEC-P1a** (cross-Project uniqueness: yes/no, case sensitivity), **DEC-P1b** (format patterns per type, or none), **DEC-P1c** (may a recorded reference be replaced, and by whom?).
- **DEC-P1a: APPROVED 2026-11-11** (implemented in `23f1f6d`).
  - **Approved rule:** a reference is unique within **(merchant_id, procurement_type, reference)**. This is scoped per Merchant, unlike the cross-Merchant default recommended above.
  - **Enforcement:** transactional, with a database-level guarantee.
  - **As implemented:** migration 007 (test database) adds `procurement_records.merchant_id`, pinned to its Project by a composite FK, and an exact partial unique index.
- **DEC-P1c: APPROVED 2026-11-11** (implemented in `23f1f6d`).
  - **Approved rule:** Purchase Request reference replacement is **not supported** in NL4D4. An existing reference is never silently overwritten, and any attempt to change it is rejected. This replaces the "allowed through an update" default above.
- **DEC-P1b: PROPOSED** (not decided). The implementation adds no format rule; the existing domain rule (non-blank, ≤ 100 characters) is unchanged.

### P2 — Purchase Requests on optional-procurement Projects

- **Existing:**
  - the domain **allows** a PR when `requires_procurement = false`;
  - no gate reads it, and steps 6–7 are SKIPPED;
  - NL4D3 reports `PROCUREMENT_NOT_REQUIRED` as a note.
- **Options:**
  - (a) Allow (as today).
  - (b) Allow, with an extra confirmation warning.
  - (c) Forbid.
- **Tradeoffs:**
  - (c) adds a new business rule and blocks legitimate optional purchases;
  - (a) can record data that no gate uses.
- **Recommended:** (b). This is the existing domain behavior, plus a mandatory warning line in the confirmation.
- **Owner:** **DEC-P2**. **APPROVED 2026-11-11** (implemented in `23f1f6d`).
  - **Approved rule:** a Purchase Request may be recorded when `requires_procurement=false`.
  - **Warning:** the informational `PROCUREMENT_NOT_REQUIRED` is returned.
  - **No side effects:** no workflow dependency changes and no automatic activation of procurement steps.

### G1 — Evidence required to complete steps 2, 3 and 9–11

- **Existing:** no gates. Step 2 (Legal review), step 3 (Accounting review), step 9 (Sign document), step 10 (Create PO) and step 11 (Create Payment Request) complete with no evidence.
- **Options:**
  - (a) Keep them ungated.
  - (b) **Gate each on its natural evidence:**
    - step 2: a LEGAL approval *decided* (APPROVED or REJECTED) on the latest revision;
    - step 3: the same for ACCOUNTING;
    - step 9: the revision is signed (D1);
    - step 10: a PO with `external_id`;
    - step 11: a Payment Request with `external_id`.
  - (c) Gate only 9–11.
- **Tradeoffs:**
  - (b) makes the workflow evidence-driven, but needs a template version bump; existing Projects must keep their old behavior or be migrated.
  - A REJECTED review that still completes step 2 is a policy question.
- **Recommended:** (b), as **new gate kinds in `gate_resolver`** keyed by template step key, applied to a **new template version** only. Existing Projects keep their version.
- **Owner:** **DEC-G1a** (which steps are gated), **DEC-G1b** (may a REJECTED review complete step 2 or 3?), **DEC-G1c** (new version only, or migrate in-flight Projects?).

### G2 — Steps 21 (Complete UAT acceptance) and 22 (Complete project)

- **Existing:** APPROVAL_GATE steps with **no evaluator**, so they can never transition, and an `OPENING_NEW_CINEMA_STANDARD` Project can never complete through the CLI.
- **Options:**
  - (a) Remove the gate.
  - (b) **Step 21:** a UAT acceptance document revision (type, for example, `UAT_ACCEPTANCE`) with a PARTNER approval and evidence. **Step 22:** all non-skipped steps COMPLETED, the contract signed, and the PO and Payment Request recorded when applicable.
  - (c) Manual sign-off by an authorized operator role, with evidence.
- **Tradeoffs:**
  - (a) loses the control;
  - (b) reuses the existing entities;
  - (c) needs S1-style roles.
- **Recommended:** (b), with `UAT_ACCEPTANCE` as a document type. The PARTNER approval for step 21 is on that type's latest revision, which needs the approval gate to accept a `document_type` (already a parameter of `evaluate_approval_gate`).
- **Owner:** **DEC-G2a** (evidence for 21), **DEC-G2b** (conditions for 22).

---

## 4. Explicit owner decisions

Four decisions were approved on 2026-11-11 (commit `23f1f6dd2d892dd534638c325a149f4d5783db51`). Every other decision is PROPOSED.

| ID | Question | Recommended answer | Status | Blocks |
|---|---|---|---|---|
| DEC-A0 | Recording actor: per-workstation configured operator id registered in `operators`? | Yes | **APPROVED 2026-11-11**: trusted local operator ID from controlled local configuration; attribution only; no `operators` table | NL4D4 and all later |
| DEC-P1a | Unique `(procurement_type, external_id)` across Projects? Case-sensitive? | Yes, exact | **APPROVED 2026-11-11**: unique `(merchant_id, procurement_type, reference)`, exact, with a database guarantee | NL4D4 |
| DEC-P1b | Reference format pattern per type? | None until ERP formats are given | PROPOSED | NL4D4 |
| DEC-P1c | May a recorded reference be replaced? By whom? | Yes, via update with old/new shown in the confirmation; any authorized operator | **APPROVED 2026-11-11**: PR reference replacement not supported in NL4D4; any change is rejected | NL4D4 |
| DEC-P2 | PR on a no-procurement Project? | Allow, with a confirmation warning | **APPROVED 2026-11-11**: allow, with `PROCUREMENT_NOT_REQUIRED`; no workflow change | NL4D4 |
| DEC-D4a/b/c | Store location and backup; media types and size; original filename kept? | Outside-repo content-addressed store; PDF/DOCX/PNG/JPEG ≤ 25 MB; filename hash only | PROPOSED | NL4D5A |
| DEC-S1a/b | Who records which role; separation of duties | Per-role operator mapping; ≥ 2 distinct operators across the three roles | PROPOSED | NL4D5B |
| DEC-S2a/b | Attestation fields; external reference without a file? | Fields as §S2; a file is required for PARTNER, an external reference is allowed for internal roles | PROPOSED | NL4D5B |
| DEC-D1a/b/c | External signing evidence model; verify the signed copy; runtime grant | Accept (b); store the signed file and hash, no content comparison in the MVP; grant deferred | PROPOSED | NL4D5C |
| DEC-G1a/b/c | Gated steps; REJECTED completes a review?; version policy | Gate 2, 3, 9, 10, 11; REJECTED blocks completion; new template version only | PROPOSED | NL4D5D |
| DEC-G2a/b | Steps 21 and 22 evidence | As §G2 | PROPOSED | NL4D5D |

---

## 5. Data model changes (proposed; migrations `007+`, test database first)

| Migration | Change | For |
|---|---|---|
| 007 `operators` | `merchant_ops.operators(id UUID PK, display_name, active, created_at)`; `operator_roles(operator_id FK, approver_role)` | A0, S1 |
| 008 `procurement_reference_unique` | `CREATE UNIQUE INDEX … ON procurement_records (procurement_type, external_id) WHERE external_id IS NOT NULL` (preceded by a duplicate check) | P1 |
| 009 `document_storage` | `document_revisions` + `storage_key`, `byte_size`, `media_type`, `original_filename_hash`; `CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$') NOT VALID` | D4 |
| 010 `approval_attestations` | append-only: `approval_id FK`, `approver_kind`, `approver_contact_id FK NULL`, `approver_operator_id FK NULL`, `approver_name_hash`, `recorded_by FK operators`, `decided_at`, `recorded_at`, `evidence_kind`, `evidence_revision_id FK NULL`, `evidence_sha256`, `external_reference`; app role INSERT-only | S2 |
| 011 `document_signatures` | `revision_id UNIQUE FK`, `signed_at`, `signed_file_sha256`, `signatories JSONB`, `recorded_by FK`, `evidence_storage_key`; INSERT-only | D1 |
| (code) | new gate kinds in `gate_resolver` and a new template version | G1, G2 |
| (later, runtime) | column grants: `document_revisions UPDATE (signed, signed_at)`; narrow `document_approvals` / `procurement_records` UPDATE to the columns the engines change | D1c, NL4D1 S6 |

**Applied to the test database only**, via the existing `migrate.py`. No production grant change until runtime enablement is separately approved.

---

## 6. Security model

**Identity:**
- the **recording actor** comes only from trusted configuration (A0);
- the **approver** is data with evidence (S2);
- neither is ever accepted from model output, teammate messages, CLI arguments or `TEAM_RESULT_JSON`.

**Authorization (per write kind), unchanged in shape from NL4C:**
1. a VERIFIED preview carrying an exact `requested_operation` and basis hash;
2. a session-owned single-use pending record of a **new kind** (`procurement`, `revision`, `approval`, `signature`);
3. the user's own `/solve Xác nhận …` phrase for that kind (a confirmation of one kind never confirms another);
4. typed scopes refused;
5. the role and separation-of-duty checks (S1) run in the preflight **and** in the transaction.

**No separate database writer.** All writes use the existing repositories inside `evidence_bound_repository` (claim + ledger + mutation + `project_events` in one transaction). New tables are written by the same repositories in the same transaction.

**Concurrency:**
- the existing lock order (Project → revision → approval → procurement) is kept;
- each repository gains an optional `precondition(connection)`, as `transition_step` has, to re-judge the preview basis under the locks;
- revision creation gets a basis (the active revision id and number), closing NL4D1 S4.

**Idempotency:**
- the preview mints the new record's UUID inside `requested_operation`, so a replay hits the primary key and is refused;
- one claim per (owner, teammate, run, task, scope), as today.

**Recovery:**
- unchanged NL4C semantics: FAILED only when fenced, SUCCEEDED only with committed evidence, otherwise UNCERTAIN, never retried automatically;
- a per-kind receipt reconciler reads the committed row, event and claim;
- for files, a placed-but-uncommitted file is an orphan, reported and never deleted while a claim is open.

**Audit:**
- existing events (`DOCUMENT_REVISION_CREATED`, `DOCUMENT_APPROVED`/`REJECTED`/`APPROVAL_REQUESTED`, `DOCUMENT_SIGNED`, `PROCUREMENT_CREATED`/`UPDATED`), with `triggered_by` = the recording operator;
- attestation and signature rows are INSERT-only;
- `project_events` stays INSERT-only.

**Sensitive data:**
- hashes, notes and filenames stay redacted in reads;
- PII from `merchant_contacts` is referenced by id, never copied into events.

**Unchanged:**
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`;
- test database only;
- no production permission change.

### Local MVP proposal: evaluation

| Element | Verdict | Reuse (NL4C/NL4D) | New component |
|---|---|---|---|
| Local-first, test-DB-only | Accept | target binding, preflight identity check, `TEST_MODE_COMMANDS` | per-kind entries in the allowlist |
| External signing + verified evidence | Accept (D1b) | `signing_engine`, `MerchantSigningRepository`, signing gate | `document_signatures`, `document sign` CLI and adapter, signed-file ingest |
| Metadata + SHA-256 + managed file | Accept (D4b) | `document_engine`, `create_revision` | evidence store, ingest (trusted hashing), columns, `document verify` |
| Approver ≠ recording actor | Accept (S1b, S2b) | `approval_engine`, `record_approval` | `operators`, `operator_roles`, `approval_attestations`, separation-of-duty check |
| No fabricated or implicit approvals | Accept | the NL4D3 POLICY_UNDECIDED stance; the delivery contract | evidence-required validation |
| Exact procurement references | Accept (P1c) | NL4D3-FIX1 extraction, `procurement_engine` | unique index; old/new in the confirmation |
| Explicit completion gates | Accept (G1b, G2b) | `gate_resolver`, `transition_step` | new gate kinds, template version |
| Atomic writes + trusted confirmation | Accept | pending store, confirmation parsing, staging, reservation, `evidence_bound_repository`, preflight | `precondition` param on four repositories; `requested_operation` + basis in `evidence preview` |
| Durable audit + receipt reconstruction | Accept | claims, ledger, fencing, `STEP_RECEIPT`-style reconciler | one reconciler per kind |

---

## 7. Implementation checkpoints (adjusted to the domain dependencies)

The requested order is changed in two places:
- **PO and Payment Request need a signed revision**, so NL4D4 covers the Purchase Request only, and PO/Payment Request move after signing (NL4D5C-P).
- **Approvals need a revision.** Signing needs all three approvals, so the order is revision → approvals → signing.

| Checkpoint | Scope | Needs decisions | MVP? |
|---|---|---|---|
| **NL4D4** | Trusted **Purchase Request** reference recording on the test DB. Steps:<br>1. `operators` (007) and the A0 recording actor.<br>2. The unique index (008).<br>3. `evidence preview` emits `requested_operation` + basis for PR only.<br>4. A `procurement` pending kind and `/solve Xác nhận ghi nhận [<id>]`.<br>5. A `precondition` on `record_procurement`.<br>6. `procurement update` added to `TEST_MODE_COMMANDS` **only for `--type PURCHASE_REQUEST`**.<br>7. A receipt reconciler. | A0, P1a–c, P2 | **Mandatory** |
| **NL4D5A** | Document revision recording: the evidence store and ingest (009), trusted SHA-256, a basis (the active revision), a `revision` pending kind, a precondition on `create_revision`, receipt. | A0, D4a–c | **Mandatory** |
| **NL4D5B** | Approval recording with attribution: 007 roles, 010 attestations, an `approval` pending kind (one role per confirmation; the finality warning), separation of duties, `expected_status` basis, receipt. | A0, S1a–b, S2a–b | **Mandatory** |
| **NL4D5C** | External signing evidence: 011, the `document sign` CLI and adapter over the existing engine and repository, signed-file ingest, a `signature` pending kind, the signing gate re-judged in the transaction. | D1a–b (D1c deferred) | **Mandatory** (PO/Payment Request depend on it) |
| **NL4D5C-P** | PO and Payment Request recording: extend NL4D4 to the other two types once a signed revision exists. | as NL4D4 | **Mandatory** for full lifecycle |
| **NL4D5D** | Step evidence gates: new gate kinds for 2, 3, 9, 10, 11, 21, 22 in a new template version; `step preview` and NL4C step update re-judge them. | G1a–c, G2a–b | **Mandatory** (otherwise Projects never complete) |
| **NL4D6** | Lifecycle acceptance on one disposable test Project, user-confirmed only: revision → LEGAL/ACCOUNTING/PARTNER approvals (two or more operators) → step 5 → PR (if procurement) → step 8 → sign → PO → Payment Request → steps 9–11 → UAT acceptance (21) → complete (22), with independent PostgreSQL verification per write. | all | **Mandatory** |
| Optional extensions | `document verify` re-hash sweep; orphan-file report; column-level runtime grants; per-type reference format patterns; SSO identity; runtime enablement (separate approval) | — | Optional |

---

## 8. Acceptance criteria (every write checkpoint)

1. **RED/GREEN** at the real entry points (intent gate → preview → capture → pending → confirmation → preflight → transaction), with both Vietnamese and English requests.
2. **Authority:**
   - only a VERIFIED preview of that kind creates a pending record;
   - a typed scope, a confirmation of another kind, an expired or foreign record, a scheduled prompt and a model-supplied actor are all refused **unspent**;
   - a changed basis (concurrent write) is refused in the preflight **and** inside the transaction.
3. **Atomicity:**
   - mutation + event + claim + ledger (+ attestation or signature row) commit together or not at all;
   - fencing and UNCERTAIN semantics hold under injected failures.
4. **Exactness:** references, hashes, roles, dates and actors in the committed row equal the confirmed preview (reference preserved as in NL4D3-FIX1).
5. **No implicit evidence:** no approval, signature or reference is created by any path other than its own confirmed write.
6. **Audit:**
   - one event per write with `triggered_by` = the configured operator;
   - INSERT-only tables cannot be updated by the app role (privilege test).
7. **Regression:** the full suite run alone; PostgreSQL suites sequential; `system_test.py`; `git diff --check`.
8. **Live:** one independent live `/solve` per write kind on the test DB, verified from transcripts, team state and PostgreSQL. The integrity hash changes **only** by the confirmed rows; claims and ledger grow by exactly one each.
9. **Runtime:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False` throughout; no production grant changed.

---

## 9. GO/NO-GO for NL4D4

> **Update 2026-11-11.** The four decisions below were approved, and NL4D4A was implemented and committed as `23f1f6dd2d892dd534638c325a149f4d5783db51` (test database only; runtime Direct EXECUTE still disabled). It differs from the plan below as follows:
> - the operator needs no `operators` table;
> - uniqueness is per Merchant, in a single migration 007;
> - recording is create-only (no replacement).
>
> The original assessment follows.

**NO-GO to implement now; GO to start as soon as these four owner decisions are recorded:**
- DEC-A0 (recording actor);
- DEC-P1a (reference uniqueness);
- DEC-P1c (replacement policy);
- DEC-P2 (PR on no-procurement Projects).

DEC-P1b may stay "no format pattern".

**Once those are decided, NL4D4 is low-risk:**
- the Purchase Request has **no domain prerequisite**;
- the engine, repository, adapter and NL extraction (NL4D3-FIX1) already exist and are live-verified;
- the authority pattern is NL4C's, already live-verified for Step Update.

**New in NL4D4:**
- migrations 007 (operators) and 008 (unique index) on the test DB;
- a `precondition` on `record_procurement`;
- the preview emitting `requested_operation`;
- the `procurement` pending kind and confirmation phrase;
- the test-mode entry restricted to `PURCHASE_REQUEST`;
- a receipt reconciler.

**Out of NL4D4:** PO, Payment Request, revisions, approvals, signing, gates and runtime.

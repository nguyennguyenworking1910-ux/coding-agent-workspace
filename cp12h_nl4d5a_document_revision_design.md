# CP12H.NL4D5A-DESIGN — Managed Document Revision Architecture

Baseline `91ad86679a68e6ba3818b9456fcc5d7027423acd`, branch `feat/cp7-9-merchant-reliability`. Test DB baseline `99abfa8e…`. Date 2026-11-11.

**Design only.** No code, schema, migration, grant or authorization change. `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

> **Status update (2026-11-12, committed as documentation).** This document was written *before* the owner decisions and is kept as the design record. Its parts have different status:
> - **Existing domain behavior (§1).** Facts read from the code at baseline `91ad866`; unchanged.
> - **Approved by the owner (2026-11-11, Local Test MVP only).** DEC-D4 and DEC-D4a–g, recorded verbatim in `cp12h_nl4d_decision_register.md`. They authorize **no document write**. Where the approval differs from this document's original proposal, **the approval governs**:
>   - **D4a:** the store is backed up **before** the DB snapshot (this document proposed DB first; see the backup gap in the NL4D5A1a report §1).
>   - **D4c:** the original filename may be kept **as sanitized metadata** (this document proposed a hash only); it never determines a storage path.
>   - **D4e:** a signed revision is **not superseded** until a signing lifecycle policy is approved (this document left it undecided).
>   - **D4f:** legacy hash-only revisions are classified **UNVERIFIED_LEGACY**: no migration, no fabricated files, never verified evidence.
>   - **D4g:** only canonical document types already recognized by the domain are accepted. The domain enumerates no list yet, so it must be identified before NL4D5A2.
> - **Proposed architecture.** §2–§9 and §11 are design proposals, not approvals. NL4D5A1a implemented only the isolated store (`d7c15d1`).
> - **Still unresolved (PROPOSED).** S1, S2, D1, G1, G2 and P1b.
>
> §10 shows both the original proposal and the recorded approval.

Sources read: decision register (`b66c0c0`), NL4D1 audit, NL4D3 / NL4D3-FIX1, NL4D4A, NL4D4B live acceptance; `migrations/0001`, `0003`, `007`; `document_engine.py`, `document_repository.py`, `approval_engine.py`, `signing_engine.py`, `gates.py`, `gate_resolver.py`, `project_factory.py`, `evidence_preview.py`, `write_adapters.py`, `attempt_evidence.py`, the NL4D4A hooks.

---

## 1. Existing architecture (actual behavior)

### 1.1 Schema

`merchant_ops.document_revisions` (`0001_initial_schema.sql:292`):

| Column | Rule |
|---|---|
| `id UUID` PK | caller-supplied or `uuid4()` in the repository |
| `project_id UUID NOT NULL` | FK `projects(id)` |
| `document_type VARCHAR(100)` | engine pattern `^[A-Z][A-Z0-9_]{0,99}$`; **no allowlist** |
| `revision_number INT` | `> 0`; **UNIQUE (project_id, document_type, revision_number)** |
| `content_hash TEXT NOT NULL` | **free text**: the engine only requires non-blank (`_required_text`); no format, no file |
| `signed BOOLEAN`, `signed_at` | CHECK: both set or both unset |
| `effective_date`, `expiry_date` | CHECK expiry > effective |
| `superseded_by UUID` | FK to `document_revisions(id)`; NULL = active |
| `created_at`, `created_by UUID` | `created_by` optional, unverified, no FK |

Other facts:
- `projects.reused_document_revision_id` is an FK to `document_revisions` (a payment-period Project reuses a contract revision).
- Grants (`0003`): `merchant_app` may INSERT revisions and UPDATE **only** `superseded_by`. There is no grant to UPDATE `signed`/`signed_at` (signing is not runtime-executable).
- **No file storage exists anywhere in the code base**: no store, no file table, no ingestion path.

`document_approvals`:
- one row per **(revision, role)** (UNIQUE);
- role ∈ LEGAL/ACCOUNTING/PARTNER;
- status ∈ PENDING/APPROVED/REJECTED;
- APPROVED ⇒ `approved_at`;
- `approved_by` is optional and unverified.

### 1.2 Domain behavior

| # | Topic | Actual behavior (code) |
|---|---|---|
| 1 | Revision semantics | `propose_document_revision` plans an **immutable** row. The engine rejects:<br>• a terminal Project (`DocumentLifecycleClosedError`);<br>• duplicate ids or numbers in the snapshot;<br>• a revision from another Project;<br>• more than one active revision per type;<br>• an active revision that is not the highest number. |
| 2 | Content hash | Any non-blank text. Never computed from bytes, never verified. Duplicate content is not detected. |
| 3 | Active revision | The single row of `(project, type)` with `superseded_by IS NULL`, required to be the highest number. Gates use `gates.latest_document_revision` and need `document_type` when several types are active (`GateValidationError`). |
| 4 | Replacement | `create_revision`:<br>• locks the Project and **all** its revisions `FOR UPDATE`;<br>• INSERTs `n+1`;<br>• UPDATEs the previous active row's `superseded_by` (guarded `superseded_by IS NULL`; `rowcount != 1` gives `DocumentRevisionConflictError`);<br>• writes a `DOCUMENT_REVISION_CREATED` event;<br>• runs in one transaction.<br>**A signed active revision is superseded like any other**: the engine does not check `signed`. |
| 5 | Approval invalidation | **Implicit.** Approvals stay attached to their revision row and are never deleted or changed. Approval and signing gates read only the latest active revision, so a new revision starts with no approvals. Approvals on a **signed** revision cannot change ("Signed document revisions cannot change approvals"). APPROVED and REJECTED are final. NL4D2 already reports `outdated_approvals`. |
| 6 | Signing dependencies | `signing_engine` signs only the **latest active unsigned** revision, after the full signing gate:<br>• LEGAL, ACCOUNTING and PARTNER APPROVED on that revision;<br>• a PR `external_id` when `requires_procurement`.<br>Purchase Order and Payment Request need a signed active revision (`procurement_engine._require_signed_document`). There is no CLI or adapter for signing, and no runtime grant. |
| 7 | File storage | None. |
| 8 | Transactions | One PostgreSQL transaction per write (lock Project → revisions → plan → INSERT → UPDATE predecessor → event). A unique violation becomes a conflict, and an exception rolls back everything.<br>`create_revision` has **no `precondition` hook** (NL4D4A added one only to `record_procurement`).<br>Under Direct EXECUTE, the claim and ledger join that transaction (`evidence_bound_repository`). |

### 1.3 What already exists to reuse (NL4C / NL4D4A)

- Read-only preview, then a `requested_operation` (NOT_AUTHORIZED, canonical argv, basis hash).
- Trusted PostToolUse capture, then a per-kind pending store (15-minute TTL, single use, owner session).
- `/solve Xác nhận …` turns it into a scope, followed by the confirmed-record preflight, `precondition` re-judgement under locks, and `evidence_bound_repository` (claim + ledger + mutation + event in one transaction).
- A PostgreSQL-derived receipt (`xmin`-reconciled) and recovery from PostgreSQL alone.
- A trusted local operator (`MERCHANT_OPERATOR_ID`, DEC-A0), re-resolved at every authority point.
- A typed scope refused at the gate, and a test-only allowlist (`TEST_MODE_COMMANDS`).

---

## 2. DEC-D4 options

| | A. Hash-only revisions | B. Managed local immutable store + PostgreSQL metadata | C. External object/document store |
|---|---|---|---|
| What is stored | a typed or claimed hash | the bytes, in a write-once local store; the hash is computed by trusted code | the bytes in S3 / SharePoint / DMS; we store a reference |
| Verifiable later | **no** (any text is accepted today) | yes: re-hash the stored bytes on demand | depends on the provider (ETag/versioning) |
| Infrastructure | none | one local directory | credentials, network, a provider |
| New attack surface | none | file ingestion (paths, symlinks, size, type) | network, credentials, provider ACLs |
| Crash consistency | trivial | filesystem and DB are not jointly atomic, so ordering rules are needed (§6) | the same problem, plus remote failures |
| Fit for a Windows local MVP | fails the "verifiable evidence" goal | **best** | heavy; no infrastructure here |

**Recommendation (Proposed): Option B, the smallest safe local design.** It adds:
- one configured store directory;
- one file-metadata table;
- two columns on revisions;
- one trusted ingestion module.

Option C stays a later replacement behind the same `document_files` abstraction (`storage_key` is opaque).

---

## 3. Recommended design (summary)

```
user drops file ─▶ INBOX (configured)        PREVIEW (read-only)                      EXECUTION (trusted hook)
                    MERCHANT_DOCUMENT_INBOX   • resolve inbox entry by bare name       1 preflight: confirmed record, operator, basis,
                                              • reject unsafe path/reparse/size/type     inbox file still hashes to the bound sha256
                                              • stream-hash bytes (SHA-256)            2 spend authority (single use)
                                              • domain plan (propose_document_revision)3 ingest: copy inbox → STAGING, hash the COPY,
                                              • requested_operation binds:               compare to bound sha256, fsync, os.replace →
                                                sha256, size, media type, inbox name,    STORE/sha256/aa/<hex> (idempotent), read-only
                                                type, project, version, basis, operator4 ONE DB transaction (claim+ledger):
                                              ─▶ trusted capture re-hashes the inbox      lock Project+revisions → precondition re-judges
                                                 file, records pending (kind=document)    basis + store file present & hash ok →
                                              ─▶ user: /solve Xác nhận …                  upsert document_files → INSERT revision →
                                                                                          supersede predecessor → event → commit
                                                                                       5 receipt from PostgreSQL (xmin) + store re-hash
```

Principles:
- The **bytes stored are the bytes hashed by trusted code**, which hashes the staged copy, never the source.
- A hash is **never** accepted from text.
- **The filesystem never deletes**; PostgreSQL is the index.
- **The file is promoted before the DB commit**, so a committed row never points to a missing file (§6).
- The **preview stays read-only** (it only reads and hashes the inbox file).

---

## 4. Storage and metadata model (Proposed)

### 4.1 Filesystem

| Item | Proposal |
|---|---|
| Store root | `MERCHANT_DOCUMENT_STORE` (local configuration, like `MERCHANT_OPERATOR_ID`). It must be an absolute local NTFS path **outside the repository** and outside OneDrive or other sync folders; this is validated at startup and fails closed. |
| Inbox | `MERCHANT_DOCUMENT_INBOX`, a configured directory where the user places files. The request names a file **by bare name only**: no separators, `..`, drive letters, UNC or ADS (`:`). This avoids passing arbitrary paths through model text. |
| Staging | `<store>/staging/` on the **same volume**, so `os.replace` is an atomic rename |
| Layout | `<store>/sha256/<aa>/<64-hex>`. It is content-addressed, so identical bytes are stored once and promotion is idempotent. |
| Storage key | `sha256/<aa>/<hex>`, stored opaquely in PostgreSQL |
| File ID | `document_files.id` is a UUID generated by trusted code, never supplied |
| Immutability | after promotion, set the read-only attribute and never open for write. An existing target is **never overwritten**; promotion of an existing target only re-hashes it. Mutation is detected by re-hash. |
| Size and type | a byte limit, enforced while streaming (Proposed 25 MB, DEC-D4b). The media type is detected from **magic bytes**, never the extension: PDF `%PDF-`, PNG, JPEG, DOCX (a ZIP containing `[Content_Types].xml` with the WordprocessingML type). The allowlist is DEC-D4b. |
| Path safety | resolve inside the inbox, then refuse if any of these hold:<br>• the resolved path is not a direct child of the inbox;<br>• `os.lstat` shows a symlink or **reparse point** (`FILE_ATTRIBUTE_REPARSE_POINT`, which covers junctions);<br>• it is not a regular file;<br>• it is larger than the limit.<br>The file is opened `O_RDONLY | O_BINARY`, and the copy is what gets hashed (TOCTOU-safe). |
| Integrity check | `document verify` (read-only): re-hash every referenced file and report missing, mismatched or unreferenced files (orphans). It never repairs. |
| Backup and restore | the store only grows, and committed rows always reference already-promoted files. So:<br>• **back up PostgreSQL first, then the store**: every row in the dump has its file in the later store copy;<br>• restore both, then run `document verify`.<br>The location and schedule are DEC-D4a. |

### 4.2 PostgreSQL (a future migration 008; not created)

```sql
CREATE TABLE merchant_ops.document_files (
    id            UUID PRIMARY KEY,                 -- trusted-code generated
    content_hash  TEXT NOT NULL UNIQUE              -- 'sha256:<64 hex>'
                  CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    byte_size     BIGINT NOT NULL CHECK (byte_size > 0),
    media_type    TEXT NOT NULL,                    -- allowlist per DEC-D4b
    storage_key   TEXT NOT NULL UNIQUE,             -- 'sha256/aa/<hex>'
    original_name_hash TEXT,                        -- or the name itself, per DEC-D4c
    stored_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    stored_by     UUID NOT NULL,                    -- trusted operator (DEC-A0)
    UNIQUE (id, content_hash)
);
ALTER TABLE merchant_ops.document_revisions
    ADD COLUMN document_file_id UUID,
    ADD CONSTRAINT document_revisions_file_fk
        FOREIGN KEY (document_file_id, content_hash)
        REFERENCES merchant_ops.document_files (id, content_hash);
```

**Design notes:**
- **Hash consistency in the database.** The composite FK (the NL4D4A-007 pattern) makes a managed revision's `content_hash` equal its file's hash. Legacy rows (file NULL) are unaffected: a composite FK with a NULL column is not checked.
- **Managed rows only (optional, NOT VALID).** `CHECK (document_file_id IS NOT NULL) NOT VALID` makes every *new* revision managed and leaves legacy rows untouched. This is DEC-D4f (legacy hash-only revisions).
- **One active revision per type (optional).** The guarantee would be `EXCLUDE USING btree (project_id WITH =, document_type WITH =) WHERE (superseded_by IS NULL) DEFERRABLE INITIALLY DEFERRED`. It must be *deferred*, because the repository inserts `n+1` before superseding `n`. The Project lock already serializes this, so it is defence in depth; verify it in A1.
- **Grants (test database first):**
  - `merchant_app` gets SELECT and INSERT on `document_files`, and nothing else;
  - files are append-only and never updated.

---

## 5. Revision lifecycle (Proposed unless marked "existing")

| Event | Behavior |
|---|---|
| Initial revision | `revision_number` 1, `superseded_by` NULL, unsigned (existing engine), plus the `document_file_id` and computed hash |
| New revision | `n+1` supersedes the active `n` in the same transaction (existing). New: the bound file must be promoted and verified, and the predecessor's approvals simply stop counting (existing gate semantics). |
| Active selection | unchanged: `superseded_by IS NULL`, the highest number, one per (project, type) |
| Versioning | `revision_number` is the version; the Project row version is part of the basis |
| Document type | the existing pattern. **An allowlist (for example CONTRACT, ADDENDUM, UAT_ACCEPTANCE) is an owner decision (DEC-D4g)**: the domain has none today and none is invented here. |
| Duplicate content | Proposed refusal: a new revision whose hash equals the **current active** revision of the same type is BLOCKED (`DOCUMENT_CONTENT_UNCHANGED`), because it would void approvals for no change. The same bytes on another type or Project are allowed (one `document_files` row, many revisions). This is a new rule, so it is **DEC-D4d**. |
| Concurrent creation | Project and revisions are locked `FOR UPDATE` (existing). The UNIQUE (project, type, number) and the guarded supersede UPDATE give a DB guarantee (existing). The basis hash plus the in-transaction precondition refuse a stale preview. Two promotions of identical bytes are idempotent. |
| Ownership | the revision belongs to its Project (FK); the file is shared by content. The Merchant comes from the Project, and the basis binds the Project row (including the Merchant). |
| Recorder attribution | `created_by` = trusted operator, and `document_files.stored_by` = operator (DEC-A0 reuse). The event's `triggered_by` = operator. |
| Approvals | **No authority policy is defined here** (S1/S2 stay PROPOSED). The revision model only guarantees that approvals attach to an immutable, hash-bound revision. |
| Approval invalidation | existing and implicit: a new revision has no approvals, and the old approvals remain as history (NL4D2 `outdated_approvals`). Nothing is deleted. |
| Superseding a **signed** revision | the existing engine allows it, and the signing gate then requires a new signature. Whether that is acceptable, or a signed contract may only be amended through an ADDENDUM type, is **DEC-D4e**. Until it is decided, the NL4D5A preview should report `SIGNED_REVISION_SUPERSEDED` as a policy blocker (POLICY_UNDECIDED, the NL4D3 pattern), not silently allow it. |
| Signed-copy linkage | for D1 (b), the signed copy is **evidence on the same revision**, not a new revision: a `document_signatures` row (NL4D5C) references a `document_files` row for the signed bytes. The store, ingestion and receipt from NL4D5A are reused unchanged. |
| Interrupted writes | see §6. Every partial state is either invisible (staging), harmless (an orphan file) or settled from DB evidence (the claim and ledger). |

---

## 6. Filesystem / PostgreSQL crash consistency

The filesystem and PostgreSQL are **not** jointly atomic. Ordering rules:
- **R1.** Promote the file, flush it (`fsync`; NTFS directory flush is best-effort on Windows) and re-hash it **before** the DB transaction commits.
- **R2.** The DB transaction's precondition re-checks, under the Project lock, that the store file exists and hashes to the bound value.
- **R3.** Nothing is ever deleted automatically.

| Crash point | State left | Consequence | Recovery |
|---|---|---|---|
| During the inbox → staging copy | a partial staging file | invisible; no DB row | staging is swept by age (a separate, explicit maintenance command) |
| After staging, before promote | a complete staging file | invisible | the same |
| After promote, before DB commit (or DB failure, refusal, rollback) | **an orphan store file** | harmless: no row references it; a retry with the same bytes reuses it (content-addressed) | `document verify` reports orphans; deletion is a manual, owner-approved operation (DEC-D4a) |
| During the DB transaction | rollback; the claim is fenced (existing) | attempt FAILED; the orphan file as above | none needed |
| After commit, before the receipt | the committed row and its file | settled SUCCEEDED from the claim and ledger (existing); the receipt is rebuilt from PostgreSQL plus a store re-hash | existing recovery |
| Store file later altered or removed | the row references a mismatched or missing file | **detected, not prevented**:<br>• the file is read-only;<br>• the ACL is restricted to the user;<br>• preflight, precondition and `document verify` re-hash it | an integrity incident; never auto-repaired |
| Inbox file changed between preview and execution | different bytes | the copy's hash ≠ the bound hash, so it is refused (`DOCUMENT_CONTENT_CHANGED`) before any DB write | preview again |

**The invariant:** *every committed managed revision references a file that was promoted and verified before the commit.* The only tolerated inconsistency is an unreferenced file.

---

## 7. Identity and authorization model (reuses NL4C / NL4D4A)

| Element | Design |
|---|---|
| Preview | `evidence preview` (REGISTER_DOCUMENT_REVISION, which already exists from NL4D3) gains an inbox file name. It hashes the bytes and runs the domain engine. It is **read-only** (no copy, no DB write) and its `requested_operation` is NOT_AUTHORIZED, produced for the test database only. |
| Operation binding | `command document revision-create`, `project_id`, `merchant_code`, `document_type`, `inbox_name`, `content_hash sha256:…`, `byte_size`, `media_type`, the expected predecessor (`revision_number` and id, or none), `project_version`, `operator_id`, `expected_basis`, canonical `argv`. The basis covers:<br>• the Project row;<br>• every revision of the type (id, number, hash, signed, `superseded_by`);<br>• the approvals on the active revision;<br>• the file hash;<br>• the operator. |
| Trusted capture | the PostToolUse hook validates the operation, **re-hashes the inbox file itself** and checks the operator against the trusted config. Only then does it create a pending record (`kind document_revision`, its own store, 15-minute TTL, single use). |
| Confirmation | the user's own `/solve Xác nhận …` (the phrase is a decision for A2; it must not collide with existing phrases). Operator and target are checked unspent. A typed `document revision-create` scope is refused at the gate. Scheduled prompts are denied. |
| Revalidation before spend | the preflight checks:<br>• the confirmed record for this run, with argv equal to it;<br>• the operator;<br>• the DB identity;<br>• the migration-008 schema present;<br>• the inbox file still hashes to the bound value;<br>• `verify_document_revision` (basis, engine plan, predecessor, and the D4d/D4e blockers). |
| Ingestion | inside the trusted handoff, after the spend and before the transaction. Copy, then hash the copy; a mismatch refuses and no DB write happens (FAILED, fenced). Then promote. |
| In-transaction revalidation | a new `create_revision(precondition=…)` hook, after the Project and revision locks. It re-runs `verify_document_revision` on the same connection, plus the store-file existence and hash check. |
| Atomic evidence | `evidence_bound_repository`: claim + ledger + `document_files` upsert + revision INSERT + supersede UPDATE + `DOCUMENT_REVISION_CREATED` event, in one transaction |
| Receipt | `document_revision_receipt_v1`, built from the ledger, claim, revision row, file row and event (same `xmin`), plus a read-only store re-hash. It has `recover_*` from PostgreSQL alone. |
| Allowlist | test mode only. `document revision-create` joins `TEST_MODE_COMMANDS` only in A3, gated on a confirmed record, exactly like `procurement update`. Runtime stays disabled, and `document approve` stays out of test mode. |

**No document write is enabled by this design.**

---

## 8. Approval and signing dependencies

| Future checkpoint | Uses from NL4D5A | Still needs (owner decisions) |
|---|---|---|
| **NL4D5B**, approval recording | immutable, hash-bound revisions; the active-revision selection; a preview that shows exactly which revision (and hash) an approval attaches to | **S1** (who may record which role; separation of duties) and **S2** (attestation fields, evidence required). The approval evidence file can reuse `document_files`. |
| **NL4D5C**, external signing evidence | the store and ingestion for the signed copy; `document_files` for `signed_file_id`; the existing `sign_document` flag flip in the same transaction | **D1a** (accept "same revision + evidence"), **D1b** (verify the signed copy against the approved revision, or only store it), **D1c** (runtime grant, deferred), **D4e** (superseding signed revisions) |
| **NL4D5C-P**, Purchase Order / Payment Request | a signed active revision (existing `_require_signed_document`), produced only by NL4D5C | NL4D5C complete; P1a/P1c already approved (the same uniqueness and create-only pattern applies) |
| **NL4D5D**, evidence-gated Step completion | revisions of the right type (for example UAT_ACCEPTANCE for step 21), approvals and signatures | **G1** and **G2** (gated steps, REJECTED semantics, template versioning) and **D4g** (document type allowlist) |

---

## 9. Test strategy

| Level | Coverage |
|---|---|
| Storage unit (no DB) | the cases below, each on a temporary store and inbox |
| Ingestion attacks | `..`, absolute paths, UNC, drive letters, an ADS `name:stream`, a **symlink** and a **junction** in the inbox, a hardlink, a directory, an empty file, an over-limit file (streamed), an extension/magic mismatch, a DOCX without `[Content_Types].xml`, a file changed between hash and copy (TOCTOU), concurrent identical promotions, an existing target with different bytes (must refuse and alert, never overwrite) |
| Crash injection | every row of §6, by monkeypatching after each step:<br>• no committed row without a file;<br>• orphans only;<br>• the claim fenced;<br>• never retried. |
| Domain and policy | initial and next revision; supersede; a concurrent second revision (exactly one); `DOCUMENT_CONTENT_UNCHANGED` (if D4d); a signed predecessor gives POLICY_UNDECIDED (until D4e); a terminal Project; type pattern and allowlist (if D4g) |
| Authorization (NL4D4A suite pattern) | a forged or edited capture; a different inbox hash at capture; an operator missing, changed or model-supplied; a handwritten scope; a wrong target; replay, expiry, wrong session; runtime refused; Step/PR/Project stores never confirm a document |
| PostgreSQL end to end | preview, capture, confirm, preflight, ingest, transaction and receipt through the real hooks, on disposable `PYTEST_NL4D5A_` fixtures and a temporary store; plus:<br>• crash before and after commit;<br>• ledger failure;<br>• the inbox file changed after confirmation;<br>• the store file corrupted before commit;<br>• recovery from PostgreSQL alone;<br>• no Step transition. |
| Migration 008 | a rolled-back dry run, then an audit (the NL4D4A §15.2 method):<br>• the composite FK;<br>• legacy rows untouched;<br>• NOT VALID behaviour;<br>• rerun refused;<br>• the documented reversal. |
| Regression | the full suite (baseline 4526), sequential PostgreSQL, `system_test`, hook smoke, `git diff --check` |

---

## 10. Owner decisions (original proposal and recorded status)

| ID | Question | Original proposal (this design) | Status (register, verbatim there) | Blocks |
|---|---|---|---|---|
| **DEC-D4** | Storage model | **Option B**: a managed local immutable content-addressed store plus `document_files` metadata | **APPROVED — LOCAL TEST MVP** 2026-11-11: immutable local store with PostgreSQL metadata | A1 |
| **DEC-D4a** | Store location, inbox location, backup, orphan deletion | configured `MERCHANT_DOCUMENT_STORE` and `MERCHANT_DOCUMENT_INBOX` outside the repository and any sync folder; DB backup first, then the store; orphans deleted only manually after `document verify` | **APPROVED**: outside the repository; **store backed up before the DB snapshot**; manual orphan cleanup only | A1 |
| **DEC-D4b** | Allowed media types and size limit | PDF, DOCX, PNG, JPEG (by magic bytes); 25 MB | **APPROVED**: PDF/DOCX/PNG/JPEG, 26,214,400 bytes | A1 |
| **DEC-D4c** | Keep the original filename? | store only its SHA-256 (filenames can be sensitive) | **APPROVED**: identity = SHA-256; filename only as **sanitized metadata**, never a path | A1 |
| **DEC-D4d** | Duplicate content | refuse a new revision identical to the active one; allow the same bytes elsewhere | **APPROVED**: reject a revision matching the current active revision | A2 |
| **DEC-D4e** | May a signed revision be superseded? | not decided. Until then the preview returns POLICY_UNDECIDED for a signed predecessor | **APPROVED**: do not supersede a signed revision until a signing lifecycle policy is approved | A2 |
| **DEC-D4f** | Legacy hash-only revisions | keep them readable and unmanaged; all new revisions must be managed (NOT VALID check) | **APPROVED**: UNVERIFIED_LEGACY; no migration, no fabricated files, never verified evidence | A1b |
| **DEC-D4g** | Document type allowlist | none until the business list is given (the existing pattern stays) | **APPROVED**: canonical types already recognized by the domain (the list is still to be identified) | A2 |
| DEC-A0 | Recording operator | already APPROVED (2026-11-11); reused | APPROVED | — |
| S1, S2, D1a–c, G1, G2, P1b | approvals, signing, gates, reference formats | stay PROPOSED; not needed for NL4D5A | **PROPOSED** | NL4D5B, 5C, 5D |

---

## 11. Checkpoints and GO/NO-GO

### 11.1 Proposed order (adjusted)

| Checkpoint | Scope | Writes enabled |
|---|---|---|
| **NL4D5A1a**, storage module (filesystem only) | config validation (store and inbox outside the repository and sync folders), safe resolution, streamed hashing, magic-byte typing, staging, idempotent promotion, read-only attribute, `document verify` (read-only); the attack and crash unit tests | none (no DB) |
| **NL4D5A1b**, schema | migration 008 (`document_files`, composite FK, optional deferred EXCLUDE, NOT VALID check per D4f), dry run, test-DB apply, audit | none |
| **NL4D5A2**, trusted preview and confirmation | the preview gains file binding (read-only); `verify_document_revision`; `create_revision(precondition)`; the pending kind and phrase; gate, capture and preflight; the D4d/D4e blockers | none (execution not allowlisted) |
| **NL4D5A3**, automated execution | trusted ingestion inside the handoff; test-mode allowlist (confirmed record only); receipt and recovery; the full RED/GREEN and PostgreSQL end-to-end suites | test database only, confirmed only |
| **NL4D5A4**, controlled live acceptance | one disposable Project, one file, one preview, confirmation and execution; independent read-back including a store re-hash | test database only |

The change from the requested order is that **A1 is split into A1a and A1b**. The filesystem module can be built and attack-tested with no database or authority change, and the migration then lands as its own reviewable step. Every checkpoint keeps `RUNTIME_DIRECT_EXECUTE_ENABLED = False` and leaves `document approve` and signing non-executable.

### 11.2 GO/NO-GO for NL4D5A1

> **Status update 2026-11-12:**
> - These decisions were recorded on 2026-11-11.
> - NL4D5A1a was implemented and committed as `d7c15d1`.
> - NL4D5A1b (migration 008) is the current checkpoint.
>
> The original assessment follows.

**NO-GO to implement now.** GO once the owner records:
- **DEC-D4** (Option B);
- **DEC-D4a** (store and inbox location, backup, orphans);
- **DEC-D4b** (types and size);
- **DEC-D4c** (filename);
- **DEC-D4f** (legacy rows).

D4d, D4e and D4g are needed before A2, not A1. NL4D5B, C and D remain blocked on S1/S2, D1 and G1/G2 respectively.

**Unchanged by this design:**
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`;
- the test-mode allowlist;
- the grants and the schema.

# CP12H.NL4D5A1b — Document Metadata Schema & Migration 008

Branch `feat/cp7-9-merchant-reliability`. Date 2026-11-12.

- **Baseline:** implementation `d7c15d1` (NL4D5A1a). Phase 1 then committed the design document separately, so HEAD is now **`c7f0933af2e1af5551f99fbfc6608890d10a04e5`** ("docs(merchant): record managed document revision architecture").
- **Migration 008:** applied to **`coding_agent_merchant_test` only**.
- **Runtime database:** never connected or migrated.
- **Not done:** no document revision execution, no live write.
- **Not committed:** migration 008, its tests and this report are uncommitted, as instructed.
- **Runtime Direct EXECUTE:** still disabled (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`).

**Phase 1, the design document check.**
- **What it got right:** existing behavior (§1) and its proposals.
- **What was stale:** it still said "DEC-D4 is not approved" and "(none approved)", and it omitted P1b.
- **What was added:** a dated status note separating:
  - existing behavior;
  - the approved DEC-D4 and D4a–g (with each approval's difference from the original proposal);
  - the proposed architecture;
  - the unresolved S1, S2, D1, G1, G2 and P1b.

  §10 now shows the original proposal and the recorded status side by side.
- **Commit:** it was committed alone.

## 1. Actual schema audit (read-only, test database)

**Environment:**
- **Server:** PostgreSQL 16.15.
- **Session:** `coding_agent_merchant_test` / `merchant_test` (owner), read-only.
- **Roles:** `merchant_app`, `merchant_alert`, `merchant_owner`, `merchant_test`.
- **Migrations:** 1–7 (007 = procurement reference uniqueness). No default privileges.

**`document_revisions`:**
- **Columns (12):** `id, project_id, document_type, revision_number, content_hash TEXT NOT NULL, signed, signed_at, effective_date, expiry_date, superseded_by, created_at, created_by`.
- **Constraints:**
  - PK;
  - FK `project_id → projects`;
  - FK `superseded_by → document_revisions`;
  - CHECK revision > 0;
  - CHECK signed ⇔ signed_at;
  - CHECK expiry > effective;
  - UNIQUE (project_id, document_type, revision_number).
- **Indexes and triggers:** one extra index (project, type, number); no triggers.
- **Grants:**
  - `merchant_app`: INSERT/SELECT on every column, UPDATE on `superseded_by` only;
  - `merchant_alert`: SELECT.

**Referenced by:**
- `document_approvals.document_revision_id` (FK);
- `projects.reused_document_revision_id` (FK);
- itself (`superseded_by`).

**`content_hash`:** **free text.** The engine requires only that it is non-blank; nothing computes or verifies it, so it was never assumed to be a SHA-256.

**Existing data (test database):**
- **0** document revisions;
- **0** approvals;
- **0** Projects reusing a revision;
- **0** document events.

**Nothing therefore had to be classified, transformed or matched.** The migration is still written for non-empty tables (§3).

**Writers of `document_revisions`:**
- `document_repository.create_revision`: INSERT, plus `superseded_by` UPDATE;
- `signing_repository.sign_document`: `signed`/`signed_at` UPDATE (no CLI, no runtime grant).

**Readers:**
- the domain engines (document, approval, signing, procurement);
- `gates`;
- `read_repository`, `repository`, `transition_repository`, `approval_repository`, `procurement_repository`, `signing_repository`, `workflow_repository`;
- `evidence_status`, `evidence_preview`, `project_status`, `step_preview`, `purchase_request` and `checker`;
- `catalog_initializer`, `runtime_readiness` and `runtime_verification`.

**Every reader selects explicit columns. There is no `SELECT *`.** The new columns therefore change no existing read, Step/PR basis hash or API output.

**Consumers potentially affected by migration 008:**

| Consumer | Effect | Action |
|---|---|---|
| `document_repository.create_revision` (INSERT without the new columns) | rows default to `UNVERIFIED_LEGACY` | correct: the free-text path can never create trusted evidence |
| `signing_repository` (UPDATE `signed`, `signed_at`) and supersede UPDATE (`superseded_by`) | allowed; the immutability trigger checks only content and evidence columns | none (tested) |
| Test fixtures that DELETE revisions | no trigger on DELETE of revisions | none |
| `runtime_readiness.EXPECTED_TABLES` (exact runtime table set, opt-in live checks only) | would need `document_files` **if** runtime were ever migrated | record for a future runtime migration plan; runtime is not migrated |
| Approval/signing engines, `gates`, `procurement_engine._require_signed_document` | still accept `UNVERIFIED_LEGACY` revisions | **must fail closed before managed evidence becomes executable** (NL4D5A2/A3); unchanged here |
| `evidence_preview` (`CONTENT_HASH_UNVERIFIED` note), `evidence_status`, `read_repository`, the revision resolver | do not yet expose `evidence_status` | NL4D5A2 should surface it |

## 2. Migration 008 design

The migration is `.claude/clients/merchant/migrations/008_document_file_metadata.sql`. Its checksum is `83547cf858e855b58ad320763dd30202abb4c6620f8f0aaff10f0d70fda668b3`, and it has 9 statements.

**`merchant_ops.document_files`** holds one content-addressed blob of the immutable store:

| Column | Constraint |
|---|---|
| `id UUID` PK | trusted identity (generated by the future write path) |
| `sha256 CHAR(64)` | `^[0-9a-f]{64}$`; **UNIQUE** |
| `content_hash TEXT` | must equal `'sha256:' || sha256` |
| `byte_size BIGINT` | 1 – 26,214,400 (DEC-D4b) |
| `file_type`, `media_type` | exactly PDF/`application/pdf`, DOCX/WordprocessingML, PNG/`image/png`, JPEG/`image/jpeg` |
| `storage_key TEXT` | must equal `'sha256/' || substr(sha256, 1, 2) || '/' || sha256`, the same layout as `document_store`; **UNIQUE** |
| `created_by UUID NOT NULL` | the trusted operator (DEC-A0) |
| `verified_at TIMESTAMPTZ NOT NULL` | when `document_store` verified the bytes at ingestion |
| `created_at` | default `now` |
| `UNIQUE (id, content_hash)` | the target of the composite FK |

**`document_revisions` gains:**

| Column | Rule |
|---|---|
| `evidence_status VARCHAR(30) NOT NULL DEFAULT 'UNVERIFIED_LEGACY'` | CHECK ∈ {`UNVERIFIED_LEGACY`, `MANAGED`} |
| `document_file_id UUID` | CHECK `(evidence_status = 'MANAGED') = (document_file_id IS NOT NULL)` |
| `original_file_name TEXT` | allowed only on MANAGED rows: 1–200 characters, trimmed, NFC, and no control characters or `< > : " / \ | ? *` (DEC-D4c: sanitized metadata, never a path) |
| FK `(document_file_id, content_hash) → document_files (id, content_hash)` | a MANAGED revision must reference an existing file **with the same hash**; MATCH SIMPLE, so legacy rows are not checked |
| index `document_revisions_document_file_idx` | partial, on managed rows |

**Triggers:**
- `document_files_immutable` refuses UPDATE and DELETE of file metadata.
- `document_revisions_evidence_immutable` refuses any change to `content_hash`, `evidence_status`, `document_file_id` or `original_file_name` after insert. Other updates still work: `superseded_by`, `signed`/`signed_at`.

**Grants:** `merchant_app` gets **SELECT only** on `document_files`. INSERT is deliberately deferred to NL4D5A3, as a separate, reviewed grant.

**Preserved unchanged:**
- every existing column, value, constraint and index;
- revision uniqueness;
- supersede semantics;
- approval and signing tables and behavior;
- Projects and Steps.

## 3. Legacy compatibility and evidence trust (DEC-D4f)

- **Existing rows:** each revision is `UNVERIFIED_LEGACY` through the column default. No value is changed; on PostgreSQL 11+ a constant default adds no rewrite.
- **No backfill and no hash matching:**
  - no `document_files` row is created;
  - a legacy revision whose `content_hash` happens to look like `sha256:<hex>`, or equals an existing file's digest, **stays `UNVERIFIED_LEGACY`**.
  - The test `legacy_revisions_stay_unverified_and_unchanged` inserts both a matching file and a SHA-shaped legacy hash.
- **No retroactive upgrade.** Changing a legacy row to MANAGED, linking a file, changing its hash or adding a filename are all refused (`a_legacy_revision_can_never_be_upgraded`). This holds for every role, owner included, unless the trigger is explicitly dropped.
- **Old write path.** New rows written by the existing `create_revision` path are also `UNVERIFIED_LEGACY`.

## 4. SHA-256 and file reference constraints

| Requirement | Enforcement |
|---|---|
| Valid SHA-256 | format CHECK (lowercase, 64 hex) |
| Content hash derived, never contradictory | CHECK `content_hash = 'sha256:' || sha256` |
| Storage key derived, never a filename | CHECK on the exact content-addressed layout |
| No duplicate or contradictory identity | UNIQUE `sha256` and UNIQUE `storage_key`; identity is the PK |
| A managed revision binds to its matching hash | composite FK (file id, content hash) |
| No reference to a nonexistent file | the same FK |
| MANAGED ⇔ a file reference | CHECK |
| Size and type | CHECKs per DEC-D4b |

## 5. Ownership model

| Identity | Scope |
|---|---|
| Blob (bytes in the store) | global, content-addressed by SHA-256 (`document_store`) |
| File metadata (`document_files.id`) | **global**, one row per blob (UNIQUE `sha256`) |
| Revision (`document_revisions.id`) | **Project-owned** (FK `project_id`), so Merchant-owned through the Project |
| Original filename | per revision (the same bytes can be uploaded under different names by different Projects) |

**Deduplication is safe** because a file row carries no ownership or authority. **A shared SHA-256 never implies access**: every read and every future authorization goes through the Project's revision. Test `one_blob_may_back_revisions_of_different_projects`.

A revision can only link to a file whose hash equals its own `content_hash` (composite FK), so it cannot link to an unrelated or inconsistent file record. Because a file record is pure content identity, no cross-Project constraint is needed on the file itself.

## 6. PostgreSQL dry-run evidence

**Before:**
- integrity hash `99abfa8e…`;
- no other sessions;
- no pytest lock;
- migrations 1–7.

**Dry run** (`nl4d5a1b_dryrun.py`; one transaction, always rolled back): **9/9 PASS.**
- All 9 statements executed.
- The three revision columns were added.
- Every existing revision was `UNVERIFIED_LEGACY`.
- `document_files` was empty (no backfill).
- All 14 expected constraints and both triggers were present.
- `merchant_app` had SELECT only.
- Projects, Steps, revisions, approvals, procurement, claims, ledger and events were identical inside the migration.
- After rollback, the schema and rows were exactly as before; the hash was `99abfa8e…`, unchanged.

## 7. Migration application evidence

| Step | Result |
|---|---|
| Runner `--plan --database test` | applied 1–7; pending `(8, document_file_metadata, 83547cf858e8…)`; no checksum conflicts; no errors |
| Runner `--apply --database test` | success; applied 1–8; nothing pending |
| Bookkeeping | `schema_migrations` = 1..8 with no gap; the row-8 checksum equals the file (`83547cf8…`) |
| Reapplication | refused: `DuplicateTable` at the first statement, inside a rolled-back transaction; the row-8 count stays 1 (test) |

## 8. Constraint tests (RED/GREEN)

The tests are in `tests/merchant/test_nl4d5a1b_migration_008_postgres.py`: **42 tests**. Each runs in one transaction that is always rolled back, with a disposable Merchant and two Projects inserted inside it; nothing commits, and the live acceptance Projects are never used.

| Run | Result |
|---|---|
| **RED** (before migration 008 existed in the database) | **41 failed, 1 passed** (the FK-to-nonexistent-Project case, which already held) |
| **GREEN** (after apply) | **42 passed**, three consecutive runs |

**One weak test was found and fixed.** The first concurrency test could pass without proving anything: the blocked second insert hit the 5 s lock timeout and was silently accepted by an "either outcome" assertion. It is now deterministic:
- transaction A holds an uncommitted identity;
- transaction B, with `lock_timeout = 500ms`, must be **blocked**;
- both roll back;
- the file count is 0 afterwards.

PostgreSQL's unique-index semantics turn B into a unique violation if A commits, so at most one can commit.

**Coverage of the Phase 7 list:**
- valid metadata, and the exact size limit;
- invalid SHA-256 (3 cases);
- contradictory hash or storage key, including `../`;
- size 0, −1 and 25 MiB + 1;
- unsupported or inconsistent types (5);
- duplicate identity;
- metadata immutability (UPDATE and DELETE);
- legacy compatibility, and no hash-match trust;
- no legacy upgrade (4 columns);
- managed binding; wrong hash association; missing file reference;
- inconsistent classification (3); file without MANAGED;
- unsafe filenames (7: traversal, backslash, colon, padding, control character, too long, non-NFC);
- cross-Project blob sharing;
- revision lifecycle preserved (supersede and uniqueness);
- approval and signing compatibility;
- FK violations;
- concurrent conflicting inserts;
- migration checksum consistency;
- reapplication refused, with rollback;
- grants are SELECT only.

## 9. Full regression

Sequential; runtime credentials blanked; no live `/solve`.

| Run | Result |
|---|---|
| Migration 008 tests | 42 passed |
| First full run after applying | **2 failed**, 4674 passed, 21 skipped, 1 xfailed |
| Final full run | **4676 passed, 21 skipped, 1 xfailed, 0 failed** (97 subtests), 6 min 06 s; 4676 = 4634 + 42 new |
| `system_test.py` | ALL TESTS PASSED |
| Hook compile/import | OK; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean |

**The two first-run failures.** They were the two tests that hard-code the discovered migration list (`test_alert_delivery_lease_migration.py`, `test_project_payment_period_migration.py`). They were investigated: both assert the exact list of migration files, so adding 008 makes them stale, exactly as when 007 was added. They were updated to include `(8, "document_file_metadata")`; no other test changed.

## 10. New database integrity baseline

| Item | Value |
|---|---|
| Full post-migration hash | **`79cfe197dae54d4edb6bea4e4c9f84596d990b21be417bf83e6afff11133d1fd`** (the new accepted baseline once accepted) |
| Equivalence hash: the same algorithm, excluding only migration 008 (`document_files`, `schema_migrations` row 8, the three new revision columns) | **`99abfa8e56c2da686b276127310d7e28ae4c80ab78b351b78f8a407b38f33f8a`**, which reproduces the accepted pre-migration baseline **exactly** |
| Migration 008 checksum | `83547cf858e855b58ad320763dd30202abb4c6620f8f0aaff10f0d70fda668b3` |
| Tables | 18 (17 + `document_files`) |
| Legacy revisions | 0 (no revisions exist) |
| Managed revisions | 0 |
| `document_files` rows | 0 |
| Projects, Steps, approvals, procurement | unchanged (covered by the equivalence hash); NL4C2B step 1 IN_PROGRESS v2 |
| Claims / ledger | 22, all COMPLETED / 6; no orphan; none new |
| Pending confirmations | 5 earlier, CONFIRMED and expired; none new |

**Constraint inventory:**
- `document_files`: PK, 3 UNIQUE (`sha256`, `storage_key`, `(id, content_hash)`), 5 CHECK.
- `document_revisions`: the 7 original constraints, plus 3 CHECK and 1 composite FK.
- Indexes and triggers as listed in §2.

## 11. Runtime database isolation

- **The runner:** invoked only with `--database test`. Every repository in this checkpoint was `role="test"`, with the database asserted to be `coding_agent_merchant_test`.
- **The runtime database:** never connected, so it is unmigrated. Its schema remains 1–7 as last verified at NL4D4A; it was not inspected here.
- **Execution:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.
- **Allowlists unchanged:**
  - the write-command list;
  - test mode (`merchant create`, `project create`, `step update`, `procurement update`).

  No document command is enabled.

**Storage boundary (Phase 8):**
- `document_store.py` remains the only file-byte verification layer, and no Merchant code imports it.
- A `document_files` row records ingestion-time verification only. It **does not prove the file exists now**; only `document_store.verify_object` does, and a row with a valid hash is not a verified file.
- No CLI write command, no trusted scope, and no approval or signing permission was added.

## 12. Backup-gap risks and proposed procedure (Phase 11; nothing implemented)

**The gap.**
- The filesystem and PostgreSQL commit independently; they are **not atomic**.
- The NL4D5A3 write order will be: promote and verify the blob, then commit the revision. So a committed row always has a blob at commit time, but an orphan blob may exist without a row.
- DEC-D4a backs up the store **before** the DB snapshot. A revision committed between the two copies references a blob absent from the store backup.

**Proposed procedure** (an owner decision is needed to adopt it):
1. **Freeze document writes:** confirm no document execution is running.
2. **Store copy (pass 1).** Copy `objects/` (append-only, read-only files). Record a **backup manifest**: every `sha256`, size and storage key, plus the store root and timestamp.
3. **Database snapshot.** `pg_dump` of the test or runtime database, recording the server timestamp and the `schema_migrations` state.
4. **Store copy (pass 2, incremental).** Copy any objects added since pass 1, and append them to the manifest. This closes the gap whether or not writes were frozen.
5. **Consistency verification.** Every `document_files.sha256` in the dump must appear in the manifest, and every manifest entry must re-hash correctly (`document_store.inventory` / `verify_object` on the backup copy).
6. **Restore validation.** Restore the DB and store into an isolated location. Run `inventory(referenced = all document_files hashes)`. Expect zero MISSING or CORRUPT, and accept any ORPHANED_FINALIZED.
7. **Read-only integrity scan.** Schedule `inventory` as a read-only scan; report, never repair.

**Missing-blob behaviour (proposed).** A revision whose blob is MISSING or CORRUPT:
- stays in the database;
- is reported;
- is treated as **unverified evidence** by every consumer, which fail closed (NL4D5A2/A3).

There is no automatic repair or re-ingestion.

**Orphan files:** manual review and deletion only (DEC-D4a). They are reported as ORPHANED_FINALIZED and never deleted automatically.

**Owner decisions needed before NL4D5A2/A3:**
- adopt this two-pass (or write-freeze) backup procedure;
- the scan frequency;
- where backups and manifests live.

## 13. Remaining decisions and risks

1. **DEC-D4g canonical document-type list.** It is still unidentified; it is required before NL4D5A2 enforces it.
2. **The backup procedure (§12).** It must be adopted before NL4D5A3.
3. **A future grant.** The `document_files` INSERT grant for `merchant_app` will come as a separate migration in NL4D5A3.
4. **Fail-closed integration** of approval, signing, gates and the procurement signed dependency for `UNVERIFIED_LEGACY` revisions. It is required before managed evidence is executable; this checkpoint does not change their behaviour (§1).
5. **A runtime migration** would need a separate approved plan:
   - a read-only audit of the runtime revisions (their real `content_hash` values);
   - an update of `runtime_readiness.EXPECTED_TABLES`;
   - the DEC-D4a backup.
6. **The trigger is not a security boundary against the owner.** The owner can drop it. It protects against application roles and accidental updates.
7. **S1, S2, D1, G1, G2 and P1b remain PROPOSED.**

## 14. GO / NO-GO for NL4D5A2

- **NL4D5A1b: GO for acceptance review.** Migration 008 is applied and audited on the test database, the regression is clean, and the business data is provably unchanged. It is uncommitted.
- **NL4D5A2 (trusted preview and confirmation): NO-GO until all of these are done:**
  1. NL4D5A1b is accepted and committed.
  2. The **DEC-D4g canonical document-type list** is identified from domain artifacts and approved.
  3. The approach for **making approval, signing and gates fail closed** on `UNVERIFIED_LEGACY` and unverifiable revisions is decided (it can be implemented in A2 alongside the preview).
  4. You explicitly authorize starting NL4D5A2.

  The backup procedure (§12) is needed before NL4D5A3, not A2.
- **Still NO-GO:** runtime migration, runtime Direct EXECUTE, and any document, approval or signing write.

## 15. Final acceptance (CP12H.MASTER Phase A, 2026-11-12)

This is the final review, run before the commit (the earlier final-acceptance pass was stopped before it ran).

**Schema checks** (read-only, test database): **all PASS.**
- Migrations 1–9 are applied. 009 followed in CP12H.NL4D-S1.
- Every applied checksum equals its file. 008 = `83547cf8…`.
- All 008 constraints are present and validated, and the composite FK definition is exact.
- The unique indexes on `document_files` (pkey, `sha256`, `storage_key`, `(id, content_hash)`) are valid and ready.
- Both immutability triggers are enabled.
- **Grants:** `merchant_app` has SELECT only (INSERT, UPDATE, DELETE and TRUNCATE all false). Owner privileges belong to the test-database owner `merchant_test`.
- `merchant_app` keeps its table-level INSERT on `document_revisions` (migration 0003), which covers the new columns. It still cannot create a MANAGED row without a `document_files` row, which it cannot insert. The NL4D5A3 grant review must keep this in mind.

**Data:** 0 revisions, approvals and files. Claims are 22 COMPLETED; the ledger has 6 rows, each with its claim. NL4C2B Step 1 is IN_PROGRESS v2, and there is no PYTEST residue. Every pending confirmation is CONFIRMED and expired.

**Hashes:**
- The full hash is `ada0d51db2c2c0cab3b73c608625e1a4cddc1a2d6ec318f7f3878ec9d496483e` (the post-009 baseline).
- The business-only hash, excluding 008 and 009, reproduces `99abfa8e56c2da686b276127310d7e28ae4c80ab78b351b78f8a407b38f33f8a`.

**Concurrency** (three tests added, all in rolled-back transactions):
- **A. A completed first insert, then a conflicting second one:** UniqueViolation, whether the second reuses the same id or uses a new id with the same identity. A real cross-session COMMIT is not exercised, because a committed `document_files` row is immutable and would persist.
- **B. The first transaction rolls back:** the waiting second insert proceeds. The wait is proven with `pg_blocking_pids`.
- **C. Unique identity indexes:** valid and ready.

The 008 suite has **45 tests, all passing.**

**Legacy consumer audit.** Superseded by DEC-SIMPLIFY (owner-approved 2026-11-12; see `cp12h_nl4d_s1_simplified_policy_and_migration_009.md`).
- Approval, signing, the gates and procurement **may** accept non-MANAGED revisions.
- The requirement is now labelling: a non-MANAGED revision is never presented as a verified file.
- No execution route was exposed by 008.

**Verdict: ACCEPTED.** It is committed before 009.

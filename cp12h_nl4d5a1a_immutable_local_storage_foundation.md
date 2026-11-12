# CP12H.NL4D5A1a — Immutable Local Document Storage Foundation

Baseline `91ad86679a68e6ba3818b9456fcc5d7027423acd`, branch `feat/cp7-9-merchant-reliability`. Date 2026-11-12.

- **Committed after the final review (§15); not pushed.**
- **No migration 008**, no database write, no live `/solve`.
- **Runtime Direct EXECUTE:** still disabled (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`).
- **Not connected:** the storage module is isolated; no Merchant execution path calls it.

**Baseline check (Phase 1).**
- **Git:** HEAD `91ad866`, 17 ahead and 0 behind.
- **Pre-existing untracked file:** `cp12h_nl4d5a_document_revision_design.md` (the NL4D5A-DESIGN deliverable), preserved.
- **NL4D4A files:** some were reported as touched on disk, but they are byte-identical to HEAD (`git status` showed no change).
- **Test database:** `99abfa8e…`, migrations 1–7, 22 COMPLETED claims, 6 ledger rows.
- **Discrepancy:** DEC-D4g refers to "canonical document types already recognized by the existing domain", but the domain enumerates **no** type list (only the pattern `^[A-Z][A-Z0-9_]{0,99}$`). This is recorded in the register; no list was invented.

## 1. Updated decision register (Phase 2; committed with this checkpoint, §15.9)

`cp12h_nl4d_decision_register.md` now records **DEC-D4 and DEC-D4a–g as APPROVED — LOCAL TEST MVP, 2026-11-11**, in the owner's wording, in three places:
- the header status;
- the D4 entry;
- the §4 table (one row each).

It states explicitly that **these storage approvals authorize no document write**.

- **Kept PROPOSED:** S1, S2, D1, G1 and G2 (and P1b).
- **D4d–g:** recorded as future domain contracts for NL4D5A2/A3; this module does not enforce them.

**Flag for the owner: DEC-D4a backup order.**
- **The approved order:** back up the store before the database snapshot.
- **The gap it leaves:** a revision committed *between* the two copies would reference a file absent from the store backup.
- **Why it is easy to close:** the store is append-only and content-addressed.
- **Compatible mitigations** (they keep the approved order):
  - pause document writes during the backup; or
  - after the DB snapshot, take a second, incremental store copy;
  - in either case, run `inventory`/`verify` on the restored pair.
- **Recommendation:** record one of these in the D4a operating procedure before NL4D5A3. Nothing was changed here.

## 2. Storage module architecture

The module is `.claude/clients/merchant/document_store.py`. It uses the standard library only (`hashlib`, `os`, `stat`, `zipfile`, `zlib`, `struct`, `uuid`), with no new dependency and no framework.

| Interface | Purpose |
|---|---|
| `StoreConfig.from_env()` / `StoreConfig.validated(inbox, store)` | validated roots; creates only `staging/` and `objects/sha256/` under the configured store |
| `validate_file_name(name)` | the only accepted identifier: a bare inbox file name, which is also the sanitized metadata |
| `inspect(config, name)` | **read-only**: resolve, validate type and structure, stream-hash; writes nothing (for the NL4D5A2 preview) |
| `ingest(config, name, *, expected_sha256=None)` | copy, then flush, re-hash, validate, promote with no overwrite, then verify; returns a `StoredObject` |
| `StoredObject` | `object_id` (`sha256:<hex>`), `sha256`, `storage_key` (`sha256/<aa>/<hex>`), `byte_size`, `file_type`, `media_type`, `original_name`, `integrity = VERIFIED`, `reused` |
| `object_path(config, sha256)` / `verify_object(config, sha256)` | re-hash a stored object: VERIFIED, MISSING or CORRUPT; never repairs |
| `inventory(config, referenced)` | classifies every entry against an authoritative reference set; read-only |
| `sweep_staging(config, older_than_seconds)` | the only deletion: abandoned `ingest-*.part` temporary files older than the threshold (**at least 3,600 s**, after the §15 review); never `objects/` |
| `DocumentStoreError.reason` | stable failure codes (§4–§9) |

**Integration boundary:** there is no PostgreSQL, no repository, no hook, no pending store and no authorization. A test asserts the source contains none of these symbols:
- `psycopg`, `MerchantRepository`;
- `merchant_pending_confirmation`, `merchant_direct_handoff`, `TEST_MODE_COMMANDS`;
- `document_revisions`, `record_pending`, `execution_claims`, `project_events`.

## 3. Exact files changed

| File | Change |
|---|---|
| `cp12h_nl4d_decision_register.md` | modified: D4 and D4a–g approved (Local Test MVP) |
| `.claude/clients/merchant/document_store.py` | **new**: the storage module |
| `tests/merchant/test_nl4d5a1a_document_store.py` | **new**: 108 tests plus 1 privilege-dependent skip (102 initially, plus 6 from the §15 review) |
| `cp12h_nl4d5a1a_immutable_local_storage_foundation.md` | **new**: this report |

**Nothing else changed:**
- no domain, repository, hook, CLI, migration, grant, agent or `CLAUDE.md` change;
- `.env` untouched;
- no store configured by default.

## 4. Configuration contract (DEC-D4a)

| Variable | Meaning |
|---|---|
| `MERCHANT_DOCUMENT_INBOX` | the directory where the user places files to register |
| `MERCHANT_DOCUMENT_STORE` | the store root; contains `staging/` and `objects/sha256/<aa>/<hex>` |

Both come only from local configuration (the environment or `.env`, like `MERCHANT_OPERATOR_ID`). Neither is set today.

**`validated()` refuses (`CONFIG_INVALID`):**
- an unset, blank, padded or relative path;
- a UNC path;
- a missing path, or one that is not a directory;
- a root that is itself a symlink or junction;
- **any link in the ancestry** (the normalized `realpath` must equal the path);
- inbox = store, or one nested in the other;
- **anything inside the repository** (which covers `.claude/runtime`), or the repository inside it;
- anything inside a OneDrive sync root (`OneDrive`, `OneDriveCommercial`, `OneDriveConsumer`);
- a `staging/` or `objects/` that is a link;
- `staging/` and `objects/` on different volumes (`st_dev`), so atomic rename is guaranteed.

It never writes into the repository or runtime directories.

## 5. Windows filesystem security analysis

| Threat | Control | Test |
|---|---|---|
| Model-supplied paths | only a bare name is accepted, joined to the configured inbox; the request never names a directory | `path_traversal…` (21 cases) |
| Traversal and absolute paths (`..`, `C:\`, `C:a`, `\\server`, `dir/`) | separators, `:`, wildcards and control characters are refused | same |
| Alternate data streams (`a.pdf:evil`, `::$DATA`) | `:` refused | same |
| Reserved device names (CON, NUL, COM1–9, LPT1–9, superscript variants, `CONIN$`) | refused case-insensitively, with any extension | `reserved_windows_names…` |
| Trailing dot or space (Win32 name normalization) | refused | `path_traversal…` |
| Unicode look-alikes and normalization | NFC required; NFD is refused, so one name maps to one byte string | `unicode_names…` |
| Junctions and reparse points | `os.lstat` plus `FILE_ATTRIBUTE_REPARSE_POINT`, and the `realpath` parent must be the inbox | `junctions_and_reparse_points…` (real NTFS junction) |
| Symlinks | the same check (`S_ISLNK`) | `symlinks…` (**skipped**: this machine lacks the symlink privilege, WinError 1314; the junction case covers the same code path) |
| Hard links to files elsewhere | `st_nlink` must be 1 | `hard_links…` |
| Directories and special objects | `S_ISREG` required | `missing_files_and_directories…` |
| Swapping the entry between check and open | after `open`, `fstat` must equal the earlier `lstat` (inode, device, size, mtime) | `source_replaced_between_validation_and_open…` |
| Modification during the copy | `fstat` after the copy and `lstat` of the entry must still match; the copied size must equal the original | `source_modified_during_copy…` |
| Bytes changed after copying | the staged file is re-hashed from disk and must equal the copy-time hash | `hash_mismatch…` |
| Overwriting stored content | promotion uses `os.rename` (MoveFileEx **without** REPLACE_EXISTING), which raises `FileExistsError` and never replaces | `existing_destination…never_overwritten`; mutation RED |
| Corrupted or colliding object at the hash path | re-hashed before reuse; a mismatch is `INTEGRITY_FAILURE`, never overwritten | same |
| Permission errors | `PERMISSION_DENIED` (inbox or staging); stored objects get a bounded sharing-violation retry, then `PERMISSION_DENIED` | `permission_errors…`, `persistent_permission_error…` |

**Unavoidable limits (documented, not hidden):**
- **Same-size rewrites inside one clock tick.** A same-user process can rewrite a source file in place with the same size *within the same filesystem timestamp tick*, and the metadata check cannot see it. The stored object is then still internally consistent (its bytes are exactly the bytes hashed), but may not be the bytes the user last saw. NL4D5A2/A3 close this for the write path, because `ingest(expected_sha256=<previewed hash>)` refuses any different content (`CONTENT_MISMATCH`).
- **The read-only attribute is not an ACL.** A same-user process can clear it and alter an object. That is **detected** (`verify_object` / `inventory` give CORRUPT), not prevented. Stronger protection, such as a separate account or ACLs, is a later owner decision.
- **Same-user trust.** Antivirus or indexers may briefly lock files; this surfaces as a retried sharing violation or `PERMISSION_DENIED`. The inbox and store are trusted only as far as the OS user is (the same boundary as `.env`).
- **Sync detection.** OneDrive detection relies on the OneDrive environment variables. Other sync tools are not detected; placing the store in one is a configuration error the operator must avoid.
- **8.3 short names.** A configured path written with 8.3 short names fails the `realpath` equality and is refused (fail closed); use the long form.

## 6. Content hash and file format validation (DEC-D4b, D4c)

**Hashing:**
- SHA-256 is computed by this code from the bytes it actually copied, streamed in 1 MiB chunks with bounded memory.
- `expected_sha256` is **only a constraint** (`CONTENT_MISMATCH`), never proof.
- Identity is `sha256:<hex>`; the storage path is derived **only** from the hash. The original name is sanitized metadata (validated, NFC) and is never a path (DEC-D4c).

**Size:**
- `0 < size ≤ 26,214,400` bytes (DEC-D4b).
- Enforced on the entry metadata, again **while streaming** (a file that grows is refused), and when reading for validation.

**Extension and content must agree.** The extension (`.pdf`, `.docx`, `.png`, `.jpg`/`.jpeg`) declares the type. The **staged copy**, not the source, must then pass that type's structural validator. Anything else is `FORMAT_INVALID` or `EXTENSION_UNSUPPORTED`; `.docm`, `.exe`, `.zip` and others are refused.

| Type | Checks (conservative; no rendering, no execution) |
|---|---|
| PDF | `%PDF-1.x` / `%PDF-2.x` header; `startxref` and `%%EOF` in the last 2 KiB; at least one object. **Not a security scan**: no JavaScript, embedded-file or structure parsing. |
| PNG | signature; `IHDR` first (13 bytes, dimensions 1–100,000); every chunk length bounded and every **CRC verified**; at least one `IDAT`; `IEND` exactly at EOF (no trailing data) |
| JPEG | `FFD8FF` SOI; every segment length in range; a frame (SOF) before the scan (SOS); the entropy data walked to the next real marker; `EOI` exactly at EOF |
| DOCX | a ZIP; at most 2,000 members; member names safe (no absolute, `..`, backslash, `:`, control characters or empty segments; no case-insensitive duplicates); no encrypted members; stored or deflated only; per-member ratio ≤ 200; declared total ≤ 200 MiB; **every member stream-read with an actual-bytes cap** (catches lying headers and verifies each CRC); `[Content_Types].xml`, `_rels/.rels` and `word/document.xml` required; WordprocessingML main content type required; macro-enabled types and `word/vbaProject.bin` refused. **Nothing is extracted to disk**, and macros or embedded content are never executed. |

**Validator limits:** these are structural checks. A crafted file can pass them and still carry malicious content for a vulnerable viewer. The store never opens documents in a viewer, and this is not malware scanning.

## 7. Immutability guarantees

**What the module guarantees:**
- Content-addressed objects; the path is derived only from the SHA-256.
- The read-only attribute is set **before** the object becomes visible (rename keeps it).
- The module **never** opens an object for writing, renames it, deletes it or replaces it.
- An existing object is reused only after a full re-hash, and a mismatch is `INTEGRITY_FAILURE`.
- `verify_object` and `inventory` detect missing or altered objects; nothing auto-repairs.

**What the tests show:**
- appending to a stored object raises `PermissionError`;
- a reuse leaves the stored object's bytes and mtime identical.

## 8. Atomic promotion: guarantees and limits

**Sequence:**
1. Create a unique temporary file in `staging/` (`O_CREAT|O_EXCL`).
2. Copy and hash.
3. `os.fsync` (FlushFileBuffers).
4. Re-hash the staged file from disk.
5. Validate the format.
6. Make it read-only.
7. `os.rename` to `objects/sha256/<aa>/<hex>`, which is atomic on one NTFS volume and refuses an existing target.
8. Re-hash the final object.

**Guaranteed:**
- An object path either does not exist or holds complete, flushed, verified bytes; a partial object is never visible.
- Concurrent ingestion of identical bytes produces exactly one object: one creator, the rest verified reusers.
  - 60 stress trials × 8 threads gave 60/60 correct after the fix in §10.

**Not guaranteed (Windows):**
- **Directory-entry durability.** Directories cannot be fsynced on Windows (`os.open` on a directory fails), so the rename's durability relies on NTFS metadata journaling. After a power loss, a just-promoted object can be missing.
  - The NL4D5A3 rule mitigates this: promote and verify **before** the database commit.
  - It is detected by `verify_object` / `inventory` (MISSING).
- **No joint atomicity.** Filesystem/PostgreSQL atomicity is **not** provided and never claimed. NL4D5A1b/A3 will rely on ordering instead:
  - promote first, then commit;
  - re-check in the transaction;
  - tolerate orphaned files.

## 9. Crash consistency and recovery

| Fault (injected in the tests) | Outcome |
|---|---|
| Failure before staging | nothing created |
| Partial staging copy (a write fails mid-copy) | the call's own staging file is removed; nothing promoted |
| Source changed during the copy / replaced before open | `SOURCE_CHANGED`; staging removed |
| Invalid signature or structure | `FORMAT_INVALID`; staging removed |
| Oversized, or grows during the copy | `TOO_LARGE` (or `SOURCE_CHANGED`); staging removed |
| Hash mismatch (staged bytes altered after the copy) | `HASH_MISMATCH`; staging removed |
| Flush failure | `FLUSH_FAILED`; nothing promoted |
| Promotion failure | `PROMOTION_FAILED`; nothing promoted |
| Destination exists with other bytes | `INTEGRITY_FAILURE`; destination untouched; staging removed |
| Interruption right after promotion | the object is complete and verified; `inventory` shows **ORPHANED_FINALIZED**; re-ingesting the same bytes reuses it (verified) |
| Repeated or concurrent identical ingestion | one object; the others report `reused` |
| A process killed mid-copy | `ingest-*.part` remains as **INCOMPLETE_STAGING**; only an explicit `sweep_staging` (≥ 3,600 s old, exact pattern, regular files) removes it |
| Finalized orphan | **reported, never deleted** (DEC-D4a: manual review only) |

**Inventory classes:**
- `VERIFIED_REFERENCED` (verified and in the reference set);
- `ORPHANED_FINALIZED` (verified, unreferenced);
- `CORRUPT_STORED` (re-hash mismatch or not a regular file);
- `INCOMPLETE_STAGING`;
- `UNEXPECTED_ENTRY` (anything else).

## 10. RED/GREEN tests

`tests/merchant/test_nl4d5a1a_document_store.py`: **102 passed, 1 skipped** (the symlink case, which needs a privilege). Each test uses its own temporary inbox and store outside the repository; there is no database fixture.

| Run | Result |
|---|---|
| **RED 1**: module removed | collection error (`ImportError`); all tests fail |
| **RED 2**: no reparse/link check | 1 failed (junction) |
| **RED 2**: no source-change check | 1 failed |
| **RED 2**: promotion may overwrite (`os.replace`) | 7 failed |
| **RED 2**: no format validation | 31 failed |
| **RED 2**: no staged re-hash | 1 failed |
| **RED 2**: no hard-link check | 1 failed |
| **RED 2**: no sharing-violation retry | 2 failed |
| **RED 2**: no identifier validation | 35 failed |
| **GREEN** (module restored byte-identical, checked) | 102 passed, 1 skipped |

**A real bug, found and fixed.**
- **The flake:** the first full GREEN run after RED had 1 failure, in `concurrent_ingestion_of_identical_content_is_safe`, roughly 1 in 3 runs.
- **Diagnosis:** a 60-trial stress run produced 25 `PermissionError`s, raised in `_verify_existing` → `os.open`. On Windows a file just renamed into place by another thread briefly refuses new handles (a sharing violation).
- **Fix:** `_open_stored` retries **only stored-object reads**, for at most 2 s, then reports `PERMISSION_DENIED`. Inbox reads keep their immediate `PERMISSION_DENIED`.
- **After the fix:** 60/60 stress trials were correct, and two deterministic regression tests were added (transient retried; persistent reported).

**Phase 9 coverage:**
- allowed formats ×5;
- the exact 25 MiB boundary (26,214,400 accepted, +1 refused);
- oversized and growing files;
- wrong extensions and spoofed signatures (7);
- malformed DOCX (7);
- malicious ZIP member names (5);
- ZIP bombs (ratio, plus lying headers caught by the streamed read);
- member-count limit and encrypted members;
- corrupt PDF/PNG/JPEG (8);
- empty files;
- duplicate content, concurrent identical content, and different contents under the same name;
- Unicode names (NFC kept, NFD refused);
- reserved names (7) and path traversal and identifiers (21);
- junctions, symlinks (skipped) and hard links;
- ADS (in the traversal set);
- incomplete writes, source races, hash failures, flush, promotion and permission failures;
- storage-root misconfiguration (14 cases);
- crash after promotion;
- no overwrite and no automatic orphan deletion (inventory and sweep);
- integration boundaries (no database or authority coupling; runtime and document writes still disabled).

## 11. Full regression

Sequential; no concurrent pytest against the test database; no live `/solve`.

| Run | Result |
|---|---|
| Storage tests | 102 passed, 1 skipped |
| Existing document suites (engine, repository, live repository, entity resolver), NL4D3 previews, NL4D4A unit and PG, procurement live | 370 passed, 3 skipped (the new file included) |
| Full suite (runtime credentials blanked) | **4628 passed, 21 skipped, 1 xfailed, 0 failed** (97 subtests), 6 min 27 s. 4628 = the accepted 4526 + 102 new; the one extra skip is the privilege-dependent symlink test. |
| `system_test.py` | ALL TESTS PASSED |
| Hook compile/import smoke | 57 files compiled (every hook plus `document_store.py`); the main hooks import; `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; `direct_execute_enabled('document revision-create', 'test')` = False |
| `git diff --check` | clean |

## 12. Database integrity evidence

All checks were read-only (`merchant_test`), before and after the full regression.

| Check | Result |
|---|---|
| Integrity hash | `99abfa8e56c2da686b276127310d7e28ae4c80ab78b351b78f8a407b38f33f8a`, **unchanged** from the accepted baseline |
| Migrations | versions 1–7 only; **no migration 008** |
| Business rows | unchanged: 5 Projects, 114 steps, 11 events, 1 procurement row, 0 revisions, 0 approvals |
| Claims / ledger | 22, all COMPLETED / 6; no orphan ledger rows; no new or unexpected entries |
| Acceptance Projects | NL2, NL3, NL4C2B and NL4D4B unchanged (covered by the hash); NL4C2B step 1 IN_PROGRESS v2 |
| Pending confirmations | 5, all earlier, CONFIRMED and expired; none new |
| Live write path | none added: `document_store` is imported by no module outside its own file and tests; `document revision-create` is not in test mode; runtime disabled |
| Production | never connected |

## 13. Known limitations

1. **Not integrated.** Nothing calls the module yet. DEC-D4d, D4e, D4f and D4g are future domain contracts for NL4D5A2/A3; existing revision behaviour is unchanged (`content_hash` is still free text, and legacy rows are not yet marked UNVERIFIED_LEGACY).
2. **No joint atomicity.** Filesystem/PostgreSQL atomicity is not provided; the write path must use the promote-then-commit ordering (design §6).
3. **Windows durability.** There is no directory fsync; immutability is the read-only attribute plus detection, not an ACL; same-size, same-tick in-place source edits are undetectable by metadata (closed in the write path by `expected_sha256`).
4. **Structural validation only.** It is not a malware scan; PDF checks are minimal.
5. **Symlink coverage.** The symlink test is skipped without the Windows symlink privilege; junctions (the same detection) are tested for real.
6. **DEC-D4a backup gap** (§1). It needs a procedure: a write pause, or a second incremental store pass.
7. **DEC-D4g has no enumerated canonical type list** in the domain. It must be identified and approved before NL4D5A2 enforces it.
8. **The sharing-violation retry** is a bounded wait (2 s). Persistent locks by antivirus or other processes surface as `PERMISSION_DENIED`, not success.

## 14. GO / NO-GO for NL4D5A1b

**GO for NL4D5A1b (schema), subject to your acceptance of this checkpoint.**
- **Ready:** the isolated store is complete, tested (102 tests, 8 guard mutations caught) and regression-clean, with the database untouched.
- **Before NL4D5A1b starts:**
  1. accept or commit NL4D5A1a and the updated decision register (both are uncommitted, as instructed);
  2. decide the DEC-D4a backup-gap procedure (§1). It is needed before NL4D5A3, not A1b.
- **What NL4D5A1b would do:** migration 008 on the test database only:
  - `document_files` (metadata matching `StoredObject`);
  - the composite FK binding `document_revisions.content_hash` to the file;
  - legacy rows left as UNVERIFIED_LEGACY (DEC-D4f; a NOT VALID or nullable design, with no fabricated files);
  - a rolled-back dry run, an audit and a documented reversal, as for migration 007.

**Out of scope until later checkpoints:**
- **NL4D5A2:** DEC-D4d, D4e and D4g enforcement, which needs the canonical type list identified and approved, plus the preview and confirmation.
- **NL4D5A3:** document execution, which binds `ingest(expected_sha256=…)` to the previewed hash.

**Still NO-GO:** runtime/production Direct EXECUTE, approvals, signing and NL4D5B–D.

*§14 is the initial assessment; §15.11 supersedes it.*

## 15. Final security review (2026-11-12)

### 15.1 Scope and accepted decisions

**Decision register:**
- **D4 entries:** all eight are now quoted **verbatim** from the owner's approval. In the first draft several were paraphrased; my notes (the D4a backup-order note, the D4g canonical-list note) are now labelled "not part of the decision".
- **Still PROPOSED:** S1, S2, D1, G1, G2 and P1b.

**Module isolation:**
- `document_store.py` imports no project package and no database driver.
- No module other than its own tests references it.
- `direct_execute_enabled('document revision-create', 'test')` is False.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

### 15.2 Concurrency retry: root cause and audit

**Root cause (found during the checkpoint).** On Windows, a file another thread has just renamed into place can refuse new handles for a short time (a sharing violation, which Python surfaces as `PermissionError`). A concurrent reuser opening the object to re-verify it then failed: 25 thread failures in 60 trials before the fix.

**Implementation:** `_open_stored` retries `os.open` on `PermissionError` only, for at most `SHARING_RETRY_SECONDS = 2.0`, sleeping 10 ms between attempts, then raises `DocumentStoreError(PERMISSION_DENIED)`.

| Audit point | Finding |
|---|---|
| 1. Only transient access errors are retried | only `PermissionError` on **opening an already stored object** (re-verification of reuse, final verification, `verify_object`). Inbox and staging opens are never retried. |
| 2. Unrelated errors are not retried | `FileNotFoundError`, read errors, hash results and format errors are never retried. A missing object is now a stable `INTEGRITY_FAILURE` / `MISSING` (§15.4). |
| 3. A mismatch is never a transient success | the retry wraps the open only; the hash comparison runs after it, and a mismatch is `INTEGRITY_FAILURE` |
| 4. Reuse requires independent verification | every reuse re-reads and re-hashes the existing object (`_verify_existing`) before it is returned |
| 5. No overwrite or replacement | `os.rename` (MoveFileEx without REPLACE_EXISTING); the mutation to `os.replace` fails 7 tests |
| 6. Deterministic timeout | a persistent lock gives `PERMISSION_DENIED` after **2.00 s** (measured with the real, unpatched budget) |
| 7. Concurrent same content stays consistent | stress results below |
| 8. Concurrent different content stays independent | stress results below, plus the new test `concurrent_ingestion_of_different_content_stays_independent` |

**Limit:** Windows reports a genuine ACL denial and a sharing violation the same way. A real denial therefore also waits up to 2 s, then fails closed.

### 15.3 60-trial stress results (final code)

Each trial ran 8 threads, started by a barrier, in a fresh temporary inbox and store.

| Scenario | Trials | Passed | Failed | Error categories | Duration |
|---|---|---|---|---|---|
| Identical content (8 threads, one blob) | 60 | **60** | 0 | none | 9.6 s |
| Different content (8 threads, 8 blobs) | 60 | **60** | 0 | none | 11.0 s |
| Persistent lock on a stored object | 1 | fail-closed | — | `PERMISSION_DENIED` | 2.00 s |

**Pass criteria for each trial:**
- every thread succeeded;
- the expected number of objects existed;
- every hash equalled the content;
- each object was verified;
- the creator count was exactly right;
- staging was empty.

### 15.4 Defects found in this review, fixed test-first

The regression tests below were written first, and all 5 failed against the reviewed code. The fixes are the smallest scoped changes.

| Defect | RED evidence | Fix |
|---|---|---|
| `sweep_staging` accepted a 60 s threshold, so an ingestion stalled by antivirus or a slow disk could have its staging file swept: **cleanup could affect an active operation** | `staging_sweep_threshold_cannot_reach_active_operations` failed | `MIN_SWEEP_AGE_SECONDS = 3600`. Smaller thresholds are refused (`CONFIG_INVALID`). An hour is far beyond any 25 MiB ingestion. |
| Store directories were checked only when the configuration was built; a **`staging/` or `objects/sha256/` swapped for a junction afterwards was written through** | `…swapped_for_a_junction…[staging]` and `[objects]` failed (the ingest succeeded through the junction) | `ingest` re-checks `staging/`, `objects/` and `objects/sha256/` on the actual filesystem objects (`lstat`, reparse attribute) at every call (`_require_real_directory`) |
| A staging copy removed mid-operation raised a raw `FileNotFoundError` | `…staging_file_removed_mid_operation…` failed | the post-copy section maps it to `INTEGRITY_FAILURE` ("the staged copy disappeared"); nothing is promoted |
| A stored object that vanished, for example **quarantined by antivirus**, raised a raw `FileNotFoundError` instead of a stable fail-closed reason | `…stored_object_that_vanishes…` failed | `_verify_existing` gives `INTEGRITY_FAILURE` ("stored object is missing"); `verify_object` gives `MISSING` if the file disappears between `lstat` and open |

The new test `concurrent_ingestion_of_different_content_stays_independent` passed before and after; the behaviour already held.

**Mutation RED (final code).** Each guard was disabled in turn and restored byte-identical (checked). **Every mutation was caught:**

| Guard disabled | Failures |
|---|---|
| reparse/link check | 3 |
| source-change check | 1 |
| no-overwrite promotion | 7 |
| format validation | 31 |
| staged re-hash | 1 |
| hard-link check | 1 |
| sharing-violation retry | 1 |
| per-operation directory re-check | 2 |
| sweep minimum | 2 |
| identifier validation | 35 |
| module absent (RED 1) | collection error |

GREEN: **108 passed, 1 skipped**.

### 15.5 Windows security coverage

| Area | Checked on the actual filesystem object? | Evidence |
|---|---|---|
| Traversal, absolute, UNC and drive paths; ADS; wildcards; control characters; trailing dot or space | identifier validation **plus** resolution only as `inbox / bare name` | 21 identifier cases |
| Reserved names (CON, NUL, COM/LPT 0–9 and superscripts, `CONIN$`/`CONOUT$`) | identifier | 7 cases |
| Symlinks, junctions, reparse points (file) | **yes**: `lstat` reparse attribute and `S_ISLNK`, plus the `realpath` parent must be the inbox | real NTFS junction test |
| Junction or link in a root's ancestry | **yes**: `realpath` must equal the configured path | misconfiguration cases |
| Store directories swapped after validation | **yes**: re-checked every call (§15.4) | 2 tests |
| Hard links | **yes**: `st_nlink == 1` | test |
| OneDrive and repository roots; root overlap | path containment on normalized absolute paths, *after* the link check above (so the paths are real) | 14 configuration cases |
| Source replaced between check and open, or modified during the copy | **yes**: `lstat` vs `fstat` identity (inode, device, size, mtime) before and after | 2 race tests |
| Staging isolation | unique `O_CREAT|O_EXCL` file per call; only the call's own file is removed; `staging/` re-checked | tests |
| Size limit | entry metadata, the streaming copy and validation reads | 25 MiB boundary and growth tests |
| Content validation | on the **staged copy**, not the source | 7 spoof and 15 corruption or DOCX cases |
| No-overwrite promotion | MoveFileEx without REPLACE_EXISTING; existing objects re-verified | integrity tests and mutation |

**Privilege-dependent skipped test.**
- `test_symlinks_are_refused` is skipped because creating a file symlink needs the Windows symlink privilege, which this account lacks (WinError 1314).
- The code path is the same as for junctions (`_is_reparse_or_link`: the reparse attribute or `S_ISLNK`). Junctions are tested for real, and the mutation removing that check fails 3 tests.
- The symlink case itself should be run once on a machine with Developer Mode or the privilege. It is not bypassed or faked.

**No NO-GO condition found.** Every important path-escape route is blocked on the actual filesystem object.

### 15.6 Crash and durability

**Reviewed for correct claims:**
- staging creation (`O_EXCL`, unique);
- the bounded-memory copy (1 MiB chunks, streamed size cap);
- SHA-256 over the copied bytes;
- `os.fsync`;
- a full re-hash of the staged file from disk;
- an atomic no-overwrite rename;
- a re-hash of the final object;
- recovery after interruption.

**What the tests confirm:**
- a partial blob is never reported complete;
- stored blobs are never overwritten;
- a corrupt existing blob is refused;
- finalized orphans are never deleted;
- `inventory` and `verify_object` are read-only;
- the sweep cannot reach active operations (§15.4).

**Limits (unchanged, explicitly not claimed):**
- **Power loss and directory durability.** Directories cannot be fsynced on Windows, so a just-promoted object can be lost on power loss. The NL4D5A3 write path must promote and verify **before** the DB commit, and `verify` reports MISSING.
- **No joint atomicity** between the filesystem and PostgreSQL.
- **Same-user tampering.** A same-user process can clear the read-only attribute and alter an object; this is detected by re-hash, not prevented.
- **Same-size edits inside one timestamp tick.** A same-size in-place source edit inside one timestamp tick is invisible to metadata; the write path closes it with `expected_sha256`.

### 15.7 Storage immutability evidence

| Evidence | Test |
|---|---|
| Objects are born read-only, and appending raises `PermissionError` | `stored_objects_are_never_modified` |
| Reuse leaves the bytes and mtime identical | same |
| A corrupt object at the hash path is never overwritten | `existing_destination…never_overwritten` |
| `inventory` deletes nothing | `inventory_classifies_without_deleting_anything` |
| The sweep never touches `objects/` | `staging_sweep_is_explicit_narrow…` |
| Replacing the no-overwrite rename with `os.replace` fails 7 tests | mutation RED |

### 15.8 Regression

Sequential; no live `/solve`; no concurrent pytest.

| Run | Result |
|---|---|
| Storage suite | 108 passed, 1 skipped |
| Targeted: storage, document engine and repositories (unit and live), entity resolver, NL4D3 previews, NL4D4A unit and PG, procurement live | 376 passed, 3 skipped |
| Full suite (runtime credentials blanked) | **4634 passed, 21 skipped, 1 xfailed, 0 failed** (97 subtests), 7 min 33 s. 4634 = the accepted 4526 + 108 new; the extra skip is the privilege-dependent symlink test. |
| `system_test.py` | ALL TESTS PASSED |
| Hook compile/import | 57 files; the main hooks and `document_store` import; `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; document revision-create not enabled on test |
| `git diff --check` | clean |

### 15.9 Database integrity

All checks were read-only (`coding_agent_merchant_test` / `merchant_test`, `transaction_read_only = on`), after the full suite.

| Check | Result |
|---|---|
| Hash | `99abfa8e56c2da686b276127310d7e28ae4c80ab78b351b78f8a407b38f33f8a`, **unchanged** |
| Migrations | 1–7; **008 not applied** |
| Business rows | unchanged (5 Projects, 114 steps, 11 events, 1 procurement row, 0 revisions or approvals) |
| Claims / ledger | 22, all COMPLETED / 6; no orphan; none new |
| Acceptance Projects | unchanged (the hash covers them); NL4C2B step 1 IN_PROGRESS v2 |
| Pending confirmations | 5 earlier records, all CONFIRMED and expired; none new |
| Other database sessions | none |
| Production | never connected |

### 15.10 Remaining risks

1. **The symlink test needs a privileged run** (§15.5).
2. **Windows durability:** no directory fsync; read-only is not an ACL; same-tick same-size edits are invisible to metadata.
3. **One error for two causes:** an ACL denial and a sharing violation are indistinguishable, so a real denial waits up to 2 s before failing closed.
4. **Structural validation only;** it is not a malware scan.
5. **DEC-D4a backup gap** (§1). The owner's procedure must close it before NL4D5A3.
6. **DEC-D4g canonical type list** to be identified and approved before NL4D5A2.
7. **D4d, D4e and D4f are domain contracts,** not yet enforced (NL4D5A2/A3).

### 15.11 GO / NO-GO

- **NL4D5A1a: GO.** All gates pass and it is committed (`feat(merchant): add immutable local document storage foundation`; the hash is in the session report, because a file cannot contain its own commit's hash).
- **NL4D5A1b: GO to start, once you authorize it.** Its prerequisites:
  1. Explicit authorization to start NL4D5A1b (this checkpoint did not start it).
  2. The migration 008 design for the **test database only**:
     - a `document_files` table matching `StoredObject` (`object_id`, `sha256`, `storage_key`, `byte_size`, `file_type`, `media_type`, sanitized `original_name`);
     - a composite FK binding a managed revision's `content_hash` to its file;
     - legacy rows kept as **UNVERIFIED_LEGACY** (DEC-D4f: no migration of data, no fabricated files);
     - grants: INSERT/SELECT only.
  3. The NL4D4A migration method: a duplicate and consistency audit first, a rolled-back dry run, a runner plan and apply on the test database, a post-apply audit, a documented reversal, and the runtime left unmigrated.
  4. Not required for A1b, but required before NL4D5A2/A3:
     - the canonical document-type list (DEC-D4g);
     - the DEC-D4a backup-gap procedure.

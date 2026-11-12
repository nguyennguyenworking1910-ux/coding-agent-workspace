# CP12H.NL4D-S1 — Simplified Policy & Migration 009

Branch `feat/cp7-9-merchant-reliability`, HEAD `c7f0933` (unpushed). Date 2026-11-12.

**Scope:**
- policy reconciliation and design;
- migration 009 with isolated rolled-back tests, applied to **`coding_agent_merchant_test` only**.

**Not done:**
- no revision, approval, signing, Step or procurement write path was enabled;
- `TEST_MODE_COMMANDS` and `WRITE_COMMANDS` are unchanged;
- the runtime database was never connected, and production permissions are unchanged;
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`;
- nothing committed or pushed.

**Working tree note.** Migration 008 (NL4D5A1b) is still uncommitted; its final acceptance was stopped earlier. Migration 009 builds on it, and both are now applied to the test database. They should be accepted and committed in order: 008, then 009.

---

## 1. Policy reconciliation

**Sources reviewed:**
- `cp12h_nl4d_decision_register.md` and `cp12h_nl4d_simplified_local_mvp_policy.md`;
- `approval_engine.propose_document_approval` and `signing_engine.propose_document_signing`;
- `gates.evaluate_approval_gate` / `evaluate_signing_gate`, `gate_resolver` and `engine._validate_gate`;
- `transition_repository.transition_step` and `step_preview._gate`;
- `dependencies.evaluate_dependency_readiness`, `branches` (conditional skipping) and `project_engine._validate_project_completion`;
- `workflow_templates.py` (all 4 templates).

**Superseded proposals.** Each was PROPOSED and never approved. The original text stays in the register as history.

| Earlier proposal | What it required | Replaced by |
|---|---|---|
| DEC-S1a | a per-role operator mapping | P1: the one local operator records any role |
| DEC-S1b | ≥ 2 distinct operators (separation of duties) | P1: a single operator |
| DEC-S2a | an `approval_attestations` table; **evidence required** for APPROVED and REJECTED | P2/P3: optional notes and date; no table |
| DEC-S2b | a file required for PARTNER | P2: no evidence required |
| DEC-D1a/b | a `document_signatures` table + a signed-file upload | P4: an operator-attested `signed` flag |
| DEC-G1a–c | new evidence gates on Steps 2, 3, 9–11, plus a new template version | Withdrawn: those Steps stay ungated |
| DEC-G2a/b | a UAT document + PARTNER evidence (21); evidence conditions (22) | P7: operator-attested completion; predecessors still required |
| NL4D5A1b report §13 item 4 | consumers must **refuse** `UNVERIFIED_LEGACY` | P6: a labelling rule. Non-MANAGED is never shown as verified, but may satisfy ordinary workflow gates. |
| NL4D5A design `cp12h_nl4d5a_document_revision_design.md` (managed upload as **the** revision path) | every new revision carries a managed file | P5: managed upload is **optional**; metadata-only revisions are the default path |

**Kept:**
- DEC-A0, P1a, P1b (still PROPOSED, no format rule), P1c and P2;
- DEC-D4 and D4a–g (applied when a file is uploaded; D4d applies to MANAGED revisions only);
- DEC-D4e (no superseding a signed revision);
- DEC-D1c (runtime grant, deferred).

The register is updated (§4 table and a dated update block). No earlier entry was deleted or rewritten; superseded entries are struck through and annotated.

## 2. Decisions and approval status

| ID | Decision | Status |
|---|---|---|
| **DEC-SIMPLIFY** | P1–P8 of `cp12h_nl4d_simplified_local_mvp_policy.md`: confirmation-first, optional evidence, single local operator, labelled attestation | **OWNER_APPROVED — LOCAL TEST MVP, 2026-11-12** |
| **DEC-SIMPLIFY-a** | `METADATA_ONLY` revision class (migration 009) | **OWNER_APPROVED — LOCAL TEST MVP, 2026-11-12** |
| **DEC-SIMPLIFY-b** | APPROVED and REJECTED may both be recorded; each is final for its revision and role | **OWNER_APPROVED — LOCAL TEST MVP, 2026-11-12** |
| DEC-S1a/b, S2a/b, D1a/b, G1a–c, G2a/b | — | **SUPERSEDED** for the Local Test MVP (never approved) |
| DEC-D1c | runtime signing grant | deferred |
| DEC-P1b | reference format | PROPOSED (no format rule) |
| DEC-D4g canonical type list | — | still to identify. The S2 revision write uses the existing pattern `^[A-Z][A-Z0-9_]{0,99}$` plus the type stated in the preview, until the list is approved. |

**Evidence of approval.** In this checkpoint I asked the owner explicitly whether to mark the three decisions OWNER_APPROVED and implement migration 009. The answer was **"Approve all three"**. The option read: "Mark DEC-SIMPLIFY (P1–P8), DEC-SIMPLIFY-a (METADATA_ONLY) and DEC-SIMPLIFY-b (APPROVED+REJECTED) OWNER_APPROVED — Local Test MVP. Then implement migration 009 + rolled-back tests, dry-run, and apply to coding_agent_merchant_test only."

**None of these approvals enables a write.** Each write kind still needs its own accepted checkpoint (§10).

## 3. Migration 009 schema

File: `.claude/clients/merchant/migrations/009_metadata_only_revisions.sql`.
- Checksum: `c4cd03a3514c417e0bdfe146b375f1ba97b15a132347240e415e589502a6add6`.
- One statement, so it is atomic.

```sql
ALTER TABLE merchant_ops.document_revisions
    DROP CONSTRAINT document_revisions_evidence_status_check,
    ADD CONSTRAINT document_revisions_evidence_status_check
        CHECK (evidence_status IN ('UNVERIFIED_LEGACY', 'METADATA_ONLY', 'MANAGED')),
    ADD CONSTRAINT document_revisions_metadata_only_content_check
        CHECK (evidence_status <> 'METADATA_ONLY' OR content_hash = 'metadata-only:' || id::text);
```

**What each class means:**

| Class | Meaning | File link | `content_hash` | Original filename |
|---|---|---|---|---|
| `UNVERIFIED_LEGACY` | unknown provenance: existing rows and any path that does not choose a class (still the **column default**) | none | free text (unchanged rule) | none |
| `METADATA_ONLY` (new) | recorded through a confirmed metadata-only write; **no file and no integrity claim** | none (008 `managed_file_check`) | **exactly `metadata-only:<revision id>`**, which can never look like or match a SHA-256 | none (008 filename check) |
| `MANAGED` | a verified stored file (unchanged) | required, composite FK to the file with the same hash | `sha256:<hex>` of the file | optional, sanitized |

**Guarantees, and how each is enforced:**

| Guarantee | Enforcement |
|---|---|
| Legacy rows unchanged | No data statement. The default stays `UNVERIFIED_LEGACY`. The rebuilt CHECK still admits every existing value. |
| MANAGED constraints still valid | Only the status CHECK is rebuilt, and every other constraint is byte-identical (dry run). The FK, `managed_file_check`, filename check and `document_files` are untouched. |
| METADATA_ONLY implies no file integrity | No file can be linked; the content marker cannot be SHA-shaped; a SHA-shaped hash is refused. |
| No silent upgrade | The 008 trigger `document_revisions_evidence_immutable` refuses any change of class, hash, file or filename. That covers METADATA_ONLY → MANAGED (even with a matching file), METADATA_ONLY → LEGACY and LEGACY → METADATA_ONLY. |
| 008 constraints remain valid | Every constraint has `convalidated = true` after applying. 008's 42 tests pass. |

**Approver attribution needs no schema work.**
- `document_approvals.approved_by` is nullable and will stay **NULL**. The actual approver is not known, so nothing is fabricated.
- The recording operator goes to `project_events.triggered_by`, as in NL4D4A.
- An optional approver name, if ever wanted, would be a separate decision with its own column. It is not designed here.

## 4. Existing data compatibility

| Item | Before | After |
|---|---|---|
| Revisions | 0 | 0 (no row inserted or changed) |
| `document_files` | 0 | 0 |
| Approvals | 0 | 0 |
| Projects / Steps / events | 5 / 114 / 11 | unchanged |
| Claims / ledger | 22 COMPLETED / 6, 0 orphans | unchanged |
| NL4C2B Step 1 | IN_PROGRESS v2 | unchanged |
| PR-NL4D4B-001 (procurement) | 1 row | unchanged |

**On a non-empty database:** existing rows keep their value (`UNVERIFIED_LEGACY` or `MANAGED`) and still satisfy the rebuilt CHECK. The new METADATA_ONLY CHECK is vacuously true for them, so the validating scan cannot fail.

**Runtime:** not migrated (schema 1–7); it would need its own approved plan.

## 5. Approval lifecycle (design for NL4D-S3; not implemented)

- **Decisions:**
  - one role (LEGAL, ACCOUNTING or PARTNER);
  - one decision (APPROVED or REJECTED);
  - one revision (the latest active, unsigned one; any class);
  - **one confirmation**.
- **No overwrite.**
  - A decided row (APPROVED or REJECTED) is final: the existing `ApprovalFinalizedError`.
  - If no row exists, the write INSERTs one.
  - A pre-existing PENDING row (not created by the simplified flow) may be decided once, with `expected_status = PENDING` (existing engine rule).
  - There is no path from APPROVED to REJECTED, or the reverse.
- **New cycle.** A new revision supersedes the unsigned active one, and approvals start empty for it. A signed revision is never superseded (DEC-D4e).
- **Confirmation** shows Project, Merchant, document type, revision number and class, role, decision, optional date and notes, and the warning "this decision is final for this revision".
- **Attribution (engine change in S3).** Split `acted_by`:
  - `approved_by` is always **NULL** (today the engine copies `acted_by` into it);
  - `triggered_by` = the trusted operator;
  - the event `new_values` carry `"attestation": "OPERATOR_RECORDED"` and the optional `decided_at`.
  - `approved_at` = the decided date for APPROVED (existing column and CHECK). For REJECTED, the date is kept in the event; there is no new column.
- **Basis and exactly-once:**
  - the preview basis covers the revision id and number, the role's current approval status and the Project version;
  - it is re-judged in the preflight and by a `precondition` on `record_approval` under the Project → revision → approval locks;
  - the preview mints the approval UUID, so a replay hits the primary key.

## 6. Signing lifecycle (design for NL4D-S4; not implemented)

- **Signing requires** LEGAL, ACCOUNTING and PARTNER all **APPROVED** on the latest active revision, plus a Purchase Request when `requires_procurement`. This is the existing `evaluate_signing_gate`, unchanged.
- **A REJECTED role blocks signing that revision permanently**, because `_approval_is_complete` needs APPROVED and REJECTED is final. The only way forward is a new revision.
- **What is written:**
  - `signed = true` and `signed_at` (optional date, default the write time);
  - event `DOCUMENT_SIGNED` with `"attestation": "OPERATOR_ATTESTED"`;
  - `triggered_by` = the operator;
  - no signatory claim and no file.
- **Basis:** the signing gate is re-judged in the preflight and by a `precondition` on `sign_document`.
- **New:** a `document sign` CLI command + adapter over the existing engine and repository, and a `signing` pending kind.
- **Permissions:** no runtime grant; DEC-D1c stays deferred.
- **Downstream:** PO and Payment Request rules are unchanged. They accept any signed revision whatever its class (P6), and their previews and receipts show the class.

## 7. Workflow completion design (design for NL4D-S5; not implemented)

**Audit:** every template's APPROVAL_GATE Steps. Only two Step names have database evaluators: "Record Partner approval" and "Validate signing gate". Every other APPROVAL_GATE gets no gate result in `transition_step`, so `engine._validate_gate` raises "A gate result is required", and `step_preview` reports `NO_DATABASE_GATE_EVALUATOR`. **These Steps can never complete today.**

| Template | Steps with no evaluator (blocked) | Evaluated (kept) |
|---|---|---|
| `MEDIA_TOP_UP_NEW_DOCUMENT` | Close payment period | Record Partner approval; Validate signing gate |
| `MEDIA_TOP_UP_EXISTING_DOCUMENT` | Validate existing signed document; Close payment period | — |
| `OPENING_NEW_CINEMA_STANDARD` | Complete UAT acceptance; Complete project | Record Partner approval; Validate signing gate |
| `INTEGRATION_NEW_MERCHANT_STANDARD` | Validate Master Merchant identity; Complete UAT acceptance; Activate Merchant; Complete project | Record Partner approval; Validate signing gate |

**Design (P7), reusing the existing Step confirmation unchanged in shape:**
1. **The preview.** `step preview` shows `gate.kind = OPERATOR_ATTESTATION` and blocking code `OPERATOR_ATTESTATION_REQUIRED`, instead of `NO_DATABASE_GATE_EVALUATOR`. It is READY only when every other check passes. Its `requested_operation` carries `gate_attestation: "OPERATOR_ATTESTED"`, included in the argv and the basis hash.
2. **The confirmation.** The usual `/solve Xác nhận cập nhật [<step id>]`. Its text states: "you attest that '<Step name>' is satisfied; the system has not verified it".
3. **The write.** `transition_step` builds a gate result for an evaluator-less gate **only** from that attestation flag in the confirmed, basis-verified operation. Without the flag, the gate still fails. Evaluated gates ignore the flag and are judged from data as today.
4. **The event.** The Step event carries `"gate": "OPERATOR_ATTESTED"` and `triggered_by` = the operator.

**Invariants kept:**
- **Predecessors.** `evaluate_dependency_readiness` is unchanged: every transitive predecessor must be COMPLETED.
- **Legitimately skipped Steps.** A conditional Step excluded at instantiation is SKIPPED **and its edges are dropped** (`branches.py`), so it never blocks. A Step SKIPPED later still counts as an unmet predecessor, which is conservative and unchanged.
- **The state machine** and the terminal statuses are unchanged.
- **"Complete project" is a Step, not the Project.**
  - Completing it does **not** change `projects.status`.
  - Project completion stays a separate transition (`project_engine`), which requires every Step to be COMPLETED, SKIPPED or SUPERSEDED (`_validate_project_completion`). It is not enabled and would be its own confirmed operation.
  - A user request never completes a Project implicitly.
- **"Activate Merchant" completes only the Step.** `merchants.account_status` changes only through the separate `merchant activate` command, which is not enabled.

## 8. Test evidence

**New:** `tests/merchant/test_nl4d_s1_migration_009_postgres.py`, **19 tests**. Each runs in one rolled-back transaction with the NL4D5A1b fixtures (disposable Merchant and two Projects).

| Run | Result |
|---|---|
| RED (before 009 was applied) | **9 failed, 10 passed.** The 10 that passed are refusals that already held before 009, because the old CHECK refused every METADATA_ONLY row; after 009 they guard the new rules. |
| GREEN (after apply) | **19 passed** |
| Migration tests together (008 + 009 + the two list tests) | 77 passed |

**What the tests cover:**
- 009 recorded once with the file checksum;
- reapplication refused (`DuplicateObject`) and rolled back;
- constraint definitions exact and validated, with 008's constraints present;
- a METADATA_ONLY revision accepted with its marker;
- the default is still `UNVERIFIED_LEGACY`;
- a METADATA_ONLY row with a SHA-shaped hash, free text, another revision's marker or an empty hash is refused;
- a METADATA_ONLY row cannot reference a file or carry a filename;
- unknown classes are refused;
- MANAGED still binds to its file and still needs one;
- reclassification refused: METADATA_ONLY → MANAGED, METADATA_ONLY → LEGACY, a hash change, an upgrade with a matching file, and LEGACY → METADATA_ONLY;
- approval, signing and supersede still work on METADATA_ONLY.

**Tests changed on purpose** (stale because a migration was added, as for 007 and 008):
- `test_alert_delivery_lease_migration.py` and `test_project_payment_period_migration.py`: `(9, "metadata_only_revisions")` added to the discovered list.
- `test_nl4d5a1b_migration_008_postgres.py::test_migration_008_is_applied_once_with_its_file_checksum`: it asserted that 008 is the **last** migration. It now checks versions 1–8 and the 008 row itself, so 009+ may follow.

**Dry run** (scratchpad `nl4d_s1_dryrun.py`; one transaction, always rolled back): **9/9 PASS.**
- the status CHECK has 3 classes and the content CHECK was added;
- every other constraint is identical;
- all are validated;
- the default is unchanged;
- the triggers are enabled;
- rows are identical inside the migration, and constraints and rows are identical after rollback.

**Runner:**
- `--plan --database test`: applied 1–8, pending exactly `(9, metadata_only_revisions, c4cd03a3…)`, no conflicts.
- `--apply`: applied 1–9.
- Re-`--plan`: nothing pending.

**Full regression** (sequential; runtime credentials blanked; no live `/solve`):

| Check | Result |
|---|---|
| Full suite | **4695 passed, 21 skipped, 1 xfailed, 0 failed** (97 subtests), 7 min 02 s. 4695 = 4676 + 19 new. |
| `system_test.py` | fully operational |
| Hook compile | OK; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean |
| Hash after the suite | `ada0d51d…`, unchanged; the tests left no residue |

## 9. Database integrity (read-only, test database)

| Item | Value |
|---|---|
| Pre-migration full hash | `79cfe197dae54d4edb6bea4e4c9f84596d990b21be417bf83e6afff11133d1fd`. It matches the NL4D5A1b baseline; there were no other sessions and no advisory locks. |
| Hash after the dry-run rollback | `79cfe197…`, unchanged |
| **Post-migration full hash (new baseline)** | **`ada0d51db2c2c0cab3b73c608625e1a4cddc1a2d6ec318f7f3878ec9d496483e`** |
| Equivalence: same algorithm, excluding only `schema_migrations` row 9 | **`79cfe197dae54d4edb6bea4e4c9f84596d990b21be417bf83e6afff11133d1fd`**, which reproduces the pre-migration hash **exactly** |
| Migrations | 1–9, no gaps; row 9 checksum `c4cd03a3…` equals the file |
| Tables | 18 (none added) |
| Revisions by class | none (0 rows) |
| Claims / ledger | 22 COMPLETED / 6, 0 orphans |
| NL4C2B Step 1 | IN_PROGRESS v2 |
| PYTEST residue | 0 |
| Runtime | not connected; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |

## 10. Implementation roadmap

Each checkpoint uses the NL4C/NL4D4A pattern:
- a verified preview with a NOT_AUTHORIZED `requested_operation` and a basis;
- its own pending kind;
- `/solve Xác nhận …`;
- a re-judge in the preflight and inside the transaction;
- claim + ledger + mutation + event in one transaction;
- a reconciled receipt;
- test database only.

| Checkpoint | Delivers | Depends on |
|---|---|---|
| **S0** | Finish the NL4D5A1b acceptance and commit 008; then accept and commit this checkpoint (009, tests, register, reports) | owner go |
| **NL4D-S2** | Confirmed **METADATA_ONLY revision**:<br>• `evidence preview` emits a revision operation (type, number, basis = the active revision);<br>• `revision` pending kind;<br>• `precondition` on `create_revision`, which inserts `evidence_status='METADATA_ONLY'` and the marker hash;<br>• `document revision-create` in test mode, revision kind only;<br>• receipt. | S0 |
| **NL4D-S3** | Confirmed **APPROVED/REJECTED** (§5): engine attribution split, `approval` pending kind, `precondition` on `record_approval`, `document approve` in test mode, receipt | S2 |
| **NL4D-S4** | Confirmed **operator-attested signing** (§6): `document sign` CLI and adapter, `signing` pending kind, `precondition`, receipt | S3 |
| **NL4D-S5** | **Operator-attested evaluator-less gates** (§7) through the existing Step confirmation | none (independent of S2–S4) |
| **NL4D-S6** | PO and Payment Request recording (NL4D4A path extended) | S4 |
| **NL4D-S7** | Project completion as its own confirmed transition; end-to-end acceptance on one disposable test Project | S5, S6 |
| Optional | managed file upload (NL4D5A2/A3) | never required by a gate |

**Out of scope:** role systems, multi-operator rules, mandatory uploads, attestation and signature tables, batch confirmations, and runtime enablement.

## 11. GO / NO-GO for NL4D-S2

- **NL4D-S1:** complete, pending owner acceptance.
  - DEC-SIMPLIFY, -a and -b are OWNER_APPROVED (Local Test MVP).
  - Migration 009 is applied to the test database only and audited; the business data is provably unchanged.
  - The regression is clean: 4695 passed, 0 failed.
  - Uncommitted.
- **NL4D-S2 (confirmed METADATA_ONLY revision): NO-GO until:**
  1. the NL4D5A1b acceptance (stopped earlier) is finished and 008 committed;
  2. this checkpoint is accepted and committed (009 after 008);
  3. you explicitly authorize S2.

  The D4g canonical type list is **not** a blocker for S2: it uses the existing pattern and the type confirmed in the preview. The list stays required for managed uploads.
- **Still NO-GO:** runtime migration, runtime Direct EXECUTE, any production grant, and any document, approval, signing, procurement or Project-completion live write.

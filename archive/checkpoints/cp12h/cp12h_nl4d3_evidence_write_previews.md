# CP12H.NL4D3 — Natural-Language Evidence & Approval Write Previews

Baseline `d06e074672f90b9b020f9fddf4b258c9c8fdabd8`, branch `feat/cp7-9-merchant-reliability`. Date 2026-11-10.

- **Git:** committed as `feat(merchant): add read-only evidence write previews` (see §12); not pushed.
- **Writes:** no evidence, approval, procurement or signing write. No new write command, execution adapter, pending-confirmation kind or test-mode command.
- **Runtime:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

## 1. Domain contract audit (Phase 1)

Sources:
- `cp12h_nl4d1_evidence_approval_domain_audit.md`;
- the engines `document_engine.py`, `approval_engine.py` and `procurement_engine.py`;
- `gates.py`;
- the CLI parsers in `cli.py`;
- `procurement_repository.py`.

| Operation | CLI (exists, not in test mode) | Required fields | Preconditions (engine) | Version / concurrency | Domain errors |
|---|---|---|---|---|---|
| Register document revision | `document revision-create <project_id> --type --content-hash [--effective-date --expiry-date --created-by --revision-id]` | `document_type` (`^[A-Z][A-Z0-9_]{0,99}$`), `content_hash` (non-blank text) | Project not COMPLETED or CANCELLED. At most one active revision per type, and it must be the highest number. The new revision gets `highest + 1` and supersedes the active one. `expiry_date` must be after `effective_date`. | No expected version: it supersedes whatever is active at commit (NL4D1 S4) | `DocumentEngineError`, `DocumentLifecycleClosedError`, `DocumentRevisionConflictError` |
| Record LEGAL / ACCOUNTING / PARTNER approval | `document approve <revision_id> --role --status [--expected-status --occurred-at --acted-by --notes --approval-id]` | `document_revision_id`, `approver_role` ∈ `gates.APPROVER_ROLES`, `approval_status` ∈ PENDING/APPROVED/REJECTED | Project open. Only the **latest active, unsigned** revision. One row per (revision, role). With an existing row, `expected_status` is required and must match. Only PENDING → APPROVED/REJECTED. APPROVED and REJECTED are **final**. | `expected_status` | `ApprovalEngineError`, `ApprovalConflictError`, `ApprovalLifecycleClosedError`, `ApprovalRevisionNotActiveError`, `ApprovalFinalizedError` |
| Record PR / PO / Payment Request reference | `procurement update <project_id> --type [--external-id --status --expected-version --document-type --triggered-by --procurement-id]` | `procurement_type`; for a new record, `status` or `external_id` (≤ 100 characters, non-blank) | Project open. One record per (project, type). PR has no prerequisite. A PO needs a **signed** latest active revision, plus a recorded PR number when `requires_procurement`. A Payment Request needs a signed revision and a recorded PO number. With several active document types, `document_type` is required. | `expected_version` for an existing record | `ProcurementEngineError`, `ProcurementConflictError`, `ProcurementLifecycleClosedError`, `ProcurementDependencyError` |

**Found in this audit:** `procurement_repository` writes `status = plan.status` on UPDATE. So a "record the reference" update must pass the stored status, or it would clear it. The preview does exactly that.

**Not defined by the domain** (left as owner decisions, never invented):

| ID | Undecided | How the preview treats it |
|---|---|---|
| S1 | Who may attest a LEGAL, ACCOUNTING or PARTNER decision, and how `acted_by` (an unverified UUID) binds to that person | Every domain-valid approval ends **POLICY_UNDECIDED**, with `APPROVAL_ATTESTATION_POLICY_UNDECIDED` and `APPROVAL_ACTOR_UNBOUND` |
| S2 | Finality is defined (APPROVED and REJECTED are final); how a confirmation must state it is not | `domain_validation.finality` states it |
| D1 | Signing has no CLI or adapter | Signing is never previewed. PO and Payment Request previews carry `SIGNING_NOT_AVAILABLE` |
| D4 | `content_hash` is unverified text; no file storage | A revision preview carries `CONTENT_HASH_UNVERIFIED` (a note, not a blocker: the domain accepts it) |
| — | Reference *format* (for example "must start with PR-") | No rule exists beyond non-blank and ≤ 100 characters. No prefix check is invented |
| — | Recording a PR on a Project that does not require procurement | The domain allows it. The preview gives `PROCUREMENT_NOT_REQUIRED` (a note) |
| — | Overwriting an existing reference with a new one | The domain allows it as an UPDATE with `expected_version`. The preview shows the stored record and the plan `UPDATE` |

## 2. Architecture

```
/solve <request>
  └─ UserPromptSubmit → IntentParser.parse
       └─ _detect_local_merchant_operation: kind EVIDENCE_WRITE + Merchant context
          (a Project, Merchant or step named, a workflow-step phrase, or a domain
          approver role / procurement record named) → merchant_execute (or merchant_read if negated)
  └─ intent_gate: unscoped and roster == [merchant-manager] and kind EVIDENCE_WRITE
       → operations [merchant_read], risk read_only, no confirmation, target from the user's words
  └─ policy gate: only merchant-manager may be dispatched (merchant_read, database_target)
  └─ merchant-manager: agent_cli.py evidence preview --request "<verbatim>" [--test-database]
       └─ read_commands.evidence_preview → evidence_preview.build_evidence_preview
            ├─ project_nl.interpret_project_request (kind, phrases, negation)
            ├─ project_status.resolve_merchant_phrase / resolve_project (exact binding; NL4A/NL4D2)
            ├─ reads.get_project_detail (revisions, approvals, procurement records)
            └─ the domain engine on that snapshot (pure; nothing written)
  └─ PostToolUse(Bash): ReadResultContract ("evidence","preview") captures the exact JSON,
     VERIFIED only with mode EVIDENCE_WRITE_PREVIEW, read_only true, authorization null,
     executable false, confirmation_available false, requested_operation null, trusted target
  └─ PreToolUse(SendMessage): the report must carry that object once after
     MERCHANT_EVIDENCE_PREVIEW_JSON:; terminal, so no argv, scope or confirmation text
```

The preview creates no pending record. Only a VERIFIED `step preview` does, and that is unchanged.

## 3. Implemented preview operations (Phase 2)

| # | Operation | `operation_kind` | `evidence_type` | Engine |
|---|---|---|---|---|
| 1 | Register document revision | `REGISTER_DOCUMENT_REVISION` | `DOCUMENT_REVISION` | `propose_document_revision` |
| 2 | LEGAL approval | `RECORD_APPROVAL` | `LEGAL_APPROVAL` | `propose_document_approval` |
| 3 | ACCOUNTING approval | `RECORD_APPROVAL` | `ACCOUNTING_APPROVAL` | `propose_document_approval` |
| 4 | PARTNER approval | `RECORD_APPROVAL` | `PARTNER_APPROVAL` | `propose_document_approval` |
| 5 | Purchase Request number | `RECORD_PROCUREMENT_REFERENCE` | `PURCHASE_REQUEST` | `propose_procurement_mutation` |
| 6 | Purchase Order reference | `RECORD_PROCUREMENT_REFERENCE` | `PURCHASE_ORDER` | `propose_procurement_mutation` |
| 7 | Payment Request reference | `RECORD_PROCUREMENT_REFERENCE` | `PAYMENT_REQUEST` | `propose_procurement_mutation` |

Signing is not implemented. "Ký revision mới nhất …" is not an evidence write, and the preview answers NEEDS_CLARIFICATION.

## 4. CLI and result contract (Phase 3)

**CLI.** `evidence preview --request "<user text>" [--test-database]`, a read:
- it is in `READ_COMMANDS`, not `WRITE_COMMANDS`;
- it is added to `TEST_DATABASE_READS` in `agent_cli` and the delivery hook;
- `--execute`, `--apply` and `--propose` are rejected by the adapter.

**Result fields:**
- `mode`: `EVIDENCE_WRITE_PREVIEW`;
- `operation_kind`, `database_target`, `merchant_id`, `project_id`, `evidence_type`;
- `resolved` (the Merchant and Project, each with its match kind);
- `requested_fields`, as written (no content hash: only `content_hash_provided`);
- `missing_required_fields`;
- `existing_evidence`: active revisions; the target revision, its approval for the role, and outdated approvals; or the stored procurement record and its dependencies;
- `domain_validation`: `status` VALID / INVALID / NOT_EVALUATED, `engine`, `error {code: engine error class, message}`, a whitelisted `plan` summary, and `finality` for approvals;
- `policy_blockers`, `policy_notes`;
- `basis` and `basis_sha256`: what was judged, including the Project version. Descriptive only, never authority;
- `candidates`, `clarifications`, `outcome`.

**Outcomes:**

| Outcome | Meaning |
|---|---|
| `PREVIEW_VALID` | The engine accepts it (revision, procurement) |
| `BLOCKED` | The engine refuses it, or the role is not a domain role (`UNSUPPORTED_APPROVAL_ROLE`), or there is no revision to approve (`MISSING_DOCUMENT_REVISION`) |
| `NEEDS_CLARIFICATION` | Project, Merchant, revision or role missing or ambiguous; several roles or types; negated or MIXED; a required field missing |
| `POLICY_UNDECIDED` | The engine accepts an approval, but S1 is undecided |

**Every outcome** has:
- `read_only: true`, `executable: false`, `confirmation_available: false`;
- `authorization: null`, `requested_operation: null`;
- no argv, scope, command or pending record.

## 5. Natural-language contract (Phase 4)

`project_nl` has a new kind, `EVIDENCE_WRITE`:
- **An imperative record verb** (ghi nhận, thêm, tạo, upload, record, register, add, approve, reject, …), followed by an evidence object outside every Project or Merchant name.
- **Or a statement** "<role> (đã) phê duyệt/duyệt/approved/rejected …".
- **Never** a question (`?`, "… chưa/không", "Has/Did/Is …") or a Project or Merchant creation.
- **Precedence:**
  - checked before Project and Merchant creation, so "Thêm revision tài liệu cho Project X" is no longer a `PROJECT_CREATE`;
  - after Step Update, so "Đánh dấu bước Record Partner approval … hoàn thành" stays a Step Update.
- **Negation:** "Đừng/Don't …", or "Legal **chưa** phê duyệt …", sets `negated` and requests no write.
- **Mixed:** a second action outside the approval nouns ("… rồi xóa Merchant …", "… và thêm Purchase Order …", "… and then delete …") is `MIXED`, and is never downgraded.

**Routing.** The local guardrail claims `EVIDENCE_WRITE` only with Merchant context:
- a named Project, Merchant or step, or a workflow-step phrase (as NL4D2-FIX1); or
- a domain approver role plus approval wording, or a full procurement record name.

A bare "PR" or "PO" never counts, so "Approve the PR for the parser fix" stays code work. The intent gate's unscoped downgrade set gains `EVIDENCE_WRITE`, and its reason text now names evidence questions and evidence writes (this also fixes the NL4D2 cosmetic limitation).

**Questions stay `EVIDENCE_STATUS`:** "Legal đã phê duyệt revision mới nhất của Project X chưa?", "Has Partner approved …?".

## 6. Domain validators reused

- `document_engine.propose_document_revision`
- `approval_engine.propose_document_approval`
- `procurement_engine.propose_procurement_mutation`
- `gates.APPROVER_ROLES`
- `project_status.resolve_project`, `resolve_merchant_phrase`, `_summary`
- `evidence_status._UUID`
- `project_nl.fold`, `interpret_project_request`

The engines receive a placeholder new-record id, which is never output. An approval update passes the stored `expected_status`, and a procurement update the stored `expected_version` and `status`.

## 7. Security (Phase 6)

**Preserved:**
- the NL4C trusted Step Update authorization;
- no typed scope for any new command: `document approve`, `procurement update` and `document revision-create` are still outside `TEST_MODE_COMMANDS`, and `direct_execute_enabled` is false for test and runtime;
- the verified source-backed delivery;
- the read-only semantics;
- runtime disabled.

**Not changed:** write allowlists, runtime write permissions, pending confirmations, execution adapters, signing, `external_write` semantics.

**Tested:**
- the policy gate denies `diagnostician` and `coder` for the preview run and allows `merchant-manager`;
- a forged capture (`read_only` false, `executable` true, `confirmation_available` true, `authorization`, a `requested_operation`, the wrong mode or the runtime target) is UNVERIFIED and cannot be delivered.

**Accepted test changed.** `test_nl4d2_fix1_evidence_routing.py::test_evidence_writes_are_never_downgraded_to_the_read` asserted "never a `merchant_read` run". NL4D3 intentionally runs an unscoped evidence write as the read-only preview, so the assertion now checks the safety property instead:
- never the evidence-status kind;
- the run is refused, or read-only, unconfirmed and unscoped;
- no pending record.

## 8. RED/GREEN (Phase 7)

**RED** at the baseline (`d06e074`, new tests added first): `tests/merchant/test_nl4d3_evidence_write_previews.py` fails at collection with `ModuleNotFoundError` (no `evidence_preview`, no `EVIDENCE_WRITE`). Baseline parser and guardrail behaviour on the spec's examples:

| Request | Baseline kind | Baseline guardrail |
|---|---|---|
| Ghi nhận Purchase Request / Purchase Order / Payment Request … cho Project X | UNKNOWN | none |
| Thêm revision tài liệu cho Project X | **PROJECT_CREATE** (misrouted to the Project create preview) | — |
| Legal đã phê duyệt revision mới nhất của Project X. | UNKNOWN | none |
| Record Accounting approval for Project X / Register Partner approval for the latest revision | UNKNOWN | none |
| Legal đã phê duyệt … chưa? | EVIDENCE_STATUS (correct) | merchant_read |

**GREEN:**

| Suite | Result |
|---|---|
| `test_nl4d3_evidence_write_previews.py` | **92 passed** |
| `test_nl4d3_evidence_write_previews_postgres.py` (alone, real test DB, no fixture written) | **7 passed** |

The 92 unit tests cover parsing, the seven operations, the domain cases, routing, the CLI, delivery and security.

**Phase 5 domain cases covered:**

| Case | Expected result |
|---|---|
| Project missing or ambiguous | CLARIFY, with candidates, nothing inferred |
| Another Merchant's Project | CLARIFY |
| Missing revision | BLOCKED `MISSING_DOCUMENT_REVISION` |
| Outdated revision | BLOCKED `ApprovalRevisionNotActiveError` |
| Final approval | BLOCKED `ApprovalFinalizedError` |
| PENDING → APPROVED | UPDATE, POLICY_UNDECIDED |
| Several active document types | CLARIFY, then bound by a stored type written whole |
| Missing actor | `APPROVAL_ACTOR_UNBOUND` |
| Unsupported role (CEO, Giám đốc) | BLOCKED |
| Missing role | CLARIFY |
| Two roles | CLARIFY |
| Procurement required vs not required | PO needs the PR number vs a note |
| PO / Payment Request dependencies | BLOCKED `ProcurementDependencyError` |
| Duplicate reference | BLOCKED `ProcurementConflictError`; a new reference is an UPDATE |
| Reference over 100 characters | BLOCKED; a missing reference is CLARIFY |
| Project-title token (`NL4C2B`) | never taken as a reference |
| Closed Project | BLOCKED `ProcurementLifecycleClosedError` |
| Project version change | changes `basis_sha256` |
| Step-name collision | stays STEP_UPDATE |
| Unicode NFC/NFD | same result |
| Negation (3 forms) | CLARIFY, no write |
| Mixed destructive (3 forms) | MIXED, not downgraded |
| Invalid date range | BLOCKED `DocumentEngineError` |
| Content hash | never echoed |

**Targeted regression.** One sequential process, PostgreSQL suites included: NL2*, NL3*, NL4A*, NL4B*, NL4C*, NL4D2, NL4D2-FIX1, NL4D3, Merchant intent routing and the CLI contract, **896 passed**. That run had 3 failures, all in the FIX1 test above, which was updated as described in §7. The FIX1 file then gave 30 passed.

## 9. Full regression and database integrity

**Preflight:** 1,858 MB free memory, CPU 45%, no other pytest process.

**Full regression.** `pytest ./tests -q --tb=short`, one process: **4375 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests) in 344 s. That is the baseline 4276 plus 99 new tests (92 unit, 7 PostgreSQL), with one accepted test updated (§7).

**Other checks:**
- `python .claude/system_test.py`: Failed 0, fully operational.
- Compile and import smoke (all hooks, all Merchant tools, `intent_parser`): OK. `intent_parser.py` also runs directly as a script.
- `git diff --check`: clean.
- No control characters in `.claude/**/*.py` or `tests/**/*.py`. Five backspace bytes from a heredoc were found and replaced during development.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; `TEST_MODE_COMMANDS = {merchant create, project create, step update}` (unchanged).

**Database (read-only check):**

| Check | Result |
|---|---|
| Hash | `ba419be9d17a7a6719f1ca864ff5bdc1fe01848a7ad65a857e023715d028a319`, unchanged |
| Claims | 20 |
| Ledger rows | 4 |
| `document_revisions` / `document_approvals` / `procurement_records` | 0 / 0 / 0 |
| `PYTEST%` Merchants | 0 |
| NL4C2B step 1 | IN_PROGRESS v2 |
| NL2/NL3 Projects | unchanged (covered by the hash) |
| Pending confirmations | none new: the only `*.pending_*.json` files are from 2026-11-04 and 2026-11-09, and no runtime file was written apart from team state |

## 10. Live read-only test plan (not run in this checkpoint)

1. **Session.** Start a fresh Claude Code session in psmux (`merchant-manager.md` changed, so an older teammate is `STALE_DEFINITION`). Check free memory first.
2. **Purchase Request.** `/solve Ghi nhận Purchase Request PR-001 cho Project Beta NL4C2B Step Acceptance trên database test`.
   - Expected envelope: `merchant-manager`, `merchant_read`, `read_only`, target `test`, no confirmation.
   - Expected read: one `evidence preview … --test-database`.
   - Expected answer: `PREVIEW_VALID` INSERT, `PROCUREMENT_NOT_REQUIRED` note, nothing recorded, no confirmation offered.
3. **Legal approval.** `/solve Legal đã phê duyệt revision mới nhất của Project Beta NL4C2B Step Acceptance trên database test.` Expected: `BLOCKED` `MISSING_DOCUMENT_REVISION`.
4. **Purchase Order.** `/solve Ghi nhận Purchase Order PO-001 cho Project Beta NL4C2B Step Acceptance trên database test`. Expected: `BLOCKED` `ProcurementDependencyError` (no signed revision), `SIGNING_NOT_AVAILABLE`.
5. **Verify:**
   - from the transcripts and team state (`evidence_preview_evidence.status == VERIFIED`);
   - database hash unchanged, claims 20, ledger 4;
   - no pending record.

## 10a. Live read-only acceptance (2026-11-10): **FAIL, not committed**

### Records examined

- **Lead session** `cc6accb5-aa45-4562-9b90-235b2f946722`. Three `/solve` runs:

  | Run | Time | Request |
  |---|---|---|
  | `c7239b20-…` | 18:01 +07 | Ghi nhận Partner approval … |
  | `32e1ebd6-…` | 18:05 | Ghi nhận Purchase Order PO-NL4D3-001 … |
  | `63fedf2a-…` | 18:07 | Ghi nhận Purchase Request số PR-NL4D3-001 … |

- **Teammate transcript** `53917f6d-…`.
- **Team state** `team_state/cc6accb5-….json`.
- **Earlier attempt** at 17:57: session `5a784f07-…`, run `ad73e3b2-…`. It failed the pane backend check and the lead stopped the teammate (TaskStop) as required. That teammate (`25eac7c5-…`) had already started one read-only preview and delivered nothing.

### What passed

**Routing.** Every envelope had:
- `selected_agents: ["merchant-manager"]`, `operations: ["merchant_read"]`, `risk_level: read_only`;
- `merchant_database_target: test`, `requires_confirmation: false`, `confirmed: false`, no scope;
- the reasons "reconciled by local guardrail: merchant_execute" and the new NL4D3 downgrade reason.

**Dispatch.**
- Run 1 spawned `merchant-manager`, passing the PreToolUse and PostToolUse(Agent) gates.
- Runs 2 and 3 reused it through `SendMessage`, as `IDLE_REUSABLE`.
- The teammate ran on psmux server 32264, pane `%5`.
- `definition_sha256` is `144c2df0…`, the current definition.

**Teammate work.** It made exactly three CLI calls, all `agent_cli.py evidence preview --request "<verbatim>" --test-database`, and sent three SendMessage reports. There were no other Merchant commands.

**Delivery.** The last run's `evidence_preview_evidence` is `status: VERIFIED`, `database_target: test`, with:
- `read_only: true`, `executable: false`, `confirmation_available: false`;
- `authorization: null`, `requested_operation: null`;
- `authorized_operations: []`.

**Outcomes:**
- **Partner approval:** BLOCKED `MISSING_DOCUMENT_REVISION`. Correct: there are 0 revisions.
- **Purchase Order:** BLOCKED `ProcurementDependencyError` ("requires an active document revision"), with `SIGNING_NOT_AVAILABLE`. Correct.
- **Purchase Request:** PREVIEW_VALID INSERT v1, `PROCUREMENT_NOT_REQUIRED`. The engine verdict is correct.

**No writes.** No write, scope, confirmation or pending record. The lead's answers offered no write and said that nothing was recorded.

**Database (read-only check after the runs):**

| Check | Result |
|---|---|
| Hash | `ba419be9…`, unchanged |
| Claims / ledger rows | 20 / 4 |
| Revisions / approvals / procurement | 0 / 0 / 0 |
| NL4C2B step 1 `98dc77cf-…` | IN_PROGRESS v2 |
| Pending files | none new (newest from 2026-11-09); the only new runtime file is team state |
| Transaction | read-only on `coding_agent_merchant_test` as `merchant_test`; no runtime or production access |

### What failed: wrong reference extracted (correctness defect)

**Symptom.** The previews reported `requested_fields.external_reference = "NL4D3-001"` when the user typed `PO-NL4D3-001` and `PR-NL4D3-001`. The lead flagged it in both answers. A preview that shows a different reference than the one requested fails "exact requested evidence operation", and a later write built on it would store the wrong number.

**Root cause.** In `evidence_preview._REFERENCE = \b([A-Z]{2,}[A-Z0-9]*[-_/.]?\d[\w./-]*)\b`, a digit must follow the letter prefix and at most one separator. In `PO-NL4D3-001`, letters follow the separator, so the match at `PO` fails and the scan restarts at `NL4D3-001`. The keyword form (`số …`) is consulted only when that pattern finds nothing, so it never ran.

**Reproduced:**

| Input | Extracted |
|---|---|
| `PO-NL4D3-001` | `NL4D3-001` |
| `PR-NL4D3-001` | `NL4D3-001` |
| `PR_ABC_7` | nothing |
| `PR-001`, `PAY-001`, `PO-2026-01` | correct |

**Test gap.** The unit tests used only `PR-001`-style references, so the pattern passed RED/GREEN.

**Proposed fix (NL4D3-FIX1, not applied):**
1. Take whole whitespace-delimited tokens, with trailing punctuation stripped, that contain a digit and match `^[A-Za-z][A-Za-z0-9]*(?:[-_/.][A-Za-z0-9]+)*$`.
2. Prefer a keyword-anchored token (`số`, `number`, `ref`, `mã`).
3. If two different candidates remain, ask (NEEDS_CLARIFICATION) instead of picking one.
4. Keep the existing Project and Merchant name masking.
5. Add RED tests for multi-segment, underscore, lowercase and keyword-anchored references, and an "echoes exactly what was typed" property.

Then repeat the live PR and PO runs.

**Update 2026-11-11:** implemented in `cp12h_nl4d3_fix1_procurement_reference_preservation.md` (full suite 4420 passed). The live retest is pending.

### Not run

The Phase 3 commit review and the Phase 4 final regression were not repeated. The live gate failed, so no commit can follow this checkpoint. The last full regression (4375 passed, 0 failed) still stands for the code as it is.

## 11. GO/NO-GO

**Superseded by 10a.**
- **Commit:** NO-GO until NL4D3-FIX1 (reference extraction) and a passing live retest.
- **NL4D-DEC:** unchanged.

The original pre-live verdict follows.

- **NL4D3:** GO for your review and the read-only live test above.
- **NL4D-DEC (owner decisions):** **GO**, and it is now the blocking step. The previews make every undecided point concrete:
  - **S1:** who may attest LEGAL, ACCOUNTING and PARTNER, and how `acted_by` binds. Every approval preview stops here.
  - **D1:** signing command and runtime grant. PO and Payment Request stay blocked without it.
  - **D4:** hash only, or file storage.
  - **Reference format:** whether one is required.
  - **Procurement on a non-procurement Project:** whether it is allowed.
  - **D2, D3, D5:** unchanged from NL4D1.
- **NL4D4 and later execution:** NO-GO until NL4D-DEC. Not started.

## 12. Final live acceptance and commit (2026-11-11): **ACCEPTED**

**Live (after NL4D3-FIX1).** Session `d27d7f75-…`, teammate `505760cc-…`. Full evidence is in `cp12h_nl4d3_fix1_procurement_reference_preservation.md` §7.

| Request | Reference | Outcome | Delivery |
|---|---|---|---|
| Purchase Order (run `20446db1-…`) | `PO-NL4D3-001` (exact) | BLOCKED `ProcurementDependencyError`, `SIGNING_NOT_AVAILABLE` | delivered object = CLI output |
| Purchase Request (run `3a65abf8-…`) | `PR-NL4D3-001` (exact; `plan.external_id` identical) | PREVIEW_VALID INSERT, `PROCUREMENT_NOT_REQUIRED` | VERIFIED |

- **Envelopes:** `merchant-manager`, `merchant_read`, `read_only`, target `test`, no scope or confirmation.
- **Teammate:** one `evidence preview … --test-database` read per run, no other Merchant call.
- **No authority:** no pending record, no write authority.
- **Earlier runs:** the Partner approval live run (`c7239b20-…`, BLOCKED `MISSING_DOCUMENT_REVISION`) was already correct in §10a.

**Database (read-only check):**

| Check | Result |
|---|---|
| Hash | `ba419be9…`, unchanged |
| Claims / ledger rows | 20 / 4 |
| Revisions / approvals / procurement | 0 / 0 / 0 |
| NL4C2B step 1 | IN_PROGRESS v2 |
| Pending confirmations | none new (3 files, all from before NL4D3) |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` |
| Production access | none |

**Final regression** (memory 1.5 GB free, CPU 46–65%, no other pytest):

| Check | Result |
|---|---|
| NL4D3, FIX1, procurement and all PostgreSQL suites, one sequential process | 301 passed, 1 skipped (the opt-in write lifecycle test) |
| Full regression | **4420 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests) in 435 s |
| `system_test.py` | Failed 0 |
| Compile and import smoke | OK |
| `git diff --check` | clean |
| Control characters | none |

**Remaining limitations:**
1. **Approvals end at POLICY_UNDECIDED.** Every domain-valid approval preview stops there until NL4D-DEC S1 (attestation and `acted_by` binding).
2. **PO and Payment Request stay BLOCKED.** They need a signed revision, and signing has no command (D1).
3. **One reference per word.** A reference is read as a single whitespace-free word made of letters or digits joined by `- _ / .`. Anything else asks; it is an extraction limit, not a domain rule.
4. **Revision previews need the type and hash in the text.** They need an explicit document type (or a stored type written whole) and a content hash. The hash is never echoed, and its meaning is undecided (D4).
5. **Approver detection is word-based.** It recognizes LEGAL, ACCOUNTING and PARTNER wording (including "kế toán", "pháp lý", "đối tác"). Other approver words are BLOCKED `UNSUPPORTED_APPROVAL_ROLE` when found next to the approval wording, and otherwise ask.
6. **The basis is descriptive only.** `basis` and `basis_sha256` grant nothing; a future confirmation checkpoint must re-judge them in its write transaction.

**GO/NO-GO:**
- **NL4D3 with FIX1:** accepted and committed.
- **NL4D-DEC (owner decisions):** GO, and it is the next blocking step.
- **NL4D4 and any evidence, approval, procurement or signing write:** NO-GO until NL4D-DEC. Not started.

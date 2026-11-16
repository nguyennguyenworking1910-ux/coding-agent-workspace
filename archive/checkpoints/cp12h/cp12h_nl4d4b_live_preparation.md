# CP12H.NL4D4B-PREP — Controlled Purchase Request Live Acceptance Preparation

Baseline `23f1f6dd2d892dd534638c325a149f4d5783db51` (NL4D4A), branch `feat/cp7-9-merchant-reliability`. Date 2026-11-11.

- **No live Purchase Request** was executed, and no Project was created.
- **Runtime Direct EXECUTE is still disabled:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.
- **Production database:** never connected to.
- **Nothing was pushed.**
- **Committed:** only the decision register, separately, as `b66c0c0` (Phase 1).
- **Agent instructions and this report:** committed after the final review (§11), as `docs(merchant): prepare trusted purchase request live acceptance`.

## 1. Decision register update (Phase 1)

`cp12h_nl4d_decision_register.md` was reviewed and updated. It was committed on its own as **`b66c0c0`** ("docs(merchant): record approved NL4D4 procurement decisions").

| Decision | Status | Recorded as approved (the owner's wording governs where it differs from the proposed default) |
|---|---|---|
| DEC-A0 | **APPROVED 2026-11-11** | a trusted local operator ID from controlled local configuration, attribution only; **no `operators` table** |
| DEC-P1a | **APPROVED 2026-11-11** | unique **(merchant_id, procurement_type, reference)**, exact, with a database guarantee (the proposal was cross-Merchant) |
| DEC-P1c | **APPROVED 2026-11-11** | PR reference replacement **not supported**; any change is rejected (the proposal allowed replacement through an update) |
| DEC-P2 | **APPROVED 2026-11-11** | allowed when `requires_procurement=false`, with `PROCUREMENT_NOT_REQUIRED`; no workflow change |

**Where it is recorded:** the approval date and implementation commit `23f1f6dd2d892dd534638c325a149f4d5783db51` appear in:
- the header;
- each decision entry;
- the §4 table (a new Status column);
- a dated note in §9.

**Still PROPOSED:** DEC-P1b, S1, S2, D1, D4, G1 and G2. No approval was invented.

## 2. Operator setup verification (Phase 2)

**Configuration contract.** `operator_identity.trusted_operator_id()` reads `MERCHANT_OPERATOR_ID`:
- **Sources:** the process environment, or the repository `.env`, loaded by `python-dotenv` from the absolute repository path with `override=False`.
- **Format:** one canonical lowercase UUID, not the nil UUID.
- **Failure:** anything else is `OPERATOR_IDENTITY_UNAVAILABLE` or `OPERATOR_IDENTITY_INVALID`.

**Setup:**
- **Generation and storage:**
  - A fresh UUID was generated with Python's `uuid.uuid4()` (OS CSPRNG).
  - It was appended to the existing `.env` by a script that prints only a SHA-256 fingerprint and refuses to overwrite an existing key.
  - The value was never printed, never placed in a prompt and never read back into this session.
- **Fingerprint:** sha256[:12] = **`210a4c001d41`**.
- **`.env` status:**
  - git-ignored (`git check-ignore`) and untracked;
  - the variable is not set in the Process, User or Machine environment, so nothing can shadow `.env`.

**Loading verified.** Each context printed status and fingerprint only:

| Process | Interpreter | Result |
|---|---|---|
| Hook interpreter (`${CLAUDE_PROJECT_DIR}/.venv/Scripts/python.exe`, as `settings.json` runs every hook) | .venv 3.11.9 | TRUSTED `210a4c001d41` |
| The same, from another working directory | .venv 3.11.9 | TRUSTED `210a4c001d41` |
| The teammate's CLI interpreter (`python` on PATH) | system 3.11.9, dotenv installed | TRUSTED `210a4c001d41` |
| Windows PowerShell 5.1 → `python` | system 3.11.9 | TRUSTED `210a4c001d41` |
| The real `agent_cli.py evidence preview … --test-database` (a read, against the NL4C2B Project) | system 3.11.9 | PREVIEW_VALID; `recording_operator` TRUSTED `210a4c001d41`; operation operator `210a4c001d41`; NOT_AUTHORIZED; `PROCUREMENT_NOT_REQUIRED` |

**Environment loading.**
- Every path loads the same file by absolute path, so PowerShell, Claude Code, psmux panes and hook processes agree.
- `pwsh` is not on this process's PATH, but a pane using it still resolves `.env` the same way.
- The only way for processes to diverge is a `MERCHANT_OPERATOR_ID` set in one shell's environment, which overrides `.env`; none is set.
- Do not set it in any shell during the live run.

**Stability and fail-closed behaviour.**
- **Stability:** the value is static for the whole preview, confirm and execute lifecycle unless `.env` is edited.
- **Verified failures:**
  - an empty value gives `OPERATOR_IDENTITY_UNAVAILABLE`;
  - a malformed value or the nil UUID gives `OPERATOR_IDENTITY_INVALID`;
  - a changed value resolves to a different operator (fingerprint `c9add0ce108a`), which the capture, gate, preflight and in-transaction checks refuse (NL4D4A tests).
- **Nothing hard-coded:** validation is unchanged and no code embeds the ID.

**Finding: the operator ID becomes visible in model context during the live run.** It is not supplied by the model, but trusted code and tool output carry it in four places:
1. the preview JSON (`recording_operator.operator_id`, `requested_operation.operator_id` and its argv `--operator-id`), which the teammate must deliver verbatim;
2. the intent gate's confirmation `systemMessage` ("recorded by operator …");
3. the persisted scope argv the teammate sends back;
4. `project_events.triggered_by` (by design).

This is not a credential:
- seeing or retyping it grants nothing;
- every check re-resolves the configured value;
- a model-supplied ID is refused (`PURCHASE_REQUEST_CONFIRMATION_MISMATCH`).

It does mean the Phase 2 rule "never place the operator ID in model prompts" holds for *setup* only, not for the live run. Accept this, or require a small display change before LIVE (§10).

## 3. Agent instruction changes (Phase 3; committed after the §11 review)

**`.claude/agents/merchant-manager.md`**, evidence write preview section:
- **The one confirmable case:** a `PREVIEW_VALID` new PR on the test database with `confirmation_available: true` and a NOT_AUTHORIZED `requested_operation`.
- **Trusted pending record:** the trusted hook, not the teammate, creates it (15 minutes, single use). It binds the Merchant, Project, reference, test database and the operator, which comes only from trusted local configuration.
- **Who confirms:** only the user, with `/solve Xác nhận ghi nhận <8 chars of project_id>` (cancel `/solve Hủy ghi nhận`).
- **The teammate never:**
  - confirms, sends or schedules the phrase;
  - chooses an operator;
  - offers a scope, argv or write command.

  A handwritten procurement scope is refused and is never authorization.
- **What the teammate relays:**
  - `PROCUREMENT_NOT_REQUIRED`;
  - `confirmation_blockers`;
  - `PROCUREMENT_REFERENCE_DUPLICATE` and `…REPLACEMENT_UNSUPPORTED` (BLOCKED).
- **No live write** for POs, Payment Requests, revisions, approvals or signing. Runtime is disabled.
- **The confirmed PR** arrives as an ordinary scoped `merchant_execute` assignment; the trusted Direct EXECUTE hook performs the write.
- **The discovery section** no longer says "no such write exists yet". It still offers nothing from that read.

**`.claude/commands/solve.md`:**
- **Conversational confirmation** covers the third store (`purchase_request`). It is refused unspent if the operator is missing or changed, and no kind confirms another.
- **The test-mode list** adds the confirmed PR create, with no general procurement update.
- **Evidence write preview delivery:** on `confirmation_available: true`, the lead tells the user they may type `/solve Xác nhận ghi nhận <8 chars>`, naming:
  - the reference;
  - the Project and Merchant;
  - the test database;
  - the operator status;
  - `PROCUREMENT_NOT_REQUIRED`.

  The lead never submits, schedules or relays the phrase, and offers nothing else.
- **The discovery section** wording is aligned.

**`CLAUDE.md`:** unchanged; the NL4D4A paragraph is already committed.

**A fresh session is required.** The team state holds 34 teammate records (29 of them `merchant-manager`; statuses IDLE_REUSABLE or FAILED), all recorded with the *old* definition hash. None matches the new `merchant-manager.md`, so any reuse is refused as STALE_DEFINITION. Start a **fresh Claude Code session** (psmux, teammate mode tmux) so `/solve` and `merchant-manager` load the new definitions.

## 4. Proposed acceptance Project (Phase 4, not created)

| Field | Value |
|---|---|
| Title | **Beta NL4D4B PR Acceptance** (no Project with this title exists) |
| Merchant | `NL2_LIVE_BETA` (Beta Cinemas, ACTIVE, `6e0c1a2b-…`) |
| Database | `coding_agent_merchant_test` |
| Workflow | `OPENING_NEW_CINEMA_STANDARD` |
| `requires_procurement` | **false** (exercises DEC-P2) |

The wording was checked with a read-only CLI `project preview`, with no hook involved, so nothing was recorded. The exact request below returns `READY_FOR_CONFIRMATION` with:
- title `Beta NL4D4B PR Acceptance`;
- Merchant `NL2_LIVE_BETA`;
- `OPENING_NEW_CINEMA` / `OPENING_NEW_CINEMA_STANDARD`;
- `requires_procurement: false`;
- `database_target: test`;
- status NOT_AUTHORIZED.

```
/solve Tạo project mở rạp Beta NL4D4B PR Acceptance cho Merchant Beta Cinemas trên database test, không cần mua sắm
/solve Xác nhận tạo <first 8 characters of the project_id shown>
```

## 5. PR reference (Phase 5)

The reference is **`PR-NL4D4B-001`**. Read-only queries on the test database found:
- exact holders for (`NL2_LIVE_BETA`, `PURCHASE_REQUEST`, `PR-NL4D4B-001`): **none**;
- holders in any Merchant, any type, ignoring case: **0**;
- `procurement_records_merchant_type_reference_unique_idx` is valid and unique: `(merchant_id, procurement_type, external_id) WHERE external_id IS NOT NULL`;
- the composite FK is validated.

Nothing was reserved or inserted. The real CLI preview extracts the reference exactly (§2).

## 6. Preflight results (Phase 6)

| Check | Result |
|---|---|
| Branch / HEAD | `feat/cp7-9-merchant-reliability`, HEAD `b66c0c0` (register) on top of `23f1f6d`; 15 ahead, 0 behind, nothing pushed |
| Working tree | modified: `merchant-manager.md`, `solve.md`; untracked: this report |
| Migration 007 | applied to the test database (versions 1–7) |
| Operator identity | configured; TRUSTED `210a4c001d41` in every process type (§2) |
| Database identity and role | `coding_agent_merchant_test` / `merchant_test`, read-only session |
| Integrity baseline | `60ea5bc9b4297182f895deadf83d82b905b8c0e0ae380d368910167795e3b3d4`, unchanged |
| PostgreSQL tests running | none (no other session on the database; pytest advisory lock not held) — re-check immediately before LIVE |
| Stale teammate definition | all recorded teammates are stale for the new definition, so reuse is refused; LIVE needs a fresh session |
| Execution claims | 20, all COMPLETED; no ACTIVE claim; ledger 4 |
| Pending confirmations | only 3 earlier records (2 Project, 1 Step), all CONFIRMED and expired; no Purchase Request store |
| Runtime Direct EXECUTE | `False` |
| Production | never connected |

## 7. Regression results (Phase 7)

The `.env` change affects every test process, and the agent instructions changed, so the full regression was run.

| Run | Result |
|---|---|
| Targeted (NL4D4A unit and PG, NL4D3 and FIX1, NL4C1, NL4C2A, NL3, merchant-manager agent and registration, procurement engine and repository), **with the real operator configured** | 440 passed |
| Full suite, with the real operator configured | **4526 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests), 6 min 17 s; matches the accepted regression |
| `system_test.py` | ALL TESTS PASSED |
| Hook compile/import smoke | 58 files compiled; the main hooks import; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean |
| Integrity after the regression | `60ea5bc9…`, unchanged |

PostgreSQL tests ran sequentially. There was no live write.

## 8. Live runbook (NL4D4B-LIVE, not executed)

**Before starting:**
1. Close every other Claude Code and pytest process that uses the test database.
2. Start a **fresh** Claude Code session in psmux (PowerShell 7, teammate mode tmux).
3. Do not set `MERCHANT_OPERATOR_ID` in any shell.
4. Take the baseline hash: `.venv/Scripts/python.exe <scratchpad>/db_integrity.py` should give `60ea5bc9…`.

The verification script is `nl4d4b_live_verify.py` in this session's scratchpad:
`C:\Users\nguyen.nguyen30\AppData\Local\Temp\claude\008e84bdc82d3955\0d7274c0-179a-4e80-8e12-f40dffbf9c16\scratchpad\nl4d4b_live_verify.py`. It is read-only and prints the operator only as a fingerprint. Run it with the `.venv` interpreter from the repository root.

| # | Action (you type it) | Expected | Stop if |
|---|---|---|---|
| A1 | `/solve Tạo project mở rạp Beta NL4D4B PR Acceptance cho Merchant Beta Cinemas trên database test, không cần mua sắm` | read-only `project preview`, READY, NOT_AUTHORIZED operation; title, `NL2_LIVE_BETA`, no procurement, test | anything differs → `/solve Hủy tạo` |
| A2 | `/solve Xác nhận tạo <8 chars>` | one Project create; `EXECUTE_SUCCESS` | any failure: do not retry |
| A3 | `nl4d4b_live_verify.py project` | ALL PASS:<br>• one Project, `NL2_LIVE_BETA`, standard workflow, no procurement;<br>• 22 steps, step 1 READY, no procurement record;<br>• NL2/NL3/NL4C2B unchanged;<br>• step snapshot saved.<br>Note the new hash, H1. | any FAIL |
| B1 | `/solve Ghi nhận Purchase Request PR-NL4D4B-001 cho Project Beta NL4D4B PR Acceptance trên database test` | read-only `evidence preview`:<br>• `PREVIEW_VALID`, `confirmation_available: true`;<br>• `requested_operation` NOT_AUTHORIZED, `database_target: test`;<br>• note `PROCUREMENT_NOT_REQUIRED`;<br>• `recording_operator.status: TRUSTED`.<br>The lead offers `/solve Xác nhận ghi nhận <8 chars>`. **Nothing recorded.** | not VALID, blockers present, or a different reference |
| B2 | Check the block: reference exactly `PR-NL4D4B-001`, Project title, Merchant `NL2_LIVE_BETA`, test database, operator TRUSTED. Optionally compare the operator's fingerprint with `210a4c001d41`. | exact | anything differs → `/solve Hủy ghi nhận <id>` and stop |
| B3 | `/solve Xác nhận ghi nhận <first 8 characters of project_id>` | the system message "Confirmed Purchase Request 'PR-NL4D4B-001' for Project 'Beta NL4D4B PR Acceptance' (NL2_LIVE_BETA …) … on the test database. It runs once now."; exactly one execution attempt; `EXECUTE_SUCCESS`; teammate IDLE_REUSABLE | refusal or failure: **do not retry**; record the reason |
| C1 | `nl4d4b_live_verify.py final` | ALL PASS (see the list after this table) | any FAIL |
| C2 | Replay `/solve Xác nhận ghi nhận` | refused ("no pending Purchase Request"); nothing written | anything written |
| C3 | Optional: preview the same request again (B1 text) | `BLOCKED` or no confirmation (the record exists or the reference is held) | a confirmation is offered |
| C4 | `db_integrity.py` | a new hash, H2 ≠ H1. Only the expected rows were added: 1 procurement row, 1 PROCUREMENT event, 1 claim, 1 ledger row (and the Project rows from A2) | any other change |

**C1 checks:**
- no Step status or version changed since A3;
- exactly one procurement record: `PURCHASE_REQUEST`, exact reference, version 1, the Project's Merchant, status null;
- the reference is held once in the Merchant;
- one `PROCUREMENT_CREATED` event whose `triggered_by` fingerprint equals the configured operator's;
- exactly one receipt rebuilt from PostgreSQL alone, with claim COMPLETED, ledger command `procurement update` and the exact binding;
- record, event, claim and ledger share one `xmin`;
- NL2/NL3/NL4C2B are unchanged, and the NL4C2B step is still IN_PROGRESS v2.

**Rules:**
- one preview, one confirmation and one execution;
- no manual database edits;
- no second attempt after any failure;
- no runtime target.

## 9. Fail-closed behaviour during LIVE

| Situation | Behaviour |
|---|---|
| Operator missing or malformed | no operation in the preview (`confirmation_blockers`), or the confirmation is refused unspent, or `PREFLIGHT:OPERATOR_IDENTITY_*` |
| Operator changed after the preview | capture UNVERIFIED, or confirmation refused unspent, or `PREFLIGHT:OPERATOR_IDENTITY_CHANGED`; inside the transaction: FAILED, fenced |
| Project changed, or the reference recorded elsewhere in the Merchant, after B1 | `PREFLIGHT:PURCHASE_REQUEST_BASIS_CHANGED` / `PROCUREMENT_REFERENCE_DUPLICATE`, nothing spent; inside the transaction: FAILED, claim REVOKED, nothing written |
| Two writes race for the reference | the unique index commits at most one |
| Stale or reused teammate, unverified pane | refused before any spend |
| Typed or edited procurement scope, or model-supplied operator | refused at the gate or the preflight |
| Crash after commit | settled from durable evidence; receipt rebuilt from PostgreSQL; never retried |
| Runtime target | refused at the preview, gate and preflight |

## 10. GO / NO-GO for NL4D4B-LIVE

**Ready:**
- the decisions are recorded;
- the operator is configured and verified across processes;
- the instructions are updated;
- the Project and reference are verified free;
- the preflight is clean;
- the regression passes (§7).

**Conditional GO.** LIVE may start once all four of these hold:
1. **You accept the operator-ID visibility finding (§2).** The UUID will appear in the preview, the confirmation message and the scope. It grants nothing. If that is not acceptable, it is NO-GO until a small fix shows only a fingerprint in the preview, `systemMessage` and lead summary, which needs a separate implementation checkpoint.
2. **You decide whether to commit the agent-instruction changes first.** They are uncommitted as instructed, and they work from the working tree.
3. **The session is fresh** (§3).
4. **The machine is otherwise idle.** No PostgreSQL tests, other sessions or a second `/solve` on the test database during the run.

**Out of scope:** runtime/production, Purchase Orders, Payment Requests, revisions, approvals, signing, and NL4D5 remain NO-GO.

## 11. Final review and commit (2026-11-11)

**Owner decisions recorded for this checkpoint:**
1. The operator UUID may appear in the local test preview, the confirmation and the trusted execution scope.
2. It is attribution metadata, not an authentication credential.
3. The trusted environment remains the authoritative operator source.
4. The agent instructions are committed before live acceptance.

This resolves conditions 1 and 2 of §10.

### 11.1 Operator trust boundary

Every *authoritative* check resolves the operator from trusted local configuration itself (`operator_identity.trusted_operator_id()`, reading the environment or `.env`). A displayed or carried UUID is only ever **compared against** that value; it is never accepted as the source.

| Stage | Code | Source of truth | A displayed UUID is |
|---|---|---|---|
| Load | `operator_identity.trusted_operator_id` | process environment, or `.env` by absolute path; canonical non-nil UUID | — |
| Preview | `read_commands.evidence_preview` → `operator_status()` → `evidence_preview._purchase_request_operation` | trusted config; the request text is never read for it | produced from config |
| Capture | `merchant_preview_delivery._evidence_operation_consistent` | **fresh `trusted_operator_id()`** in the hook | compared; a mismatch is UNVERIFIED, no pending record |
| Pending record | `record_pending_purchase_request` | copied from the verified operation | data only |
| Confirmation | `intent_gate.confirm_pending_purchase_request` → `allowed()` → `require_operator(record.operator_id)` | **fresh trusted config** | compared; a mismatch is refused unspent |
| Scope construction | `validate_direct_scope` / `_require_canonical_purchase_request_argv` | structure only (canonical argv); grants nothing | — |
| Preflight | `_confirmed_purchase_request_operation`: staged argv must equal the confirmed record's argv, then `require_operator(operation.operator_id)` | **fresh trusted config** | compared; `OPERATOR_IDENTITY_CHANGED` / `…_MISMATCH` |
| Preflight re-judgement | `_verify_purchase_request` → `verify_purchase_request(…, operation.operator_id)` | the value just verified equal to trusted config in the same call | — |
| Transaction | `write_adapters._record_confirmed_purchase_request`: `operator = require_operator(payload.operator_id)`; precondition `verify_purchase_request(…, require_operator(operator))`; `triggered_by=operator` | **fresh trusted config, twice**; the value written is the one `trusted_operator_id()` returned | compared; a mismatch fails the transaction and fences the claim |
| Receipt | `attempt_evidence.purchase_request_receipt` | `project_events.triggered_by`, written from trusted config | reconciliation only, no authority |

**Substitution is impossible:**

| Attempt | Result | Test |
|---|---|---|
| Prompt-supplied operator (text, UUID or `--operator-id` inside the request) | ignored; the operation names only the configured operator | `test_the_operator_never_comes_from_the_request_or_a_teammate` |
| Model- or teammate-generated operator (an edited execute argv) | `PURCHASE_REQUEST_CONFIRMATION_MISMATCH` before spend | `changed_scope_is_refused[actor]`; PG `a_model_generated_actor_cannot_be_executed` |
| Forged preview capture with another operator | UNVERIFIED; no pending record | `a_forged_or_inconsistent_capture_records_nothing`, `…another_operator_than_the_hook_resolves…` |
| Handwritten procurement scope, even carrying the correct visible UUID | refused at the intent gate on both targets; a scope never reaches the preflight without this run's confirmed record | `a_handwritten_scope_is_never_authority[None,test]` |
| Changing configuration after the preview | refused at the gate (unspent), the preflight or inside the transaction | `operator_substitution_before_confirmation…`, `operator_change_after_confirmation…`, PG `operator_substitution_inside_the_transaction` |
| Bypassing configuration | no code path accepts an operator from a payload, argv or message as the source; merchant-manager cannot set environment variables (its only executable surface is the literal `agent_cli.py` call) | code review above |

**Verdict:** no check trusts only the displayed UUID. Knowing the UUID grants nothing, because every authority point also requires:
- this session's own verified, single-use pending record;
- the exact canonical argv;
- the configured operator.

**Residual risk, unchanged:** any same-OS-user process that can edit `.env` changes the operator for future operations. That is the same workstation boundary as the database credentials.

### 11.2 Agent instruction review

| Requirement | `merchant-manager.md` | `solve.md` |
|---|---|---|
| PR preview is read-only | "the preview itself never records anything" | "Nothing was recorded or changed. PREVIEW_VALID is not an authorization" |
| Only a verified pending confirmation enables the test-only PR | the trusted hook creates it; test only | "appears only on a PREVIEW_VALID new Purchase Request on the test database" |
| Only the user types `/solve Xác nhận ghi nhận`; no auto-confirmation | "never confirm, send or schedule that phrase" | "Only the user's own prompt confirms. Never submit, schedule or relay it" |
| No retries after uncertain execution | added: "Never retry after a refusal, failure or uncertain result"; also the general Direct EXECUTE rule ("never retry after … uncertain execution") | added "No retry" bullet; also the general rule ("one attempt only; an uncertain or failed result must be reported, not retried") |
| No handwritten procurement scope | "refused, and is never authorization" | the same |
| No PO, Payment Request, revision, approval or signing execution | "no live write" | "Never offered" paragraph |
| Runtime disabled | "nothing is confirmable on the runtime database" | "nothing is offered for a runtime target" |

**Scope of the edits:** only the evidence-discovery and evidence-write-preview passages, the conversational-confirmation paragraph and the test-mode list changed. Nothing unrelated was edited.

### 11.3 Preflight, re-run

| Check | Result |
|---|---|
| Migration 007 | applied (versions 1–7); unique index valid; composite FK validated |
| Test database identity and role | `coding_agent_merchant_test` / `merchant_test`, read-only session |
| Operator fingerprint | `210a4c001d41` from the hook interpreter (`.venv`), the teammate interpreter (`python`) and another working directory. Not set in the Process, User or Machine environment. The full UUID is not printed anywhere in this report. |
| Other PostgreSQL test processes | none: no Python process, no other session on the database, pytest advisory lock not held |
| Claims | 20, all COMPLETED; no active or conflicting claim; ledger 4 |
| Pending confirmations | 3 earlier records, all CONFIRMED and expired; no Purchase Request store |
| `PR-NL4D4B-001` | unused (0 holders in any Merchant, type or case); no Project titled "Beta NL4D4B PR Acceptance" |
| Integrity | `60ea5bc9…`, unchanged |
| Production | never accessed |

### 11.4 Regression

No code changed, only the instructions, so a full re-run was not required. The last full run, on these instructions minus the two no-retry sentences, was 4526 passed, 20 skipped, 1 xfailed, 0 failed (§7).

| Run | Result |
|---|---|
| Targeted routing, preview and confirmation suites (NL4D4A unit and PG, NL4D3 and FIX1, NL4D3 PG, NL4D2 and FIX1 routing, NL4C1, NL4C2A, NL3, NL4B routing, merchant-manager agent and registration) | 497 passed |
| Operator and authority subset (operator, actor, handwritten, forged, capture, edited, changed-scope) | 46 passed |
| `system_test.py` | ALL TESTS PASSED |
| Hook compile/import smoke | 56 hooks; main hooks import; `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |
| `git diff --check` | clean |

### 11.5 GO / NO-GO

**NL4D4B-LIVE: GO.** Conditions 1 and 2 of §10 are met by the decisions above and this commit. It must still run in a **fresh Claude Code session** on an otherwise idle machine, following the §8 runbook exactly once, with no retries.

**Still NO-GO:** runtime/production, Purchase Orders, Payment Requests, revisions, approvals, signing, and NL4D5.

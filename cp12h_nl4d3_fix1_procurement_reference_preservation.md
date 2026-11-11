# CP12H.NL4D3-FIX1 — Exact Procurement Reference Preservation

Baseline `d06e074672f90b9b020f9fddf4b258c9c8fdabd8` (+ uncommitted NL4D3), branch `feat/cp7-9-merchant-reliability`. Date 2026-11-11.

- **Git:** not committed, not pushed. All uncommitted NL4D3 changes are preserved.
- **Writes:** no evidence, approval, procurement or signing write. No procurement execution. NL4D4 not started.
- **Runtime:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

## 1. Live failures

| Request (live /solve, session `cc6accb5-…`) | Typed | Previewed |
|---|---|---|
| Ghi nhận Purchase Order PO-NL4D3-001 cho Project Beta NL4C2B Step Acceptance trên database test (run `32e1ebd6-…`) | `PO-NL4D3-001` | `NL4D3-001` |
| Ghi nhận Purchase Request số PR-NL4D3-001 cho Project Beta NL4C2B Step Acceptance trên database test (run `63fedf2a-…`) | `PR-NL4D3-001` | `NL4D3-001` |

## 2. Trace and root cause (Phase 1)

| Stage | Evidence | Reference |
|---|---|---|
| Raw prompt → UserPromptSubmit envelope `raw_request` | lead transcript `cc6accb5-…`, envelopes of both runs | **full** |
| `/solve` → lead assignment (SendMessage) | lead transcript | **full** |
| Teammate CLI argv `agent_cli.py evidence preview --request "…" --test-database` | teammate transcript `53917f6d-…` | **full** |
| `prepare_agent_cli_argv` → argparse `args.request` | reproduced locally: equal to the input | **full** |
| `project_nl.interpret_project_request` | `project_phrase = "Beta NL4C2B Step Acceptance"`, no Merchant phrase (correct) | not a reference owner |
| **`evidence_preview._reference`** | `_REFERENCE = \b([A-Z]{2,}[A-Z0-9]*[-_/.]?\d[\w./-]*)\b` | **`NL4D3-001`: lost here** |
| `propose_procurement_mutation` | received the shortened value | shortened |
| `redact_payload` | `external_reference` is not a sensitive field: unchanged | shortened |
| CLI JSON → PostToolUse capture → SendMessage block | the delivered block equals the captured CLI output (10 occurrences of `"NL4D3-001"`) | shortened, faithfully delivered |

**Root cause.** The pattern required a digit immediately after the letter prefix and at most one separator. In `PO-NL4D3-001`, letters follow the first separator, so no match starts at `PO`. `finditer` then restarted at the next word boundary and matched `NL4D3-001`.

- **The fallback never ran.** The keyword fallback (`số …`) was consulted only when that pattern found nothing.
- **Unsafe text was accepted.** The pattern also took `PR-001` out of `PR-001;rm`, `PR-001$(whoami)` and `PR-001';DROP TABLE …` instead of refusing.
- **Test gap.** The NL4D3 tests used only `PR-001`-style references.

**Only owner.** `evidence_preview._reference`. The parser, intent gate, CLI, redaction and delivery all preserve the text.

## 3. Exact changes (Phase 2)

`.claude/agents/tools/merchant/evidence_preview.py` only.

**`_reference` is rewritten.** It returns `(reference, None)` or `(None, MISSING | AMBIGUOUS | UNSAFE)`:
1. **Control characters:** any control character other than tab or newline in the request → `UNSAFE`.
2. **Masking:** the Project phrase, Merchant phrase and UUIDs are removed, exactly as before.
3. **Tokens:** the rest is split on whitespace. Each token is unwrapped (`_unwrapped`). The **only** normalizations, documented in the code:
   - matching surrounding quotes or brackets (`" ' \` “” ‘’ «» () [] 「」`);
   - one leading `#`;
   - trailing sentence punctuation (`. , ! ? :`);
   - NFC.
4. **Classification of a digit-bearing token:**
   - it must be letters or digits joined by `- _ / .` (`^[^\W_](?:[\w./-]*[^\W_])?$`, Unicode letters allowed), or the whole reference is `UNSAFE` (metacharacters, dangling separator, unbalanced quote);
   - a bare number counts only after an anchor word (`số`, `number`, `no`, `ref`, `mã`, `id`, or the record's name: `Request`, `Order`, `hàng`, `toán`) or a `#`.
5. **Count:** zero candidates → `MISSING`; two different ones → `AMBIGUOUS`; exactly one → returned **whole, never shortened or rebuilt**.

**Procurement preview.** `MISSING`, `AMBIGUOUS` and `UNSAFE` each end `NEEDS_CLARIFICATION`, with `missing_required_fields: ["external_reference"]`, `requested_fields.reference_problem` and a specific question. The engine is not called (`domain_validation.status: NOT_EVALUATED`).

**Plan.** `domain_validation.plan` now includes the engine's `external_id`, so the value the domain received is visible next to the requested one.

**Not changed:**
- Domain rules: non-blank, ≤ 100 characters (`ProcurementEngineError`), one record per type, PO and Payment Request dependencies, signing prerequisites.
- `PROCUREMENT_NOT_REQUIRED` stays an informational note; a Purchase Request on a no-procurement Project is still `PREVIEW_VALID`.
- No reference-format rule was added. The token shape is an extraction limit for reading free text, documented as such, and an unreadable reference only asks.
- No CLI, hook, policy gate, allowlist, pending-confirmation or authorization change.

## 4. RED/GREEN

**New test file:** `tests/merchant/test_nl4d3_fix1_reference_preservation.py`, 45 tests. It drives `build_evidence_preview` and the real verified-delivery hook with both exact live requests.

| | Result |
|---|---|
| **RED** (NL4D3 code before this fix) | **30 failed**, 15 passed |
| **GREEN** | **45 passed**; with NL4D3's 92: **137 passed** |

**The 30 RED failures:**
- both exact live requests;
- domain hand-off (`plan.external_id`);
- the PR-, PO-, PAY-NL4D3-001, lowercase and `ĐH-…` shapes;
- all 10 quoting and punctuation forms;
- NFD normalization;
- anchored numbers;
- 8 injection and unsafe forms (SQL `';DROP TABLE …;--`, `;rm`, `$(whoami)`, `|ls`, `&&`, `>`, ANSI escape `\x1b[2J`, dangling `-`);
- the domain-rules check;
- the delivery check.

**The 15 that already passed:**
- references that were already handled: `PR-2026-0001`, `PO/2026/001`, `PR_2026_001`, `ABC-123-XYZ`, `PR.2026.001`;
- requests that already asked: two references, newline, missing, spaced, quoted with a space, NUL;
- mixed and negated requests;
- a Project-title token used as the reference.

**Covered cases:**

| Category | Cases | Expected |
|---|---|---|
| Live requests | `PO-NL4D3-001`, `PR-NL4D3-001` | exact reference; PO stays BLOCKED (`ProcurementDependencyError`), PR stays PREVIEW_VALID INSERT |
| Domain hand-off | `plan.external_id` | equals the requested reference |
| Shapes | `PR-NL4D3-001`, `PO-NL4D3-001`, `PAY-NL4D3-001`, `PR-2026-0001`, `PO/2026/001`, `PR_2026_001`, `ABC-123-XYZ`, `pr-nl4d3-001`, `ĐH-2026-001`, `PR.2026.001` | kept whole |
| Normalization | quoted, backticked, “curly”, `(…)`, trailing `,` and `:`, `số …`, `number …`, `#…` | `PR-NL4D3-001`; NFD → NFC |
| Anchored numbers | `số 2026001` and `Purchase Request 2026001` | accepted |
| Unanchored number | "năm 2026" | ignored |
| Project-title token | `NL4C2B` | never the reference; `NL4C2B-001` kept whole |
| Fail closed | two references, a replaced reference, newline-separated references, missing, `PR - 001`, `"PR 001"`, SQL / shell metacharacters, NUL, ANSI escape, dangling separator | NEEDS_CLARIFICATION, engine not called, no reference echoed |
| Mixed and negated | with an exact reference | still NEEDS_CLARIFICATION |
| Domain unchanged | 120-character reference | BLOCKED by the domain's 100-character rule |
| Domain unchanged | Payment Request without a PO | BLOCKED, reference exact |
| Delivery | a teammate block whose `external_reference` was changed (`NL4D3-001`, `PR-NL4D3-002`, a trailing space) | denied; only the exact captured object is delivered |

## 5. Security regression

- **No new authority:**
  - every outcome is still `read_only: true`, `executable: false`, `confirmation_available: false`, `authorization: null`, `requested_operation: null`, with no pending record;
  - `TEST_MODE_COMMANDS` unchanged (`merchant create`, `project create`, `step update`).
- **Injection:**
  - a request containing SQL or shell metacharacters in the reference is never passed to the engine;
  - the Merchant reads are parameterized and read-only regardless;
  - merchant-manager's Bash policy still allows only one literal `agent_cli.py` invocation, with no chaining, redirection or substitution.
- **Delivery:** verified source-backed delivery is unchanged and proven to refuse a modified reference.

## 6. Regression

**Preflight:** 1,490 MB free memory, CPU 17%, no other pytest process.

| Check | Result |
|---|---|
| FIX1 + NL4D3 unit tests | 137 passed |
| Targeted, one sequential process: FIX1, NL4D3, NL4D3 PostgreSQL, procurement engine and repository, NL4D2 (+ PostgreSQL), NL4D2-FIX1, Merchant intent routing, CLI contract, NL2*, NL3*, NL4A*, NL4B*, NL4C* (all PostgreSQL suites, sequential) | **980 passed, 1 skipped** |
| Full regression, `pytest ./tests -q --tb=short`, one process | **4420 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests) in 332 s |
| `python .claude/system_test.py` | Failed 0, fully operational |
| Compile and import smoke (all hooks, all Merchant tools, `intent_parser`) | OK |
| `git diff --check` | clean |
| Control characters in `.claude/**/*.py`, `tests/**/*.py` | none |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` |
| `TEST_MODE_COMMANDS` | unchanged |

- **The skip:** `test_procurement_repository_live.py`, the opt-in (`MERCHANT_RUN_LIVE_TESTS=1`) lifecycle test that writes to the test database. It is part of the baseline 20 skipped, and it was not run because no write is allowed.
- **The count:** 4420 is NL4D3's 4375 plus the 45 new tests, with no existing test changed.

**Database integrity (read-only check):**

| Check | Result |
|---|---|
| Hash | `ba419be9d17a7a6719f1ca864ff5bdc1fe01848a7ad65a857e023715d028a319`, unchanged |
| Claims / ledger rows | 20 / 4 |
| `document_revisions` / `document_approvals` / `procurement_records` | 0 / 0 / 0 |
| `PYTEST%` Merchants | 0 |
| NL4C2B step 1 `98dc77cf-…` | IN_PROGRESS v2 |
| Pending confirmations | none new: only the 2026-11-04 and 2026-11-09 files |

## 7. Live retest: PASS (2026-11-11)

**Records:**
- lead session `d27d7f75-5ee1-4e92-bc01-7c068df9d0f5`;
- teammate transcript `505760cc-90ba-4fa0-9b36-05f4c4de2ecd`;
- team state `team_state/d27d7f75-….json`.

The original wording was used, unchanged.

| | Purchase Order | Purchase Request |
|---|---|---|
| `/solve` | Ghi nhận Purchase Order PO-NL4D3-001 cho Project Beta NL4C2B Step Acceptance trên database test | Ghi nhận Purchase Request số PR-NL4D3-001 cho Project Beta NL4C2B Step Acceptance trên database test |
| Run / time | `20446db1-…`, 10:38 +07 | `3a65abf8-…`, 10:46 +07 |
| Envelope | `merchant-manager`, `merchant_read`, `read_only`, target `test`, `requires_confirmation` false, `confirmed` false, `merchant_scope` null, reason "reconciled by local guardrail" | same |
| Dispatch | `Agent` spawn; Pre/PostToolUse(Agent) gates passed | reuse via `SendMessage` (`IDLE_REUSABLE`); PreToolUse(SendMessage) passed |
| Teammate command (only Merchant call) | `agent_cli.py evidence preview --request "<verbatim>" --test-database` | same |
| `requested_fields.external_reference` | **`PO-NL4D3-001`** | **`PR-NL4D3-001`** |
| Domain | BLOCKED `ProcurementDependencyError`: "Procurement operation requires an active document revision"; note `SIGNING_NOT_AVAILABLE` | PREVIEW_VALID INSERT v1, `PROCUREMENT_CREATED`; **`plan.external_id` = `PR-NL4D3-001`**; note `PROCUREMENT_NOT_REQUIRED` |
| Flags | `read_only` true, `executable` false, `confirmation_available` false, `authorization` null, `requested_operation` null, project `8dd4c68d-…` | same |
| Delivery | `MERCHANT_EVIDENCE_PREVIEW_JSON:` once; delivered object **equals** the CLI output; Pre/PostToolUse(SendMessage) passed with no denial | same; team state `evidence_preview_evidence` **VERIFIED**, target `test`, equal to the CLI output |
| Lead answer | reference `PO-NL4D3-001`, BLOCKED, nothing recorded, no confirmation, scope or command | reference `PR-NL4D3-001`, PREVIEW_VALID, not authority, nothing recorded |

**Teammate:**
- `merchant-manager` ran in psmux server 26136, pane `%4`.
- `definition_sha256 144c2df0…` equals the current `merchant-manager.md`.
- `authorized_operations: []`, `report_source: sendmessage`.
- Its only tools were Read, two Bash `agent_cli.py` reads and two SendMessage reports.

**Database after the runs (read-only, `coding_agent_merchant_test` as `merchant_test`, no txid):**

| Check | Result |
|---|---|
| Hash | `ba419be9…`, unchanged |
| Claims / ledger rows | 20 / 4 |
| Revisions / approvals / procurement for the Project (and table-wide) | 0 / 0 / 0 |
| Step 1 | IN_PROGRESS v2 |
| Pending files | none new (newest from 2026-11-09); the only new runtime file is the session's team state |
| Runtime Direct EXECUTE | `RUNTIME_DIRECT_EXECUTE_ENABLED = False` |

## 8. GO/NO-GO

- **NL4D3-FIX1:** ACCEPTED. The live references are exact, the domain outcomes are unchanged and nothing was written.
- **NL4D3 commit:** GO, subject to the final regression in `cp12h_nl4d3_evidence_write_previews.md` §12.
- **NL4D4, and evidence, approval, procurement or signing writes:** NO-GO until the NL4D-DEC decisions. Not started.

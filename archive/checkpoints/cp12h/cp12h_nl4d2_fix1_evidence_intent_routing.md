# CP12H.NL4D2-FIX1 — Merchant Evidence Intent Routing

Baseline `b0860a7a30e8c0b655d369dcc8309382a46734e3` (+ uncommitted NL4D1 and NL4D2), branch `feat/cp7-9-merchant-reliability`. Date 2026-11-10.

Not committed, not pushed. No evidence, approval, procurement or signing write. `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

## Root cause

| Layer | What happened to "Bước Partner Approval của Project Beta NL4C2B Step Acceptance còn thiếu gì trên database test?" |
|---|---|
| UserPromptSubmit → `intent_gate.run` | Passed the text unchanged to `IntentParser.parse`. |
| Intent model | Classified it as `operations: [diagnose]`, `domains: [data]`, read-only. |
| `IntentParser._reconcile_merchant_intent` → `_detect_local_merchant_operation` | Returned `None`. The local guardrail claims a request only when it has a Merchant word (`merchant`, `đối tác`, …) **or** the parser sees a Project **type** ("mở rạp", "cinema opening") **or** a Step **update**. An evidence question has none of these, so the model's roster stood. |
| Agent selection and envelope | `selected_agents = ["diagnostician"]`, with no "reconciled by local guardrail" reason. The NL4D2 read downgrade in the intent gate (keyed on the parser kind) was never reached, because the envelope had no Merchant operation. |
| `/solve` | Correctly stopped: a Merchant read with `merchant-manager` absent from `selected_agents`. |

**Contributing gaps in the NL4D2 parser:**
- **Step plus blocker wording.** "What blocks Step 8?" and "Bước 8 bị chặn vì sao?" have no evidence noun, so they were not evidence questions.
- **"Giấy tờ và phê duyệt."** The second-action check read "và … duyệt" as a second verb, so the question became MIXED.

## Exact fix

### `.claude/agents/tools/merchant/project_nl.py`

1. **Step-blocker wording is evidence.** A step named outside every Project or Merchant name (`names_a_step`), plus blocker wording (`bị chặn`, `vì sao`, `tại sao`, `why`, `blocks`/`blocked`, `còn thiếu`, `thiếu gì`, `missing`), is now an evidence question. The question shape is still required, and imperative writes and completion questions are still excluded.
2. **New nouns:** `requirement(s)` and `required`.
3. **Mixed requests.** An evidence question is MIXED only when a second action appears **outside the evidence nouns**. "giấy tờ và phê duyệt" stays one question; "…, rồi xóa Merchant …" becomes MIXED and is never downgraded to the read.

### `.claude/system/intent_parser.py`

1. `_detect_local_merchant_operation` now also claims an `EVIDENCE_STATUS` request, but only when `_names_merchant_evidence_context` finds Merchant context:
   - a named Project, Merchant or step; or
   - a phrase from `WORKFLOW_STEP_PHRASES`: every suffix of two or more words of a standard template step title ("partner approval", "legal review", "signing gate", "purchase order", …), built from `STANDARD_WORKFLOW_TEMPLATES`, the domain's own vocabulary.
2. **Precedence is unchanged.** The existing source-code diagnosis and development-wording exclusions (`.py`, `implementation`, `module`, `pytest`, …) still run first.
3. **The claimed operation** is `merchant_read`, because an evidence question never requests a write. The existing gate downgrade then makes the run `read_only` with no `--confirm`, and binds the test target from the user's words.

### What is unchanged

- No change to the gate, the policy gate, `/solve`, the instructions, `external_write` semantics, test-mode commands or any write path.
- The lead cannot override the roster: the guardrail fixes it before the envelope exists, and the policy gate denies a `diagnostician` dispatch for that run.

## RED/GREEN evidence

**New test:** `tests/merchant/test_nl4d2_fix1_evidence_routing.py`, 30 tests. It drives the **real `IntentParser`** fed the live model decision (`diagnose`/`data`), and the **real intent gate and policy gate**; it does not only test the text parser.

**RED** (`project_nl.py` = NL4D2 version, `intent_parser.py` = HEAD; then restored and checked with `cmp`):

| Suite | RED | GREEN |
|---|---|---|
| Routing tests | **17 failed**, 13 passed | **30 passed** |

**RED failures:**
- the exact live request at the gate;
- all 13 phrasings (Vietnamese and English);
- two routed-read checks;
- the dispatch test.

**The 13 that passed under RED** cover boundaries that already held:
- code questions stay code work;
- evidence writes are never downgraded;
- a mixed request is not a read;
- runtime stays disabled;
- a step-only question infers no Project.

**Accepted (routed to `merchant-manager` as `merchant_read`, `read_only`, no confirmation, whatever the model says):**
- "Bước Partner Approval của Project … còn thiếu gì (trên database test)?"
- "Project … còn thiếu giấy tờ (và phê duyệt) gì trên database test?"
- "Legal Review (của Project …) đang chờ điều kiện nào?"
- "Step 8 của Project … bị chặn vì sao?", "Bước 8 bị chặn vì sao?"
- "What is missing for Partner Approval (of project …)?"
- "Which approvals are still required for project …?"
- "What blocks Step 8 (of project … on the test database)?"

**The live request end to end:**
- selected agent `merchant-manager`, operation `merchant_read`, `read_only`;
- target `test`, `requires_confirmation: false`, no scope;
- the reason "reconciled by local guardrail" is present;
- no pending record;
- the policy gate denies `diagnostician` and allows `merchant-manager` with a `merchant_read` / `database_target: test` assignment.

**Routed reads infer nothing:**
- "What blocks Step 8 of project …" answers with step 8's domain gate (NOT_MET).
- "What blocks Step 8?" names no Project, so the read returns NEEDS_CLARIFICATION. No Project is inferred from the conversation.

## Security and negative tests

| Case | Result |
|---|---|
| "Diagnose the Step Preview parser.", "Find the bug in intent_gate.py.", "Why do merchant tests fail?", "Review the Project evidence implementation.", "What blocks the CI pipeline step for the evidence module?", "Why is step 3 of the pytest fixture setup blocked?" | stay code work; never `merchant-manager`, never a Merchant operation |
| "Which approvals are still required?" (no Merchant context) | not claimed; left to the model |
| Evidence writes ("Ghi nhận Partner đã duyệt …", "Approve the latest document …", "Upload tài liệu mới …") | never the evidence kind; never a `merchant_read` run; no scope |
| Mixed ("… còn thiếu giấy tờ gì, rồi xóa Merchant …") | MIXED; keeps the model's destructive risk; not a read |
| Write authority | `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; `TEST_MODE_COMMANDS = {merchant create, project create, step update}` (unchanged) |
| Diagnostician on Merchant data | the policy gate denies dispatching `diagnostician` for the routed run |

## Full regression

**Targeted suites, run one after another, all passed:**

| Suite | Passed |
|---|---|
| NL4D2-FIX1 routing | 30 |
| NL4D2 | 47 + 3 |
| Merchant intent routing | 27 |
| NL3 | 41 + 2 |
| NL3A | 34 + 1 |
| NL4A | 43 + 10 |
| NL4A FIX | 37 |
| NL4B | 44 + 8 |
| NL4B FIX1 / FIX2 / FIX2B | 19 / 37 / 43 |
| NL4C preview contract | 13 |
| NL4C1 | 60 + 8 |
| NL4C2A | 18 + 14 |
| NL4C2B FIX | 55 + 5 |
| NL4C2B approval concurrency | 6 |
| NL4C2B receipt | 3 |
| NL2 PostgreSQL | 11 |
| NL2F PostgreSQL | 3 |
| NL1 PostgreSQL | 3 |
| Execution claims / evidence / ledger / attempt evidence / atomic create / Project create (PostgreSQL) | 5 / 16 / 4 / 10 / 3 / 3 |

**Full pytest:** run alone against the test database: **4276 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests). That is NL4D2's 4246 plus 30 new tests, with no existing test changed.

**Other checks:**
- `python .claude/system_test.py`: ALL PASSED.
- Compile and import smoke (intent_parser, all hooks, all Merchant tools): OK. `intent_parser.py` also runs directly as a script (fallback import path).
- `git diff --check`: clean.
- No stray control characters in any `.claude/**/*.py`.

## Database integrity

**Hash.** `ba419be9d17a7a6719f1ca864ff5bdc1fe01848a7ad65a857e023715d028a319`, identical before and after every run.

**Execution evidence.** Claims are still 20 and ledger rows still 4, so nothing new was written. There are 0 `PYTEST%` Merchants.

**Pending confirmations.** None were created: the only pending files on disk date from 2026-11-04 and 2026-11-09.

**Accepted Projects.**
- The NL4C2B accepted step `98dc77cf-…` is still IN_PROGRESS v2.
- The NL2 and NL3 acceptance Projects are unchanged (included in the hash).

**Production.** No production access.

## Live retest instructions

1. **Session.** Start a **fresh** Claude Code session. `merchant-manager.md` changed in NL4D2, so any running merchant-manager is `STALE_DEFINITION`; this fix itself changed no agent definition.
2. **Ask.** Type:
   `/solve Bước Partner Approval của Project Beta NL4C2B Step Acceptance còn thiếu gì trên database test?`
3. **Expected envelope:**
   - `selected_agents: ["merchant-manager"]`, `operations: ["merchant_read"]`, `risk_level: read_only`;
   - `merchant_database_target: test`, `requires_confirmation: false`;
   - a reason "Merchant operational intent reconciled by local guardrail: merchant_read".
4. **Expected dispatch.** `merchant-manager` runs `project evidence --request "<your words>" --test-database` once. Its report carries the CLI result after `MERCHANT_EVIDENCE_STATUS_JSON:`.
5. **Expected answer:**
   - `focus_step` 5 "Record Partner approval", matched as `PARTIAL_UNIQUE`;
   - gate NOT_MET with `MISSING_DOCUMENT_REVISION`;
   - unmet direct dependency step 4;
   - PARTNER approval MISSING and REQUIRED by steps 5 and 8;
   - nothing recorded or changed, and no confirmation or command offered.
6. **Optional checks:**
   - `/solve What blocks Step 8 of project Beta NL4C2B Step Acceptance on the test database?` should answer with step 8's gate.
   - `/solve Project Beta NL4C2B Step Acceptance còn thiếu giấy tờ và phê duyệt gì trên database test?` should route the same way.

## GO/NO-GO

- **NL4D2-FIX1:** GO for your review.
- **Live retest (read-only) in a fresh session:** GO.
- **NL4D3 (evidence previews):** GO after the live retest passes and you accept NL4D2 with this fix.
- **Evidence, approval, procurement and signing writes:** NO-GO until the NL4D1 owner decisions.

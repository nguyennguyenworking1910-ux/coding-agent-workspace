# CP12H.NL4C2B-FIX — Live Step Resolution & Command Reliability

> **Final NL4C status (committed together as `feat(merchant): enable trusted test-only step updates`).**
> - **Execution:** Step Update runs **only on the test database** (`coding_agent_merchant_test`), only from the user's own `/solve Xác nhận cập nhật` of a verified preview. **Production (runtime) Direct EXECUTE is disabled in code** (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`).
> - **Automated regression:** the final full suite is in the NL4C commit summary.
> - **Live acceptance:** one user-confirmed Step Update (step 1 READY → IN_PROGRESS of Project `8dd4c68d-…`) returned EXECUTE_SUCCESS, and an **independent read-only PostgreSQL verification** found it EXECUTED_AND_VERIFIED (`cp12h_nl4c2b_live_acceptance.md`).
> - **`confirmation_available`:** `true` only for a READY test-database preview. It means the user may confirm; it never means a write is authorized. This supersedes any "always false" wording below.
> - **Known limitations:** see the "Remaining risks" section of each report.

Branch `feat/cp7-9-merchant-reliability`; last commit `578790c`, with NL4C1, NL4C2A and NL4C2B-PREP still uncommitted and preserved.
Not committed, not pushed. No live Step Update was run, and no new acceptance Project was created. `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

## 1. Confirmed root causes

### Defect 1: `step_reference = null` on the live Project

I traced the data flow layer by layer for both live requests.

| Layer | What arrived | Step present? |
|---|---|---|
| UserPromptSubmit → intent classifier → `/solve` envelope | `raw_request` exactly as typed | yes |
| Teammate → `agent_cli.py step preview --request "<words>"` (live transcript) | the user's words, verbatim; request 2 was finally sent single-quoted | yes |
| `project_nl.interpret_project_request` → `_Words.step_reference()` | references found: request 1 → `['1', 'Acceptance']`; request 2 → `['Draft or renew document', 'Acceptance']` | **lost here** |
| `step_preview` → resolver | `step_reference = None` → NEEDS_CLARIFICATION | — |

**Root cause:** `step_reference()` treats every `bước`/`step` token as the start of a step reference. The live Project is titled "Beta NL4C2B **Step** Acceptance". Its word "Step" produced a second reference, "Acceptance", and two references deliberately fail closed (as with "bước 1 và bước 2"). The Project and target status resolved correctly because they are extracted separately.

The same root cause had two more effects:
- **Wrong reference.** With no real step written ("Đánh dấu bước của Project … Step Acceptance là hoàn thành"), the old parser returned the reference **"Acceptance"**, taken from the Project title. The resolver never binds a partial name, so no wrong step could have been selected.
- **Word cap.** `_MARK_AS` capped the name at 8 words, so "Đánh dấu Draft or renew document của Project Beta NL4C2B Step Acceptance là …" (10 words) was not recognised as a Step Update at all.

**Related defect found by the new tests:**
- **What:** a step title containing the stop word "to" was cut short by the parser. "Send reviewed revision **to** Partner" (template step 4) became "Send reviewed revision".
- **Effect:** the resolver offered a partial match and never bound it, so the request failed closed. It still needed a fix.

### Defect 2: read-only commands rejected by the Bash policy

These are the two commands the live session's PreToolUse(Bash) hook denied:

```text
python .claude/agents/tools/merchant/agent_cli.py completeness check --command "project create" --argv-json "[\"project\",\"create\",…]"
python .claude/agents/tools/merchant/agent_cli.py step preview --request "Cập nhật bước \"Draft or renew document\" của …" --test-database
```

The single-quoted retries (`'…"Draft or renew document"…'`, `'["project",…]'`) were allowed.

**Root cause:** `policy_gate._shell_text_is_literal` rejected **any** backslash inside double quotes (`_DOUBLE_QUOTE_SPECIAL_CHARS` includes `\`). An escaped `\"` is valid and harmless. Both Bash and POSIX `shlex` (which the hook and the preview capture use to rebuild argv) read it as a literal `"`.

## 2. Exact changes

| File | Change |
|---|---|
| `.claude/agents/tools/merchant/project_nl.py` | 1. `step_reference()` skips step nouns that are part of a Project or Merchant name: the words after `project`/`projects`/`dự án`/`merchant(s)`, by the same `_introduces_name` and phrase rules that extract those names (`_entity_name_words`). It also skips those inside the step title already found. 2. `names_a_step()` replaces the raw "any step noun" check before the `đánh dấu X là …` fallback. 3. `_step_at` returns the end of its reference; `_phrase` is split into `_span` and `_phrase`, with unchanged output. 4. `_MARK_AS`: the 8-word cap is gone; the shortest name before a status connector plus a known status wins. |
| `.claude/agents/tools/merchant/step_preview.py` | `_written_title`: when a persisted step title of the resolved Project starts with the parsed name **and appears whole in the user's own words**, that exact stored title is the reference. If none matches, or several equally long titles match, the parsed name is kept unchanged and the resolver decides (fail closed). Digits are never touched. |
| `.claude/hooks/policy_gate.py` | `_shell_text_is_literal`: inside double quotes, only `\"` and `\\` are accepted; any other backslash is rejected. `$`, backtick, `!`, newlines, operators outside quotes and unterminated quotes stay rejected. The allowlist (interpreter, the two scripts, no flags, no environment assignments) is unchanged. |

**No other changes:**
- no change to the domain engine, resolver rules (UUID or exact name binds; partial or several names never bind), pending store, gates, Direct EXECUTE, claim, ledger or receipt;
- no change to `merchant-manager.md`, so the running teammate's definition fingerprint is unchanged.

## 3. RED/GREEN evidence

**New tests:**
- `tests/merchant/test_nl4c2b_fix_step_resolution.py`: 55 unit tests (parser, preview against stored steps, pending safety, quoting and injection).
- `tests/merchant/test_nl4c2b_fix_step_resolution_postgres.py`: 5 PostgreSQL tests on a throwaway "<short> NL4C2B Step Acceptance" Project.

**RED:** `project_nl.py` and `policy_gate.py` reset to HEAD, and `step_preview.py` without `_written_title`. Then restored and checked with `cmp`.

| | RED | GREEN |
|---|---|---|
| Unit (55) | **27 failed**, 28 passed | 55 passed |
| PostgreSQL (5) | — | 5 passed |

**RED failures:**
- every phrasing on a Project title containing "Step" (13);
- the live requests against stored steps (5);
- the Unicode Project and the similar-title Projects;
- the stop-word title;
- duplicate titles;
- the quoted-title capture;
- the parse of the live escaped commands, and their policy decision (2);
- "no step written" returning the guessed "Acceptance".

The 28 that passed under RED are the injection rejections and the fail-closed cases that already held.

**Phase 2 coverage:**
- **Accepted:**
  - both exact live requests; `bước 1`, `bước số 1`, `step 1`, `Step 01`, `step number 1`;
  - exact and lower/upper-case titles, quoted and unquoted titles, long titles (including one cut at "to"), a Vietnamese title, a title containing "Step";
  - a Unicode Project name with "Step"; similar Project titles ("… Step Acceptance" vs "… Step Acceptance Two"); the "Merchant …" suffix.
- **Fail closed:** two steps; missing step; invalid number 99; unknown title; partial name "review" (ambiguous, with candidates); duplicate stored titles; a Project prefix that matches 3 Projects.
- **Reads:** the status question stays PROJECT_STATUS.
- **Quoting:**
  - both live denied commands are now allowed and parse to the intended argv, identical to the single-quoted form;
  - `$(…)`, `\$`, backticks (bare and escaped), `${HOME}`, `!!`, `\n`, Windows `C:\…`, `;`, `&&`, `|`, `>`, unterminated quotes, a backslash outside quotes, a newline in single quotes, environment prefixes, interpreter flags and other scripts are all still denied by the real policy decision;
  - single-quoted Unicode with `$HOME` stays literal.

**Live Project, read-only:** both live phrasings were previewed against **the real** `Beta NL4C2B Step Acceptance` (`8dd4c68d-…`). Both returned `READY_FOR_CONFIRMATION`, bound to step `98dc77cf-39d2-5f3f-b3a3-9e8e762d39c7`, READY → IN_PROGRESS, `NOT_AUTHORIZED`. The database snapshot was identical before and after.

## 4. Full regression

**Targeted suites, run one after another:**

| Suite | Result |
|---|---|
| NL4C2B-FIX unit | 55 passed |
| NL4C2B-FIX PostgreSQL | 5 passed |
| NL4C2B approval concurrency (PostgreSQL) | 6 passed |
| NL4C2B receipt (PostgreSQL) | 3 passed |
| NL4C2A unit | 18 passed |
| NL4C2A PostgreSQL | 14 passed |
| NL4C1 unit | 60 passed |
| NL4C1 PostgreSQL | 8 passed |
| NL4B unit | 44 passed |
| NL4B PostgreSQL | 8 passed |
| NL4A unit | 43 passed |
| NL4A PostgreSQL | 10 passed |
| NL3 unit | 41 passed |
| NL3 PostgreSQL | 2 passed |
| NL3A unit | 34 passed |
| NL3A PostgreSQL | 1 passed |
| NL2 PostgreSQL | 11 passed |

**Full pytest:**
- Run alone against the test database: **4183 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests). That is NL4C2B-PREP's 4123 plus the 60 new tests.
- No existing test needed changing.

**Other checks:**
- `python .claude/system_test.py`: ALL PASSED.
- Compile (all hooks and all Merchant tools) and import smoke (intent_gate, merchant_direct_handoff, merchant_pending_confirmation, merchant_preview_delivery, team_result_hook, policy_gate, team_lifecycle): OK.
- `git diff --check`: clean.

## 5. Database integrity

- **New baseline.** The test-database hash is now `151f8ef5356098f547fceb96a24dcfee0174ef2fcbd314a101bcc2a4ab864f89`. The previous `1636f0cb…` differs by exactly your live acceptance Project create:
  - +1 Project, +22 steps and 22 dependencies, +1 event, +1 claim, +1 ledger row.
- **Unchanged since.** The hash was identical before and after every test run in this checkpoint.
- **Live acceptance Project:** step 1 is still READY v1, with 0 STEP events.
- **NL2/NL3 acceptance Projects and the other Projects:** unchanged (versions 1, 1 and 2).
- **No leftovers:** 0 `pytest:` claims or ledger rows, 0 ACTIVE claims, and 0 `PYTEST%` Merchants after the full run.

## 6. Security checks

| Check | Result |
|---|---|
| Preview read-only | snapshot equality (unit fake reader denies non-read APIs; PostgreSQL snapshot before and after) |
| Pending record only from verified READY evidence | an unresolved step (99) capture records nothing; the escaped quoted-title capture records exactly one, for the correct step and Project |
| No authority from an invalid or ambiguous step | `requested_operation` is None for every fail-closed case |
| Typed Step scope prohibited; target not substitutable; single use; version and basis re-check; claim, ledger and receipt unchanged | NL4C1, NL4C2A and NL4C2B-PREP suites pass unchanged |
| The new title extension cannot pick a step the user did not write | it needs a stored title of **this** Project that starts with the parsed name and appears whole in the request; equal-length ties keep the parsed name, and the resolver still binds only exact names |
| Bash allowlist not broadened | only `\"`/`\\` inside double quotes are newly accepted; the hook and the preview capture share `exact_merchant_manager_command`, so the validated argv equals the executed argv |
| `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; `TEST_MODE_COMMANDS` unchanged | verified |

## 7. Remaining risks

1. **Step noun at the start of a Project name.** If the name starts with a step noun ("Cập nhật bước 1 của Project Step Two Rollout"), the noun is not treated as introducing a name, so the request still fails closed (NEEDS_CLARIFICATION). It is never wrong.
2. **Title extension needs a prefix.** It applies only when the stored title starts with the parsed name. A title cut in its middle by some other parser rule still fails closed rather than resolving.
3. **Windows-style backslashes are still denied** inside double quotes (`"C:\path"`). The teammate's inputs never need them. Single quotes remain the literal form.
4. **Unchanged from earlier checkpoints:**
   - the same OS user is trusted;
   - raw SQL can bypass repositories (see the NL4C2B-PREP report);
   - the pending record is spent at confirmation.

## 8. Exact live retest procedure (NL4C2B)

1. **Session.** Use a fresh Claude Code session, or the current one if `/solve` shows merchant-manager as absent or `IDLE_REUSABLE` (this fix did not change `merchant-manager.md`). Stop if it shows `STALE_DEFINITION` or any other status.
2. **No other PostgreSQL work** on `coding_agent_merchant_test` during the test.
3. **Preview:**
   `/solve Cập nhật bước 1 của Project Beta NL4C2B Step Acceptance thành đang thực hiện trên database test`
   Expect `READY_FOR_CONFIRMATION`:
   - Project `8dd4c68d-76a9-571b-ad08-a864d7fcf7a5`, Merchant `NL2_LIVE_BETA`;
   - step 1 "Draft or renew document" (`98dc77cf-39d2-5f3f-b3a3-9e8e762d39c7`), READY → IN_PROGRESS, test database;
   - the lead offers `/solve Xác nhận cập nhật 98dc77cf`. Nothing has been updated.
4. **Check the exact target.** If anything differs, type `/solve Hủy cập nhật 98dc77cf` and stop.
5. **Confirm,** typed by you, once:
   `/solve Xác nhận cập nhật 98dc77cf`
   Expect a single attempt, `EXECUTE_SUCCESS`, and a receipt `RECONCILED`. Never retry an uncertain result.
6. **Verify independently.** Run the read-only script in `cp12h_nl4c2b_live_preparation.md` §6. Expected:
   - step 1 IN_PROGRESS v2;
   - exactly 1 `STEP_STARTED` event;
   - claims +1 COMPLETED, ledger +1;
   - `recover_step_update_receipts` returns 1 receipt;
   - everything else unchanged.

## 9. GO/NO-GO

- **NL4C2B-FIX:** GO for your review.
- **NL4C2B live Step Update (step 1 READY → IN_PROGRESS on the test database):** GO once you accept this fix, following §8. The write happens only when you type step 5 yourself.
- **Runtime/production Direct EXECUTE:** NO-GO (disabled in code).

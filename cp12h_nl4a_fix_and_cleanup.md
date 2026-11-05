# CP12H.NL4A-FIX — Live Bug Fixing & Controlled Code Cleanup

- **Branch:** `feat/cp7-9-merchant-reliability`
- **Committed baseline:** `1b56a0bdcff06e221d07042ff5dc255e6b78f550`
- **Date:** 2026-11-05
- **Status:** uncommitted, as required. Nothing was pushed, no live write was executed, and nothing from NL4B/C/D was started.

All pre-existing NL4A work is preserved. That covers `project_status.py`, the NL4A unit tests, CLI wiring, the delivery gate and `cp12h_nl4a_project_discovery_status.md`. This run's edits sit on top of it.

## 1. Confirmed live bugs and root causes

Live tests 1 and 4 passed. These are the two failures.

### Bug A (live test 2): "vào bước khác" extracted as the Merchant

**Request:**
> Các bước đang chờ của Project Beta NL3 Confirmation Test trên database test là gì? Bước nào đang bị phụ thuộc vào bước khác?

**Root cause:** It was not "vào". "phụ **thuộc** vào" folds to `phu thuoc vao`, and `thuoc` ("belongs to") is an owner anchor in `_Words.owner_phrase`. The phrase after it, `vào bước khác`, became `merchant_phrase`. Merchant resolution then failed, and the request never reached Project resolution. "vào" was never an anchor.

The same defect class existed for:
- "tùy thuộc vào" and "lệ thuộc", which mean "depends on";
- "của bước khác" ("of another step");
- "cho biết" ("tell me"), wherever `cho` is an anchor (the list and create paths).

### Bug B (live test 3): a list request classified as `PROJECT_STATUS`

**Request:**
> Liệt kê tất cả Project của Merchant Beta Cinemas trên database test và cho biết trạng thái từng Project

**Root cause:** `interpret_project_request` tested `has_project and _STATUS` before `_LIST`. "trạng thái" (status) is a field the user wants for each list item, but it outranked the list operation. The status path then had no Project phrase and asked "Which Project do you mean?".

### Found during the audit (confirmed and fixed)

| # | Issue | Evidence |
|---|---|---|
| C1 | A single **partial** title match with **no Merchant named** bound silently (`match_kind: CANDIDATE`). This contradicts the module contract, which allows only an exact title across Merchants. | `status("Project NL3 Confirmation đang ở bước nào?")` returned a full status on baseline. |
| C2 | `unmet_predecessors` came back in id order, not sequence order. | Live step 4 showed `[3, 2]`. RED reproduces `[3, 2]` when ids sort opposite to sequence. |
| C3 | A list request's Merchant came from anchor priority, not reading order. In "projects **for** Merchant Beta … status **of** each", `of` won and "each" became the Merchant. | RED in `test_collection_requests_are_lists…` |
| C4 | English verbs after a title were absorbed into it: "…Confirmation Test **depend** on other steps". | RED in `test_dependency_wording_is_never_a_merchant` |
| C5 | "List the steps of project X" was `UNKNOWN`. | Same result on baseline. |
| C6 | The live teammate summary said "steps 2–4 wait on step 1", but the data says 4 waits on 2 **and** 3. The structured output was correct; the prose summary was wrong. | Run `cd94de07` report |

### Suspected, not changed (see §8)

- A BLOCKED step with all predecessors complete appears in `waiting_steps` with an empty `unmet_predecessors`. The reason it is blocked is not surfaced.
- In status mode, the Merchant "not found" question still says "(A Project request never creates a Merchant.)". The wording is inherited from the shared preview resolver.

## 2. Call flow (as audited)

```
/solve request
 → intent_gate.py (UserPromptSubmit): model envelope; interpret_project_request() only
   DOWNGRADES an unscoped merchant_execute/read to merchant_read when kind ∈
   {PROJECT_CREATE, PROJECT_STATUS, PROJECT_LIST}; requests_test_database() → target
 → merchant-manager → agent_cli.py project status --request "<words>" [--test-database]
 → read_commands.project_status → project_status.build_project_status
     → project_nl.interpret_project_request      (intent: _classify; entities: _Words)
     → project_preview.resolve_merchant          (Merchant: catalog + role label)
     → _find_project                             (UUID | exact title | Merchant+entity resolver)
     → MerchantReadRepository.get_project_detail (steps, dependency rows, evidence)
     → dependencies.dependency_ready_step_ids / evaluate_dependency_readiness (domain rules)
 → MERCHANT_PROJECT_STATUS_JSON → merchant_preview_delivery (exact-object check) → lead
```

Classification has one owner, `project_nl._classify`. The gate reuses it and does not duplicate it. Because the gate can only reduce authority, a broader read classification can never create write authority.

## 3. Exact changes per module

### `.claude/agents/tools/merchant/project_nl.py`

- **Intent separated from extraction.** The new `_classify()` holds the whole precedence order. It runs writes first (STEP_UPDATE, MIXED, MERCHANT_CREATE, PROJECT_CREATE), then reads in this order:
  1. a **collection operation** (`_LIST_OPERATION`), unless a step question without a per-item word overrides it;
  2. `PROJECT_STATUS`;
  3. the weaker `_LIST` wording.
- **`_LIST_OPERATION`.**
  - Vietnamese "liệt kê" / "danh sách" plus the Project noun.
  - English "list" / "show (me) all" plus the **plural** "projects". This keeps "show me the status of project X" a status read.
  - "tất cả", "các", "những" or "all" plus the Project noun.
  - The words in between may not name a step (`_NOT_STEP`), so "liệt kê các bước của Project X" stays a status read.
- **`_PER_ITEM`.** "từng", "each", "every", "all", "tất cả", or "mỗi" before a Project noun. With one of these, a list plus a step question stays a list ("… và mỗi project đang ở bước nào").
- **Explicit contradiction handled safely.** "Liệt kê Project X đang ở bước nào?" is a status read of X. If no Project is named, the CLI asks; it never guesses.
- **Syntactic anchor context.** The new `_Words._introduces_name()` is shared by `phrase_after_word` and `owner_phrase`. An anchor does not introduce a name in these cases:
  - `thuoc` preceded by `phu`, `le` or `tuy`, or followed by `vao`;
  - `cho` followed by `biet`, `xem` or `hoi`;
  - any anchor followed by a step noun (`buoc`, `step`, `steps`).
- **List Merchant comes from reading order.** It uses `owner_phrase(("cua","of","for","cho","thuoc","under"))`, so the first owner in the sentence wins (C3).
- **Name terminators** `depend depends waiting waits blocked bi` added (C4).
- **`_STEP_QUESTION`** gains "list/show (me) (all) (the) steps" (C5).
- **Deduplication.** `_STEP_UPDATE` is now built from `_STEP_UPDATE_EXPLICIT`, so the explicit verbs live in one place. The list alternation that `_LIST_OPERATION` superseded was removed from `_LIST`.

### `.claude/agents/tools/merchant/project_status.py`

- With no Merchant named, a partial title match is always returned as candidates with "Did you mean: …?", and nothing is bound (C1). A unique partial title **within a named Merchant** still resolves, as before.
- `unmet_predecessors` is sorted by sequence (C2).
- The module docstring now records the partial-title rule.

### `.claude/agents/tools/merchant/project_preview.py`

- `_resolve_merchant` was renamed to `resolve_merchant`. `project_status` had been importing a private name across modules. The body and its two call sites are unchanged.

### Delivery instructions (`.claude/agents/merchant-manager.md`, `.claude/commands/solve.md`)

- One rule each, for C6: describe what a step waits on only from its own `unmet_predecessors`. Steps that share predecessors are parallel and are never collapsed into a range.

### Tests

- **New `tests/merchant/test_nl4a_fix.py`** (37 tests): both live requests, VN/EN variants, Merchant phrases, a preposition inside a Merchant name, cross-Merchant ambiguity, partial titles, list precedence, preserved status reads, write precedence, the intent gate staying read-only, and join ordering.
- **Rewritten `tests/merchant/test_nl4a_project_status_postgres.py`** (5 → 10 tests). See §5.
- **`tests/merchant/test_nl1_project_preview_postgres.py`**: `_delete_fixtures` gained a `prefix` parameter (default unchanged) so NL4A reuses it instead of copying it.

## 4. RED/GREEN evidence

**RED:** the new file run against the baseline modules. The baseline `project_nl.py` and `project_status.py` and HEAD's `project_preview.py` were swapped in temporarily, then restored and verified with `cmp`.

| Test group | Baseline |
|---|---|
| `test_live_2_exact_request…` | FAIL (`merchant_phrase == 'vào bước khác'`) |
| `test_dependency_wording_is_never_a_merchant` (5 of 6 variants) | FAIL |
| `test_real_merchant_phrases…[… of Beta Cinemas depend …]` | FAIL (C4) |
| `test_same_title_under_two_merchants…` | FAIL (Bug A stopped it before candidates) |
| `test_unique_partial_title_without_a_merchant…` | FAIL (C1: bound silently) |
| `test_live_3_exact_request…` | FAIL (`PROJECT_STATUS`) |
| `test_collection_requests…` (5 variants) | FAIL |
| `test_list_without_a_merchant_asks…` | FAIL |
| `test_status_word_in_a_list…` | FAIL |
| `test_parallel_join_lists…` | FAIL: `assert [3, 2] == [2, 3]`, matching the live ordering |

18 RED in total. The rest of the file passed on baseline as regression guards: Merchant phrases, single-status reads, write precedence, and the intent gate staying read-only.

**GREEN:** `test_nl4a_fix.py` **37 passed**. The NL1–NL4A, preview, intent and policy suites: **469 passed**.

**Real CLI subprocess**, test database, read-only:

- Live request 2 → `PROJECT_STATUS`, `merchant_phrase: null`, Project `ba5cc7ec…`, Merchant `NL2_LIVE_BETA` (`FROM_PROJECT`), waiting `(2,[1]) (3,[1]) (4,[2,3]) (5,[4])`.
- Live request 3 → `PROJECT_LIST`: `Beta Nguyễn Văn Cừ` PLANNED, `Beta NL3 Confirmation Test` PLANNED.

## 5. Workflow correctness (Phase 4) and test isolation (Phase 5)

The `OPENING_NEW_CINEMA_STANDARD` template was checked against stored rows on a Project freshly created by the real workflow repository (`test_fresh_project_graph_follows_the_stored_dependencies`):

| Check | Result |
|---|---|
| Step 1 READY, the only current step | ✔ |
| Steps 6–7 SKIPPED with `requires_procurement=false`, never waiting or completed | ✔ |
| Step 8 waits on 5 only (procurement edges 6→7→8 not present) | ✔ |
| 10 Purchase Order waits on 9; 11 Payment Request waits on 10 (both required) | ✔ |
| 2 and 3 parallel after 1; 4 joins them, listed `[2, 3]` | ✔ |
| Production (12) and UAT (15) both branch from 9 | ✔ |
| 22 joins `[11, 14, 21]` | ✔ |
| SKIPPED ≠ COMPLETED; PENDING is never in `current_steps`; `dependency_ready_steps` is empty | ✔ |
| Progress from stored rows: 1 and 2 COMPLETED, 3 IN_PROGRESS → completed `[1,2]`, current `[3]`, 4 waits on `[3]` | ✔ |

Readiness still comes only from `dependencies.py`. No second workflow engine was added in the NL layer.

**Isolation.** General PostgreSQL coverage no longer depends on the NL2/NL3 live Projects:

- The fixture creates two `PYTEST_NL4A_` Merchants with unique names and three Projects, including the same exact title under both Merchants for the ambiguity case.
- After every test it asserts a whole-table snapshot is unchanged, deletes the fixtures with NL1's helper, and asserts 0 `PYTEST_NL4A_` Merchants remain.
- It runs on a clean, provisioned database. Its unique names cannot collide with "Beta Cinemas".

**`TestLiveAcceptance`** holds the four exact live requests against the real Projects. It is read-only, asserts the snapshot is unchanged, and **skips** when those Projects are absent.

`test_nl3a_natural_language_postgres.py` was left as it is: it is already a live-acceptance check that skips when `NL2_LIVE_BETA` is absent and handles both the pre-create and post-create states. NL1 already has the disposable-fixture equivalent.

## 6. Code cleanup inventory

Each refactor is listed with the behaviour it preserves and the proof.

| Refactor | Behaviour preserved | Proof |
|---|---|---|
| `_classify()` extracted from `interpret_project_request` | Same order for every write kind; read precedence changed only as intended | NL1/NL2E/NL3/NL3A/NL4A parser suites unchanged and green; write-precedence tests |
| `_STEP_UPDATE` built from `_STEP_UPDATE_EXPLICIT` | Identical regex language (explicit verbs, plus "bước … đã xong") | `test_explicit_step_updates_are_still_step_updates`, NL3A step-update tests |
| `_introduces_name()` shared by both phrase finders | All prior anchors still work; the only new rejections are the listed collocations | Create, preview and status extraction suites green |
| `_resolve_merchant` → `resolve_merchant` | Same function, now a public name for its two users | NL1 preview and NL4A suites |
| `_delete_fixtures(..., prefix=CODE_PREFIX)` | NL1 behaviour unchanged (default prefix) | NL1 PostgreSQL 3/3 |
| Dead alternation removed from `_LIST` | Anything it caught is now caught earlier by `_LIST_OPERATION` or rejected as a step question | Full list suites |

Measured (AST):

| Function | Lines | Branch nodes |
|---|---|---|
| `interpret_project_request` before | 106 | 31 |
| `interpret_project_request` after | 90 | 20 |
| `_classify` (new) | 35 | 14 |

Classification can now be read in one place. Duplicated step-update verbs went from 2 copies to 1. `project_nl.py` grew from 435 to 501 lines, almost all of it documented patterns and the anchor-context table.

Out of scope and unchanged: the CLI commands, the JSON result contracts, UTF-8 handling, Direct EXECUTE, claims, ledger, pending confirmation, authorization, and every module outside the NL read path.

## 7. Full regression, security and database integrity

| Check | Result |
|---|---|
| Full pytest (04:06:51–04:13:32Z) | **3864 passed, 20 skipped, 1 xfailed, 97 subtests passed**, exit 0. That is the 3822 baseline plus 37 fix tests plus 5 net PostgreSQL tests. No test was skipped, xfailed or weakened. |
| `python .claude/system_test.py` | **80/80** |
| `git diff --check` | clean (only Git's CRLF notices on pre-existing files) |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` (`merchant_direct_handoff.py:63`) |
| Reads cannot authorize writes | `authorization: null` and `read_only: true` on every result; both live requests run through the gate as `merchant_read` / `read_only` with no `merchant_scope` |
| Explicit step updates still need confirmation | `test_explicit_step_update_still_needs_confirmation`; "Hoàn thành bước … của tất cả Project" stays `STEP_UPDATE` |
| Test/runtime isolation | `test_agent_cli_status_reads_test_only_when_asked`, `test_other_reads_still_cannot_reach_the_test_database`, policy target tests — green |
| Trusted confirmation flow | Unchanged code; NL3 conversational-confirmation suites green |
| **Test DB integrity** | sha256 over every `merchant_ops` table is `71d315c9…22a7` **before this run, after the PostgreSQL fixture tests, and after the full suite**. The live Projects, their 18 claims, 2 ledger rows and 7 events are untouched, and 0 `PYTEST%` Merchants remain. |
| Git hygiene | No credentials, `.env`, runtime state or generated files in the diff. `.env` was not read. |

## 8. Remaining risks

1. **The parser is still rule-based.** New phrasings can miss, as C4 and C5 did. Every miss so far fails safe: the CLI asks or returns candidates, and a read never gains write authority. There is still a ceiling on coverage of Vietnamese syntax.
2. **"nhung" is ambiguous.** It folds from both "những" (plural) and "nhưng" (but). A "nhưng … project" clause could be read as a list. That outcome is read-only and harmless.
3. **BLOCKED steps have no stated reason.** A BLOCKED step with all predecessors met appears waiting with empty `unmet_predecessors`. The output doesn't say why it is blocked. None exist in the current data.
4. **Unexplained skips.** The 20 skipped tests are pre-existing environment gates, the same count as the baseline. `TestLiveAcceptance` skips on a database without the accepted Projects, by design.

## 9. Four-command live retest

Run each as its own prompt, from an interactive, psmux-backed Claude Code session. All four are read-only, with no `--confirm`.

```
/solve Project Beta Nguyễn Văn Cừ của Merchant Beta Cinemas hiện tại đến bước nào trên database test?
/solve Các bước đang chờ của Project Beta NL3 Confirmation Test trên database test là gì? Bước nào đang bị phụ thuộc vào bước khác?
/solve Liệt kê tất cả Project của Merchant Beta Cinemas trên database test và cho biết trạng thái từng Project
/solve Những bước nào đã hoàn thành và còn vướng ở đâu trong Project Beta Nguyễn Văn Cừ trên database test?
```

**Expected results:**

1. `PROJECT_STATUS`, `30fffeaf…`, current step `[1]`.
2. `PROJECT_STATUS` with `merchant_phrase: null`, `ba5cc7ec…`, Merchant `NL2_LIVE_BETA` (`FROM_PROJECT`). Step 4 waits on `[2, 3]`. The summary must say "2 and 3 wait on 1; 4 waits on 2 and 3".
3. `PROJECT_LIST`: both Projects, each `PLANNED`.
4. `PROJECT_STATUS`, `30fffeaf…`: COMPLETED 0, current `[1]`, skipped `[6, 7]`.

**Afterwards:** recompute the database hash. It must still equal `71d315c9…22a7`.

**Executed 2026-11-05:** all four passed, and the hash was unchanged. Details are in `cp12h_nl4a_live_acceptance.md`.

## 10. GO / NO-GO

**GO for the NL4A final live retest (§9).** Final acceptance is conditional on all four commands returning the expected outcomes. Both live failures are fixed at the root cause with RED/GREEN proof, and the real-CLI subprocess already returns the expected results for requests 2 and 3. The full suite, `system_test.py` and the security checks are green, and the test database is byte-identical to its state before the run.

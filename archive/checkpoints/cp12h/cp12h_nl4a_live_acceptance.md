# CP12H.NL4A — Live Acceptance

- **Date:** 2026-11-05
- **Branch:** `feat/cp7-9-merchant-reliability`
- **Committed baseline:** `1b56a0b`
- **Environment:** real interactive Claude Code lead session with a psmux pane-backed `merchant-manager` teammate, on the Merchant **test** database.

Every fact below comes from this session's own records: the `INTENT_ENVELOPE_JSON` and `TEAM_STATE_SNAPSHOT_JSON` the hooks injected, the teammate's `SendMessage` reports, which carry the gate-verified `MERCHANT_PROJECT_STATUS_JSON`, and the lead's own read-only commands. Nothing was reconstructed.

## 1. First live run: before NL4A-FIX

| # | Run | Request | Outcome |
|---|---|---|---|
| 1 | `cd94de07-a19e-4862-b035-0471cbda94df` | Project Beta Nguyễn Văn Cừ của Merchant Beta Cinemas hiện tại đến bước nào trên database test? | **PASS**: `PROJECT_STATUS`, `30fffeaf…` |
| 2 | `fa636d9b-24a5-49fb-94ca-b083428d138c` | Các bước đang chờ của Project Beta NL3 Confirmation Test trên database test là gì? Bước nào đang bị phụ thuộc vào bước khác? | **FAIL**: `NEEDS_CLARIFICATION`, `merchant_phrase: "vào bước khác"` |
| 3 | `7095801f-ad61-4f8a-9f14-645dacdb2a41` | Liệt kê tất cả Project của Merchant Beta Cinemas trên database test và cho biết trạng thái từng Project | **FAIL**: `query.kind: PROJECT_STATUS`, so the CLI asked "Which Project do you mean?" |
| 4 | `abcc866f-aec6-4052-805c-ca8b5548f2f3` | Những bước nào đã hoàn thành và còn vướng ở đâu trong Project Beta Nguyễn Văn Cừ trên database test? | **PASS**: `PROJECT_STATUS`, `30fffeaf…` |

Neither failure was a security or data problem. Both were read-only results asking for clarification, with nothing bound or written.

The root causes were:
- **Request 2:** the "thuộc" in "phụ thuộc" was read as the owner anchor "belongs to".
- **Request 3:** the status keyword was checked before the list operation.

Both are fixed in `cp12h_nl4a_fix_and_cleanup.md`.

One presentation defect was also seen in run 1. The teammate's prose said "steps 2–4 wait on step 1", while the structured data said step 4 waits on 2 and 3. This is fixed through the delivery rules and the sorted `unmet_predecessors`.

## 2. Retest: after NL4A-FIX

Every envelope had the same fields:
- `task_class: small_task`
- `risk_level: read_only`
- `operations: ["merchant_read"]`
- `selected_agents: ["merchant-manager"]`
- `merchant_database_target: test`
- `requires_confirmation: false`
- limits of 1 member, 1 round, 10 tool calls and $1.00

There was no `--confirm` and no `merchant_scope`. Each time, the teammate was reused through `SendMessage` because its snapshot was `IDLE_REUSABLE`.

| # | Run / request | Expected | Actual | Result |
|---|---|---|---|---|
| 1 | `5313f22c-0642-4c9a-9268-8c8d284e2030` / `708c4891…` | `PROJECT_STATUS`, `30fffeaf…`, current `[1]` | `PROJECT_STATUS`; Merchant `NL2_LIVE_BETA` by `NAME`; Project `30fffeaf-e6b5-5119-b078-52c934e1821e` by `TITLE`; current `[1]` | **PASS** |
| 2 | `50ae31c6-747e-4fe9-8a37-2c166ddb03fd` / `864c49e8…` | `PROJECT_STATUS`, `merchant_phrase: null`, `ba5cc7ec…`, `FROM_PROJECT`, step 4 waits on `[2,3]` | `query.merchant_phrase: null`, `project_phrase: "Beta NL3 Confirmation Test"`; Project `ba5cc7ec-bd78-5582-84e2-46b16037444c` by `TITLE`; Merchant `NL2_LIVE_BETA` `FROM_PROJECT`; step 4 waits on `[2, 3]` | **PASS** |
| 3 | `855e6e77-34e1-4135-8758-fcd9dbc0d99f` / `732c6b03…` | `PROJECT_LIST`, both Projects, each `PLANNED` | `outcome: PROJECT_LIST`, `query.kind: PROJECT_LIST`, `status_filter: null`; `30fffeaf…` PLANNED and `ba5cc7ec…` PLANNED | **PASS** |
| 4 | `9a82894f-6b67-4882-90c7-b1c6aec395c2` / `e3cc05de…` | `PROJECT_STATUS`, `30fffeaf…`, COMPLETED 0, current `[1]`, skipped `[6,7]` | Exactly that; Merchant `FROM_PROJECT` | **PASS** |

Every status result carried `read_only: true` and `authorization: null`.

## 3. Verified step state and dependencies

Both Projects (`30fffeaf…` and `ba5cc7ec…`) returned the same state:

- **Project:** `OPENING_NEW_CINEMA` / `OPENING_NEW_CINEMA_STANDARD`, `requires_procurement: false`, status `PLANNED`, version 1.
- **Step counts:** total 22; PENDING 19, READY 1, IN_PROGRESS 0, BLOCKED 0, COMPLETED 0, SKIPPED 2, SUPERSEDED 0.
- **Current step:** 1 "Draft or renew document" (READY). `dependency_ready_steps` and `completed_steps` are empty.
- **Skipped:** steps 6 and 7 (procurement branch). Neither is completed or waiting.
- **Waiting steps** and their own `unmet_predecessors`, as returned:

  | Step | Waits on |
  |---|---|
  | 2, 3 | 1 |
  | 4 | 2, 3 |
  | 5 | 4 |
  | 8 | 5 |
  | 9 | 8 |
  | 10 | 9 |
  | 11 | 10 |
  | 12 | 9 |
  | 13 | 12 |
  | 14 | 13 |
  | 15 | 9 |
  | 16–21 | each waits on the step before it |
  | 22 | 11, 14, 21 |

  This matches the template: 2 and 3 run in parallel and 4 joins them; the payment, Production and UAT branches start in parallel after 9; 22 joins three branches. The procurement path 6→7→8 is absent because there is no procurement.

- **Open approval gates:** 5, 8, 21 and 22.
- **Evidence:** 0 document revisions, 0 approvals and 0 procurement records.

In retests 1, 2 and 4 the teammate's prose listed each step's predecessors separately, with no ranges. This is the delivery rule from NL4A-FIX.

## 4. Teammate lifecycle

Each retest ended with one `SendMessage` report from `merchant-manager`, followed by an idle notification with `idleReason: available` and `result: RESULT_DELIVERED`:

| Retest | Idle notification (UTC, 2026-11-05) |
|---|---|
| 1 | 04:56:47.527Z |
| 2 | 04:58:44.424Z |
| 3 | 05:00:31.424Z |
| 4 | 05:02:06.347Z |

The injected `TEAM_STATE_SNAPSHOT_JSON` reported `merchant-manager` as `IDLE_REUSABLE` at the start of retests 1–4. Retest 1's snapshot reflects the end of the pre-fix runs. No snapshot was taken after retest 4, because no later `/solve` ran; its terminal state is evidenced only by the `RESULT_DELIVERED` idle notification.

The teammate process was spawned before NL4A-FIX, so it was still running the old `merchant-manager.md`. The new delivery rule was therefore stated in each retest assignment. The CLI is a fresh subprocess per call, so every read used the fixed code.

## 5. Database snapshot comparison

The lead ran read-only checks with a scratch script (`db_hash.py`). The script computes the sha256 of the per-table `count` and `md5(string_agg(row))` across **every** `merchant_ops` base table, plus a count of `PYTEST%` Merchants.

| When | Hash |
|---|---|
| Before NL4A-FIX (baseline) | `71d315c99d0b5cdbfdb5588b07ee7f307736a308dc6e980f7f7885b87e0322a7` |
| After the PostgreSQL fixture tests | identical |
| After the full regression | identical |
| **After all four live retests** | `71d315c99d0b5cdbfdb5588b07ee7f307736a308dc6e980f7f7885b87e0322a7`, **identical** |

The baseline counts are 2 Merchants, 3 Projects, 70 steps, 70 dependencies, 7 events, 18 execution claims and 2 ledger rows, with 0 `PYTEST%` Merchants. The accepted NL2/NL3 Projects, their claims, ledger rows and events are unchanged. No live writes occurred.

## 6. Read-only Bash redirection denial (retest 4)

After retest 4, the lead's first database-hash command tried to write its output to a scratchpad file. The `PreToolUse:Bash` hook refused it:

> Blocked: this command redirects output into a file, but this run is read-only. Use a read-only command, or ask the user for a run that can write.

That is the correct behaviour: a `read_only` run blocks file writes, **including the lead's own**. The check was then re-run without a redirect, and the hash was compared in the console against the baseline value. No retry was attempted around the guard.

A practical consequence: the post-run snapshot can't be saved to a file during a read-only `/solve` run. Capture it in the console, or in a later non-`/solve` turn.

## 7. Remaining limitations

1. **The parser is rule-based.** Unfamiliar phrasings can still miss. Every miss observed so far failed safe, as a read-only clarification or a candidate list.
2. **"nhung" is ambiguous.** It folds from both "những" and "nhưng", so a "nhưng … project" clause may read as a list. The result is read-only.
3. **A BLOCKED step's reason isn't shown.** A BLOCKED step with all predecessors met would show as waiting with empty `unmet_predecessors`. None exist in the current data.
4. **No conversational memory.** A follow-up without a Project name asks which Project.
5. **A teammate summary misstated history.** In retest 2 it said the earlier failure happened "because the request had no Merchant phrase". The real cause was the "phụ thuộc" misparse. Only the prose was wrong; the gate-verified JSON was correct, and the lead corrected it in its summary.
6. **Live-retest scope.** The live retests covered only the `test` target. Runtime Direct EXECUTE stays disabled (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`), and NL4A grants no write authority on either target.

## 8. Decision

**GO: NL4A final acceptance.**

- All four live requests pass in the real psmux environment.
- Both original failures are fixed at the root cause, with RED/GREEN tests.
- Every result is read-only with no authorization, and the teammate delivered each result exactly once.
- The test database is byte-identical to its pre-checkpoint state.

**NO-GO for runtime writes**, which remain disabled and out of scope.

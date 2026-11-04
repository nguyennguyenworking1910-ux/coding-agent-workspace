# CP12H.NL2-RC1 — Intermittent PostgreSQL Test Failure Review

Date: 2026-11-04 · Branch `feat/cp7-9-merchant-reliability` · HEAD `204bcde`
Database: `coding_agent_merchant_test` as `merchant_test`.

## Verdict: unresolved, not reproduced, no code change

The single failure (1 failed / 16 passed) did not reproduce in **39 further focused runs**, and two full-suite runs also passed. Its traceback was lost, because the original command piped output through `grep -E "SKIP|XFAIL|passed|failed"`. Every candidate cause that could be tested deterministically was ruled out (§3). By the review rules, no fix was invented.

## 1. Checkpoint preservation

| Check | Before | After |
|---|---|---|
| HEAD | `204bcde6124837b7cb6099cebc513e12c6d742b0` | unchanged |
| Staged files | 66 | 66 (+ this report, see §6) |
| `sha256(git diff --cached --binary)` | `bba810c4348b1b2b2aa66b6f3a6effbdb3da84f276d4404b2be8b5fefba552e1` | identical |
| Unstaged / untracked | 0 | 0 (apart from this report before staging) |

Nothing was unstaged, reset, discarded, committed or pushed.

## 2. Tests executed

The three files from the original focused run (17 tests):

- `tests/merchant/test_nl1_project_preview_postgres.py` (3)
- `tests/merchant/test_nl2_project_create_postgres.py` (11)
- `tests/merchant/test_nl2f_execute_delivery_postgres.py` (3)

Every run was sequential and used `pytest -v -p no:cacheprovider --tb=long -rA`, with full stdout and stderr captured. No run was parallel. Logs are outside the repo in `C:\Users\nguyen.nguyen30\AppData\Local\Temp\claude\008e84bdc82d3955\659c42bb-1d31-4b69-b3fe-dee5d2f922ca\scratchpad\rc1\`.

### 2a. 20-iteration loop (`iter_01.log` … `iter_20.log`, `summary.tsv`)

| # | Start (UTC) | End (UTC) | Exit | Result |
|---|---|---|---|---|
| 01 | 07:42:28.415 | 07:43:09.135 | 0 | 17 passed (30.91s) |
| 02 | 07:43:11.086 | 07:43:38.009 | 0 | 17 passed (23.26s) |
| 03 | 07:43:40.340 | 07:44:09.316 | 0 | 17 passed (24.64s) |
| 04 | 07:44:11.095 | 07:44:36.422 | 0 | 17 passed (18.49s) |
| 05 | 07:44:39.410 | 07:45:08.588 | 0 | 17 passed (23.99s) |
| 06 | 07:45:11.055 | 07:45:30.457 | 0 | 17 passed (15.98s) |
| 07 | 07:45:32.042 | 07:45:51.885 | 0 | 17 passed (16.46s) |
| 08 | 07:45:54.039 | 07:46:16.863 | 0 | 17 passed (18.17s) |
| 09 | 07:46:18.442 | 07:46:37.461 | 0 | 17 passed (15.78s) |
| 10 | 07:46:39.767 | 07:47:04.196 | 0 | 17 passed (20.38s) |
| 11 | 07:47:06.183 | 07:47:30.580 | 0 | 17 passed (20.00s) |
| 12 | 07:47:32.512 | 07:47:55.721 | 0 | 17 passed (19.19s) |
| 13 | 07:47:57.903 | 07:48:18.504 | 0 | 17 passed (16.95s) |
| 14 | 07:48:20.120 | 07:48:38.767 | 0 | 17 passed (15.89s) |
| 15 | 07:48:40.263 | 07:48:57.359 | 0 | 17 passed (14.15s) |
| 16 | 07:48:58.900 | 07:49:16.904 | 0 | 17 passed (14.92s) |
| 17 | 07:49:18.844 | 07:49:41.720 | 0 | 17 passed (19.51s) |
| 18 | 07:49:43.369 | 07:50:05.818 | 0 | 17 passed (18.60s) |
| 19 | 07:50:07.495 | 07:50:38.165 | 0 | 17 passed (26.18s) |
| 20 | 07:50:40.703 | 07:51:10.694 | 0 | 17 passed (24.66s) |

No failed node IDs and no tracebacks.

### 2b. Reproducing the original condition: full suite, then focused runs immediately

The original failure happened in the first focused run right after a full suite. To recreate that, I ran:

- **Full suite** 07:52:05 to 07:59:38 UTC: exit 0, **3695 passed, 20 skipped, 1 xfailed, 97 subtests passed** (`full2.log`)
- Focused run A, 07:59:41 to 08:00:11: 17 passed
- Focused run B, 08:00:11 to 08:00:39: 17 passed
- Focused run C, 08:00:39 to 08:01:06: 17 passed

### 2c. Tracer run (`trace_run.log`)

One extra focused run used a `pytest` plugin that counts `os.replace` and `Path.replace` call sites under `.claude/`. It gave 17 passed and counted:
`runtime_state.py:300` ×81 and `team_lifecycle.py:357` ×89, both with Windows retry, plus `tmux_result_receipt.py:207` ×2, which has no retry.

### Totals since the failure

| Runs | Result |
|---|---|
| 13 runs in the previous session | all passed |
| 20 loop iterations | all passed |
| 3 runs after the full suite | all passed |
| 1 tracer run | passed |
| **Focused runs: 37 consecutive** | 0 failures |
| Full suites | 2 of 2 passed |

The observed failure rate is therefore 1 in 38 focused runs. This does **not** prove the defect is absent.

## 3. Root-cause analysis

| Candidate | Evidence | Status |
|---|---|---|
| **Fixture cleanup** | The DB snapshot (all `merchant_ops` tables plus a content hash of the live records) is byte-identical before the loop, after the loop, after the full suite and at the end. No `PYTEST_%` merchants and no `pytest:`-keyed claims or ledger rows remain. | Ruled out |
| **Shared DB state / ordering** | The order is fixed in every run. A focused run directly after the full suite (the original condition) passed three times, and the full suite leaves no rows behind. | Not reproduced |
| **Random fixture names** (`Nlbeta{uuid[:6]}`) | I fuzzed 20,000 names per request template through `interpret_project_request`: one output shape each. I fuzzed 20,000 per template through `_resolve_merchant` + `_title`, using the real test-DB catalog (`NL2_LIVE_BETA` "Beta Cinemas", `TEST_CLI_…`): always the correct merchant and the expected title. | Ruled out |
| **Transaction isolation / connection lifecycle / race / claim-ledger persistence** | The PostgreSQL server log (`docker logs coding-agent-rag-db`) shows **no error, lock timeout, deadlock or dropped connection** in the failing run's window (about 07:05–07:07 UTC, between the end of the first full suite at 07:04:43 and the next loop at 07:08). The only server errors that day fall inside full-suite windows. They appear identically in both full suites (auth failures, an unexpected EOF, two lock timeouts on `merchant_execution_claims`), so they are intentional negative tests. The failure was therefore a client-side assertion or exception, not a fault reported by the database. | No DB-side evidence |
| **Expiry / timing** | The relevant TTLs are an intent claim of 30 s, a runtime authorization of 60 s, and 10 s file locks. The whole 17-test run takes 14–31 s. | Unlikely |
| **Windows file locking** | Atomic state writes use `os.replace`. `runtime_state.replace_with_retry` and `team_lifecycle` retry `PermissionError` for about 1.3 s, and their comments record that a live denial from an indexer or antivirus once lasted about 150 ms. `tmux_result_receipt.py:207` has **no** retry and runs twice per focused run. The others without retry (`tmux_merchant_completeness`, `tmux_{merchant,project,step,document_revision}_resolution`) are not reached by these tests. | **Plausible, unconfirmed.** It's the only remaining class consistent with a client-side, one-off, Windows-only failure. |
| **Actual production behavior** | Every deterministic production path these tests exercise passed 37 times. | No evidence |

### Side finding (not the cause)

These tests reach `team_result_hook` → `clear_pending_merchant_resolution`. That creates and deletes a `.lock` file in the **real** `.claude/runtime/pending_{merchant,project}_resolutions/`, because the `isolated` fixture in `tests/merchant/test_direct_execute_end_to_end.py` does not redirect `CLAUDE_PENDING_*_RESOLUTION_DIR`. The file is keyed by the fixed test session id `cp12h3-lead`, so it cannot touch another session's files (the September files are unchanged) or the database. It is still an isolation gap. Fixing it is optional cleanup and outside this checkpoint.

## 4. Code changes

None. The cause was not confirmed, so no regression test or fix was written (Phase 5 condition). No test was skipped, xfailed or weakened.

If you want the Windows hypothesis tested, the smallest follow-up is to route `tmux_result_receipt.py:207` through the existing `runtime_state.replace_with_retry`. The same could later apply to the five other writers without retry. That change would harden the code, not fix a confirmed bug, and it would need its own RED test (inject `PermissionError` on the first `os.replace`).

## 5. Database reconciliation

The snapshot (`snapshot.py`, read-only session, `transaction_read_only = on`) covers:

- the Beta fixture and all merchants
- the live Project `30fffeaf-…`, its 22 steps, 22 dependencies and 1 event
- all claims and ledger rows
- the row count of every `merchant_ops` table

| Point | sha256 |
|---|---|
| Before testing | `a4a2fd398a4274ef6097b9d878d3e4c096034fee1d4289c93761e5770196a795` |
| After the 20 iterations | identical |
| After the full suite | identical |
| Final | identical |

- Identity: `coding_agent_merchant_test` / `merchant_test`.
- `NL2_LIVE_BETA` is still at version 1. The live Project is `PLANNED`, version 1, with 22 steps and 1 `PROJECT_CREATED` event.
- The live claim `merchant-scope:v1:275d6482…` is `COMPLETED`, generation 1, with 1 ledger row.
- The 16 historical claims are unchanged, all `COMPLETED`.
- Orphans: 0 `PYTEST_%` merchants, 0 `pytest:` claims, 0 `pytest:` ledger rows.
- Table counts: claims 17, ledger 1, merchants 2, projects 2, steps 48, events 6.

No manual cleanup was performed.

## 6. Staged inventory

The 66 files from the NL2 checkpoint are unchanged (checksum above), plus this report:

- `cp12h_nl2_rc1_intermitent_test_review.md`

Total: **67 staged files**.

## 7. Recommendation

**Conditional GO** for committing NL1–NL2H. The case for it:

- 37 consecutive focused passes and 2 full-suite passes
- database state verified byte-identical throughout
- no database-side error in the failure window
- every deterministic and randomness-driven cause tested and excluded

The open risk is a one-off client-side failure of unknown origin, most plausibly a transient Windows file-replace denial. Not committing would not reduce it, because it isn't in NL-specific logic that was shown faulty.

If you need certainty before committing, the alternative is **NO-GO pending the replace-retry hardening above** as a separate, test-first change. Reruns of the focused suite should keep full output (`--tb=long -rA`, unfiltered) so that any recurrence is captured.

Runtime Direct EXECUTE remains disabled (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`). No live `/solve` was run. Nothing was committed or pushed.

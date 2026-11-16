# CP12H.NL2A — Windows UTF-8 Hook Input Boundaries

Branch `feat/cp7-9-merchant-reliability`; committed baseline `204bcde`; NL1 and NL2 are uncommitted and preserved. Nothing is committed or pushed.

## 1. Root cause

Claude Code writes each hook's JSON event to the hook's stdin as **UTF-8 bytes**.
- **Input:** on this Windows machine a piped `sys.stdin` in Python 3.11 decodes with the ANSI code page. That is `cp1252`, with UTF-8 mode off; verified by `sys.stdin.encoding == 'cp1252'` and `sys.flags.utf8_mode == 0`.
- **Silent corruption:** cp1252 can decode almost any byte sequence, so the UTF-8 Vietnamese turned into mojibake without raising.

```text
typed:     Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm
envelope:  Xem trÆ°á»›c dá»± Ã¡n má»Ÿ ráº¡p Beta Nguyá»…n VÄƒn Cá»« trÃªn database test, khÃ´ng cáº§n mua sáº¯m
```

**Why the live run came out the way it did:**
- **Classification:** the corrupted text no longer contains `xem truoc`, so the deterministic guardrail never fired. Read-only routing came from the OpenAI model alone.
- **Display:** the hook's *output* was already UTF-8 (`configure_utf8_output`), so the model's Vietnamese reasons displayed correctly. That hid the fact that the *input* side was broken.
- **Stopping the run:** the `/solve` envelope-match rule caught the mismatch, so nothing was dispatched.

**Two further defects found in the audit:**
1. **Fail-open on undecodable bytes.** Every entry point did `try: json.load(sys.stdin) except (JSONDecodeError, ValueError): return 0`. `UnicodeDecodeError` is a `ValueError`, so undecodable input was silently accepted.
   - For the PreToolUse `policy_gate`, `return 0` with no output **allows the tool call**.
2. **Latent output crash.** `intent_envelope_bridge.py` (run by `/solve` through `!`) and `policy_gate.py` print `ensure_ascii=False` JSON to a cp1252 stdout.
   - The bridge survived the live run only because mojibake is cp1252-encodable.
   - With input fixed, real Vietnamese ("ư", "ạ", …) raises `UnicodeEncodeError`. This is proven by test, see §3.

## 2. Hook entry points audited

The registered hooks were taken from `.claude/settings.json`, plus the `/solve` `!` bridge.

| Entry point | Event(s) | stdin | Non-ASCII stdout/stderr | Before | Fix |
|---|---|---|---|---|---|
| `intent_gate.py` | UserPromptExpansion, UserPromptSubmit | raw UTF-8 bytes | yes (envelope) — already UTF-8 | **mojibake** `raw_request`; bad bytes ignored | strict UTF-8 read; undecodable → `decision: block`, no run state |
| `policy_gate.py` | PreToolUse `*` | raw UTF-8 bytes | yes (`ensure_ascii=False`) | bad bytes → **allow**; latent output crash | strict read; undecodable → `permissionDecision: deny`; UTF-8 stdout/stderr |
| `team_result_hook.py` → `team_result_dispatcher.py` | PostToolUse (SendMessage/Bash/PowerShell), TeammateIdle | raw UTF-8 bytes | stderr idle feedback | **Unicode execute-request args ≠ scope** (rejected at staging); bad bytes ignored | strict read; undecodable → exit 2, no state change (keeps an idle teammate working); UTF-8 stdout/stderr |
| `round_counter.py` | PostToolBatch | raw UTF-8 bytes | no | bad bytes ignored | strict read; undecodable → exit 2, stderr |
| `cleanup_state.py` | Stop, SessionEnd | raw UTF-8 bytes | no | bad bytes ignored | strict read; undecodable → keep all state, stderr, exit 0 (exit 2 would trap Stop) |
| `intent_envelope_bridge.py` | `/solve` `!` command (no stdin) | — | yes (envelope) | **crash** printing real Vietnamese | UTF-8 stdout/stderr |

**What I didn't change, and why:**
- **In-process callers.** These read the payload through tests and other code paths with already-decoded text (`StringIO` in the e2e harness). `read_hook_payload` uses `stream.buffer` when present, so those paths are unchanged.
- **File I/O.** All hook file reads and writes already pass `encoding="utf-8"`. The one exception is a Linux `/proc/<pid>/stat` read, which is ASCII.
- **Agent CLI subprocesses.** `agent_cli.py` and `cli.py` receive arguments through argv, which Windows passes as UTF-16 (`CommandLineToArgvW`). Their stdout is already forced to UTF-8. Out of scope; no change.

## 3. RED/GREEN subprocess tests

`tests/test_hook_utf8_boundaries.py` contains 11 tests.
- **How they run:** each starts a real `python` subprocess with `PYTHONIOENCODING=cp1252` and `PYTHONUTF8=0`, and writes raw UTF-8 bytes to its stdin.
- **What is stubbed:** only the non-I/O seams. These are the OpenAI call (a model decision with **no** Merchant routing, so routing must come from the deterministic guardrail) and the OS pane-server lookup.
- **What is real:** the hook `main()` functions, their stdin reads and their stdout writes. `intent_gate`, `policy_gate`, `round_counter`, `cleanup_state` and the bridge run as scripts, exactly as Claude Code runs them. `team_result_hook` runs its real `main()` in a subprocess.

| Test | RED (before fix) | GREEN |
|---|---|---|
| intent_gate exact request — Vietnamese | `raw_request` = `Xem trÆ°á»›c dá»± Ã¡n …` (the live mojibake) | exact; `merchant_read`, merchant-manager only, no confirmation, reason "local guardrail"; persisted `request` exact |
| intent_gate exact request — mixed VN/EN | `Nguyá»…n VÄƒn Cá»« trÃªn` | exact, same routing |
| intent_gate exact request — ASCII | passes | passes |
| intent_gate malformed UTF-8 | not blocked; an envelope was created | `decision: block`; no run state |
| envelope bridge prints exact request | `UnicodeEncodeError: 'charmap' codec can't encode characters` (verified by reverting only the bridge fix) | exact `raw_request` |
| policy_gate malformed UTF-8 | no deny (tool allowed) | `permissionDecision: deny` |
| policy_gate Unicode merchant-manager preview command | passes | passes (not denied) |
| team-result: Unicode Project title in a scoped execute request | no handoff: staging rejected the mojibake args | args equal the Unicode scope → `PREFLIGHT:RUNTIME_EXECUTION_DISABLED`; authority unspent |
| team-result malformed UTF-8 | exit 0 | exit 2; handoff state unchanged; authority unspent |
| round_counter malformed UTF-8 | exit 0 | exit 2 |
| cleanup_state malformed UTF-8 | silent | state kept, stderr names UTF-8, exit 0 |

RED: 9 failed, 2 passed. GREEN: 11 passed.

## 4. Changes made

- `.claude/hooks/runtime_state.py`:
  - `read_hook_payload()` decodes `sys.stdin.buffer` as **strict** UTF-8 (no replacement, no fallback), then `json.loads`.
  - `configure_utf8_output()` was moved here from `intent_gate`.
- `intent_gate.py`, `policy_gate.py`, `team_result_dispatcher.py`, `round_counter.py`, `cleanup_state.py`:
  - each reads through `read_hook_payload`;
  - each handles `UnicodeDecodeError` *before* the existing `(JSONDecodeError, ValueError)` clause, with the fail-closed action in §2.
- `policy_gate.py` and `team_result_hook.py` set UTF-8 output.
- `intent_envelope_bridge.py` reconfigures stdout and stderr to UTF-8 strict.
- **Not changed:** envelope comparison, scope/authorization, staging, execution and the JSON protocols. The only new behaviour is a refusal on undecodable input.

## 5. Full regression

- **Full suite:** `pytest -q` with the test DB up: **3511 passed, 0 failed, 20 skipped, 1 xfailed, 97 subtests passed (168 s)**. That is the NL2 count of 3500 plus exactly the 11 new tests.
- **Structural checks:** `system_test.py` passed 80/80.
- **`git diff --check`:** clean. The CRLF notices are on files that were already CRLF in the working copy.
- **Test DB:** the snapshot before and after the suite is identical (16 tables by md5; 16 historical claims). The Beta fixture is intact (2 Merchants: "Manual CLI Test", "Beta Cinemas").
- **Runtime:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; the production DB was never connected.

## 6. Live read-only acceptance — PASSED (2026-11-01)

The user typed the request in the psmux session, after the fix and without restarting:

```text
/solve Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm
```

This is real harness behaviour, kept separate from the automated results:

| Check | Evidence | Result |
|---|---|---|
| Exact Vietnamese survives the UserPromptSubmit boundary | The injected `INTENT_ENVELOPE_JSON` `raw_request` is `Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm`, byte-identical to the prompt. The previous run showed `Xem trÆ°á»›c …`. | PASS |
| Envelope matches the request; the `/solve` gate passes | the lead validated the envelope before reading files | PASS |
| Deterministic routing | reason `Merchant operational intent reconciled by local guardrail: merchant_read` (previously "by intent model"); `operations: [merchant_read]`, `risk_level: read_only`, `requires_confirmation: false`, `selected_agents: [merchant-manager]` | PASS |
| Exact text survives dispatch, PreToolUse and the teammate's shell | the teammate ran `python .claude/agents/tools/merchant/agent_cli.py project preview --request "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm" --test-database`; `policy_gate` allowed it; the interpretation echoed `merchant_phrase "Beta Nguyễn Văn Cừ"` | PASS |
| Teammate result delivered to the lead (PostToolUse SendMessage boundary) | the report reached the lead intact, including Vietnamese | PASS |
| Beta Cinemas resolves from the test DB | `database_target: test`; Merchant **Beta Cinemas**, `NL2_LIVE_BETA`, `6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f`, ACTIVE v1, match `CANDIDATE` on "Beta" | PASS |
| Preview content | `READY_FOR_CONFIRMATION`; `OPENING_NEW_CINEMA` / `OPENING_NEW_CINEMA_STANDARD` v1 (`a3cc7546-…`, installed); title "Beta Nguyễn Văn Cừ"; requires_procurement false; no missing fields, clarifications or conflicts; 22 initial steps (1 READY, 6–7 SKIPPED, the rest PENDING); `basis_hash` `49d1df1e…3d23`; argv identical to the NL2 pre-check | PASS |
| No write authorization issued | `requested_operation.status: NOT_AUTHORIZED`; `executable: false`; the run had no `merchant_scope`; the teammate sent no execute request. Team-state record for merchant-manager: no `direct_writes`, `direct_scope_execution`, receipt or no-write-terminal footprint, `authorized_operations: []` | PASS |
| No DB mutation | the read-only test-DB snapshot after the run is identical to the one taken after the full suite (16 tables md5; 16 claims; 2 Merchants; 1 Project) | PASS |

**Teammate's caution.** It noted the Merchant matched as a CANDIDATE on "Beta" rather than by exact name. The resolution is unique and deterministic. The user should still check the Merchant identity in the preview before confirming.

### 6.1 Live finding: dispatch lifecycle defect (not encoding)

After its report the teammate was stuck in a TeammateIdle loop. It received "Result delivery is still incomplete" more than 20 times, although both of its SendMessage deliveries had succeeded. Root cause, from the session transcript's hook record:

```text
2026-11-01T14:36:58Z  PreToolUse:Agent  hook_non_blocking_error  exit 1
policy_gate._…agent_dispatch → team_lifecycle.mark_teammate_running → locked_team_state
  → save_team_state → replace_with_retry → os.replace
PermissionError: [WinError 5] Access is denied:
  …\team_state\b9c98bf4-….json.82kfn6wy.tmp -> …\team_state\b9c98bf4-….json
```

The chain of events:
1. **Allocation, then crash.** `allocate_teammate` wrote a fresh `CREATED` record. `mark_teammate_running` then failed: the atomic replace of the team-state file was denied by Windows on all 5 retries (about 150 ms in total). This is the same transient-handle class as the known flaky atomic-save test.
2. **The crash allowed the dispatch.** The uncaught exception made `policy_gate` exit 1. Claude Code treats that as a **non-blocking** error, so the Agent call went ahead. The teammate ran without a run or task binding (`status CREATED`, `current_run_id null`).
3. **Stop cleared the run.** At the end of the lead's turn, Stop found no teammate owning the run, so it cleared the run state and envelope. This explains the missing files noted above.
4. **The report could not bind.** The teammate's report reached the lead, but with no current task no pending-result receipt could bind. TeammateIdle then finds an owner record with no run or task and returns `PENDING_RESULT_FEEDBACK` (exit 2) forever. There is no terminal exit for that state.

**Security reading:**
- **This run:** a read, so no write was possible.
- **A writing run:** the dispatch receipt (`_record_merchant_execute_dispatch`) runs after `mark_teammate_running`, so it would also have been skipped. The downstream handoff requires that receipt and the run binding, so it should refuse; this is believed, not yet verified by test.
- **Pre-existing fail-open:** **any exception in `policy_gate` currently allows the tool call.** That predates NL2A, and NL2A did not cause it; the `UnicodeDecodeError` path fixed here was one instance of it.

**Status:** fixed in CP12H.NL2B (`cp12h_nl2b_dispatch_fail_closed.md`), as the user approved after this run.

**Not fixed in NL2A (out of scope). Proposed:**
1. **`policy_gate.main`:** an unexpected exception → deny, i.e. fail closed.
2. **`replace_with_retry`:** a longer bounded retry for Windows sharing violations, and fix the test that records `os.replace` before it succeeds.
3. **TeammateIdle:** a `CREATED` record with no run or task must reach a terminal state once (report the dispatch failure), not loop.
4. **Regression tests** for each, including a writing dispatch whose binding fails.

## 7. Remaining encoding risks

1. **`PYTHONUTF8` / `PYTHONIOENCODING` in Claude Code's hook environment.** These are not controlled by this repo. The fix does not depend on them, because it reads raw bytes.
2. **Unknown stdin encoding.** If a future Claude Code sent stdin in another encoding, the strict decode would refuse it (fail closed), not mis-read it.
3. **`agent_cli.py` arguments** depend on Windows argv decoding. It is correct for `CreateProcessW` callers; through Git Bash the MSYS argv conversion has worked in all checks so far, but it was not exhaustively tested.
4. **Other Python entry points that read stdin** (`.claude/schedule.py`, `rag_search.py`) were out of scope; none receives hook JSON.
5. **Unicode lookalikes.** NFC vs NFD Vietnamese is not normalised at the boundary; it is preserved byte-exact. The interpreter folds both forms for matching, but scope equality is exact, so a user who pastes NFD text must confirm the same NFD text.

## 8. GO / NO-GO

- **UTF-8 boundary fix: GO.** Every encoding check in the live run passed.
- **Resume NL2 controlled test-database Project creation: NO-GO.**
  - **Reason:** the live run exposed the dispatch lifecycle defect in §6.1. A failed team-state write lets `policy_gate` crash open, and the teammate is then stranded in an idle loop.
  - **Condition to resume:** fix §6.1 items 1–4 and repeat the live read-only run.
- **Production:** unchanged, NO-GO.

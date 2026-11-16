# CP12H.NL2B — Dispatch Must Fail Closed When Lifecycle Binding Fails

Branch `feat/cp7-9-merchant-reliability`; baseline `204bcde` plus the uncommitted NL1, NL2 and NL2A work, all preserved. Nothing is committed or pushed. The user authorised this fix after the NL2A live run (option "Fix now as NL2B").

## 1. Live defect (2026-11-01, NL2A acceptance run)

The transcript's hook record for the lead's Agent dispatch:

```text
2026-11-01T14:36:58Z  PreToolUse:Agent  hook_non_blocking_error  exit 1
policy_gate → team_lifecycle.mark_teammate_running → locked_team_state → save_team_state
  → replace_with_retry → os.replace
PermissionError: [WinError 5] Access is denied: …team_state\b9c98bf4-….json.82kfn6wy.tmp -> …json
```

| Step | What happened |
|---|---|
| 1 | `allocate_teammate` wrote a fresh `CREATED` record. |
| 2 | `mark_teammate_running` could not save. Windows denied the atomic replace on all 5 retries (≈150 ms of backoff). |
| 3 | The uncaught exception made `policy_gate` exit 1. **Claude Code treats exit 1 as non-blocking, so the Agent call ran.** |
| 4 | The teammate ran unbound (`CREATED`, no run/task). The Stop hook saw no owner and cleared the run state and envelope. |
| 5 | The teammate's report reached the lead, but no task receipt could bind. TeammateIdle returned `PENDING_RESULT_FEEDBACK` (exit 2) for an owner with no run/task — 20+ times, with no terminal exit. |
| 6 | With the user's approval, the lead stopped the teammate (`TaskStop`). |

This run was a `merchant_read`, so no write was possible. The general flaw is that **any exception in `policy_gate` allowed the tool call**.

## 2. Changes

| File | Change |
|---|---|
| `.claude/hooks/policy_gate.py` | `main()` now wraps the gate (`_main`). Any unexpected exception prints a **deny** with the exception class name, writes the traceback to stderr, and exits 0. `mark_teammate_running` raising (`OSError`/lock `Timeout`) or returning False now **discards the unbound allocation** and denies. Without the discard, the role would stay `CREATED` and every later dispatch would be refused as BUSY. |
| `.claude/hooks/team_lifecycle.py` | `discard_unbound_teammate()` removes only a `CREATED` record with no run, task, authority, pane, report or write. The retry budget is now 10 attempts, ≈1.3 s of backoff. |
| `.claude/hooks/runtime_state.py` | Same retry budget for run-state saves. |
| `.claude/hooks/teammate_idle_orchestrator.py` | If the owner record has no run/task and is `CREATED`, the unused allocation is released once (`mark_teammate_idle_reusable`) and the hook exits 0. Every other no-run state keeps the existing feedback. |
| `.claude/hooks/team_result_hook.py` | Wires the release function into the idle dependencies. |
| `tests/test_team_result_dependency_type_precision.py` | Field count 91 → 92 (one new field, precisely typed). |
| `tests/test_team_lifecycle.py` | The atomic-save test now records `os.replace` only after it succeeds. This fixes the known flake from CP12H.5C. |
| `tests/test_nl2b_dispatch_fail_closed.py` (new) | 5 RED/GREEN tests. |

## 3. Tests

`tests/test_nl2b_dispatch_fail_closed.py` runs the dispatch cases through the **real `policy_gate` subprocess**. Only `replace_with_retry` is stubbed: the first replace succeeds and every later one is denied, as Windows did live.

| Test | RED (before) | GREEN |
|---|---|---|
| Read dispatch whose binding cannot be saved | exit 1, no output; the live traceback is reproduced exactly | `permissionDecision: deny`, exit 0 |
| Scoped **write** dispatch whose binding cannot be saved | exit 1, no output | deny; no `merchant_dispatch` receipt, `merchant_dispatch_spent` not set |
| `team_lifecycle.replace_with_retry` survives a denial lasting 7 attempts | `PermissionError` after 5 | succeeds; backoff budget ≥ 1 s |
| `runtime_state.replace_with_retry`, same case | `PermissionError` | succeeds |
| An unbound `CREATED` teammate at TeammateIdle | exit 2 (loop) | exit 0 twice, record `IDLE_REUSABLE`, no authority |

**Contention repro of the old flaky test** (300 runs with a thread holding the file):
- **Before:** 170 × `ValueError`, a test defect.
- **After:** 0 × `ValueError`.
- **Remaining failures:** 76 × `WinError 32` and 2 × `WinError 5`. The `WinError 32` cases are the repro harness's holder thread racing the test's own teardown, as established in CP12H.5C. The source of the two `WinError 5` cases was not isolated.
- **Production `save_team_state` under the same contention:** 200/200 correct.

## 4. Regression

- **Full suite:** **3516 passed, 0 failed, 20 skipped, 1 xfailed, 97 subtests passed (180 s)**. That is the NL2A count of 3511 plus exactly the 5 new tests.
- **Structural checks:** `system_test.py` passed 80/80.
- **`git diff --check`:** clean.
- **Test DB:** the snapshot before and after is identical (16 tables, 16 claims, 2 Merchants including the Beta fixture).
- **Runtime:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; production was not touched.

## 5. Open finding: the teammate ran in-process

`TaskStop` reported the stopped teammate as **`in_process_teammate`**. After the stop, the harness team config (`~/.claude/teams/session-b9c98bf4/config.json`) lists only `team-lead` (`backendType: in-process`, `tmuxPaneId: leader`), so the teammate's own backend can no longer be read there.

This conflicts with the `/solve` contract, which requires visible tmux/psmux panes and forbids in-process fallback, although the project settings set `teammateMode: tmux` and the session runs inside psmux (`TMUX` set).

- **Writes still fail closed.** They need a verified harness pane (`members[].tmuxPaneId` plus process ancestry), so an in-process teammate cannot pass the Direct EXECUTE pane gate.
- **Reads do not.** A read-only dispatch is not stopped by any check.
- **Needs the user:** did a merchant-manager pane appear? If not, the harness's backend choice needs checking before the confirmed write. A dispatch-time backend check could be added in a later checkpoint.

## 6. GO / NO-GO

- **NL2B fix: GO.**
- **Resume NL2 controlled test-database Project creation: NO-GO until** these two conditions are met:
  1. The live read-only `/solve` is repeated: the teammate binds (RUNNING with run/task), the report settles, the teammate returns to `IDLE_REUSABLE`, and there is no idle loop.
  2. The teammate backend (§5) is confirmed to be a tmux/psmux pane. Otherwise the write cannot pass the pane gate.
- **Production:** NO-GO.

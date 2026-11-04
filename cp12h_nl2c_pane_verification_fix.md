# CP12H.NL2C-FIX — TEAMMATE_BACKEND_UNVERIFIED

Branch `feat/cp7-9-merchant-reliability`; committed baseline `204bcde`. NL1–NL2C remain uncommitted and are preserved. Nothing is committed or pushed. No database write was run by this checkpoint. Runtime Direct EXECUTE is still disabled.

## 1. Exact root cause

**Category D: the pane identity lookup used evidence that psmux does not provide for teammate panes.** The teammate really did run in its own split pane of the lead's psmux server.

Claude Code 2.1.316 starts a tmux teammate in two steps:

1. `split-window -d -t <leader> -h -P -F '#{pane_id}' -- cat`
2. `set-option -p remain-on-exit failed`, then `respawn-pane -k -t %N -- <claude --agent-id <name>@<team> … --parent-session-id <lead-session> …>`

After `respawn-pane -k`, psmux 3.3.7 reports an **empty `#{pane_pid}` for that pane for its whole lifetime**. `pane_current_command` changes to the hostname, and `pane_pids` and `pane_start_command` are also empty.

`harness_team_identity._pane_pids` therefore drops the pane, because its pid is not a digit. `_os_teammate_pane` gets no candidates, `teammate_pane_identity` returns `None`, and `verify_spawned_teammate_backend` reports **`TEAMMATE_BACKEND_UNVERIFIED`**.

This happens on every real teammate spawn. It is deterministic, not a race.

The failed predicate is `matches = [pid for pid in _pane_pids("%12") if parent == lead_server …]` evaluating to `[]` (`harness_team_identity.py`, `_os_teammate_pane`).

The NL2C tests did not catch it because they stub `_pane_pids` / `_os_teammate_pane`. NL2C's live check only used the lead's own pane `%1`, which is not respawned and still reports a pid.

The same defect affected the teammate-side Direct EXECUTE identity (`verified_teammate_pane` → `own_pane_server`), which also relies on `_pane_pids`. A test-database `project create` staged from a real teammate pane would therefore also have failed closed.

## 2. Evidence from the failed live run (2026-11-02, session `556b81a8`)

| # | Item | Value | Source |
|---|---|---|---|
| 1 | Lead | `claude.exe` pid **26184** (`--teammate-mode tmux`), pane `%1` (pane_pid 20956 `powershell.exe`), server **25944** (`tmux.exe server -s 0`) | team config `leadProcess`, process table, `$TMUX=/tmp/psmux-25944/default`, `TMUX_PANE=%1` |
| 1 | Lead ancestry | 26184 claude → 20956 powershell → **25944 tmux (server)** → 28696 tmux → 27664 powershell → VS Code → explorer | process table |
| 2 | Teammate | separate CLI session `7682ebfc…` (`entrypoint: cli`, `isSidechain: false`, `agentName: merchant-manager`, `teamName: session-556b81a8`), SessionStart 07:45:43.55Z | teammate transcript |
| 2 | Teammate pane | **`%12`**, `is_splitpane: true`, `tmux_session_name: current` | Agent spawn result |
| 3 | Pane inventory now | `%1 20956` only; the teammate pane was torn down by `TaskStop` | `tmux list-panes -a` |
| 3 | Other servers | `29508 tmux.exe server -s __warm__` (child of 25944), pre-spawned shells only | process command lines |
| 4 | Spawn metadata | `status: teammate_spawned`, `tmux_pane_id: %12`, `is_splitpane: true`, `team_name: session-556b81a8` | lead transcript |
| 5 | Run/task binding | Policy gate bound the dispatch to `run-…` (RUNNING + task). The gate then detached it: final record `FAILED`, `failure_reason: TEAMMATE_BACKEND_UNVERIFIED`, `current_run_id/task_id: null` | `.claude/runtime/team_state/556b81a8….json` |
| 6 | Verification receipt | none (`harness_pane` never recorded) | same |
| 7 | Timing | Agent call 07:45:27.93Z → gate verdict 07:45:35.69Z → tool result 07:45:36.13Z → teammate SessionStart 07:45:43.55Z | transcripts, `last_transition_at` |

**Reproduction against the live server.** I ran the harness's exact split + respawn sequence with a sleep command and polled with the real lookup:

```text
split pane=%14 pid=29956
after respawn-pane -k:   list-panes → "%15||0|MDS-NGUYENNGUYE"   (pane_pid empty)
_pane_pids → []   _os_teammate_pane → None   for the full 20 s polled
respawned process: 29076 powershell.exe -NoLogo -Command "<cmd>", parent 25944
```

A plain `split-window` (no respawn) verified instantly (`%11` → `(25944, 26216)`), which isolates the cause to `respawn-pane`.

**Hypotheses ruled out**

| | Hypothesis | Verdict |
|---|---|---|
| A | Teammate not in a separate pane | Ruled out: `is_splitpane: true`, pane `%12`, separate CLI process |
| B | Pane belongs to a different psmux server | Ruled out: the respawned process's parent is the lead's server 25944 |
| C | Startup race | Ruled out: the wrapper exists as soon as `respawn-pane` returns (before the Agent tool returns), and `pane_pid` stays empty indefinitely |
| D | Wrong identity evidence | **Root cause**: `#{pane_pid}` is empty for respawned panes |
| E | Run/task binding missing | Ruled out: the record was RUNNING with run and task when checked; `UNBOUND_DISPATCH` was not reported |
| F | Stale or unloaded hook settings | Ruled out: the hook ran (it produced the block), and the process/session was started after registration |

## 3. Change

**`.claude/hooks/harness_team_identity.py`** (only production file changed)

- **New fallback, used only when psmux lists the pane with an empty `pane_pid`** (`_pane_pid_unreported`). The pane process is the **unique direct child of the server** whose OS command line contains both:
  - `--agent-id <agentId>`, exactly as recorded by the harness in `members[].agentId`;
  - `--parent-session-id <lead session>`.

  psmux wraps the respawn command as `powershell -NoLogo -Command "<cmd>"`, so that wrapper is what gets matched.
  - The command line is read from the OS with `NtQueryInformationProcess(ProcessCommandLineInformation)` on Windows and `/proc/<pid>/cmdline` elsewhere. It is never taken from a hook payload or the environment.
  - Flags are matched as whole tokens, with optional quotes. A prefix such as `…@session-xx` does not match `…@session-x`.
- **Lead side (`_os_teammate_pane`)**: fallback candidates must still have the lead's nearest server as their parent, must not be in the lead's own ancestry, and there must be exactly one.
- **Teammate side (`own_pane_server`, for Direct EXECUTE staging)**: the pane root is the hook process's nearest ancestor whose parent is a server. It must be that server's only matching child, and `_os_pane_server` still requires that server to be the lead's nearest server.
- **Unchanged.** When psmux reports a pid, the fallback is never consulted and the strict NL2C check alone decides. A harness record without a valid `agentId` disables the fallback.
- **Identity values.** `harness_member` now also returns `agentId`. The verified identity is still `{server, pane, pane_pid}`; for a respawned pane, `pane_pid` is the wrapper pid. Reuse therefore still requires that same process.

**No startup retry was added**, because the evidence rules out a race. A delay would only slow down rejections.

**Tests (stub signatures only).** Five OS-seam stubs (`lambda pane, lead_pid` / `lambda tmux_pane`) were widened with `*_` to accept the new identity arguments. No assertion changed.

- `tests/test_nl2c_teammate_backend.py`
- `tests/test_hook_utf8_boundaries.py`
- `tests/merchant/test_direct_execute_end_to_end.py`
- `tests/merchant/test_cp12h5b_identity_and_routing.py`

## 4. Tests — `tests/test_nl2c_fix_respawned_pane.py` (20)

Real hooks, lifecycle state, harness config and policy gate. Only the OS evidence is faked: process table, pane listing and command lines.

| Requirement | Test |
|---|---|
| Live failure: respawned pane, empty pid | spawn gate accepts, `harness_pane = {200, %12, 31}`, still RUNNING |
| Pane process not yet observable | `TEAMMATE_BACKEND_UNVERIFIED`, FAILED; process appearing later does **not** revive the task or allow reuse |
| Pane never appearing | pane not listed → None |
| Wrong psmux server | wrapper under the outer nesting server or another session's server → None |
| Lead pane as teammate pane | lead's pane root carrying the teammate's markers → None |
| Ambiguity / impersonation | two matching wrappers → None |
| Identity markers | other teammate, agent-id prefix, other lead session, marker under a different flag, unreadable command line → None |
| No silent widening | pid reported (here in another server) → fallback never consulted → None |
| Missing harness agentId | spawn rejected |
| Stale pane reuse | same wrapper → match; replaced by a new process with the same markers → no match |
| Teammate-side (write staging) | inside respawned pane → `"200:%12"`; non-matching wrapper → None; pane under a server other than the lead's → None |
| Hook crash | command-line reader raises → gate blocks (fail closed) |
| Real reader | reads this process's command line; nonexistent pid → None |

Existing NL2C tests still cover the missing trusted run binding (`UNBOUND_DISPATCH`, `UNTRACKED_TEAMMATE`), the missing verification receipt (a never-verified teammate cannot be reused), and generic hook errors.

**RED/GREEN**

- **RED.** Both fallback branches were disabled in place. **5 failed**: spawn acceptance, the "not revived" acceptance half, reuse, teammate-side acceptance, and the crash test, which needs the fallback to reach the reader. The 15 rejection tests passed either way, as they should.
- **GREEN.** After restoring the module: **20/20**.

**Live OS check (real code, no stubs, throwaway pane, then killed)**

```text
pane %19  pane_pids []  unreported True
right markers      → (25944, 30928)   0.52 s
other lead session → None
other agent id     → None
no agent id        → None
lead pane %1       → None
```

## 5. Regression

| Check | Result |
|---|---|
| Full pytest | **3557 passed, 0 failed**, 20 skipped, 1 xfailed, 97 subtests passed (227 s). That is NL2C's 3537 + 20 new. |
| `python .claude/system_test.py` | ALL TESTS PASSED |
| `git diff --check` | clean (only Git's autocrlf notices; the files have no CR) |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` (`merchant_direct_handoff.py:63`) |
| Database | This checkpoint ran no Merchant CLI and no write. The suite includes the existing test-database-backed tests, unchanged from NL2C. I did not take a fresh DB snapshot. |

## 6. Remaining failure modes

- **Binding is by command line for respawned panes, not by pane id.** psmux gives no OS-observable link between `%N` and its process after respawn. The fallback binds the harness-recorded agent id and lead session to a unique direct child of the lead's server.
  - A same-user process that runs `tmux respawn-pane`/`new-window` in the lead's server with the same markers could impersonate the teammate. If it runs alongside the real teammate, the duplicate is rejected.
  - This is the same threat class the module already accepts (same-user `send-keys` or a replaced `tmux` on PATH). merchant-manager's shell cannot do either.
- **Depends on psmux's wrapper behaviour** (`powershell -NoLogo -Command "<cmd>"` as a direct child of the server). If a future psmux wraps the command differently, the check fails closed. If psmux starts reporting `pane_pid` again, the strict check is used automatically.
- **Depends on the harness command format** (`--agent-id`, `--parent-session-id`, `members[].agentId`), as confirmed in the Claude Code 2.1.316 binary. A format change fails closed.
- **Unchanged from NL2C:** if the hook process cannot start at all, nothing enforces the backend for read results.

## 7. GO / NO-GO

- **Retry the live read-only `/solve`: GO.** No restart is needed, because only the code of an already-registered hook changed. Type it fresh, since the old envelope is spent:

  ```text
  /solve Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm
  ```

  Expected result:
  - no block from `teammate_backend_gate`;
  - team state `harness_pane.server = 25944` and `pane_pid` = the pane's wrapper process;
  - then the NL2C §5 checks 4–8.
- **Live acceptance: NOT claimed.** It holds only after that fresh, user-triggered run succeeds.
- **Test-database `project create`: NO-GO** until the read-only run passes and the user types the exact `--confirm --merchant-target test --merchant-scope [...]`. The teammate-side staging identity now uses the same fallback, but it has not been exercised live.
- **Production: NO-GO.** Runtime Direct EXECUTE remains disabled.

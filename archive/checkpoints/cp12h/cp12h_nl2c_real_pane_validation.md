# CP12H.NL2C — Verify Real psmux Teammate Execution

Branch `feat/cp7-9-merchant-reliability`; committed baseline `204bcde`. The NL1, NL2, NL2A and NL2B work is uncommitted and preserved. Nothing is committed or pushed. No database write was run.

## 1. Answer

**`in_process_teammate` is a harness label, not the execution mode.**

In the NL2A live run, merchant-manager ran in its own psmux split pane, `%17`:
- the harness spawn record for that dispatch says `tmux_pane_id: "%17"`, `is_splitpane: true`, `team_name: session-b9c98bf4`;
- `TaskStop` reported `task_type: in_process_teammate` because, in Claude Code 2.1.316, that is the lead's task-registry type for every teammate, pane-backed ones included.

The dispatch mode itself was correct. The real defect was that **nothing verified the backend for a read-only dispatch**:
- Only the Direct EXECUTE write path checked the pane (`verified_teammate_pane`).
- An in-process or unverified teammate could have run a read and delivered a result unchecked.

NL2C closes that gap.

## 2. Evidence

### 2.1 What `in_process_teammate` means (Claude Code 2.1.316 binary)

| Finding | Harness code (minified) |
|---|---|
| The **pane** spawn path (`createTeammatePaneInSwarmView`, `sendCommandToPane`, telemetry `swarm_pane_spawn`) registers the teammate in the lead's task registry as type `in_process_teammate`, passing `paneId`, `insideTmux` and `backendType: w.backend.type`. | `ne(n.taskRegistry,{…paneId:y,insideTmux:D,backendType:w.backend.type…})` → `{…type:"in_process_teammate"…}` |
| The kill for that task type tears down the OS pane (`killPane(paneId)`) when the backend is `tmux`/`iterm2`. | `lSn(e){return e==="tmux"\|\|e==="iterm2"}`, `osTeardown` |
| Before returning, the spawn writes `{tmuxPaneId, backendType}` into the team file. | `await Y(u,h,{tmuxPaneId:y,backendType:w.backend.type},…)` |
| A genuinely in-process spawn is a separate path that returns `is_splitpane: false`. | `Ee(...)` … `is_splitpane:!1` |
| In-process is selected only for a non-interactive session (`-p`), `teammateMode: "in-process"`, or `auto` after a pane-backend failure. With `teammateMode: "tmux"` the pane backend is used. | `Cun()` "isInProcessEnabled" |

### 2.2 NL2A live dispatch record (session transcript, 2026-11-01T14:37:02Z)

```text
status: teammate_spawned   name: merchant-manager   agent_type: merchant-manager
tmux_session_name: current  tmux_pane_id: %17      is_splitpane: true
team_name: session-b9c98bf4
TaskStop (14:53:31Z): task_type "in_process_teammate"   ← registry type, not backend
```

The harness team config of earlier sessions shows the same pattern for every `/solve` teammate: `backendType: tmux` with a real `%N` pane. Only `team-lead` is `in-process` / `leader`, which is how the harness records the lead.

### 2.3 Live topology now (read-only, 2026-11-02)

The current session was resumed at 13:53, so the lead has a new process. The teammate from 2026-11-01 was stopped, and no teammate pane exists now.

| Item | Value | Source |
|---|---|---|
| Lead `claude.exe` | pid **19484** | team config `leadProcess.pid`, process table |
| Lead pane | `%1`, pane_pid **20956** (`powershell.exe`) | `tmux display-message`, `list-panes` |
| Lead psmux server | pid **25944**, socket `psmux-25944`, session `0` | `$TMUX=/tmp/psmux-25944/default,…`, nearest server ancestor of 19484 |
| Server nesting | 28696 → **25944** → 29508 | process table (`tmux.exe`) |
| Lead ancestry | 19484 claude → 20956 powershell → 25944 tmux → 28696 tmux → 27664 powershell → VS Code → explorer | process table |
| Panes in the lead's server | only `%1` (the lead) | `tmux list-panes -a` |
| Team config members | `team-lead` (`in-process`, `leader`) only | `~/.claude/teams/session-b9c98bf4/config.json` |
| Teammate-pane check against the live system | lead's own pane `%1` → rejected; absent `%17` → rejected; `merchant-manager` → not verified (no member) | `_os_teammate_pane`, `teammate_pane_identity` |

Every pane id here is qualified by its server: psmux numbers panes from `%1` in each server.

## 3. Changes

| File | Change |
|---|---|
| `.claude/hooks/harness_team_identity.py` | **`teammate_pane_identity(owner, name)`** verifies a teammate pane **from the lead's side**. It requires all of: a harness member with `backendType: tmux` and a `%N` pane; exactly one pane with that id whose process is a child of the **lead's nearest psmux server**; and that pane is not the lead's own. It returns `{server, pane, pane_pid}`. The OS lookup is the seam `_os_teammate_pane`. The shared helper `_nearest_server` is also used by the existing `_os_pane_server`, whose behavior is unchanged. |
| `.claude/hooks/team_lifecycle.py` | **`verify_spawned_teammate_backend`**: the dispatch must already be bound (RUNNING with this run and a task), not reported as a non-split pane, verified, and matching the pane the harness reported. On success it records `harness_pane`. Otherwise the task ends **FAILED** (`UNBOUND_DISPATCH`, `NOT_A_SPLIT_PANE`, `TEAMMATE_BACKEND_UNVERIFIED`, `PANE_MISMATCH`). **`reused_teammate_pane_matches`**: true only if the live pane equals the recorded `{server, pane, pane_pid}`. |
| `.claude/hooks/teammate_backend_gate.py` (new) | The `PostToolUse(Agent\|Task)` hook. Inside a `/solve` run it calls the check above. On failure it blocks and tells the lead to stop the teammate with `TaskStop`, report, and not dispatch a replacement. It **fails closed**: unreadable input or any exception also blocks. Calls outside a `/solve` run are ignored. |
| `.claude/hooks/policy_gate.py` | The reuse path (lead `SendMessage` to an existing teammate) is denied unless `reused_teammate_pane_matches` holds. This covers a closed pane, a recycled pane id, and a teammate that was never verified. |
| `.claude/settings.json` | Registers the new hook (`PostToolUse`, matcher `Agent\|Task`). |
| `CLAUDE.md`, `.claude/commands/solve.md`, `.claude/documents/ARCHITECTURE.md` | Document the post-spawn check, the lead's action on a block, and that `in_process_teammate` is a registry label. |

**Existing pane identity requirements are not weakened.**
- `verified_teammate_pane`, the Direct EXECUTE binding, `direct_pane_identity_status` and all write gates are unchanged.
- The new checks are additional.
- The verified identity grants no authority.

## 4. Tests

### 4.1 New: `tests/test_nl2c_teammate_backend.py` (21 tests)

These tests use the real policy gate, lifecycle state, harness config and hook entry points. Only the OS pane lookup is replaced. The wrong-server cases run the real lookup against a fake process table.

| Requirement | Tests |
|---|---|
| Valid separate-pane teammate | accepted; `harness_pane = {server, pane, pane_pid}` recorded; still RUNNING with `merchant_read` |
| In-process teammate rejected | `backendType: in-process` with `is_splitpane: false` → `NOT_A_SPLIT_PANE`; without that flag → `TEAMMATE_BACKEND_UNVERIFIED`. The task ends FAILED with authority detached; 3 idle events return `(0, "")` with no loop; it cannot be reused |
| Forged pane metadata | `TMUX_PANE=%7` in the environment but no such pane under the lead's server → rejected; tool-response pane `%9` ≠ harness `%7` → `PANE_MISMATCH`; another lead's harness record → rejected |
| Wrong psmux server | in the real `_os_teammate_pane`: a pane under the outer (nesting) server → rejected; another server → rejected; the same `%N` in two servers → only the lead's server counts; two candidates in one server → rejected; the lead's own pane → rejected; lead outside any server → rejected |
| Stale pane reuse | pane closed → reuse denied; pane id recycled (new `pane_pid`) → reuse denied; teammate never verified at spawn → reuse denied. Each denial leaves the record IDLE_REUSABLE |
| Dispatch without trusted run binding | unbound CREATED allocation → `UNBOUND_DISPATCH`, FAILED; no lifecycle record → `UNTRACKED_TEAMMATE`; `/solve` not active → ignored; a check error → blocks (fail closed) |
| Return to IDLE_REUSABLE | verified spawn → report → idle → IDLE_REUSABLE with `harness_pane` kept; a second idle event is quiet; a new run reuses the same pane → RUNNING |

**RED/GREEN.** The new logic was neutralized: the spawn check returned "verified" without checking (the pre-NL2C behavior, with no hook), and the reuse pane check was removed.
- **RED:** 12 tests failed, every acceptance, rejection, binding and reuse test.
- **Passing even in RED (9):** they exercise the new OS lookup directly, the "not in a `/solve` run" case, and the fail-closed error path.
- **GREEN after restore:** 21/21.

### 4.2 Existing tests updated, because a reused teammate must now have been verified at spawn

| File | Update |
|---|---|
| `tests/merchant/test_direct_execute_end_to_end.py` | `dispatch()` now runs the real spawn check after an allowed Agent call, the way the harness runs PostToolUse. The autouse fixture stubs `_os_teammate_pane` as it already stubbed `_os_pane_server`. |
| `tests/test_teammate_reuse_dispatch.py` (2), `tests/test_policy_gate.py` (1) | Verify the spawn through the new helper `tests/teammate_pane.py`. |
| `tests/test_hook_utf8_boundaries.py` | The `scoped_lead` fixture stubs the same OS seam. |

Before these updates, 5 reuse tests and 1 UTF-8 test failed, because their teammate had never been verified. No assertion was relaxed.

### 4.3 Regression

- **Full suite:** **3537 passed, 0 failed, 20 skipped, 1 xfailed, 97 subtests passed (240 s)**. That is the NL2B count of 3516 plus exactly the 21 new tests.

- **Structural checks:** `system_test.py` passed.
- **`git diff --check`:** clean.
- **Runtime:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; production was not touched.
- **Test DB** (`coding_agent_merchant_test` / `merchant_test`): the snapshot after the full suite is identical to the one after NL2B (claims, candidates, ledger references, all 16 tables). The Beta Cinemas fixture is intact and has no Projects, claims or ledger rows.

## 5. Live read-only acceptance

**PENDING: the user must restart Claude Code in the psmux pane, then type the request.**

The restart is required because `settings.json` gained a new hook registration. Edits to existing hooks apply immediately, since each hook runs as a new process, but a new hook entry needs the settings to be reloaded. Resuming the same session (`claude --continue`) is fine.

```text
/solve Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm
```

Checks, in order. Stop at the first failure.

| # | Condition | Evidence |
|---|---|---|
| 1 | Exact UTF-8 `raw_request` | Envelope `raw_request` equals the typed text; reason "reconciled by local guardrail: merchant_read" |
| 2 | `merchant_read` routing | `selected_agents: ["merchant-manager"]`, no confirmation |
| 3 | Separate verified psmux pane | Spawn result `is_splitpane: true`; team config member `backendType: tmux`, `tmuxPaneId %N`; team state `harness_pane.server` = lead's server; no block from `teammate_backend_gate`; a new pane visible next to the lead |
| 4 | Persisted run/task binding | team state RUNNING, `current_run_id`/`current_task_id` set, `authorized_operations: ["merchant_read"]` |
| 5 | Correct Project preview | `project preview --test-database` → `READY_FOR_CONFIRMATION`, Beta Cinemas, 22 steps, procurement excluded |
| 6 | Terminal result delivered | The teammate's `SendMessage` is accepted |
| 7 | IDLE_REUSABLE without resend loop | No repeated "Result delivery is still incomplete" |
| 8 | No DB mutation | Snapshot identical |

## 6. GO / NO-GO

- **NL2C code: GO.** In-process or unverified teammates are now rejected for `/solve`, and the reuse check catches a stale pane.
- **Controlled NL2 test-database Project creation: NO-GO until §5 passes live.** Once it passes, the remaining gate is the user's explicit, exact `/solve --confirm --merchant-target test --merchant-scope [...]` for the previewed `project create`.
- **Production:** NO-GO. Runtime Direct EXECUTE remains disabled.

## 7. Residual risk

- **If the hook process cannot start at all, nothing enforces the backend.** In that case Claude Code reports a non-blocking error and the teammate stays RUNNING but unverified. Its read result would still be accepted, as before NL2C.
  - Writes are unaffected: they still need `verified_teammate_pane` at staging.
  - Reuse is also blocked, because the teammate was never verified.
  - Gating read-result acceptance on `harness_pane` would close this. It touches the result-delivery path and its tests, so it is left for a later checkpoint.
- **The identity is process-tree based, not cryptographic.** This is the same threat model as `harness_team_identity`.

# CP12H.5A — Live psmux Runtime Validation

- Date: 2026-10-30
- Branch: `feat/cp7-9-merchant-reliability`, baseline `84d28d2` (working tree clean before the run)
- Verdict: **NO-GO** for runtime Direct EXECUTE

Phase 1 completed. Phase 2 ran live and **failed** two of its four required properties. Phase 3
was **not run**, as the checkpoint rule requires ("only after Phase 2 passes"). It is also
independently blocked by defect D1 (below). No Merchant database mutation was performed. No
commit or push.

## 1. Actual psmux behavior and pane identity evidence

| Item | Observed |
|---|---|
| Executable | `psmux.exe` and `tmux.exe` shim, WinGet package `marlocarlo.psmux` |
| Version | `psmux 3.3.7 (05cc5d4 2026-07-20)`, reports itself as `tmux 3.3.7` |
| Configuration | none (`~/.tmux.conf`, `~/.config/psmux` absent); state in `~/.psmux/` |
| Lead session | psmux session `0`, `TMUX=/tmp/psmux-6316/default,50675,0`, `TMUX_PANE=%1` |
| Project settings | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, `teammateMode: tmux` |
| Shell | lead tool shell is Windows PowerShell 5.1; panes start `powershell` |

**`TMUX_PANE` is provided** inside pane processes and their children, and equals `#{pane_id}`.
This was verified for the lead pane and for every pane of a controlled detached session
`cp12h5a`. Each driver process logged `TMUX_PANE` from its own environment, and the driver never
sets it.

**Trusted harness record.** `~/.claude/teams/session-d904fc16/config.json` (this session)
records the lead as `name: team-lead`, `backendType: in-process`, `tmuxPaneId: "leader"`.
Teammate entries (`backendType: tmux`, `tmuxPaneId: %N`) appear only when the harness spawns a
teammate. `harness_team_identity.harness_member_pane` accepts a member only if:

- `agentType == name`;
- `backendType == "tmux"`; and
- `tmuxPaneId` matches `%\d+`.

`verified_teammate_pane` then compares that id with the hook process's `TMUX_PANE`.

**New finding: pane ids are per-server, and psmux runs one server per session.** The detached
session `cp12h5a` started its own server (`TMUX=/tmp/psmux-29232/default,...`) and numbered its
panes `%1 %2 %3`. That duplicates the lead's `%1` in server `psmux-6316`. `tmux list-panes -a`
showed `0 %1 30584` and `cp12h5a %1 3796`. Because the identity check compares only the pane-id
string, a process in a *different* psmux session can pass as the teammate's pane (trace p2f#4,
defect D4).

**Limitation.** No harness-authored teammate entry was observed in this session. Dispatching a
teammate requires a user-typed `/solve` with a valid envelope. This validation was not invoked
through `/solve`, and the lead does not dispatch outside it. Phase 2 therefore used a
harness-shaped `config.json` written with the real psmux pane id
(`tests/merchant/test_direct_execute_end_to_end.write_harness_team`). It also used the real
policy-gate dispatch of an intent envelope, applied through `policy_gate.apply_call` from the
lead shell. Every teammate-side hook (`team_result_hook.main` for `SendMessage`/`TeammateIdle`,
plus pane binding) ran as a separate process inside a real psmux pane.

## 2. End-to-end execution trace

Driver: `live_driver.py`. Orchestrator: `run_phase2.sh` (both in the session scratchpad). The
orchestrator sends each step to a pane with `tmux send-keys` and waits for the step's trace line.
State was isolated per scenario through `CLAUDE_*_STATE_DIR` and `CLAUDE_HARNESS_TEAMS_DIR`. The
Merchant repository was restricted to role `test`. Scoped non-Create writes went to an in-memory
fake handler (no DB).

### p2f — identity, foreign rejection, conflict bound (harness pane `%1` in `cp12h5a`)

| # | Pane | Step | Result | Pass? |
|---|---|---|---|---|
| 2 | cp12h5a `%1` | whoami | verified `%1` | ✅ |
| 3 | cp12h5a `%2` | whoami | verified `None` | ✅ |
| 4 | **session 0 `%1`** (lead) | whoami | verified **`%1`** — foreign server accepted | ❌ D4 |
| 5 | `%2` | execute request | rejected `PANE_IDENTITY_UNVERIFIED`, nothing spent | ✅ |
| 6–8 | `%2` | idle ×3, task unbound | `rc=2` "Your result was not delivered…" each time | ❌ D3 |
| 9 | `%1` | bind `mm-sess` | `BOUND` | ✅ |
| 10–11 | `%2` | idle ×2, task bound | ignored, rc 0, no state change | ✅ |
| 12–14 | `%1` | idle ×3, new session id | `FAILED PANE_BINDING_CONFLICT` once, then stable rc 0 | ✅ bounded |
| 15 | `%1` | execute after conflict | rejected, nothing spent | ✅ |

### p2g — successful scoped write, release, stale pane after reuse

| # | Pane | Step | Result | Pass? |
|---|---|---|---|---|
| 2 | `%1` | execute (fake project update) | succeeded, authority spent, 1 handler call | ✅ |
| 3–4 | `%1` | `TEAM_RESULT_JSON` SUCCEEDED + idle | `IDLE_REUSABLE` | ✅ |
| 5 | `%1` | repeated idle | still 1 handler call | ✅ no duplicate |
| 6 | lead | new `/solve` run, reuse | Agent denied (reuse via SendMessage), SendMessage allowed; task `de556783…` RUNNING | ✅ |
| 7–8 | lead / `%3` | harness now records `%3` | `%3` verifies | ✅ |
| 9 | stale `%1` | execute on new task | rejected `PANE_IDENTITY_UNVERIFIED` | ✅ |
| 10–11 | **stale `%1`** | `TEAM_RESULT_JSON` FAILED + idle | **new task settled, teammate `IDLE_REUSABLE`** | ❌ D2 |
| 13 | real `%3` | execute on its task | rejected "no unique active lead session owns merchant-manager" | ❌ consequence |

After step 11 the record still carries the previous task's binding
(`trusted_pane_task_id = 3422eee1…`, `trusted_tmux_pane_id = %1`). `current_task_id` is
cleared, so the stale pane's forged result became the new task's outcome. No authority was spent
and nothing was written. The failure is result forgery plus denial of service, not an
unauthorized write.

An earlier run of the same scenario today (session `b9c98bf4`, trace p2b) settled the new task
`FAILED` instead, because its report shape was rejected. Either way the stale pane, not the
assigned pane, decided the task.

### Phase 2 requirements

| Requirement | Result |
|---|---|
| Actual teammate pane matches trusted record | ✅ same server; ⚠ no harness-authored teammate record observed |
| Foreign panes rejected | ❌ same-server foreign panes rejected; **cross-server pane with same id accepted** (D4) |
| Stale panes cannot reuse a previous task identity | ❌ stale pane settles the new, still-unbound task (D2) |
| Binding conflict cannot loop | ✅ terminal `PANE_BINDING_CONFLICT`, bounded; ⚠ unbound task returns `rc=2` feedback on every idle (D3) |

## 3. Database target confirmation

- `RepositoryConfig.from_env("test")` resolves to `coding_agent_merchant_test` / `merchant_test`.
  A live read-only query returned
  `current_database=coding_agent_merchant_test, current_user=merchant_test, port 5432`.
- `from_env("app")` resolves to `coding_agent_merchant` / `merchant_app` (runtime). The driver
  refused every non-`test` repository role. No runtime connection was opened.
- The test database was read only. `merchant_ops.merchants` holds 1 row, and there are no
  `E2E%`/`CP12%` leftovers from earlier runs. Nothing was created, so there is nothing to clean
  up.
- The real Direct Create path hard-codes `merchant_direct_handoff.DIRECT_CREATE_DATABASE =
  "runtime"`. No trusted mechanism points a real `/solve` Create at the test database. The test
  suite and the driver both monkeypatch it.

## 4. Tests run and results

| Check | Result |
|---|---|
| `python .claude/system_test.py` | all passed |
| `pytest` direct-execute e2e, lifecycle fencing, team lifecycle, tmux multi-role, reuse dispatch (`-k "not commits_and_releases"`) | 99 passed, 1 deselected |
| Live psmux p2f (15 steps) and p2g (13 steps) | 4 defects reproduced (above) |
| Phase 3 test-DB Create | **not run** (gate) |

The one deselected test (`test_scoped_merchant_create_commits_and_releases`) performs a real
test-DB Create. It was excluded because running it would be Phase 3 work. The 99 mocked tests
pass while the live run fails, because the mocks set `TMUX_PANE` per call and assume one tmux
server. They never present an unbound task to a stale or foreign pane over the reuse path.

## 5. Blockers and required fixes

All defects fail closed with respect to writes: no unauthorized mutation was observed.

**D1 — runtime Create can never succeed and burns authority (blocker).**
`merchant_direct_handoff._execute_reserved_create` calls `reserve_direct_scope_authorization`
(spend) and *then* `MerchantRepository(role="runtime")`. That raises
`ValueError: Unsupported Merchant database role: runtime` because the valid roles are app, alert,
owner and test.

*Fix:*

- Map the target the way `cli_contract` already does (`runtime → app`).
- Construct and check the repository (`config.database == DATABASE_NAMES[database]`) **before**
  the spend, so a configuration error cannot consume the one-use scope.

**D2 — stale pane can settle a new task (blocker).**
`team_lifecycle.direct_pane_identity_status` returns `MATCH` whenever the task is not yet bound
to a pane, without checking the caller's pane at all.

*Fix:*

- For a `merchant_execute` task, an unbound task must still require
  `verified_teammate_pane(owner, teammate)` to be non-`None`; otherwise return `IGNORE`.
- The result path that releases a direct task should also require the pane binding for the
  *current* task.

**D3 — foreign or stale idle on an unbound task gets `MISSING_RESULT_FEEDBACK` every time.**
This is a consequence of D2 (`teammate_idle_orchestrator.py` ~L414) and is resolved by the same
`IGNORE`.

**D4 — pane-id collision across psmux servers (blocker for "foreign panes rejected").**
`TMUX_PANE` alone is not a unique identity under psmux.

*Fix:*

- Bind the server identity too. Record the server field of `$TMUX` (socket path and server pid)
  from the lead's trusted PreToolUse dispatch into team state.
- Require the pane hook's `$TMUX` server to match before comparing `tmuxPaneId`.
- Before relying on this, confirm with a real `/solve` teammate that harness panes are created in
  the lead's psmux server.

**B5 — no trusted test-DB path for a real-harness Create.** The real-harness Phase 3 the
checkpoint asks for cannot target `coding_agent_merchant_test` without a monkeypatch. Do not add
an environment or CLI database selector to the agent surface, because that weakens the boundary.

*Options:*

- a test-only entry that the lead can invoke but the teammate cannot; or
- running Phase 3 as the existing in-process e2e test plus the live identity steps above.

**B6 — no harness-authored teammate record observed.** Fully closing Phase 2 needs one
user-typed `/solve` run that dispatches `merchant-manager` for a read-only request. That run
would capture its `members[].tmuxPaneId`, `TMUX`, and pane process, and would rerun p2f/p2g
against the real config.

## 6. Recommendation

**NO-GO** for enabling runtime Direct EXECUTE.

- Runtime Create cannot succeed and consumes authority on every attempt (D1).
- Pane identity does not satisfy the "foreign/stale panes rejected" contract live (D2, D4).

Write safety held throughout: every rejected path left authority unspent and the handler call
count unchanged.

Re-validate after D1, D2/D3 and D4 are fixed. That means rerunning p2f/p2g live, doing the B6
real-teammate capture, and then Phase 3 against `coding_agent_merchant_test` with cleanup
verification.

# CP12H.5B — Live psmux Identity and Safe Database Routing

- Date: 2026-10-30
- Branch: `feat/cp7-9-merchant-reliability`, baseline `84d28d2`
- Not committed or pushed. No runtime database write. The only runtime connection was the
  teammate's read-only `merchant list` in the §7.3 read-only gate, through its runtime-only
  read adapter.

| Decision | Verdict |
|---|---|
| Test-mode Direct EXECUTE | **GO** — real `/solve` read-only dispatch and test-target Create both passed (§7.3) |
| Runtime production execution | **NO-GO** — disabled in code; requires separate approval (§9) |

## 1. Root causes

**D1 — runtime Create could never succeed and burned authority.**
`merchant_direct_handoff._execute_reserved_create` spent the one-use scope
(`reserve_direct_scope_authorization`) and only then built
`MerchantRepository(role="runtime")`. The repository roles are `app/alert/owner/test`, so that
call raised `ValueError` after the spend. The same wrong mapping existed in
`team_result_hook._reconcile_direct_merchant_writes`, which would have broken reconciliation.
The CLI and write adapters already mapped targets correctly
(`cli_contract.repository_role_for_target`: `runtime → app`). There was also no check of the
database before the spend.

**D2 — a stale pane could settle a reassigned task.**
`team_lifecycle.direct_pane_identity_status` returned `MATCH` whenever the current task had no
pane binding yet, without looking at the caller's pane. On reuse, the record still held the
previous task's binding, so a stale pane's report and idle settled the new task.

**D3 — feedback loop for foreign panes.**
D3 follows from D2. A foreign pane idling on an unbound task got `MATCH`, and then
`MISSING_RESULT_FEEDBACK` (`rc=2`) on every idle.

**D4 — pane ids are not identities under psmux.**
psmux runs one server per session, and every server numbers its panes from `%1`. The identity
check compared only the `TMUX_PANE` string with `members[].tmuxPaneId`.

Two further facts were found live during this checkpoint:

- **(a)** psmux resolves a bare `-t %N` against its *default* session rather than the caller's
  `$TMUX`, and silently falls back to the current pane. A pane lookup by id is therefore
  unreliable.
- **(b)** psmux spawns new servers from existing ones, so servers **nest** in the process tree:
  server 7028 (`cp12h5b`) was a child of server 31436 (`idprobe`). A rule of "the pane's server
  is *an* ancestor of the lead" is therefore too weak. The first fix used that rule, and the live
  run caught it (§7.1).

**Harness producer.** Claude Code writes `members[].tmuxPaneId` and `backendType: tmux` for
teammates, and `leadProcess {pid, pidSpace}` for the lead (recent versions only; older configs
lack it). It records no server or session. We cannot change that producer. The fix therefore
uses only those harness fields plus operating-system evidence, and fails closed when
`leadProcess` is missing.

## 2. Files changed

| File | Change |
|---|---|
| `.claude/hooks/harness_team_identity.py` | Process-tree pane authentication (Windows Toolhelp / `/proc`), `tmux list-panes -a`, nearest-server lead check, `harness_member` (pane + lead pid) |
| `.claude/hooks/team_lifecycle.py` | `direct_pane_identity_status`: verify first; an unbound or stale task is bound only from the verified pane; anything else is `IGNORE` |
| `.claude/hooks/merchant_reserved_execution.py` | `DATABASE_ROLES`, `repository_for_target`, `preflight_database_identity`, `DatabasePreflightError`; executor pins database **and** user; spent authority must name the target |
| `.claude/hooks/merchant_direct_handoff.py` | `RUNTIME_DIRECT_EXECUTE_ENABLED = False`, test mode limited to Create, `preflight_direct_execute` before any reservation or spend; target comes only from the staged attempt; `DIRECT_CREATE_DATABASE` removed |
| `.claude/system/merchant_runtime_handoff.py` | `validate_direct_scope(argv, database_target)`; target included in `scope_hash` and confirmation hash; staged-handoff and authority binding to target |
| `.claude/hooks/merchant_runtime_handoff_gate.py` | Request target must equal trusted scope target; target is stored in the staged handoff and `PreparedRuntimeHandoff`; execution receipt must report that target |
| `.claude/hooks/intent_gate.py` | User-typed `--merchant-target test` (only `test` can be named; the default is `runtime`) |
| `.claude/hooks/policy_gate.py` | Dispatch re-validation uses the persisted target |
| `.claude/hooks/team_result_hook.py` | Reconciliation uses `repository_for_target`; injects `DirectPreflightRefused` |
| `.claude/hooks/team_result_dispatcher.py` | Separate "refused before execution, authorization not spent" outcome |
| `.claude/hooks/teammate_idle_orchestrator.py` | A no-write result's declared target must equal the trusted scope target |
| `.claude/hooks/team_result_contract.py` | Declared target may be `runtime` or `test` (it never selects a database) |
| `CLAUDE.md`, `.claude/commands/solve.md`, `.claude/agents/merchant-manager.md` | Identity rule, runtime disabled, test-target syntax and contract |
| `tests/merchant/test_cp12h5b_identity_and_routing.py` (new) | 27 RED/GREEN tests (§6) |
| 14 existing test files | Fixtures now write `leadProcess` and fake only the OS evidence. Runtime-lifecycle tests explicitly enable the constant for an in-memory handler. Completion-only tests use the injected pane-status seam. The test-DB Create test now uses `--merchant-target test` with nothing patched |

## 3. Before/after evidence

| Defect | Before (CP12H.5A live, and RED on baseline) | After (live §7.1, GREEN) |
|---|---|---|
| D1 | Spend, then `ValueError`; message "attempted … spent" | Runtime: `RUNTIME_EXECUTION_DISABLED`. Bad config: `INVALID_CONFIGURATION`. Unreachable: `DATABASE_UNAVAILABLE`. All refused **before** reservation or spend |
| D2 | Stale `%1` settled reused task `IDLE_REUSABLE` (p2g#10–11) | Stale `%2` execute is rejected; its report and idle are ignored; task stays `RUNNING`. Respawned `%3` executes once and releases (L6#9–15) |
| D3 | `rc=2` on every foreign idle (p2f#6–8) | `rc=0`, no state change (L1#9–11) |
| D4 | Lead-server `%1` accepted from another session (p2f#4) | `%2` in another (nested, outer) server: `own_server=31436`, not verified; execute rejected, nothing spent (L1#4–8) |

## 4. Trust boundary and limitations

A pane is verified for `(owner session, teammate)` only if **all** of the following hold:

1. **One harness team.** Exactly one harness team config has `leadSessionId == owner`. It has a
   `leadProcess.pid` whose `pidSpace` equals this host. It has one member with
   `name == agentType == teammate`, `backendType == "tmux"` and `tmuxPaneId == %N`.
2. **Pane id.** The hook process's `TMUX_PANE == %N`.
3. **Own pane.** Exactly one pane listed by `tmux list-panes -a` with id `%N` has a `pane_pid`
   that is an ancestor of the hook process. Its parent is a `tmux`/`psmux` executable: this
   pane's server *S*.
4. **Lead's server.** *S* is the **nearest** server ancestor of the harness lead pid.

The verified identity is `"S:%N"`. The binding stores it together with the pane session, run and
task.

- **Binding at idle.** A task is bound only from a verified pane, at execute or at idle. A stale
  binding from a previous task is replaced only by the pane the harness records now.
- **Ignored events.** Unverified, stale, foreign, or other-run/task events are `IGNORE`d: no
  state change and no feedback. A verified pane presenting a different session for a bound task
  is a `CONFLICT`: the task ends `FAILED` once.
- **`$TMUX` is not trusted.** It is never used. psmux routing ignores it, and the process tree
  is used instead. The CP12H.5A recommendation to compare `$TMUX` was rejected for that reason.

**Remaining same-user limitations (not cryptographic):**

- **Injection into the pane.** A process injected into the teammate's own pane (for example
  `tmux send-keys`) runs as a descendant of that pane and passes.
- **Fake `tmux` on PATH.** A replaced `tmux` executable on `PATH` can lie about `pane_pid`. It is
  bounded because the claimed pid must still be a real ancestor whose parent is a server
  executable that is also the lead's nearest server.
- **Windows PID reuse.** A reused parent pid could, in theory, create a false ancestry if a parent
  exits. Live parents (pane shell, Claude process) do not exit during a hook.
- **Missing `leadProcess`.** Older harness versions don't write it. Every Direct EXECUTE pane is
  then unverified, and the task fails closed: no settlement, no feedback.

merchant-manager cannot use these routes, because its shell is limited to the allowlisted
scripts. The write itself still requires the user's one-use scope.

## 5. Database routing contract

- **Selection.** The user types `/solve --confirm --merchant-target test --merchant-scope [...]`.
  Without the flag the target is `runtime`. `--merchant-target` accepts only `test` and must
  precede `--merchant-scope`.
- **Binding.** The target is bound into all of these:
  - `scope_hash = sha256({argv, database_target})`;
  - the confirmation envelope (`confirmation_hash`, which is also the policy dispatch receipt
    binding);
  - the staged handoff `database_target`;
  - `PreparedRuntimeHandoff.database_target`;
  - the Create reservation `database`;
  - the spent authority `database_target` (checked by `spent_authority_matches`);
  - the execution receipt `database`.

  Expansion and Submit must agree on the target.
- **Teammate input.** The teammate's `database_target` must equal the trusted target or the
  request is rejected at staging, with nothing spent. Rewriting the persisted target breaks
  `scope_hash` and `confirmation_hash`. No environment variable, CLI argument, message text or
  payload selects the database.
- **Physical identity.** The physical identity is pinned in code: `test → (role test,
  coding_agent_merchant_test, merchant_test)` and `runtime → (role app, coding_agent_merchant,
  merchant_app)`. The test role reads only the `MERCHANT_TEST_*` credentials.
- **Order of checks before any reservation or spend:**
  1. runtime disabled → `RUNTIME_EXECUTION_DISABLED`;
  2. test mode and not `merchant create` → `TEST_MODE_COMMAND_UNSUPPORTED`;
  3. repository config names another database or user → `INVALID_CONFIGURATION`;
  4. read-only `SELECT current_database(), current_user` fails → `DATABASE_UNAVAILABLE`, or
     returns a mismatch → `INVALID_CONFIGURATION`.
- **Refusals.** A refusal is reported as "refused before execution … authorization was not
  spent". The run cannot retry, and the teammate reports `FAILED` (no write).
- **Outcome classes:**

  | Class | Meaning |
  |---|---|
  | Invalid configuration | Refused before execution, not spent |
  | Database unavailable | Refused before execution, not spent |
  | Authorization denied | `RESERVE_AUTHORIZATION` stage error |
  | Attempted but uncertain | `UNCERTAIN`; never inferred as rolled back |
  | Committed | Verified by reconciliation and recorded as a completion receipt |

- **Runtime gate.** Runtime is `RUNTIME_DIRECT_EXECUTE_ENABLED = False`, a code constant. There
  is no environment flag.

## 6. RED/GREEN results

- **RED.** New tests were run against the baseline code (`git stash -- .claude`). Results:
  **22 failed, 4 passed**. The 4 that pass are regression guards: existing cross-target
  rejection, duplicate idle, and read-only completion. The key RED assertions:
  - D2: stale pane → `'IDLE_REUSABLE' == 'RUNNING'`;
  - D3: `idle(rogue) == 2`;
  - D4: other-server `%7` settled → `'IDLE_REUSABLE'`;
  - D1: "attempted … spent".

  The nested-server test was also RED against the first "any ancestor" fix.
- **GREEN.**
  - New file: 27 passed.
  - Full suite: `pytest tests -k "not runtime_live"` → **3352 passed, 20 skipped, 1 xfailed**.
    Baseline was 3324 passed with 1 deselected.
  - `python .claude/system_test.py` → 100%.
  - `git diff --check` → clean.
- **Coverage.** D2 stale pane; D3 foreign pane while unbound; D4 equal ids across servers,
  including nested servers; D1 runtime and invalid configuration before spend; database
  unavailable; identity mismatch; test routing never reads runtime credentials;
  cross-target replay and test→runtime escalation; test mode refuses non-Create; duplicate and
  conflicting pane events; read-only task completes with no verifiable pane.
- **Test-database Create in the suite.** `test_scoped_merchant_create_commits_and_releases` now
  creates through `--merchant-target test` with nothing patched, then cleans up its own claim,
  ledger row, events and merchant. Afterwards the test DB holds no ledger rows and only its
  pre-existing merchant.

  *Correction (CP12H.5B.1):* an earlier draft said the test DB held no `merchant-direct:` claims.
  That was wrong. It holds 16 historical `merchant-direct:` claims, classified in §7.4. Separately,
  other DB-backed tests leave `pytest:*` claim rows (2 per suite run). This predates the change and
  the rows were left in place.

## 7. Live psmux results

| Layer | Mocked? |
|---|---|
| Unit/regression tests (§6) | OS evidence faked (`_os_pane_server` / `own_pane_server`); harness record and `TMUX_PANE` checks real |
| Live driver (§7.1) | **Nothing about identity mocked**: real psmux panes, real `tmux list-panes`, real Windows process tree, real hooks as separate processes. Synthetic only: harness `config.json` (isolated dir, **real** lead pid) and an in-memory handler for the scoped write (runtime constant enabled in the driver process only) |
| Real harness `/solve` (§7.3) | Nothing mocked. Real harness, real teammate pane, real test DB. The read-only and Create gates both passed |

### 7.1 Live driver

The driver is `live_driver_5b.py` and `run_live_5b.sh` in the session scratchpad. The process
setup:

- **Lead stand-in.** Pane `cp12h5b:%1`, pid 30708, in server 7028.
- **Teammate.** The harness records the teammate as `%2`.
- **Foreign same-id pane.** `idprobe:%2` is in server 31436, the *outer* nested server.

**L1 — identity, foreign panes, binding and conflict**

| # | Pane | Step | Result |
|---|---|---|---|
| 2 | `%2@7028` | whoami | verified `7028:%2` |
| 3 | `%3@7028` | whoami | not verified (not the harness pane) |
| 4 | `%2@31436` | whoami | `own_server=31436`, **not verified** |
| 5 | lead shell `%1@6316` | whoami | not verified |
| 6–8 | `%2@31436` | execute / report / idle | rejected `PANE_IDENTITY_UNVERIFIED`; ignored; spent=False, 0 calls |
| 9–11 | `%3` | idle ×3 (unbound task) | `rc=0`, no state change |
| 12 | `%2@7028` | idle | bound `7028:%2`, `rc=2` (asked for its result) |
| 13–15 | `%2@7028` | idle with new session; execute | `PANE_BINDING_CONFLICT` once, then stable; execute rejected |

**L6 — success, duplicates, reuse, stale pane, respawn**

| # | Pane | Step | Result |
|---|---|---|---|
| 2–6 | `%2@7028` | execute, duplicate execute, report, idle ×2 | executed once; duplicate rejected; `IDLE_REUSABLE`; no second write |
| 7–8 | lead | reuse via the real policy-gate SendMessage path; harness now records `%3` | new task `RUNNING` |
| 9–12 | stale `%2` | execute / report / idle ×2 | rejected; ignored; `RUNNING`; not spent |
| 13–15 | `%3@7028` | execute / report / idle | `7028:%3` bound, executed once (calls=2), `IDLE_REUSABLE` |

The first live run (archived in `live_run1/`) used an "any ancestor" rule. It **accepted**
`%2@31436` (L1#4) and let it execute (L1#6–8). That led to the nearest-server rule. The rerun
above is clean.

### 7.2 Database target confirmation

A read-only query returned `coding_agent_merchant_test` / `merchant_test` (port 5432). No runtime
connection was opened: every live driver process refused non-`test` repositories.

### 7.3 Real harness `/solve` — PASS

1. **Read-only dispatch — PASS (2026-10-30).** The user typed
   `/solve List merchants in the Merchant database`. The envelope was `read_only`, with roster
   `merchant-manager`. Results, all checked from outside the pane without touching it:
   - The harness config gained `merchant-manager: backendType tmux, tmuxPaneId %5`, with
     `leadProcess.pid` 29756.
   - `tmux list-panes -a` showed `0:%5` with `pane_pid` 32408 (`powershell.exe`), whose parent is
     server **6316** (`tmux.exe`). The teammate `claude.exe` 9156 runs inside it.
   - The lead's chain is 29756 → 30584 → **6316**, so 6316 is the nearest server ancestor. The
     identity the hook verifies would be `6316:%5`.
   - The read-only `merchant list` returned 23 rows, reported once via `SendMessage`, and ended
     `IDLE_REUSABLE` with `report_source=sendmessage`.
   - A read-only task binds no pane: pane verification applies only to `merchant_execute` tasks,
     so the record keeps no `trusted_*` fields.
   - Observation: for a moment right after creation, psmux listed `%5` with an empty `pane_pid`.
     `own_pane_server` finds no matching ancestor in that state, so it fails closed. It does not
     accept the pane.
2. **Pre-write check — PASS.** The read-only `preflight_database_identity` on the test target
   returned `coding_agent_merchant_test` / `merchant_test`.
3. **Disposable Create — PASS (2026-10-30).** The user typed:

   `/solve --confirm --merchant-target test --merchant-scope ["merchant","create","--code","CP12H5BLIVE1","--name","CP12H5B Live Test"] Create disposable test merchant CP12H5BLIVE1`

   The resulting envelope:
   - `external_write`, `confirmed: true`, roster `merchant-manager`;
   - `merchant_scope.database_target: test`;
   - `scope_hash 3c9b5084…`, `run_id 4d9d2ca6-f966-41cf-9b4b-eb5920828850`.

   The `IDLE_REUSABLE` teammate was reused through `SendMessage`; no new pane was created.

   **Directly observed** (team-state file, harness config, and a read-only query against
   `coding_agent_merchant_test` as `merchant_test`):

   | Evidence | Observed |
   |---|---|
   | Teammate messages | Exactly one `MERCHANT_EXECUTE_REQUEST_JSON` (`database_target: test`, exact scope argv). Completeness `complete=true`. Final `TEAM_RESULT_JSON` `EXECUTE_SUCCESS`, `database_target: test`, `proposal_emitted: false` |
   | Pane binding | `trusted_tmux_pane_id = "6316:%5"`, `trusted_pane_task_id = 4d9d2ca6…:merchant-manager`. Only the hook running inside the real teammate pane can produce this value |
   | Completed write record | `database: test`, `command: merchant create`, `operation_key merchant-direct:v1:a614e98a…`, `payload_hash e0032c0f…`, `execution_attempt_id b5d3ee10…`, `claim_generation 1`, `merchant_id e808b9b5-7f5c-4bfa-a214-bfd1e408724b` |
   | PostgreSQL (before cleanup) | `merchants`: 1 row (`CP12H5BLIVE1`, "CP12H5B Live Test", version 1). `project_events` for the merchant: 1. `merchant_execution_ledger` for the key: 1. `merchant_execution_claims` for the key: 1. `merchant_contacts` / `projects` / `integration_identifiers`: 0 |
   | Lifecycle | `IDLE_REUSABLE`, `report_source sendmessage`, `result_received true`; a second idle notification left the counts unchanged |
   | Runtime untouched | The teammate's read-only runtime `merchant resolve --query CP12H5BLIVE1` returned NOT_FOUND |
   | Cleanup | One transaction, with the identity re-asserted first: deleted 1 project_event, 1 claim, 1 ledger row, 1 merchant (each `rowcount == 1`). Afterwards: no `CP12H5BLIVE1`, ledger table empty, 1 merchant total (the pre-existing `TEST_CLI_20260915110525`) |

   **Inferred, not directly observed:**
   - That the read-only identity preflight ran inside the hook immediately before the
     reservation. The code path requires it, and the committed row in the test DB is consistent
     with it, but no hook trace was captured.
   - That the receipt in the completed write record was produced from verified committed
     PostgreSQL evidence. Release to `IDLE_REUSABLE` is gated on it in code.

### 7.4 Historical `merchant-direct:` claims in the test DB (CP12H.5B.1)

The rows were inspected read-only (`transaction_read_only = on`, `coding_agent_merchant_test` /
`merchant_test`). Nothing was deleted, updated or revoked.

| Property | Observed |
|---|---|
| Count | **16** claims with `operation_key` prefix `merchant-direct:` (of 129 total; the other 113 are `pytest:*`) |
| Status | All `COMPLETED`, `claim_generation 1`, distinct payload hashes and attempt ids |
| Timestamps | 4 on 2026-10-15 00:00:35–00:01:18 (+07). 12 on 2026-10-20 16:20:31–19:27:42, in pairs about 0.4 s apart |
| Active, reserved, executing or uncertain | None |
| Matching ledger rows | None. `merchant_execution_ledger` holds 0 rows in total |
| Orphan merchants | None. The test DB holds only `TEST_CLI_20260915110525` |
| Team-state reservations | No key appears in any `.claude/runtime` or `~/.claude/teams` file. No teammate record has an active reservation. The only `merchant-direct:` key in team state is the live run's (already cleaned up) |

**Classification: historical pytest leakage, terminal and inert. Attribution is circumstantial.**
- Real `merchant-direct:v1:<sha256>` keys are produced only by `merchant_direct_binding`, so by a
  real Direct EXECUTE Create.
- The only DB-backed test that drove such Creates during that window was
  `tests/merchant/test_reserved_execution_e2e.py`, which has existed since 2026-10-14. At
  `921e2c5` (2026-10-20 16:46) its cleanup deleted ledger rows, events and merchants but **not
  claims**, and two of its tests commit a Create, which fits the pairs. Claim cleanup was added in
  `009bfcc` (2026-10-20 23:17), and all 16 rows predate it.
- The keys are hashes of per-run payloads, so no row can be tied to a specific test invocation.
  Ownership is therefore **likely but not proven**.

## 8. Remaining blockers

- **Harness dependency.** Identity depends on `leadProcess` in the harness config. Older Claude
  Code versions omit it, and Direct EXECUTE then fails closed.
- **Same-user limits.** The limitations in §4 remain by design.
- **Test mode is Create-only.** Non-Create test routing would need the scoped CLI path to carry
  `--database test` under the same authorization. It was not built.
- **Leftover claim rows (housekeeping, not security).** The 16 historical `merchant-direct:`
  claims (§7.4) and the growing `pytest:*` claims (§6) are all `COMPLETED` and not referenced by
  any state. They need a cleanup decision from the owner. No active or uncertain claim exists.
- **Brief window after pane creation.** For a moment after creation, psmux reports an empty
  `pane_pid`. An execute request in that window is refused (fail-closed) rather than accepted.

## 9. GO / NO-GO

- **Test-mode Direct EXECUTE: GO.** It is verified by:
  - RED/GREEN tests;
  - the full suite;
  - live psmux identity on real processes;
  - a real `/solve` read-only dispatch and a real `/solve` test-target Create (§7.3). The Create
    bound pane `6316:%5`, committed exactly once to `coding_agent_merchant_test` as
    `merchant_test`, released to `IDLE_REUSABLE`, and was cleaned up.

  Scope stays limited to `merchant create`.
- **Runtime production execution: NO-GO.** It is disabled in code
  (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`) and was never exercised against production.
  Enabling it requires separate approval, plus a runtime-specific preflight run against
  `coding_agent_merchant` / `merchant_app` in a controlled window.

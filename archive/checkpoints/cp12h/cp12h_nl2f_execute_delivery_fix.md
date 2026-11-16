# CP12H.NL2F — Cross-Run Project Confirmation and Execute Message Routing

Branch `feat/cp7-9-merchant-reliability`, baseline `204bcde`. The uncommitted NL1, NL2, NL2A,
NL2B, NL2C and NL2E changes are preserved. Nothing was committed or pushed. No live `/solve`
Project Create was performed.

## 1. Root causes

### RC1 — The execute request was judged by the preview delivery contract (primary)

`policy_gate._main` runs `merchant_preview_delivery.preview_delivery_decision` on **every**
merchant-manager `SendMessage`, whatever the run's trusted operation is. With no
current-task preview evidence, the predicate that rejected the live request was:

```python
# merchant_preview_delivery.preview_delivery_decision (before NL2F)
expected = None                                   # no VERIFIED evidence for this task
if blocks or claims_ready or _OPERATION_TEXT.search(message):
    reason = "no verified Project preview operation exists for this task"  # evidence is None
    return deny(... + DELIVERY_FAILED_INSTRUCTION)
```

`_OPERATION_TEXT` contains `\[\s*"project"\s*,\s*"create"` and `"--merchant-id"`. A correct
`MERCHANT_EXECUTE_REQUEST_JSON` for a Project create always carries both in its `arguments`.
So every scoped Project create was denied before it reached the trusted staging hook.

The cause was not message classification inside the execute gate, and not a missing cross-run
capability. It was contract dispatch: one shared PreToolUse hook applied a read-only contract
without checking the run's operation or the message type. Run B (the user's confirmation) is a
fresh task, so it can never have Run A's task-local evidence.

### RC2 — The denial told the teammate to call itself a preview failure

`DELIVERY_FAILED_INSTRUCTION` tells the sender to resend with a `PREVIEW_DELIVERY_FAILED:`
prefix. The teammate followed it, so a blocked execute request was reported as a preview
delivery failure.

### RC3 — The tests never drove the PreToolUse gate for execute requests

`test_direct_execute_end_to_end.send()` and the NL2 PostgreSQL tests call only the PostToolUse
`team_result_hook`. The harness runs PreToolUse first, so the real ordering was never tested.

### Phase 4 finding — RESULT_DELIVERED

The `RESULT_DELIVERED` final answer came **after** the teammate's terminal `SendMessage`
(`BLOCKED` plus `TEAM_RESULT_JSON`) had succeeded; the lead received it. The denied call was the
earlier execute request. The claim was therefore true for the terminal report. The only
misleading part was RC2's prefix. The lifecycle already refuses to release a teammate on a
denied call: a denied tool never runs PostToolUse, so nothing reaches the ledger, and
`TeammateIdle` exits 2. This is now covered by a regression test (#11). Settlement as
`BLOCKED` with a no-write marker was correct: nothing was staged, reserved or spent.

### Phase 5 finding — `variant` vs `workflow_variant`

The scope argv uses CLI flags (`--variant`), but `completeness check --payload-json` expects
repository payload keys (`workflow_variant`, set by argparse `dest=`). The model rebuilt the keys
by hand. The trusted handoff already translates the argv deterministically
(`build_argument_parser` + `build_write_payload`); the teammate had no access to that
translation.

## 2. Contract routing before and after

| Message from merchant-manager | Run (trusted state) | Before | After |
|---|---|---|---|
| `MERCHANT_EXECUTE_REQUEST_JSON` | scoped `merchant_execute` | **Denied** by the preview gate (RC1) | Allowed at Pre; staged and validated at Post against the persisted scope (command, exact argv, target, run/task, pane, completeness, reservation) |
| `MERCHANT_EXECUTE_REQUEST_JSON` | unscoped `merchant_read` | Denied, worded as a preview failure | Denied: "valid only in a run with a user-authorized `--merchant-scope`" |
| `MERCHANT_EXECUTE_REQUEST_JSON` | run of the task not verifiable (stale/missing) | Denied as a preview failure | Denied: no verifiable scope |
| Execute request **and** preview block / `PREVIEW_DELIVERY_FAILED` / `confirmation_command` | any | Denied as a preview failure | Denied: mixed contracts |
| `MERCHANT_PREVIEW_OPERATION_JSON`, `PREVIEW_DELIVERY_FAILED`, `confirmation_command` | scoped `merchant_execute` | Preview contract | Denied: a scoped run cannot present a preview result |
| Preview report or operation block | `merchant_read` | Evidence-bound | **Unchanged**: evidence-bound |
| Terminal `TEAM_RESULT_JSON` | scoped | Preview gate, then terminal consistency | Terminal consistency gate only |

The run's operation comes only from trusted run state written by the intent gate. A
`merchant_scope` there means `merchant_execute`. Teammate text never selects the contract.

**Cross-run confirmation (Phase 3).** No new write path was added. Run B is validated by what
already existed: the persisted user scope (`validate_direct_scope`: canonical preview argv,
explicit procurement flag, UUID targets, completeness); staging of the exact arguments and
target; the read-only preflight that recomputes the preview against current test-DB state
(merchant id and code, project id, type, variant, Unicode title, procurement, `expected_basis`,
template, existing Projects); and the in-transaction re-check and idempotency. None of these
depend on Run A's task id or task-local evidence.

## 3. Changes

| File | Change |
|---|---|
| `.claude/hooks/merchant_preview_delivery.py` | `trusted_run_operation`, `_message_contract_decision` (routing above); `_owner_run` exposes the task's run state; `_owner_binding` is unchanged in behaviour |
| `.claude/agents/tools/merchant/cli.py` | `completeness check --argv-json` (mutually exclusive with `--payload-json`); `scope_argv_payload` reuses the trusted parser and `build_write_payload`, and refuses an argv that names another command |
| `.claude/agents/merchant-manager.md` | Use `--argv-json` for scoped runs; execute requests are scope-checked, not preview-checked; no preview content in scoped runs; report `BLOCKED` on denial; never claim delivery of a blocked message |
| `tests/merchant/test_nl2f_execute_delivery.py` | 22 tests; every message goes through the real PreToolUse gate, then PostToolUse only if allowed; includes 2 real policy-gate subprocess tests |
| `tests/merchant/test_nl2f_execute_delivery_postgres.py` | 3 test-DB integration tests |

## 4. RED/GREEN evidence

RED was produced by restoring the pre-NL2F routing: `_message_contract_decision` was
monkeypatched to always return the preview contract, through a temporary pytest plugin that was
then removed.

| Suite | RED (pre-NL2F routing) | GREEN |
|---|---|---|
| `test_nl2f_execute_delivery.py` | 15 failed, 7 passed | 22 passed |
| `test_nl2f_execute_delivery_postgres.py` | 3 failed | 3 passed |

The 7 that pass under RED are invariants that already held: the read-only evidence binding,
the stale-run-unscoped and malformed paths that were denied anyway, the idle hold, production
disabled, and the subprocess tests. The plugin cannot patch a subprocess, so those 2 run real
code. The `--argv-json` test fails on the old code with `ImportError` (`scope_argv_payload`
does not exist there).

| # | Requirement | Test |
|---|---|---|
| 1 | Cross-run preview → confirmed execute accepted | `test_cross_run_execute_request_passes_the_message_gate`, `…reaches_the_trusted_preflight…`, PG `test_cross_run_confirmation_creates_exactly_one_project` |
| 2 | Missing current-task preview evidence does not block | same; asserts `project_preview_evidence` is absent |
| 3 | Missing persisted authorization rejected | `test_execute_request_in_an_unscoped_run_is_refused`, subprocess `…still_refuses_an_unscoped…` |
| 4 | Read-only previews stay evidence-bound | `test_read_only_preview_block_still_needs_current_task_evidence` plus all 95 NL2E tests |
| 5 | Execute messages cannot masquerade as preview | `test_scoped_run_messages_cannot_present_as_preview_results` ×3 |
| 6 | Mixed message types rejected | `test_mixed_execute_and_preview_contracts_are_refused` |
| 7 | Wrong run/task or target rejected | `test_execute_request_from_a_stale_run_is_refused`, `test_wrong_database_target_is_rejected_at_staging_without_spend`, PG `test_runtime_target_request_for_a_test_scope_writes_nothing` |
| 8 | Stale `expected_basis` rejected | PG `test_stale_merchant_state_after_run_a_is_refused_before_spend`; existing NL2 PG stale-basis and in-transaction tests |
| 9 | Merchant id/code mismatch rejected | `test_changed_arguments_never_reach_the_preflight[code]`; existing NL2 PG merchant-code tests |
| 10 | Malformed or reordered arguments rejected | `test_changed_arguments_never_reach_the_preflight` (reordered, truncated, folded title), `test_malformed_execute_request_never_reaches_the_preflight` |
| 11 | Failed SendMessage cannot produce RESULT_DELIVERED | `test_blocked_send_message_cannot_release_the_teammate` (idle exit 2, not `IDLE_REUSABLE`) |
| 12 | A blocked attempt is never retried silently | `test_a_refused_attempt_is_never_retried` (preflight called once) |
| 13 | UTF-8 titles survive | `test_unicode_title_survives_into_the_staged_request`, subprocess test with UTF-8 stdin, PG title assertion |
| 14 | Production Direct EXECUTE disabled | `test_runtime_direct_execute_remains_disabled` |
| P5 | Deterministic argv → payload | `test_completeness_from_scope_argv_uses_the_trusted_translation`; CLI run returns `complete: true` for the live argv |

## 5. Regression results

| Run | Result |
|---|---|
| Focused: NL2F unit + PG | 25 passed |
| Focused: NL2E P1/P2/P4 + P4 delivery | 95 passed |
| Focused: NL1/NL2/NL2F PostgreSQL | 17 passed |
| Full `pytest tests` (PostgreSQL configured) | **3677 passed, 20 skipped, 1 xfailed, 97 subtests passed** (4m14s); the 3 NL2F PG tests ran separately (above) |
| `python .claude/system_test.py` | 100% pass |
| `git diff --check` | clean |

## 6. Database reconciliation (`coding_agent_merchant_test`, read-only, after all suites)

| Check | Result |
|---|---|
| Beta fixture `NL2_LIVE_BETA` | `6e0c1a2b-…`, "Beta Cinemas", ACTIVE, version 1: **unchanged** |
| Beta Projects / previewed Project `30fffeaf-…` | 0 / does not exist |
| Historical claims | 16, all COMPLETED (NL2E baseline: 16) |
| Ledger | 0 rows (baseline 0) |
| Table counts | merchants 2, projects 1, project_steps 26, dependencies 26, events 5, templates 4: same as the NL2E baseline |
| `PYTEST_*` Merchants, `pytest:` claims and ledger rows left | 0 / 0 / 0 |
| md5 snapshot | claims `d6217d8c…`, merchants `094d5dba…`, projects `1e91b4a3…`, steps `abeb9e49…` |

## 7. Remaining security limitations

- The contract is chosen from trusted run state, but a teammate is identified at PreToolUse by
  the harness-reported `agent_type`, as before. Pane identity is verified at PostToolUse
  staging, not at Pre.
- Pre now allows a well-formed execute request in a scoped run. All authority checks stay at
  Post staging and in the trusted preflight. Pre is a filter, not the authority.
- Marker detection is substring-based. A scoped-run report that quotes
  `confirmation_command` in prose is denied. That is fail-closed and gets one correction turn.
- Defense in depth, not a sandbox: any same-user process that can run arbitrary Python can
  still reach the test credentials (unchanged; see `CLAUDE.md`).
- Round limits are not enforced per teammate: the live teammate used 3 rounds against
  `max_tool_rounds: 1` (out of scope here).

## 8. GO / NO-GO

**GO** for a fresh read-only Project preview, followed by a controlled test-database creation
through `/solve --confirm --merchant-target test --merchant-scope [...]`. Use the new preview's
`confirmation_command`. The old argv is valid only while the Merchant and Projects are
unchanged, and the preflight re-checks that anyway.

Watch for: an exact Pre allowance of the execute request; staging against the persisted scope;
a passing preflight; exactly one Project with 22 steps; one COMPLETED claim; `EXECUTE_SUCCESS`;
and the teammate returning to `IDLE_REUSABLE`.

Runtime (production) Direct EXECUTE remains **NO-GO**: it is disabled in code.

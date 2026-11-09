# CP12H.NL4C2A — Trusted Test-Only Step Update Execution

> **Final NL4C status (committed together as `feat(merchant): enable trusted test-only step updates`).**
> - **Execution:** Step Update runs **only on the test database** (`coding_agent_merchant_test`), only from the user's own `/solve Xác nhận cập nhật` of a verified preview. **Production (runtime) Direct EXECUTE is disabled in code** (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`).
> - **Automated regression:** the final full suite is in the NL4C commit summary.
> - **Live acceptance:** one user-confirmed Step Update (step 1 READY → IN_PROGRESS of Project `8dd4c68d-…`) returned EXECUTE_SUCCESS, and an **independent read-only PostgreSQL verification** found it EXECUTED_AND_VERIFIED (`cp12h_nl4c2b_live_acceptance.md`).
> - **`confirmation_available`:** `true` only for a READY test-database preview. It means the user may confirm; it never means a write is authorized. This supersedes any "always false" wording below.
> - **Known limitations:** see the "Remaining risks" section of each report.

Baseline `578790c` (+ uncommitted NL4C1), branch `feat/cp7-9-merchant-reliability`.
Not committed, not pushed. No live Step Update was run. `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

## 1. Architecture and exact execution flow

There is no new writer. A confirmed Step Update runs through the **existing scoped-write path**,
the same one a previewed `project create` takes.

| # | Stage | Code | Step-specific in NL4C2A |
|---|---|---|---|
| 1 | Run A: read-only `step preview`; PostToolUse(Bash) captures the verified READY output and records a pending Step Update | `merchant_preview_delivery.record_read_evidence` → `record_pending_step` | — (NL4C1) |
| 2 | The user types `/solve Xác nhận cập nhật [<id>]`; UserPromptSubmit spends exactly one live record into `merchant_scope` | `intent_gate.confirm_pending_step` → `pending.resolve(kind=step)` | allowed only where `direct_execute_enabled("step update", target)`, so test only |
| 3 | A typed `--merchant-scope ["step","update",...]` is refused | `intent_gate.run` | **new** |
| 4 | Policy gate dispatch receipt; teammate reuse; pane identity; staging; completeness evidence | `policy_gate`, `team_result_hook`, `merchant_runtime_handoff_gate` | unchanged |
| 5 | Preflight, before any reservation or spend: target allowlist → terminal marker → **confirmed-record check** → DB identity → `verify_step_update` re-judgement | `merchant_direct_handoff.preflight_direct_execute` | `_confirmed_step_operation` **new**; `_verify_step_preview` (NL4C1) |
| 6 | Persist `direct_scope_execution` EXECUTING with a fresh `execution_attempt_id` | `_begin_scope_execution` | unchanged |
| 7 | One-use spend bound to that reservation | `reserve_direct_scope_authorization` | unchanged |
| 8 | Test-target guard re-check, then `agent_cli --database test step update ... --execute` | `invoke_authorized_scope_apply` | unchanged |
| 9 | One evidence-bound transaction: claim + ledger insert → lock project/steps → **in-transaction `verify_step_update`** → domain `transition_step` (UPDATE + STEP event) → ledger result + claim COMPLETED → commit | `attempt_evidence._BoundConnection`, `transition_repository.transition_step(precondition=...)` | precondition (NL4C1) |
| 10 | Settle from committed evidence (fence a missing claim, never infer a rollback) | `settle_scope_execution` | unchanged |
| 11 | On SUCCEEDED: build a receipt from the ledger, claim and STEP event of that transaction; check it against the confirmed operation; persist it in the run state | `_record_step_receipt` → `attempt_evidence.step_update_receipt` | **new** |
| 12 | The teammate's `TEAM_RESULT_JSON` must agree with the evidence; TeammateIdle releases only on SUCCEEDED | `merchant_terminal_consistency`, `team_lifecycle` | unchanged |

## 2. Allowlist and authorization changes

- `TEST_MODE_COMMANDS = {merchant create, project create, step update}`. Runtime is still disabled in code.
  - No other command joined test mode. A test asserts that `project update`, `document approve` and `procurement update` stay refused.
- There is no general Step Update permission:
  - **Typed scope refused.** `/solve --confirm [--merchant-target test] --merchant-scope ["step","update",...]` is blocked in the intent gate on both targets, so a typed, pasted or model-built Step argv is never authority.
  - **Confirmed record required.** The preflight calls `pending.confirmed_step_record(owner, run_id)`. It needs exactly one record in the Step store with status CONFIRMED, owned by this session and confirmed for this exact `run_id`. Its operation must pass `validate_step_operation`, and its argv and database target must equal the staged attempt. Otherwise the attempt is refused unspent with:
    - `STEP_CONFIRMATION_REQUIRED`: the record is missing, from another run or session, damaged, or in the Project store;
    - `STEP_CONFIRMATION_MISMATCH`: a different argv or target.
- **Runtime target.** A runtime-target Step confirmation is refused at the gate, and the record is not spent. A runtime attempt is refused in the preflight with `RUNTIME_EXECUTION_DISABLED`.
- **Existing checks are unchanged:**
  - Requirements 1–9: test target, exact Step/Project/Merchant, target status, versions, basis, and a trusted, single-use confirmation. These are enforced by the canonical argv (`_require_canonical_step_argv`), the basis hash (which covers the Project row, including `merchant_id`), the Merchant-code check, `verify_step_update` and the domain engine.
  - The Project create and Step stores stay separate. The preflight reads only the Step store, and a test shows a CONFIRMED-looking record in the Project store authorizes nothing.

## 3. Revalidation and locking

- **Gate (UserPromptSubmit).** It spends one PENDING record under the pending-store file lock. A replay, a second session, an expired record or an ambiguous choice is refused.
- **Preflight (read-only, nothing spent).**
  1. Confirmed-record check.
  2. Database identity (`coding_agent_merchant_test` / `merchant_test`).
  3. `verify_step_update`: Merchant code, step in Project, step version, transition and gate re-run through `_evaluate`, and the basis hash over Project, steps, dependencies, revisions, approvals and procurement.
- **Write transaction (same connection).**
  1. `acquire_execution_claim` and the ledger insert. A duplicate operation key is refused before any mutation.
  2. `_lock_project_steps` takes `FOR UPDATE` on the Project and its steps.
  3. The precondition re-runs `verify_step_update` through `TransactionDetailReader`.
  4. The domain engine plans the transition, and the UPDATE is guarded by `status` and `version`.
  5. The STEP event is inserted, then the ledger result and claim completion. All of it commits together.
- **On any refusal or crash:** the transaction rolls back as a whole, the attempt is fenced with a REVOKED claim and settled FAILED, and it is never retried.

## 4. Execution receipt contract

The receipt is `step_update_receipt_v1`, stored in the run state under `merchant_step_update_receipt`. It is built **only from durable evidence** and is reproducible at any time with `attempt_evidence.step_update_receipt(repository, identity, step_id)`.

| Field | Source |
|---|---|
| `merchant_id`, `project_id`, `step_id` | STEP event row |
| `step_sequence` | `project_steps.sequence_number` |
| `previous_status` / `new_status`, `previous_version` / `new_version` | event `old_values` / `new_values` (versions must differ by exactly 1) |
| `event_id` | event row |
| `execution_attempt_id` | the claim and the ledger result must both name it |
| `operation_key` | trusted attempt identity |
| `transaction_id` | the PostgreSQL `xmin` shared by the ledger row, the claim row and the event row |
| `status`, `run_id`, `task_id`, `database_target` | the hook (`RECONCILED` or `UNRECONCILED`) |

`RECONCILED` requires all of the following:
- the claim is COMPLETED, and the claim and ledger carry the attempt's payload hash and attempt ID;
- exactly one STEP event for the step was written by the same transaction as the claim and ledger;
- the result equals the confirmed operation: Merchant, Project, step, sequence, current and target status, and step version.

An `UNRECONCILED` receipt is recorded as such and never changes the settled outcome. Committed evidence decides that outcome, and a teammate's success claim never does.

## 5. RED/GREEN

**New tests:**
- `tests/merchant/test_nl4c2a_step_execution.py`: 18 unit tests, no database.
- `tests/merchant/test_nl4c2a_step_execution_postgres.py`: 14 PostgreSQL end-to-end tests through the real hooks.

**RED** was run against the NL4C1 behaviour: this checkpoint's five source and test-infra files were rebuilt without the new wiring, then restored and checked with `cmp`.

| Suite | RED | GREEN |
|---|---|---|
| Unit | 14 failed, 4 passed | 18 passed |
| PostgreSQL | 13 failed, 1 passed | 14 passed |

The tests that passed under RED cover boundaries that already held in NL4C1:
- a relayed `UserPromptExpansion` without Submit;
- three prompts that try to replace the target ("…COMPLETED", "…database runtime", "…thành hoàn thành") are not confirmations;
- the database-level two-claims race.

**Phase 6 coverage:**

| Case | Test | Result |
|---|---|---|
| Duplicate confirmation | `…executes_once…` (replayed `/solve Xác nhận cập nhật`) | blocked; run unchanged |
| Replayed teammate message | `…replayed_execute_request…` | no second write; claim COMPLETED once |
| Concurrent execution / two claims for one operation | `…two_claims_for_one_step_operation…` (4 threads, same key) | exactly 1 write, 1 claim |
| State changed after confirmation (Project version, step version, dependency) | `…refused_before_any_spend[…]` | `PREFLIGHT:<reason>`; nothing spent or written |
| Change between preflight and write | `…refused_in_the_transaction` | in-transaction refusal; FAILED; fenced (REVOKED); nothing written |
| Crash before commit | `…crash_before_commit…` | full rollback; FAILED; fenced |
| Failed ledger/evidence persistence | `…failed_evidence_persistence…` | the UPDATE rolled back with the evidence; FAILED; fenced |
| Crash after commit, before result delivery | `…crash_after_commit…` | settled SUCCEEDED from evidence; receipt reproducible; retry writes nothing |
| Contradictory terminal result | `…executes_once…` (`EXECUTE_FAILED` after success) | denied; the consistent report releases |
| Stale execution state / missing pending record | `…missing_confirmation_record…`, unit `missing_store`, `damaged`, `another run/session` | `STEP_CONFIRMATION_REQUIRED`; unspent |
| Stale teammate definition | `…stale_teammate_definition…` | reuse refused; nothing spent or written |
| No verified pane identity | `…unverified_pane_cannot_execute` | nothing staged or spent; nothing written |
| Wrong target, replaced target status, edited version | unit `changed_scope_is_refused[…]`, `runtime_record_is_refused_unspent` | refused unspent |

**Intentional test updates** (both said "Step execution stays disabled", which NL4C2A changes on purpose):
- `test_nl2_project_create.py`: the TEST_MODE_COMMANDS set now includes `step update`.
- `test_nl4c1_step_confirmation.py`:
  - the disabled-confirmation test now uses a runtime-target record;
  - the preflight test is now runtime-only.

## 6. Full regression

- **Full pytest, run alone against the test database:** 4114 passed, 20 skipped, 1 xfailed, 0 failed (97 subtests passed), in 7 min 20 s.
  - That is NL4C1's 4083, plus 32 new tests, minus 1 because the NL4C1 disabled-preflight test now has one case instead of two.

- `python .claude/system_test.py`: ALL PASSED.
- Hook compile and import smoke (intent_gate, merchant_direct_handoff, merchant_pending_confirmation, merchant_preview_delivery, team_result_hook, policy_gate): OK.
- `git diff --check`: clean.
- Related PostgreSQL suites, run one after another: NL4C1 8, NL4B 8, NL3 2, NL2 11, all passed.

## 7. Test database integrity

- **Hash:** `1636f0cb9ac89532b4b4e70ff2759f71c4c6bf4990d9fd86a11dbaecb4c0809c` was identical before NL4C2A work, after the GREEN PostgreSQL runs, after RED, and after the full suite.
- **Leftovers:** 0 `PYTEST%` Merchants. Every NL4C2A fixture also asserts that no `PYTEST_NL4C2A_` Merchants and no `pytest:nl4c2a-scope:` claims remain.
- **Untouched:**
  - no manual cleanup was done;
  - the NL2/NL3 acceptance Projects and the 3 Projects / 2 Merchants in the base data were not touched;
  - the production database was never constructed: the e2e `isolated` fixture refuses any non-test repository.

**Isolation (Phase 7):**
- `tests/merchant/conftest.py` takes a session-level PostgreSQL advisory lock (`pg_try_advisory_lock(0x4E4C3443)`) on its own connection the first time a process constructs a test-role `MerchantRepository`.
- A second pytest process aborts with exit code 3 ("PostgreSQL tests must run sequentially") instead of interleaving its fixtures with ours. `…second_pytest_process_is_refused…` checks this.
- Threads inside one process are not serialized, which the concurrency tests rely on.

## 8. Remaining security risks

1. **Spent before dispatch.** The pending record is spent at confirmation (as in NL3). If dispatch is then refused (for example a stale teammate), nothing is written, but the user must preview again.
2. **Receipt on the normal path only.** The run-state receipt is written only on the normal success path. After a crash between commit and settlement, the attempt still settles SUCCEEDED from evidence, but the receipt has to be reproduced with `step_update_receipt`; TeammateIdle does not record it.
3. **Lead summary.** The receipt is not yet surfaced in the lead's final summary. The lead still summarizes from the teammate's evidence-checked report.
4. **Operation key is per run.** The operation key includes run and task, so a duplicate across runs is stopped by the step version and basis (re-judged in the transaction), not by the ledger key. Both stops are tested.
5. **Unlocked evidence reads.** Approval and procurement evidence is read in the transaction without row locks, as in the existing write path. A concurrent approval write could commit between the re-check and the commit.
6. **Lead and teammate wording.** It is still the NL4B wording ("Step Update confirmation does not exist yet"). The pipeline works when the user types the confirmation, but the agents will not offer it. The update is deferred so running teammates are not marked STALE_DEFINITION.
7. **Lock coverage.** The advisory lock covers only pytest processes that construct a test-role repository. A manual script or a live `/solve` on the test database is not blocked. With the test-database environment set but the database unreachable, test-role construction now fails at once.
8. **`xmin` reconciliation.** It relies on PostgreSQL MVCC. Any later UPDATE of the ledger or claim row would break the receipt's transaction match. None happens by design.

## 9. Controlled live acceptance prerequisites (NL4C2B)

1. You accept NL4C2A (and NL4C1) and authorize the commit separately.
2. Update `merchant-manager.md` and the `solve.md` NL4B section so that a READY **test-database** preview offers `/solve Xác nhận cập nhật [<step id>]`, with no argv or scope shown. Then start a fresh Claude Code session.
3. Use a designated throwaway Project on `coding_agent_merchant_test`, never the NL2/NL3 acceptance Projects. Take the integrity hash before and after.
4. One preview, one confirmation and one execution. Check:
   - the receipt is `RECONCILED`;
   - the claim is COMPLETED and exactly one STEP event exists;
   - the terminal report is consistent and the teammate is released IDLE_REUSABLE;
   - a replayed confirmation is refused.
5. Do not run any other PostgreSQL test process during the live run.
6. Runtime Direct EXECUTE stays disabled throughout.

## 10. GO/NO-GO

- **NL4C2A:** GO for your acceptance review.
- **NL4C2B (controlled live acceptance on the test database):** NO-GO until NL4C2A is accepted and prerequisites 2–3 are done.
- **Runtime/production Step Update:** NO-GO. It is outside this track and needs separate approval.

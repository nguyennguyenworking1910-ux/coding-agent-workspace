# CP12H.5C — Direct EXECUTE Result Consistency and Durable Recovery

- Date: 2026-10-30
- Branch: `feat/cp7-9-merchant-reliability`, baseline `011d29e`
- Not committed or pushed. No runtime database connection or write. Database work ran only on
  `coding_agent_merchant_test` as `merchant_test`.

| Decision | Verdict |
|---|---|
| Commit CP12H.5C | **GO**, after diff review (§8) |
| Runtime production Direct EXECUTE | **NO-GO**: still disabled in code (§9) |

F7 and F8 are not defined anywhere in the repository. This checkpoint uses the definitions in
the task:

- **F7:** a report's database target conflicts with the trusted authorization.
- **F8:** a committed write is presented as BLOCKED, FAILED or REQUIRES_CLARIFICATION.

## 1. Root causes and fixes

### F7 and F8: the report was never checked once a write existed

`teammate_idle_orchestrator` parsed `TEAM_RESULT_JSON` only on the no-write path. When a task
had a scoped execution or a Create reservation, idle settled it from evidence and released the
teammate without reading the report. As a result:

- **The lead got a contradictory report.** A teammate could report BLOCKED, FAILED or
  REQUIRES_CLARIFICATION for a committed write. The lead read that message and the teammate was
  still released. An existing test, `test_scoped_write_cannot_be_released_as_no_write`, asserted
  this behaviour.
- **No target check on the write path.** A report could claim `database_target: test` for a
  runtime write, or the reverse.
- **Uncertain was reported as failed.** The dispatcher told the teammate to report
  `EXECUTE_FAILED` for any unsuccessful attempt, including attempts that may have committed. The
  contract had no outcome for "may have committed".
- **A failed Create looped forever.** It stayed `EXECUTING`. Idle reconciliation found no
  evidence and returned PENDING on every idle, with no terminal state.

**Fix.** The trusted outcome is now derived from team-state evidence by
`merchant_terminal_consistency.direct_evidence_state`, which returns one of:

- `NO_WRITE`;
- `COMMITTED`: scope `SUCCEEDED`, or every Create write `VERIFIED`;
- `NOT_COMMITTED`: fenced or never executed;
- `UNCERTAIN`;
- `PENDING_VERIFICATION`.

Evidence bound to another run or task, or malformed, is `UNCERTAIN`.
`terminal_report_violation` accepts a report only when all of these hold:

| Evidence | Accepted outcomes |
|---|---|
| `NO_WRITE` | REQUIRES_CLARIFICATION, BLOCKED, FAILED |
| `COMMITTED` | **EXECUTE_SUCCESS only** |
| `NOT_COMMITTED` | EXECUTE_FAILED, EXECUTE_UNCERTAIN |
| `UNCERTAIN` / `PENDING_VERIFICATION` | **EXECUTE_UNCERTAIN only** |

- `database_target` equals the trusted target (**F7**).
- `operation` is `merchant_execute`.
- `command` equals the scope command.

The trusted target comes from this run's `merchant_scope`; the Stop hook keeps that run state
while a teammate owns the run. Without it, a Create write records its database. A task with no
write evidence can only have read runtime. A scoped write without its run state is unverifiable,
so it is rejected.

The check is enforced in two places:

1. **PreToolUse, before delivery.** `policy_gate` now runs `merchant_terminal_report_decision`
   on every `merchant-manager` `SendMessage` that carries `TEAM_RESULT_JSON`. A contradictory
   report is denied, so the lead never receives it. The check can only deny, never grant.

   An accepted report leaves a run/task-bound `direct_terminal_report` marker. The marker blocks
   any later execution for the task in three places:
   - the preflight, as `TERMINAL_REPORT_ALREADY_SENT`, before anything is spent;
   - `_begin_scope_execution`;
   - `reserve_merchant_create`.

   The last two run under the team-state lock that creates the write footprint. Because both the
   marker and the footprint are created under that lock, a no-write report and a write can never
   both happen, whatever the order of parallel tool calls.
2. **TeammateIdle, after evidence is settled.** The delivered report is checked again on every
   path:
   - **No-write path:** rejected reports use the existing one correction turn.
   - **Write paths:** use a new `claim_direct_report_correction`. The first contradiction gets a
     correction turn that names the violation. The second ends the task `FAILED` with reason
     `TERMINAL_REPORT_CONTRADICTS_EVIDENCE: …`, which names the evidence state, and the committed
     evidence is kept.
   - Unsettled writes are never "corrected".
   - The old rule that a write footprint never uses the no-write recovery turn is unchanged.

Other changes:

- **New outcome.** `EXECUTE_UNCERTAIN` was added to `team_result_contract`.
- **Dispatcher messages.** The dispatcher now takes the outcome the teammate must report from
  evidence (`direct_execution_evidence`), not from the CLI output. An uncertain attempt's message
  says that it may have committed.
- **Create verification.** A successful Create is verified against committed PostgreSQL evidence
  right after execution (`_verify_committed_create`), so the report can be checked at once. Idle
  verifies it again.
- **Failed Create.** A Create that reconciliation cannot verify is now fenced, and the task ends
  `FAILED`. The reason is `DIRECT_WRITE_NOT_COMMITTED`, or `DIRECT_WRITE_UNCERTAIN` when the fence
  cannot be placed. The reservation is kept. This fixes the loop.

### Phase 2: non-Create writes had no database evidence

**Inventory.** I ran an AST scan of each handler. All ten non-Create write commands open exactly
one read-write connection and one transaction:

- `contact import`, `document approve`, `document revision-create`,
  `integration identifier-set`;
- `merchant activate`, `merchant activate-all`;
- `procurement update`, `project create`, `project update`, `step update`.

Only `merchant create` had durable evidence, through the ledger and claim in `atomic_create`. A
scoped write's outcome came from the CLI exit code and its stderr error class alone.

**Design.** Implemented in `.claude/clients/merchant/attempt_evidence.py` and
`.claude/hooks/merchant_attempt_resolution.py`.

- **Attempt identity.**
  - **Operation key:** `merchant-scope:v1:sha256(owner, teammate, run, task, command,
    scope_hash)`. It excludes the attempt id, so a second attempt for the same operation collides
    in the database.
  - **Payload hash:** the scope hash, which binds the exact argv and target.
  - **Attempt id:** the `execution_attempt_id` that the spend and the `EXECUTING` record are
    already bound to.
- **Atomic evidence.** `evidence_bound_repository` wraps the repository's connection factory.
  The single outer read-write transaction then works as follows:
  1. It inserts the claim (`ACTIVE`) and the ledger row, all before the mutation.
  2. It runs the handler.
  3. It writes the ledger result and completes the claim, and then commits.

  The mutation and its evidence therefore commit or roll back together. A second write
  transaction for the attempt is refused (`EvidenceBindingError`). Read-only connections are
  untouched. The handoff passes this repository through the existing `write_command_factory`
  seam, so no repository code changed.
- **Idempotency and replay.** An existing claim or ledger row for the key refuses the
  transaction before the handler runs.
- **Recovery.** `resolve_attempt` returns:
  - `COMMITTED` only for the attempt's own completed claim with a matching ledger result;
  - `NOT_COMMITTED` only when a committed `REVOKED` fence owns the key, so the attempt can never
    commit later;
  - `UNCERTAIN` otherwise. This includes a fence blocked by an in-flight transaction (the
    5-second `lock_timeout`), an unreachable database, and a completed claim under another
    identity.

  The `REVOKED` status already exists in the schema, so no migration was needed.
- **When a fence is placed.** Only after the attempt's own connection has closed:
  - **Right after the attempt.** The CLI call returned or raised. The attempt is settled straight
    from `EXECUTING`, with a fence only when the CLI did *not* report success.
  - **At TeammateIdle.** The teammate's turn has ended. Only an attempt still `EXECUTING`
    (crashed) is fenced. An `UNCERTAIN` attempt is re-read but never fenced, because it may stand
    for a reported success whose evidence is missing.
- **No runtime fence.** A fence is a database write. Resolution never contacts the runtime
  database while `RUNTIME_DIRECT_EXECUTE_ENABLED` is False, even for an attempt left by an earlier
  version.
- **Identity preflight.** The read-only identity preflight now runs for scoped writes too
  (`_target_repository`).

`UNCERTAIN` still ends the task `FAILED`, with its evidence kept, and it is never released.
Nothing infers a rollback from a terminated caller.

Scoped writes now record `SUCCEEDED` or `FAILED` from database evidence, where before they used
the CLI exit code and error class. For example, a lost acknowledgement after commit now settles
as `SUCCEEDED` instead of `UNCERTAIN`.

### Phase 3: completed claims accumulating

Every suite run left two `pytest:` claims. `test_execution_evidence_postgres` and
`test_protected_merchant_create` deleted their ledger rows but not their claims. Both now delete
their claims.

Two more leaks came from my own work in this session; both are fixed and their rows removed.

- **Create end-to-end test.** It leaked its merchant and event whenever an assertion failed
  before it learned the merchant id, and that happened three times. Its cleanup now finds the
  merchant by its unique code.
- **Fence from a unit test.** A unit test fenced a real key in the test database before I added
  a guard. The new `tests/merchant/conftest.py` lets tests fence only `pytest:` keys.

**Retention policy**, implemented in `.claude/clients/merchant/claim_retention.py`:

- **Operational keys (`merchant-direct:`, `merchant-scope:`) are never swept.**
  - A `COMPLETED` claim is commit evidence and refuses replay of its key.
  - A `REVOKED` claim is a fence that keeps a stopped attempt from ever committing.
- **`ACTIVE` claims** never persist outside an open transaction.
- **`pytest:` keys.** `COMPLETED` or `REVOKED` rows older than the cutoff are swept.
  - The default cutoff is 1 day.
  - The sweep runs only after verifying `coding_agent_merchant_test` / `merchant_test`.
  - It is a dry run unless `--apply` is given.
  - It deletes and reports in one statement.

Command: `python -m claude.clients.merchant.claim_retention [--older-than-days N] [--apply]`.

**Applied on 2026-10-31 with your authorization: 125 `pytest:` claims deleted.**

- **Why 125, not 89.** When this report was first written, 89 of the 125 `pytest:` claims were
  older than one day. The other 36 were all updated on 2026-10-30 and have since passed the
  cutoff. No new claims were created in between.
- **Preconditions, all verified before `--apply`:**
  - effective identity `coding_agent_merchant_test` / `merchant_test`;
  - the dry run and an independent query of the same predicate both selected the same 125 keys;
  - every candidate was `pytest:` and `COMPLETED`, the newest last updated 2026-10-30 15:52;
  - no `ACTIVE` claims, and no `pytest:` claim outside the selection;
  - the claims table has no foreign keys or triggers, and the ledger was empty;
  - none of the 70 local team-state, run-state or receipt files referenced a `pytest:` key.
- **Result:** `deleted 125 test-data claim(s)`.
  - The deleted set equals the dry-run set exactly, and no rows were added.
  - Claims went from 141 to 16.
- **Preserved:** the **16 historical `merchant-direct:` claims** (CP12H.5B.1, §7.4) are unchanged
  in every field. All 16 other `merchant_ops` tables kept the same row count and content checksum.
  Deleting the 16 historical claims still needs your explicit authorization.

## 2. Tests added

`tests/merchant/test_cp12h5c_correctness_and_recovery.py` has 43 tests, using the in-memory
evidence model with no database:

- **Evidence classification.** Each scope status; Create `VERIFIED`, `RESERVED` and `EXECUTING`;
  stale-task evidence becoming `UNCERTAIN`; spent authority without evidence becoming
  `UNCERTAIN`.
- **Decision table:**
  - a committed write rejects BLOCKED, FAILED, REQUIRES_CLARIFICATION, EXECUTE_FAILED and
    EXECUTE_UNCERTAIN;
  - EXECUTE_SUCCESS is rejected for `NO_WRITE` (a replayed success), `NOT_COMMITTED`, `UNCERTAIN`
    and `PENDING_VERIFICATION`;
  - EXECUTE_FAILED and BLOCKED are rejected for `UNCERTAIN`;
  - **F7** in both directions (test→runtime and runtime→test), on no-write and committed
    evidence;
  - a wrong command, missing authorization, and a missing result.
- **Binding sources.** Binding from run state or from write evidence; another run's scope never
  binds.
- **Real PreToolUse gate (`policy_gate.main`):**
  - F8: five contradictory outcomes are denied before delivery, and no marker is left;
  - F7: a wrong target is denied;
  - an uncertain write must be reported `EXECUTE_UNCERTAIN`;
  - a lost acknowledgement after commit is settled as committed;
  - an accepted no-write report forbids a later execution (no call, nothing spent);
  - a replayed success into a new no-write run/task is denied at PreToolUse and rejected at idle.
- **TeammateIdle re-check.** A contradictory report gets one correction, then the task fails
  with the contradiction disclosed and the evidence kept. A wrong-target report is never released
  until corrected.
- **Crash recovery:**
  - after commit, it recovers `SUCCEEDED`, and the uncertain report must be corrected to success;
  - before commit, it is fenced to `FAILED`;
  - with an unplaceable fence, it stays `UNCERTAIN`;
  - a runtime attempt is never fenced while runtime is disabled.
- **Dispatcher message.** It names `EXECUTE_UNCERTAIN` and says "may have committed".

`tests/merchant/test_cp12h5c_attempt_evidence_postgres.py` has 10 tests on the **real test
database**:

- the mutation and its evidence commit together;
- a failed mutation rolls back its evidence, then a fence settles it, and the fenced attempt can
  never commit;
- a replay never writes twice;
- a second write transaction is refused;
- **a real subprocess crash** before commit (`os._exit` inside the transaction) is fenced as
  `NOT_COMMITTED`;
- **a real subprocess crash** after commit recovers as `COMMITTED`;
- a fence against an **in-flight transaction** in another thread returns `UNCERTAIN`, and the
  attempt is `COMMITTED` after it commits;
- the handoff's real `_scope_write_commands` factory commits atomically and refuses a replay;
- the retention sweep touches only aged `pytest:` rows and never a `merchant-direct:` fence;
- the retention sweep refuses any database except the test database.

**Updated existing tests** (each change reflects a deliberate behaviour change):

- The F8 tests now expect a committed write's BLOCKED report to be rejected, then corrected.
- Scoped-failure tests now model database evidence: a fence placed means `FAILED`; a fence
  blocked means `UNCERTAIN`.
- An unparseable success with committed evidence is `SUCCEEDED`. One without evidence is
  `UNCERTAIN` and never fenced.
- An unverified executing Create now ends `FAILED`/`DIRECT_WRITE_UNCERTAIN` instead of looping.
- The Create end-to-end test expects `VERIFIED` right after execution.
- Two test fixtures were made realistic: plain-text reports became valid `TEAM_RESULT_JSON`, and
  spent authority now carries its scope.
- `EXPECTED_TOTAL_FIELDS` went from 86 to 91, for five new dependencies:
  - the report check;
  - scope settlement;
  - the unverified Create ending;
  - the report correction;
  - the dispatcher evidence.

**RED/GREEN.** A behaviour probe ran in a baseline worktree, with `claude` shimmed to the
baseline `.claude`:

| Probe | Baseline `011d29e` | Working tree |
|---|---|---|
| BLOCKED report for a committed write is not released (F8) | **FAILED** | passed |
| Wrong-target report for a committed write is not released (F7) | **FAILED** | passed |
| Contradictory report denied before delivery (F8) | **FAILED** | passed |
| Unverified Create ends instead of looping | **FAILED** | passed |

## 3. PostgreSQL evidence

All of this ran on `coding_agent_merchant_test` / `merchant_test`; every session verified the
identity first.

- **Integration results.** All tests pass with real rows. A committed attempt has one
  `COMPLETED` claim with its own attempt id, plus a ledger result carrying that attempt id. A
  fenced attempt has one `REVOKED` claim and no merchant row.
- **Crash results.** The crash-before-commit child exited with code 17 inside the transaction.
  Its rows were rolled back by PostgreSQL, and the fence then settled it. The crash-after-commit
  child exited with code 18 after commit and was recovered as committed.
- **Final state after two full suite runs:**
  - merchants: 1 (`TEST_CLI_20260915110525`, pre-existing);
  - ledger: 0;
  - claims: 16 `merchant-direct:` `COMPLETED` (historical, untouched) and 125 `pytest:`
    `COMPLETED` (since swept; see §1, Phase 3);
  - **0 claims created** during the two final full runs, so the leaks are fixed.
- **Final acceptance run (2026-10-31).** Snapshots of the test database were taken before and
  after the full suite, and every check passed:
  - still 16 claims, all `merchant-direct:` `COMPLETED`, every field identical;
  - no `ACTIVE`, `REVOKED` or uncertain claims, and no claims added;
  - ledger still 0;
  - no change in row count or content checksum for any of the 16 `merchant_ops` tables.
- **Rows I removed** (each was this session's own test artifact, confirmed before deletion):
  - one `REVOKED` fence for the fake key `merchant-direct:v1:aaa…`;
  - three `CP12H3 E2E` merchants and their three project events.
- **Runtime database:** never connected.

## 4. Unsupported recovery cases

- **A write that bypasses the evidence-bound connection.**
  - **Assumption:** every read-write connection a write handler opens comes from the bound
    repository. All ten handlers satisfy this today.
  - **Mitigation:** an attempt that reports CLI success without evidence stays `UNCERTAIN` and
    is never fenced.
  - **Remaining case:** a *crashed* attempt is fenced at idle. A commit that bypassed the binding
    and then crashed would wrongly settle as `NOT_COMMITTED`. A new handler using a second
    connection or a non-repository path would break this assumption.
- **Multi-transaction commands.** None exist. One would be refused at its second transaction,
  after its first transaction had already committed with evidence, which would be a partial
  write. Such a command must stay single-transaction or be split into separate scopes.
- **Unplaceable fence.** If the database is unreachable or another transaction holds the key
  past the lock timeout, the attempt stays `UNCERTAIN` and ends `FAILED`. Nothing retries it
  later automatically; a later manual `resolve_attempt` could settle it.
- **Scoped write without run state.** It cannot be bound to a target and is not settled. This
  only happens if a new prompt replaced the run state while the task was running.
- **Report/write race.** If parallel tool calls run the report's PreToolUse before the execute
  request's PostToolUse, the marker blocks the execution: the report wins. The reverse order is
  the normal path.
- **No live run of non-Create scoped writes.** Test mode is still Create-only, and runtime is
  disabled. The non-Create evidence path is verified by tests on the real test database and real
  handlers, not by a live `/solve` run.

## 5. Full regression results

| Check | Result |
|---|---|
| Full suite (run 1) | 3406 passed, 20 skipped, 1 xfailed |
| Full suite (run 2, after the final runtime-fence guard) | 3406 passed, **1 failed**, 20 skipped, 1 xfailed |
| **Full suite, final acceptance (2026-10-31)** | **3407 passed, 0 failed, 20 skipped, 1 xfailed**, 97 subtests passed (159 s) |
| Merchant and lifecycle suites | 2653 passed |
| CP12H.5C correctness + PostgreSQL, final | 53 passed (43 + 10) |
| `python .claude/system_test.py` | All passed (100%) |
| `git diff --check` | Clean (only Git's CRLF→LF notices on files that were already CRLF in the working copy) |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` |
| `TEST_MODE_COMMANDS` | `{merchant create}` |

**Why the final count is 3407, not 3406.** Run 1 came before the final runtime-fence guard test
was added. Run 2 collected the same 3,428 tests as the final run: 3406 passed and 1 failed. In
the final run that test passes too, so the count is complete with nothing missing.

- **Skipped (20):** all opt-in live suites.
  - 10 need `MERCHANT_RUN_RUNTIME_*`; these are runtime-only and were deliberately not enabled.
  - 10 need `MERCHANT_RUN_LIVE_TESTS`; these are older test-database lifecycle suites.
- **Expected failure (1):** `test_reserved_execution_toctou.py::test_reassignment_between_validation_and_write`,
  the known TOCTOU case, unchanged.

The baseline before this checkpoint was 3352 passed.

### Intermittent Windows atomic-save failure

**Failing test:** `tests/test_team_lifecycle.py::AtomicTeamStatePersistenceTests::test_save_uses_a_unique_temporary_name_in_the_destination_directory`.
It failed once, in run 2, with `ValueError: too many values to unpack (expected 2)`.

**Root cause: a fragile test assertion, not a production defect.**

- The test wraps `os.replace` and records each call *before* delegating to the real
  `os.replace`.
- When Windows holds a transient handle on the state file (antivirus or the search indexer),
  the real call raises `PermissionError`.
- `replace_with_retry` correctly retries that, by design and as tested elsewhere.
- So the wrapper records three calls for two saves, and `first, second = observed` fails.

**Reproduction.** A scratch harness ran the unmodified test method 300 times each way.

| Condition | Result |
|---|---|
| No contention | 300 of 300 passed |
| Another thread briefly holding a read handle on the state file (2 ms hold, 20 ms gap) | the same `ValueError` 170 times out of 300 |
| Production `save_team_state`, same contention, 200 saves | 200 of 200 wrote the correct content; no errors; no leftover `.tmp` files |

**Unrelated to CP12H.5C.**

- `tests/test_team_lifecycle.py` is unmodified.
- The first diff hunk in `team_lifecycle.py` is at line 1298. `replace_with_retry` and
  `save_team_state` (lines 345–395) are byte-identical to `011d29e`.

**Repeated runs on the final tree:**

- standalone, 50 separate pytest runs: 50 passed;
- with `test_team_lifecycle.py`, `test_merchant_direct_lifecycle_fencing.py` and
  `test_tmux_multi_role_lifecycle.py`, 10 runs: 69 passed in each;
- full suite: passed.

The test was not suppressed, deleted or marked xfail. Its fix belongs in a separate change: record
a replace only after the real `os.replace` succeeds, or assert on distinct sources. It is not
included in this checkpoint.

## 6. Files changed

**New modules**

- `.claude/clients/merchant/attempt_evidence.py`: evidence-bound transaction, `resolve_attempt`,
  and the fence.
- `.claude/clients/merchant/claim_retention.py`: the test-data claim sweep.
- `.claude/hooks/merchant_attempt_resolution.py`: scope attempt identity, settlement, the
  unverified Create ending, and the runtime no-fence guard.
- `.claude/hooks/merchant_terminal_consistency.py`: the evidence classifier, the report check,
  binding, the PreToolUse decision, and the marker.

**Modified hooks**

- `merchant_direct_handoff.py`:
  - evidence-bound scoped writes, settled from the database;
  - identity preflight for every command;
  - the report-marker preflight;
  - immediate Create verification;
  - `direct_execution_evidence`.
- `merchant_direct_write_state.py`: the marker check under the reservation lock.
- `policy_gate.py`: the PreToolUse report gate.
- `team_lifecycle.py`:
  - `claim_direct_report_correction`;
  - `end_unverified_direct_create`;
  - the new markers, cleared alongside the no-write marker.
- `team_result_contract.py`: `EXECUTE_UNCERTAIN`.
- `team_result_dispatcher.py`, `team_result_dependency_protocols.py`: messages from evidence.
- `team_result_hook.py`: dependency wiring.
- `teammate_idle_orchestrator.py`: report check on every Direct path, scope settlement, the
  Create ending, and the write-path correction.

**Docs:** `CLAUDE.md`, `.claude/commands/solve.md`, `.claude/agents/merchant-manager.md`.

**Tests**

- New:
  - `tests/merchant/conftest.py`;
  - `test_cp12h5c_correctness_and_recovery.py`;
  - `test_cp12h5c_attempt_evidence_postgres.py`.
- Modified:
  - `direct_reservation_support.py`;
  - `test_cp12h4_write_boundary.py`;
  - `test_direct_execute_end_to_end.py`;
  - `test_direct_idle_delivery.py`;
  - `test_direct_no_write_terminal_gate.py`;
  - `test_execution_evidence_postgres.py`;
  - `test_protected_merchant_create.py`;
  - `test_reserved_execution_e2e.py`;
  - `tests/test_team_result_dependency_type_precision.py`.

Totals: 21 tracked files changed (751 insertions, 142 deletions), plus 7 new files and this
report.

**Exact inventory against `011d29e`** (`git status --short`, final acceptance):

```text
 M .claude/agents/merchant-manager.md
 M .claude/commands/solve.md
 M .claude/hooks/merchant_direct_handoff.py
 M .claude/hooks/merchant_direct_write_state.py
 M .claude/hooks/policy_gate.py
 M .claude/hooks/team_lifecycle.py
 M .claude/hooks/team_result_contract.py
 M .claude/hooks/team_result_dependency_protocols.py
 M .claude/hooks/team_result_dispatcher.py
 M .claude/hooks/team_result_hook.py
 M .claude/hooks/teammate_idle_orchestrator.py
 M CLAUDE.md
 M tests/merchant/direct_reservation_support.py
 M tests/merchant/test_cp12h4_write_boundary.py
 M tests/merchant/test_direct_execute_end_to_end.py
 M tests/merchant/test_direct_idle_delivery.py
 M tests/merchant/test_direct_no_write_terminal_gate.py
 M tests/merchant/test_execution_evidence_postgres.py
 M tests/merchant/test_protected_merchant_create.py
 M tests/merchant/test_reserved_execution_e2e.py
 M tests/test_team_result_dependency_type_precision.py
?? .claude/clients/merchant/attempt_evidence.py
?? .claude/clients/merchant/claim_retention.py
?? .claude/hooks/merchant_attempt_resolution.py
?? .claude/hooks/merchant_terminal_consistency.py
?? cp12h5c_correctness_and_recovery.md
?? tests/merchant/conftest.py
?? tests/merchant/test_cp12h5c_attempt_evidence_postgres.py
?? tests/merchant/test_cp12h5c_correctness_and_recovery.py
```

There are no other modified or untracked files. All 29 belong to CP12H.5C.

## 7. Remaining security limitations

- **Same-user trust boundary (unchanged).** Any same-user process that can run arbitrary Python
  can reach the credentials, edit team state or write the database directly. The PreToolUse
  report gate relies on the harness-reported `agent_type`. It can only deny; it never grants.
- **The report can still misdescribe the write in prose.** It is checked only through its
  `TEAM_RESULT_JSON` fields. The lead should treat the structured outcome, and for
  `EXECUTE_UNCERTAIN` the words "may have committed", as authoritative.
- **The evidence-binding assumption** in §4 carries the crash-recovery guarantee for non-Create
  writes. At final acceptance it holds for all ten non-Create commands. Each maps to exactly one
  repository write method, and each such method opens one connection from the shared (bound)
  repository and mutates only inside `connection.transaction()`. No method commits outside a
  transaction or builds its own repository or connection.

  | Command | Repository write method |
  |---|---|
  | `contact import` | `merchants.import_contacts` |
  | `document approve` | `approvals.record_approval` |
  | `document revision-create` | `documents.create_revision` |
  | `integration identifier-set` | `identifiers.set_identifier` |
  | `merchant activate` | `merchants.activate_merchant` |
  | `merchant activate-all` | `merchants.activate_merchants_batch` |
  | `procurement update` | `procurement.record_procurement` |
  | `project create` | `workflows.create_project` |
  | `project update` | `projects.transition_project` |
  | `step update` | `steps.transition_step` |

  **This verification is structural, from an AST map of the adapters plus inspection of the
  repositories.** The bound wrapper itself is tested on PostgreSQL: atomic commit, rollback,
  replay refusal, second-transaction refusal and real crashes. But that real-database factory test
  drives `merchant create`. No test runs each of the ten non-Create commands individually against
  the database. A per-command test, or a structural regression test, is a recommended follow-up.
- **`tests/test_team_lifecycle.py` atomic-save test is fragile on Windows** (§5). It is a test
  defect, not a production one, and it is not fixed in this checkpoint. Expect an occasional
  `ValueError` failure in that test until it is fixed separately.
- **Ten test-database lifecycle suites** (`MERCHANT_RUN_LIVE_TESTS`) stay opt-in and were not run
  at final acceptance.
- **Fences and committed claims are permanent by design.** Removing one reopens replay of its
  key.
- **Earlier limits still apply:** the `leadProcess` harness dependency, pane identity limits
  (CP12H.5B §4), and Create-only test mode.

## 8. GO / NO-GO: commit this checkpoint

**GO**, once you have reviewed the diff.

- F7 and F8 are fixed at both boundaries and covered by RED/GREEN tests.
- Non-Create writes now have atomic, replay-safe evidence and fence-based recovery, tested with
  real crashes on the test database.
- The leaks are fixed and a retention mechanism exists.
- No existing authorization, completeness, reservation or committed-evidence check was weakened.
  Several are stricter now: the report check, the marker, preflight for scoped writes, and no
  runtime fence.
- The final full suite is green: 3407 passed, 0 failed, 20 skipped, 1 xfailed. The one earlier
  failure is a fragile Windows test assertion outside this checkpoint (§5). It is reproduced and
  explained, and it was not suppressed.
- The test database is isolated:
  - the full suite left no residue;
  - only the 16 historical `merchant-direct:` claims remain, unchanged;
  - there are no active or uncertain claims;
  - the runtime database was never connected.
- The `pytest:` claim sweep is applied: 125 deleted.

**Staged for commit** (not committed): the 21 modified files, the 7 new files and this report.
One decision is still yours: whether to delete the 16 historical `merchant-direct:` claims.

## 9. GO / NO-GO: runtime production Direct EXECUTE

**NO-GO.** `RUNTIME_DIRECT_EXECUTE_ENABLED = False` is unchanged, and resolution now also
refuses to touch the runtime database while it is disabled.

Enabling it requires all of the following:

- separate approval;
- confirming the runtime `merchant_app` role can insert and update `merchant_execution_claims`
  and `merchant_execution_ledger`, which the evidence-bound transaction now needs for scoped
  writes;
- a runtime identity preflight in a controlled window;
- a live `/solve` validation of a non-Create scoped write, which test mode cannot exercise today.

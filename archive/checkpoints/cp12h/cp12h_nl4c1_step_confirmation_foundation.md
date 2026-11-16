# CP12H.NL4C1 — Trusted Conversational Step Confirmation Foundation

> **Final NL4C status (committed together as `feat(merchant): enable trusted test-only step updates`).**
> - **Execution:** Step Update runs **only on the test database** (`coding_agent_merchant_test`), only from the user's own `/solve Xác nhận cập nhật` of a verified preview. **Production (runtime) Direct EXECUTE is disabled in code** (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`).
> - **Automated regression:** the final full suite is in the NL4C commit summary.
> - **Live acceptance:** one user-confirmed Step Update (step 1 READY → IN_PROGRESS of Project `8dd4c68d-…`) returned EXECUTE_SUCCESS, and an **independent read-only PostgreSQL verification** found it EXECUTED_AND_VERIFIED (`cp12h_nl4c2b_live_acceptance.md`).
> - **`confirmation_available`:** `true` only for a READY test-database preview. It means the user may confirm; it never means a write is authorized. This supersedes any "always false" wording below.
> - **Known limitations:** see the "Remaining risks" section of each report.

Baseline `578790c1349a082908a3e6404b76754eb5330248`, branch `feat/cp7-9-merchant-reliability`.
Date 2026-11-06. Not committed, not pushed. No live Step Update was performed.

## 1. Architecture audit

| Area | Finding | Decision |
|---|---|---|
| NL4B `step preview` | It already applies the write path's own checks to a read snapshot: the transition table, dependency readiness, the stored-evidence gate and `propose_step_transition`. | Reused unchanged as the judge. Added a basis hash and `requested_operation`. |
| `transition_step` (write) | Under lock it already re-checks the step version (`expected_version`), the transition, dependencies and the gate. It does not bind the Project version, the dependency graph, other steps or the Merchant. | Added an optional `precondition(connection)`. It runs after the Project and step locks and before any change. |
| NL3 pending store | File-locked records with owner, TTL and a single-use spend, a strict phrase parser, scheduled-prompt denial and bare-phrase guidance. | Reused the machinery with a `kind` dimension. Step records live in a separate file. |
| NL3 gate confirmation | Turns a record into an ordinary `merchant_scope` and envelope. | Factored out as `_conversational_scope`, shared by the Project and Step paths. |
| Scope validation and hashing | `validate_direct_scope` already hashes argv plus target. A Project preview requires canonical argv. | Added the same canonical-argv rule for a preview-bound `step update`. |
| Direct EXECUTE preflight | Runtime is disabled. Test mode allows only `merchant create` and `project create`. A Project preview is re-verified before spend. | Added a Step re-verification before spend. Added `direct_execute_enabled()`, the single switch the gate also uses. Nothing was enabled. |
| Claims, ledger and recovery | Non-Create writes go through `invoke_authorized_scope_apply`, with the claim and ledger in the mutation transaction. | Unchanged. This is the path NL4C2 must exercise for `step update`. |

## 2. Security model

1. **Preview (read).** A READY preview carries `requested_operation`, with `status: NOT_AUTHORIZED`. `executable` and `confirmation_available` stay false, and `authorization` stays null.
2. **Trusted creator.** Only `record_read_evidence`, the PostToolUse(Bash) hook, creates a pending Step record. It does so only for a capture that meets all of these:
   - the exact CLI JSON of `step preview`;
   - from merchant-manager's verified pane;
   - on the trusted target;
   - READY with exactly one valid operation, whose target equals the capture's.

   If READY lacks an operation, a non-READY outcome carries one, or the operation is forged or retargeted, the capture is UNVERIFIED and nothing is recorded. No model, teammate message or prompt can create or edit a record.
3. **Store.** Step records go to `<session>.pending_step.json`, separate from `.pending_project.json`. Each record has an owner session, a 15-minute TTL and single use (the status changes under a file lock). A Project record can never confirm a Step, and the reverse.
4. **Confirmation.** The whole prompt must be exactly `/solve Xác nhận cập nhật [<step-id prefix>]` (also `Confirm update [step <id>]`; cancel with `Hủy cập nhật` / `Cancel update`):
   - Any extra word ("thành COMPLETED", "trên database runtime", "và xóa …") means it is not a confirmation, and it is classified normally (external_write, `--confirm` required, no scope).
   - The step, target status, Project and database target all come from the record. The prompt only picks which record.
   - A bare phrase without `/solve` gets guidance only.
   - A `CronCreate`, `ScheduleWakeup` or `RemoteTrigger` prompt carrying it is denied.
5. **Execution switch.** `direct_execute_enabled("step update", target)` is false for both targets. While it is false, the gate refuses the confirmation through `resolve(..., allowed=...)` before the status change, so the record stays PENDING until it expires. NL4C2 enables it only by adding `step update` to `TEST_MODE_COMMANDS`.
6. **Re-judgement.** `verify_step_update` runs in two places:
   - before any spend, in `preflight_direct_execute` via `_verify_step_preview`;
   - inside the write transaction, after the Project and its steps are locked, via the `transition_step` precondition and a `TransactionDetailReader` on the same connection.

   It refuses with:
   - `STEP_BASIS_REQUIRED`: no project_id, merchant_code or basis. A bare `step update` scope can never skip the re-check.
   - `MERCHANT_MISMATCH`, `STEP_NOT_IN_PROJECT` or `STEP_VERSION_CHANGED`.
   - `STEP_NOT_READY`: the transition, dependencies, approval gate or domain planner now block.
   - `STEP_BASIS_CHANGED`: anything else in the snapshot changed.

   Any other exception in preflight is refused as `STEP_PREVIEW_UNVERIFIABLE`.

## 3. Operation contract (`requested_operation`, `command: "step update"`)

| Field | Meaning |
|---|---|
| `status` | Always `NOT_AUTHORIZED`. |
| `database_target` | `test` or `runtime`, from the preview's trusted target. |
| `merchant_id`, `merchant_code` | The Project's Merchant. The code is re-checked as a confirmation of the Merchant. |
| `project_id`, `project_title`, `project_version` | The Project. The title keeps UTF-8. |
| `step_id`, `step_sequence`, `step_name`, `step_version` | The step. |
| `current_status`, `target_status` | The transition. Both must be known step statuses, and they must differ. |
| `expected_basis` | sha256 of the judged snapshot (below). |
| `argv` | Canonical and fixed order: `step update <step_id> --status <T> --expected-version <v> --project-id <P> --merchant-code <C> --expected-basis <H>`. |
| `note` | "Data, not authority…" |

**Basis.** The basis is the sha256 of the following, as sorted-key JSON:
- the step id and target status;
- the whole Project row, including version, status, Merchant code, name and account status;
- every row of `steps`, `dependencies`, `document_revisions`, `document_approvals` and `procurement_records` for the Project.

Contacts and integration identifiers are excluded. Any change to the Project version, a Step version, the dependency graph, another step or approval evidence invalidates it.

`validate_step_operation` rejects:
- truncated, edited, retargeted or no-op operations;
- non-canonical UUIDs or argv;
- a non-positive or boolean version.

`validate_direct_scope` accepts a preview-bound `step update` scope only as that exact argv; an extra `--allow-reopen` or reordered fields are rejected.

## 4. Files

| File | Change |
|---|---|
| `.claude/agents/tools/merchant/step_preview.py` | `_skeleton`, `requested_operation` on READY, `step_basis_hash`, `canonical_step_argv`, `validate_step_operation`, `verify_step_update`, `StepPreviewMismatch`. |
| `.claude/agents/tools/merchant/cli.py` | `step update` accepts `--project-id`, `--merchant-code` and `--expected-basis`, which go into the payload only when given. |
| `.claude/agents/tools/merchant/write_adapters.py` | `update_step` passes the in-transaction precondition when the payload has a basis. |
| `.claude/clients/merchant/transition_repository.py` | `transition_step(precondition=...)`, run after the locks and before any change. |
| `.claude/clients/merchant/read_repository.py` | `project_detail_in(connection, …)`, the same detail read on a caller's transaction; `TransactionDetailReader`. |
| `.claude/system/merchant_runtime_handoff.py` | `_require_canonical_step_argv` for preview-bound Step scopes. |
| `.claude/hooks/merchant_direct_handoff.py` | `STEP_UPDATE_COMMAND`, `direct_execute_enabled()`, `_verify_step_preview` in the preflight. `TEST_MODE_COMMANDS` and `RUNTIME_DIRECT_EXECUTE_ENABLED = False` are unchanged. |
| `.claude/hooks/merchant_pending_confirmation.py` | `kind` (project or step) stores, `record_pending_step`, `parse_step_confirmation`, `resolve(kind, allowed)`, Step guidance and scheduled denial. The Project behaviour and messages are unchanged. |
| `.claude/hooks/merchant_preview_delivery.py` | Checks Step-capture consistency and calls `record_pending_step` for VERIFIED READY captures. |
| `.claude/hooks/intent_gate.py` | `confirm_pending_step` and the shared `_conversational_scope`; a Step `systemMessage`. |
| `CLAUDE.md` | One paragraph on the NL4C1 foundation and the disabled execution. |
| `tests/merchant/test_nl4b_step_preview.py`, `test_nl4b_fix2_clarification_and_dependencies.py` | Intentional changes: a READY preview now carries a NOT_AUTHORIZED operation, and non-READY previews carry `requested_operation: null`. The `confirmation_command`, `--merchant-scope` and "pending" text are still forbidden. |
| `tests/merchant/test_nl4c1_step_confirmation.py` | New: 61 unit tests. |
| `tests/merchant/test_nl4c1_step_confirmation_postgres.py` | New: 8 PostgreSQL integration tests. |

`merchant-manager.md` was deliberately not changed, so live teammates keep a current definition fingerprint.

## 5. RED / GREEN

- **RED 1** (all 10 source files at HEAD, new tests kept): both new files fail at collection with `ImportError: StepPreviewMismatch`.
- **RED 2** (new `step_preview.py` kept; the 9 wiring files at HEAD: gate, store, delivery, preflight, scope, CLI, adapter, transition, read repository): **41 failed, 13 errors, 15 passed**.
  - The 15 that pass are the pure operation-contract tests, plus "execution stays disabled", which already held at HEAD.
  - The failures cover every confirmation, replay, expiry, session, ambiguity, scope, target, capture, re-judgement, concurrency and crash test.
  - In RED 2 the PostgreSQL tests applied transitions without the re-check, to disposable fixtures only. Those were deleted, and the DB hash was verified unchanged afterwards.
- Sources were restored byte-identical from backups (checked with `cmp`).
- **GREEN:** 61/61 unit tests and 8/8 PostgreSQL tests pass.

Coverage map of the spec's test list:

| Required | Tests |
|---|---|
| Valid confirmation | `test_valid_confirmation_yields_the_recorded_scope`, PG `test_unchanged_confirmation_applies_exactly_the_previewed_transition` |
| Ambiguous | `test_ambiguous_confirmation_names_the_choices_and_an_id_picks_one` |
| Expired / replayed | `test_expired_confirmation_is_refused`, `test_replayed_confirmation_is_refused`; in PG, a second apply is refused |
| Wrong session | `test_wrong_session_cannot_confirm` |
| Changed Project version | unit `test_changed_state_is_refused`, PG `[project-version]` |
| Changed Step version | unit and PG `[step-version]` |
| Changed dependencies | `test_changed_dependencies_are_refused`, PG `[dependency-graph]`, `[other-step]` |
| Invalid transitions | `test_blocked_and_clarifying_previews_carry_no_operation`, `STEP_NOT_READY` cases, `test_target_status_cannot_be_swapped_under_the_same_basis` |
| Missing evidence | `test_missing_evidence_is_refused[*]`, preflight `STEP_BASIS_REQUIRED` |
| Approval bypass | `test_approval_gate_evidence_is_bound_and_cannot_be_bypassed`, `test_gate_without_database_evaluator_never_yields_an_operation` |
| Mixed requests | `test_mixed_request_never_confirms`, `test_edited_confirmation_is_not_a_confirmation` |
| UTF-8 titles | operation tests (`Beta Nguyễn Văn Cừ`), the `systemMessage` check, the PG fixture title `… Nguyễn Văn Cừ` |
| Scheduled prompts | `test_scheduled_confirmation_prompts_are_denied` |
| Target substitution | `test_edited_operations_are_rejected[database_target]`, `test_database_target_is_bound_into_the_scope_hash`, a forged-target capture recorded as UNVERIFIED |
| Concurrency | `test_concurrent_confirmations_spend_once` (8 threads), PG `test_concurrent_applies_of_one_confirmation_write_once` (4 threads, 1 write) |
| Crash recovery | `test_crash_after_spend_never_restores_the_record`, PG `test_crash_inside_the_write_transaction_leaves_nothing` |
| No production write / no live Step Update | `test_confirmation_is_refused_unspent_while_execution_is_disabled`, `test_step_update_execution_stays_disabled[test,runtime]` |

## 6. PostgreSQL integration (`coding_agent_merchant_test`, run alone)

- **Fixtures.** Disposable `PYTEST_NL4C1_` Merchant and Project, created and deleted per test.
- **Write path.** Transitions run only on those fixtures, through the real `step update` adapter and `transition_step`. Nothing ran through `/solve`, and the NL2 and NL3 acceptance Projects were not touched.
- **Results:**
  - an unchanged confirmation applies READY→IN_PROGRESS once, with one event;
  - Project version, Step version, another step and dependency-graph changes are each refused inside the transaction with nothing written;
  - the preflight accepts unchanged state, then refuses a missing basis and a changed basis;
  - 4 concurrent applies produce exactly one write;
  - a crash after the UPDATE and before commit rolls back completely.
- **Integrity hash.** `1636f0cb9ac89532b4b4e70ff2759f71c4c6bf4990d9fd86a11dbaecb4c0809c`, the same as the NL4B baseline. It was identical:
  - before NL4C1 testing;
  - after the GREEN PostgreSQL run;
  - after the RED 2 run;
  - after the final full suite.
- **Row counts.** 2 merchants, 3 projects, 70 steps, 7 events, 18 claims, 2 ledger rows, 0 `PYTEST%` merchants. No manual cleanup was performed.

## 7. Full regression (final working tree)

- **Full suite**, DB-backed, alone, with runtime credentials blanked: **4083 passed, 20 skipped (MERCHANT_RUN_* opt-ins), 1 xfailed, 0 failed**. That is 4014 at NL4B plus the 69 new tests.
- **Without databases** (an earlier run): 3928 passed, 0 failed.
- `python .claude/system_test.py`: ALL TESTS PASSED.
- `git diff --check`: clean.
- **Hook import smoke** (`intent_gate`, `policy_gate`, `merchant_preview_delivery`, `merchant_direct_handoff`): OK.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`, and `TEST_MODE_COMMANDS` is unchanged (`merchant create`, `project create`).

## 8. Remaining risks

- **Pending records are now created live.** A READY Step preview in a live session writes a pending record. It cannot be spent while execution is disabled; it expires after 15 minutes.
- **Strict basis.** The basis is deliberately strict. Any change to a revision, approval or procurement row of the Project invalidates the confirmation, even an unrelated one. That fails closed and needs a fresh preview.
- **Unlocked gate evidence.** The precondition reads dependencies and gate evidence inside the transaction but does not lock them. Only the Project and step rows are locked, which is the existing `transition_step` behaviour. A concurrent approval withdrawal committed between the re-check and the commit is not excluded. The step-version guard and the Project lock cover the step itself.
- **Claim and ledger path untested for Steps.** The claim/ledger and uncertain-outcome recovery for `step update` through `invoke_authorized_scope_apply` is unchanged and was not exercised end to end for Steps. Execution is disabled, so that is NL4C2 scope.
- **Teammate and lead wording.** The teammate and the lead have no wording for offering a Step confirmation. That is deliberate while it is disabled, and needs NL4C2 changes to `merchant-manager.md`, `solve.md` and the terminal delivery contract.
- **Short ids can be ambiguous.** A short id prefix can match several Steps, which is then refused as ambiguous. The full step UUID always resolves.
- **No concurrent PostgreSQL runs.** PostgreSQL suites must never run concurrently against the test database.

## 9. GO / NO-GO

- **GO** for NL4C1 acceptance review of this uncommitted foundation.
- **GO** to plan NL4C2 after acceptance. NL4C2 means:
  - enable `step update` in test mode only;
  - exercise the claim, ledger and recovery path end to end;
  - add the teammate/lead confirmation wording and delivery contract;
  - run a live read-only preview, then one confirmed test-database Step Update.
- **NO-GO** for:
  - live Step Updates;
  - production Direct EXECUTE, which stays disabled;
  - starting NL4C2 before NL4C1 is accepted.

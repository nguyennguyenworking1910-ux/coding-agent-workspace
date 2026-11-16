# CP12H.NL3 — Conversational Project Confirmation

Date: 2026-11-04 · Branch `feat/cp7-9-merchant-reliability` · Baseline `96c3c0e`
Not committed or pushed. No live Project Create was performed.

## 1. Phase 1 — Can a user confirmation be authenticated?

**Yes. The signal is the `UserPromptSubmit` hook payload.** It carries the exact text the user submitted and the harness-issued `session_id`. The existing `--merchant-scope` authority already rests on it. The model cannot emit that event.

Evidence from the live NL2 lead transcript (`49f7c713…`):

| Input | How it reaches the lead | `UserPromptSubmit` envelope |
|---|---|---|
| User's `/solve --confirm …` prompt | recorded with `origin: {kind: "human"}` | yes, the only one in the session |
| Teammate messages (execute request, final report, idle) | user-role turns wrapped as `Another Claude session sent a message: <teammate-message …>` | none |

Two conditions are needed to make the signal sufficient:

1. **A whole-prompt, anchored match.** The confirmation must be the entire prompt, starting with `/solve`. The harness wrapper means a relayed teammate message can never match, and neither can a sentence that only contains the phrase.
2. **No model-scheduled prompts.** `CronCreate`, `ScheduleWakeup` and `RemoteTrigger` submit model-written text later as a prompt. A new `PreToolUse` guard denies any scheduled prompt that would be a controlled `/solve` or `/schedule-agent` command or a confirmation phrase.

**What is not trusted as approval:** teammate messages, lead/model text, `TEAM_RESULT_JSON`, task assignments, and persisted JSON. The pending record only says *what* may be confirmed. It is never approval itself.

The platform-signal condition for stopping did not apply, so the write-authorization path was implemented.

## 2. Architecture

```
/solve Tạo project mở rạp Beta Nguyễn Văn Cừ…          (user, UserPromptSubmit)
  intent_gate: unscoped Project-create → read-only preview run (no --confirm needed)
  merchant-manager: agent_cli.py project preview [--test-database]
  PostToolUse(Bash) record_preview_evidence  ── verified pane + exact CLI JSON + trusted target
        └─ merchant_pending_confirmation.record_pending(owner=lead session)   ← only creator
  teammate report (exact MERCHANT_PREVIEW_OPERATION_JSON) → lead shows preview + “/solve Xác nhận tạo <id8>”

/solve Xác nhận tạo [<id8>]                              (user, UserPromptSubmit)
  intent_gate.confirm_pending_project:
     parse_confirmation(whole request) → resolve(session_id, …) under file lock
     exactly 1 live record → status CONFIRMED (single-use spend point)
     re-validate: validate_requested_operation + validate_direct_scope
     merchant_scope = {argv, command, database_target, scope_hash, run_id}
     deterministic envelope (merchant_execute, merchant-manager, external_write,
       conversational_confirmation{…}); no model classification
     systemMessage to the user: exact title / merchant / project_id / target
  ── from here, the unchanged Direct EXECUTE pipeline ──
  dispatch/reuse merchant-manager → completeness → MERCHANT_EXECUTE_REQUEST_JSON
  → reservation → test-target preflight (basis recompute) → spend → transaction
     (basis recheck) → committed claim + ledger evidence → release
```

### Pending record (`.claude/hooks/merchant_pending_confirmation.py`)

The record lives at `<runtime state dir>/<session>.pending_project.json`. It is guarded by a `FileLock` and written atomically with `replace_with_retry`, and holds at most 20 records.

| Field | Content |
|---|---|
| `operation` | The full CLI `requested_operation`, which `validate_requested_operation` checks. It includes the exact argv, `merchant_id`/`merchant_code`, `project_type`, `workflow_variant`, the Unicode `title`, `requires_procurement`, `expected_basis`, `database_target` and `confirmation_command`. |
| `project_id`, `database_target` | Copied from the operation and cross-checked at confirmation. |
| `owner_session_id` | The lead session that ran the preview. A record is only ever looked up by the submitting session. |
| `source_run_id`, `source_task_id` | The preview run and task that produced the evidence. |
| `created_at`, `expires_at` | A 15-minute lifetime (`PENDING_TTL_SECONDS = 900`). |
| `status` | `PENDING` → `CONFIRMED` (with `confirmed_run_id`) or `CANCELLED`. The transition is the single-use spend point. |
| Identifier | `project_id`. The user may type its first 8+ hex characters, and full UUIDs are accepted. Ambiguous or unknown prefixes are refused. |

**Creation.** Only `record_preview_evidence` creates records, and only for a VERIFIED, READY capture with an operation. That means:

- the exact `agent_cli.py project preview` call
- run in the verified teammate pane
- whose output passed `preview_from_tool_response`
- on the trusted target

A re-captured preview of the same `project_id` replaces its live record, so there are no duplicates.

## 3. User interaction flow

| Step | User types | System |
|---|---|---|
| 1 | `/solve Tạo project mở rạp Beta Nguyễn Văn Cừ trên database test.` | Runs the read-only preview. **`--confirm` is no longer needed** for an unscoped Project create (§5.3). The lead shows the preview, the `confirmation_command`, and `/solve Xác nhận tạo <id8>`. |
| 2 | `/solve Xác nhận tạo.` (or `… <id8>`, `xac nhan tao`, `Confirm create`, `… project`) | The hook shows `Confirmed Project create 'Beta Nguyễn Văn Cừ' for Merchant NL2_LIVE_BETA (project_id …) on the test database. It runs once now.` The scoped run then executes once. |
| — | `/solve Hủy tạo [<id8>]` / `Cancel create` | The record is cancelled and the hook replies "Nothing was created." |
| — | `Xác nhận tạo.` (no `/solve`) | If something is pending, the hook refuses and explains how to confirm. Otherwise the prompt is ignored. Nothing is consumed. |

**Platform constraint.** A `UserPromptSubmit` hook can add context or block a prompt, but it cannot turn a bare prompt into the `/solve` command. The confirmation therefore has to be `/solve Xác nhận tạo`, not the bare phrase.

## 4. Security analysis

| Requirement | Enforcement | Test |
|---|---|---|
| No write without explicit user confirmation | Only `UserPromptSubmit` with the whole prompt equal to the phrase creates a scope. The bare phrase, a preview, or no pending record gives no scope. | `test_no_pending_record_means_no_authorization`, `test_bare_phrase_never_starts_a_run`, PG: no Project after the preview |
| No model-generated confirmation | Confirmations are never classified by a model (the parser factory raises in tests). Scheduled prompts are denied by `policy_gate`. | `test_model_cannot_schedule_a_confirmation` ×9, `test_policy_gate_denies_a_scheduled_confirmation` |
| No teammate or relayed confirmation | Anchored whole-prompt match, and the harness wrapper prefix | `test_teammate_relayed_confirmation_is_not_user_approval` |
| No cross-session confirmation | The store is keyed by the submitting `session_id`, and records are filtered by `owner_session_id`. | `test_another_session_cannot_confirm` |
| No ambiguous selection | More than one live record means refusal with a list of ids and titles. An id prefix selects exactly one record, and an unknown id is refused. | `test_multiple_pending_operations_refuse_an_ambiguous_confirmation`, `test_unknown_identifier_is_refused` |
| No operation substitution | The scope argv is the record's validated canonical argv. Any extra words (edits, negation, target) make the prompt *not* a confirmation. A tampered record fails `validate_requested_operation`. | `test_contradictory_text_is_not_a_confirmation` ×3, `test_tampered_pending_record_is_refused` |
| No stale preview execution | The record expires after 15 minutes. The existing `expected_basis` recompute runs at preflight and inside the transaction. | `test_expired_record_is_refused`, PG `test_merchant_changed_after_preview_is_refused_before_any_spend` |
| No replay | The `PENDING→CONFIRMED` transition under a lock happens before the run exists. The downstream operation key also blocks a second attempt. | `test_replay_after_confirmation_is_refused`, PG replay |
| Concurrent confirmation | A file lock gives exactly one winner. | `test_concurrent_confirmations_select_the_record_once` (8 threads) |
| No test→runtime escalation | The target comes only from the captured evidence, and the phrase cannot carry one. "…trên database runtime" is not a confirmation. | contradictory-text case 3 |
| Runtime Direct EXECUTE stays disabled | Unchanged: `RUNTIME_DIRECT_EXECUTE_ENABLED = False`. A runtime record would become a runtime scope, which is refused before reservation. | existing suites |
| No expired-record execution | Expired records are not live. | `test_expired_record_is_refused` |
| No bypass of completeness, reservation, pane identity or evidence | The confirmation only produces an ordinary `merchant_scope`. Every later gate is the existing code. | PG end-to-end: completeness, verified pane, reservation, preflight, committed claim `COMPLETED`, release `IDLE_REUSABLE` |
| Crash safety | A crash after the spend but before the run commits leaves the record CONFIRMED and no run. A retry is refused and a fresh preview is needed, so the failure is closed and nothing replays. | `test_crash_before_the_run_is_committed_never_replays` |
| UTF-8 | The title survives the store, the scope argv, the envelope and the database row. | unit + PG (`title == "<short> Nguyễn Văn Cừ"`) |
| Teammate lifecycle | The preview run releases to `IDLE_REUSABLE`. The confirmed run reuses the teammate through the `SendMessage` redirect and releases again after `EXECUTE_SUCCESS`. | PG `test_conversational_confirmation_creates_exactly_one_project` |

### Defense additions beyond the brief

- A **trusted `systemMessage`** on confirmation states the exact operation. The user sees it from the hook, not from the model, so a misrendered preview can't misstate what runs.
- The `PreToolUse` **scheduling guard** also closes the equivalent pre-existing gap for typed `--merchant-scope` prompts.

## 5. Implementation

### 5.1 Files

| File | Change |
|---|---|
| `.claude/hooks/merchant_pending_confirmation.py` (new) | Record store, phrase parser, `resolve` (single-use spend), bare-phrase guidance, scheduling guard |
| `.claude/hooks/merchant_preview_delivery.py` | `record_preview_evidence` creates the pending record after verified READY evidence |
| `.claude/hooks/intent_gate.py` | `confirm_pending_project`, deterministic envelope, trusted `systemMessage`, bare-phrase refusal, unscoped Project-create downgrade |
| `.claude/hooks/policy_gate.py` | Calls the scheduling guard first on every `PreToolUse` |
| `.claude/commands/solve.md` | Lead accepts a gate-issued conversational scope and shows `/solve Xác nhận tạo <id8>` |
| `.claude/agents/merchant-manager.md` | Names the conversational confirmation; never confirm for the user |
| `CLAUDE.md`, `.claude/documents/ARCHITECTURE.md` | Authority statement and hook listing |
| `tests/merchant/test_nl3_conversational_confirmation.py` (new) | 42 unit tests on real hooks, no database |
| `tests/merchant/test_nl3_conversational_confirmation_postgres.py` (new) | 2 end-to-end tests on `coding_agent_merchant_test` |

### 5.2 RED/GREEN

1. Unit tests written first. Collection failed with the module missing (RED).
2. Store, gate and capture implemented: 32 passed, 6 failed (the policy-gate guard was not wired yet, plus one wrong assertion of mine).
3. Guard wired: 38 passed (GREEN).
4. Downgrade test: 1 failed (RED), then 42 passed (GREEN).
5. `systemMessage` assertion: 5 failed (RED), then passed (GREEN).
6. PostgreSQL end-to-end: first run exposed the `--confirm` UX block (§5.3), then 2 passed.

### 5.3 Behaviour change: preview without `--confirm`

The model classifies "Tạo project …" as `merchant_execute` / `external_write`, so the gate used to **block** it until `--confirm` was added, even though an unscoped run can only read. The gate now downgrades it to `merchant_read` / `read_only` without `--confirm`, but only when all of these hold:

- there is no scope
- `selected_agents == ["merchant-manager"]`
- the operations are a subset of `{merchant_execute, merchant_read}`
- the deterministic `interpret_project_request(...).kind == PROJECT_CREATE`

This is strictly a reduction in authority. Merchant creates, mixed requests and step updates still require `--confirm` (`test_other_writes_still_need_explicit_confirmation` ×3).

## 6. Verification

| Check | Result |
|---|---|
| NL3 unit + PG | 44 passed |
| NL3 + NL2H envelope + NL2E preview suites | 120 passed |
| **Full regression** (run alone, final code, 08:52:59–08:59:06Z) | **3739 passed, 20 skipped, 1 xfailed, 97 subtests passed**, exit 0. The 3695 baseline plus 44 new tests, with no regressions. An earlier run overlapped another test run and used pre-final code; it also passed but is not counted. |
| `system_test.py` | 80/80 |
| `git diff --check` | clean |
| Test DB integrity (RC1 snapshot of live Project `30fffeaf…`, its claims, ledger and fixtures) | **Byte-identical** to the RC1 baseline (sha256 `a4a2fd39…a795`). The live Project, its 22 steps, its event, the live claim, the ledger and the 16 historical claims are unchanged, and no test fixtures are left behind. |

Script-mode smoke test (real `python .claude/hooks/*.py`, isolated state):

- `ScheduleWakeup` with `/solve Xác nhận tạo` → deny
- `Read` → silent
- bare phrase → silent
- `/solve Xác nhận tạo` with nothing pending → refused

## 7. Remaining limitations

1. **`/solve` prefix required.** This is the platform constraint in §3. A bare "Xác nhận tạo." only produces guidance.
2. **The approval signal depends on harness behaviour.** The `UserPromptSubmit` payload has no explicit origin field. Trust rests on two observed facts: only user prompts and scheduled prompts reach it, and teammate messages are wrapped. Scheduled prompts are guarded. A future harness channel that submits unwrapped model text as a prompt would need the same guard.
3. **The preview display is model-rendered.** The trusted `systemMessage` appears at confirmation, not before it. The operation that runs is always the verified record.
4. **Same-user processes.** A process running as the same user can edit the store file, as with all existing runtime state. Edits are detected only when the result is non-canonical (`validate_requested_operation`).
5. **A crash between spend and run commit loses the record** and requires a fresh preview. This is deliberate fail-closed behaviour.
6. **The 15-minute lifetime is a constant.** The basis recheck is what actually protects against staleness.
7. **Template change.** It is covered by the existing basis-recompute unit tests (NL2E) rather than a new PG test, because changing the shared test-DB template would affect the live acceptance fixture.
8. **Runtime Direct EXECUTE remains disabled.** Conversational confirmation of a runtime preview is refused downstream.

## 8. Recommendation

**GO for controlled live testing on the test database.** Every check passed:

- the trusted foundation
- the single-use confirmation
- the scheduling guard
- the end-to-end run on PostgreSQL through the unchanged Direct EXECUTE pipeline
- the full regression
- `system_test.py`
- database integrity

Suggested live script, with a fresh user confirmation and nothing else:

1. `/solve Tạo project mở rạp Beta <new site> trên database test. Không cần mua sắm.` Expect a preview with `/solve Xác nhận tạo <id8>`.
2. `/solve Xác nhận tạo <id8>`. Expect the hook's `Confirmed Project create …` message, then `EXECUTE_SUCCESS` and the teammate back at `IDLE_REUSABLE`.
3. Repeat step 2. Expect a refusal with nothing created.
4. Verify read-only in PostgreSQL that exactly one Project, one `COMPLETED` claim and one ledger row exist.

**NO-GO for runtime (production).** Runtime Direct EXECUTE remains disabled and needs separate approval.

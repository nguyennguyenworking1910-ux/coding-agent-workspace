# CP12H.NL4B-FIX1 — Live Preview Routing and Stale Teammate Definition

Baseline `dd103bb` on `feat/cp7-9-merchant-reliability`, on top of the uncommitted NL4B changes, which are preserved. Nothing is committed or pushed. No live Step Update was run and NL4C was not started.

## 1. Root causes

### Failure 1: a read-only Step preview was blocked for `--confirm`

**Evidence.**
- The session transcript records the block at `2026-11-05T08:52:39Z`. That was after the NL4B intent-gate downgrade was already in place, so the downgrade existed but its conditions didn't match.
- The gate doesn't log the envelope on a block. I replayed the exact request through the real `IntentParser`, 3 times per request (scratch `replay_parser.py`; it prints classification fields only).

| Request | Model output |
|---|---|
| Live 1, "Đánh dấu bước Legal Review của Project Beta Nguyễn Văn Cừ là hoàn thành trên database test" | **attempt 0: `ops ['fix']`, `domains ['data']`, `selected ['bug-fixer']`, `external_write`**. Attempts 1–2: `merchant_execute` / `merchant-manager`. |
| Live 2, "Cập nhật bước 1 của Project Beta NL3 Confirmation Test thành đang thực hiện trên database test" | 3/3 `merchant_execute` / `merchant-manager`. |

**Cause.**
1. The parser's deterministic guardrail `_detect_local_merchant_operation` claims a request only when it contains a Merchant word ("merchant", "đối tác", …) or a Project type ("mở rạp", …). Neither live request has one.
2. Ownership was therefore left to the LLM, which is nondeterministic on wording like "Đánh dấu … là hoàn thành". Once it routed the request to `bug-fixer`, the intent gate's read-only downgrade didn't apply: it requires `selected_agents == ["merchant-manager"]` and only Merchant operations.
3. The `external_write` confirmation gate then blocked the request.

The two wordings didn't differ in kind: both depended on the model, and live 2 happened to classify correctly every time.

### Failure 2: the reused teammate ran a stale definition

The harness loads `.claude/agents/<role>.md` once, when the teammate's pane starts. The lifecycle kept no record of which definition a teammate loaded. It marks a teammate `IDLE_REUSABLE` on report delivery and pane identity only.

The `merchant-manager` pane in this session started before NL4B added `step preview` to its definition. It was reused, it didn't know the command, and it refused it. That refusal was correct.

The command allowlist itself (`agent_cli.py`, `cli_contract.py`) is code, re-imported on every call, so it can't go stale. Only the loaded instructions can.

## 2. Code changes

| File | Change |
|---|---|
| `.claude/system/intent_parser.py` | `_detect_local_merchant_operation` also counts as a Merchant request an explicit `STEP_UPDATE` (`project_nl`) that names a Project (`project_phrase` set). The guardrail then decides the operation, as it already does for Project create, and the model no longer does. An affirmative request gives `merchant_execute`, which the intent gate downgrades to the read-only preview when there is no scope; a negated one gives `merchant_read`. |
| `.claude/hooks/team_lifecycle.py` | New `agent_definition_fingerprint(role)`, the sha256 of `.claude/agents/<role>.md`; the role must match `[a-z0-9-]` and read failures return `None`. New `teammate_definition_current(record)`. `init_teammate_record` stores `definition_sha256` at allocation, in PreToolUse(Agent), before the harness loads the definition. |
| `.claude/hooks/policy_gate.py` | Reuse via `SendMessage` is refused, after the pane check and before `reserve_reusable_teammate`, unless the teammate's fingerprint matches the current file. Nothing is reserved or sent. |
| `.claude/hooks/intent_gate.py` | `TEAM_STATE_SNAPSHOT_JSON` reports an idle teammate with a stale or missing fingerprint as `STALE_DEFINITION` instead of `IDLE_REUSABLE`. |
| `.claude/commands/solve.md` | Adds `STALE_DEFINITION` to the stop-and-report statuses, and states that `RESULT_DELIVERED` means only that a report was sent. |
| `tests/merchant/test_nl4b_fix1_routing_and_teammate.py` | New, 20 tests. |

**Fail-closed choices.**
- A record with no fingerprint is never current. That covers a teammate spawned before this fix, which is exactly the live case.
- If the definition changes between allocation and pane start, the teammate is newer than its fingerprint, so it is refused, never wrongly accepted.

## 3. RED / GREEN

The RED runs used a disposable worktree holding the current tree with selected files reverted, and the editable `claude` finder replaced. The live hooks were never swapped, and the worktree was removed afterwards.

| Variant | Result |
|---|---|
| RED-A: pre-fix `intent_parser.py` | **12 failed**, 8 passed. All 7 VN/EN paraphrases were routed to `bug-fixer`; all 4 end-to-end `/solve` submissions were blocked for confirmation; the negated request was not a read. |
| RED-B: pre-fix `team_lifecycle.py` + `policy_gate.py` + snapshot | **4 failed**: no fingerprint at allocation (`KeyError`); stale teammate shown as `IDLE_REUSABLE`; both reuse cases failed. In those two cases the pre-fix failure is the missing fingerprint API, not a demonstrated wrongful reuse. |
| GREEN: FIX1 + NL4B unit tests | **64 passed** |
| Real parser replay, after the fix | Live 1: 3/3, Live 2: 3/3 `merchant_execute` / `merchant-manager` ("reconciled by local guardrail"). The gate then downgrades them to read-only. |

**Test coverage.**
- **Both exact live requests and five paraphrases:** "Hoàn thành bước …", "Chuyển bước 2 của dự án … sang đang thực hiện", "Mark step 3 … as completed on the test database", "Mark the Legal Review step … as done", "Start step 1 …". All are fed the model's actual bug-fixer classification.
- **End-to-end:** `intent_gate.run` produces `merchant_read` / `read_only` with a test or runtime target and no scope.
- **Strict cases still blocked:** "Mark the deploy step as done" (no Project), "Fix the step update code in project_nl.py" (code work), a Merchant create, and a mixed Merchant + Project request.
- **Teammate:** fingerprint recorded and checked, path-traversal role rejected, snapshot shows `STALE_DEFINITION`, and real policy-gate reuse is refused for a changed and for an unfingerprinted teammate, with the status left `IDLE_REUSABLE` and `members_used` empty.

## 4. Teammate lifecycle findings

- **Before this fix:** reuse was decided by lifecycle status, run/task binding and the verified pane identity (`reused_teammate_pane_matches`). Nothing tied a teammate to the definition it loaded.
- **Now:** a fingerprint is checked before every reuse, and reuse is allowed only on a match. Pane verification, task identity, the same-run circuit breaker and the max-members limit are unchanged.
- **Deferred: automatic replacement.** Retiring a stale `IDLE_REUSABLE` teammate and spawning a fresh one under the same canonical name needs lifecycle changes. Allocation, global ownership, pane teardown and the "never create a replacement or suffixed name" rule would all be affected. A stale teammate is refused and reported instead.
- **Retest requirement:** run the live retests from a fresh Claude Code session. That holds for this session's existing `merchant-manager` as well, because it has no fingerprint.

## 5. Full regression

- **pytest, full suite:** **3935 passed, 20 skipped, 1 xfailed, 0 failed**, 97 subtests passed. That is NL4B's 3915 plus the 20 FIX1 tests. The doc-contract tests and `system_test.py` were re-run after the final `solve.md` edit and pass.
- **Targeted:**
  - FIX1 + NL4B unit tests: 64 passed.
  - Lifecycle, reuse and policy-gate tests (`test_team_lifecycle`, `test_nl2c_fix_respawned_pane`, `test_teammate_reuse_dispatch`, `test_tmux_multi_role_lifecycle`, `test_policy_gate`, `test_solve_command_contract`, `test_merchant_direct_lifecycle_fencing`) and all of `tests/merchant`, including PostgreSQL: 3127 + 54 passed.
- **`python .claude/system_test.py`:** 80/80.
- **`git diff --check`:** clean.

## 6. Security invariants

- **No Step Update execution:** no write path was added, and `step update` stays rejected by `agent_cli`.
- **No pending confirmation and no authorization from a preview:** both are unchanged from NL4B (`record_read_evidence` returns before `record_pending`, and the step preview contract is terminal).
- **The guardrail only changes ownership:** it maps to `merchant_execute`, so the model's `external_write` risk is kept. Without a scope, the intent gate's existing downgrade turns it into a read with no scope. With a user-typed `--merchant-scope`, the strict scoped path is unchanged, and the downgrade requires `merchant_scope is None`.
- **No broad downgrade:** a step update needs an explicit update verb with `bước`/`step` and a named Project. Merchant create, mixed requests, code work and non-Merchant "steps" keep their previous classification and the confirmation block.
- **Direct EXECUTE:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False` (`.claude/hooks/merchant_direct_handoff.py:63`).
- **Database isolation:** the target still comes from the user's words (`merchant_read_target`). Test-DB hash `71d315c99d0b5cdbfdb5588b07ee7f307736a308dc6e980f7f7885b87e0322a7` is unchanged.
- **Accurate outcomes:** in the failed live run, the teammate's `PREVIEW_DELIVERY_FAILED` report was delivered and its idle notice said `RESULT_DELIVERED`. That marks delivery only. The lead reported the run as failed, and `solve.md` now says so explicitly. The fix adds no new `TEAM_RESULT_JSON` path.

## 7. Live retest instructions

1. **Start a fresh Claude Code session in psmux.** It must be new so that `merchant-manager` is allocated with a fingerprint. The existing teammate here has none and will now show as `STALE_DEFINITION`.
2. **Record the test-DB hash** with the read-only `db_hash.py`, printed to the console. File redirects are blocked in read-only runs.
3. **Run:**
   - `/solve Đánh dấu bước Legal Review của Project Beta Nguyễn Văn Cừ là hoàn thành trên database test`. Expect envelope `merchant_read` / `read_only` with reason "reconciled by local guardrail", and outcome **BLOCKED**: `TRANSITION_NOT_ALLOWED` (PENDING→COMPLETED) and `UNMET_DEPENDENCIES` (step 1).
   - `/solve Cập nhật bước 1 của Project Beta NL3 Confirmation Test thành đang thực hiện trên database test`. Expect **READY_FOR_CONFIRMATION** (READY→IN_PROGRESS). The lead must state that nothing was updated and that no confirmation exists.
   - The remaining prompts of NL4B report §9 (3–5).
4. **Pass criteria:**
   - each prompt makes one `step preview … --test-database` call and returns one `MERCHANT_STEP_PREVIEW_JSON` block;
   - no `--merchant-scope`, confirmation command or argv appears;
   - the teammate is released as `IDLE_REUSABLE` and reused, in the same session, for the next prompt;
   - the hash is unchanged.

## 8. GO / NO-GO

**GO for NL4B acceptance, conditional on the fresh-session live retest in §7.** Both live failures have confirmed root causes and fixes, with RED/GREEN evidence. The failure-1 cause was also replayed against the real model. Authorization is not weakened: explicit, scoped, create, mixed and runtime-write paths are unchanged. Runtime Direct EXECUTE stays disabled, and the test database is unchanged.

NO-GO if a live run shows any of these: a confirmation block for these requests, a non-`merchant-manager` route, a `STALE_DEFINITION` teammate in a fresh session, or any change to the test-DB hash.

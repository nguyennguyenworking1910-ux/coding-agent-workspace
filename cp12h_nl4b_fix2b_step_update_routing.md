# CP12H.NL4B-FIX2B — UserPromptSubmit Routing for Incomplete Step Updates

Baseline `dd103bb`, branch `feat/cp7-9-merchant-reliability`, on top of the
uncommitted NL4B, NL4B-FIX1 and NL4B-FIX2 changes (all preserved). Not committed.

## 1. Live failure

`/solve Đánh dấu bước Legal Review hoàn thành trên database test` was blocked by
UserPromptSubmit: "needs explicit confirmation … risk_level is external_write".

## 2. Root cause

Trace: UserPromptSubmit → `intent_gate.run` → `IntentParser.parse` (model plus
`_detect_local_merchant_operation` guardrail) → gate read-only downgrade → block.
The rejection happened **before** the gate's read-only downgrade could apply.

- `project_nl.interpret_project_request` classified the prompt correctly
  (`STEP_UPDATE`, step `Legal Review`, target `COMPLETED`, project `None`).
- The FIX1 guardrail claimed a Step update only **when it named a Project**
  (`project_phrase is not None`). With no Project, `local = None`, so the model
  decided ownership on its own. Three replays of the real parser on the live prompt:
  - 2 of 3 runs: `operations ['fix'], domains ['data'], selected ['bug-fixer']`.
    The downgrade needs merchant-manager only, so the prompt was blocked for `--confirm`
    (this is the live symptom).
  - 1 of 3 runs: `merchant_execute` / merchant-manager, but with
    `requires_clarification: true` (no Project). The clarification block ran
    **before** the downgrade, so the prompt was blocked anyway.
- Secondary bug: in "Đánh dấu bước hoàn thành cho Project Beta", the verb was
  read as the Step name (`step_reference='danh dau'`). The English "the X step"
  rule, which reads the name *before* the step noun, was also applied to "bước".

## 3. Fix

| File | Change |
|---|---|
| `.claude/system/intent_parser.py` | The guardrail claims **every** recognized `STEP_UPDATE`. A Project is no longer required. |
| `.claude/hooks/intent_gate.py` | The `requires_clarification` block moved below the read-only downgrade. A recognized `STEP_UPDATE` downgrade clears it, so a missing Project, Step or status reaches the preview's `NEEDS_CLARIFICATION`. Every other clarification still blocks. |
| `.claude/agents/tools/merchant/project_nl.py` | `_FURTHER_ACTION`: a Step update joined by a conjunction to another action verb ("… và lên lịch", "… rồi xóa", "… and then delete") becomes `MIXED`. MIXED is never downgraded, keeps external_write, and is not claimed by the guardrail. In `_step_at`, only "step", never "bước", reads a name that comes before the noun. |
| `tests/merchant/test_nl4b_fix1_routing_and_teammate.py` | Intentional change: "Mark the deploy step as done" (no Project) no longer blocks for `--confirm`. It is now a read-only preview, which asks for the Project. |
| `tests/merchant/test_nl4b_fix2b_step_update_routing.py` | New: 42 tests on the real `intent_gate.run` with the real `IntentParser`. Only the model's answer is replayed. |

Unchanged:
- The downgrade still requires `merchant_scope is None`, no conversational
  confirmation, `selected_agents == ["merchant-manager"]`, operations ⊆
  {merchant_execute, merchant_read}, and a deterministic `STEP_UPDATE` kind.
- No scope is ever built from the text.
- `--confirm` on a Step update still yields `merchant_read` only.
- Unrecognized wording (e.g. "Set step Legal Review to in progress") still fails
  closed to the model's external_write classification and `--confirm`.

## 4. RED / GREEN (real UserPromptSubmit entry point)

- **RED:** with only the three FIX2B source edits reverted (files backed up and
  restored), 28 of 41 tests fail. The live-prompt test fails with the exact live
  message: `/solve needs explicit confirmation before running: risk_level is external_write`.
- **GREEN:** 42/42 pass. The 42nd test, the moved FIX1 case, was added after the RED run.
- **Real model, real hook subprocess** (UTF-8 bytes on stdin, isolated state dirs):

| Prompt | Result |
|---|---|
| Đánh dấu bước Legal Review hoàn thành trên database test | read_only, merchant_read, merchant-manager, target test, no confirm/clarify/scope |
| Đánh dấu bước Legal Review hoàn thành | read_only, target runtime |
| Đánh dấu bước Legal Review của Project Beta Nguyễn Văn Cừ là hoàn thành trên database test | read_only, target test |
| Mark the Legal Review step as completed on the test database | read_only, target test |
| … hoàn thành và lên lịch họp ngày mai | blocked (MIXED, not downgraded) |
| Tạo merchant Beta Cinemas mã BETA2 | blocked, `--confirm` required |

- **Parser replay after the fix:** the live prompt is routed to merchant-manager 3/3 times.

## 5. Parser/clarification consistency

- "Đánh dấu bước Legal Review hoàn thành": step `Legal Review`, `COMPLETED`, no
  Project. Preview `missing == ["project"]`, outcome `NEEDS_CLARIFICATION`.
- "…của Project Beta Nguyễn Văn Cừ là hoàn thành": the same step and status, with
  the Project phrase set.
- Both forms get the same parser operation and go through the same read-only gate path.

## 6. Security coverage (new test file)

The file covers:
- the exact live prompt under both live model answers;
- missing Project, missing Step and missing status;
- Vietnamese and English variants, and "Hoàn thành bước X";
- `--confirm` granting no write;
- `record_pending` and `invoke_authorized_scope_apply` never reached, and no pending record;
- status questions ("…đã hoàn thành chưa?", "Is the … step completed?") staying non-writes;
- Project create still being only a preview;
- five mixed requests blocked under both a `bug-fixer` and a merchant-only model answer;
- an unrecognized Step wording, code work and Merchant create still blocked;
- `CronCreate`, `ScheduleWakeup` and `RemoteTrigger` refused for the prompt;
- a `--merchant-scope` without `--confirm` refused.

## 7. Regression

- Merchant suite: 3156 passed. The only failure was the intended FIX1 case, since updated.
- Full suite, DB-backed, runtime credentials blank: **4014 passed, 20 skipped
  (MERCHANT_RUN_* opt-ins), 1 xfailed**. That is the FIX2 total of 3972 plus the 42 new tests.
- `python .claude/system_test.py`: ALL TESTS PASSED.
- `git diff --check`: clean.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False` (`merchant_direct_handoff.py:63`).
- Test DB integrity hash: `1636f0cb…809c` before and after, which matches FIX2.
  Row counts are identical (3 projects, 18 claims, 2 ledger rows). The existing
  Project and execution evidence is untouched.
- Hook import smoke (`py_compile` plus importing `intent_gate` and `policy_gate`)
  passed after the edits.

## 8. Live retest

Use a fresh Claude Code session in psmux. The hooks are unchanged in registration;
a fresh session picks up the new parser and gate.

1. `/solve Đánh dấu bước Legal Review hoàn thành trên database test`. Expect no block, an
   envelope with `risk_level: read_only`, `operations: ["merchant_read"]` and
   `merchant_database_target: test`. merchant-manager runs `step preview --request …
   --test-database` and returns `NEEDS_CLARIFICATION` with missing `[project]`. No write.
2. `/solve Đánh dấu bước Legal Review của Project Beta Nguyễn Văn Cừ là hoàn thành trên database test`.
   Expect the same path, with a preview outcome from current DB state.
3. `/solve Đánh dấu bước Legal Review hoàn thành và lên lịch họp ngày mai`. Expect a block.
4. Re-run the DB integrity hash. It must still be `1636f0cb…809c`.

## 9. GO / NO-GO

- **GO** for the live read-only retest in §8.
- Step Update writes stay **NO-GO**: there is no Step confirmation path (NL4C was not
  implemented), and runtime Direct EXECUTE is disabled.

Known limits:
- Mixed detection needs a conjunction followed by an action verb. A comma-only second
  action ("…, xóa merchant Beta") is not detected. It still cannot write, because the
  downgrade makes the whole run read-only.
- "Mark step 3 of the CI pipeline as done" now runs as a read-only Merchant preview,
  which asks or fails to resolve; it never writes.

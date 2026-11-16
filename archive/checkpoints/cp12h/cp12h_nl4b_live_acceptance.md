# CP12H.NL4B — Live Acceptance: Read-only Natural-Language Step Update Preview

Baseline `dd103bb73d5227366c2d49f23486ead96769a06f`, branch `feat/cp7-9-merchant-reliability`.
Covers NL4B, NL4B-FIX1, NL4B-FIX2 and NL4B-FIX2B. Date 2026-11-06.

## 1. Scope

NL4B adds `step preview --request "<user words>"`: a read-only "what would happen if this Step
update ran" for one Project step.

- It never writes, reserves, claims or confirms.
- `executable` and `confirmation_available` are always false and `authorization` is always null.
- Step Update confirmation and execution are NL4C and later. They were not started.

## 2. Live prompts, failures and fixes

**The live runs did not all run on one code revision.** Each failure below led to a fix, and the
next run used the fixed code in a fresh Claude Code session.

The five scenarios come from the original NL4B script (`cp12h_nl4b_step_update_preview.md` §9),
as amended by the FIX1 and FIX2 retest lists. The user reported that all five reached their
expected read-only outcomes. This session directly observed only the final FIX2B run (§2.4).
For the other runs, the outcomes below are taken from the user's statement and the FIX reports;
they were not re-executed for this report.

| # | Prompt (test database) | Expected outcome |
|---|---|---|
| 1 | `Đánh dấu bước Legal Review của Project Beta Nguyễn Văn Cừ là hoàn thành trên database test` | BLOCKED: TRANSITION_NOT_ALLOWED (PENDING→COMPLETED), UNMET_DEPENDENCIES (step 1) |
| 2 | `Cập nhật bước 1 của Project Beta NL3 Confirmation Test thành đang thực hiện trên database test` | READY_FOR_CONFIRMATION (READY→IN_PROGRESS); nothing updated, no confirmation offered |
| 3 | `Mark the Send reviewed revision to Partner step of Project Beta NL3 Confirmation Test as completed on test database` | BLOCKED: direct deps [2, 3], transitive [1, 2, 3], count 3 |
| 4 | `Bước Legal Review của Project Beta Nguyễn Văn Cừ đã hoàn thành chưa trên database test?` | NL4A Project status read, not a step preview |
| 5 | `Đánh dấu bước Legal Review hoàn thành trên database test` (incomplete: no Project) | NEEDS_CLARIFICATION, `missing = ["project"]` |

### 2.1 FIX1: routing to bug-fixer, and a stale teammate (`cp12h_nl4b_fix1_live_routing_and_teammate.md`)

**Prompt 1 blocked for `--confirm`.**
- *Cause:* the parser guardrail claimed a request only when it contained a Merchant word or a
  Project type. The model sometimes routed the prompt to `bug-fixer`, so the read-only downgrade
  never applied.
- *Fix:* the guardrail also claims a Step update that names a Project.

**A reused teammate ran an old definition.**
- *Cause:* a reused `merchant-manager` pane kept the definition it was started with, from before
  `step preview` existed.
- *Fix:* a definition fingerprint (`definition_sha256`) is recorded at allocation. A stale or
  unfingerprinted teammate is reported as `STALE_DEFINITION`, and the policy gate refuses to reuse it.

### 2.2 FIX2: target status and clarification (`cp12h_nl4b_fix2_clarification_and_dependencies.md`)

**Prompt 5 (first attempt) asked only for the status.**
- *Cause:* the status "hoàn thành" came right after the step name with no connector, so it was
  lost. The preview also returned at the first missing field.
- *Fix:* bare states after đánh dấu / cập nhật / chuyển bước are read, and the preview collects
  all missing fields at once.

**Dependency evidence was ambiguous.**
- *Cause:* the reported count did not match the steps named.
- *Fix:* `unmet_dependency_scope` and `unmet_transitive_dependencies` now label direct and
  transitive dependencies separately.

### 2.3 FIX2B: incomplete request blocked (`cp12h_nl4b_fix2b_step_update_routing.md`)

**Prompt 5 (second attempt) was blocked in UserPromptSubmit as external_write.**
- *Cause:* the FIX1 guardrail still required a Project. Without one, the model routed the prompt
  to `bug-fixer` (2 of 3 replays), or set `requires_clarification`, which was checked before the
  read-only downgrade (1 of 3).
- *Fix:*
  - every recognized Step update is claimed by the guardrail;
  - the downgrade now runs before the clarification block, and clears clarification for
    STEP_UPDATE only;
  - a Step update joined to a second action becomes MIXED and keeps external_write.

### 2.4 Final run of prompt 5 (observed in this session)

`/solve Đánh dấu bước Legal Review hoàn thành trên database test`:

- **Envelope:** `read_only`, `operations ["merchant_read"]`, `selected ["merchant-manager"]`,
  `merchant_database_target: test`, `requires_confirmation: false`, `requires_clarification: false`,
  `confirmed: false`, no `merchant_scope`. The reason reads "reconciled by local guardrail".
- **Teammate:** `merchant-manager`, newly spawned in a psmux pane. It made one call,
  `step preview --request … --test-database`, and delivered one `MERCHANT_STEP_PREVIEW_JSON`
  block via `SendMessage`.
- **Result:**
  - outcome `NEEDS_CLARIFICATION`;
  - query `step_reference "Legal Review"`, `target_status "COMPLETED"`;
  - `missing ["project"]`, one Project question;
  - `project`, `step` and `candidates` empty;
  - `read_only true`, `executable false`, `confirmation_available false`, `authorization null`.
- **Lifecycle:** the teammate went idle with `RESULT_DELIVERED` and is reusable.

## 3. Evidence and its limits

- **Source-backed delivery.** The PostToolUse hook captures the CLI JSON. The policy gate accepts
  the teammate's `MERCHANT_STEP_PREVIEW_JSON` only if it is identical to that capture, from a
  verified pane, with the trusted target and the read-only fields.
- **Limits of the evidence.**
  - The outcomes of prompts 1–4 come from earlier sessions. Their raw transcripts are not
    reproduced here.
  - The domain checks (transition table, dependencies, gates) are the write path's own functions
    applied to a read snapshot. The real write would re-check everything under lock, so state
    can change between a preview and any future confirmation.

## 4. Security invariants (re-verified on the final tree)

- **No write capability added.**
  - `step preview` is in `READ_COMMANDS`, and `agent_cli` allows only `--test-database` for it.
  - `step update --test-database` is still refused by the allowlist.
  - The diff does not touch `merchant_direct_handoff`, `merchant_runtime_handoff`,
    `merchant_staging`, the reserved executor, or `merchant_pending_confirmation`.
- **`step_preview.py` only reads.** It reads through the read-command repository and calls the
  pure domain planners. Its output carries no argv, command, scope or confirmation.
- **The gate downgrade is narrow.** It applies only with no scope, no conversational confirmation,
  a roster of exactly `merchant-manager`, only Merchant operations, and a deterministic kind of
  PROJECT_CREATE, STATUS, LIST or STEP_UPDATE. It only ever lowers the risk.
- **What still fails closed:**
  - unrecognized wording keeps the model's external_write classification and needs `--confirm`;
  - MIXED requests keep external_write;
  - `--confirm` on a Step update still yields `merchant_read`.
- **No pending confirmation.** Step-preview evidence never reaches `record_pending`.
- **Scheduled prompts.** `CronCreate`, `ScheduleWakeup` and `RemoteTrigger` are refused for any
  `/solve` prompt.
- **Stale teammates.** A stale definition is refused for reuse.
- **Runtime Direct EXECUTE** stays disabled: `RUNTIME_DIRECT_EXECUTE_ENABLED = False`
  (`.claude/hooks/merchant_direct_handoff.py:63`).

## 5. Database comparison (`coding_agent_merchant_test`, read-only transaction, user `merchant_test`)

- **Integrity hash** (sha256 over every `merchant_ops` table, sorted-key JSON):
  `1636f0cb9ac89532b4b4e70ff2759f71c4c6bf4990d9fd86a11dbaecb4c0809c`.
  - This equals the FIX2 baseline.
  - It was identical before FIX2B, after the FIX2B live run, and after the final full suite.
- **Row counts:** 2 merchants, 3 projects, 70 steps, 70 step dependencies, 7 events,
  18 execution claims, 2 ledger rows, 0 `PYTEST%` merchants.
- **NL2 Project `30fffeaf-e6b5-5119-b078-52c934e1821e`** ("Beta Nguyễn Văn Cừ"):
  - PLANNED v1, last updated 2026-11-04 13:44 (before NL4B);
  - 22 steps, all at version 1 (step 1 READY, steps 6–7 SKIPPED, the rest as created);
  - 1 event.
- **NL3 Project `ba5cc7ec-bd78-5582-84e2-46b16037444c`** ("Beta NL3 Confirmation Test"):
  - PLANNED v1, last updated 2026-11-04 17:00;
  - 22 steps, all at version 1;
  - 1 event.
- **Pending confirmations:** none created by Step Previews. The only pending-Project file is dated
  2026-11-04 16:59 (NL3), and this session has no live records.
- No manual cleanup was performed.

The earlier NL4B report quotes hash `71d315c9…`, computed with a different method that cannot be
reproduced. Its row counts are identical to the above.

## 6. Final regression (current working tree)

- **Targeted** NL3, NL4A and all NL4B files, including PostgreSQL: **235 passed**.
- **Full suite**, run alone, DB-backed, runtime credentials blanked: **4014 passed, 20 skipped
  (MERCHANT_RUN_* opt-ins), 1 xfailed, 0 failed**.
  - An earlier full run that overlapped a concurrent targeted run had 3 failures and 5 errors, all
    in `test_nl4b_step_preview_postgres.py`: whole-table snapshot mismatches and an FK violation
    during teardown, caused by two runs sharing the test database.
  - Run alone, both the targeted set and the full suite are green. No test was changed.
- `python .claude/system_test.py`: ALL TESTS PASSED.
- `git diff --check`: clean.

## 7. Remaining risks

- READY_FOR_CONFIRMATION is advisory only. No Step confirmation or execution exists (NL4C).
- **Wording-dependent detection:**
  - mixed detection needs a conjunction followed by an action verb, so a comma-only second action
    is not caught (the run stays read-only);
  - a generic "Mark the X step as done" now goes to the Merchant preview, which asks or fails to
    resolve;
  - unrecognized phrasings such as "Set step X to in progress" fall back to the model and
    `--confirm`.
- PostgreSQL integration tests must not run concurrently against the same test database.
- `merchant-manager.md` changed during NL4B. Any teammate started before this tree reports
  `STALE_DEFINITION` and needs a fresh session.

## 8. GO / NO-GO

- **GO**: commit NL4B (read-only Step Update preview) and its fixes.
- **NO-GO** for Step Update writes and NL4C until separately specified.
- **NO-GO** for production Direct EXECUTE, which stays disabled.

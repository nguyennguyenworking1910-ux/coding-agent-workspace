# CP12H.NL4B — Natural Language Step Update Preview

Baseline `dd103bb` on `feat/cp7-9-merchant-reliability`. Uncommitted and unpushed. NL4C and NL4D were not started, and no live Step Update was run.

## 1. Summary

A request to update one Project step, in Vietnamese or English, now gets a read-only preview. It answers one question: what would the existing domain rules say if this update ran now? It does not run the update.

Command: `agent_cli.py step preview --request "<user words>" [--test-database]`

The preview never:

- authorizes anything or creates a pending confirmation;
- reserves, claims, writes a ledger row or updates a row.

`READY_FOR_CONFIRMATION` means only that the domain would accept the update. The result contains no command, argv or confirmation instruction, because Step Update confirmation (NL4C) does not exist.

## 2. Domain transition rules (reused, not invented)

Every check is the write path's own (`transition_repository.transition_step` / `engine.propose_step_transition`), applied in the same order to the read snapshot:

1. **Transition table.** `state_machine.validate_step_transition` runs without `allow_reopen`:
   - PENDING → READY, BLOCKED, SKIPPED or SUPERSEDED
   - READY → IN_PROGRESS, BLOCKED, SKIPPED or SUPERSEDED
   - IN_PROGRESS → BLOCKED, COMPLETED or SUPERSEDED
   - BLOCKED → READY or SUPERSEDED
   - COMPLETED → SUPERSEDED
   - SKIPPED and SUPERSEDED are terminal.
   - Reopen (COMPLETED→READY, SKIPPED→READY) is reported as `REOPEN_NOT_PREVIEWED` and never assumed.
2. **Dependencies.** For READY, IN_PROGRESS and COMPLETED, `evaluate_dependency_readiness` runs. The unmet direct predecessors are listed in sequence order, with `unmet_transitive_count`.
3. **Gates.** For any `APPROVAL_GATE` step, the gate is evaluated by `resolve_database_gate` over this Project's own revisions, approvals and procurement records, just as the locked write snapshot does. A gate with no database evaluator (for example "Complete UAT acceptance") gets no gate result on the write path, so it can never be met through the CLI. The preview reports it as `NO_DATABASE_GATE_EVALUATOR` and blocks.
4. **Merchant activation.** Completing a step of an `INTEGRATION_NEW_MERCHANT` Project can activate the Merchant. That check needs the locked write snapshot, so the preview reports `MERCHANT_ACTIVATION_NOT_PREVIEWED` and never `READY`.
5. **Planner.** When nothing above blocks, `propose_step_transition(..., expected_version=<stored step version>, gate_required, gate_result)` must itself accept the plan. Its `event_type`, `expected_version` and `new_version` are reported. Any rule the planner raises becomes `DOMAIN_REJECTED`, never `READY`.

The simulation is never done by writing and then rolling back.

## 3. Architecture changes

| File | Change |
|---|---|
| `agents/tools/merchant/step_preview.py` (new) | `build_step_update_preview`: resolve, evaluate, report. Pure reads over `MerchantReadRepository`. |
| `agents/tools/merchant/project_nl.py` | STEP_UPDATE parsing extracts `step_reference` (number, VN name after `bước`, or English name before `step`) and `target_status`. The step-update verbs gain `bắt đầu`/`bỏ qua`/`start`/`skip`, and an English name may be up to 6 words. "… đã hoàn thành chưa?" and "Is … step …" remain reads. A request naming two steps gets no step. |
| `agents/tools/merchant/project_status.py` | `resolve_merchant_phrase` and `resolve_project` are extracted so that NL4A and NL4B bind Projects identically. NL4A behaviour is unchanged. |
| `read_commands.py`, `cli.py`, `cli_contract.py`, `agent_cli.py` | Adds the `step preview` read command. It is allowed to name `--test-database`; `step update` and every other read still cannot. |
| `hooks/merchant_preview_delivery.py` | A `ReadResultContract` table covers both read results. `record_read_evidence` and `_read_delivery_decision` replace the status-only versions. The step preview is a terminal contract. |
| `hooks/intent_gate.py` | An unscoped `STEP_UPDATE` is downgraded to `merchant_read` (`risk_level read_only`, no confirmation), alongside Project create, status and list. |
| `merchant-manager.md`, `solve.md`, `CLAUDE.md` | Documents the NL4B section, the command row, lead delivery guidance and the adapter exception list. |

**Project and Step binding.**
- A Project is bound by exact id, exact title, or Merchant plus title. Several matches, or a partial title with no Merchant, return candidates and a question.
- A step is bound by its exact `sequence_number`, or through `resolve_step_entity` with UUID or exact `STEP_NAME` only.
- A partial name, even a single match, is offered as a candidate and never bound. Duplicate exact names also return candidates.
- A missing target, a negated request ("Đừng đánh dấu…"), a missing Project, an unknown step or two named steps each return `NEEDS_CLARIFICATION`.

## 4. CLI / JSON contract

```json
{
  "success": true, "mode": "STEP_UPDATE_PREVIEW", "database_target": "test|runtime",
  "outcome": "READY_FOR_CONFIRMATION | BLOCKED | NEEDS_CLARIFICATION",
  "read_only": true, "executable": false, "confirmation_available": false, "authorization": null,
  "query": {"kind", "merchant_phrase", "project_phrase", "project_id", "step_reference", "target_status"},
  "merchant": {"merchant_id", "code", "name", "match_kind"},
  "project": {"project_id", "title", "status", "version", "project_type", "workflow_variant", "requires_procurement", "match_kind", ...},
  "step": {"step_id", "sequence", "name", "status", "step_type", "version", "is_optional", "condition_key", ...},
  "transition": {"current_status", "target_status", "supported", "is_reopen", "event_type?", "expected_version?", "new_version?"},
  "unmet_dependencies": [step...], "unmet_transitive_count": 0,
  "gate": null | {"required", "kind", "database_verifiable", "all_met", "blocking_codes", "missing_roles", "approved_roles", "document_revision_id?"},
  "blocking": [{"code", "message"}],
  "project_state": {"step_counts", "current_steps"},
  "candidates": [...], "clarifications": [...]
}
```

**Blocking codes:**
- `ALREADY_IN_STATUS`
- `TRANSITION_NOT_ALLOWED`
- `REOPEN_NOT_PREVIEWED`
- `UNMET_DEPENDENCIES`
- `GATE_NOT_MET` (with gate `blocking_codes`, for example `MISSING_DOCUMENT_REVISION`, `MISSING_REQUIRED_APPROVALS` or `NO_DATABASE_GATE_EVALUATOR`)
- `MERCHANT_ACTIVATION_NOT_PREVIEWED`
- `DOMAIN_REJECTED`

**Delivery.** The teammate's report carries the CLI object exactly once after `MERCHANT_STEP_PREVIEW_JSON:`. If the capture can't be verified, the report starts with `STEP_UPDATE_DELIVERY_FAILED:` and has no block. The `DELIVERY_FAILED` outcome in the spec is this marker.

## 5. RED / GREEN evidence

RED runs used a disposable `git worktree` at HEAD, with the editable `claude` finder replaced so that the worktree's copy was imported. The live hooks were never swapped, and the worktree has since been removed. Each run combined the NL4B tests, NL4A tests and CLI-contract tests.

| Variant | Result |
|---|---|
| R0: HEAD code + NL4B tests | collection error: `No module named …step_preview` |
| R1: HEAD `project_nl.py` | **39 failed**, 88 passed (no step reference or target; delivery tests cascade) |
| R2: HEAD `intent_gate.py` | **3 failed**: unscoped step update blocked with "needs explicit confirmation … external_write" |
| R3: HEAD `cli_contract.py` + `agent_cli.py` | **2 failed**: `step preview --test-database` rejected; READ_COMMANDS mismatch |
| R4: HEAD `merchant_preview_delivery.py` | **4 failed**: a READY step-preview report denied as a Project-preview READY claim; a BLOCKED preview with a READY claim accepted; an unverified capture not enforced |
| GREEN: all NL4B | **127 passed** |

**Unit tests (`tests/merchant/test_nl4b_step_preview.py`, 44 tests).** These use a read-only fake whose every non-read attribute fails the test, with timezone-aware datetimes. They cover:

- VN and EN parsing, and reads versus updates;
- eligible READY with identity and versions;
- unsupported transitions, already-in-status and unmet dependencies;
- optional skip, and a SKIPPED step that is never completed or reopened;
- a DB gate without evidence, a DB gate with a stored PARTNER approval, and another Project's revision never satisfying the gate;
- a gate with no evaluator, and Merchant activation;
- six clarification shapes, partial step names and duplicate exact names;
- read-only proof (flags, no argv, confirmation or operation text, reader data unchanged);
- intent-gate downgrade on test and runtime;
- the adapter's test-database isolation;
- delivery: exact object, missing, altered or duplicated block, confirmation, scope or operation text, a READY claim on BLOCKED, unverified capture, forged `executable`, a block with no capture, and `record_pending` patched to raise.

**Intentional test changes:**
- NL4A `test_explicit_step_update_still_needs_confirmation` is now `…_runs_only_as_a_read_only_preview`.
- The NL3 `test_other_writes_still_need_explicit_confirmation` step-update case is removed.

Both previously asserted that an unscoped step update was blocked for `--confirm`. NL4B makes it a read-only preview with no scope by design. Merchant create and mixed requests still require confirmation.

## 6. PostgreSQL results

`tests/merchant/test_nl4b_step_preview_postgres.py` ran 8 tests, all passed, through `prepare_agent_cli_argv` → `cli.dispatch_read_command` → `MerchantReadRepository` on `coding_agent_merchant_test`.

**Fixtures.** Two disposable `PYTEST_NL4B_` Merchants and three Projects, created by `MerchantWorkflowRepository.create_project`:
- FRESH: as created.
- STARTED: steps 1–4 COMPLETED and the gate at step 5 IN_PROGRESS.
- The FRESH title again under the second Merchant.

The fixture asserts that the whole-table snapshot is identical after every test and that no `PYTEST_NL4B_` rows are left.

**Cases:**
- READY for start step 1 (expected version 1 → new version 2);
- an English 5-word step name with unmet dependencies [2, 3];
- READY→COMPLETED not allowed;
- the Partner gate blocked with `MISSING_DOCUMENT_REVISION`;
- SKIPPED step 6: completion not allowed and reopen not previewed;
- the same title under two Merchants returns candidates;
- a partial "review" step offers steps 2 and 3.

**Real CLI subprocess** (`agent_cli.py step preview … --test-database` on the live acceptance Projects, reads only):
- "Đánh dấu bước Legal review của Project Beta Nguyễn Văn Cừ của Merchant Beta Cinemas là hoàn thành…" → `BLOCKED` (`TRANSITION_NOT_ALLOWED`, `UNMET_DEPENDENCIES`). Step 2 is PENDING v1; the Project is v1. `executable=false`, `confirmation_available=false`, `authorization=null`.
- "Bắt đầu bước 1 của Project Beta NL3 Confirmation Test…" → `READY_FOR_CONFIRMATION` (READY → IN_PROGRESS).
- `agent_cli.py step update --test-database` → exit 2, "do not match the allowlisted CLI contract".

**Test-DB integrity hash** (sha256 over every `merchant_ops` table): `71d315c99d0b5cdbfdb5588b07ee7f307736a308dc6e980f7f7885b87e0322a7`. It was identical at the NL4B start, before and after the live CLI reads, and after the full suite. Row counts: 2 merchants, 3 projects, 70 steps, 70 dependencies, 7 events, 18 claims, 2 ledger rows, 0 `PYTEST%`.

## 7. Security validation

- **No write authority.** The intent gate's NL4B branch only downgrades: operations become `merchant_read`, `risk_level` becomes `read_only` and `requires_confirmation` is false. It applies only with no `--merchant-scope` and no conversational confirmation, and it never creates a scope. The tests assert `merchant_scope is None`.
- **No pending confirmation.** Step-preview evidence is recorded by `record_read_evidence` and returns before the Project-preview branch, which is the only caller of `record_pending`. The test patches `record_pending` to raise.
- **Capture is source-backed.** A capture is VERIFIED only when all of these hold:
  - the CLI JSON is exact;
  - the mode is `STEP_UPDATE_PREVIEW`;
  - the target equals the command target, which equals the trusted run target;
  - `read_only is True`, `authorization is None`, `executable is False` and `confirmation_available is False`;
  - the teammate's pane is verified.

  A forged `executable: true` is UNVERIFIED.
- **Delivery is terminal.** A verified step preview must appear exactly once and identically. The report may not carry `MERCHANT_PREVIEW_OPERATION_JSON`, `PREVIEW_DELIVERY_FAILED`, `confirmation_command`, `--merchant-scope` or Project-create argv. Its prose may not claim READY_FOR_CONFIRMATION unless the captured outcome is READY.
- **Isolation.** Writes remain unreachable from the adapter, and the database target comes from the trusted run.
- **Hook safety.** `py_compile` and a real import of `merchant_preview_delivery`, `intent_gate` and `policy_gate` ran after each hook edit. The policy gate was never disabled or bypassed.
- **Runtime Direct EXECUTE** is unchanged: `RUNTIME_DIRECT_EXECUTE_ENABLED = False` (`.claude/hooks/merchant_direct_handoff.py:63`).

## 8. Full regression

- `pytest`, full suite, final run: **3915 passed, 20 skipped, 1 xfailed, 0 failed**, 97 subtests passed.
- The earlier full run had 1 failure: the NL3 step-update case above, an intentional semantic change. Removing that parametrized case accounts for the unchanged pass count.
- `python .claude/system_test.py`: 80/80 passed.
- `git diff --check`: clean.

## 9. Controlled live read-only test script

Run each prompt in a fresh interactive `/solve` session in psmux. Each must run as `merchant_read` with no `--confirm`, as one `merchant-manager` `step preview … --test-database` call, and arrive as a single `MERCHANT_STEP_PREVIEW_JSON` report.

Record the test-DB hash before and after with the read-only `db_hash.py` (no file redirection). The hash must not change.

1. `/solve Đánh dấu bước Legal review của Project Beta Nguyễn Văn Cừ của Merchant Beta Cinemas là hoàn thành trên database test`. Expect BLOCKED: TRANSITION_NOT_ALLOWED (PENDING→COMPLETED) and UNMET_DEPENDENCIES on step 1.
2. `/solve Bắt đầu bước 1 của Project Beta NL3 Confirmation Test trên database test`. Expect READY_FOR_CONFIRMATION, with the lead stating that nothing was updated and no confirmation exists yet.
3. `/solve Mark step 5 of project Beta Nguyễn Văn Cừ as completed on the test database`. Expect BLOCKED (not allowed from PENDING, dependencies, gate).
4. `/solve Đánh dấu bước review của Project Beta Nguyễn Văn Cừ là hoàn thành trên database test`. Expect NEEDS_CLARIFICATION, with candidates Legal review and Accounting review.
5. `/solve Bước Legal review của Project Beta Nguyễn Văn Cừ đã hoàn thành chưa trên database test?`. Expect an NL4A status read, not a preview.

Pass criteria for every prompt:
- no `--merchant-scope`, confirmation command or argv anywhere in the lead output;
- no new claims, ledger rows, events or step-version changes;
- the teammate is released, or reused, as `IDLE_REUSABLE`.

## 10. Remaining limitations

- No Step Update confirmation or execution (NL4C/NL4D). READY is advisory only.
- Reopen, Merchant-activation completion and approval gates with no database evaluator are never READY by design.
- The preview's planner time is "now". The real write re-checks everything under lock, so state can change between the preview and any future NL4C confirmation.
- Step names are matched exactly (case- and accent-folded by the resolver). Paraphrases ("legal check") get NOT_FOUND or a candidate and a question.
- `bỏ qua` / `skip` is read as a state verb: "Bỏ qua bước 5" means SKIPPED. A request naming two target states asks.
- A step-preview message in a scoped (`merchant_execute`) run is not a preview contract; such runs report through `TEAM_RESULT_JSON`, as before.

## 11. GO / NO-GO

**GO for NL4B (read-only preview), pending the live read-only script in section 9.** All acceptance checks pass:

- no write path was added;
- no authorization, pending confirmation, claim or ledger row can result;
- the test-DB hash is unchanged;
- Runtime Direct EXECUTE stays disabled;
- NL1–NL4A behaviour is preserved, apart from the documented intentional change for unscoped step updates.

Nothing was committed or pushed.

# CP12H.NL2 — Natural-Language Project Creation on the Test Database

Branch `feat/cp7-9-merchant-reliability`. The baseline is `204bcde` plus the uncommitted NL1 working tree, which is preserved. Nothing is committed or pushed.

## 1. Architecture

There is still one writer, the existing Direct EXECUTE pipeline. NL2 adds no second write path. It adds three things around the existing one:

1. **Preview → exact operation.**
   - `project preview` (NL1) now ends a `READY_FOR_CONFIRMATION` preview with an exact `requested_operation.argv` that carries two new values:
     - `--project-id`: a deterministic UUID derived from the basis;
     - `--expected-basis`: the preview's `basis_hash`.
   - The basis is a SHA-256 over:
     - the Merchant (id, version, account status);
     - the template (id, definition fingerprint, installed row: name, version, variant, is_active);
     - every Project of that Merchant (id, version, status, title);
     - every operation field (merchant_id, type, variant, title, requires_procurement, payment period, reused revision).
   - The preview still carries `authorization: null`, `executable: false` and `status: NOT_AUTHORIZED`.
2. **User authorization stays the typed scope.**
   - The user confirms by typing that argv as `/solve --confirm --merchant-target test --merchant-scope [...]`.
   - Intent gate, policy gate, scope hash, confirmation hash, staging, the reservation, the spend and the receipt are all unchanged, and they bind the Merchant ID, Project ID, command, payload, template and target.
   - The model's own text, the preview object and the `TEAM_RESULT_JSON` grant nothing.
3. **Trusted re-check, twice.** `verify_project_create` recomputes the assessment from authoritative state and refuses unless the operation is still ready, the basis is identical and the Project ID is the derived one.
   - **Before any spend:** in `preflight_direct_execute`, read-only.
     - A refusal (`PREVIEW_BASIS_REQUIRED`, `PREVIEW_BASIS_CHANGED`, `PROJECT_NOT_READY`, `PROJECT_ID_MISMATCH`) spends nothing and leaves no footprint.
   - **Inside the write transaction:** as a `create_project` precondition, after `SELECT … FOR UPDATE` on the Merchant row, which serialises Project creation per Merchant.
     - A change between the two checks aborts the transaction.
     - The CLI reports the error as a classified `ValueError`, so the attempt settles `FAILED` and is fenced.

**Test mode.**
- `TEST_MODE_COMMANDS` is now `{merchant create, project create}`.
- `project create` is a non-Create command, so it runs through the CP12H.5C evidence-bound path: claim, ledger and mutation in one transaction, then settlement from that evidence.
- `invoke_authorized_scope_apply` gained a test-target branch:
  - **Why:** the in-memory `RuntimeApplyAuthorization` can only be issued for a runtime confirmation.
  - **What the branch does:** for a test scope it runs the same reservation guard (`_verify_team_reservation` and `spent_authority_matches`) immediately before invoking the CLI with `--database test`. It issues no runtime capability.
- `RUNTIME_DIRECT_EXECUTE_ENABLED` is still `False`; a runtime `project create` is refused in preflight.

**Reading the test database for the preview.**
- `agent_cli.py project preview --test-database …` reads `coding_agent_merchant_test`.
- It is accepted only on `project preview`; every other command, and `--database`, are still rejected.
- It is a read, so it grants nothing; the preview reports `database_target: "test"`.

## 2. Exact write path (test target)

```text
/solve Xem trước … trên database test            (merchant_read, no confirmation)
  merchant-manager → agent_cli.py project preview --test-database --request "<user words>"
     → READY_FOR_CONFIRMATION + requested_operation.argv (NOT_AUTHORIZED)

/solve --confirm --merchant-target test --merchant-scope [argv] <description>   (user types it)
  intent_gate: validate_direct_scope(argv, "test") → scope_hash, confirmation_hash (target bound)
  policy_gate: one dispatch receipt for merchant-manager
  teammate (verified pane) → MERCHANT_EXECUTE_REQUEST_JSON (database_target "test", same argv)
  team_result_hook → staging (args must equal scope) → merchant_direct_handoff:
    preflight_direct_execute: runtime disabled? test-mode command? terminal marker?
                              DB identity coding_agent_merchant_test/merchant_test?
                              verify_project_create (read-only)          ← refuse = nothing spent
    _begin_scope_execution: EXECUTING + fresh execution_attempt_id (team state)
    invoke_authorized_scope_apply: reserve_direct_scope_authorization (spend, one use)
                                   test branch: reservation guard → cli --database test … --execute
      MerchantWorkflowRepository.create_project (evidence-bound connection, one transaction):
        execution claim → merchant FOR SHARE → template installed check →
        precondition: merchant FOR UPDATE + verify_project_create (cursor reader) →
        project + 22 steps + dependencies + PROJECT_CREATED event → ledger → claim COMPLETED → COMMIT
    settle_scope_execution: SUCCEEDED only from committed evidence; else fence (REVOKED) → FAILED,
                            or UNCERTAIN; never retried
  teammate TEAM_RESULT_JSON EXECUTE_SUCCESS (must match evidence + target) → TeammateIdle → IDLE_REUSABLE
```

## 3. Files changed in NL2 (on top of NL1)

| File | Change |
|---|---|
| `.claude/agents/tools/merchant/project_preview.py` | Split into the NL preview plus `assess_project_create` / `verify_project_create`. The basis now covers the operation fields and the installed template row. Adds the deterministic Project ID, `ProjectPreviewMismatch`, and the argv `--project-id` / `--expected-basis`. |
| `.claude/agents/tools/merchant/project_nl.py` | Handles "… for <site> under/thuộc <Merchant>". Name phrases stop at on/trên/database. |
| `.claude/agents/tools/merchant/cli.py` | `project create --expected-basis` (payload key only when given); preview reports `database_target`. |
| `.claude/agents/tools/merchant/read_commands.py` | Passes `database_target` through to the preview. |
| `.claude/agents/tools/merchant/agent_cli.py` | `project preview --test-database` (read-only, preview only). |
| `.claude/agents/tools/merchant/write_adapters.py` | Adds the in-transaction re-check when `expected_basis_hash` is present. |
| `.claude/clients/merchant/workflow_repository.py` | `create_project(precondition=…)`; `TransactionPreviewReader` (cursor-backed reads plus a Merchant `FOR UPDATE`). |
| `.claude/hooks/merchant_direct_handoff.py` | `project create` in `TEST_MODE_COMMANDS`; read-only preview verification in the preflight, before any spend. |
| `.claude/system/merchant_runtime_handoff.py` | Test-target branch: runs the reservation guard and issues no runtime capability. |
| `CLAUDE.md`, `.claude/commands/solve.md`, `.claude/agents/merchant-manager.md` | Contract text for the above. |
| `tests/merchant/test_nl1_project_preview_postgres.py` | Uses a unique Merchant word, so it cannot collide with a live "Beta" fixture. |
| `tests/merchant/test_nl2_project_create.py` (new) | 18 unit tests. |
| `tests/merchant/test_nl2_project_create_postgres.py` (new) | 8 real-pipeline tests on the test DB. |
| `cp12h_nl2_project_creation_report.md` (new) | This report. |

## 4. Tests

### Coverage map

| Required | Test(s) |
|---|---|
| Existing Merchant resolution | `test_under_merchant_wording_resolves_the_existing_merchant`; NL1 resolution tests |
| Ambiguous Merchant identity | NL1 `test_ambiguous_merchant_requires_clarification` (no `requested_operation`, so nothing can be confirmed) |
| Missing required information | `test_missing_or_foreign_confirmation_data_is_refused`; PG `test_scope_without_preview_basis_is_refused`; NL1 `test_procurement_is_asked_not_invented` |
| Stale basis_hash | `test_stale_merchant_state_is_refused`, `test_unrelated_new_project_still_invalidates_the_basis`; PG `test_stale_basis_is_refused_before_any_spend` |
| Template change | `test_template_definition_change_is_refused`, `test_uninstalled_template_is_refused` |
| Cross-merchant authorization | `test_cross_merchant_scope_is_refused`, `test_edited_operation_field_is_refused` |
| Duplicate Project | `test_duplicate_created_after_preview_is_refused`; the PG success test re-confirms the same operation → `PREFLIGHT:PROJECT_NOT_READY`, still 1 Project |
| Authorization replay | PG success test: a second execute request in the same task does not reach PostgreSQL; a fresh scope is refused before spend |
| Crash before commit | PG `test_crash_before_commit_writes_nothing_and_is_not_retried` (claim fenced REVOKED, 0 Projects, no retry) |
| Crash after commit | PG `test_crash_after_commit_is_settled_from_evidence` (ack lost → SUCCEEDED from evidence, 1 Project) |
| TOCTOU after preflight | PG `test_change_after_preflight_fails_inside_the_transaction` (FAILED, fenced, 0 Projects, never retried) |
| Test → runtime escalation | `test_test_and_runtime_confirmations_differ_for_the_same_argv`, `test_runtime_scope_still_requires_the_runtime_capability`; PG `test_runtime_confirmation_of_a_test_operation_is_refused` (`PREFLIGHT:RUNTIME_EXECUTION_DISABLED`), `test_teammate_cannot_retarget_a_test_scope` |
| No unauthorized DB writes | All refusal tests compare count+md5 of 8 tables before/after, or assert 0 Projects and authority unspent; `test_preview_marker_is_not_a_payload` |
| Lifecycle | PG success test: `EXECUTE_SUCCESS` → TeammateIdle → `IDLE_REUSABLE`; reuse dispatch (Agent → SendMessage) for the next task |

### RED/GREEN

RED was produced by mutation in a scratch copy of the working tree, with the tests run against it and the test DB available.

| Guard reverted | Tests that turn RED |
|---|---|
| `project create` removed from `TEST_MODE_COMMANDS` | 7 (the gate test + 6 PG pipeline tests) |
| Preflight basis check removed | 4 (success/replay, stale, missing basis, TOCTOU) |
| In-transaction re-check removed | 1 (TOCTOU — a Project would be created on changed state) |
| Test-target branch removed (runtime capability issuance) | 3 (no-capability unit, success, crash-after-commit) |
| Basis ignores the Merchant's Projects | 1 (unrelated new Project must invalidate) |

GREEN: all 26 NL2 tests pass (18 unit, 8 PostgreSQL).

### Full regression

- **Full suite:** `pytest -q`, test DB up: **3500 passed, 0 failed, 20 skipped, 1 xfailed, 97 subtests passed (154 s)**. That is the NL1 count of 3474 plus exactly 26; the skips and the xfail are unchanged.
- **Structural checks:** `system_test.py` passed 80/80.
- **`git diff --check`:** clean. The remaining CRLF notices are on files that were CRLF in the working copy before this checkpoint.
- **Test DB:** the read-only snapshot before and after the suite is identical (16 tables, md5). There are 16 historical `merchant-direct:` claims, all COMPLETED; no `pytest:` claims and no `PYTEST_NL*` Merchants remain.
- **Production:** the runtime DB was never connected; the suite's test fixture refuses to construct a non-test repository.

## 5. Real database evidence

- **The real pipeline tests write to `coding_agent_merchant_test`.** In each run:
  - a Project was created with the previewed ID;
  - it belonged to the seeded Merchant, with variant `OPENING_NEW_CINEMA_STANDARD`, status `PLANNED`, 22 steps (the count the preview showed), and one COMPLETED claim;
  - all rows were then removed by Merchant id and by `pytest:nl2-scope:` evidence key.
- **Live fixture on the test DB:** created explicitly for live validation and not part of any Project request.
  - Merchant `6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f`, code `NL2_LIVE_BETA`, name **Beta Cinemas**, ACTIVE.
  - Seed / status / cleanup script: `…/scratchpad/nl2_live_fixture.py`. Cleanup deletes only this Merchant, its Projects, and `merchant-scope:v1:` evidence created after the fixture.
- **Pre-check through the real agent adapter** (`agent_cli.py project preview --test-database`). This is not the harness.
  - "Create a cinema opening project for Beta Nguyễn Văn Cừ under Beta Cinemas on the test database. No procurement." gave `READY_FOR_CONFIRMATION`: Merchant Beta Cinemas (NAME match), title "Beta Nguyễn Văn Cừ", no conflicts.
  - "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm" gave the same exact operation (CANDIDATE match):

```json
["project","create","--merchant-id","6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f","--type","OPENING_NEW_CINEMA","--variant","OPENING_NEW_CINEMA_STANDARD","--title","Beta Nguyễn Văn Cừ","--project-id","7572e024-61a4-505c-bd85-365e10f384bc","--expected-basis","49d1df1e8306ca44579cafdec8cde42eacdbdbdfb98617be008c99e69daa3d23"]
```

## 6. Live harness validation (real `/solve` in psmux)

**Status: PENDING — the user must type both commands; I cannot type `/solve` for them.**

- **Automated results (sections 4–5):** these use the real hooks, the real pipeline and the real test DB, with a simulated harness team config and pane.
- **Real harness behaviour:** recorded here only after the user's runs.

1. Read-only preview (NL1 acceptance; `merchant_read`, no `--confirm`):
   `/solve Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm`
   - **Expected:** a merchant-manager teammate pane appears and runs `agent_cli.py project preview --test-database …`. It reports `READY_FOR_CONFIRMATION` and the argv above (the hash changes only if the state changed). Nothing is written.
2. Confirmed creation (only after reviewing 1). The test DB is written:
   `/solve --confirm --merchant-target test --merchant-scope <argv from step 1> Create a cinema opening project for Beta Nguyễn Văn Cừ under Beta Cinemas.`
   - **Expected:** one Project `7572e024-…` under Beta Cinemas; the teammate reports `EXECUTE_SUCCESS`; the teammate returns to `IDLE_REUSABLE`.
   - **Check:** `python …/scratchpad/nl2_live_fixture.py status`.
   - **Then:** `cleanup --apply`.

## 7. Remaining blockers and limitations

1. **The live `/solve` runs (section 6) have not happened yet.**
   - Pane identity is validated by the existing CP12H.5B logic, but not yet for this command.
   - The intent gate's real OpenAI classification is guarded deterministically (`Xem trước` → read; "Create a cinema opening project…" → execute), but the live call is untested here.
2. **The basis is strict.** Any change to the Merchant or to any of its Projects (even an unrelated one) invalidates a preview, so the user must re-preview. That is deliberate (fail closed), but it can annoy on busy Merchants.
3. **Concurrency.** Two different confirmed creations for one Merchant serialise on the Merchant row lock (`FOR UPDATE`). The second then fails `PREVIEW_BASIS_CHANGED` and is FAILED/fenced — correct, but spent.
4. **The test-target branch's capability gap.** It does not issue the in-memory runtime capability; it relies on the reservation guard plus the test repository's database identity. The window between the guard and the mutation is a function call, versus "at consume time" for runtime. That is acceptable for test mode, and it is one reason production stays NO-GO.
5. **Coverage limits:**
   - Duplicate detection stays title-based (NL1).
   - Only `OPENING_NEW_CINEMA` wording is exercised live.
   - `MEDIA_TOP_UP` previews ask for the payment period, but no NL extraction of it exists.
6. **`--test-database` and isolation.** It lets the teammate read the test DB on request, a small widening of the "adapter exposes no database selection" rule, limited to `project preview`.

## 8. GO / NO-GO

- **Test mode — GO**, conditional on the two live `/solve` runs in section 6 succeeding:
  - the read-only preview;
  - the user-confirmed creation, with lifecycle `IDLE_REUSABLE`.
  - Every automated gate above is green.
- **Production (runtime) — NO-GO.**
  - `RUNTIME_DIRECT_EXECUTE_ENABLED = False` is unchanged, and a runtime `project create` is refused before any spend.
  - Enabling it needs separate approval, a runtime read of whether Beta Cinemas exists, and a review of limitations 2–4.

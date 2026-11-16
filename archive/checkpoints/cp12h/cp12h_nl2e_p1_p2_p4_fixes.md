# CP12H.NL2E — Fix P1, P2 and P4

Branch `feat/cp7-9-merchant-reliability`; committed baseline `204bcde`. NL1–NL2C (and NL2C-FIX) remain uncommitted and are preserved. Nothing is committed or pushed.

Neither Merchant database was connected to, read or written during this checkpoint:
- The full suite ran with every Merchant credential blanked and the host set to `127.0.0.1:1` (§5).
- The live `/solve --confirm` command was not run.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False` is unchanged.

**P3 — CONFIRMED INTENDED BEHAVIOR.** One consolidated Purchase Requisition per large deal:
- PR steps 6–7 may be SKIPPED;
- PO step 10 and Payment Request step 11 stay PENDING;
- no PR dependency for PO or Payment Request.

No template, step logic or procurement schema was touched.

## Evidence from the live preview (2026-11-02, sessions `6e2ae44a` lead / `3060756f` teammate)

| | Observed |
|---|---|
| Lead dispatch | `database_target: runtime (the user did not type a --merchant-target option…)` |
| Teammate command | `agent_cli.py project preview --request "<text>" --test-database`, chosen by the teammate itself |
| CLI output | `database_target: "test"`; `merchant.match_kind: "CANDIDATE"`, `matched_text: "Beta"`, code `NL2_LIVE_BETA` |
| CLI `requested_operation.argv` | 14 tokens, **no procurement token** (`--requires-procurement` was a `store_true` flag, emitted only when true) |
| Delivery | The argv reached the lead only inside free-text `SendMessage` prose retyped by the model. The lead rebuilt the `/solve --confirm …` line from that prose. Nothing checked either copy. |

## 1. Root causes

**P1 — target consistency.**
- **No trusted target for unscoped reads.** The only trusted target was the user-typed `--merchant-target test` of a write scope. For an unscoped read, `solve.md` told the lead to write `runtime`.
- **The teammate chose the database itself.** `merchant-manager.md` told it to add `--test-database` when the user asked, so the effective target was a model decision.
- **Nothing compared the two.** The policy gate validated neither the lead's declared target nor the teammate's CLI target. `merchant_terminal_consistency.trusted_scope_binding` assumed `runtime` for every unscoped run.

**P2 — Merchant identity.**
- **Resolution already rejected the clear bad cases.**
  - `_resolve_merchant` returns no operation for `AMBIGUOUS` or `NOT_FOUND`; the clarification says "A Project request never creates a Merchant".
  - The basis hash binds `merchant_id`, `version` and `account_status`, so a stale identity was already refused.
- **But a `CANDIDATE` match was treated as exact.** It produced an operation that named the Merchant only by UUID.
  - The candidate status never reached the operation.
  - Nothing human-readable about the Merchant was part of what the user confirms.
  - Nothing at write time checked a user-confirmed identity beyond the UUID.

**P4 — operation delivery.**
- **The operation never travelled as data.** The CLI printed a structured `requested_operation`, but the only path to the lead was prose the model retyped. No hook captured the CLI output or compared the delivered copy.
- **The argv was neither explicit nor canonical.**
  - `requires_procurement=false` was represented by omission.
  - The CLI emitted no confirmation command, so the lead had to build one.
  - Scope validation accepted any token order.

## 2. Changes

| File | Change |
|---|---|
| `.claude/agents/tools/merchant/project_nl.py` | `requests_test_database(text)`: deterministic detection, over the **user's** request text, of "database test / test database / db test / cơ sở dữ liệu thử nghiệm…". A negation in the 4 preceding words keeps `runtime`. |
| `.claude/hooks/runtime_state.py` | `new_state(merchant_read_target=…)`, written only by the intent gate. `merchant_database_target(state)`: the scope's target if a scope exists, else the read target, else `runtime`; `None` if malformed. |
| `.claude/hooks/intent_gate.py` | For an unscoped `merchant_read`/`merchant_execute` run, persists `merchant_read_target`. Every Merchant envelope also shows `merchant_database_target`. |
| `.claude/hooks/policy_gate.py` | Lead→merchant-manager assignment: every declared `database_target` must equal the trusted target, and an unscoped `test` run must declare it. `_main` runs the two new PreToolUse checks below. |
| `.claude/hooks/merchant_preview_delivery.py` (new) | P1 `teammate_target_decision` and P4 `record_preview_evidence` / `preview_delivery_decision`; see below. |
| `.claude/hooks/team_result_dispatcher.py` | PostToolUse calls `record_preview_evidence`. A failure records nothing, so the delivery check fails closed. |
| `.claude/hooks/merchant_terminal_consistency.py` | An unscoped run's trusted target is now `merchant_database_target(state)` instead of a hard-coded `runtime`. |
| `.claude/agents/tools/merchant/project_preview.py` | P2: `merchant_code` is an operation field. P4: `canonical_create_argv`, `confirmation_command`, `validate_requested_operation`, and the complete `requested_operation`. Details below. |
| `.claude/agents/tools/merchant/cli.py` | `project create --merchant-code`; `--requires-procurement` is now `BooleanOptionalAction` (`--no-requires-procurement`; absent still means False). |
| `.claude/system/merchant_runtime_handoff.py` | `validate_direct_scope`: a preview-confirmed `project create` (has `--expected-basis`) must carry `--merchant-code` and be **exactly** the canonical argv. Otherwise it is rejected at the intent gate, before anything is staged or spent. |
| `merchant-manager.md`, `solve.md`, `CLAUDE.md` | Contract text: trusted target, the `MERCHANT_PREVIEW_OPERATION_JSON:` block, verbatim `confirmation_command`, CANDIDATE wording. |

**P1 enforcement (`teammate_target_decision`, PreToolUse Bash)**

- **Scope.** Applies to merchant-manager's literal `agent_cli.py` calls. The effective target is `test` only for `project preview … --test-database`. `completeness check` opens no database.
- **Trusted target.** Read from the owning lead's run state, via `find_unique_active_teammate_owner`, the run/task binding, and `merchant_database_target`.
- **A mismatch is denied, which covers:**
  - a runtime run reading test;
  - a test run reading runtime (test→runtime escalation);
  - any runtime read in a test run.
- **No verifiable owner.** A test read is denied; runtime reads keep their existing behaviour.

**P2 (`project_preview`, write path)**

- **Binding the code.**
  - `fields.merchant_code = <resolved code>` is part of the basis.
  - `assess_project_create` adds a blocking `MERCHANT_CODE_MISMATCH` when the confirmed code no longer names that Merchant.
  - `verify_project_create` refuses `MERCHANT_CONFIRMATION_REQUIRED` without a code.
- **Where it is checked.** `verify_project_create` already runs in the test-mode preflight (before spend) and inside the write transaction (`_confirmed_preview_precondition`, Merchant row locked). The confirmed Merchant is therefore re-validated in the existing execution transaction.
- **Candidate visibility.** A CANDIDATE match sets `merchant.confirmation_required` and `requested_operation.merchant_confirmation_required`. An exact match (UUID/CODE/NAME/ALIAS) does not. The candidate is still allowed: the user confirms it explicitly by typing the command, which names its code and UUID.

**P4 (`requested_operation`, capture, delivery)**

- **`requested_operation` contents:**
  - `command`, `status: NOT_AUTHORIZED`, `database_target`;
  - `merchant_id`, `merchant_code`, `merchant_name`, `merchant_match_kind`, `merchant_matched_text`, `merchant_confirmation_required`;
  - `project_id`, `project_type`, `workflow_variant`, `title`, `requires_procurement`, `expected_basis`;
  - `argv` (canonical order, procurement always explicit);
  - `confirmation_command`: `/solve --confirm [--merchant-target test ]--merchant-scope <compact JSON, ensure_ascii=False> Create the previewed Project`;
  - `note`.

  `validate_requested_operation` rejects any object whose argv or command is not exactly what its fields produce. The preview runs that check on its own output.
- **Capture (`record_preview_evidence`, PostToolUse).** The evidence is recorded only when all of these hold:
  - the call is an exact `agent_cli.py project preview` invocation (RAG output can never pose as evidence);
  - the stdout is one JSON object with `mode: PROJECT_PREVIEW`, whose `database_target` equals the command's target and the trusted target;
  - its operation passes `validate_requested_operation`;
  - the calling process is in the verified merchant-manager pane (`verified_teammate_pane`).

  It is stored as `project_preview_evidence`, bound to the run and task.
- **Delivery (`preview_delivery_decision`, PreToolUse SendMessage).**
  - **When evidence holds an operation:** the report must contain exactly one `MERCHANT_PREVIEW_OPERATION_JSON:` block that is deep-equal to it. A missing, duplicated, truncated, folded-Unicode, edited or non-JSON block is denied before it reaches the lead.
  - **When there is no evidence:** any block is denied.
- **Lead side (`solve.md`).** The lead shows `confirmation_command` verbatim and lists the fields; it never rebuilds the command from prose.

## 3. RED/GREEN

**Test file.** `tests/merchant/test_nl2e_p1_p2_p4.py`, 61 tests:
- real intent gate, policy gate, team state and hook entry points;
- the NL1 fake reader, extended with the live fixture shape (`NL2_LIVE_BETA` / "Beta Cinemas", so "Beta" is a CANDIDATE);
- no database.

- **RED 0.** Before any production change, the file failed at collection: none of the contract existed.
- **Per-issue RED.** Each fix was disabled on copies of the files, then all files were restored, with checksums verified identical.

| Disabled | Result | Failing tests |
|---|---|---|
| P1 (detection, lead-target rule, teammate-target gate) | **17 failed** / 44 passed | detection; intent-gate binding; lead must declare test / cannot escalate runtime→test; teammate test-only reads; runtime run cannot switch to test; unowned test read; entry-point gate; and the capture/delivery tests whose trusted owner target is now `runtime` |
| P2 (code requirement, code check, candidate flag) | **4 failed** / 57 passed | candidate requires confirmation; scope without code; stale/re-assigned code; another Merchant's code |
| P4 (capture, delivery check, canonical scope, operation validator) | **19 failed** / 42 passed | malformed/reconstructed operations (9 cases); canonical scope; capture; lossy delivery (6 cases); unbacked block; entry-point capture + delivery |
| none | **GREEN 61/61** | |

**Tests that pass in every RED run.** Some properties were already enforced before NL2E and are pinned here:
- ambiguous Merchant → no operation;
- unknown Merchant → never a Merchant create;
- stale version or INACTIVE → refused;
- replay after creation → refused (`PROJECT_NOT_READY`, duplicate);
- the delivered operation grants no authority.

**Existing tests updated to the new contract.** No assertion was weakened.
- `test_nl1_project_preview.py`: `fields` now includes `merchant_code`.
- `test_nl2_project_create.py::test_cross_merchant_scope_is_refused`: still refused, now earlier, as `PROJECT_NOT_READY` (code mismatch) instead of `PREVIEW_BASIS_CHANGED`.
- `test_hook_utf8_boundaries.py`: the Unicode policy-gate case uses a runtime preview. A `--test-database` read with no trusted test run is now correctly denied.

**Unicode, scope binding, stale previews and replay.** These are covered by:
- the round trip of `confirmation_command` through `intent_gate.split_merchant_scope` and `validate_direct_scope`;
- the folded-title rejections;
- the existing NL2 basis tests (template/merchant/project changes) and the single-use scope tests in the full suite.

## 4. Regression

| Check | Result |
|---|---|
| Focused (NL2E, NL1, NL2, UTF-8 hooks) | 133 passed |
| Full pytest, Merchant DB disabled | **3557 passed, 1 failed, 80 skipped, 1 xfailed, 97 subtests passed** (162 s). Previous run: 3557 passed / 20 skipped. The difference is +61 new tests and 60 DB-backed tests now skipped. |
| The 1 failure | `test_database_unavailable_is_refused_before_spend` is an artifact of the blanked `MERCHANT_TEST_DB_NAME`: it reports INVALID_CONFIGURATION instead of DATABASE_UNAVAILABLE. Run alone with the normal environment it **passes**; it points itself at `127.0.0.1:1`, so it cannot connect. |
| `python .claude/system_test.py` | ALL TESTS PASSED |
| `git diff --check` | clean |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` |

## 5. Database integration acceptance (authorized run on the test database)

**Authorization and scope.**
- **Authorized:** `coding_agent_merchant_test` as `merchant_test`; test-owned fixtures may be created and cleaned up.
- **Not authorized and not done:** runtime access; changes to `NL2_LIVE_BETA` or the 16 historical `merchant-direct` claims; a live `/solve` Project Create; commit or push.

**Runtime guard used for every run in this section.**
- `MERCHANT_DB_PASSWORD`, `MERCHANT_OWNER_PASSWORD`, `MERCHANT_ALERT_PASSWORD` and `MERCHANT_ADMIN_PASSWORD` were set empty. `RepositoryConfig.from_env` then raises before connecting for every non-test role.
- Every `MERCHANT_RUN_*` live or runtime opt-in was forced to `0`.
- Only the `merchant_test` credential was usable.

### 5.1 Preflight (read-only)

| Check | Result |
|---|---|
| Docker PostgreSQL | `coding-agent-rag-db` Up (healthy), `127.0.0.1:5434->5432`; PostgreSQL 16.15 |
| Effective identity | `current_database() = coding_agent_merchant_test`, `current_user = session_user = merchant_test`, `transaction_read_only = on` |
| Beta fixture | 1 row: `6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f`, `NL2_LIVE_BETA`, "Beta Cinemas", ACTIVE, version 1, row md5 `33c8c1bd282b70e4c9a9c0d7c7b78806`, 0 Projects |
| Historical claims | 16 `merchant-direct:*` rows (the only claims); ledger empty |
| Snapshot | Per-table row count and md5 of all row contents for all 17 `merchant_ops` tables; per-row md5 of the 16 claims |

### 5.2 Database-backed regression: the 60 tests previously skipped

These are the 17 files that use the test database. Without the database they gave **229 passed / 60 skipped / 1 failed**; the failure is the known environment artifact from §4. Against the test database they gave **290 passed, 0 skipped, 0 failed**. Matching the JUnit results test by test, **all 60 previously skipped tests passed**:

| File | Tests | Verifies |
|---|---:|---|
| `test_nl2_project_create_postgres` | 8 | Previewed `project create` through the real intent gate, policy gate, reservation, evidence transaction and idle settlement, covering: **exact payload**; **UTF-8 title stored as `"<short> Nguyễn Văn Cừ"`**; 22 steps; **replay creates no duplicate** (`PREFLIGHT:PROJECT_NOT_READY`, no spend); **stale basis** refused before spend; scope without basis refused; **change after preflight fails inside the transaction** (claim REVOKED); **crash before and after commit**; runtime confirmation of a test operation refused; **teammate cannot retarget** a test scope |
| `test_nl1_project_preview_postgres` | 3 | Real preview resolves Beta and mutates nothing; duplicate blocks; stale candidate rejected |
| `test_cp12h5c_attempt_evidence_postgres` | 10 | Mutation and evidence commit together; rollback and fence; replay never writes twice; crash before/after commit; retention limited to the test database |
| `test_execution_evidence_postgres` / `_claims_` / `_ledger_` | 16 / 5 / 4 | Claim identity, generation, integrity, concurrency, ledger commit/replay/rollback |
| `test_atomic_create_postgres`, `test_project_create_postgres`, `test_protected_merchant_create`, `test_reserved_execution_e2e`, `test_direct_test_target_execution`, `test_direct_execute_end_to_end`, `test_migrations::TestPostgresIntegration` | 3, 3, 1, 3, 2, 1, 1 | Atomic create, rollback, duplicate id, reserved executor, **exact test target**, test-database migration integration |

**New DB-backed tests for the P2 merchant-code binding.** These were added to `test_nl2_project_create_postgres.py`; no existing test was changed.

| Test | Proves |
|---|---|
| `test_merchant_code_of_another_merchant_is_refused_before_any_spend` | A canonical scope naming another Merchant's code (`NL2_LIVE_BETA`, read only) → `PREFLIGHT:PROJECT_NOT_READY`, no spend, database unchanged (**cross-merchant**) |
| `test_transaction_precondition_rechecks_the_confirmed_merchant_code` | The real `_confirmed_preview_precondition` on a real `dict_row` write-transaction cursor passes for unchanged state. After the code is re-assigned in the same transaction, it raises `MERCHANT_CODE_MISMATCH`. Both transactions roll back and the Merchant is unchanged (**transactional merchant-code verification**) |
| `test_merchant_code_changed_after_preflight_fails_inside_the_transaction` | The code changes between preflight and write → the Direct EXECUTE attempt is FAILED, no Project is created, and the claim is REVOKED |

**RED/GREEN for the new tests.** The 3 tests fail when only the `MERCHANT_CODE_MISMATCH` check is disabled, and pass after it is restored (file checksum verified identical).

### 5.3 Full regression (normal test-database configuration, runtime guard)

| Check | Result |
|---|---|
| Full pytest | **3621 passed, 0 failed, 20 skipped, 1 xfailed, 97 subtests passed** (237 s). 3621 = 3557 (NL2C-FIX baseline) + 61 NL2E unit + 3 NL2E DB-backed. |
| 20 skipped | All are explicit opt-ins, identical to every earlier baseline. **10** runtime read-only or initialization gates (`MERCHANT_RUN_RUNTIME_*`) are outside this authorization. **10** `*_live` test-database lifecycle suites need `MERCHANT_RUN_LIVE_TESTS=1`; they were never part of the 60 and were not requested. |
| 1 xfailed | `test_reserved_execution_toctou::test_reassignment_between_validation_and_write`, the documented known TOCTOU, unchanged |
| Unexpected skips | none |
| `python .claude/system_test.py` | ALL TESTS PASSED |
| `git diff --check` | clean |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` (`merchant_direct_handoff.py:63`) |

The §4 environment-artifact failure does not occur with the real test configuration.

### 5.4 Reconciliation (read-only snapshot after all runs)

| Item | Before | After |
|---|---|---|
| Identity | `coding_agent_merchant_test` / `merchant_test` | same |
| `merchant_ops` tables (17): row count + md5 of all row contents | recorded | **all 17 identical** (`merchants` 2, `projects` 1, `project_steps` 26, `project_step_dependencies` 26, `project_events` 5, `merchant_execution_claims` 16, `merchant_execution_ledger` 0, `schema_migrations` 6, templates 4/64/68, others 0) |
| Beta fixture row md5 | `33c8c1bd…7806`, 0 Projects | identical, 0 Projects |
| Historical `merchant-direct` claims (per-row md5) | 16 | **16, identical** |
| Claim / ledger key prefixes | `{merchant-direct: 16}` / `{}` | same: no leftover `pytest:` claims, ledger rows, Projects or Merchants |

All test-owned records were cleaned up. Sequence counters and server statistics are not part of the content comparison.

## 6. Remaining limitations

- **The `*_live` lifecycle suites were not run.** These 10 test-database suites (`MERCHANT_RUN_LIVE_TESTS=1`) were outside this request and skipped in every baseline.
- **No runtime test of any kind was run.** This was by design.
- **Test-database detection is a fixed phrase list over the user's text.** A request that asks for the test database in other words gets `runtime`, which is safe: the test read is then refused, not escalated. A negation further than 4 words away would be misread as a request for `test`, which is read-only.
- **The lead's final answer is not machine-checked.** The gate guarantees the lead receives the exact operation. Showing `confirmation_command` verbatim is an instruction in `solve.md`. A mistyped command still fails safely at the intent gate (canonical argv, required code) or at the basis check.
- **Previously printed argv is now refused.**
  - Older previews (without `--merchant-code` / explicit procurement) produce argv that `validate_direct_scope` refuses. The live preview from 2026-11-02 must be **re-run**.
  - A non-preview `project create` (no `--expected-basis`) is unaffected; it is not runnable in test mode, and runtime is disabled.
- **The capture binds to the latest preview of the task.** If the teammate previews twice, only the last operation can be delivered.
- **The new P1/P4 hook wiring has not yet been exercised by a real psmux teammate.** It is covered through the real hook entry points in tests; the next live preview is its first real use.

## 7. GO / NO-GO

- **P1, P2, P4 code: GO.** RED/GREEN tests cover each fix, the database integration passed, and there are no regressions.
- **Fresh read-only `/solve` preview: GO.** No restart is needed: only code in hooks that are already registered changed. Run:

  ```text
  /solve Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm
  ```

  Expected:
  - envelope `merchant_database_target: test`;
  - the lead's assignment declares `database_target: test`;
  - the teammate's `--test-database` read is allowed;
  - the report carries exactly one `MERCHANT_PREVIEW_OPERATION_JSON:` object with `merchant_code: NL2_LIVE_BETA`, `merchant_match_kind: CANDIDATE`, `merchant_confirmation_required: true`, `requires_procurement: false` and `--no-requires-procurement` in the argv;
  - the lead shows `confirmation_command` verbatim.

  Live acceptance is not claimed until that run succeeds.
- **Controlled test-database Project creation: NO-GO** until that preview passes live. Then you type its exact `confirmation_command`, after confirming Beta Cinemas (`NL2_LIVE_BETA`) is the intended Merchant.
- **Production: NO-GO.** Runtime Direct EXECUTE remains disabled.

## 8. CP12H.NL2E-P4: missing confirmation command in the live preview

### 8.1 Evidence (live run 2026-11-02 09:29Z; lead `3a21ef05`, teammate `9019434c`)

| Boundary | What happened |
|---|---|
| CLI JSON | **Complete and valid.** `READY_FOR_CONFIRMATION`, `database_target: test`; the operation had `merchant_id 6e0c1a2b-…`, `merchant_code NL2_LIVE_BETA`, `project_id 30fffeaf-e6b5-5119-b078-52c934e1821e`, the Unicode title, a 17-token argv ending `--no-requires-procurement`, `expected_basis 2f26fb44…3ea5` and `confirmation_command`. `validate_requested_operation` passes on it. |
| Bash `tool_response` | `stderr: ""`. The **stdout began with a Python `FutureWarning`** (`google/api_core/_python_version_support.py:254`, printed by the system `python` the teammate ran), followed by the JSON with CRLF line endings. Claude Code's Bash tool merges stderr into stdout. |
| PostToolUse capture | `_exact_json_object` required stdout to be exactly one JSON object, so `json.loads` failed and **no evidence was stored**. Team state `project_preview_evidence: null`. Replaying the real stdout through the old parser returns `None`. |
| Teammate `SendMessage` #1 | Carried the operation block. **Denied**: "no Project preview operation was captured… remove the block". |
| Teammate `SendMessage` #2 | `READY_FOR_CONFIRMATION` without the block, merchant_id, argv or command. **Accepted**: the gate only rejected blocks when there was no evidence. |
| Lead | Correctly refused to rebuild the command and reported it missing. |

**Root cause.**
1. **Capture boundary (primary).** The exact-JSON parser broke on stderr noise that Claude Code merges into stdout. The CLI did emit the operation; the capture discarded it. The evidence validator never saw it, and the CLI and the lead were not at fault.
2. **Delivery contract (secondary).** Without evidence, the gate let a READY_FOR_CONFIRMATION report through without any operation, so the result read as actionable but was incomplete.

### 8.2 Changes

| File | Change |
|---|---|
| `.claude/hooks/merchant_tool_result_contract.py` | `_exact_json_object` (shared by the preview, completeness and execute captures) ignores **leading** non-JSON lines. The first line starting with `{` must begin exactly one JSON object that runs to the end of stdout; trailing text or a second object is still rejected. |
| `.claude/hooks/merchant_preview_delivery.py` | **Capture.** Evidence now has a `status`. A verified preview is `VERIFIED`, and READY must carry an operation while non-READY must not. A preview call whose output can't be verified, whose target differs, or whose pane can't be verified is stored as `UNVERIFIED` with no operation. |
| | **Delivery.** With `VERIFIED` READY evidence, the exact block is required, as before. Otherwise any `READY_FOR_CONFIRMATION` claim, operation block, argv, `--merchant-scope` or `confirmation_command` is denied with one satisfiable instruction: resend once as `PREVIEW_DELIVERY_FAILED: <reason>` with the read-only findings, and do not rerun. A verified operation cannot be dropped or downgraded. |
| `merchant-manager.md`, `solve.md` | The `PREVIEW_DELIVERY_FAILED` report shape. The lead reports it as non-actionable, with no command and nothing rebuilt. |

The operation still comes only from CLI stdout captured in the verified pane. Teammate text is only compared against it and never used as its source. A failed delivery creates no scope and grants nothing.

### 8.3 Tests: `tests/merchant/test_nl2e_p4_delivery.py` (34)

| Requirement | Tests |
|---|---|
| Live failure | Warning prefix + CRLF stdout is captured as `VERIFIED`, and its exact block is delivered |
| No widened parsing | Text after the object, a second object, a non-JSON first `{` line or pure log text → rejected; clean and prefixed objects parse identically |
| Missing fields | Each of `merchant_id`, `merchant_code`, `project_id`, `project_type`, `workflow_variant`, `title`, `requires_procurement`, `expected_basis`, `database_target`, `argv`, `confirmation_command` → the operation is invalid |
| Block missing merchant_id, argv or confirmation_command; truncated or reordered argv; Unicode folded, mojibake or `\u`-escaped | refused |
| Valid exact operation (Unicode) | delivered |
| Lead-facing report that lists fields but omits the operation | refused, both when verified and when unverified |
| READY or reconstructed `--merchant-scope` / argv without evidence | refused |
| No resend loop | Identical bad reports get the identical denial; the stated `PREVIEW_DELIVERY_FAILED` correction is accepted once; no scope is created |
| Non-READY preview reported as READY | refused; an honest clarification report is accepted |

One NL2E test was updated: an inconsistent preview now records `UNVERIFIED` instead of nothing.

**RED/GREEN.**

| Reverted | Result |
|---|---|
| Strict parse restored | **5 failed** (live warning capture, prefixed parse, Unicode delivery, cannot drop a verified operation, non-READY capture) |
| Old gate (block-only) restored | **7 failed** (READY without operation, the 4 reconstructed/READY variants, no resend loop, non-READY as READY) |
| Both restored, file checksums verified | **95/95** across the NL2E files |

**Real evidence replay.** The actual live stdout and command from the failed run now produce `VERIFIED`, with all required fields and the exact `confirmation_command`.

### 8.4 Regression

| Check | Result |
|---|---|
| Focused (NL2E, NL2E-P4, tool-result contract) | 110 passed |
| Full pytest (database disabled: no DB access in this checkpoint) | **3591 passed, 1 failed, 83 skipped, 1 xfailed, 97 subtests passed**. 3591 + 63 DB-gated skips + 1 = 3655 = 3621 (§5.3) + 34 new. The 1 failure is the known blanked-DB-name artifact (§4); it passes when run alone. |
| `system_test.py` | ALL TESTS PASSED |
| `git diff --check` | clean |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` |
| Database | Not connected. No `/solve --confirm`. Nothing committed or pushed. P1, P2 and P3 behaviour is unchanged (their tests pass). |

### 8.5 GO / NO-GO

- **Fresh read-only preview: GO.** No restart is needed: only code in registered hooks changed. Same request:
  ```text
  /solve Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm
  ```
  Expected:
  - the teammate's first report carries the exact `MERCHANT_PREVIEW_OPERATION_JSON:` object and is accepted;
  - the lead shows `merchant_id`, the fields and `confirmation_command` verbatim.

  If capture still fails for another reason, the report must now arrive as `PREVIEW_DELIVERY_FAILED`, never as an incomplete READY.
- **Test-database Project creation: NO-GO** until that preview passes live and you confirm Beta Cinemas (`NL2_LIVE_BETA`).
- **Production: NO-GO.**

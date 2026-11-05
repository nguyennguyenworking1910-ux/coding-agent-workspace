# CP12H.NL4A — Natural Language Project Discovery & Status

Date: 2026-11-05 · Branch `feat/cp7-9-merchant-reliability` · Baseline `1b56a0b`

Nothing was committed or pushed. No Project Create or Step Update was run. Only NL4A was implemented; NL4B, NL4C and NL4D were not started.

## 1. Architecture investigation (Phase 1)

| Existing piece | Finding | Reused how |
|---|---|---|
| Read commands (`project list/show/resolve/blockers`) | They take IDs, and the agent CLI fixes them to **runtime**. The only test-database read was `project preview --test-database`. | A natural-language status read on the test database needs one new read command. It follows the same pattern as `project preview`. |
| `MerchantReadRepository` (`list_merchants`, `list_projects`, `get_project_detail`) | Read-only connections. `get_project_detail` returns steps with `step_type`, plus dependencies, documents, approvals and procurement rows. | The **only** data source. There is no new SQL and no new database path. |
| `project_preview._resolve_merchant` | Label-aware Merchant resolution (NL3A), with candidate and ambiguity handling | Reused as-is |
| `project_entity_resolver.resolve_project_entity` | Merchant-scoped resolution by UUID, exact title or whole-token candidate. Several matches give AMBIGUOUS. | Reused for Merchant-scoped discovery |
| `dependencies.dependency_ready_step_ids` / `evaluate_dependency_readiness` | The domain readiness rule: only COMPLETED predecessors are met. | Reused unchanged. On the real no-procurement Projects, the SKIPPED steps 6–7 have **no** dependency edges (5→8→9→10→11), so readiness is correct without reinterpreting SKIPPED. |
| `project_nl.interpret_project_request` | Already had `PROJECT_STATUS` and `PROJECT_LIST`. Two gaps (below) included a read-to-write misclassification. | Fixed narrowly |
| Intent gate (NL3 read-only downgrade) | `Tạo project …` already runs as a read without `--confirm` | Extended to status and list questions |
| Preview delivery gate (`merchant_preview_delivery`) | Trusted PostToolUse capture plus an exact-block delivery contract | The same mechanism is used for status results |

**Parser defects found (exact live examples):**

- `Những bước nào đã hoàn thành và còn vướng ở đâu?` → **`STEP_UPDATE`, `write_requested: true`**. The update clause `bước … đã hoàn thành` matched a *question* about completed steps. This is a read-to-write reclassification.
- `Các bước đang chờ của Project X là gì?` → `UNKNOWN`. "đang chờ" and "các bước" were not status words.

## 2. Architecture changes

| File | Change |
|---|---|
| `.claude/agents/tools/merchant/project_status.py` (**new**) | `build_project_status(request, reads, database_target)`: discovery and status over the read repository only |
| `read_commands.py` | `MerchantReadCommands.project_status(request, database_target)` (redacted result) |
| `cli.py` | Parser `project status --request` and dispatch, with `--database` threaded as for preview |
| `cli_contract.py` | `"project status"` added to `READ_COMMANDS`. `WRITE_COMMANDS` is unchanged. |
| `agent_cli.py` | `TEST_DATABASE_READS = {project preview, project status}`. Only these accept `--test-database`, and every other read is still runtime-only. |
| `project_nl.py` | `_STEP_UPDATE_EXPLICIT` (an update verb naming the step), `_STEP_QUESTION` (questions about steps), Merchant owner phrase for status (`của Lotte Cinema`, but not `của Project X`) |
| `intent_gate.py` | The read-only downgrade now covers `PROJECT_STATUS` and `PROJECT_LIST` (no `--confirm`) |
| `merchant_preview_delivery.py` | `record_status_evidence` (PostToolUse capture), `_status_delivery_decision` (PreToolUse contract), `command_target` for `project status --test-database` |
| `merchant-manager.md`, `solve.md`, `CLAUDE.md` | When to run `project status`, the report contract, and how the lead summarizes |
| `tests/merchant/test_cli_contract.py` | The pinned read allowlist now includes `project status`. This is a deliberate inventory change. |

## 3. Data access and resolution rules

All reads go through `MerchantReadRepository` read-only connections. The target is the trusted `database_target` (§6).

**Discovery order:**

1. **Exact Project UUID** in the request text, case-insensitive. A UUID that is unknown, or that belongs to another Merchant when a Merchant is named, gives NEEDS_CLARIFICATION.
2. **Merchant named** (`của …`, `of …`, `cho Merchant …`), resolved with the NL3A label-aware resolver. If it doesn't resolve, the result asks. Otherwise discovery runs `resolve_project_entity` within **that Merchant only**: exact title, else a unique whole-token candidate. Several matches give candidates. A Project of another Merchant is never returned.
3. **No Merchant named**: an exact title (accent and case folded) across all Merchants. Otherwise a whole-token partial title. **More than one match always gives NEEDS_CLARIFICATION** with candidates (id, title, Merchant code), so a Project is never chosen silently.
4. **No Project named** (`Những bước nào … ?`) gives NEEDS_CLARIFICATION, "Which Project do you mean?". There is no conversational memory.
5. **List** (`Liệt kê các Project của <Merchant>`): the Merchant is required, with an optional single status filter. `đang chạy` / in progress → IN_PROGRESS. `đã hoàn thành` / completed → COMPLETED. The others are PLANNED, BLOCKED, ON_HOLD and CANCELLED. Two filters in one request give a question.

**Step semantics** come only from stored rows and the domain evaluator:

- `current_steps` are steps whose stored status is READY or IN_PROGRESS. Only these are actionable.
- `dependency_ready_steps` are PENDING or BLOCKED steps whose transitive predecessors are all COMPLETED (`dependency_ready_step_ids`). They are unlocked but still PENDING, never presented as actionable.
- `waiting_steps` are the other PENDING or BLOCKED steps, each with `unmet_predecessors` (direct unmet, otherwise transitive, via `evaluate_dependency_readiness`).
- `completed_steps` and `skipped_steps` are separate, and **SKIPPED is never COMPLETED**.
- Text in the request (for example "Legal review đã xong rồi") never changes a state. This is tested.

## 4. Structured output contract (`mode: PROJECT_STATUS`)

```json
{
  "success": true, "mode": "PROJECT_STATUS", "database_target": "test|runtime",
  "outcome": "PROJECT_STATUS | PROJECT_LIST | NEEDS_CLARIFICATION",
  "read_only": true, "authorization": null,
  "query": {"kind", "merchant_phrase", "project_phrase", "project_id"},
  "merchant": {"merchant_id", "code", "name", "match_kind"} | null,
  "project": {"project_id", "title", "status", "merchant_id", "merchant_code", "merchant_name",
              "project_type", "workflow_variant", "updated_at", "requires_procurement",
              "version", "created_at", "last_updated_at", "match_kind"} | null,
  "step_counts": {"total", "PENDING", "READY", "IN_PROGRESS", "BLOCKED", "COMPLETED",
                  "SKIPPED", "SUPERSEDED"},
  "current_steps": [step], "dependency_ready_steps": [step],
  "waiting_steps": [step + {"unmet_predecessors": [step]}],
  "completed_steps": [step], "skipped_steps": [step], "approval_gates": [step],
  "evidence": {"document_revisions", "document_approvals", "procurement_records"},
  "projects": [summary], "status_filter": "…|null",        // PROJECT_LIST only
  "candidates": [summary], "clarifications": [question]
}
step = {"step_id", "sequence", "name", "status", "step_type", "branch_key"}
```

- `last_updated_at` is the latest of the Project's `updated_at` and the steps' `actual_start` / `actual_completion`. The step rows have no `updated_at` column.
- "Required approvals and evidence" are reported as the non-terminal `APPROVAL_GATE` steps plus counts of stored document revisions, approvals and procurement records.

**Delivery contract.** This is the same mechanism as the preview delivery gate.

1. `PostToolUse(Bash)` captures the exact `agent_cli.py project status` JSON as `project_status_evidence`, bound to run and task. It is `VERIFIED` only when all of these hold:
   - `mode` is PROJECT_STATUS;
   - `database_target` equals the command target, which equals the trusted run target;
   - `read_only` is true and `authorization` is null;
   - the pane is verified.

   Anything else is recorded as `UNVERIFIED`.
2. `PreToolUse(SendMessage)` enforces:

   | Capture | Report must |
   |---|---|
   | VERIFIED | carry the exact object **once** after `MERCHANT_PROJECT_STATUS_JSON:` (missing, altered or duplicated is denied) |
   | UNVERIFIED | start with `STATUS_DELIVERY_FAILED:` and carry no block |
   | none for the task | carry no status block at all |

3. The lead summarizes **only** from that object (`solve.md`).
4. The existing preview, execute and terminal contracts are unchanged.

## 5. Routing (Phase 4)

An unscoped request routed only to merchant-manager, with operations ⊆ {merchant_execute, merchant_read}, runs as a read-only `merchant_read` with no `--confirm`, even when the model labelled it a write, if its deterministic kind is any of:

- `PROJECT_STATUS`
- `PROJECT_LIST`
- `PROJECT_CREATE` (the NL3 behaviour)

This is strictly a downgrade.

**Read-to-write protection:** a step update now needs an explicit update verb that names the step (`cập nhật / hoàn thành / đánh dấu / chuyển bước`, `update/complete/mark … step`). A question about steps (`bước nào`, `các bước`, `đang chờ`, `còn vướng`, `which steps`) is a status read. Explicit step updates are still `STEP_UPDATE` and still require `--confirm` (tested). Project Create and Step Update authorization is otherwise unchanged.

## 6. Test and runtime isolation

- `--test-database` is accepted only for `project preview` and `project status`. `project list --test-database` is still rejected (tested).
- The run's trusted target comes from the user's own words (`trên database test`). The existing P1 gate holds every `agent_cli.py` read to it, and `command_target` now knows `project status --test-database`.
- Every test uses the test role, and the e2e harness refuses to build a non-test repository.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False` is unchanged.

## 7. RED/GREEN

| Stage | Result |
|---|---|
| RED: `test_nl4a_project_status.py` (43 tests), no implementation | collection error, so all 43 RED (module and contract missing) |
| `project_status.py`, parser, CLI wiring, delivery gate | 40 passed, **3 failed** (routing still blocked status questions as external writes) |
| Gate downgrade extended | **43 passed** |
| Neighbouring suites (NL1, NL2E, NL2F, NL3, NL3A, CLI contract, policy gate) | 365 passed, 1 failed: the pinned `READ_COMMANDS` inventory. Updated deliberately, then all passed. |
| `test_nl4a_project_status_postgres.py` (5) against the **real** NL2 and NL3 Projects through the real CLI argv path (`prepare_agent_cli_argv` → parser → dispatch), whole-database snapshot asserted unchanged | **5 passed**. Written after the implementation; its RED counterpart is the unit suite on the same code path. |

**Coverage.** The unit file has 43 tests and the PostgreSQL file has 5:

| Area | Tests |
|---|---|
| Vietnamese and English status questions | 7 resolve |
| Unicode title and identity | covered |
| Ambiguity | cross-Merchant title, duplicate exact titles |
| Incorrect or missing identifiers | no Project named, unknown title, unknown UUID, Project under another Merchant, unknown Merchant |
| Counts, current, dependency-ready and waiting with unmet predecessors | covered |
| SKIPPED versus COMPLETED | covered |
| Approval gates and evidence | covered |
| Conversational claims ignored | covered |
| Merchant-scoped lists and 3 status filters | covered |
| Parser | 4 reads never write; 3 explicit updates stay writes |
| Gate | 3 status questions run read-only without `--confirm` (runtime and test targets); an explicit step update still needs `--confirm` |
| Test/runtime target in CLI and policy | covered |
| Delivery | exact block accepted; missing, altered or duplicated denied; unverified gives `STATUS_DELIVERY_FAILED`; block without a run denied; no write authority |

**On real data (NL3 `ba5cc7ec`):**

- 22 steps: READY 1, PENDING 19, SKIPPED 2, COMPLETED 0.
- Current step 1. No dependency-ready steps.
- Step 2 waits on 1, step 8 on 5, Purchase Order 10 on 9, Payment Request 11 on 10.
- Steps 6–7 are SKIPPED and never shown as waiting or completed.
- NL2 `30fffeaf` resolves by its Unicode title, and the Beta Cinemas list contains both Projects.

## 8. Full regression

**Final run** (alone, 03:18:51–03:25:51Z): **3822 passed, 20 skipped, 1 xfailed, 97 subtests passed**, exit 0. That is the 3774 after NL3A plus 48 new NL4A tests.

**First run** (03:10–03:17Z): 3821 passed, **1 failed**: `test_nl3a_natural_language_postgres.py::test_exact_live_request_previews_ready_and_mutates_nothing`.

- **Cause:** test data, not NL4A. The NL3A test asserted that the exact live request previews `READY_FOR_CONFIRMATION`. The NL3 live acceptance later *created* that Project, so the same request is now correctly `BLOCKED` by `POSSIBLE_DUPLICATE_PROJECT` on `ba5cc7ec…`, with no operation offered. The parse is still `NL2_LIVE_BETA`, the exact title and `requires_procurement: false`. NL4A does not touch `project_preview`, so the test would fail on `1b56a0b` as well.
- **Fix (test only):** the parse assertions are kept unconditionally. READY is expected only while that Project is absent; otherwise the duplicate block on that exact Project is asserted. This now also pins the no-duplicate-create protection.

| Check | Result |
|---|---|
| `system_test.py` | 80/80 |
| `git diff --check` | clean |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` |
| Test DB integrity | **byte-identical** to the pre-NL4A snapshot (sha256 `3fa71aec…504a`) after both full runs. The NL2 and NL3 Projects, their claims, ledger and fixtures are unchanged, and no orphans remain. |
| Real CLI subprocess | `agent_cli.py project status --request "Các bước đang chờ của Project Beta NL3 Confirmation Test là gì?" --test-database` → `PROJECT_STATUS`, 22 steps, current `[1]` |

## 9. Live read-only test procedure

Run these in a psmux lead session, in order. None of them needs `--confirm`:

1. `/solve Các bước đang chờ của Project Beta NL3 Confirmation Test là gì? trên database test`
   - Envelope: `merchant_read`, `read_only`, `merchant_database_target: test`.
   - merchant-manager runs `project status --request "…" --test-database` once.
   - The report carries `MERCHANT_PROJECT_STATUS_JSON:` with Project `ba5cc7ec…`, 22 steps, current step 1, and waiting steps 10 and 11 with their unmet predecessors.
2. `/solve Project Beta Nguyễn Văn Cừ hiện tại đến bước nào trên database test?` → Project `30fffeaf…`, current step "Draft or renew document".
3. `/solve Liệt kê các Project của Merchant Beta Cinemas trên database test.` → `PROJECT_LIST` with both Projects.
4. `/solve Những bước nào đã hoàn thành và còn vướng ở đâu trên database test?` → `NEEDS_CLARIFICATION`: which Project. No write and no `--confirm` prompt.
5. Afterwards, check read-only that the whole-database snapshot is unchanged (same counts and hashes).

Each run must end with the teammate `IDLE_REUSABLE`, no `MERCHANT_EXECUTE_REQUEST_JSON`, and no claim or ledger rows.

## 10. Remaining limitations

1. **No conversational memory.** "Những bước nào …?" without a Project name always asks which Project; it never uses the previous turn.
2. **Partial-title matching** is whole-token only, with no fuzzy or typo tolerance. ~~A single partial match without a Merchant is accepted as `match_kind: CANDIDATE`.~~ *Superseded by NL4A-FIX (C1): without a Merchant, a partial match is only ever a candidate and binds nothing.*
3. **Readiness follows the domain rule** (only COMPLETED satisfies a predecessor). In the real no-procurement graphs the SKIPPED steps have no edges, so this is exact. A future template with edges into a SKIPPED step would show that step as an unmet predecessor rather than reinterpret it.
4. **Approval and evidence detail** is counts plus open `APPROVAL_GATE` steps. Document contents and approval actors are not shown (NL4B+).
5. **Status filters** use one keyword set, and two filters in one request ask instead of combining.
6. ~~**Live verification is pending.**~~ *Done.* The first live run failed two of four requests; both were fixed in NL4A-FIX (`cp12h_nl4a_fix_and_cleanup.md`), and all four passed on retest (`cp12h_nl4a_live_acceptance.md`).

## 11. Recommendation

**GO for the live read-only test (§9) on the test database.** Every check passed:

- discovery, status, dependency semantics and delivery, offline and against the real NL2/NL3 Projects through the real CLI path;
- read questions can no longer be classified as writes;
- explicit step updates still require confirmation;
- the full regression, `system_test.py` and database integrity.

NL4A final acceptance should follow that live run. **NO-GO for runtime writes.** Runtime Direct EXECUTE remains disabled.

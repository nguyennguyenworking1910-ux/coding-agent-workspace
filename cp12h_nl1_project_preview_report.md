# CP12H.NL1 — Natural-Language Project Preview MVP

Branch `feat/cp7-9-merchant-reliability`, baseline `204bcde`. Nothing committed or pushed.

## 1. Domain model (from the real code and schema)

| Concept | Where it lives | Facts that matter for NL |
|---|---|---|
| Merchant | `merchant_ops.merchants` (`id`, unique `code`, `name`, `account_status`, `version`) | No alias storage. Resolution: `entity_resolver.resolve_merchant_entity` — UUID > exact code > exact name > alias > whole-token candidate; several matches fail closed as `AMBIGUOUS`. |
| Project | `merchant_ops.projects` (`merchant_id`, `project_type`, `workflow_variant`, `workflow_template_version_id`, optional `title`, `status`, `requires_procurement`, `payment_period_number`, `reused_document_revision_id`, `version`) | No uniqueness on title, so duplicates are possible at the DB level. Resolution inside one Merchant: `project_entity_resolver.resolve_project_entity`. |
| Project template | Immutable Python definitions in `workflow_templates.py` (4 standard templates), installed rows in `merchant_ops.workflow_templates` (+ steps, dependencies) | `OPENING_NEW_CINEMA` → only `OPENING_NEW_CINEMA_STANDARD`; `MEDIA_TOP_UP` → `_NEW_DOCUMENT` or `_EXISTING_DOCUMENT`; `INTEGRATION_NEW_MERCHANT` → `_STANDARD`. All four are installed and active in the test DB. |
| Step | `merchant_ops.project_steps` + dependencies, laid out by `project_factory.build_project_instantiation_plan` and `branches.resolve_workflow_branches` | Conditional procurement steps (condition `requires_procurement`) become `SKIPPED` when false. |
| Evidence | Gates (`gates.py`, `gate_resolver.py`) over document revisions, approvals and procurement records | Not needed for creation; untouched. |

Creation rules (from `project_factory` and `completeness.REQUIRED_WRITE_FIELDS`): required `merchant_id`, `project_type`, `workflow_variant`. The Merchant must be `ACTIVE` (`ONBOARDING` only for `INTEGRATION_NEW_MERCHANT`). `MEDIA_TOP_UP` also needs `payment_period_number`. `_EXISTING_DOCUMENT` needs `reused_document_revision_id` and no procurement. `_NEW_DOCUMENT` always has procurement. The write is `project create` through `MerchantWorkflowRepository.create_project`; it is reachable only through Direct EXECUTE with a user-typed scope.

## 2. Components reused (no parallel domain engine)

- `resolve_merchant_entity` binds the Merchant by its canonical identity.
- `_whole_token_sequence_match` is used for duplicate title matching.
- `STANDARD_WORKFLOW_TEMPLATES`, `template_uuid`, `template_fingerprint` and `PROJECT_TYPES` are used for template selection.
- `build_project_instantiation_plan` (pure) and `_validate_merchant_precondition` validate the Project and produce the initial steps.
- `MerchantReadRepository` (`list_merchants`, `list_projects`) is used, plus one new read-only method, `get_workflow_template`.
- `MerchantReadCommands` + `redact_payload` run the preview through the existing read path, and `cli.py` / `agent_cli.py` expose it as a read command.
- The intent parser's local Merchant guardrail and preview reconciliation now route the NL requests.

## 3. Files changed

New:
- `.claude/agents/tools/merchant/project_nl.py`: deterministic Vietnamese/English interpreter; pure, no I/O.
- `.claude/agents/tools/merchant/project_preview.py`: trusted resolution and the read-only preview.
- `tests/merchant/test_nl1_project_preview.py`: 45 unit tests with a fake read-only reader.
- `tests/merchant/test_nl1_intent_routing.py`: 19 `/solve` intent-routing tests.
- `tests/merchant/test_nl1_project_preview_postgres.py`: 3 tests on the real test DB.
- `cp12h_nl1_project_preview_report.md`: this report.

Modified:
- `.claude/clients/merchant/read_repository.py`: `get_workflow_template` (SELECT only, read-only connection).
- `.claude/agents/tools/merchant/read_commands.py`: `project_preview`.
- `.claude/agents/tools/merchant/cli.py`: `project preview --request [--merchant-hint] [--type-hint] [--title-hint]` parser and dispatch.
- `.claude/agents/tools/merchant/cli_contract.py`: `project preview` added to `READ_COMMANDS`.
- `.claude/system/intent_parser.py`:
  - Project-type wording counts as Merchant context.
  - Affirmative creation routes to `merchant_execute`, and negated, exploratory, preview or lookup wording routes to `merchant_read`.
  - `preview` / `dry run` / `xem trước` count as explicit preview-only.
- `.claude/agents/merchant-manager.md`: the preview command and how to report it.
- `.claude/commands/solve.md`: a Project request is never a Merchant creation, and the preview carries no authority.
- `tests/merchant/test_cli_contract.py`: the pinned read allowlist includes `project preview`.

## 4. Natural-language examples and interpretation

| Request | Kind | Write requested | Candidates (plain text, never identities) |
|---|---|---|---|
| Tạo project mở rạp Beta Nguyễn Văn Cừ. | PROJECT_CREATE | yes | type OPENING_NEW_CINEMA, phrase "Beta Nguyễn Văn Cừ" (split at resolution into Merchant "Beta" + site "Nguyễn Văn Cừ") |
| Tạo dự án khai trương rạp Nguyễn Văn Cừ cho Beta. | PROJECT_CREATE | yes | type OPENING_NEW_CINEMA, Merchant "Beta", site "Nguyễn Văn Cừ" |
| Create a new cinema opening project for Beta Nguyễn Văn Cừ. | PROJECT_CREATE | yes | type OPENING_NEW_CINEMA, phrase "Beta Nguyễn Văn Cừ" |
| Create a project to open Beta Nguyễn Văn Cừ cinema | PROJECT_CREATE (not MERCHANT_CREATE) | yes | type OPENING_NEW_CINEMA, phrase "Beta Nguyễn Văn Cừ" |
| Các dự án hiện tại của Beta là gì? | PROJECT_LIST | no | Merchant "Beta" |
| Project Beta Nguyễn Văn Cừ đang ở bước nào? | PROJECT_STATUS | no | Project "Beta Nguyễn Văn Cừ" |
| Tạo merchant Beta mới | MERCHANT_CREATE | yes | — no Project preview is built |
| Cập nhật bước Legal review của project Beta sang hoàn thành | STEP_UPDATE | yes | — |
| Không tạo project, chỉ xem trước dự án mở rạp Beta Nguyễn Văn Cừ | PROJECT_CREATE | no (negated, preview) | as above |
| Should we create a cinema opening project for Beta Nguyễn Văn Cừ? | PROJECT_CREATE | no (exploratory) | as above |

All three creation paraphrases produce the same preview fields: the Merchant id, `OPENING_NEW_CINEMA` / `OPENING_NEW_CINEMA_STANDARD`, and the title "Beta Nguyễn Văn Cừ".

How the Merchant is split from the site: the longest leading part of the phrase that the trusted resolver can match wins, and the rest is the site. A model may pass `--merchant-hint`, `--type-hint` or `--title-hint`. A hint that disagrees with the request is reported as a clarification, and so is a hint that is stale (for example an unknown UUID). A hint never overrides the repository.

`/solve` routing:

| Wording | Classified as | Result |
|---|---|---|
| Affirmative creation | `merchant_execute` | Needs `--confirm`. Without `--merchant-scope` the teammate can only preview; this is the existing unscoped behaviour. |
| Explicit preview | `merchant_read` | Read-only, no confirmation. |
| Negated or exploratory | `merchant_read` | If the model rated the request `external_write`, the risk is not lowered, so confirmation is still asked. This is conservative by design. |

## 5. Real Project preview for Beta Nguyễn Văn Cừ

**The test database has no Beta Merchant.** Its only Merchant is `Manual CLI Test 20260915110525`. Through the real CLI (`cli.py --database test project preview --request "Tạo project mở rạp Beta Nguyễn Văn Cừ."`) the preview correctly answers `NEEDS_CLARIFICATION`: "No existing Merchant matches 'Beta Nguyễn Văn Cừ' … (A Project request never creates a Merchant.)"

To show a resolved preview, I inserted a temporary fixture Merchant into the test DB: code `PYTEST_NL1_…`, name `Beta Cinemas`, `ACTIVE`. I ran the preview through `MerchantReadCommands` against the real database and then deleted the fixture; 0 fixture rows remain. The table checksums were identical before and after the preview.

"Tạo project mở rạp Beta Nguyễn Văn Cừ." returned `NEEDS_CLARIFICATION`:
- Merchant: `Beta Cinemas`, resolved by `CANDIDATE` match.
- Template: `OPENING_NEW_CINEMA_STANDARD` v1, `a3cc7546-6b0f-58a7-b78d-8e7a3289dc10`, installed.
- Missing field: `requires_procurement`, with the question "Does this Project require procurement (a Purchase Request)?"
- Steps: all 22 template steps are listed, with no statuses yet.

"Tạo project mở rạp Beta Nguyễn Văn Cừ. Không cần mua sắm." returned `READY_FOR_CONFIRMATION`:

```text
merchant      Beta Cinemas (fixture id d6cc0f63-…), ACTIVE, match CANDIDATE on "Beta"
project       title "Beta Nguyễn Văn Cừ", OPENING_NEW_CINEMA / OPENING_NEW_CINEMA_STANDARD v1
fields        merchant_id, project_type, workflow_variant, title, requires_procurement=false — none missing
conflicts     none
initial steps 1 Draft or renew document READY; 2 Legal review, 3 Accounting review,
              4 Send reviewed revision to Partner, 5 Record Partner approval PENDING;
              6 Create Purchase Request, 7 Record Purchase Request number SKIPPED;
              8–22 (signing gate, sign, PO, payment request, Production, UAT, complete) PENDING
requested_operation (status NOT_AUTHORIZED)
              ["project","create","--merchant-id","d6cc0f63-…","--type","OPENING_NEW_CINEMA",
               "--variant","OPENING_NEW_CINEMA_STANDARD","--title","Beta Nguyễn Văn Cừ"]
executable false, authorization null, basis_hash <sha256 of merchant/template/projects state>
```

## 6. Tests and RED/GREEN evidence

**RED** was run against a `git archive` copy of `204bcde` with the new tests copied in.
- `test_nl1_project_preview*.py` fail at collection: `ImportError` / `ModuleNotFoundError: claude.agents.tools.merchant.project_preview`.
- 17 behavioural tests failed:
  - 8 creation-routing cases: at baseline, the creation sentences were routed to `merchant_read`, or to `coder` when the model said BUILD;
  - 5 non-write routing cases;
  - 3 preview-confirmation cases;
  - 1 pinned allowlist test.
- The 3 "generic project or integration code work is not Merchant" guards passed both before and after.

**GREEN:** 67 new tests pass (45 unit, 19 routing, 3 PostgreSQL), along with all existing intent-parser and CLI-contract suites.

| Required coverage | Test(s) |
|---|---|
| Merchant vs Project classification | `test_creation_paraphrases_are_project_creation_not_merchant_creation`, `test_lookup_status_step_and_merchant_requests_are_distinguished`, `test_merchant_creation_request_builds_no_project_preview`, `test_unknown_merchant_is_never_created` |
| Vietnamese/English paraphrases | parametrised over the 4 creation sentences, in the interpreter, the preview and the routing tests |
| Existing Merchant resolution | `test_paraphrases_resolve_the_existing_merchant_and_one_template`, `test_real_preview_resolves_beta_and_mutates_nothing` (PG) |
| Ambiguous Merchant | `test_ambiguous_merchant_requires_clarification` |
| Missing or invalid template | `test_template_not_installed_blocks`, `test_invalid_or_ambiguous_template_requires_clarification` |
| Duplicate prevention | `test_possible_duplicate_project_blocks` (×3 title forms, including an unaccented one), `test_cancelled_duplicate_and_other_merchant_projects_do_not_block`, `test_real_duplicate_project_blocks` (PG, Project created through the real `MerchantWorkflowRepository`) |
| Negated or preview-only | `test_negated_preview_and_exploratory_wording_never_requests_a_write`, `test_preview_only_requests_get_the_same_non_executable_preview`, routing `test_preview_negated_and_exploratory_project_requests_stay_reads` |
| Stale candidates | `test_stale_or_conflicting_merchant_candidate_is_rejected`, `test_real_stale_merchant_candidate_is_rejected` (PG), `test_basis_hash_detects_changed_authoritative_state` |
| No runtime write access | `test_preview_uses_only_read_apis` (a reader that fails on any non-read attribute), `test_preview_is_a_read_command_and_its_operation_is_not_runnable_by_agents`, `test_runtime_direct_execute_remains_disabled` |
| No DB mutation during preview | PG tests compare count + md5 of 8 tables before and after |
| Preview is not write authorization | `test_preview_carries_no_authorization_material`, `test_preview_in_run_state_records_no_execute_dispatch` (policy gate records no dispatch receipt for an unscoped run carrying a preview); the agent CLI rejects the preview's argv |
| Not over-routing code work | `test_generic_project_or_integration_code_work_is_not_merchant` |
| Procurement asked, not invented | `test_procurement_is_asked_not_invented` |
| Precondition | `test_inactive_merchant_fails_the_template_precondition` |

## 7. Full regression

- **Full suite:** `pytest -q` from the repo root, test DB configured: **3474 passed, 0 failed, 20 skipped, 1 xfailed, 97 subtests passed (153 s)**. That is the CP12H.5C final count of 3407 plus exactly the 67 new tests; the skips and the xfail are the same opt-in live suites and the same known TOCTOU case.
- **Structural checks:** `python .claude/system_test.py` passed 80/80.
- **Test DB:** a read-only snapshot before and after the full suite was identical. There are still exactly 16 `merchant-direct:` claims, all `COMPLETED`; there are no `ACTIVE`, `REVOKED` or `pytest:` claims, and no fixture Merchants (`PYTEST_NL1_%`) remain. The runtime DB was never connected.
- **Direct EXECUTE settings:** `RUNTIME_DIRECT_EXECUTE_ENABLED = False` and `TEST_MODE_COMMANDS = {merchant create}` are unchanged. Preview code calls no write repository, handoff, reservation or claim API.
- **Earlier CP12H security tests:** all pass, including F7/F8, crash/replay/fence, pane identity, and scope/intent gates.
- **`git diff --check`:** clean on modified and new files.

## 8. Unresolved limitations

1. **The NL patterns are a deliberately narrow, rule-based vocabulary.**
   - Project types are recognised only from phrases such as "mở rạp", "khai trương rạp", "cinema opening", "open … cinema", "media top-up", and "tích hợp/integration + merchant/đối tác".
   - Other wording is left to the intent model, and the preview then asks for the type.
   - Pure lookups without a type word ("Các dự án hiện tại của Beta là gì?") are routed by the intent model, as before. The interpreter classifies them correctly, but the parser's local guardrail does not use the interpreter for that routing.
2. **`đừng` ("don't") and `dùng` ("use") fold to the same ASCII word.**
   - A sentence like "dùng … tạo project" is therefore read as negated.
   - That is the conservative direction: no write.
3. **Exploratory or negated creation that the model rated `external_write` keeps that risk**, so `/solve` still asks for `--confirm` even though the run is read-only. Explicit preview wording is downgraded.
4. **No Merchant aliases exist in the schema.**
   - "Beta" resolves only when it is unique as a code, name or whole-token candidate.
   - An exact code match takes precedence over name candidates; this is the existing resolver rule.
5. **The Project title is derived as "<Merchant words> <site>"**, for example "Beta Nguyễn Văn Cừ". A different naming convention would need a rule or a `--title-hint`.
6. **Duplicate detection is title-based**, using whole-token match in either direction, accent-insensitive, and skipping `CANCELLED` Projects. Two Projects for the same site under different titles are not detected.
7. **The preview reports `basis_hash` but nothing checks it yet.** NL2 should rebuild the preview at confirmation and refuse when the hash changed.
8. **I did not drive `/solve` live in psmux** for this checkpoint.
   - The exact request to try is `/solve Xem trước dự án mở rạp Beta Nguyễn Văn Cừ, không cần mua sắm`. It is a `merchant_read`, needs no `--confirm`, and runs one read.
   - The runtime DB was not connected, so I have not checked whether a Beta Merchant exists in production.
9. **Test-mode Direct EXECUTE still supports only `merchant create`** (`TEST_MODE_COMMANDS`). Test-DB Project creation in NL2 needs `project create` added to that test-mode path.

## 9. GO / NO-GO for NL2

**GO for NL2 design and test-database work**, with three prerequisites that belong to NL2 itself:

1. **Test-mode `project create`.** `TEST_MODE_COMMANDS` must admit `project create` through the existing reservation and evidence path, with its own tests. No change to the runtime gate is needed.
2. **Re-preview at confirmation.** Confirmation must rebuild the preview and refuse when `basis_hash` changed or the outcome is no longer `READY_FOR_CONFIRMATION`. It must use the user-typed exact scope; the preview object itself must never be accepted.
3. **Seed a Beta Merchant in the test DB.** Either seed a test Beta Merchant (ACTIVE) for the end-to-end run or accept a pytest fixture, because the test database has none today.

**Runtime (production) Project creation remains NO-GO**; `RUNTIME_DIRECT_EXECUTE_ENABLED` stays `False`.

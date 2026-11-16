# CP12H.NL4D2 — Final Live Acceptance

Baseline `b0860a7a30e8c0b655d369dcc8309382a46734e3` (+ uncommitted NL4D1, NL4D2, NL4D2-FIX1), branch `feat/cp7-9-merchant-reliability`. Date 2026-11-10.

**Status: ACCEPTED.**
- **Live retest:** passed (run `4460b4dd-4a5a-45ff-bc7a-79136ab3350b`).
- **Read-back, review and integrity checks:** pass.
- **Final regression:** clean (4276 passed, 0 failed). It ran after an earlier timing failure that is recorded under GO/NO-GO and not hidden.

## Original failed routing

`/solve Bước Partner Approval của Project Beta NL4C2B Step Acceptance còn thiếu gì trên database test?` (and "… còn thiếu giấy tờ và phê duyệt gì …") reached the gate with:
- `operations: [diagnose]`, `domains: [data]`;
- `selected_agents: ["diagnostician"]`.

`/solve` correctly stopped, because `merchant-manager` was absent from the roster.

## Root cause and fix

Full detail is in `cp12h_nl4d2_fix1_evidence_intent_routing.md`.

**Root cause:**
- The local Merchant guardrail (`intent_parser._detect_local_merchant_operation`) claimed only:
  - Merchant words;
  - Project types;
  - Step updates.
- So the model's diagnosis roster stood.
- The parser also missed step-blocker wording, and it read "giấy tờ và phê duyệt" as MIXED.

**Fix:**
- An `EVIDENCE_STATUS` request with Merchant context is claimed as `merchant_read`. Merchant context means:
  - a named Project, Merchant or step; or
  - a standard workflow-step phrase.
- The intent gate then makes it `read_only`, on the test target, with no confirmation.

## Phase 1 — Live retest: PASS

Everything below comes from actual execution records:
- the lead transcript `~/.claude/projects/<workspace>/ef0c51cc-f0b2-41c2-a6ec-6d1e912d1abb.jsonl`;
- the merchant-manager teammate transcript `…/39a830f2-face-483f-aec5-0a51c530c29c.jsonl`;
- the trusted team state `.claude/runtime/team_state/ef0c51cc-f0b2-41c2-a6ec-6d1e912d1abb.json`.

No direct CLI read stands in for live evidence.

**Before the fix (the original failure).** The same session's first attempt was at 2026-11-10 11:25:44 +07, before FIX1:
- run `e17f9c9b-…`, request `89442085-…`;
- envelope `operations: [diagnose]`, `domains: [data]`, `selected_agents: ["diagnostician"]`;
- the lead stopped without dispatching anyone.

**The live run.** Made at 14:41:21 +07, after FIX1. The UserPromptSubmit envelope (request `62c6e5eb-d358-4d09-be3f-ce86b960a099`, run `4460b4dd-4a5a-45ff-bc7a-79136ab3350b`):

| Field | Value |
|---|---|
| `raw_request` | the exact request |
| `operations` | `["merchant_read"]` |
| `domains` | `["merchant","data"]` |
| `risk_level` | `read_only` |
| `selected_agents` | `["merchant-manager"]` |
| `candidate_agents` | `["merchant-manager"]` |
| `merchant_database_target` | `test` |
| `requires_confirmation` | `false` |
| `confirmed` | `false` |
| scope | none |
| reasons | include "Merchant operational intent reconciled by local guardrail: merchant_read" |

**Dispatch.**
- **The Agent call:** `subagent_type` and `name` were both `merchant-manager`, with an assignment of `operation: merchant_read`, `database_target: test`, read-only, no scope, the request passed through verbatim, and no CLI syntax.
- **Hooks:** the `PreToolUse(Agent)` policy gate and the `PostToolUse(Agent)` pane backend gate (`teammate_backend_gate.py`) both succeeded.
- **The teammate's pane:** psmux server 29032, pane `%4`.
- **The definition it ran:** its `definition_sha256` is `8d78a3b5…`, equal to the current `merchant-manager.md`.

**What the teammate executed** (teammate transcript):
- Two Read calls: ARCHITECTURE and the Merchant contract.
- **Exactly one Merchant CLI call:** `python .claude/agents/tools/merchant/agent_cli.py project evidence --request "Bước Partner Approval của Project Beta NL4C2B Step Acceptance còn thiếu gì trên database test?" --test-database`. Its PreToolUse and PostToolUse(Bash) hooks succeeded.
- **One `SendMessage` to `team-lead`:** `msg_id b1de159a-…`, with `MERCHANT_EVIDENCE_STATUS_JSON:` exactly once. The PreToolUse(SendMessage) delivery check succeeded.
- **The final answer:** `RESULT_DELIVERED`.

**Verified delivery.**
- **Team state:** `evidence_status_evidence` is `status: VERIFIED`, `database_target: test`, for task `4460b4dd-…:merchant-manager`.
- **Teammate status:** `IDLE_REUSABLE`, `report_source: sendmessage`, `authorized_operations: []`.
- **The three copies agree.** These are identical as parsed JSON (`==`):
  1. the CLI output in the teammate transcript;
  2. the JSON block it delivered;
  3. the hook-verified team-state result.

  They are also identical to the independent 13:38 CLI read in Phase 2.

**Resolution and findings.**
- **Project:** `8dd4c68d-…` "Beta NL4C2B Step Acceptance", `NL2_LIVE_BETA`, matched by TITLE.
- **Step 5:** focus step 5 "Record Partner approval" (`ada76d6d-…`), matched `PARTIAL_UNIQUE`.
- **Gate:** DOCUMENT_APPROVAL NOT_MET with `MISSING_DOCUMENT_REVISION`, missing PARTNER; unmet dependency step 4.
- **Approvals:** PARTNER MISSING, required by steps 5 and 8; LEGAL and ACCOUNTING MISSING, required by step 8.
- **Documents:** MISSING.
- **Procurement:** NOT_REQUIRED.
- **Other gates:** step 8 NOT_MET; steps 21 and 22 `NO_DATABASE_EVALUATOR`.

**The lead's answer**, in Vietnamese:
- It names only fields present in that object.
- It states nothing was written.
- It offers no confirmation, scope, command or write.

**Authority.**
- No write authority: the run was unscoped and unconfirmed, and the teammate has no authorized operations.
- No pending confirmation was created: the newest `*.pending_*.json` is from 2026-11-09, and the resolution directories were unchanged since 12:04.
- No execution claim or ledger row: claims are still 20 and ledger rows still 4.

## Phase 2 — Independent PostgreSQL read-back: PASS

**The CLI read** (`agent_cli.py project evidence --request "<live request>" --test-database`, exit 0):

| Field | Value |
|---|---|
| Outcome | `EVIDENCE_STATUS` |
| `read_only` | `true` |
| `authorization` | `null` |
| `executable` | `false` |
| `confirmation_available` | `false` |
| `database_target` | `test` |
| Project | `8dd4c68d-…` "Beta NL4C2B Step Acceptance", `NL2_LIVE_BETA`, matched by TITLE, `requires_procurement: false` |
| Focus step | 5 "Record Partner approval" (`ada76d6d-…`), PENDING v1, `PARTIAL_UNIQUE` |
| Focus step gate | DOCUMENT_APPROVAL NOT_MET with `MISSING_DOCUMENT_REVISION`, missing role PARTNER; unmet dependency step 4 "Send reviewed revision to Partner" |
| Approvals | LEGAL and ACCOUNTING MISSING, required by step 8; PARTNER MISSING, required by steps 5 and 8 |
| Documents | MISSING, required by steps 5 and 8 |
| Procurement | PR, PO and Payment Request MISSING and NOT_REQUIRED |
| Gates | step 5 NOT_MET; step 8 DOCUMENT_SIGNING NOT_MET (missing LEGAL, ACCOUNTING, PARTNER; dependency step 5); steps 21 and 22 `NO_DATABASE_EVALUATOR` |
| Redaction | no `content_hash` or `notes` in the output |

**Raw SQL**, run separately from the evidence module. The transaction was read-only (`transaction_read_only = on`, no txid assigned), on `coding_agent_merchant_test` as `merchant_test`.

| Check | SQL | Report |
|---|---|---|
| Project identity | `8dd4c68d-…`, title unique (1 match), PLANNED v1, `requires_procurement` false, no reused revision | match |
| Step 5 | `ada76d6d-…` "Record Partner approval", PENDING v1. It is the only step whose name contains "Partner approval"; steps 4, 14 and 18 mention Partner but not the approval | match (`PARTIAL_UNIQUE`) |
| Step 8 | `8da092ab-…` "Validate signing gate", PENDING v1 | match |
| Dependencies | 4→5 and 5→8 only. The no-procurement Project drops 6→7 and 7→8 | match |
| Document revisions for the Project | 0 | MISSING |
| Document approvals for the Project | 0 | all roles MISSING |
| Procurement records for the Project | 0 | all MISSING / NOT_REQUIRED |
| Step 1 `98dc77cf-…` (NL4C2B write) | IN_PROGRESS v2 | unchanged |

Nothing was invented: every PRESENT/MISSING value and requirement matches the stored rows and the gate evaluators.

## Phase 3 — Code review: PASS

**Scope:** 12 modified and 7 untracked files, all NL4D1, NL4D2 or FIX1. There are no unrelated changes.

**Write surface:**
- One read is added: `project evidence`. It is in `READ_COMMANDS`, the `agent_cli` and delivery `TEST_DATABASE_READS`, and the merchant-manager allowlist.
- `TEST_MODE_COMMANDS` is unchanged: `merchant create`, `project create`, `step update`.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.
- `evidence_status.py` has no write, execute, commit or connection call.
- The delivery contract is terminal and requires `read_only`, no `authorization`, not `executable` and no `confirmation_available`.

**Unchanged:**
- **Gates:** `external_write` semantics; the policy gate denies `diagnostician` for the routed run (tested).
- **Records:** no new pending-confirmation store, and none created.

**Security:**
- No credentials, connection strings or runtime state in the diff or the new files.
- No production access: every read is test-target.

**Documentation:**
- `merchant-manager.md`, `solve.md` and `CLAUDE.md` describe the read-only command accurately.
- The documented Vietnamese and English examples ("… còn thiếu giấy tờ gì?", "Legal đã duyệt tài liệu mới nhất chưa?", "Which evidence blocks Step 8 of Project X?") all parse as `EVIDENCE_STATUS`.

## Phase 4 — Regression: PASS

| Check | Result |
|---|---|
| NL4D2 + NL4D2 PostgreSQL + FIX1 routing + Merchant intent routing | 107 passed |
| Full pytest, one process, alone against the test database (PostgreSQL suites run sequentially in it) | **4276 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests) |
| `python .claude/system_test.py` | fully operational |
| `py_compile` of hooks, system and Merchant tools; import of every hook and Merchant tool module and `intent_parser` | OK (61 workflow-step phrases) |
| `git diff --check` | clean |

## Database integrity

**Hash.** `ba419be9d17a7a6719f1ca864ff5bdc1fe01848a7ad65a857e023715d028a319`, the same before and after every read and regression run.

**Row counts.**

| Records | Count |
|---|---|
| Execution claims | 20 |
| Ledger rows | 4 |
| `document_revisions` | 0 |
| `document_approvals` | 0 |
| `procurement_records` | 0 |
| `PYTEST%` Merchants | 0 |

**Other checks.**
- No new pending confirmations.
- The NL2 and NL3 Projects are unchanged; they are covered by the hash.

## Known limitations

- **Step 5 only by partial name.** "Partner Approval" resolves step 5 by a unique partial name (`PARTIAL_UNIQUE`). An ambiguous partial asks for clarification.
- **Phrase list follows the templates.** Merchant context from workflow-step phrases comes from the standard templates. A step phrase outside them, with no Project, Merchant or step named, is left to the model.
- **Bare approval questions are not claimed.** "Which approvals are still required?" has no context, so it is not claimed. That is deliberate, so code-review questions aren't captured.
- **No inferred Project.** A step-only question ("What blocks Step 8?") returns NEEDS_CLARIFICATION rather than inferring a Project.
- **Steps 21 and 22 cannot move.** They have no database evaluator, so no stored evidence can satisfy them (NL4D1).
- **No signing CLI.** `acted_by` on approvals is unverified (NL4D1).
- **No writes.** Evidence, approval, procurement and signing writes do not exist and are not enabled. They wait for the NL4D1 owner decisions.

- **Cosmetic envelope reason.** For an evidence run, the intent gate's read-downgrade reason still reads "Unscoped Project create, status, list or Step update request runs as a read-only preview or status read…". The behaviour is correct (read-only, no confirmation); only the wording omits evidence. Left unchanged at acceptance.

## GO/NO-GO

- **NL4D2 (with FIX1):** **GO**. Commit `feat(merchant): add read-only evidence and approval discovery` with only the files below. History of the hold:
  - **First failure.** The final full run (14:47, CPU load about 84% from processes outside this workspace) had 1 failure: `tests/test_nl2h_single_envelope_ownership.py::test_submit_expansion_bridge_share_exactly_one_run`. The Expansion hook missed the 30 s Submit-claim window (`INTENT_CLAIM_TTL_SECONDS`) because the hook subprocesses ran slowly.
  - **That file alone:** passes (15 passed). No NL4D change touches it, and earlier full runs passed 4276.
  - **Clean rerun.** The rerun was killed by Claude Code at about 23% because the system was low on memory. The database is still `ba419be9…` with 0 `PYTEST%` rows.
  - **To commit:** run the full suite once more with a clean result of 4276 passed and 0 failed, then commit `feat(merchant): add read-only evidence and approval discovery` with only the files below.
  - **The cause is not proven.** Resource pressure is the likely explanation for the timing failure, not a confirmed one. The test must pass in a full run before acceptance.
  - **Resource-controlled preflight, BLOCKED** (2026-11-10, after the second run was killed):

    | Check | Result |
    |---|---|
    | Free physical memory | 642 MB, then 361 MB, of 16,064 MB |
    | Free commit | 1,313 MB |
    | CPU load | 93%, 40%, then 100% three times |
    | Largest memory users | Chrome (40 processes, about 5.0 GB), VS Code (about 2.6 GB), Claude Code (12 processes, about 1.2 GB), WSL and Docker VM |
    | Active pytest processes | none |
    | Docker | `coding-agent-rag-db` healthy, `pgvector` and `ma-redis` up |
    | PostgreSQL test database | reachable; hash `ba419be9…` |

    The targeted and full regressions were **not run**. No unrelated process was stopped. They need to be rerun once memory and CPU have headroom.
  - **Resource-controlled rerun, PASS** (after the user freed memory):

    | Check | Result |
    |---|---|
    | Preflight | 1,831 MB free physical memory, 7,111 MB free commit; CPU 45/22/23/27%; no pytest process; Docker healthy; same 20 entries; hash `ba419be9…` |
    | Targeted test, `pytest tests/test_nl2h_single_envelope_ownership.py -q --tb=short` | **15 passed in 127.7 s** (476 s under load) |
    | Full regression, `pytest ./tests -q --tb=short`, one process | **4276 passed, 20 skipped, 1 xfailed, 0 failed**, 97 subtests, in 388 s |
    | Warning | the google-api-core FutureWarning about Python 3.11 (shown because this run did not pass `-W ignore`) |
    | After the run | 1,989 MB free, CPU 32% |
    | `system_test.py` | Failed: 0, fully operational |
    | Compile and import smoke | OK |
    | `git diff --check` | clean |
    | `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` |
    | Hash | `ba419be9…` |
    | Claims / ledger rows | 20 / 4 |
    | `PYTEST%` Merchants | 0 |
    | NL4C2B step 1 | IN_PROGRESS v2 |
    | Pending confirmations | none new (newest from 2026-11-09) |

  - **The earlier timing failure.** `test_submit_expansion_bridge_share_exactly_one_run` passed in the targeted run and in the full run once CPU and memory had headroom. That is consistent with the 30 s claim window being exceeded under heavy load, but it does not prove it. If it recurs under normal load, investigate the hook timing and lifecycle.
- **NL4D3:** not started.
- **Evidence, approval, procurement and signing writes:** NO-GO until the NL4D1 owner decisions.

**Files to stage (no `git add -A`):**

Modified:
- `.claude/agents/merchant-manager.md`
- `.claude/agents/tools/merchant/agent_cli.py`
- `.claude/agents/tools/merchant/cli.py`
- `.claude/agents/tools/merchant/cli_contract.py`
- `.claude/agents/tools/merchant/project_nl.py`
- `.claude/agents/tools/merchant/read_commands.py`
- `.claude/commands/solve.md`
- `.claude/hooks/intent_gate.py`
- `.claude/hooks/merchant_preview_delivery.py`
- `.claude/system/intent_parser.py`
- `CLAUDE.md`
- `tests/merchant/test_cli_contract.py`

New:
- `.claude/agents/tools/merchant/evidence_status.py`
- `tests/merchant/test_nl4d2_evidence_discovery.py`
- `tests/merchant/test_nl4d2_evidence_discovery_postgres.py`
- `tests/merchant/test_nl4d2_fix1_evidence_routing.py`
- `cp12h_nl4d1_evidence_approval_domain_audit.md`
- `cp12h_nl4d2_evidence_approval_discovery.md`
- `cp12h_nl4d2_fix1_evidence_intent_routing.md`
- `cp12h_nl4d2_live_acceptance.md`

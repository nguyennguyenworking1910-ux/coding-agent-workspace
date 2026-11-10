# CP12H.NL4D2 — Natural Language Evidence & Approval Discovery

Baseline `b0860a7a30e8c0b655d369dcc8309382a46734e3`, branch `feat/cp7-9-merchant-reliability`. Date 2026-11-10.

This checkpoint adds a **read-only** natural-language discovery of document revisions, approvals, procurement records, missing requirements and blocked gates. It adds **no write of any kind**: no evidence, approval, procurement, signing or confirmation capability.
- Not committed, not pushed.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`; `TEST_MODE_COMMANDS` unchanged.

## 1. Domain contracts reused (nothing re-implemented)

| Question | Authoritative method used |
|---|---|
| Read revisions, approvals, procurement, steps, dependencies | `MerchantReadRepository.get_project_detail` (same snapshot as `project show` and `step preview`) |
| Bind Merchant and Project | `project_status.resolve_merchant_phrase` / `resolve_project` (NL4A: exact ID, exact title, Merchant plus title; never one of several; a partial title without a Merchant is a candidate only) |
| Bind a step | sequence number; `step_entity_resolver.resolve_step_entity` (UUID or exact name); `step_preview._written_title` (a stored title cut at a stop word) |
| Latest revision | `gates.latest_document_revision` (refuses when several document types are active) |
| Approval validity on the latest revision | `gates.evaluate_approval_gate` (APPROVED with `approved_at`, on the latest non-superseded revision) |
| Gate evaluation | `gate_resolver.resolve_database_gate`, called exactly as `transition_repository.transition_step` calls it; `database_gate_kind` / `is_approval_gate` for which steps are gates |
| Unmet dependencies | `dependencies.evaluate_dependency_readiness` |
| Procurement types | `procurement_engine.PROCUREMENT_TYPES`; Purchase Request validity is the signing gate's own `purchase_request_present` |
| Redaction | `read_commands` → `redact_payload` (as for every read); `content_hash` and approval `notes` are never even placed in the result |

**What drives each answer:**
- **Requirements** come only from gate evaluations: a role or record is REQUIRED only if an open gate's own result names it.
- **The rules themselves** are never duplicated in the parser, the result builder or a prompt.

## 2. Natural-language command examples

The teammate runs `project evidence --request "<user words>" [--test-database]` (an allowlisted read; `agent_cli` accepts `--test-database` for it, as for `project status`).

| Request | Bound to |
|---|---|
| "Project Beta NL4C2B Step Acceptance còn thiếu giấy tờ gì?" | whole Project |
| "Bước Partner Approval của Project X còn thiếu gì?" | step 5 (unique partial title, marked `PARTIAL_UNIQUE`) |
| "Legal đã duyệt tài liệu mới nhất của Project X chưa?" | whole Project, `query.roles = ["LEGAL"]` |
| "Accounting Review của Project X đang chờ điều kiện nào?" | step 3 (stored title written whole) |
| "Project X đã có Purchase Order chưa?" | whole Project, `query.procurement_types = ["PURCHASE_ORDER"]` |
| "Show missing approvals for Project X." | whole Project |
| "Which evidence blocks Step 8 of Project X?" | step 8 |
| "List document revisions for Project X." | whole Project |

**Routing:**
- **New kind.** The parser kind `EVIDENCE_STATUS` (`project_nl`) is used for questions that name evidence outside any Project or Merchant name.
- **Read downgrade.** The intent gate runs it as `merchant_read` (risk `read_only`, no `--confirm`) and binds the database target from the user's words.
- **What it never catches:** an imperative write ("Ghi nhận …", "Upload …", "Approve …"), a step-completion question ("… đã hoàn thành chưa?") or a Step Update.
- **Fail closed.**
  - "Project này …" has no trusted binding, so it gets NEEDS_CLARIFICATION.
  - An ambiguous Project or step returns NEEDS_CLARIFICATION with candidates.

## 3. Structured result schema (`mode: EVIDENCE_STATUS`)

```text
success, mode, database_target, outcome: EVIDENCE_STATUS | NEEDS_CLARIFICATION
read_only: true, executable: false, confirmation_available: false, authorization: null
query      {kind, merchant_phrase, project_phrase, project_id, step_reference, roles[], procurement_types[]}
merchant   {merchant_id, code, name, match_kind}
project    {project_id, title, status, merchant_*, project_type, workflow_variant, version, requires_procurement, match_kind}
focus_step {step_id, sequence, name, status, version, match_kind: EXACT | PARTIAL_UNIQUE,
            gate (as below) | null, evidence_requirement: GATE | NOT_REQUIRED, explanation,
            unmet_direct_dependencies[], unmet_transitive_count}            # when a step was named
documents  [{document_type, requirement, required_by[], revisions[{revision_id, revision_number,
            status: PRESENT | INVALID, reason: ACTIVE | SUPERSEDED, superseded_by, signed, signed_at,
            effective_date, expiry_date, created_at}]}]  # or one MISSING entry when there is none
approvals  [{role: ACCOUNTING | LEGAL | PARTNER, status, reason, requirement, required_by[],
            document_revision_id (the latest revision), approval {role, approval_status, approved_at, document_revision_id} | null}]
outdated_approvals [{role, approval_status, approved_at, document_revision_id, status: INVALID,
            reason: SUPERSEDED_REVISION | REVISION_NOT_JUDGED, explanation}]
procurement [{procurement_type, status, reason, requirement, required_by[], external_id, record_status, version, note}]
gates      [{step_id, sequence, name, status, version, gate_kind, database_verifiable,
            gate_status: MET | NOT_MET | CLOSED | NO_DATABASE_EVALUATOR | UNKNOWN,
            evaluation (GateValidationResult.to_dict) | null, blocking_codes[], explanation,
            unmet_direct_dependencies[]}]
missing    [{code, role?, gate {sequence, name}, explanation}]  # from open gates' blocking codes only
sources    {gate, approval, dependencies, procurement}         # which domain method answered
candidates[], clarifications[]
```

### Classification (read-model, derived from the domain contracts)

**`status`, what is stored:**

| Status | Meaning |
|---|---|
| PRESENT | Counts for its gate: an approval APPROVED with `approved_at` on the latest revision; the active revision; a procurement record with its number. |
| MISSING | Nothing stored, or a PENDING decision (`reason: PENDING_DECISION`). |
| INVALID | Stored but can never count: REJECTED (`REJECTED_FINAL`); APPROVED without a timestamp; on a superseded revision; a procurement record without `external_id`. |
| UNKNOWN | The domain refused to judge the snapshot (for example several active document types: `latest_document_revision` requires a type). |

**`requirement`, whether an open gate needs it:**

| Requirement | Meaning |
|---|---|
| REQUIRED | An open gate's own evaluation names it. |
| NOT_REQUIRED | No open gate does. |
| UNKNOWN | A gate could not be judged. |

There is no separate `NOT_REQUIRED` status: requirement and presence are reported independently, so "missing but not required" (for example a Purchase Order) is never shown as a blocker.

## 4. Gate evaluation behaviour

- Every `APPROVAL_GATE` step of the Project is listed.
- **Status by gate:**

  | Gate | Status |
  |---|---|
  | Terminal steps (COMPLETED, SKIPPED, SUPERSEDED) | `CLOSED` |
  | Steps 21 and 22 (no evaluator) | `NO_DATABASE_EVALUATOR`, with blocking code `NO_DATABASE_GATE_EVALUATOR`: never satisfiable |
  | Step 5 (Partner) and step 8 (signing) | `resolve_database_gate` → `MET` or `NOT_MET` with the domain's `blocking_codes`, `missing_roles`, `approved_roles`, `purchase_request_present`, `already_signed` and the judged `document_revision_id` |

- **Missing items.** `missing` lists exactly those blocking codes, per role for `MISSING_REQUIRED_APPROVALS`, with the gate they came from.
- **Historical approvals.** A valid approval on an older revision is **never** counted for the latest revision. It appears only in `outdated_approvals` as INVALID / `SUPERSEDED_REVISION`. This was tested in both the unit and PostgreSQL suites.

## 5. RED/GREEN tests

**New tests:**
- `tests/merchant/test_nl4d2_evidence_discovery.py`: 47 tests. The fake reader serves the real 22-step template with both edge variants and refuses non-read APIs.
- `tests/merchant/test_nl4d2_evidence_discovery_postgres.py`: 3 tests. Real evidence is written through the domain repositories on a throwaway `PYTEST_NL4D2_` Project; the read is checked against `resolve_database_gate` on the stored rows, and a digest of every evidence, claim and ledger table must stay equal.

**Coverage:**
- **Phase 5 domain cases:**
  - no revision; one unsigned revision; multiple revisions; an approval on an outdated revision;
  - missing LEGAL, ACCOUNTING and PARTNER (parametrized at step 8);
  - procurement required, with PR missing, present or blank; procurement not required;
  - steps 5 and 8 blocked; dependencies incomplete; a step without a gate;
  - an already signed revision; several active document types (UNKNOWN);
  - REJECTED and PENDING decisions;
  - ambiguous Project, "Project này", unknown Project, ambiguous step;
  - Unicode title with similar titles kept apart.
- **Security:**
  - the result carries no hash, notes, operation, argv, scope or confirmation;
  - the CLI cannot `--execute`, and other reads cannot reach the test database;
  - the intent gate makes it `merchant_read` / `read_only` with no scope;
  - verified delivery: the exact object is accepted; a missing, altered or duplicated object, `--merchant-scope` or `confirmation_command` is denied;
  - 6 forged captures are UNVERIFIED;
  - a runtime read cannot answer a test run;
  - no pending Project or Step record is created.

**RED** (sources at HEAD, `evidence_status.py` absent; then restored and checked with `cmp`):

| Suite | RED | GREEN |
|---|---|---|
| Unit | collection error (no evidence kind or module) | 47 passed |
| PostgreSQL | 3 of 3 failed | 3 passed |

**Regressions found and fixed during GREEN:**
- **Step-name words.** "Legal review" / "Accounting review" in step-status questions are step names, so they were removed from the evidence nouns. Step-completion questions are excluded.
- **Words inside names.** An evidence noun inside a Project name ("… Evidence") is masked with the same name spans used by NL4C2B-FIX.

**Intentional test change:** `test_cli_contract.py` now lists `project evidence` in `READ_COMMANDS`.

## 6. Full regression

**Targeted suites, run one after another, all passed:** every NL2, NL3, NL4A, NL4B, NL4C and NL4D2 file, and every `*_postgres.py` file.

| Suite | Passed |
|---|---|
| NL4D2 unit | 47 |
| NL4D2 PostgreSQL | 3 |
| NL4C2B FIX | 55 + 5 |
| NL4C2B approval concurrency (PostgreSQL) | 6 |
| NL4C2B receipt (PostgreSQL) | 3 |
| NL4C2A | 18 + 14 |
| NL4C1 | 60 + 8 |
| NL4C preview contract | 13 |
| NL4B | 44 + 8 |
| NL4B FIX1 / FIX2 / FIX2B | 19 / 37 / 43 |
| NL4A | 43 + 10 |
| NL4A FIX | 37 |
| NL3 | 41 + 2 |
| NL3A | 34 + 1 |
| NL2 | 18 + 11 |
| NL2E | 61 + 34 |
| NL2F | 22 + 3 |
| NL1 PostgreSQL | 3 |
| Execution claims / evidence / ledger / attempt evidence / atomic create / Project create (PostgreSQL) | 5 / 16 / 4 / 10 / 3 / 3 |

**Full pytest:**
- Run alone against the test database: **4246 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests). That is the NL4C baseline of 4196 plus 50 new tests.
- Without a database: run before the last two fixes (7 failures found and fixed, see §5); every affected suite passes after.

**Other checks:**
- `python .claude/system_test.py`: ALL PASSED.
- Compile (all hooks and Merchant tools) and import smoke (intent_gate, merchant_preview_delivery, policy_gate, team_result_hook, merchant_direct_handoff, evidence_status): OK.
- `git diff --check`: clean.

## 7. Database integrity

**Hash.** `ba419be9d17a7a6719f1ca864ff5bdc1fe01848a7ad65a857e023715d028a319` (post-NL4C2B state) was identical before and after:
- the PostgreSQL tests (GREEN and RED);
- the live acceptance;
- the full suite.

**Execution evidence.** No new execution claims (20) or ledger rows (4) were written. No `PYTEST%` Merchants are left.

**Pending confirmations.** None were created: the only pending files on disk date from 2026-11-04 and 2026-11-09.

**Accepted Projects.**
- The NL4C2B accepted step `98dc77cf-…` is still IN_PROGRESS v2.
- The NL2 and NL3 acceptance Projects are unchanged (included in the hash).

## 8. Live read-only acceptance

**What was run:** the exact teammate read path (`agent_cli` argv → `dispatch_read_command` → `MerchantReadCommands.project_evidence`) against the real Project "Beta NL4C2B Step Acceptance" (`8dd4c68d-…`) on `coding_agent_merchant_test`.

### Discovery results

| Request | Outcome |
|---|---|
| "… còn thiếu giấy tờ gì trên database test?" | `EVIDENCE_STATUS`. Documents: MISSING (REQUIRED by 5 and 8). Approvals: all MISSING (`MISSING_DOCUMENT_REVISION`); PARTNER required by [5, 8]; LEGAL and ACCOUNTING by [8]. Procurement: all MISSING, all NOT_REQUIRED. Gates: 5 NOT_MET (unmet direct [4]); 8 NOT_MET ([5]); 21 and 22 NO_DATABASE_EVALUATOR ([20] and [11, 14, 21]). |
| "Which evidence blocks Step 8 … on the test database?" | same, plus `focus_step` 8: PENDING, EXACT, gate NOT_MET (`MISSING_DOCUMENT_REVISION`), unmet direct [5], transitive count 5 |
| "… đã có Purchase Order chưa trên database test?" | Purchase Order MISSING and NOT_REQUIRED, with the note that no gate checks it |
| "Project Beta còn thiếu phê duyệt nào trên database test?" | NEEDS_CLARIFICATION, listing the three Beta Projects as candidates; none chosen |

### Independent PostgreSQL verification

A separate read-only session (`transaction_read_only = on`, no transaction ID assigned):

| Fact | Value |
|---|---|
| Revisions / approvals / procurement records | 0 / 0 / 0 |
| `requires_procurement` | false |
| Steps | 1 IN_PROGRESS; 2, 3, 4, 5, 8, 20, 21 and 22 PENDING |
| Gate edges | 4→5, 5→8, 20→21, 11/14/21→22 |

Every discovery value above agrees.

**Not yet run through `/solve`.** A full `/solve` run through a teammate pane needs a fresh Claude Code session, because `merchant-manager.md` changed and running teammates are now `STALE_DEFINITION`:
1. Start a fresh session.
2. Type `/solve Project Beta NL4C2B Step Acceptance còn thiếu giấy tờ gì trên database test?`.
3. Expect a `merchant_read` run whose report carries `MERCHANT_EVIDENCE_STATUS_JSON:` with the values above.

## 9. Known limitations

1. **Partial step titles.** A unique partial step title is bound for this **read** (marked `PARTIAL_UNIQUE`). Several matches still ask. Previews and writes keep the stricter exact-only rule.
2. **Requirements come only from gates.** Steps 9–11 (sign, Purchase Order, Payment Request) and the review steps 2–3 are not linked to evidence in the domain (NL4D1 D3/D5). They are reported as `NOT_REQUIRED`, with a note.
3. **Several active document types** make the gates UNKNOWN, because the domain needs a type the workflow does not supply. Not guessed.
4. **Parser coverage** is keyword-based, Vietnamese and English. Wording with no evidence noun ("Bước review … còn thiếu gì?") is not routed here; it fails closed rather than guessing.
5. **Unknown roles or statuses.** A stored approval with an unknown role or status makes the gate UNKNOWN (domain refusal), not a crash.
6. **Instruction change.** `merchant-manager.md` changed, so running teammates need a fresh session (fingerprint).

## 10. GO/NO-GO for NL4D3

**GO for NL4D3 (evidence previews), once you accept this checkpoint.** The read model, routing and verified delivery that previews will build on are in place.

Writes (NL4D4 and later) remain **NO-GO until the NL4D-DEC owner decisions** recorded in the NL4D1 audit are made:
- the actor-attestation policy for LEGAL, ACCOUNTING and PARTNER;
- finality wording;
- signing;
- the evaluators for steps 21 and 22.

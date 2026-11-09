# CP12H.NL4C2B-PREP — Step Execution Safety & Live Acceptance Preparation

> **Final NL4C status (committed together as `feat(merchant): enable trusted test-only step updates`).**
> - **Execution:** Step Update runs **only on the test database** (`coding_agent_merchant_test`), only from the user's own `/solve Xác nhận cập nhật` of a verified preview. **Production (runtime) Direct EXECUTE is disabled in code** (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`).
> - **Automated regression:** the final full suite is in the NL4C commit summary.
> - **Live acceptance:** one user-confirmed Step Update (step 1 READY → IN_PROGRESS of Project `8dd4c68d-…`) returned EXECUTE_SUCCESS, and an **independent read-only PostgreSQL verification** found it EXECUTED_AND_VERIFIED (`cp12h_nl4c2b_live_acceptance.md`).
> - **`confirmation_available`:** `true` only for a READY test-database preview. It means the user may confirm; it never means a write is authorized. This supersedes any "always false" wording below.
> - **Known limitations:** see the "Remaining risks" section of each report.

Baseline `578790c` (+ uncommitted NL4C1 and NL4C2A), branch `feat/cp7-9-merchant-reliability`.
Not committed, not pushed. No live Step Update was run. `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

## 1. Approval concurrency assessment

### Evidence a Step Update depends on

| Table | Read by | Lock in the Step transaction |
|---|---|---|
| `projects` (joined `merchants`) | precondition (basis), domain | `FOR UPDATE OF project` (first) |
| `project_steps` | precondition, domain | `FOR UPDATE OF step` (second) |
| `project_step_dependencies` | precondition, domain | none (written only at Project creation) |
| `document_revisions` | precondition (basis); gate for APPROVAL_GATE steps | gate: `FOR SHARE OF revision` |
| `document_approvals` | precondition (basis); gate | gate: `FOR SHARE OF approval, revision` |
| `procurement_records` | precondition (basis); signing gate | gate: `FOR SHARE OF procurement` |

**Isolation:** READ COMMITTED (the default); each statement sees the latest committed data. The confirmed write runs as:
1. Lock the Project row `FOR UPDATE`.
2. Lock its steps `FOR UPDATE`.
3. Run the NL4C1 precondition (`verify_step_update`, a full re-judgement plus the basis hash).
4. Read the dependencies.
5. If the step is gated, read the gate evidence `FOR SHARE` and run `resolve_database_gate`.
6. Domain `propose_step_transition`.
7. Guarded UPDATE, then the STEP event.
8. Complete the ledger row and the claim, then COMMIT.

### Every path that changes approval or evidence rows

All of them take the same Project row lock first:

| Writer | Lock order |
|---|---|
| `MerchantApprovalRepository.record_approval` | Project `FOR UPDATE` (via the revision's Project) → revisions → approvals |
| `MerchantDocumentRepository.create_revision` (supersedes the previous revision) | Project `FOR UPDATE` → revisions |
| `MerchantProcurementRepository.record_procurement` | Project `FOR UPDATE` → revisions → procurement |
| `MerchantSigningRepository.sign_document` | Project `FOR UPDATE` → revisions → approvals → procurement |

**Consequences:**
- **Lock order is consistent.** Project, then steps or evidence, everywhere, so there is no deadlock cycle.
- **Evidence is per Project.** The gate and the basis read only rows whose `project_id` is the Step's Project, so a writer on another Project cannot affect it.
- **Approved decisions are final.** `record_approval` raises `ApprovalFinalizedError` on any change to an APPROVED decision. The only application-level way to invalidate an approved gate is a **new document revision** that supersedes the approved one.

### Concurrency tests (PostgreSQL, deterministic)

The race points are set with Events, not timing. The file is `tests/merchant/test_nl4c2b_approval_concurrency_postgres.py`, with 6 tests. Each runs on a throwaway Project whose step 5 "Record Partner approval" (a database-verified APPROVAL_GATE) is satisfied by one stored PARTNER approval. The confirmed operation completes step 5.

| Race | Observed |
|---|---|
| A repository writer (new revision) starts **after** the in-transaction re-check | it blocks on the Project lock; the Step Update commits against the evidence it validated; then the revision commits (serialized) |
| A repository writer holds the Project lock **first** | the Step Update waits, then its re-check refuses (`STEP_NOT_READY`, gate re-judged first); nothing written |
| Raw SQL (bypassing every repository) rejects the approval **between** the re-check and the gate read | the gate reads the rejection: `WorkflowGateNotMetError`; nothing written |
| Raw SQL UPDATE / DELETE of the approval, or INSERT of a new revision, **after** the gate read | blocked by the gate's `FOR SHARE` rows (an INSERT of a revision needs a `KEY SHARE` lock on the Project row, which conflicts with the Step's `FOR UPDATE`) until the Step Update commits |

The tests passed 3 times out of 3. **No stale-approval commit was shown, so no code fix was made.** The tests stay as regression guards. They pass on the baseline too, so there is no RED for this phase: they describe behaviour that already held.

**Residual risk:**
- **Raw-SQL phantom approvals.** A raw-SQL INSERT of an *additional* approval row is not blocked by `FOR SHARE`. It cannot invalidate a met gate: each role has at most one approval per revision (`document_approvals_role_unique`), so a second PARTNER decision on the same revision is impossible, and other roles do not count for the Partner gate.
- **Unchecked basis tables.** Changes to basis-only tables made with raw SQL after the precondition (for example procurement rows of an ungated step) do not affect whether the transition is valid.

## 2. Execution receipt verification

**Changes in `attempt_evidence.py`:**
- **New receipt fields:** `payload_hash`, `claim_status` and `ledger_command`, alongside the NL4C2A fields:
  - Merchant, Project and step IDs, the step number, both statuses and both versions;
  - the event ID, the attempt ID, the operation key and the shared transaction ID.
- **New `recover_step_update_receipts(repository, step_id)`.** It rebuilds every evidenced receipt of a step from **PostgreSQL alone**. It joins each STEP event to the ledger row written by the same transaction (`xmin`), derives the attempt identity from the ledger, then fully reconciles it with `step_update_receipt`.

**Tests:** `tests/merchant/test_nl4c2b_receipt_postgres.py`, 3 tests through the real hooks.

| Check | Result |
|---|---|
| The receipt has every required field; the claim is COMPLETED; the ledger command is `step update`; the payload hash equals the attempt's | pass |
| Run state, the team-state directory and the pending store all deleted; `recover_step_update_receipts` returns the identical receipt | pass |
| A teammate's `EXECUTE_SUCCESS` with no evidence, even carrying a fabricated `receipt` object | denied by the terminal-consistency gate; no receipt in run state; recovery returns `[]` |
| A fabricated attempt identity | `EvidenceBindingError` (does not reconcile) |
| A transition written outside Direct EXECUTE (plain repository) | no receipt (no ledger row in its transaction) |

RED with the NL4C2A `attempt_evidence.py` restored: 3 of 3 failed. GREEN: 3 passed.

A teammate cannot invent a receipt:
- it has no file-writing or shell tool beyond `agent_cli.py`/`rag_search.py`;
- the receipt is written only by the trusted hook, from database rows;
- a success report must agree with committed evidence or it is denied.

## 3. Updated agent instructions

| File | Change |
|---|---|
| `.claude/agents/merchant-manager.md` | Removed "no confirmation for a Step update exists yet" and "cannot be confirmed yet"; added the six points below. Its fingerprint (`agent_definition_fingerprint`, sha256 of the file) changes automatically, so any running merchant-manager is shown as `STALE_DEFINITION` and its reuse is refused. **A fresh Claude Code session is required.** |
| `.claude/commands/solve.md` | Step section: on a verified READY **test-database** preview, the lead tells the user they can type `/solve Xác nhận cập nhật <first 8 of step_id>` (or `/solve Hủy cập nhật <id>`). The lead never submits, schedules or relays it, never offers argv or `--merchant-scope`, and offers nothing for a runtime target. The conversational-confirmation section now covers the Step store. |
| `CLAUDE.md` | No change needed (NL4C2A text is still accurate). |
| `merchant_preview_delivery.py`, `intent_gate.py` | Comment and denial text no longer say a Step confirmation does not exist ("is read-only and grants nothing"). No logic change. |
| `tests/merchant/test_nl4a_project_status.py` | Comment only. |

**What the instructions now say:**
1. A Step Update preview is read-only and grants nothing.
2. A verified READY preview leaves a trusted pending Step Update for the session (15 minutes, single use).
3. Only the user's own prompt `/solve Xác nhận cập nhật [<step-id>]` confirms it. The teammate never confirms or sends the phrase, and the lead never submits, schedules or relays it.
4. The confirmation is bound to the exact pending operation. It can pick a record but cannot change it.
5. The confirmed run is an ordinary scoped `merchant_execute`, and the teammate sends the persisted scope once through the existing Direct EXECUTE path.
6. The test database only; production Direct EXECUTE stays disabled.

## 4. Fixes found during this checkpoint

**`tests/merchant/conftest.py` (from NL4C2A):**
- **Problem:** in a run with the test-database password blank, a test that builds an *invalid* test configuration triggered the advisory-lock connection inside `MerchantRepository.__init__`. That replaced the refusal the test expected (`test_d1_invalid_test_configuration_is_refused_before_spend`).
- **Fix:** a lock attempt that cannot connect now defers to the next test-role repository. It still aborts (exit 3) whenever another process actually holds the lock.
- **Before and after:** without a database, 1 failure before the fix; 4006 passed, 137 skipped after.

**Exploration fixture leak (cleaned up):**
- **What happened:** my first exploration script for the gated fixture left its own `PYTEST_NL4C2BX_` rows, because cleanup did not remove document revisions.
- **Fix:** they were removed by a prefix-scoped cleanup of only those rows. The integrity hash was back to `1636f0cb…` immediately afterwards.
- **Prevention:** the committed test module removes approvals and revisions before the Project, and asserts no Merchant with the prefix remains.

## 5. Regression

**Targeted suites, run one after another:**

| Suite | Result |
|---|---|
| NL4C2B approval concurrency (PostgreSQL) | 6 passed |
| NL4C2B receipt (PostgreSQL) | 3 passed |
| NL4C2A (PostgreSQL) | 14 passed |
| NL4C2A unit | 18 passed |
| NL4C1 (PostgreSQL) | 8 passed |
| NL4C1 unit | 60 passed |
| NL4B (PostgreSQL) | 8 passed |
| NL3 (PostgreSQL) | 2 passed |
| NL2 (PostgreSQL) | 11 passed |

**Full pytest:**
- Run alone against the test database: **4123 passed, 20 skipped, 1 xfailed, 0 failed** (97 subtests). That is NL4C2A's 4114 plus 9 new tests.
- Without a database: 4006 passed, 137 skipped, 1 xfailed.

**Other checks:**
- `python .claude/system_test.py`: ALL PASSED.
- Compile (all hooks, all Merchant clients, conftest) and import smoke (intent_gate, merchant_direct_handoff, merchant_pending_confirmation, merchant_preview_delivery, team_result_hook, policy_gate, team_lifecycle): OK.
- `git diff --check`: clean.
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False` (`merchant_direct_handoff.py:65`).

**Test database:**
- The integrity hash `1636f0cb9ac89532b4b4e70ff2759f71c4c6bf4990d9fd86a11dbaecb4c0809c` was the same before and after everything.
- Row counts are unchanged:
  - 2 Merchants, 3 Projects, 70 steps, 7 events;
  - 18 claims and 2 ledger rows, all from before NL4C1.
- 0 `pytest:` claims or ledger rows, 0 ledger rows without a claim, 0 ACTIVE claims, and 0 `PYTEST%` Merchants.
- No production repository was constructed: the e2e fixture refuses any non-test role.

**Step Update write paths:** `write_adapters.update_step` (`transition_step`) is reached only through the CLI `--execute`.
- `agent_cli.py`, the teammate's only surface, refuses every write mode.
- The trusted handoff runs it only for a confirmed, re-judged, test-database scope.
- A typed Step scope is refused at the intent gate.

## 6. Controlled live test (NL4C2B), to be run by the user only

### Prerequisites

1. You accept this checkpoint.
2. **Fresh session.** Quit every Claude Code session in this workspace, then start a new interactive session in psmux with PowerShell 7, with no running merchant-manager pane. The definition changed, so a reused teammate is refused anyway.
3. **No other PostgreSQL work.** No pytest or other process uses `coding_agent_merchant_test` during the test.
4. **Baseline snapshot.** Record it with the read-only script below. The expected hash before step B is the current `1636f0cb9ac89532b4b4e70ff2759f71c4c6bf4990d9fd86a11dbaecb4c0809c`, unless something else changed the database.
5. **Do not touch** `Beta Nguyễn Văn Cừ` (`30fffeaf-…`, NL2), `Beta NL3 Confirmation Test` (`ba5cc7ec-…`, NL3) or `Manual Integration Test 20260915110525`.

### Disposable acceptance Project

This checkpoint does not write the test database. The disposable Project is created at the start of NL4C2B through the already-accepted NL3 path (one user-confirmed Project create), so its creation is itself evidenced. Merchant `NL2_LIVE_BETA` (Beta Cinemas, ACTIVE) is reused. Its step 1 "Draft or renew document" starts READY, with no gate and no Merchant-activation side effect.

| # | You type | Expected |
|---|---|---|
| A1 | `/solve Tạo project mở rạp Beta NL4C2B Step Acceptance cho Merchant Beta Cinemas trên database test, không cần mua sắm` | read-only `project preview`, READY, NOT_AUTHORIZED operation shown; nothing created |
| A2 | `/solve Xác nhận tạo <first 8 of project_id shown>` | one Project create; `EXECUTE_SUCCESS`; 22 steps; step 1 READY |

### The Step Update (one transition: step 1 READY → IN_PROGRESS)

| # | You type | Expected |
|---|---|---|
| B1 | `/solve Bắt đầu bước 1 của Project Beta NL4C2B Step Acceptance của Merchant Beta Cinemas trên database test` | read-only `step preview`: `READY_FOR_CONFIRMATION`, step 1 "Draft or renew document", READY → IN_PROGRESS, `database_target: test`; the lead offers `/solve Xác nhận cập nhật <8 chars>`; **nothing updated** |
| B2 | Check exact target: Project title, Merchant `NL2_LIVE_BETA`, step 1, READY → IN_PROGRESS, test database | if anything differs, type `/solve Hủy cập nhật <id>` and stop |
| B3 | `/solve Xác nhận cập nhật <first 8 characters of step_id>` | system message "Confirmed Step Update: step 1 'Draft or renew document' … from READY to IN_PROGRESS … on the test database. It runs once now."; one execution; `EXECUTE_SUCCESS` |

Do not retry anything. One attempt only; an uncertain or failed result is reported, not repeated. Never type the confirmation as `--merchant-scope` (refused), and never let a schedule or a teammate carry it.

### Independent read-only verification (after B3)

Run it from a normal shell, not the teammate. It connects read-only to the test database.

```powershell
$env:PYTHONIOENCODING = "utf-8"
@'
import sys, json; sys.path.insert(0, ".")
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.attempt_evidence import recover_step_update_receipts
r = MerchantRepository(role="test"); assert r.config.database == "coding_agent_merchant_test"
with r.connection(read_only=True) as c:
    p = c.execute("SELECT id, version, status FROM merchant_ops.projects WHERE title = %s",
                  ("Beta NL4C2B Step Acceptance",)).fetchone()
    s = c.execute("SELECT id::text, status, version, actual_start FROM merchant_ops.project_steps"
                  " WHERE project_id = %s AND sequence_number = 1", (p["id"],)).fetchone()
    e = c.execute("SELECT event_type, old_values, new_values FROM merchant_ops.project_events"
                  " WHERE entity_type = 'STEP' AND entity_id = %s::uuid", (s["id"],)).fetchall()
print(dict(p), dict(s), [dict(x) for x in e], sep="\n")
print(json.dumps(recover_step_update_receipts(r, s["id"]), indent=2, default=str))
'@ | .venv\Scripts\python.exe -W ignore -
```

## 7. Expected before/after database state (B3 only)

| Object | Before B3 | After B3 |
|---|---|---|
| step 1 of `Beta NL4C2B Step Acceptance` | READY, version 1, `actual_start` NULL | IN_PROGRESS, version 2, `actual_start` set |
| other 21 steps, the Project row, the Merchant | unchanged | unchanged (a Step transition does not update `projects`) |
| `project_events` STEP rows for step 1 | 0 | 1, `STEP_STARTED`, old `{status: READY, version: 1}`, new `{status: IN_PROGRESS, version: 2}` |
| `merchant_execution_claims` | N | N + 1, `COMPLETED`, `merchant-scope:v1:…` key |
| `merchant_execution_ledger` | M | M + 1, result `{command: "step update", execution_attempt_id}` |
| `recover_step_update_receipts(step 1)` | `[]` | exactly 1 receipt: the Beta Merchant, step 1, READY → IN_PROGRESS, versions 1 → 2, claim COMPLETED |
| NL2/NL3 acceptance Projects, other Merchants | unchanged | unchanged |
| run state `merchant_step_update_receipt` | absent | `status: RECONCILED`, equal to the recovered receipt |

A2 separately adds 1 Project, 22 steps, its dependencies, 1 PROJECT event, and 1 claim and ledger row.

## 8. Rollback and fail-closed expectations

- **No automatic rollback of a committed Step Update.** If B3 commits, step 1 stays IN_PROGRESS. The disposable Project may be left as acceptance evidence; nothing should "undo" it by hand.
- **Refused before spend.** If anything changed between B1 and B3 (Project, step, dependencies, approvals, revisions, procurement or Merchant), the attempt is refused before spend (`PREFLIGHT:STEP_*`), or, if the change lands in between, inside the transaction. Nothing is written. Preview again (B1) for a new confirmation.
- **Crash or disconnect before commit:** a full rollback; the attempt is fenced (REVOKED claim) and FAILED; there is never a retry.
- **Crash after commit:** settled SUCCEEDED from the claim and ledger at TeammateIdle; the receipt can be rebuilt with `recover_step_update_receipts`; never re-executed.
- **Refused without spending:**
  - a missing or expired pending record, the wrong session, or a replayed confirmation;
  - an edited step id, target status or database;
  - a scheduled or relayed confirmation, a stale teammate, or an unverified pane.
- **Contradictory report.** A teammate report that contradicts the evidence is denied, and the teammate is released only on SUCCEEDED evidence.
- **Runtime target:** refused at the gate (record not spent) and at preflight (`RUNTIME_EXECUTION_DISABLED`).

## 9. Remaining risks

1. **Raw SQL bypassing the repositories** (section 1, residual): it cannot invalidate a met PARTNER gate during the transaction, but basis-only tables are not locked.
2. **The same OS user is trusted.** Any same-user process with Python and the test credentials can run `cli.py --database test step update --execute` directly; this is documented in CLAUDE.md as defence in depth, not a sandbox. `agent_cli.py` (the teammate's only surface) refuses every write mode.
3. **The test-run lock** covers only pytest processes; a live `/solve` and a pytest run are not mutually excluded (prerequisite 3).
4. **The receipt is not shown in the lead's final summary.** The lead's summary still comes from the evidence-checked teammate report; the receipt is in the run state and can be rebuilt from PostgreSQL.
5. **The pending record is spent at confirmation** (as in NL3); a dispatch failure afterwards (for example a stale teammate) requires a new preview.

## 10. GO/NO-GO

- **NL4C2B-PREP (this checkpoint):** GO for your review.
- **NL4C2B (one live Step Update on the test database):** GO only after you accept this checkpoint and follow prerequisites 1–5 in a fresh session. The write happens only when you type B3 yourself.
- **Runtime/production Step Update:** NO-GO (disabled in code; needs separate approval).

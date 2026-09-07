# Merchant Project Manager — Checkpoint 8 Handoff

**Date:** September 7, 2026
**Branch:** `feat/workspace-rag`
**Base commit:** `370b0d0` (`Complete Checkpoint 7 Merchant intent and policy integration`)
**Completion commit:** Pending staging review
**Checkpoint:** 8 — Deadline and Alert Calculation
**Status:** Implementation and verification complete; staging review pending

## 1. Outcome

Checkpoint 8 delivers a deterministic, read-only alert view over authoritative PostgreSQL
Merchant workflow state. It centralizes deadline calculation, hardens blocker and missing-gate
detection, and adds bounded global alert queries without weakening Checkpoint 7's controlled
mutation boundary.

The completed view calculates the five persisted alert types:

- `OVERDUE`;
- `DUE_TODAY`;
- `DUE_SOON`;
- `BLOCKED`;
- `MISSING_GATE`.

A blocked overdue step produces independent `BLOCKED` and `OVERDUE` facts. Checkpoint 8 does not
add a sixth alert type, enqueue a delivery, create a project event, or update workflow state.

## 2. Deadline policy

The centralized policy is:

```text
.claude/agents/tools/merchant/deadline_policy.py
```

It uses `Asia/Ho_Chi_Minh`, a default due-soon window of seven calendar days, and exact business
date boundaries:

| Difference from business date | Result |
|---:|---|
| Less than 0 days | `OVERDUE` |
| Exactly 0 days | `DUE_TODAY` |
| 1 through 7 days by default | `DUE_SOON` |
| Beyond the configured window | No deadline alert |

Date, naive datetime, aware datetime, and strict ISO string inputs normalize through one policy.
Invalid input and invalid configuration fail closed. Terminal projects and terminal steps emit no
deadline alert.

## 3. Blocker and missing-gate calculation

The existing `MerchantProjectChecker` remains the single calculator. It now:

- preserves the exact `project_step_id`, step name, and `branch_key` for parallel branches;
- reports deadline and blocker facts independently and sorts them deterministically;
- evaluates the allowlisted `requires_procurement` condition and rejects invalid condition keys;
- detects incomplete dependencies without suppressing unrelated ready branches;
- selects the latest active document revision and never carries approval from a superseded
  revision;
- checks Partner and Legal approval requirements against the same revision;
- validates signing prerequisites before a signing-gate step completes;
- requires an exact Purchase Request when the workflow requires a PR, so a Purchase Order cannot
  satisfy that gate;
- validates reused-document identity, signed state, signing timestamp, validity period,
  supersession, and payment-period requirements.

Gate findings use stable reason codes in `condition_fingerprint`. Deduplication includes project,
step, alert type, business due date, condition fingerprint, and delivery channel, so repeated reads
produce stable keys without persisting anything.

## 4. Read repository and global filters

`MerchantReadRepository.list_alert_candidate_project_ids` provides a parameterized, read-only
candidate query. It supports optional merchant and project filters, excludes terminal projects,
and orders candidates by creation time and project id.

The repository default is 100 candidate projects and the reviewed maximum is 500. It fetches one
sentinel row beyond the selected bound and fails with a narrowing instruction instead of silently
returning a partial global result.

Project snapshots now include the payment period and reused-document revision reference. When an
existing document is reused, the read repository loads that exact signed revision as supporting
evidence even when it belongs to an earlier project.

Calculated results can be filtered by:

- merchant id;
- project id;
- one of the five alert types;
- inclusive `business_due_date <= due-date-before`.

All returned records pass through the existing redaction boundary.

## 5. CLI contract

Both of these forms remain valid:

```text
project alerts <project_id>
project alerts [--merchant-id UUID] [--project-id UUID]
               [--alert-type TYPE] [--due-date-before YYYY-MM-DD]
```

The positional project id is retained for compatibility. Equivalent positional and flagged ids
are accepted; conflicting ids fail before repository dispatch. UUID, date, and alert-type filters
are validated before use, output is deterministic JSON, and the Merchant agent adapter forwards
the same read-only filters to the fixed runtime target.

The candidate limit is an internal repository/command safeguard, not a public CLI option.
`--project-limit` remains deliberately undocumented and rejected.

## 6. Read-only and delivery boundary

The ordinary alert command may read project, step, dependency, document, approval, procurement,
and identifier evidence. It may not:

- update a project or step;
- create a project event;
- enqueue or claim an alert delivery;
- record an alert attempt;
- send an email, Slack message, or internal notification;
- acquire confirmed runtime-write authority.

The existing delivery worker remains separate and compatible with the seven-day default. Making
that worker production-ready remains future Checkpoint 10 work.

## 7. Files added

- `.claude/agents/tools/merchant/deadline_policy.py`
- `.claude/documents/MERCHANT_CHECKPOINT_8_PLAN_2026-09-07.md`
- `.claude/documents/MERCHANT_CHECKPOINT_8_HANDOFF_2026-09-07.md`
- `tests/merchant/test_deadline_policy.py`
- `tests/merchant/test_blocker_gate_calculation.py`
- `tests/merchant/test_alert_read_query.py`
- `tests/merchant/test_alert_cli.py`
- `tests/merchant/test_checkpoint_8_alert_read_live.py`
- `tests/merchant/test_checkpoint_8_plan.py`
- `tests/merchant/test_checkpoint_8_documentation.py`

## 8. Principal files updated

- `.claude/agents/tools/merchant/checker.py`
- `.claude/agents/tools/merchant/cli.py`
- `.claude/agents/tools/merchant/read_commands.py`
- `.claude/clients/merchant/read_repository.py`
- `.claude/clients/merchant/repository.py`
- `.claude/workers/merchant_alert.py`
- `.claude/documents/MERCHANT_CHECKPOINT_7_HANDOFF_2026-09-07.md`
- `.claude/documents/README.md`
- `.claude/documents/ARCHITECTURE.md`
- `README.md`

Existing Checkpoint 3, 5, 6, and 7 compatibility tests were updated only where the completed
Checkpoint 8 read contract extends their historical expectations.

## 9. Verification evidence

| Gate | Evidence |
|---|---:|
| 8.0 repository baseline and Checkpoint 7 finalization | 46 passed; system 80/80 |
| 8.1 centralized deadline policy | Focused suite passed; system 80/80 |
| 8.2 blocker and missing-gate calculation | Focused suite passed; system 80/80 |
| 8.3 read repository and global filters | Focused suite passed; system 80/80 |
| 8.4 alert CLI integration | Focused suite passed; system 80/80 |
| 8.5 complete focused regression | 295 passed |
| 8.5 complete non-live regression | 1,374 passed, 120 subtests passed |
| 8.5 structural validation | 80/80 passed |
| 8.6 pre-lifecycle readiness | 1 passed |
| 8.6 cleanup-safe alert-read lifecycle | 1 passed |
| 8.6 post-lifecycle readiness | 1 passed |

`git diff --check` passed at every completed gate. The complete non-live suite explicitly
excluded integration tests. Gate 8.6 was separately enabled only after exact guards verified
database `coding_agent_merchant_test`, user `merchant_test`, host `127.0.0.1`, and port `5434`.

## 10. Safe test-database lifecycle

The Gate 8.6 lifecycle began with migration versions exactly 1, 2, and 3; no pending, missing,
checksum-conflicting, or description-conflicting migration; matching standard templates and
migration 3 indexes; correct least-privilege grants; and an empty Merchant business state.

It created two fictitious merchants, two projects, and three steps under generated UUIDs. The
read checks proved:

- two consecutive global queries were identical;
- both projects were returned in deterministic order;
- the target project produced exactly one `OVERDUE`, one `BLOCKED`, and one `DUE_SOON` fact;
- merchant, project, alert-type, due-date, combined, and legacy positional filters were exact;
- project and step versions and timestamps were unchanged;
- zero project events and zero alert deliveries were created.

Cleanup deleted only the generated records and template fixture. The final business counts were
zero in every checked table, and the post-lifecycle readiness check passed. The accepted final
marker was `CHECKPOINT_8_GATE_6_SAFE_TEST_DATABASE_ALERT_LIFECYCLE_HOTFIX_V2_PASSED`.

No runtime database was read or mutated during Checkpoint 8 verification.

## 11. Remaining boundaries

Checkpoint 8 does not initialize the private runtime catalog and does not authorize applying
migration 3 to the runtime database. It also does not productionize alert delivery.

Real Merchant names, codes, contacts, identifiers, credentials, `.env` files, database dumps,
runtime session state, and generated archives must remain outside Git and RAG ingestion.

Any runtime migration or catalog import requires a fresh read-only readiness plan, exact target
and role verification, checksum and backup review, explicit authorization, and separate
post-operation verification.

## 12. Next checkpoint — Checkpoint 9

Checkpoint 9 is the final currently planned core Phase 4 checkpoint. Build it in this order:

1. Finalize the Checkpoint 8 handoff with its pushed commit and clean-checkout evidence.
2. Define and validate a private 22-record Merchant catalog contract without copying real values
   into Git, test fixtures, logs, archives, prompts, or RAG.
3. Perform read-only runtime readiness checks for database identity, migration state, roles,
   backups, templates, and current business state.
4. Produce an explicit migration and initialization plan with record-count and status invariants.
5. Apply only after the user separately authorizes the exact runtime target and operation.
6. Verify the 22 Merchant records, expected `ONBOARDING` or `ACTIVE` states, template integrity,
   idempotency, and rollback/recovery evidence.

Checkpoint 10 remains a future alert-delivery extension and is not required to complete the core
Phase 4 Merchant manager.

## 13. Staging and commit boundary

Before committing Checkpoint 8:

1. Run the Gate 8.7 documentation compatibility and focused alert regression.
2. Run the complete root non-integration regression and structural validation.
3. Review the complete modified and untracked file list against sections 7 and 8.
4. Confirm no `.env`, credential, cache, archive, persisted runtime state, database dump, or real
   Merchant data is staged.
5. Stage only the reviewed Checkpoint 8 files and run `git diff --cached --check`.
6. Commit and push only to `feat/workspace-rag` after confirming the branch.

After the commit, replace the pending completion fields above with the actual commit SHA and
record the clean-checkout structural validation result during Checkpoint 9 Gate 9.0.

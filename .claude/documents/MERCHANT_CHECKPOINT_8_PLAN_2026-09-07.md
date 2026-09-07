# Merchant Project Manager — Checkpoint 8 Build Plan

**Date:** September 7, 2026
**Branch:** `feat/workspace-rag`
**Base commit:** `370b0d0` (`Complete Checkpoint 7 Merchant intent and policy integration`)
**Checkpoint:** 8 — Deadline and Alert Calculation
**Status:** Gate 8.0 baseline verified; Implementation and verification complete; staging review pending

## 1. Goal

Checkpoint 8 delivers a deterministic, read-only alert view over authoritative PostgreSQL
Merchant workflow state. It must calculate deadlines and blockers without changing project,
workflow, document, approval, procurement, identifier, event, or delivery state.

The public result must cover:

- overdue steps;
- steps due today;
- steps due soon using a configurable window;
- blocked-and-overdue state without inventing a sixth database alert type;
- missing document, signing, approval, and procurement gates;
- workflow blockers caused by incomplete dependencies or failed preconditions;
- deterministic ordering and stable deduplication;
- project-specific and global filtered alert queries.

Alert delivery is not part of Checkpoint 8. No email, Slack, internal delivery enqueue, claim, or
send operation may run from the read-only alert command.

## 2. Existing baseline

The repository already contains an earlier alert calculator in
`.claude/agents/tools/merchant/checker.py`. It currently provides:

- `Asia/Ho_Chi_Minh` business-date calculation;
- `OVERDUE`, `DUE_TODAY`, `DUE_SOON`, `BLOCKED`, and `MISSING_GATE` alerts;
- suppression for completed, cancelled, skipped, and superseded records;
- dependency and procurement checks;
- stable content-based deduplication;
- project-scoped `project alerts <project_id>` and `project blockers <project_id>` reads;
- unit coverage in `tests/merchant/test_checker.py` and `tests/merchant/test_read_commands.py`.

Checkpoint 8 will extend and harden this baseline. It must not create a duplicate checker or a
second alert model.

## 3. Contract reconciliation

The authoritative contract is section 19 and Checkpoint 8 in
`.claude/documents/MERCHANT_PROJECT_MANAGER.md`.

The following differences remain between that contract and the current baseline:

| Area | Existing baseline | Checkpoint 8 target |
|---|---|---|
| Due-soon window | Configurable, default 3 days | Central policy with the documented 7-day default and boundary tests |
| Blocked and overdue | Separate `BLOCKED` and `OVERDUE` facts | Preserve both facts and prove deterministic coexistence |
| Gate detection | Primarily step type/name plus persisted records | Prefer explicit workflow condition metadata with safe compatibility fallback |
| Query scope | One required project id | Optional merchant/project/type/date filters across projects |
| CLI output | Project alert list | Deterministic structured facts with filters and supporting identifiers |
| Delivery | Separate worker code exists | Remains outside the read-only query path |

The database constraint already allows exactly five alert types. Checkpoint 8 will represent a
blocked overdue step with both `BLOCKED` and `OVERDUE`; it will not add an undocumented
`BLOCKED_AND_OVERDUE` type or require a migration merely to combine those facts.

## 4. Build gates

### Gate 8.0 — Repository consistency and Checkpoint 7 finalization

- Verify remote branch head `370b0d0` and a clean checkout.
- Run structural validation from the clean checkout.
- Finalize the Checkpoint 7 handoff with its actual commit and evidence.
- Record this Checkpoint 8 baseline and the remaining contract gaps.

### Gate 8.1 — Deadline policy

- Centralize timezone and due-soon policy.
- Cover aware and naive timestamps, date strings, exact boundaries, missing dates, and invalid
  configuration.
- Prove terminal projects and terminal steps never emit deadline alerts.

### Gate 8.2 — Blocker and missing-gate calculation

- Prove blocked and overdue facts coexist deterministically.
- Harden document, signing, approval, procurement, dependency, and precondition detection.
- Preserve all parallel branches and identify the exact affected step.

### Gate 8.3 — Read repository and global filtering

- Add a read-only repository path for candidate projects.
- Support optional merchant id, project id, alert type, and due-date-before filters.
- Prevent unbounded or mutating access and preserve redaction.

### Gate 8.4 — CLI integration

- Align `project alerts` with the global Phase 4A query contract.
- Keep project-specific compatibility where unambiguous.
- Return deterministic JSON and fail closed on invalid filters.

### Gate 8.5 — Complete non-live regression

- Run focused checker, repository, command, CLI, agent, and policy tests.
- Run all root tests with integration tests explicitly excluded.
- Run structural and whitespace validation.

### Gate 8.6 — Safe test-database lifecycle

- Verify the exact empty test database before the lifecycle.
- Exercise read-only alert calculation with fictitious records and cleanup.
- Verify the empty state again after cleanup.

### Gate 8.7 — Handoff and staging review

- Record implemented behavior, evidence, remaining boundaries, and the Checkpoint 9 plan.
- Stage only the reviewed Checkpoint 8 files.
- Commit and push only after explicit user review.

## 5. Completion criteria

Checkpoint 8 is complete only when:

1. Alert calculation is deterministic and read-only.
2. Deadline boundaries use the documented Merchant timezone and configurable window.
3. Blocked, overdue, gate, procurement, dependency, and parallel-branch cases are tested.
4. Global filters match the architecture contract and cannot expose sensitive values.
5. The ordinary `project alerts` command cannot enqueue, claim, deliver, or mutate alerts.
6. Focused, full non-live, structural, and safe live test-database gates pass.
7. The handoff is reviewed, committed, pushed, and verified from a clean checkout.

## 6. Remaining roadmap

Checkpoint 8 is not the final core checkpoint.

- **Checkpoint 9 — Private Runtime Initialization:** import the real 22-record Merchant catalog
  from a private source, keep it outside Git and RAG, and verify real workflows under explicit
  runtime authorization.
- **Checkpoint 10 — Alert Worker (future):** productionize independent alert delivery,
  deduplicated claiming, retries, and delivery channels. This is a future operational phase, not
  required for the read-only Checkpoint 8 alert view.

Checkpoint 9 is the final currently planned core Phase 4 checkpoint. Checkpoint 10 remains an
explicit future extension.

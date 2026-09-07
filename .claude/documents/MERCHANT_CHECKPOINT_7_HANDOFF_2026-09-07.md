# Merchant Project Manager — Checkpoint 7 Handoff

**Date:** September 7, 2026
**Branch:** `feat/workspace-rag`
**Base commit:** `ba16daa` (`Complete Checkpoint 6 merchant manager agent`)
**Completion commit:** Pending staging review
**Checkpoint:** 7 — Intent and Policy Integration
**Status:** Implementation and verification complete; staging review pending

## 1. Outcome

Checkpoint 7 connects Merchant operational intent to the existing controlled-orchestration
envelope, exact confirmation policy, single teammate dispatch, and trusted runtime apply path.

The completed flow supports:

- `merchant_read` for current Merchant and project state;
- `merchant_propose` for the nine allowlisted write commands without mutation;
- `merchant_apply` only after exact proposal confirmation and policy acceptance;
- exclusive routing of every Merchant operation to `merchant-manager`;
- one policy-validated dispatch and at most one runtime mutation attempt;
- fail-closed denial for stale, mismatched, replayed, malformed, or untrusted authority.

The ordinary `agent_cli.py` entry point remains read/propose-only. Checkpoint 7 does not expose a
shell apply command, database selector, credential parameter, authorization flag, reusable token,
or environment-variable bypass.

## 2. Intent routing

The intent model now recognizes these operations:

| Operation | Meaning | Risk boundary |
|---|---|---|
| `merchant_read` | Read current Merchant/project state | Non-mutating |
| `merchant_propose` | Normalize an allowlisted write and return a redacted proposal | Non-mutating |
| `merchant_apply` | Apply one previously proposed and exactly confirmed mutation | External write |

Local reconciliation prevents the model from weakening an explicit Merchant operation. Merchant
operations select only `merchant-manager`, reject mixed operational rosters, and preserve the
existing no-envelope-no-run, clarification, member, tool-call, round, and budget limits.

An apply request without the exact confirmation is not treated as a proposal and is not
dispatched. Ambiguous Merchant/project identifiers, fields, or required expected versions must be
clarified before teammate creation.

## 3. Exact confirmation contract

Every successful proposal returns a versioned `confirmation_token` plus redacted confirmation
metadata. The token is canonical and binds:

- normalized allowlisted command;
- `runtime` database target;
- expected version when required;
- payload hash;
- proposal hash;
- confirmation hash.

The intent hook accepts the token only through the dedicated `--merchant-confirmation` input. A
general `--confirm`, approval-like prose, a changed encoding, extra fields, non-runtime target,
hash mismatch, or raw payload cannot authorize `merchant_apply`.

After validation, the persisted state contains only the structured redacted confirmation. The
token and raw proposal payload are deliberately absent.

## 4. Policy-validated dispatch

The policy gate accepts one `merchant-manager` dispatch only when all of these conditions hold:

1. The saved operation is exactly `merchant_apply`.
2. The selected roster is exactly `merchant-manager`.
3. Risk is `external_write` or `destructive` and confirmation is exact.
4. The assignment contains exactly one `MERCHANT_DISPATCH_AUTHORIZATION_JSON` block.
5. Every redacted field matches the persisted confirmation.
6. No confirmation token, raw payload, extra field, database override, or credential is present.

An accepted dispatch writes a receipt and consumes the dispatch binding before the Agent call is
allowed. Repeated, concurrent, malformed, stale, or altered dispatches fail closed.

Dispatch authority is not database-write authority. The teammate cannot turn the redacted block
into a CLI option or capability, and the lead cannot substitute itself or another teammate.

## 5. Trusted runtime authorization

The only confirmed runtime-write bridge is:

```text
claude.system.merchant_runtime_handoff.invoke_confirmed_merchant_session_apply
```

Controlled orchestration supplies the exact session id and allowlisted apply arguments directly
to this in-process function. The function:

1. parses and validates an exact apply command before touching authority;
2. locks and loads the real persisted session state;
3. verifies the confirmation, accepted dispatch receipt, operation, roster, risk, and spent flag;
4. permanently reserves and saves the single issuance slot;
5. issues an opaque, expiring, non-serializable capability;
6. passes that capability through the internal Python call chain to the existing CLI and
   repository adapter.

The reservation is saved before capability issuance or repository dispatch. This deliberately
provides at-most-once execution: success, mismatch, expiry, repository failure, concurrent use,
or an uncertain process interruption spends the attempt. A retry requires a fresh proposal,
confirmation, envelope, and dispatch.

The legacy boolean `runtime_authorized=True`, a CLI flag, environment variable, confirmation
token, copied capability, reconstructed state, teammate prompt, or direct repository call is not
authority. The ordinary Merchant agent adapter still rejects `--apply`.

## 6. Persisted state and package boundary

`.claude/hooks` is now an importable `claude.hooks` package. The intent, policy, round-counter,
cleanup, and runtime-state hooks keep their standalone execution behavior while sharing the same
locked session document with the in-process handoff.

Session state is written atomically and guarded by a per-session lock. The runtime issuance slot
is persisted before leaving that lock. Cleanup uses the same state boundary, so a capability
cannot be reconstructed from a deleted or partially written file.

## 7. Safety invariants

Checkpoint 7 preserves these invariants:

- no valid envelope means no run;
- clarification and exact confirmation happen before dispatch;
- only selected agents may run and Merchant operations have one owner;
- proposal generation never mutates PostgreSQL;
- runtime apply has no public CLI, text, JSON, boolean, or environment authority;
- tokens and raw payloads never enter persisted run state or dispatch prompts;
- authorization is exact, expiring, non-serializable, and one-use;
- mutation attempts are at-most-once and uncertain outcomes are never retried;
- runtime and test database targets remain isolated;
- no live database migration or runtime database mutation is implicit.

## 8. Files added

- `.claude/hooks/__init__.py`
- `.claude/system/merchant_runtime_handoff.py`
- `tests/merchant/test_confirmation_contract.py`
- `tests/merchant/test_merchant_confirmation_gate.py`
- `tests/merchant/test_merchant_dispatch_gate.py`
- `tests/merchant/test_merchant_intent_routing.py`
- `tests/merchant/test_merchant_session_apply.py`
- `tests/merchant/test_runtime_authorization.py`
- `tests/merchant/test_runtime_handoff.py`
- `.claude/documents/MERCHANT_CHECKPOINT_7_HANDOFF_2026-09-07.md`
- `tests/merchant/test_checkpoint_7_documentation.py`

## 9. Principal files updated

- `.claude/system/intent_parser.py`
- `.claude/hooks/intent_gate.py`
- `.claude/hooks/policy_gate.py`
- `.claude/hooks/runtime_state.py`
- `.claude/hooks/round_counter.py`
- `.claude/hooks/cleanup_state.py`
- `.claude/agents/tools/merchant/cli_contract.py`
- `.claude/agents/tools/merchant/cli.py`
- `.claude/agents/tools/merchant/write_commands.py`
- `.claude/agents/tools/merchant/agent_cli.py`
- `.claude/agents/merchant-manager.md`
- `.claude/commands/solve.md`
- `.claude/agents.json`
- `pyproject.toml`
- `README.md`
- `CLAUDE.md`
- `.claude/documents/ARCHITECTURE.md`
- `.claude/documents/README.md`

Existing Checkpoint 5 and 6 compatibility tests were updated only where the completed
Checkpoint 7 contract extends their historical boundary.

## 10. Verification evidence

| Gate | Evidence |
|---|---:|
| 7.0 repository consistency and Checkpoint 6 finalization | 23 passed, 23 subtests passed; system 80/80 |
| 7.1 Merchant intent routing | 34 passed; system 80/80 |
| 7.2 exact Merchant confirmation | 207 passed, 23 subtests passed; system 80/80 |
| 7.3 Merchant dispatch enforcement | Focused suite passed; system 80/80 |
| 7.4 trusted runtime authorization | Focused suite passed; system 80/80 |
| 7.5 persisted session apply | 181 passed, 23 subtests passed; system 80/80 |
| 7.6 complete non-live regression | 1,223 passed, 8 deselected, 120 subtests passed; system 80/80 |
| 7.7 pre-lifecycle readiness | 1 passed |
| 7.7 cleanup-safe test-database lifecycle | 1 passed |
| 7.7 post-lifecycle readiness | 1 passed |

`git diff --check` passed at every completed gate. The non-live suite explicitly excluded all
integration tests. The live lifecycle was separately enabled only after an exact safety guard
verified database `coding_agent_merchant_test`, user `merchant_test`, host `127.0.0.1`, and port
`5434`.

The readiness checks before and after the lifecycle both proved:

- migration versions are exactly 1, 2, and 3;
- no migration is pending, missing locally, or in checksum/description conflict;
- all Merchant business tables are empty;
- all four standard workflow templates match their manifests;
- migration 3 indexes and least-privilege grants remain correct;
- the test connection is read-only outside the cleanup-safe lifecycle.

The live lifecycle completed in 29.69 seconds and cleanup restored the empty business state. No
runtime database was read or mutated during Gate 7.7.

## 11. Runtime database boundary

Migration 3 remains unapplied to the runtime database. Checkpoint 7 authorizes no runtime
migration, catalog import, or general database-write access. Any future runtime migration still
requires a fresh read-only plan, checksum review, backup/readiness review, exact target and role
verification, and explicit authorization.

Real Merchant data remains outside Git, test fixtures, archives, logs, and RAG ingestion.

## 12. Next checkpoint — Checkpoint 8

Checkpoint 8 adds deadline and alert calculation without weakening the completed mutation
boundary. Build it in this order:

1. Define one timezone-aware deadline policy and explicit due-soon windows.
2. Calculate overdue, due-today, and due-soon conditions from persisted workflow state.
3. Detect blocked-and-overdue steps, missing signing/approval/procurement gates, and workflow
   blockers across parallel branches.
4. Make `project alerts` return deterministic structured alert facts and supporting identifiers.
5. Keep alert calculation read-only and separate from alert delivery.
6. Add unit tests for boundary times, missing dates, completed/cancelled steps, dependencies,
   parallel branches, and duplicate suppression.
7. Add repository and CLI contract tests, then run the complete non-live regression.
8. Run a separately authorized cleanup-safe lifecycle only against the exact test database.

Checkpoint 8's deliverable is a deterministic, queryable alert view. It does not send email,
Slack, or other notifications; delivery remains future Checkpoint 10 work.

## 13. Staging and commit boundary

Before committing Checkpoint 7:

1. Review the complete modified and untracked file list against sections 8 and 9.
2. Confirm no `.env`, credential, cache, archive, runtime state, or real Merchant data is staged.
3. Run the Gate 7.8 focused documentation tests and final non-live regression.
4. Run `git diff --cached --check` after staging only the intended files.
5. Commit the complete Checkpoint 7 implementation and finalized handoff together.
6. Push only to `feat/workspace-rag` after confirming the branch and remote.

After the commit, replace the pending completion fields above with the actual commit SHA and
record the clean-checkout structural validation result.

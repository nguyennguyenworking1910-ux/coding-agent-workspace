# Merchant Project Manager — Checkpoint 9 Build Plan

**Date:** September 7, 2026
**Branch:** `feat/workspace-rag`
**Base commit:** `efa05fa` (`Complete Checkpoint 8 Merchant deadline and alert calculation`)
**Checkpoint:** 9 — Private Runtime Initialization
**Status:** Complete; implementation commit `2ac90c0a57ac857da8d537b8aeeea7b04fc97cb9` pushed and verified

## 1. Goal

Checkpoint 9 is the final currently planned core Phase 4 checkpoint. It initializes the runtime
Merchant database from a private 22-record UTF-8 catalog, verifies the intended `ONBOARDING` and
`ACTIVE` lifecycle states, and proves that the initialized data works with the completed workflow,
CLI, policy, and alert boundaries.

Real Merchant values must never be added to Git, test fixtures, documentation, generated
archives, ordinary logs, prompts, or RAG ingestion.

## 2. Verified baseline

The pushed Checkpoint 8 boundary is:

```text
efa05fa10bc32f1fbf2b8c2d5d82c1d5b5ec156e
```

Remote verification established:

- commit message `Complete Checkpoint 8 Merchant deadline and alert calculation`;
- exactly 27 reviewed Checkpoint 8 files;
- `git show --check` passes;
- a detached checkout is clean;
- structural validation passes 81/81.

Checkpoint 8's alert view remains read-only. Checkpoint 9 must not weaken its delivery, redaction,
or controlled runtime-mutation boundaries.

## 3. Private catalog boundary

The catalog source is supplied locally at runtime through an explicit private path. The repository
stores only the importer, schema contract, validators, and fictitious test fixtures.

The private source must contain exactly 22 Merchant records. Each record will be validated before
any write for:

- required UTF-8 `code` and `name`;
- optional normalized `region_code`;
- exact allowlisted `account_status` of `ONBOARDING` or `ACTIVE`;
- unique normalized code;
- stable identity and deterministic ordering;
- no contact, integration identifier, credential, or unrelated project payload.

Validation errors must identify a safe record position and reason without printing the private
value. A complete validation pass produces only counts, hashes, and redacted summaries.

The exact input format, identity strategy, normalization rules, and source hash contract will be
locked in Gate 9.1 before a runtime connection is permitted.

## 4. Runtime authority boundary

Checkpoint 9 separates planning, migration, import, and workflow verification:

1. Catalog validation is local and non-mutating.
2. Runtime readiness is read-only.
3. Migration planning is read-only.
4. Applying runtime migrations 2 and 3 requires explicit authorization for the exact target and
   reviewed checksums.
5. Standard-template initialization requires a separate explicit authorization after migrations.
6. Catalog initialization requires another explicit authorization bound to the validated
   source hash and exact 22-record plan.
7. Any real workflow mutation requires its own Checkpoint 7 proposal, exact confirmation,
   policy-accepted dispatch, and one-use runtime authorization.

No `--force`, database override, credential argument, environment authorization flag, generic
confirmation, or reusable token may bypass these gates.

## 5. Idempotency and failure behavior

Initialization must run in one database transaction and be all-or-nothing. Before mutation it
must reject:

- an unexpected database, role, encoding, schema, or migration state;
- a non-empty or incompatible Merchant catalog state;
- duplicate codes or conflicting identities;
- a source hash that differs from the reviewed plan;
- any record count other than exactly 22;
- any status outside `ONBOARDING` and `ACTIVE`.

A repeat using the identical source must produce a verified no-op. A changed, partial, or
conflicting source must fail closed rather than update existing runtime records silently.

## 6. Build gates

### Gate 9.0 — Repository consistency and Checkpoint 8 finalization

- Verify the pushed Checkpoint 8 commit and exact 27-file boundary.
- Run structural validation from a clean detached checkout.
- Finalize the Checkpoint 8 handoff with commit and verification evidence.
- Record this Checkpoint 9 plan without accessing runtime or private catalog data.

### Gate 9.1 — Private catalog contract and isolation

- Define a strict local input schema for exactly 22 records.
- Implement UTF-8, uniqueness, status, region, and unknown-field validation.
- Bind the validated plan to a deterministic source hash.
- Prove errors and summaries never expose private values.
- Use only fictitious fixtures in tests.

### Gate 9.2 — Import planner and transaction boundary

- Build a deterministic redacted import plan.
- Define stable Merchant identity and identical-source idempotency.
- Reject non-empty, partial, duplicate, or conflicting target states.
- Prove no database connection occurs during local validation.
- Prove no write occurs during plan mode.

### Gate 9.3 — Read-only runtime readiness

- Verify exact runtime database, application role, UTF-8 encoding, schema, and migration history.
- Inspect current Merchant counts and template state without printing private rows.
- Verify backup and recovery prerequisites.
- Accept the evidenced migration-1-only, zero-template baseline as a safe pre-upgrade state.
- Produce a migrations 2-and-3, template, and catalog initialization readiness report.

### Gate 9.4 — Runtime migrations 2 and 3

- Stop for explicit authorization of the exact migration target and both reviewed checksums.
- Apply pending migrations 2 and 3 with the owner role only and one migration-runner session.
- Verify migrations 1, 2, and 3, indexes, constraints, grants, and application read-only checks.
- Make no template or catalog change in this gate.

### Gate 9.5 — Private runtime catalog initialization

- Initialize the four immutable standard templates under separate explicit authorization.
- Verify their stable identities and fingerprints before catalog access.
- Revalidate the exact private source and reviewed hash.
- Stop for another explicit authorization of the 22-record import.
- Execute one atomic initialization transaction.
- Return counts and redacted evidence only.
- Prove an identical second run is a no-op and conflicts fail closed.

### Gate 9.6 — Runtime verification and workflow compatibility

- Verify exactly 22 Merchant records and the expected status distribution without exposing rows.
- Verify UTF-8 preservation through private hash-based checks.
- Exercise ordinary redacted reads.
- Verify allowed workflow preconditions for `ONBOARDING` and `ACTIVE` merchants.
- Use controlled per-operation authorization for any real workflow mutation.

### Gate 9.7 — Complete regression and final handoff

- Run focused catalog, planner, readiness, migration, CLI, policy, workflow, and privacy tests.
- Run the complete non-live workspace regression.
- Run structural and whitespace validation.
- Record runtime evidence without private values.
- Stage, review, commit, push, and verify the final core Checkpoint 9 boundary.

## 7. Completion criteria

Checkpoint 9 is complete only when:

1. The exact private source validates as 22 unique UTF-8 Merchant records.
2. No real value enters Git, fixtures, documentation, archives, logs, prompts, or RAG.
3. Runtime migrations are exactly 1, 2, and 3 with no checksum or description conflicts.
4. Initialization is atomic, hash-bound, idempotent, and conflict-safe.
5. Runtime contains exactly 22 Merchants with the reviewed status distribution.
6. Redacted reads and workflow preconditions work against initialized runtime state.
7. Complete regression, handoff, commit, push, and clean-checkout verification pass.

All seven completion criteria were satisfied. The main implementation was committed and pushed as
`2ac90c0a57ac857da8d537b8aeeea7b04fc97cb9`, and a detached checkout of that remote commit was
clean and passed all 81 structural checks.

## 8. Future boundary

Checkpoint 10 remains an optional Phase 4B operational extension for alert claiming, retries, and
delivery channels. It is not required for the core Merchant Project Manager to be complete.

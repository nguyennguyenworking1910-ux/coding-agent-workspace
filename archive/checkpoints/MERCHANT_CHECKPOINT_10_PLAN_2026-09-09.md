# Merchant Project Manager — Checkpoint 10 Build Plan

**Date:** September 9, 2026
**Branch:** `feat/workspace-rag`
**Base commit:** `ef2ee1d695ca1f0e63472f881d95449cf1db2f02` (`Finalize Checkpoint 9 handoff`)
**Checkpoint:** 10 — Phase 4B Production Alert Delivery
**Status:** Complete; implementation commit `d4d29db5bd4e470bf5af49f640c55b00cd3157e4` pushed and verified

## 1. Goal

Checkpoint 10 is the final planned Merchant Project Manager checkpoint before normal use and
debugging. It productionizes the existing independent alert worker with lease-safe claiming,
bounded retries, fail-closed delivery channels, redacted operational health, and guarded runtime
rollout.

Checkpoint 10 extends the deterministic Checkpoint 8 calculator and the initialized Checkpoint 9
runtime. It does not rebuild deadline or blocker logic, change the private catalog, or authorize a
Merchant workflow mutation.

## 2. Verified baseline

The pushed Checkpoint 9 boundary is:

```text
main implementation 2ac90c0a57ac857da8d537b8aeeea7b04fc97cb9
final handoff       ef2ee1d695ca1f0e63472f881d95449cf1db2f02
```

Remote verification established:

- `origin/feat/workspace-rag` resolves to the final handoff commit;
- the final handoff commit has the main implementation commit as its parent;
- a detached checkout is clean and structural validation passes 81/81;
- the runtime has migrations 1–3, 4 templates, 64 template steps, and 68 dependencies;
- the private catalog has 22 `ONBOARDING` records and no real projects, contacts, identifiers, or
  alert deliveries;
- no private catalog row, credential, source file, backup, or environment file is in Git.

The runtime catalog and the Checkpoint 9 verification hashes remain immutable inputs to this
checkpoint. Alert-worker changes must not read or render private catalog source values.

## 3. Existing capability to preserve

The current worker already:

- runs independently of Claude Code;
- uses the isolated `merchant_alert` PostgreSQL role;
- calculates Checkpoint 8 alerts with the seven-day due-soon policy;
- enqueues stable `(deduplication_key, delivery_channel)` records;
- claims candidates with `FOR UPDATE SKIP LOCKED`;
- retries failed records after a configured delay;
- emits redacted INTERNAL JSON;
- writes only `merchant_ops.alert_deliveries`;
- leaves projects, steps, documents, approvals, procurement, identifiers, templates, catalog, and
  project events unchanged.

These contracts remain backward compatible unless a stricter fail-closed default is explicitly
documented and tested.

## 4. Production delivery contract

### 4.1 Delivery semantics

Database deduplication guarantees one durable delivery record for one calculated condition and
channel. A claim token and expiring lease prevent two active workers from owning the same attempt
and prevent a stale worker from marking a newer attempt sent or failed.

External notification delivery is **at least once**, not exactly once. A provider may accept a
message immediately before the worker loses the response or database connection. Retries therefore
reuse the same stable delivery identifier and provider idempotency metadata where supported, but
the system never makes a false exactly-once claim.

### 4.2 Claim and retry state

Forward-only migration 4 will add the minimum state required for safe ownership:

- explicit `CLAIMED` and `DEAD_LETTER` statuses;
- opaque claim token;
- lease expiry;
- next-attempt time;
- last-attempt time;
- optional redacted provider message identifier;
- constraints that reject partial or contradictory claim state;
- an index aligned with due claims and expired leases.

Claiming remains one bounded transaction using `FOR UPDATE SKIP LOCKED`. Attempt count increments
once per successful claim. Completion and failure updates require the exact claim token. Retry
delay uses bounded exponential backoff. The final failed attempt enters `DEAD_LETTER`; it is never
silently retried forever.

### 4.3 Channels

Supported channels will be:

- `INTERNAL`: structured UTF-8 JSON for a local log or downstream collector;
- `EMAIL`: authenticated SMTP with configured sender and fixed operator distribution list;
- `SLACK`: an explicitly configured Slack destination and credential.

EMAIL and SLACK remain unavailable unless every required setting validates. Secrets are accepted
only from the repository-root environment, stored with redacted representations, excluded from
payloads and errors, and never accepted as command-line arguments. Tests use fake transports and
fictitious recipients; non-live regression makes no network call.

Every channel receives the same allowlisted payload: delivery id, project id, optional step id,
alert type, business due date or condition fingerprint, attempt number, and stable deduplication
key. Merchant names, contacts, integration identifiers, document contents, credentials, private
paths, and arbitrary exception text are excluded.

### 4.4 Execution modes

The command line will require one explicit mode:

- `--dry-run`: calculate and print without a database write;
- `--enqueue-only`: calculate and enqueue without claiming or sending;
- `--deliver`: calculate, enqueue, claim, and deliver.

There is no implicit live delivery mode. The worker remains one-shot and is scheduled externally,
for example by Windows Task Scheduler. Each run has reviewed maximums for candidate projects,
claims, attempts, lease duration, network timeout, and retry delay. Invalid or conflicting values
fail before a database connection or network request.

### 4.5 Operational visibility

A read-only status command will expose only bounded aggregate metrics:

- counts by allowlisted channel and delivery status;
- claims ready now and active leases;
- expired leases;
- retryable failures and dead-letter count;
- oldest pending age and most recent successful delivery time;
- database, role, encoding, migration, and worker-configuration checks.

Status output never returns a Merchant row, project title, contact, destination, credential,
provider response body, or raw database error. A failed check returns stable reason codes and a
non-zero exit status.

## 5. Authority and mutation boundary

The worker is a non-agent runtime process. It does not use the Merchant Manager proposal/apply
handoff because its authority is restricted by the `merchant_alert` database role to workflow
reads and alert-delivery state.

The role must still be proven unable to mutate merchants, contacts, projects, steps, documents,
approvals, procurement, identifiers, templates, migrations, or project events. Channel delivery
does not grant Merchant workflow authority.

Migration 4 is a schema mutation and therefore requires:

1. a fresh verified PostgreSQL custom-format runtime backup;
2. a read-only migration plan bound to the exact database, owner role, file checksum, and backup;
3. explicit phrase `ALERT_LEASE_MIGRATION_4_AUTHORIZED`;
4. forward-only application by `merchant_owner`;
5. post-apply role, constraint, index, and runtime-state verification.

No environment flag, generic confirmation, `--force`, database override, or copied authorization
phrase can bypass the exact preflight.

## 6. Build gates

### Gate 10.0 — Repository consistency and final checkpoint plan

- Verify Checkpoint 9 main and finalization commits on the remote branch.
- Prove a clean detached checkout and 81/81 structural validation.
- Audit the existing worker, repository, schema, role, CLI, and tests.
- Lock the delivery, privacy, authority, rollout, and completion contracts in this plan.

### Gate 10.1 — Delivery configuration and safe payload contract

- Define immutable worker limits and strict environment parsing.
- Define the allowlisted channel-neutral payload.
- Replace raw exception persistence with stable redacted delivery reason codes.
- Reject missing, malformed, oversized, or conflicting configuration before I/O.
- Use fictitious fixtures only.

### Gate 10.2 — Lease-safe repository and migration 4

- Add the forward-only alert claim lease migration.
- Implement token-bound claim, sent, failed, dead-letter, and expired-lease behavior.
- Preserve stable deduplication and parameterized SQL.
- Prove stale tokens and concurrent claimers cannot update a newer attempt.
- Add read-only aggregate queue status queries.

### Gate 10.3 — INTERNAL, EMAIL, and SLACK adapters

- Preserve INTERNAL structured JSON delivery.
- Add EMAIL and SLACK adapters behind strict configuration factories.
- Apply bounded network timeouts and stable provider-facing delivery identifiers.
- Redact credentials, destinations, provider bodies, and transport exceptions.
- Test all network behavior with fake transports only.

### Gate 10.4 — Worker orchestration and operations

- Require an explicit execution mode and retain one-shot independence from Claude Code.
- Add bounded candidate, claim, lease, retry, and attempt policies.
- Add aggregate `--status` and fail-closed `--health-check` modes.
- Document Windows Task Scheduler commands, exit codes, logs, overlap behavior, and recovery.
- Add no scheduler task or external channel action automatically.

### Gate 10.5 — Complete non-live regression

- Run focused alert payload, repository, retry, adapter, CLI, privacy, and documentation tests.
- Run every non-integration repository test.
- Run structural and whitespace validation.
- Prove unit tests make no database or network connection.

### Gate 10.6 — Safe test-database lifecycle

- Verify the target is exactly `coding_agent_merchant_test` with the test role and expected host.
- Apply migration 4 to the test database under the existing guarded migration path.
- Seed only UUID-scoped fictitious records.
- Prove enqueue, concurrent claim exclusion, lease expiry, stale-token rejection, retry, success,
  dead-letter, status metrics, acknowledgement compatibility, and cleanup.
- Restore the test database to its pre-lifecycle business state in `finally`.

### Gate 10.7 — Runtime migration and read-only production verification

- Create and inspect a fresh runtime backup without exposing catalog values.
- Run the exact read-only migration-4 preflight.
- Stop for `ALERT_LEASE_MIGRATION_4_AUTHORIZED`.
- Apply only migration 4 and verify the alert role, constraints, index, and empty alert queue.
- Run INTERNAL dry-run and health checks only; do not send EMAIL or SLACK automatically.
- Prove the 22-record catalog, templates, and zero-project state are unchanged.

### Gate 10.8 — Final regression, operations handoff, and commit

- Run final focused, complete non-live, structural, privacy, and runtime verification.
- Record tested delivery semantics, configuration, scheduling, recovery, and debugging guidance.
- Stage only the reviewed Checkpoint 10 manifest.
- Commit, push, verify the remote branch, and prove a clean checkout.

## 7. Completion criteria

Checkpoint 10 is complete only when:

1. Claim ownership is token-bound, leased, and safe against stale completion.
2. Retries are bounded, backoff is deterministic, and exhausted alerts become dead letters.
3. INTERNAL, EMAIL, and SLACK adapters pass strict configuration and redaction contracts.
4. External delivery is documented honestly as at least once.
5. No CLI invocation sends live notifications without explicit `--deliver` mode.
6. Aggregate health and queue status are available without private rows or secrets.
7. The alert role cannot mutate Merchant workflow or catalog state.
8. Migration 4 passes guarded test and runtime rollout with a fresh backup.
9. The initialized 22-record catalog and four templates remain unchanged.
10. Complete regression, privacy scan, handoff, commit, push, and clean-checkout verification pass.

After these criteria pass, the planned Merchant Project Manager implementation is complete and the
repository is ready for ordinary use, observation, and issue-driven debugging. Live EMAIL or Slack
activation remains an operator configuration decision and is never performed automatically by the
checkpoint.

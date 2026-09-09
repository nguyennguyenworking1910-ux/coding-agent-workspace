# Merchant Project Manager — Checkpoint 10 Handoff

**Date:** September 9, 2026
**Branch:** `feat/workspace-rag`
**Base commit:** `ef2ee1d695ca1f0e63472f881d95449cf1db2f02` (`Finalize Checkpoint 9 handoff`)
**Implementation commit:** `d4d29db5bd4e470bf5af49f640c55b00cd3157e4` (`Complete Checkpoint 10 production alert delivery`)
**Checkpoint:** 10 — Phase 4B Production Alert Delivery
**Status:** Complete; implementation committed, pushed, and remotely verified

## 1. Outcome

Checkpoint 10 is the final planned Merchant Project Manager implementation checkpoint before
ordinary use, observation, and issue-driven debugging. It converts the independent alert worker
into a bounded operational process with token-bound leases, deterministic retries, dead-letter
handling, strict delivery adapters, redacted health reports, and a guarded runtime rollout.

The checkpoint does not change deadline or blocker calculation, create a real project, activate an
external channel, or weaken the Checkpoint 7 workflow authorization boundary.

## 2. Delivery semantics

Alert records remain unique by stable deduplication key and delivery channel. Claiming uses
`FOR UPDATE SKIP LOCKED`, increments the attempt count once, assigns a fresh opaque token, and sets
an expiring lease. A sent, failed, or dead-letter update requires the exact current claim token, so
a stale worker cannot complete a newer claim.

Retry delay uses bounded exponential backoff. Retryable failures return to the queue only after
`next_attempt_at`; a final failed attempt becomes `DEAD_LETTER`. External delivery is **at least
once**, not exactly once, because a provider may accept a message before a response or database
acknowledgement is lost.

## 3. Payload and channel boundary

Every adapter receives only the allowlisted delivery payload: delivery id, project id, optional
step id, alert type, due date or condition fingerprint, attempt number, and deduplication key.
Merchant names, contacts, document content, identifiers, credentials, destinations, provider
bodies, arbitrary exceptions, and private paths are excluded.

Supported channels are:

- `INTERNAL`: structured UTF-8 JSON for local collection;
- `EMAIL`: authenticated SMTP with mandatory TLS and a fixed configured distribution list;
- `SLACK`: a fixed Slack API endpoint, bot credential, and channel id.

EMAIL and Slack fail closed unless every required environment setting validates. Tests use fake
transports and fictitious destinations. No live external message was sent during this checkpoint.

## 4. Worker modes and limits

Exactly one mode is required:

- `--dry-run` calculates and prints without database writes;
- `--enqueue-only` calculates and enqueues without sending;
- `--deliver` calculates, enqueues, claims, and delivers;
- `--status` returns aggregate queue metrics;
- `--health-check` verifies database, role, migration, adapter, and limit readiness.

There is no implicit delivery mode. Candidate count, claim count, attempts, lease duration, retry
delay, and network timeout are bounded. Invalid values fail before repository construction or
network access. Successful operations return exit code 0, operational failures return 1, argument
errors return 2, and unhealthy runtime checks return 3.

## 5. Database and authority boundary

Migration 4, `add_alert_delivery_leases`, has SHA-256:

```text
5d305951e7970d982f3d839bc0bb1363d96beb16312445b07cdbde777109e110
```

It adds only claim token, lease expiry, retry timing, last-attempt timing, provider-message state,
related constraints, and the lease-aware claim index to `merchant_ops.alert_deliveries`. The
migration contains no Merchant, project, workflow, template, catalog, or project-event mutation.

The worker uses `merchant_alert`, which has workflow reads and alert-delivery state writes. It has
no authority to mutate merchants, contacts, projects, steps, documents, approvals, procurement,
identifiers, templates, migrations, or project events. Runtime schema application remains owned by
`merchant_owner`.

## 6. Test-database lifecycle

Gate 10.6 applied migration 4 only to `coding_agent_merchant_test`, then used UUID-scoped fictitious
records to prove:

- duplicate enqueue suppression;
- allowlisted INTERNAL payloads and acknowledgement compatibility;
- separate-connection concurrent claim exclusion;
- active-lease exclusion and expired-lease reclaim;
- claim-token rotation and stale-token rejection;
- retry delay, successful retry, explicit dead letter, and exhausted-attempt handling;
- aggregate queue status without business values;
- cleanup of every generated row in `finally`.

The lifecycle restored the test business tables to their initial empty state and preserved four
templates, 64 template steps, 68 template dependencies, and migrations 1–4.

## 7. Guarded runtime rollout

Gate 10.7 created a fresh PostgreSQL custom-format backup and verified its restore listing. The
reviewed evidence was:

```text
backup_sha256 7745c7855d6fb0549c1e81c58af5e67a9c7da4289af0c8980ffff784045068be
plan_sha256   d230a81f7af0fa54efd10a02a700ccc89d07ed7dea20d62845055b4d032bfd9b
```

The exact read-only plan showed migrations 1–3 applied and only migration 4 pending. After explicit
`ALERT_LEASE_MIGRATION_4_AUTHORIZED` authorization, `merchant_owner` applied migration 4 through the
forward-only runner and advisory lock. Post-apply verification proved:

- migrations 1, 2, 3, and 4 have their exact reviewed checksums and none are pending;
- the runtime database, UTF-8 encoding, `merchant_app`, and `merchant_alert` roles are exact;
- all five lease columns and five reviewed constraints exist;
- the lease-aware claim index is exact;
- the alert role has the required alert-table privileges;
- the runtime alert queue remains empty;
- the pre-migration recovery backup remains bound and retained.

## 8. Preserved private runtime state

Runtime verification after migration 4 returned only counts and hashes:

| Component | Verified state |
|---|---:|
| Merchant records | 22 |
| `ONBOARDING` | 22 |
| `ACTIVE` | 0 |
| Catalog initialization events | 22 |
| Workflow templates | 4 |
| Template steps | 64 |
| Template dependencies | 68 |
| Contacts | 0 |
| Projects | 0 |
| Alert deliveries | 0 |

The immutable catalog bindings remain:

```text
source_sha256  c0c48cf58a0cd55a25a78abc35922114a36c42b92d29d6c1c58d97898733a501
catalog_sha256 d657f977a384b4747882017ef77163bf4e268a38f6092dfbdd8dfc4ebb609354
```

No catalog row, credential, environment file, private source, or database backup is included in
the repository or this handoff.

## 9. Operations and recovery

`MERCHANT_ALERT_OPERATIONS.md` is the operator runbook for explicit modes, environment settings,
exit codes, safe logs, Windows Task Scheduler with `IgnoreNew`, health checks, retry handling,
dead-letter review, and backup-based recovery. The worker never creates a scheduled task or applies
a migration itself.

INTERNAL is the safe initial operational channel. EMAIL or Slack activation requires a separate
operator decision, valid credentials and destinations, a successful `--health-check`, and an
intentional `--deliver` command. Secrets remain environment-only and never appear in command-line
arguments.

## 10. Verification evidence

Accepted gate markers include:

```text
CHECKPOINT_10_GATE_1_DELIVERY_CONFIGURATION_AND_PAYLOAD_PASSED
CHECKPOINT_10_GATE_4_WORKER_OPERATIONS_PASSED
CHECKPOINT_10_GATE_5_COMPLETE_NON_LIVE_REGRESSION_PASSED
CHECKPOINT_10_GATE_6_SAFE_TEST_DATABASE_DELIVERY_LIFECYCLE_PASSED
CHECKPOINT_10_GATE_7A_RUNTIME_BACKUP_AND_PREFLIGHT_PASSED
CHECKPOINT_10_GATE_7B_RUNTIME_MIGRATION_4_APPLY_AND_VERIFY_PASSED
```

Gate 10.7B passed 68 immediate pre-apply contract tests, the hash-bound runtime preflight, the
forward migration, the alert-role health proof, the post-migration private-state proof, and all 80
structural checks.

Gate 10.8 then passed 219 focused tests, 1,810 complete non-live tests, 120 subtests, all 80
working-tree structural checks, the final read-only runtime proof, the INTERNAL health check and
dry run, and the private-data isolation scan. The exact 31-file manifest was staged and committed
as `d4d29db5bd4e470bf5af49f640c55b00cd3157e4`, then pushed to
`origin/feat/workspace-rag`.

A detached clean checkout of the pushed implementation commit passed all 81 structural checks and
had no working-tree changes. The commit has the final Checkpoint 9 handoff as its parent and
contains exactly the reviewed 31 files.

## 11. Files in the implementation boundary

The reviewed Checkpoint 10 implementation boundary contains 31 files: 13 production/configuration
files, 5 documentation files, and 13 test files. The exact list is enforced by the final staging
gate rather than duplicated as an unaudited wildcard.

Private catalog JSON, spreadsheets, environment files, backup files, database dumps, ZIP delivery
artifacts, caches, and compiled Python files are excluded from staging.

## 12. Ready-for-use boundary

The planned Merchant Project Manager is now ready
for ordinary use, observation, and issue-driven debugging. This completion does not authorize a
real Merchant workflow mutation or automatic external delivery.

For initial operation:

1. run `--health-check` with `INTERNAL`;
2. run `--dry-run` and inspect the redacted result;
3. use `--enqueue-only` only when durable queue creation is intended;
4. use `--deliver` only as an explicit operator action;
5. configure scheduling or an external channel separately after observing local behavior.

Any future bug fix should reproduce the issue with a focused regression, preserve private-data
isolation, and use the test database before touching runtime state.

## 13. Commit and remote boundary

The Checkpoint 10 implementation was committed as:

```text
d4d29db5bd4e470bf5af49f640c55b00cd3157e4
Complete Checkpoint 10 production alert delivery
```

Its parent is the exact Checkpoint 9 final handoff commit
`ef2ee1d695ca1f0e63472f881d95449cf1db2f02`. The commit changes exactly the reviewed 31 files.
`git show --check` passed, and `origin/feat/workspace-rag` resolved to the same implementation
commit.

A detached checkout of the pushed commit was clean and passed all 81 structural checks. This
documentation-only finalization records that immutable implementation boundary without changing
worker behavior, database state, delivery configuration, or private catalog data.

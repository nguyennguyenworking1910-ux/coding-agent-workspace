# Merchant Alert Worker Operations

The Merchant alert worker is a standalone, one-shot process. It calculates the deterministic
Checkpoint 8 alerts, writes only alert-delivery state, and exits. It is not a Claude Code agent,
does not perform Merchant workflow mutations, and does not create or manage a scheduler.

Migration 4 must be authorized and applied before `--enqueue-only`, `--deliver`, `--status`, or a
successful `--health-check`. Checkpoint 10 rollout gates handle that migration separately. Merely
running the worker never applies a migration.

## 1. Required environment

Run from the repository root. The repository client loads missing settings from the root `.env`
without replacing already-set process variables. The alert role must resolve to `merchant_alert`
on `coding_agent_merchant`.

The reviewed defaults are:

| Setting | Default | Reviewed range |
|---|---:|---:|
| `MERCHANT_ALERT_PROJECT_LIMIT` | 100 | 1–500 |
| `MERCHANT_ALERT_CLAIM_LIMIT` | 25 | 1–100 |
| `MERCHANT_ALERT_MAX_ATTEMPTS` | 5 | 1–10 |
| `MERCHANT_ALERT_LEASE_SECONDS` | 120 | 30–900 |
| `MERCHANT_ALERT_RETRY_BASE_SECONDS` | 300 | 1–3,600 |
| `MERCHANT_ALERT_RETRY_MAX_SECONDS` | 21,600 | 1–86,400 |
| `MERCHANT_ALERT_NETWORK_TIMEOUT_SECONDS` | 10 | 1–60 |

The retry maximum cannot be below its base. The lease must exceed the network timeout by at least
five seconds. Invalid values fail before the worker opens a database connection or network
request. CLI numeric options override the corresponding environment values for one execution but
remain inside the same bounds.

EMAIL and SLACK configuration is read only from the root environment. Credentials and fixed
destinations are never command-line arguments. Leave those variables unset until that channel is
deliberately enabled and tested.

## 2. Explicit one-shot modes

Exactly one mode is required. There is no default delivery mode.

```powershell
$python = ".\.venv\Scripts\python.exe"

# Calculate and print allowlisted alerts. No database write or network call.
& $python -B .\.claude\workers\merchant_alert.py --dry-run

# Calculate and enqueue. Does not claim or send.
& $python -B .\.claude\workers\merchant_alert.py --enqueue-only

# Calculate, enqueue, claim, and deliver one bounded INTERNAL cycle.
& $python -B .\.claude\workers\merchant_alert.py --deliver --channel INTERNAL

# Read aggregate queue state only.
& $python -B .\.claude\workers\merchant_alert.py --status --channel INTERNAL

# Verify identity, role, read-only access, migration 4, privileges, and configuration.
& $python -B .\.claude\workers\merchant_alert.py --health-check --channel INTERNAL
```

Use repeated `--project-id <uuid>` options to limit dry-run, enqueue, or delivery to reviewed
projects. With no project identifiers, the worker reads at most the configured project limit plus
one sentinel row. It fails instead of silently truncating a larger project set. An optional
`--business-date YYYY-MM-DD` makes alert calculation reproducible. `--due-soon-days` accepts 0–365
and otherwise uses the documented seven-day default.

`--status` and `--health-check` reject project, business-date, and due-soon options. Their output is
aggregate and redacted: it contains no Merchant row, project title, contact, destination,
credential, provider response, raw exception, or private catalog value.

## 3. Exit codes and delivery semantics

| Exit code | Meaning |
|---:|---|
| 0 | Requested operation or health proof succeeded |
| 1 | Configuration, database, calculation, enqueue, claim, or delivery operation failed |
| 2 | Command-line syntax or required-mode error reported by `argparse` |
| 3 | `--health-check` completed and one or more readiness checks failed |

Delivery is **at least once**, not exactly once. A provider can accept a notification immediately
before the worker loses its response or database connection. Stable delivery identifiers reduce
duplicates where a provider supports idempotency.

Expired claims are eligible for a later worker to reclaim. Completion and failure updates require
the current opaque claim token, so a stale worker cannot finish a newer attempt. Retryable failures
use bounded exponential delay; the last attempt becomes `DEAD_LETTER` and is not retried forever.

## 4. Windows Task Scheduler

First run `--health-check`, `--dry-run`, and a supervised one-shot `--deliver --channel INTERNAL`.
Do not schedule EMAIL or SLACK until its fixed destination and credential have been reviewed with
the corresponding health check.

Create the task manually in Windows Task Scheduler with:

| Field | Value |
|---|---|
| Program/script | `C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace\.venv\Scripts\python.exe` |
| Arguments | `-B .claude\workers\merchant_alert.py --deliver --channel INTERNAL` |
| Start in | `C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace` |
| Multiple instances | Do not start a new instance (`IgnoreNew`) |

Use a dedicated local account with access only to this repository and the required environment.
Select a schedule appropriate for operations only after the one-shot checks pass. Do not embed a
password, SMTP credential, Slack token, destination, or private catalog path in task arguments.

The task must not overlap. `IgnoreNew` is the primary scheduler control; claim leases and tokens
are the database safety boundary if separate hosts accidentally overlap. A new run is independent
of Claude Code and does not depend on an earlier Python process.

For append-only local logs, point Task Scheduler at a reviewed PowerShell wrapper that runs the
exact command and redirects both streams to an access-controlled file. The worker already emits
one-line, allowlisted JSON and stable error codes. Do not add environment dumps, command tracing,
provider response bodies, or raw exceptions to the wrapper.

## 5. Monitoring and recovery

Use the two read-only operational commands:

```powershell
& $python -B .\.claude\workers\merchant_alert.py --health-check --channel INTERNAL
if ($LASTEXITCODE -ne 0) { throw "Merchant alert health check failed." }

& $python -B .\.claude\workers\merchant_alert.py --status --channel INTERNAL
if ($LASTEXITCODE -ne 0) { throw "Merchant alert status query failed." }
```

Monitor ready, active-claim, expired-claim, retryable-failure, and dead-letter counts. Investigate
repeated non-zero exits and any dead-letter increase.

Recovery sequence:

1. Disable the scheduled task and wait for any active process to exit.
2. Run `--health-check`; fix the named failed check without changing business tables.
3. Run `--status`; record only its redacted aggregate output.
4. For configuration or provider failures, correct the root environment and run one supervised
   cycle. Do not reset attempt counts or claim tokens manually.
5. Let an expired claim be reclaimed by a later bounded run. Never mark a stale claim sent.
6. For schema damage, keep the worker disabled and follow the reviewed PostgreSQL backup and
   recovery procedure in `MERCHANT_PROJECT_MANAGER.md`. Do not improvise a reverse migration.
7. Re-run health, dry-run, and INTERNAL delivery before re-enabling the schedule.

The worker may insert or update `merchant_ops.alert_deliveries` only. It cannot change merchants,
contacts, projects, steps, documents, approvals, procurement, identifiers, workflow templates,
migrations, or project events. Normal Merchant workflow changes still require their existing
proposal, confirmation, policy, and one-use authorization path.

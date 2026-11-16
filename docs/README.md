# Documentation

Current documentation for the workspace. Start with the repository [README](../README.md);
agents also load [`CLAUDE.md`](../CLAUDE.md) automatically. Historical checkpoint reports are in
[`archive/checkpoints/`](../archive/checkpoints/) and are never authoritative.

## Index

| Area | Document | What it owns |
|---|---|---|
| Architecture | [architecture/system-overview.md](architecture/system-overview.md) | Folder structure, ownership, dependency direction, naming, documentation placement, adding components |
| | [architecture/trusted-execution.md](architecture/trusted-execution.md) | Merchant Direct EXECUTE: authority sources, pending confirmations, preflight, claim/ledger transaction, receipts, result delivery, database isolation, teammate backend enforcement |
| Merchant | [merchant/project-lifecycle.md](merchant/project-lifecycle.md) | Confirmation-first Local MVP policy, workflow templates, Step/Project state machines and promotion, operations and confirmation phrases, activation, signed revision reuse, known findings |
| | [merchant/project-manager-design.md](merchant/project-manager-design.md) | Original domain design: schema, workflows, gates, CLI and agent contracts, activation commands (sections on proposal/apply are historical) |
| Operations | [operations/local-setup.md](operations/local-setup.md) | Python environment, `.env`, API keys, Google credentials |
| | [operations/database-and-migrations.md](operations/database-and-migrations.md) | Runtime vs test database, migrations 001–011, integrity checks, backup and recovery |
| | [operations/backup-restore.md](operations/backup-restore.md) | Backup inventory and verification status, naming, restore rules, retained local recovery artifacts |
| | [operations/live-acceptance.md](operations/live-acceptance.md) | User-driven live `/solve` acceptance on the test database |
| | [operations/merchant-alert-operations.md](operations/merchant-alert-operations.md) | One-shot alert worker modes, limits, health checks, recovery |
| | [operations/scheduler.md](operations/scheduler.md) | `/schedule-agent` and `python .claude/schedule.py`, timezone, credential troubleshooting |
| | [operations/bigquery.md](operations/bigquery.md) | BigQuery ADC setup, `.sql` templates, `bq_query.py`, safety caps |
| | [operations/rag.md](operations/rag.md) | Local RAG search, source filters, retrieved-content trust rules |
| Development | [development/testing.md](development/testing.md) | Test commands, PostgreSQL test rules, what to run after a change |
| | [development/decision-register.md](development/decision-register.md) | Current status of every owner decision, withdrawn policies, open decisions |
| | [development/checkpoint-history.md](development/checkpoint-history.md) | CP1–CP12H timeline, durable decisions and lessons, links to archived evidence |
| | [development/repository-cleanup-report.md](development/repository-cleanup-report.md) | The 2026-11-16 consolidation: what moved, what was removed, validation evidence |

## The eight specialists

The agent roster (`diagnostician`, `red-team`, `reviewer`, `coder`, `bug-fixer`,
`group-sales-manager`, `merchant-manager`, `scheduler`) is defined in `.claude/agents/*.md`,
registered in `.claude/agents.json`, and summarised in [`CLAUDE.md`](../CLAUDE.md). Those
definitions and the slash commands in `.claude/commands/` are load-bearing Markdown: the harness
finds them only there.

## Subject ownership

Each subject has one canonical home; other documents link to it instead of repeating it.

| Subject | Canonical document |
|---|---|
| `/solve` orchestration, envelope, roster, limits, teammate dispatch | `CLAUDE.md` (rules) and `.claude/commands/solve.md` (procedure) |
| Merchant manager responsibilities and CLI surface | `.claude/agents/merchant-manager.md` |
| Trusted handoff, confirmations, Execute-only, exactly-once, receipts | [trusted-execution.md](architecture/trusted-execution.md) |
| Read-only previews and confirmation phrases | [project-lifecycle.md §4](merchant/project-lifecycle.md#4-operations-and-their-confirmations) |
| Database isolation and operator attribution | [trusted-execution.md §5](architecture/trusted-execution.md#5-database-isolation-and-attribution) |
| Project lifecycle, revisions, approvals, signing, PR/PO/Payment Request, completion | [project-lifecycle.md](merchant/project-lifecycle.md) |
| Step state machine and promotion | [project-lifecycle.md §3](merchant/project-lifecycle.md#3-step-and-project-state-machines) |
| Merchant activation | [project-lifecycle.md §5](merchant/project-lifecycle.md#5-merchant-activation) |
| Signed revision reuse | [project-lifecycle.md §6](merchant/project-lifecycle.md#6-signed-revision-reuse-existing-document-media) |
| Migrations, recovery | [database-and-migrations.md](operations/database-and-migrations.md), [backup-restore.md](operations/backup-restore.md) |
| Testing and acceptance | [testing.md](development/testing.md), [live-acceptance.md](operations/live-acceptance.md) |
| Policy decisions | [decision-register.md](development/decision-register.md) |

## Adding documentation

1. Put it in the matching folder above (kebab-case filename).
2. Add a row to the index.
3. Link to the canonical document instead of duplicating a subject.

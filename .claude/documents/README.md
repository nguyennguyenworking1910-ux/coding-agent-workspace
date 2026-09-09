# Documentation

This folder contains all system documentation, setup guides, and reference materials.

## 📚 Documentation Index

### ⚠️ MANDATORY FOR ALL AGENTS
- **[AGENT_INITIALIZATION.md](./AGENT_INITIALIZATION.md)** — **REQUIRED reading before any agent executes a task**
  - Mandatory initialization checklist
  - What all agents must understand
  - Step-by-step initialization flow
  - Critical rules quick reference
  - Acknowledgment template

### Core System Documentation
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — System architecture and development guidelines
  - System overview and components
  - Directory structure and folder responsibilities
  - Subagent definitions vs. Python agents — which to add and why
  - Critical documentation storage rules (and the two `.md` exceptions)
  - Rules for building and adding files
  - Building checklists for new agents/tools/clients
  - System orchestration and team hierarchy
  - Best practices and naming conventions

- **[SETUP.md](./SETUP.md)** — Installing and configuring the Python side of the workspace
  - Python 3.10+ requirement
  - Virtual environment on Windows, and `pip install -e .`
  - `OPENAI_API_KEY` for the intent parser (which fails closed without it)
  - Google Cloud CLI and Application Default Credentials, per-API scopes
  - Google Calendar credential resolution order (token → OAuth app → service account → ADC)
  - Unit-test and system-test commands, and troubleshooting

### Feature Documentation
- **[SCHEDULE_CLI.md](./SCHEDULE_CLI.md)** — Scheduling, from a session or a shell
  - `/schedule-agent` usage (dispatches the `scheduler` subagent)
  - `python .claude/schedule.py "<request>"` usage and exit codes
  - The confirmation requirement for calendar writes
  - Timezone handling — everything is `Asia/Ho_Chi_Minh`
  - Credential troubleshooting, message by message

- **[BIGQUERY_INTEGRATION.md](./BIGQUERY_INTEGRATION.md)** — BigQuery data access guide
  - gcloud ADC setup and project selection
  - Environment variables
  - How to add a `.sql` query template (file drop, no code change)
  - Running templates from `python .claude/bq_query.py`
  - How an agent uses the `bigquery_tools` module
  - Safety caps (max bytes billed, row cap) and troubleshooting

- **[EXAMPLES_GUIDE.md](./EXAMPLES_GUIDE.md)** — Reference implementations and usage patterns

- **[RAG_INTEGRATION.md](./RAG_INTEGRATION.md)** — Local workspace knowledge retrieval
  - Dependency boundary: agent → tool → client → RAG API
  - Searching project documents and Claude history
  - Source filters and CLI usage
  - Retrieved-content trust and prompt-injection rules
  - Runtime configuration and verification

- **[MERCHANT_PROJECT_MANAGER.md](./MERCHANT_PROJECT_MANAGER.md)** — Phase 4 Merchant Project Manager architecture
  - Authoritative design contract for merchant and project state management
  - PostgreSQL schema design (merchants, projects, workflows, documents, procurement)
  - Three project types with four workflow variants (Media Top-Up New/Existing, Opening New Cinema, Integration New Merchant)
  - Document review and approval gates, UAT and Production separation, integration identifiers
  - Agent response contracts, CLI boundaries, transaction and concurrency model
  - Testing strategy, migration strategy, and implementation checkpoints

- **[MERCHANT_CHECKPOINT_5_HANDOFF_2026-09-05.md](./MERCHANT_CHECKPOINT_5_HANDOFF_2026-09-05.md)** — Checkpoint 5 implementation handoff
  - Completed read/write CLI, proposal binding, redaction, and repository adapters
  - Migration 3 checksum, test-database state, and least-privilege proof
  - Regression evidence, runtime boundary, and Checkpoint 6 continuation plan

- **[MERCHANT_CHECKPOINT_6_HANDOFF_2026-09-06.md](./MERCHANT_CHECKPOINT_6_HANDOFF_2026-09-06.md)** — Checkpoint 6 implementation handoff
  - Registered `merchant-manager` teammate and `/solve` routing boundary
  - Credential-safe runtime adapter, proposal-only writes, and authority denial
  - Agent Team result-delivery contract and Checkpoint 7 continuation plan

- **[MERCHANT_CHECKPOINT_7_HANDOFF_2026-09-07.md](./MERCHANT_CHECKPOINT_7_HANDOFF_2026-09-07.md)** — Checkpoint 7 implementation handoff
  - Merchant read, proposal, and confirmed-apply intent routing
  - Exact redacted confirmation and single-dispatch policy enforcement
  - Opaque one-use runtime authorization, persisted session bridge, and Checkpoint 8 plan

- **[MERCHANT_CHECKPOINT_8_PLAN_2026-09-07.md](./MERCHANT_CHECKPOINT_8_PLAN_2026-09-07.md)** — Checkpoint 8 baseline and build plan
  - Reconciles the existing checker with the authoritative Phase 4 alert contract
  - Defines remaining deadline, blocker, filter, CLI, and verification gates
  - Preserves read-only calculation and separates future alert delivery

- **[MERCHANT_CHECKPOINT_8_HANDOFF_2026-09-07.md](./MERCHANT_CHECKPOINT_8_HANDOFF_2026-09-07.md)** — Checkpoint 8 implementation handoff
  - Deterministic deadline, blocker, and missing-gate calculation
  - Bounded global alert reads with CLI filters and legacy compatibility
  - Complete non-live and cleanup-safe test-database verification evidence

- **[MERCHANT_CHECKPOINT_9_PLAN_2026-09-07.md](./MERCHANT_CHECKPOINT_9_PLAN_2026-09-07.md)** — Checkpoint 9 private runtime initialization plan
  - Finalizes the Checkpoint 8 commit boundary
  - Defines private catalog isolation, runtime readiness, and authorization gates
  - Keeps all real Merchant values outside Git, fixtures, logs, archives, and RAG

- **[MERCHANT_CHECKPOINT_9_HANDOFF_2026-09-08.md](./MERCHANT_CHECKPOINT_9_HANDOFF_2026-09-08.md)** — Checkpoint 9 final core implementation handoff
  - Records authorized migrations, templates, and atomic private catalog initialization
  - Verifies the 22-record runtime through hashes and redacted counts only
  - Preserves per-operation authority for every future real workflow mutation

- **[MERCHANT_CHECKPOINT_10_PLAN_2026-09-09.md](./MERCHANT_CHECKPOINT_10_PLAN_2026-09-09.md)** — Checkpoint 10 production alert-delivery plan
  - Extends the existing independent worker with lease-safe claim ownership and bounded retries
  - Defines fail-closed INTERNAL, EMAIL, and Slack delivery contracts
  - Guards migration 4, operational health, privacy, runtime rollout, and final completion

- **[MERCHANT_CHECKPOINT_10_HANDOFF_2026-09-09.md](./MERCHANT_CHECKPOINT_10_HANDOFF_2026-09-09.md)** — Final Merchant implementation handoff
  - Records the lease-safe worker, adapters, runtime migration, and verification evidence
  - Preserves the private 22-record catalog and four standard workflow templates
  - Defines the boundary for ordinary use, observation, and issue-driven debugging

- **[MERCHANT_ALERT_OPERATIONS.md](./MERCHANT_ALERT_OPERATIONS.md)** — One-shot alert-worker operations
  - Explicit dry-run, enqueue, delivery, status, and health-check commands
  - Reviewed limits, exit codes, redacted logging, and recovery procedure
  - Safe Windows Task Scheduler configuration without an in-process scheduler

---

## 🧭 Where things live

Documentation is not the only markdown in this system. Two other locations are **executable
configuration**, and the harness only finds them there:

| Markdown | Location | What it is |
|---|---|---|
| Documentation | `.claude/documents/` | What you are reading |
| Subagent definitions | `.claude/agents/*.md` | The eight specialists |
| Slash commands | `.claude/commands/*.md` | `/solve`, `/schedule-agent` |

Moving a subagent or command into this folder silently stops it from existing. See the
Documentation Rules section of [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## 📖 How to Use This Documentation

### For Users
Start with **SCHEDULE_CLI.md** to understand how to use the schedule agent, and the root
[README.md](../../README.md) for the subagent team and `/solve`.

### For Developers Adding Features
1. Read **[ARCHITECTURE.md](./ARCHITECTURE.md)** first
2. Follow the appropriate checklist (adding agent/tool/client)
3. Refer to **SETUP.md** if integrating external services
4. Run `python .claude/system_test.py` to verify structure and conventions
5. Update documentation here as you add features

### For Agents (MANDATORY)
**⚠️ IMPORTANT: All agents MUST follow this sequence BEFORE executing any task:**

1. **[AGENT_INITIALIZATION.md](./AGENT_INITIALIZATION.md)** — Read this FIRST (initialization checklist)
2. **[ARCHITECTURE.md](./ARCHITECTURE.md)** — Understand system design and critical rules
3. **Acknowledge** completion of initialization checklist
4. Execute assigned task

**Agents that must do this:**
- The `/solve` team leader (before planning or dispatching)
- Every subagent in `.claude/agents/` (before executing) — the requirement is written into
  each definition
- The standalone Scheduler (before scheduling)
- Any new agents (before first execution)

See **AGENT_INITIALIZATION.md** for the complete initialization flow and acknowledgment template.

---

## 📝 Adding New Documentation

When creating new documentation:
1. **Save files in this folder** (`.claude/documents/`)
2. **Update this README.md** with a link and brief description
3. **Use clear headings** and organize by feature/domain
4. **Include examples** where applicable
5. **Keep it current** as features change

---

**Last Updated:** September 9, 2026

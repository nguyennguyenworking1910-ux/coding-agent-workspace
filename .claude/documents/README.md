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
---

## 🧭 Where things live

Documentation is not the only markdown in this system. Two other locations are **executable
configuration**, and the harness only finds them there:

| Markdown | Location | What it is |
|---|---|---|
| Documentation | `.claude/documents/` | What you are reading |
| Subagent definitions | `.claude/agents/*.md` | The seven specialists |
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

**Last Updated:** August 13, 2026

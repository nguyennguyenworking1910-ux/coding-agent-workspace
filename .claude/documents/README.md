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
  - Critical documentation storage rules
  - Rules for building and adding files
  - Building checklists for new agents/tools/clients
  - System orchestration and team hierarchy
  - Best practices and naming conventions

- **[SETUP.md](./SETUP.md)** — Credential setup and configuration guide for Google Calendar integration
  - OAuth Desktop App setup
  - Service Account configuration
  - gcloud CLI (Application Default Credentials) setup
  - Troubleshooting and credential resolution order

### Feature Documentation
- **[SCHEDULE_CLI.md](./SCHEDULE_CLI.md)** — Schedule agent usage guide
  - Quick start guide
  - Schedule task examples (English & Vietnamese)
  - Time specification formats
  - Architecture overview
  - Troubleshooting

---

## 📖 How to Use This Documentation

### For Users
Start with **SCHEDULE_CLI.md** to understand how to use the schedule agent.

### For Developers Adding Features
1. Read **[ARCHITECTURE.md](./ARCHITECTURE.md)** first
2. Follow the appropriate checklist (adding agent/tool/client)
3. Refer to **SETUP.md** if integrating external services
4. Update documentation here as you add features

### For Agents (MANDATORY)
**⚠️ IMPORTANT: All agents MUST follow this sequence BEFORE executing any task:**

1. **[AGENT_INITIALIZATION.md](./AGENT_INITIALIZATION.md)** — Read this FIRST (initialization checklist)
2. **[ARCHITECTURE.md](./ARCHITECTURE.md)** — Understand system design and critical rules
3. **Acknowledge** completion of initialization checklist
4. Execute assigned task

**Agents that must do this:**
- Team Leader (before orchestrating)
- Scheduler agent (before scheduling)
- All specialized agents (before executing)
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

**Last Updated:** August 7, 2026

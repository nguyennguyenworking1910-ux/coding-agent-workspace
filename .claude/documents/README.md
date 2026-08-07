# Documentation

This folder contains all system documentation, setup guides, and reference materials.

## 📚 Documentation Index

### Core System Documentation
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

### Architecture & Guidelines
- **[../ARCHITECTURE.md](../ARCHITECTURE.md)** — System architecture and development guidelines (project root)
  - System overview and components
  - Directory structure and folder responsibilities
  - Rules for building and adding files
  - Building checklists for new agents/tools/clients
  - System orchestration and team hierarchy
  - Best practices and naming conventions

---

## 📖 How to Use This Documentation

### For Users
Start with **SCHEDULE_CLI.md** to understand how to use the schedule agent.

### For Developers Adding Features
1. Read **[../ARCHITECTURE.md](../ARCHITECTURE.md)** first
2. Follow the appropriate checklist (adding agent/tool/client)
3. Refer to **SETUP.md** if integrating external services
4. Update documentation here as you add features

### For Agents
The Team Leader and all specialized agents should read:
1. **[../ARCHITECTURE.md](../ARCHITECTURE.md)** before spawning new agents or modifying the system
2. Relevant documentation (SETUP.md, SCHEDULE_CLI.md) for their domain

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

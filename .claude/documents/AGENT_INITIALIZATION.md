# Agent Initialization Checklist

**This document is REQUIRED reading for all agents before executing any task.**

---

## ⚠️ MANDATORY STEP 1: Read ARCHITECTURE.md

Before an agent (Team Leader, Scheduler, or any specialist) executes ANY task, it MUST:

1. ✅ **Read** `.claude/documents/ARCHITECTURE.md` completely
2. ✅ **Understand** the system structure, components, and responsibilities
3. ✅ **Acknowledge** understanding of the critical rules
4. ✅ **Confirm** readiness to proceed with the task

This is **NON-NEGOTIABLE** and applies to:
- Team Leader agent
- Scheduler agent
- All specialized agents (Bug Fixer, Reviewer, Diagnostician, etc.)
- Any new agents added to the system

---

## What Agents Must Understand (from ARCHITECTURE.md)

### 1. System Overview
- Multi-agent orchestration system
- Role of Team Leader (coordinator)
- Role of specialized agents
- How tools, clients, and system components interact

### 2. Folder Structure & Ownership
- `agents/` — Agent implementations ONLY
- `tools/` — Reusable tool definitions
- `clients/` — External API integrations
- `system/` — System utilities
- `commands/` — Slash command definitions
- `documents/` — ALL markdown documentation
- `examples/` — Reference implementations

### 3. Critical Rules

#### 🚨 Documentation Rule
**ALL markdown files (.md) MUST be stored in `.claude/documents/`**

This includes:
- Feature guides
- Setup documentation
- Architecture documentation
- User guides
- Troubleshooting guides

❌ NEVER create `.md` files in:
- Project root (except references)
- Agent folders
- Tool folders
- Client folders

#### 🚨 Folder Structure Rule
**Each file must be in the correct folder**
- Code goes in agents/, tools/, or clients/
- Docs go in documents/
- No exceptions

#### 🚨 Dependencies Rule
**One-way dependency direction only**
- Agents → Tools → Clients
- NEVER: Clients → Tools or Tools → Agents

#### 🚨 Registration Rule
**All new agents and tools must be registered in `agents.json`**
- Single source of truth for system structure
- Update before any agent uses the new component

### 4. Best Practices
- Keep concerns separated
- Don't duplicate functionality
- Handle errors gracefully
- Test locally before system-wide use
- Document complex features

### 5. Building Rules
When adding new agents/tools/clients:
1. Create in correct folder
2. Register in `agents.json`
3. Document (in `.claude/documents/`)
4. Update examples if complex
5. Commit with proper message

---

## Agent Initialization Flow

```
1. Agent Startup
   ↓
2. ⚠️ REQUIRED: Read ARCHITECTURE.md
   ↓
3. Acknowledge Understanding
   ↓
4. Understand System Architecture
   ├─ Folder structure
   ├─ Component responsibilities
   └─ Critical rules
   ↓
5. Check Initialization Checklist
   ├─ ✅ Read ARCHITECTURE.md
   ├─ ✅ Understand system structure
   ├─ ✅ Know folder responsibilities
   ├─ ✅ Understand documentation rules
   └─ ✅ Ready to execute tasks
   ↓
6. Execute Assigned Task
```

---

## Initialization Checklist for Agents

Every agent MUST complete this before proceeding:

```
Checklist for [Agent Name]:
- [ ] Read ARCHITECTURE.md completely
- [ ] Understand system structure (agents, tools, clients, system)
- [ ] Know folder responsibilities and ownership
- [ ] CRITICAL: Understand documentation rule (all .md → .claude/documents/)
- [ ] Understand dependency direction (Agents → Tools → Clients)
- [ ] Know registration requirement (agents.json)
- [ ] Understand naming conventions
- [ ] Ready to execute task while following these rules
```

---

## Critical Rules (Quick Reference)

| Rule | Requirement | Violation |
|------|-------------|-----------|
| **Documentation** | ALL .md files in `.claude/documents/` | Store .md elsewhere = ERROR |
| **Folder Structure** | Code in correct folder | Wrong folder = ERROR |
| **Dependencies** | Agents→Tools→Clients | Reverse dependency = ERROR |
| **Registration** | New agents/tools in `agents.json` | Not registered = ERROR |
| **Naming** | Follow conventions | Non-standard names = WARNING |

---

## Before Creating New Agents

✅ **REQUIRED** - Complete this checklist:

1. ✅ Read ARCHITECTURE.md
2. ✅ Check if similar agent exists (don't duplicate)
3. ✅ Determine correct folder location
4. ✅ Create agent file
5. ✅ Register in `agents.json` with proper fields
6. ✅ Add to Team Leader's `canSpawn` list (if spawnable)
7. ✅ Document in `.claude/documents/` (create {AGENT}_GUIDE.md if complex)
8. ✅ Include this initialization requirement in agent's docstring
9. ✅ Test locally
10. ✅ Commit with proper message

---

## FAQ

**Q: Do I need to read ARCHITECTURE.md every time I execute?**  
A: No. Once per initialization. But reference it frequently.

**Q: What if I'm creating a new agent?**  
A: Absolutely read ARCHITECTURE.md first. It will guide where to put code and what to register.

**Q: Can I put .md files anywhere else?**  
A: NO. All .md files MUST go in `.claude/documents/`. This is non-negotiable.

**Q: What if I forgot to register in agents.json?**  
A: Go back and register immediately. The Team Leader won't spawn agents not in agents.json.

**Q: Can I import from agents into tools?**  
A: NO. One-way only: Agents → Tools → Clients. Never backwards.

---

## Agent Acknowledgment Template

When an agent confirms it has read ARCHITECTURE.md, it should state:

```
✅ [Agent Name] Architecture Check - COMPLETE

I have read ARCHITECTURE.md and understand:
✓ System architecture with 6 core components
✓ Folder structure: agents/, tools/, clients/, system/, commands/, documents/, examples/
✓ CRITICAL: All .md files must go in .claude/documents/
✓ Dependencies: One-way only (Agents → Tools → Clients)
✓ Registration: New agents/tools go in agents.json
✓ Naming conventions and best practices
✓ Building rules for new components

I am ready to execute my assigned tasks while following these guidelines.
```

---

**Last Updated:** August 7, 2026  
**Status:** MANDATORY for all agents  
**Effective:** Immediately (all new agents must follow)

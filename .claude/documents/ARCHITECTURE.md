# System Architecture & Development Guide

**Last Updated:** September 6, 2026
**Status:** Active System  
**Target Audience:** Team Leader, All Agent Members, Future Developers

---

## Overview

This is a **multi-agent workspace built on Claude Code** where:
- The **Team Leader** is the `/solve` command — it plans task allocation and dispatches
  specialized subagents from the main session
- **Specialized subagents** (`.claude/agents/*.md`) handle specific domains (code review,
  security, bug fixing, implementation, diagnostics, sales data, Merchant operations,
  scheduling)
- **Tools** provide capabilities to agents — either harness tools (`Read`, `Bash`, MCP
  integrations), registered CLI adapters, or Python tools under `agents/tools/`
- **Clients** handle external integrations (Google Calendar, BigQuery, PostgreSQL, etc.)
- **System** holds the schemas shared across the Python layer

Everything runs inside a Claude Code session, with one deliberate exception: the Scheduler
also has a Python implementation so it can run from a plain shell or cron.

The system prioritizes **clean separation of concerns**, **clear ownership**, and **scalable agent addition**.

---

## Directory Structure & Responsibilities

### `.claude/` — System Core
Root configuration and orchestration for all agents and tools.

```
.claude/
├── agents.json              [MASTER CONFIG] Human-readable index of the roster
├── settings.json            [SETTINGS] Claude Code harness configuration
├── settings.local.json      [LOCAL SETTINGS] User-specific overrides, not committed
├── schedule.py              [ENTRY POINT] Standalone scheduler (runs outside a session)
├── system_test.py           [CHECKS] Structure and convention validation
│
├── documents/               [DOCUMENTATION FOLDER]
│   ├── README.md            Index of all documentation
│   ├── ARCHITECTURE.md      This file
│   ├── AGENT_INITIALIZATION.md  Mandatory pre-execution checklist
│   ├── SETUP.md             Python environment, API keys & credential setup
│   ├── SCHEDULE_CLI.md      Scheduling usage, confirmation rules & troubleshooting
│   ├── BIGQUERY_INTEGRATION.md  BigQuery data access guide
│   └── EXAMPLES_GUIDE.md    Reference implementations and usage patterns
│
├── agents/                  [AGENT DEFINITIONS & IMPLEMENTATIONS]
│   ├── reviewer.md          ┐
│   ├── red-team.md          │ SUBAGENT DEFINITIONS. Markdown + YAML
│   ├── bug-fixer.md         │ frontmatter is the ONLY form Claude Code
│   ├── diagnostician.md     │ discovers and dispatches. These files are
│   ├── coder.md             │ the agents — there is no Python behind them.
│   ├── group-sales-manager.md │
│   ├── merchant-manager.md  │
│   ├── scheduler.md         ┘
│   │
│   ├── base_agent.py        Base class for the standalone Python scheduler
│   ├── system_init.py       Enforces the ARCHITECTURE.md reading requirement
│   ├── requirements.txt     Python dependencies
│   ├── team/
│   │   ├── scheduler.py     SchedulerAgent: Google Calendar REST implementation
│   │   └── .env.example     Environment variables template
│   │
│   └── tools/               Tool implementations and registered CLI adapters
│       ├── base_tool.py     Tool base class and registry
│       ├── merchant/        Merchant workflow tools and JSON CLI
│       │   └── agent_cli.py Credential-safe operational agent adapter
│       └── scheduler/       Calendar helpers (availability, event creation)
│
├── clients/                 [EXTERNAL INTEGRATIONS]
│   ├── __init__.py          Package initialization
│   ├── config.py            Credential resolution & configuration
│   ├── SETUP.md             Credential setup instructions
│   ├── calendar_client.py   Google Calendar API wrapper
│   └── .env.example         Environment variables template
│
├── commands/                [SLASH COMMANDS FOR USERS]
│   ├── solve.md             /solve — team leader: plans and dispatches subagents
│   └── schedule-agent.md    /schedule-agent — dispatches the scheduler subagent
│
├── system/                  [SHARED SCHEMAS]
│   └── schemas.py           TaskResult, used by the Python scheduler path
│
├── examples/                [USAGE EXAMPLES & TEMPLATES]
│   └── (reference implementations for new agents/tools)
│
└── worktrees/               [GIT WORKTREES] Isolated branches for parallel work
```

### Two kinds of agent — know which you are adding

| | Subagent (`.md`) | Python agent (`.py`) |
|---|---|---|
| **Lives in** | `.claude/agents/{name}.md` | `.claude/agents/team/{name}.py` |
| **Runs** | Inside a Claude Code session | As a standalone process |
| **Dispatched by** | The harness, via `/solve` or by description match | A script you write |
| **Use when** | Always, by default | Only when it must run with no session (cron, CI) |

**Default to a subagent.** The only Python agent in this repo is the Scheduler, and it exists
solely because `.claude/schedule.py` needs to schedule from a plain shell. Python classes are
invisible to Claude Code — it does not load them, and it will never dispatch them.

---

## Folder Purposes (Detailed)

### `agents/` — Agent Definitions & Implementations
**Contains:** Subagent definitions (`*.md`) and the Python implementations that must run
outside a session. Not client logic, not shared schemas.

**Rules:**
- ✅ **Store subagent definitions** as `{name}.md` directly in `agents/` — the harness only
  looks here, and only at markdown with frontmatter
- ✅ **Each agent** gets its own file
- ✅ **Give each subagent only the tools it needs** — omit `Edit`/`Write` for read-only roles
- ✅ **Always grant `SendMessage` and `TaskUpdate`**, read-only roles included — a teammate
  reports to the lead through `SendMessage` and nothing else, so a definition without it
  finishes its work and silently delivers no result
- ✅ **Import from** `tools/` for tool definitions, `clients/` for external APIs
- ❌ **Don't store** credentials, configuration (use `clients/config.py`), or shared schemas
- ❌ **Don't hardcode** API keys, URLs, or environment-specific paths
- ❌ **Don't write a Python agent class** expecting Claude Code to dispatch it — it won't

**Subagent definition structure:**
```markdown
---
name: reviewer
description: Reviews code changes for correctness and maintainability. Use after a
  change is written and before it is committed. Read-only.
tools: Read, Grep, Glob, Bash, SendMessage, TaskUpdate
model: opus
---

Before doing anything else, read `.claude/documents/ARCHITECTURE.md`.

You are an expert code reviewer. Your role is to:
1. ...
```

The `description` is what the harness matches a request against, so write it as *when to use
this agent*, not just what it is.

**Python agent structure** (only for standalone execution):
```python
# agents/team/scheduler.py
from ..base_agent import BaseAgent, AgentConfig
from ...system.schemas import TaskResult
from ..tools.scheduler import SCHEDULER_TOOLS

class SchedulerAgent(BaseAgent):
    async def execute(self, task) -> TaskResult:
        # Agent logic here
        ...
```

---

### `tools/` — Tool Implementations
**Contains:** Reusable tool definitions that agents use.

**Rules:**
- ✅ **Store** tool classes, methods, and capabilities
- ✅ **One tool = one subdirectory** (e.g., `scheduler/`, `bigquery/`, `github/`)
- ✅ **Tools are agent-agnostic** — can be used by multiple agents
- ✅ **Import from** `clients/` for external integrations
- ❌ **Don't import from** `agents/` (avoid circular dependencies)
- ❌ **Don't hardcode** business logic (tools should be generic)

**Tool structure:**
```
tools/scheduler/
├── __init__.py
├── parser.py          # Parse natural language scheduling requests
├── conflict_detector.py  # Check calendar conflicts
└── time_suggester.py  # Find available slots
```

---

### `clients/` — External API Integrations
**Contains:** Wrappers for external services (Google Calendar, BigQuery, databases, etc.).

**Rules:**
- ✅ **Each service** gets one module (e.g., `calendar_client.py`, `bigquery_client.py`)
- ✅ **Handle credential resolution** (gcloud ADC, OAuth tokens, service accounts, environment variables)
- ✅ **Expose simple, clean APIs** for tools to use
- ✅ **Store setup instructions** in `SETUP.md`
- ❌ **Don't store** credentials directly (use `config.py` for resolution)
- ❌ **Don't duplicate** API wrappers (use the same client class)

**Client pattern:**
```python
# clients/calendar_client.py
class GoogleCalendarClient:
    def __init__(self):
        self.credentials = config.resolve_google_credentials()
        self.service = build('calendar', 'v3', credentials=self.credentials)
    
    def list_events(self, start, end):
        # Clean, single-purpose method
        pass
```

---

### `system/` — Shared Schemas & Infrastructure
**Contains:** Data structures shared across the Python layer. Currently just `TaskResult`.

**Rules:**
- ✅ **Store** shared schemas, system utilities, middleware, hooks
- ✅ **Keep it dependency-free** — this is imported by everything, so it must not import
  from `agents/`, `tools/`, or `clients/`
- ✅ **Prefer stdlib** (`dataclasses`) over adding a dependency for a data holder
- ❌ **Don't store** agent logic or business tools (use `agents/` or `tools/`)
- ❌ **Don't hardcode** agent-specific behavior

---

### `documents/` — Documentation & Guides
**Contains:** All system documentation, setup guides, and reference materials.

**Rules:**
- ✅ **Store** all `.md` documentation files here
- ✅ **One document = one file** (e.g., `SETUP.md`, `SCHEDULE_CLI.md`)
- ✅ **Maintain a README.md** that indexes all documentation
- ✅ **Keep updated** as features change
- ❌ **Don't store** code or configuration (use appropriate folders)

**Examples:**
- `SETUP.md` — Credential setup and initialization guides
- `SCHEDULE_CLI.md` — Feature-specific usage guides
- `{FEATURE}_GUIDE.md` — Documentation for new features

---

### `commands/` — Slash Command Definitions
**Contains:** `.md` files defining `/slash-commands` for users.

**Rules:**
- ✅ **One command = one `.md` file** (e.g., `schedule-agent.md`, `analyze-code.md`)
- ✅ **Define what the command does**, what tools it can use, and how to handle failures
- ✅ **Commands invoke agents or tools**, not arbitrary scripts
- ❌ **Don't execute** complex logic in commands (delegate to agents/tools)

**Command structure:**
```markdown
---
description: Brief description of what the command does
argument-hint: <example argument format>
allowed-tools: Tool1(*), Tool2(*), Skill(skill-name)
---

## What to do
1. Parse input
2. Call tools
3. Report results
```

---

### `examples/` — Reference Implementations
**Contains:** Template agents, example tools, and usage patterns.

**Rules:**
- ✅ **Store** working examples for future developers
- ✅ **Keep updated** as system evolves
- ✅ **Use as reference** before building new agents/tools
- ❌ **Not imported** by production agents (for learning only)

---

## Building & Adding Files

### Adding a New Agent

**Checklist:**

1. **Create the subagent definition**
   ```
   .claude/agents/{agent-name}.md
   ```
   - Use `kebab-case` for the filename and the `name:` field, and keep them identical
   - Required frontmatter: `name`, `description`, `tools`, `model`
   - Write `description` as *when to use this agent* — that is what dispatch matches on
   - Grant only the tools the role needs; omit `Edit`/`Write` for read-only agents
   - Always include `SendMessage` and `TaskUpdate` so the agent can report to the lead
   - Close the body with the result-delivery contract the other definitions carry
   - Open the body with the ARCHITECTURE.md reading requirement

2. **Register in `agents.json`**
   ```json
   {
     "id": "agent-name",
     "name": "Human Name",
     "description": "What it does",
     "enabled": true,
     "type": "category",
     "definition": ".claude/agents/agent-name.md",
     "tools": ["Read", "Grep", "Glob", "Bash"],
     "permissions": "read-only"
   }
   ```
   Keep `id` identical to the filename stem and the `name:` in frontmatter.

3. **Add it to the team leader**

   Add a row to the team members table in `.claude/commands/solve.md` and to the
   `dispatches` list under `commands` in `agents.json`. `/solve` cannot delegate to an
   agent it does not know about.

4. **Update `requirements.txt`** only if you also added Python that needs a dependency

5. **Verify**
   ```bash
   python .claude/system_test.py
   ```
   This checks the file exists, has valid frontmatter, and carries the ARCHITECTURE.md
   requirement.

6. **Write documentation** in `.claude/documents/` if the agent needs more explanation than
   its definition carries

---

### Adding a New Tool

**Checklist:**

1. **Create tool directory**
   ```
   .claude/agents/tools/{tool_name}/
   ├── __init__.py
   ├── core.py         (main tool class)
   └── helpers.py      (utilities)
   ```

2. **Implement tool class**
   ```python
   class MyTool:
       def method1(self, args): ...
       def method2(self, args): ...
   ```

3. **Register in `agents.json`**
   ```json
   {
     "id": "my_tool",
     "name": "My Tool",
     "type": "category",
     "enabled": true,
     "methods": [
       {"name": "method1", "description": "..."},
       {"name": "method2", "description": "..."}
     ]
   }
   ```

4. **Update agent declarations** that use this tool

---

### Adding a New Client Integration

**Checklist:**

1. **Create client module**
   ```
   .claude/clients/{service}_client.py
   ```

2. **Implement credential resolution**
   ```python
   from claude.clients import config
   
   class ServiceClient:
       def __init__(self):
           self.credentials = config.resolve_credentials('service_name')
   ```

3. **Document setup** in `.claude/documents/SETUP.md`
   - Installation steps
   - Credential paths
   - Troubleshooting

4. **Add variables to the unified environment template**
   ```
   .env.example
   ```
All local services read configuration from the repository root `.env`.
Do not create component-specific `.env` files.

---

## System Orchestration

### Execution Flow

```
User Input
    ↓
Claude Code Harness
    ↓
[/solve command definition]  ← .claude/commands/solve.md
    ↓
Team leader plans the request
    ↓
Dispatch subagents (Task tool)  ← .claude/agents/*.md
    ├─ independent work runs concurrently
    ├─ each subagent uses only its granted tools
    └─ writing agents edit the tree; they never commit
    ↓
Team leader synthesises and relays results
    ↓
Report to User + git diff --stat
```

Standalone path, for when there is no session:

```
Shell / cron
    ↓
python .claude/schedule.py "<request>"
    ↓
SchedulerAgent.execute()  ← .claude/agents/team/scheduler.py
    ├─ Calls tools in .claude/agents/tools/scheduler/
    │   └─ Tools use clients/calendar_client.py to reach the Calendar API
    └─ Returns TaskResult  ← .claude/system/schemas.py
```

### Team Hierarchy

```
Team Leader (/solve command — not an agent)
├── Diagnostician         (root cause from logs, metrics, traces)  read-only
├── Red Team              (security and edge cases)                read-only
├── Reviewer              (code validation)                        read-only
├── Coder                 (features and refactors)                 writes
├── Bug Fixer             (issue resolution)                       writes
├── Group Sales Manager   (sales data, allocation analysis)        read-only
└── Scheduler             (calendar & task management)             calendar only
```

- **The team leader is the `/solve` command**, not a subagent — the orchestrating role belongs
  to the main session, which is the only thing that can dispatch others
- **Members** execute their specialized tasks and report back
- **Subagent reports are not shown to the user** — the leader must relay what matters
- **A teammate's pane text does not reach the leader either** — the report arrives only as a
  `SendMessage` to `team-lead`, which is why every definition grants that tool and ends with the
  delivery contract. A completed task or an idle pane is a coordination signal, not a result
- **Never run two writing agents on overlapping paths concurrently**; give them disjoint file
  sets or sequence them
- **Specific members** have domain-specific tools (calendar, database, etc.)

---

## Naming Conventions

### Files & Directories
- ✅ `snake_case` for Python files: `scheduler.py`, `calendar_client.py`
- ✅ `kebab-case` for commands: `schedule-agent.md`
- ✅ `SCREAMING_SNAKE_CASE` for constants: `ADC_LOGIN_COMMAND`

### Code
- ✅ `CamelCase` for classes: `SchedulerAgent`, `GoogleCalendarClient`
- ✅ `snake_case` for functions/methods: `list_events()`, `create_event()`
- ✅ Descriptive names: `detect_conflicts()` not `check()`

### Configuration
- ✅ Use `agents.json` for agent/tool definitions (single source of truth)
- ✅ Use `config.py` for credential resolution logic
- ✅ Use `.env.example` as templates, never commit real `.env`

---

## Rules & Best Practices

### ✅ DO

1. **Keep concerns separated** — agents don't know about clients, tools don't contain business logic
2. **Register everything in `agents.json`** — single source of truth for system structure
3. **Use tools for reusable capabilities** — don't duplicate logic across agents
4. **Document as you build** — examples/ folder should stay current
5. **Import from the correct modules** — `agents/` from `tools/` and `clients/`, not vice versa
6. **Test agents locally** before registering them system-wide
7. **Handle errors gracefully** — agents should report problems clearly

### ❌ DON'T

1. **Hardcode credentials** — use `config.py` resolution
2. **Store credentials** in version control (use `.env.example` instead)
3. **Add files to wrong directories** — follow the folder structure strictly
4. **Duplicate clients** — reuse existing integrations
5. **Call agents directly** — use Team Leader to spawn them
6. **Import from agents/ into tools/** — maintain acyclic dependencies
7. **Commit .env files** or `settings.local.json` to git
8. **Store `.md` files outside `.claude/documents/`** — ALL markdown documentation must go in the documents folder

### 📝 Documentation Rules (CRITICAL)

**Every `.md` file created in this system MUST be stored in `.claude/documents/`**

This is a **non-negotiable rule** for system organization.

#### ✅ What Goes in `.claude/documents/`
- ✅ All feature guides (`{FEATURE}_GUIDE.md`)
- ✅ Setup and configuration docs (`SETUP.md`, `CONFIG_GUIDE.md`)
- ✅ Architecture and design docs (`ARCHITECTURE.md`)
- ✅ Integration guides (`{SERVICE}_INTEGRATION.md`)
- ✅ User guides and tutorials (`USER_GUIDE.md`, `TUTORIAL.md`)
- ✅ API documentation (`API_DOCS.md`)
- ✅ Troubleshooting guides (`TROUBLESHOOTING.md`)

#### ❌ What DOESN'T Go in `.claude/documents/`
- ❌ Code files (`.py`) — go in `agents/`, `tools/`, or `clients/`
- ❌ Configuration files (`.json`, `.yaml`) — stay in their respective folders
- ❌ Environment files (`.env`) — stay in client/agent folders
- ❌ **Subagent definitions** (`.claude/agents/*.md`) — stay in `agents/`
- ❌ Command definitions (in `commands/`) — stay in their folders
- ❌ Example files (in `examples/`) — stay in their folders

**The two `.md` exceptions are load-bearing, not preferences.** Subagent definitions and
slash commands are markdown, but they are *code the harness executes*, not documentation.
Claude Code discovers them only at `.claude/agents/` and `.claude/commands/` respectively —
move one into `documents/` and the agent or command silently stops existing. `system_test.py`
treats all three locations as valid.

#### 📋 Documentation Checklist

When creating **ANY** new markdown file:

1. ✅ **Save to `.claude/documents/{filename}.md`**
2. ✅ **Add entry to `.claude/documents/README.md`** with description
3. ✅ **Use clear, descriptive filename** (e.g., `GITHUB_INTEGRATION.md`, not `guide.md`)
4. ✅ **Add proper markdown headings** and organization
5. ✅ **Include examples** where applicable
6. ✅ **Cross-link** to related documentation
7. ✅ **Update this ARCHITECTURE.md** if adding a new category
8. ✅ **Commit with message** referencing the documentation addition

#### Example: Adding New Documentation

```bash
# Create new doc
echo "# GitHub Integration Guide" > .claude/documents/GITHUB_INTEGRATION.md
# Add content...

# Update index
# Edit .claude/documents/README.md to add:
# - **[GITHUB_INTEGRATION.md](./GITHUB_INTEGRATION.md)** — GitHub API integration guide

# Commit
git add .claude/documents/GITHUB_INTEGRATION.md .claude/documents/README.md
git commit -m "docs: Add GitHub integration guide"
```

#### Enforcement
- **Code review:** Reject PRs with `.md` files outside `.claude/documents/`, `.claude/agents/`,
  or `.claude/commands/`
- **Agents:** Will not process documentation requests without proper location
- **System check:** Run `python .claude/system_test.py` — Test 2 reports every `.md` file and
  flags any in an invalid location

---

## Adding Features: Step-by-Step Example

### Scenario: Add GitHub code review tool

**Step 1: Create the client**
```
.claude/clients/github_client.py
```

**Step 2: Create the tool**
```
.claude/agents/tools/github/
├── __init__.py
├── reviewer.py   (PR review logic)
└── fetcher.py    (Fetch PR details)
```

**Step 3: Create/Update the subagent**
```
.claude/agents/code-reviewer.md
(or grant the new tool to the existing reviewer.md)
```

**Step 4: Register in agents.json**
```json
{
  "id": "github",
  "name": "GitHub Tool",
  "methods": [
    {"name": "review_pr", "description": "Review a GitHub PR"}
  ]
}
```

**Step 5: Update the team leader**

Add the subagent to the team members table in `.claude/commands/solve.md` and to the
`dispatches` list in `agents.json`.

**Step 6: Document in documents/**
```
.claude/documents/GITHUB_INTEGRATION.md
```

**Step 7: Add setup guide**
```
.claude/documents/SETUP.md  (add GitHub setup section)
```

---

## Key Principles

| Principle | Meaning |
|-----------|---------|
| **Single Responsibility** | Each agent/tool has ONE clear purpose |
| **Dependency Inversion** | Agents depend on abstractions (tools), not implementations |
| **Open/Closed** | System is open for adding agents, closed for modification of core |
| **Composition** | Build complex behavior by composing simple tools |
| **Clear Ownership** | Each folder "owns" its domain, no overlaps |

---

## 🚨 CRITICAL: All `.md` Files Go in `.claude/documents/`

**THIS IS A NON-NEGOTIABLE RULE**

Every markdown file created in this system, without exception, must be stored in `.claude/documents/`.

| What | Where | Example |
|------|-------|---------|
| **Feature docs** | `.claude/documents/` | `GITHUB_INTEGRATION.md` |
| **Setup guides** | `.claude/documents/` | `DATABASE_SETUP.md` |
| **Architecture docs** | `.claude/documents/` | `ARCHITECTURE.md` |
| **User guides** | `.claude/documents/` | `USER_GUIDE.md` |
| **Troubleshooting** | `.claude/documents/` | `TROUBLESHOOTING.md` |

**NOT here:**
- ❌ Project root (except `README.md`)
- ❌ Agent folders — **except** subagent definitions, which MUST be `.claude/agents/*.md`
- ❌ Command folders — **except** slash commands, which MUST be `.claude/commands/*.md`
- ❌ Tool folders
- ❌ Client folders
- ❌ System folders

The two exceptions are the only ones. They exist because the harness loads those paths as
executable configuration; a subagent or command placed anywhere else does not run.

**When adding documentation:**
1. Create file in `.claude/documents/{name}.md`
2. Update `.claude/documents/README.md`
3. Commit with: `git add .claude/documents/` && `git commit -m "docs: Add {description}"`

---

## Before Building Anything

**All agents and developers MUST:**

1. ✅ Read this ARCHITECTURE.md (especially the Documentation Rules section)
2. ✅ Check existing agents/tools for similar functionality
3. ✅ Determine which folder the new code belongs in
4. ✅ Follow naming conventions
5. ✅ Update `agents.json` with proper registration
6. ✅ Document with examples if complex (in `.claude/documents/`)
7. ✅ Keep this file updated if architecture changes

---

## Questions for Team Members

**Ask yourself before building:**

- Does this logic belong in an agent, tool, or client?
- Is there already a similar agent/tool I can extend?
- Does this need to be registered in `agents.json`?
- Are my imports following the dependency direction?
- Have I documented this for future developers (in `.claude/documents/`)?
- Does this follow the system's naming conventions?
- **If creating documentation: Is it in `.claude/documents/`?** (CRITICAL)

---

**System Maintainer:** Team Leader Agent  
**Last Reviewed:** August 11, 2026  
**Next Review:** As needed when new agent/tool added

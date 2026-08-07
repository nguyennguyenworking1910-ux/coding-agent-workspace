# System Architecture & Development Guide

**Last Updated:** August 7, 2026  
**Status:** Active System  
**Target Audience:** Team Leader, All Agent Members, Future Developers

---

## Overview

This is a **multi-agent orchestration system** where:
- The **Team Leader** (coordinator agent) manages task allocation and spawns specialized agents
- **Specialized agents** handle specific domains (code analysis, bug fixing, scheduling, etc.)
- **Tools** provide capabilities to agents (thought, calendar access, database queries, etc.)
- **Clients** handle external integrations (Google Calendar, BigQuery, etc.)
- **System** defines how everything connects and operates

The system prioritizes **clean separation of concerns**, **clear ownership**, and **scalable agent addition**.

---

## Directory Structure & Responsibilities

### `.claude/` — System Core
Root configuration and orchestration for all agents and tools.

```
.claude/
├── agents.json              [MASTER CONFIG] Defines all agents, tools, permissions
├── settings.json            [SETTINGS] Claude Code harness configuration
├── settings.local.json      [LOCAL SETTINGS] User-specific overrides
├── ARCHITECTURE.md          [THIS FILE] System design & guidelines
├── SCHEDULE_CLI.md          [DOCUMENTATION] Schedule agent usage guide
│
├── agents/                  [AGENT IMPLEMENTATIONS]
│   ├── __init__.py          Package initialization
│   ├── requirements.txt     Python dependencies for all agents
│   ├── team/                Team member agents (coordinators, specialists)
│   │   ├── scheduler.py     Scheduler agent: calendar & task management
│   │   └── .env.example     Environment variables template
│   │
│   └── tools/               Tool implementations for agents
│       ├── thought/         Base reasoning tool (for all agents)
│       └── scheduler/       Scheduler-specific tools (calendar parsing, conflict detection)
│
├── clients/                 [EXTERNAL INTEGRATIONS]
│   ├── __init__.py          Package initialization
│   ├── config.py            Credential resolution & configuration
│   ├── SETUP.md             Credential setup instructions
│   ├── calendar_client.py   Google Calendar API wrapper
│   └── .env.example         Environment variables template
│
├── commands/                [SLASH COMMANDS FOR USERS]
│   └── schedule-agent.md    /schedule-agent command definition
│
├── system/                  [SYSTEM OPERATIONS & UTILITIES]
│   └── (reserved for system-level tools, monitoring, logging)
│
├── examples/                [USAGE EXAMPLES & TEMPLATES]
│   └── (reference implementations for new agents/tools)
│
└── worktrees/               [GIT WORKTREES] Isolated branches for parallel work
```

---

## Folder Purposes (Detailed)

### `agents/` — Agent Implementations
**Contains:** Agent logic, not client logic or system utilities.

**Rules:**
- ✅ **Only store** `*.py` agent implementations and their direct dependencies
- ✅ **Each agent** gets its own file or subdirectory (e.g., `scheduler.py`, `diagnostician.py`)
- ✅ **Import from** `tools/` for tool definitions, `clients/` for external APIs
- ❌ **Don't store** credentials, configuration (use `clients/config.py`), or system utilities
- ❌ **Don't hardcode** API keys, URLs, or environment-specific paths

**Example agent structure:**
```python
# agents/team/scheduler.py
from claude.tools import ThoughtTool, GoogleCalendarTool
from claude.clients import GoogleCalendarClient

class SchedulerAgent:
    def __init__(self):
        self.thought = ThoughtTool()
        self.calendar = GoogleCalendarTool()
        self.client = GoogleCalendarClient()
    
    async def execute(self, request):
        # Agent logic here
        pass
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

### `system/` — System Utilities & Infrastructure
**Contains:** Logging, monitoring, metrics, system-level tools (not agent-specific).

**Rules:**
- ✅ **Store** system utilities, middleware, hooks
- ✅ **Store** monitoring/debugging tools
- ✅ **Store** batch operations or migrations
- ❌ **Don't store** agent logic or business tools (use `agents/` or `tools/`)
- ❌ **Don't hardcode** agent-specific behavior

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

1. **Create agent file**
   ```
   .claude/agents/team/{agent_name}.py
   ```
   - Define agent class with `__init__` and `execute()` method
   - Import tools from `claude.tools`
   - Import clients from `claude.clients`

2. **Register in `agents.json`**
   ```json
   {
     "id": "unique_id",
     "name": "Human Name",
     "description": "What it does",
     "enabled": true,
     "type": "category",
     "tools": ["tool1", "tool2"],
     "permissions": "read-only" or "write",
     "capabilities": ["cap1", "cap2"]
   }
   ```

3. **Update Team Leader (if spawnable)**
   ```json
   "canSpawn": ["existing_agents", "your_new_agent"]
   ```

4. **Update `requirements.txt`** if new dependencies needed

5. **Write documentation** in `.claude/examples/` if complex

---

### Adding a New Tool

**Checklist:**

1. **Create tool directory**
   ```
   .claude/tools/{tool_name}/
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

3. **Document setup** in `.claude/clients/SETUP.md`
   - Installation steps
   - Credential paths
   - Troubleshooting

4. **Add environment template**
   ```
   .claude/clients/.env.example
   ```

---

## System Orchestration

### Execution Flow

```
User Input
    ↓
Claude Code Harness
    ↓
[Command Definition (.md file)]
    ↓
[Invoke Agent or Tool]
    ↓
Agent.execute(request)
    ├─ Use Thought tool (reasoning)
    ├─ Call specialized tools
    │   └─ Tools use Clients to access external APIs
    ├─ Spawn child agents (if Team Leader)
    └─ Return result
    ↓
Report to User
```

### Team Hierarchy

```
Team Leader (Coordinator)
├── Diagnostician (Code analysis)
├── Bug Fixer (Code fixes)
├── Reviewer (Code validation)
├── Group Sale Manager (BigQuery operations)
└── Scheduler (Calendar & task management)
```

- **Team Leader** can spawn any member
- **Members** execute their specialized tasks
- **All members** have access to Thought tool (reasoning)
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

---

## Adding Features: Step-by-Step Example

### Scenario: Add GitHub code review tool

**Step 1: Create the client**
```
.claude/clients/github_client.py
```

**Step 2: Create the tool**
```
.claude/tools/github/
├── __init__.py
├── reviewer.py   (PR review logic)
└── fetcher.py    (Fetch PR details)
```

**Step 3: Create/Update agent**
```
.claude/agents/team/code_reviewer.py
(or update existing reviewer with new tool)
```

**Step 4: Register in agents.json**
```json
{
  "id": "github",
  "name": "GitHub Tool",
  "tools": [
    {"name": "review_pr", "description": "Review a GitHub PR"}
  ]
}
```

**Step 5: Update Team Leader**
```json
"canSpawn": [..., "code_reviewer"]
```

**Step 6: Document in examples/**
```
.claude/examples/github_agent_example.py
```

**Step 7: Add setup guide**
```
.claude/clients/SETUP.md  (add GitHub setup section)
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

## Before Building Anything

**All agents and developers MUST:**

1. ✅ Read this ARCHITECTURE.md
2. ✅ Check existing agents/tools for similar functionality
3. ✅ Determine which folder the new code belongs in
4. ✅ Follow naming conventions
5. ✅ Update `agents.json` with proper registration
6. ✅ Document with examples if complex
7. ✅ Keep this file updated if architecture changes

---

## Questions for Team Members

**Ask yourself before building:**

- Does this logic belong in an agent, tool, or client?
- Is there already a similar agent/tool I can extend?
- Does this need to be registered in `agents.json`?
- Are my imports following the dependency direction?
- Have I documented this for future developers?
- Does this follow the system's naming conventions?

---

**System Maintainer:** Team Leader Agent  
**Last Reviewed:** August 7, 2026  
**Next Review:** As needed when new agent/tool added

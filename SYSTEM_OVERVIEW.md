# Coding Agent Workspace — Complete System Overview

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Core Components](#core-components)
4. [How It Works](#how-it-works)
5. [Key Features](#key-features)
6. [Usage Guide](#usage-guide)
7. [Directory Structure](#directory-structure)
8. [System Connections](#system-connections)

---

## Project Overview

**Coding Agent Workspace** is an **agent orchestration system** that automates code analysis, bug fixing, and quality review through coordinated multi-agent workflows.

### Purpose

Enable developers to:
- Automatically analyze code for bugs and vulnerabilities
- Fix issues through intelligent agent workflows
- Review code quality at scale
- Track agent execution in real-time
- Understand complex code through distributed reasoning

### Core Philosophy

Instead of one monolithic AI doing all the work, **specialized agents** each handle what they do best:
- **Diagnostician** — finds problems
- **Bug Fixer** — implements solutions
- **Reviewer** — validates quality
- **Team Leader** — coordinates them all

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          User Interface                              │
│                   (Command Line or Terminal)                         │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    workspace_cli/ (CLI Layer)                        │
│  • cli.py — Command parsing and execution                            │
│  • claude_provider.py — Claude Code subprocess bridge               │
│  • __init__.py — Package exports                                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────────┐
│              Orchestration Layer (Choice of 2)                       │
│                                                                       │
│  Option A: Single Terminal                                          │
│  └─ TeamLeaderAgent (from .claude/agents/technical/)               │
│     • Plans workflow (DAG)                                          │
│     • Spawns agents sequentially                                    │
│     • Synthesizes results                                           │
│                                                                       │
│  Option B: Multi-Terminal (NEW!)                                    │
│  └─ MultiTerminalOrchestrator (from .claude/agents/)               │
│     • Spawns agents in separate terminals                           │
│     • Real-time visibility                                          │
│     • Parallel execution tracking                                   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────────┐
│                   Agent Layer (.claude/agents/)                      │
│                                                                       │
│  Technical Agents:                                                   │
│  • DiagnosticianAgent — Analyzes code, finds issues                │
│  • BugFixerAgent — Implements fixes, modifies files                │
│  • ReviewerAgent — Validates quality, approves/rejects              │
│  • TeamLeaderAgent — Coordinates workflow, routes tasks             │
│                                                                       │
│  Business Agents:                                                    │
│  • GroupSaleManagerAgent — Sales data analysis                      │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    Tools Layer (.claude/tools/)                      │
│                                                                       │
│  • Thought Tool — Reasoning and planning capability                 │
│  • BigQuery Tool — Sales data access (business agents)              │
│  • Query Builder — SQL construction                                 │
│  • Schema Reader — Database introspection                           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      Output Layer                                    │
│                                                                       │
│  • Execution Logs — Timestamped trace of all events                │
│  • Mission Files — JSON results in .agent-workspace/runs/           │
│  • Terminal Output — Real-time agent feedback                       │
│  • diff — Changes ready for user review                             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. workspace_cli/ — The CLI Application

**Location:** `C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace\workspace_cli\`

**Purpose:** Provides the user-facing command-line interface and subprocess management.

**Key Files:**

| File | Purpose |
|------|---------|
| `cli.py` | Command parsing, orchestrator routing, execution |
| `claude_provider.py` | Launches Claude Code CLI as subprocess |
| `__main__.py` | Entry point for `python -m workspace_cli` |
| `__init__.py` | Package exports and version info |

**Supported Commands:**
```bash
workspace_cli analyze "task"    # Analyze code
workspace_cli plan "task"       # Create execution plan
workspace_cli review "task"     # Review changes
workspace_cli fix "task"        # Fix issues
workspace_cli execute "task"    # Execute task
workspace_cli solve "task"      # Direct team leader (most common)
```

**CLI Flags:**
```bash
--multi-terminal    # Run agents in separate terminals
--no-team-leader    # Execute without team leader coordination
--workspace DIR     # Custom workspace directory
--quiet             # Suppress output streaming
--version           # Show version
```

---

### 2. .claude/agents/ — The Agent System

**Location:** `C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace\.claude\agents\`

**Purpose:** Specialized agents that perform focused tasks.

#### Technical Agents (`technical/`)

| Agent | Role | Mode | Tools | Purpose |
|-------|------|------|-------|---------|
| **TeamLeaderAgent** | Coordinator | Read-only | Thought | Plans DAG, routes tasks, spawns workers |
| **DiagnosticianAgent** | Analyzer | Read-only | Thought | Analyzes code, identifies bugs/issues |
| **BugFixerAgent** | Implementer | Write | Thought | Implements fixes, modifies files |
| **ReviewerAgent** | Validator | Read-only | Thought | Validates quality, approves changes |

#### Workflow Example

```
Task: "Fix SQL injection vulnerability"
    ↓
TeamLeader (classifies as "bug_analysis")
    ↓
Spawns → DiagnosticianAgent
         (scans code, finds vulnerability)
    ↓
Spawns → BugFixerAgent
         (implements parameterized queries)
    ↓
Spawns → ReviewerAgent
         (validates fix is correct)
    ↓
Results returned to user
```

---

### 3. .claude/tools/ — Capability System

**Location:** `C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace\.claude\tools\`

**Purpose:** Reusable capabilities that agents can invoke.

| Tool | Purpose | Used By |
|------|---------|---------|
| **thought.py** | Reasoning/planning framework | All agents |
| **query_builder.py** | SQL query construction | BigQuery tool |
| **query_executor.py** | Query execution | BigQuery tool |
| **data_fetcher.py** | Data retrieval | BigQuery tool |
| **schema_reader.py** | Database schema inspection | BigQuery tool |

**Thought Tool Methods:**
```python
thought.execute(thought)      # Execute reasoning
thought.analyze(task, context) # Analyze through reasoning
thought.plan(goal, constraints) # Create plan
thought.evaluate(statement, criteria) # Evaluate
```

---

### 4. Multi-Terminal System (NEW)

**Location:** `C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace\.claude\agents\`

**Purpose:** Enable real-time visibility into agent execution by running each in its own terminal.

**Key Components:**

| Component | Purpose |
|-----------|---------|
| `terminal_manager.py` | Spawns terminals, manages lifecycle |
| `multi_terminal_orchestrator.py` | Coordinates multi-terminal execution |

**How It Works:**

1. User runs: `workspace_cli --multi-terminal solve "task"`
2. MultiTerminalOrchestrator classifies the task
3. TerminalManager spawns separate terminals for each agent
4. Each terminal shows real-time agent output
5. Main terminal shows orchestration log
6. Results saved to `.agent-workspace/runs/`

---

## How It Works

### Standard Execution Flow (Single Terminal)

```
1. USER INPUT
   $ python -m workspace_cli solve "Fix authentication bug"
   
2. CLI LAYER (workspace_cli/)
   ├─ Parses command
   ├─ Creates AgentOrchestrator
   └─ Checks if TeamLeader is available
   
3. ORCHESTRATION (workspace_cli/cli.py)
   ├─ execute_solve() called
   ├─ TeamLeaderAgent imported from .claude/
   └─ TeamLeaderAgent.execute(task) invoked
   
4. TEAM LEADER (.claude/agents/technical/)
   ├─ Classifies task → "bug_analysis"
   ├─ Plans DAG → [Diagnostician → BugFixer → Reviewer]
   ├─ Spawns Diagnostician
   ├─ Spawns BugFixer
   ├─ Spawns Reviewer
   └─ Synthesizes results
   
5. AGENT EXECUTION
   Each agent:
   ├─ Initializes (loads tools)
   ├─ Executes task via execute()
   ├─ Uses Thought tool for reasoning
   ├─ Returns structured result
   └─ Next agent in DAG starts
   
6. OUTPUT
   ├─ Results printed to terminal
   ├─ JSON mission saved to .agent-workspace/runs/
   ├─ Diff ready for user review
   └─ Exit code returned (0=success, 1=failure)
```

### Multi-Terminal Execution Flow (NEW)

```
1. USER INPUT
   $ python -m workspace_cli --multi-terminal solve "Fix authentication bug"
   
2. CLI LAYER (workspace_cli/)
   ├─ Parses command
   ├─ Sees --multi-terminal flag
   └─ Calls execute_multi_terminal()
   
3. MULTI-TERMINAL ORCHESTRATOR
   ├─ MultiTerminalOrchestrator created
   ├─ Task classified → "bug_analysis"
   ├─ TerminalManager created
   └─ Agent runner scripts generated
   
4. TERMINAL SPAWNING (TerminalManager)
   ├─ Spawn Windows terminal for Diagnostician
   │  └─ Runs diagnostician_{run_id}.py
   ├─ Spawn Windows terminal for BugFixer
   │  └─ Runs bug_fixer_{run_id}.py
   └─ Spawn Windows terminal for Reviewer
      └─ Runs reviewer_{run_id}.py
   
5. PARALLEL EXECUTION
   Each terminal independently:
   ├─ Imports agent class
   ├─ Creates agent instance
   ├─ Calls execute(task)
   ├─ Shows output in that terminal
   └─ Waits for user to close
   
6. MAIN TERMINAL
   Shows:
   ├─ Orchestration trace
   ├─ Which agents spawned
   ├─ Where terminals opened
   ├─ Execution log
   └─ Cleanup confirmation
```

---

## Key Features

### 1. Automatic Task Classification

System intelligently determines workflow based on task keywords:

```python
TASK_PATTERNS = {
    "security": ["vulnerability", "injection", "exploit", ...],
    "bug_analysis": ["bug", "error", "crash", "broken", ...],
    "performance": ["slow", "memory leak", "optimize", ...],
    "quality": ["review", "refactor", "design", ...],
    "data_operations": ["query", "aggregate", "export", ...]
}
```

### 2. DAG-Based Execution

Team Leader creates directed acyclic graphs:

```
Bug Analysis Task:
    Diagnostician
         ↓
    BugFixer
         ↓
    Reviewer

Quality Task:
    Diagnostician
         ↓
    Reviewer
```

### 3. Real-Time Visibility

Multi-terminal mode gives unprecedented visibility:

```
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ Main Terminal       │  │ Diagnostician Term  │  │ BugFixer Terminal   │
│                     │  │                     │  │                     │
│ [ORCHESTRATION]     │  │ AGENT: DIAGNOSTICIAN│  │ AGENT: BUG_FIXER    │
│ [SPAWN] diagnostician│  │                     │  │                     │
│ [SPAWN] bug_fixer   │  │ Analyzing auth.py   │  │ Planning fixes...   │
│ [SPAWN] reviewer    │  │                     │  │                     │
│                     │  │ Found issues:       │  │ Will modify:        │
│ ✓ All agents        │  │ - SQL injection     │  │ - auth.py           │
│   spawned           │  │ - Missing check     │  │ - database.py       │
│                     │  │                     │  │                     │
│ Press any key...    │  │ [Press Enter]       │  │ [Press Enter]       │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘

                  ┌─────────────────────┐
                  │ Reviewer Terminal   │
                  │                     │
                  │ AGENT: REVIEWER     │
                  │                     │
                  │ Reviewing changes...|
                  │                     │
                  │ Status: ✓ APPROVED  │
                  │                     │
                  │ [Press Enter]       │
                  └─────────────────────┘
```

### 4. Persistent Execution History

All runs saved to `.agent-workspace/runs/{run-id}.json`:

```json
{
  "run_id": "run-2026-07-29T14-30-45",
  "timestamp": "2026-07-29T14:30:45.123456",
  "task": "Fix SQL injection in auth.py",
  "result": "EXECUTION REPORT..."
}
```

### 5. Cross-Platform Support

- **Windows:** Opens new `cmd` windows
- **macOS:** Opens Terminal.app
- **Linux:** Opens `gnome-terminal`

---

## Usage Guide

### Quick Start

```bash
# Navigate to project
cd C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace

# Show available commands
python -m workspace_cli --help

# Standard execution (single terminal)
python -m workspace_cli solve "Analyze my code for security issues"

# Multi-terminal execution (see each agent work)
python -m workspace_cli --multi-terminal solve "Fix the authentication bug"

# Custom workspace directory
python -m workspace_cli --multi-terminal --workspace ./debug-runs solve "task"
```

### Example Workflows

#### Workflow 1: Find and Fix a Bug

```bash
# Step 1: Discover bug
# You notice authentication is broken

# Step 2: Launch analysis
python -m workspace_cli --multi-terminal solve "Fix authentication failure in login flow"

# Step 3: Watch the work
# - Diagnostician terminal: Shows what's broken
# - BugFixer terminal: Shows how it's being fixed
# - Reviewer terminal: Shows validation

# Step 4: Review results
# - Check .agent-workspace/runs/ for detailed results
# - Review the diff
# - Test the fix
# - Commit if satisfied
```

#### Workflow 2: Code Quality Review

```bash
python -m workspace_cli --multi-terminal review "Review the payment module for best practices"

# Diagnostician finds issues
# Reviewer validates improvements
# Results saved with recommendations
```

#### Workflow 3: Security Analysis

```bash
python -m workspace_cli analyze "Check for SQL injection vulnerabilities in queries"

# Automatically routes to security-focused workflow
# Diagnostician scans for injection points
# Results highlight vulnerable code
```

---

## Directory Structure

```
coding-agent-workspace/
│
├── workspace_cli/                   # ← CLI Application Package
│   ├── __init__.py                 # Package exports
│   ├── __main__.py                 # Entry point
│   ├── cli.py                      # Command routing & orchestration
│   ├── claude_provider.py          # Claude subprocess bridge
│   └── __pycache__/
│
├── .claude/                        # ← Agent System
│   ├── agents/
│   │   ├── __init__.py            # Agent registry
│   │   ├── technical/             # Code analysis agents
│   │   │   ├── __init__.py
│   │   │   ├── team_leader.py     # Coordinator agent
│   │   │   ├── diagnostician.py   # Analyzer agent
│   │   │   ├── bug_fixer.py       # Implementer agent
│   │   │   └── reviewer.py        # Validator agent
│   │   │
│   │   ├── business/              # Sales management agents
│   │   │   ├── __init__.py
│   │   │   └── group_sale_manager.py
│   │   │
│   │   ├── multi_terminal_orchestrator.py  # NEW: Multi-terminal coordination
│   │   ├── terminal_manager.py             # NEW: Terminal spawning
│   │   └── agent_runners/                  # NEW: Generated runner scripts
│   │
│   ├── tools/                     # Agent capabilities
│   │   ├── __init__.py           # Tool registry
│   │   ├── thought.py            # Reasoning tool
│   │   ├── query_builder.py      # SQL construction
│   │   ├── query_executor.py     # Query execution
│   │   ├── data_fetcher.py       # Data retrieval
│   │   └── schema_reader.py      # Schema inspection
│   │
│   ├── docs/                     # Documentation
│   │   ├── AGENTS.md
│   │   ├── EXPERIMENTAL_FEATURES.md
│   │   └── MULTI_TERMINAL_GUIDE.md  # NEW: Multi-terminal usage
│   │
│   ├── config.py                 # Agent configuration
│   ├── agents.json               # Agent definitions
│   ├── settings.json             # System settings
│   └── settings.local.json       # Local overrides
│
├── .agent-workspace/             # ← Execution Results
│   └── runs/
│       ├── run-2026-07-29T14-30-45.json
│       ├── run-2026-07-29T14-45-12.json
│       └── ...
│
├── pyproject.toml                # Python package config
├── SYSTEM_OVERVIEW.md            # ← This file
└── README.md
```

---

## System Connections

### Data Flow

```
User Command
    ↓
workspace_cli/cli.py (parse args)
    ↓
Check for --multi-terminal flag
    ├─ YES → MultiTerminalOrchestrator
    │        ├─ Classify task
    │        ├─ TerminalManager.spawn_terminal()
    │        └─ Show orchestration log
    │
    └─ NO → AgentOrchestrator.execute_solve()
            ├─ Import TeamLeaderAgent from .claude
            ├─ TeamLeader.execute(task)
            ├─ Agents collaborate via Thought tool
            └─ Return results
    ↓
workspace_cli/claude_provider.py (if needed)
    ├─ Launch Claude Code CLI subprocess
    ├─ Stream output
    └─ Capture response
    ↓
.agent-workspace/runs/ (persist)
    ├─ Save mission JSON
    ├─ Save execution log
    └─ Save results
    ↓
Output to terminal
    ├─ Display summary
    ├─ Show exit code
    └─ Ready for user action
```

### Import Hierarchy

```
workspace_cli/cli.py (entry point)
    ├─ imports
    │   ├─ .claude.agents.technical.TeamLeaderAgent
    │   ├─ .claude.agents.multi_terminal_orchestrator.MultiTerminalOrchestrator
    │   └─ .claude.config
    │
    └─ uses
        ├─ .claude.agents.terminal_manager.TerminalManager
        └─ workspace_cli.claude_provider.run_claude()

.claude.agents.technical.TeamLeaderAgent
    ├─ imports
    │   ├─ .diagnostician.DiagnosticianAgent
    │   ├─ .bug_fixer.BugFixerAgent
    │   └─ .reviewer.ReviewerAgent
    │
    └─ uses
        └─ .tools.get_tool("thought")

.claude.agents.multi_terminal_orchestrator.MultiTerminalOrchestrator
    ├─ imports
    │   └─ .terminal_manager.TerminalManager
    │
    └─ uses
        ├─ .tools.get_tool()
        └─ .technical.get_technical_agent()
```

---

## Key Concepts

### Agents

Specialized autonomous units that:
- Have specific roles (analyze, fix, review)
- Have constrained permissions (read-only vs. write)
- Use tools for capabilities (Thought, BigQuery)
- Execute independently
- Return structured results

### Tools

Reusable capabilities that agents invoke:
- **Thought Tool** — Internal reasoning framework
- **BigQuery Tools** — External data access
- **Extensible** — New tools can be added

### Orchestration

The coordination layer that:
- Routes tasks to appropriate agents
- Creates execution plans (DAGs)
- Manages parallel vs. sequential execution
- Synthesizes results

### Modes

**Single Terminal** — Traditional approach, agents run silently in background

**Multi-Terminal** — New approach, each agent visible in separate window

### Mission

Complete execution record:
- Task description
- Agents involved
- Execution trace
- Results and changes
- Timestamp and run ID

---

## Configuration

### Enable/Disable Features

Edit `.claude/settings.json`:

```json
{
  "experimental_agent_teams_enabled": true,
  "multi_terminal_enabled": true,
  "max_retries": 5,
  "timeout_seconds": 300
}
```

### Agent Definitions

Edit `.claude/agents.json`:

```json
{
  "agents": {
    "diagnostician": {
      "enabled": true,
      "tools": ["thought"],
      "mode": "read-only"
    }
  }
}
```

---

## Performance Characteristics

| Metric | Single Terminal | Multi-Terminal |
|--------|-----------------|-----------------|
| **Setup Time** | ~1 second | ~3-5 seconds |
| **Execution Visibility** | After complete | Real-time |
| **Terminal Complexity** | Single window | N windows |
| **Parallel Execution** | Sequential DAG | Parallel spawned |
| **Resource Usage** | Low | Medium (N processes) |
| **Debugging** | Difficult | Easy |

---

## Next Steps

1. **Read** the Quick Start section above
2. **Try** a single-terminal execution: `workspace_cli solve "task"`
3. **Explore** multi-terminal: `workspace_cli --multi-terminal solve "task"`
4. **Review** results in `.agent-workspace/runs/`
5. **Extend** by adding new agents or tools

---

## Related Documentation

- [Multi-Terminal Guide](.claude/docs/MULTI_TERMINAL_GUIDE.md)
- [Agent System](.claude/docs/AGENTS.md)
- [Experimental Features](.claude/docs/EXPERIMENTAL_FEATURES.md)

---

**Version:** 0.1.0  
**Last Updated:** 2026-07-29  
**Project:** Coding Agent Workspace

# Codebase Onboarding Guide

Welcome to the **Coding Agent Workspace** — an intelligent multi-agent system for code analysis and debugging. This guide explains the codebase structure and how to navigate it effectively.

---

## Quick Map

**New to the project?** Start here in this order:

1. Read **Project Overview** (this section)
2. Review **System Architecture** to understand the big picture
3. Follow **The Reading Path** — a guided walk through the code
4. Explore **Key Files** when you're ready to dive deeper
5. Study **Execution Flow** to see how everything connects

---

## Project Overview

### What Is This Project?

**Coding Agent Workspace** is a Python-based agent orchestration system that uses Claude AI to analyze and improve code. Instead of running one agent, it orchestrates multiple specialized agents working in parallel:

- **Team Leader** — Receives tasks, classifies them, and coordinates
- **Diagnostician** — Analyzes code to find issues  
- **BugFixer** — Implements fixes for discovered problems
- **Reviewer** — Validates findings and scores quality
- **AgentArchitect** — Designs and generates new agents
- **GroupSaleManager** — Handles data operations tasks

### Key Characteristics

- **Multi-Agent**: Not one "AI" doing everything; specialized agents working in parallel
- **Tmux-Based**: Agents run in separate tmux panes for real-time visibility
- **Task Classification**: Automatically routes tasks to the right agents
- **Python 3.9+**: Modern Python with PEP 517/518 packaging
- **Production-Ready**: Version 0.3.0, actively maintained

### What Can It Do?

```bash
# Security analysis → routes to Diagnostician + Reviewer
coding-agent-workspace solve "find security vulnerabilities"

# Bug fixing → routes to Diagnostician + BugFixer + Reviewer  
coding-agent-workspace solve "fix authentication issues"

# Code review → routes to Diagnostician + Reviewer
coding-agent-workspace solve "review code quality"

# Add new agent → routes to AgentArchitect + Reviewer
coding-agent-workspace solve "create an agent for X"

# Data operations → routes to GroupSaleManager
coding-agent-workspace solve "query and analyze sales data"
```

---

## System Architecture

### High-Level Flow

```
User Request
    ↓
CLI Entry (workspace_cli/cli.py)
    ↓
AgentOrchestrator (creates run ID, coordinates)
    ↓
TeamLeaderAgent (orchestrator)
    ├─ Classifies task type (security, bug_analysis, etc.)
    ├─ Determines which agents to use
    ├─ Builds execution workflow
    └─ Spawns agents in tmux panes
        ├─ Agent 1 (Diagnostician, BugFixer, etc.)
        ├─ Agent 2 (parallel execution)
        └─ Agent 3 (in separate tmux panes)
    ↓
Results → Terminal output + JSON file in .agent-workspace/
```

### The Agent System

All agents follow the same pattern:

```
Agent
  ├─ Inherits from BaseAgent
  ├─ Has name, type, mode, tools
  ├─ Implements execute(task, run_id) method
  └─ Returns dict with success/findings/results
```

**Agent Types:**

| Agent | Purpose | Tools | Workflow Role |
|-------|---------|-------|---------------|
| **Team Leader** | Orchestration | thought | Coordinator |
| **Diagnostician** | Code analysis | grep, read, glob | Issue finder |
| **BugFixer** | Implementation | edit, bash | Fix applier |
| **Reviewer** | Validation | all tools | Quality gate |
| **AgentArchitect** | Agent design | all tools | Creator |
| **GroupSaleManager** | Data operations | database tools | Data handler |

### Task Classification

The Team Leader classifies tasks using keyword matching:

```python
# From team_leader.py
TASK_PATTERNS = {
    "security": ["security", "vulnerabilities", "breach", ...],
    "bug_analysis": ["bug", "error", "crash", ...],
    "performance": ["slow", "memory", "optimization", ...],
    "quality": ["review", "validate", "refactor", ...],
    "data_operations": ["query", "sales", "bigquery", ...],
    "agent_creation": ["add agent", "create agent", ...]
}
```

Task → Match keywords → Determine task_type → Select agents → Build workflow

---

## The Reading Path

### Step 1: Understand the Entry Point (5 min)

**File:** `workspace_cli/cli.py`

Start at `main()` and follow down:

1. `main()` — Gets you started
2. `create_parser()` — Defines CLI commands
3. `execute_command()` — Routes to appropriate action
4. `AgentOrchestrator` — Manages runs and delegation

**Key Insight:** The CLI is thin; it delegates to `AgentOrchestrator` which creates a run ID and calls `TeamLeaderAgent`.

---

### Step 2: Understand the Orchestrator (5 min)

**File:** `workspace_cli/cli.py` → `AgentOrchestrator` class

The orchestrator does three things:

1. **Creates run IDs**: Unique identifier for each execution (timestamp-based)
2. **Saves missions**: Stores results to `.agent-workspace/runs/{run_id}.json`
3. **Routes tasks**: For `solve` command, calls `TeamLeaderAgent.execute()`

**Key Method:** `execute_solve()` — This is where "solve" commands come in

---

### Step 3: The Team Leader — The Brain (10 min)

**File:** `.claude/agents/technical/team_leader.py`

The Team Leader is the orchestrator's orchestrator. Read in this order:

1. `__init__()` — Sets up terminal manager, tools, logging
2. `execute()` — The main entry point (follows this sequence):
   - Classify task → `_classify_task()`
   - Plan approach → `thought_tool.plan()`
   - Choose agents → `_determine_agents()`
   - Build workflow → `_build_workflow()`
   - Execute workflow → `_execute_workflow()`

**Key Insight:** The Team Leader doesn't do work; it **orchestrates** work by:
- Classifying what needs to be done
- Picking which agents fit best
- Running them in sequence with context passing
- Collecting and returning results

**Task Classification:** Read `_classify_task()` to understand how it picks a task type

---

### Step 4: The Base Agent — The Foundation (5 min)

**File:** `.claude/agents/base_agent.py`

All specialist agents inherit from `BaseAgent`. It provides:

```python
class BaseAgent:
    __init__(name, type, mode, tool_names)  # Setup
    _init_tools()                             # Load tools
    _print_header(task, run_id)              # Output formatting
    _print_footer(status)                     # Output formatting
    _agent_result(success, **kwargs)         # Result packaging
```

**Key Insight:** `BaseAgent` is minimal — just setup and formatting. Agents extend it to add their own `execute()` logic.

---

### Step 5: A Specialist Agent — See It In Action (5 min)

**File:** `.claude/agents/technical/diagnostician.py`

The simplest agent to understand:

1. `__init__()` — Sets name, type, mode, and tools (grep, read, glob)
2. `execute()` — 
   - Prints header
   - Calls `_analyze_python_files()` to scan code
   - Collects findings
   - Prints footer

**What It Does:** Scans Python files, looks for issues (hardcoded secrets, bare exceptions, missing docstrings), and returns a list of findings.

**Read Also:** 
- `bug_fixer.py` — More complex; implements fixes (uses edit, bash)
- `reviewer.py` — Validates findings; calculates scores

---

### Step 6: The Terminal Manager — How Agents Run (5 min)

**File:** `.claude/agents/claude_terminal_manager.py`

Manages tmux sessions and split panes:

1. `__init__()` — Creates/connects to tmux session
2. `_ensure_tmux_session()` — Creates session if needed
3. `open_agent_terminal()` — Opens a split pane for an agent
4. `wait_for_pane_completion()` — Waits for agent to finish

**Key Insight:** Agents can run inline (default) or in tmux panes (if configured). The terminal manager creates the split panes and monitors them.

---

### Step 7: Configuration and Tools (5 min)

**Files:** 
- `.claude/config.py` — Read/write settings
- `.claude/tools/` — Reusable utilities
- `.claude/settings.json` — User preferences

**Tools Available:**
- `thought.py` — Reasoning and planning
- `read.py` / `edit.py` / `bash.py` — File operations
- `grep.py` — Code search
- Others as needed

---

## Key Files Map

### Core Application

```
workspace_cli/
├── cli.py                          # Entry point; defines CLI commands
├── claude_provider.py              # Claude API integration (imported but not shown)
└── __init__.py
```

**What to read:** `cli.py` main() → execute_command() → AgentOrchestrator.execute_solve()

### Agent System

```
.claude/agents/
├── base_agent.py                   # Base class for all agents
├── agent_utils.py                  # Shared utilities
├── claude_terminal_manager.py       # Tmux management
├── config.py                        # Configuration loading
├── __init__.py
├── technical/
│   ├── team_leader.py              # MOST IMPORTANT - Orchestrator
│   ├── diagnostician.py            # Issue finder
│   ├── bug_fixer.py                # Fix implementer
│   ├── reviewer.py                 # Quality validator
│   ├── agent_architect.py           # Agent generator
│   └── __init__.py
└── business/
    ├── group_sale_manager.py       # Data operations
    └── __init__.py
```

**What to read in order:**
1. `base_agent.py` — Understand the base class
2. `team_leader.py` — Understand orchestration
3. One specialist agent (diagnostician.py is simplest)

### Tools

```
.claude/tools/
├── __init__.py
├── thought.py                      # Planning and reasoning
├── read.py                         # File reading
├── edit.py                         # File editing
├── bash.py                         # Command execution
├── grep.py                         # Code search
└── ... other tools
```

### Configuration

```
.claude/
├── settings.json                   # Global settings
└── settings.local.json            # Local overrides (if present)
```

### Project Structure

```
coding-agent-workspace/
├── .claude/                        # Agent system (all agents here)
├── workspace_cli/                  # CLI interface
├── .agent-workspace/
│   └── runs/                       # Saved mission results
├── pyproject.toml                  # Python packaging config
├── README.md                       # Project overview
├── ARCHITECTURE.md                 # System design
└── ONBOARDING.md                   # This file
```

---

## Execution Flow - Step By Step

### What Happens When You Run This:

```bash
coding-agent-workspace solve "find security vulnerabilities"
```

#### 1. CLI Initialization (workspace_cli/cli.py)

```
main()
  └─ create_parser() creates ArgumentParser
  └─ args = parser.parse_args()  # args.command = "solve", args.task = "..."
  └─ execute_command(args)
```

#### 2. Orchestration Start (workspace_cli/cli.py)

```
execute_command(args)
  └─ orchestrator = AgentOrchestrator(".agent-workspace")
  └─ run_id = orchestrator.create_run_id()  # "run-2026-07-29T..."
  └─ Since command == "solve":
      └─ orchestrator.execute_solve(task, multi_terminal=True)
```

#### 3. Team Leader Takes Over (team_leader.py)

```
AgentOrchestrator.execute_solve()
  └─ team_leader = TeamLeaderAgent(run_id)
  └─ result = team_leader.execute(task, run_id)
      ├─ Step 1: _classify_task(task)
      │   └─ Returns "security" (matched keywords)
      │
      ├─ Step 2: thought_tool.plan(task)
      │   └─ Creates thinking/reasoning
      │
      ├─ Step 3: _determine_agents("security", task)
      │   └─ Returns ["diagnostician", "reviewer"]
      │
      ├─ Step 4: _build_workflow(task, "security", agents, thinking)
      │   └─ Creates workflow steps
      │
      └─ Step 5: _execute_workflow(task, "security", workflow, agents)
          ├─ For each step in workflow:
          │   └─ _spawn_agent(agent_name, task)
          │       ├─ Instantiate agent class (DiagnosticianAgent, ReviewerAgent)
          │       ├─ Call agent.execute(task, run_id)
          │       └─ Collect results
          └─ Aggregate and return all results
```

#### 4. Specialist Agent Executes (diagnostician.py, reviewer.py, etc.)

Each agent does the same pattern:

```
agent.execute(task, run_id)
  ├─ _print_header(task, run_id)  # [AGENT: DIAGNOSTICIAN] header
  ├─ Do the work:
  │   ├─ Scan files
  │   ├─ Find issues
  │   ├─ Collect findings
  │   └─ Print progress
  ├─ _print_footer("COMPLETED")
  └─ return _agent_result(success=True, findings=[...], ...)
```

#### 5. Results Are Collected and Saved

```
orchestrator.save_mission(run_id, task, result)
  └─ Writes to: .agent-workspace/runs/{run_id}.json
```

#### 6. Output to User

The Team Leader's result is formatted and printed showing:
- Task classification
- Workflow steps
- Agents executed
- Final status

---

## Key Concepts

### 1. **Task Classification**

Tasks are matched against keyword patterns to determine their type. This routes them to the right agents.

```python
# From team_leader.py TASK_PATTERNS
Task: "find security vulnerabilities"
  ├─ Match against "security" pattern
  ├─ Keywords: "security", "vulnerabilities", ...
  └─ Task Type: "security" ✓
      └─ Agents: ["diagnostician", "reviewer"]
```

### 2. **Agents Are Stateless**

Each agent is instantiated, executed, and discarded:

```python
agent = DiagnosticianAgent()  # Create
result = agent.execute(task, run_id)  # Run
# agent is not reused
```

This keeps the system simple and predictable.

### 3. **Results Are Dictionaries**

Every agent returns a dict with at minimum:

```python
{
    "success": True,
    "agent": "diagnostician",
    "findings": [...],
    # ... other fields based on agent type
}
```

### 4. **Context Passing**

The Team Leader passes context from one agent to the next:

```python
# After agent 1 finishes:
current_context["latest_findings"] = agent1_result.get("thinking")
current_context["issues"] = agent1_result.get("findings")

# Agent 2 gets context in its task:
enriched_task = f"{agent_task}\n\nContext: {current_context}"
```

### 5. **Tools Are Registered**

Tools are loaded via a registry pattern:

```python
from tools import get_tool

tool = get_tool("thought")()  # Get tool by name, instantiate
```

This allows dynamic tool loading and substitution.

---

## Common Tasks

### Adding a New Agent

1. **Create the agent file:** `.claude/agents/technical/my_agent.py`

```python
from ..base_agent import BaseAgent

class MyAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="my_agent",
            type="analyzer",  # or "fixer", "validator", etc.
            mode="read-only",  # or "read-write"
            tool_names=["grep", "read"]  # Tools it uses
        )
    
    def execute(self, task: str, run_id: str = "default") -> dict:
        self._print_header(task, run_id)
        
        # Do work here
        findings = []
        
        self._print_footer()
        return self._agent_result(success=True, findings=findings)
```

2. **Register in Team Leader:** Update `team_leader.py`:

```python
# In TASK_PATTERNS, add pattern if needed
TASK_PATTERNS = {
    "my_task_type": ["keyword1", "keyword2", ...],
    # ...
}

# In _determine_agents(), add routing
elif task_type == "my_task_type":
    agents = ["my_agent"]

# In _spawn_agent(), add instantiation
elif agent_name == "my_agent":
    agent = MyAgentImport()
```

3. **Import the agent** in team_leader.py

### Adding a New Tool

1. **Create tool file:** `.claude/tools/my_tool.py`

```python
class MyTool:
    def __init__(self):
        self.name = "my_tool"
    
    def execute(self, **kwargs):
        # Implementation
        return result
```

2. **Register in tool registry** (in `.claude/tools/__init__.py`)

3. **Use in agents:**

```python
class MyAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="my_agent",
            type="analyzer",
            mode="read-only",
            tool_names=["my_tool"]  # Add here
        )
```

### Changing Task Classification

Edit the `TASK_PATTERNS` dict in `team_leader.py`:

```python
TASK_PATTERNS = {
    "my_new_type": [
        "keyword1", "keyword2", "phrase"
    ]
}
```

Any task matching these keywords will be classified as `my_new_type`.

---

## Configuration

### Settings File: `.claude/settings.json`

```json
{
  "theme": "dark",
  "preferences": {
    "terminalManager": "tmux",
    "tmuxSessionPrefix": "agents-",
    "tmuxAutoAttach": false,
    "tmuxSplitPanes": false
  },
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "CLAUDE_AGENT_COMMUNICATION_ENABLED": "1"
  }
}
```

**Key Settings:**
- `tmuxAutoAttach` — Automatically attach to tmux when agents run
- `tmuxSplitPanes` — Run agents in separate panes (requires tmux)
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` — Enable experimental features

### Environment Variables

```bash
# Enable experimental mode (adds tracing and logging)
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1

# Enable agent communication logging
export CLAUDE_AGENT_COMMUNICATION_ENABLED=1

# Enable interactive mode
export INTERACTIVE_MODE_ENABLED=1
```

---

## Debugging Tips

### 1. Check Results File

```bash
cat .agent-workspace/runs/run-2026-07-29T*.json
```

This shows what agents did and what they found.

### 2. Enable Experimental Mode

```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
coding-agent-workspace solve "your task"
```

This adds detailed trace logging and shows execution flow.

### 3. Watch tmux Session

```bash
tmux attach-session -t agents-{run_id}

# Navigate:
Ctrl+B n     # Next window
Ctrl+B p     # Previous window
Ctrl+B 0-9   # Jump to window
```

### 4. Add Debug Prints

Agents are just Python classes. Add `print()` statements to debug:

```python
def execute(self, task, run_id):
    self._print_header(task, run_id)
    print(f"[DEBUG] Task received: {task}")
    # ... rest of code
```

### 5. Test a Single Agent

Create a test script:

```python
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / ".claude"))
from agents.technical.diagnostician import DiagnosticianAgent

agent = DiagnosticianAgent()
result = agent.execute("test task", "test-run")
print(result)
```

---

## Module Dependencies

```
workspace_cli/
└── cli.py
    ├── AgentOrchestrator (in cli.py)
    │   └── calls TeamLeaderAgent
    └── claude_provider.py (Claude API wrapper)

.claude/
├── agents/
│   ├── base_agent.py
│   │   └── BaseAgent (parent class)
│   ├── technical/
│   │   ├── team_leader.py
│   │   │   └── imports all specialist agents
│   │   ├── diagnostician.py
│   │   ├── bug_fixer.py
│   │   ├── reviewer.py
│   │   ├── agent_architect.py
│   │   └── imports base_agent
│   ├── business/
│   │   ├── group_sale_manager.py
│   │   └── imports base_agent
│   ├── claude_terminal_manager.py
│   ├── agent_utils.py
│   └── config.py
└── tools/
    ├── __init__.py
    ├── thought.py
    ├── read.py
    ├── edit.py
    └── ...
```

---

## Glossary

| Term | Meaning |
|------|---------|
| **Run ID** | Unique identifier for one execution (timestamp-based) |
| **Task Type** | Classification (security, bug_analysis, quality, etc.) |
| **Workflow** | Sequence of agent steps to execute |
| **Agent** | Specialist that does one type of work |
| **Execution Result** | Dict with success flag, findings, and results |
| **Mission** | Saved record of a run (JSON file in .agent-workspace/) |
| **Context Passing** | Feeding agent N's output as input to agent N+1 |
| **Split Panes** | Running agents in separate tmux windows for visibility |
| **Tool** | Reusable utility (grep, read, edit, bash, thought) |

---

## Next Steps

1. **Run a Test:** 

```bash
coding-agent-workspace solve "find bugs in the workspace_cli module"
```

2. **Examine Results:**

```bash
cat .agent-workspace/runs/run-*.json | head -50
```

3. **Review Code:** Open a specialist agent (diagnostician.py) and read it end-to-end

4. **Add a Feature:** Create a new agent or tool following the patterns

5. **Read Supporting Docs:**
   - `README.md` — Project overview
   - `ARCHITECTURE.md` — Detailed design
   - `QUICKSTART.md` — Usage examples

---

## Summary

**Coding Agent Workspace** is built on these core ideas:

1. **Specialization** — Different agents for different tasks
2. **Orchestration** — Team Leader coordinates them
3. **Simplicity** — Agents inherit from BaseAgent, return dicts
4. **Visibility** — Tmux panes show agent activity in real-time
5. **Extensibility** — Easy to add new agents and tools

To understand it: Start with `cli.py` → `TeamLeaderAgent` → one specialist agent → one tool. That's 90% of the system.

Good luck! 🚀

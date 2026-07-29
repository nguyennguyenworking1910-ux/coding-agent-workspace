# System Architecture

Complete technical documentation of the Coding Agent Workspace system design, components, and execution flow.

**Version:** 0.3.0  
**Last Updated:** 2026-07-29

---

## Table of Contents

1. [Overview](#overview)
2. [Core Architecture](#core-architecture)
3. [Components](#components)
4. [Execution Flow](#execution-flow)
5. [Terminal Management (Tmux)](#terminal-management-tmux)
6. [Task Classification](#task-classification)
7. [Agent Coordination](#agent-coordination)
8. [Data Flow](#data-flow)
9. [Configuration](#configuration)

---

## Overview

The system follows a **coordinator + specialists** pattern where:

- **Team Leader** (coordinator) receives tasks and orchestrates execution
- **Specialist Agents** execute specific tasks in parallel
- **Tmux** manages multi-pane terminal execution
- **Direct output** through simple print statements (no boilerplate)

### Design Principles

1. **Single Responsibility** - Each agent has one focused role
2. **Parallel Execution** - Agents work independently and simultaneously
3. **Task-Driven** - Tasks determine which agents to use
4. **Direct Communication** - Simple print output, no complex messaging
5. **Organized State** - Each execution gets isolated tmux session

---

## Core Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────┐
│              User (Claude Code Terminal)                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │   CLI Entry Point      │
        │  (workspace_cli/cli.py)│
        └────────────┬───────────┘
                     │
                     ▼
        ┌────────────────────────────────────┐
        │   Team Leader Agent                │
        │ - Task classification              │
        │ - Agent selection                  │
        │ - Workflow coordination            │
        │ - Tmux session management          │
        └────────────┬───────────────────────┘
                     │
        ┌────────────┴──────────────┬────────────────┐
        │                           │                │
        ▼                           ▼                ▼
   ┌─────────────┐            ┌──────────────┐ ┌────────────┐
   │Diagnostician│            │   Reviewer   │ │ BugFixer   │
   │ - Analyzes  │            │ - Validates  │ │ - Fixes    │
   │ - Finds     │            │ - Scores     │ │ - Commits  │
   │   issues    │            │ - Approves   │ │ - Improves │
   └─────────────┘            └──────────────┘ └────────────┘
   (in tmux pane)             (in tmux pane)   (in tmux pane)
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Language** | Python 3.9+ | Core implementation |
| **CLI Framework** | Click (via workspace_cli) | Command-line interface |
| **Terminal Mgmt** | tmux | Multi-pane execution |
| **AI Model** | Claude (via tools) | Agent reasoning |
| **Package Format** | pyproject.toml | PEP 517/518 packaging |

---

## Components

### 1. Team Leader Agent (`.claude/agents/technical/team_leader.py`)

**Role:** Orchestrator that coordinates all agents

**Key Responsibilities:**
- Classify incoming tasks by type
- Select appropriate agents for the task
- Build execution workflow
- Manage tmux session initialization
- Execute agents and aggregate results
- Broadcast execution status

**Key Methods:**
```python
def execute(task: str) -> dict
    # Main entry point - executes the full workflow

def _classify_task(task: str) -> str
    # Determines task type: security, bug_analysis, quality, etc.

def _select_agents(task_type: str) -> list
    # Returns agents needed for the task type

def _execute_workflow(task, task_type, workflow) -> dict
    # Runs all agents in parallel

def _spawn_agent(agent_name: str, task: str) -> dict
    # Executes a single agent in tmux window
```

**Task Classification Patterns:**

```python
TASK_PATTERNS = {
    "security": ["security", "vulnerabilities", "exploit", ...],
    "bug_analysis": ["bug", "error", "issue", "crash", ...],
    "performance": ["performance", "slow", "optimize", ...],
    "quality": ["quality", "review", "refactor", ...],
    "data_operations": ["query", "bigquery", "sales", ...]
}
```

---

### 2. Specialist Agents

#### Diagnostician Agent (`.claude/agents/technical/diagnostician.py`)

**Purpose:** Code analysis and issue detection

**Analyzes:**
- Hardcoded credentials (password, api_key, secret, token)
- Bare exception handlers
- Missing function docstrings
- Code style violations

**Output:**
```python
{
    "success": True,
    "agent": "diagnostician",
    "findings": [
        {
            "file": "auth.py",
            "issue": "Hardcoded credentials detected",
            "severity": "CRITICAL"
        }
    ],
    "status": "analysis_complete"
}
```

#### Bug Fixer Agent (`.claude/agents/technical/bug_fixer.py`)

**Purpose:** Fix planning and implementation

**Strategies:**
- Code review for logical errors
- Error handling improvements
- Security hardening
- Input validation
- Performance optimization
- Testing improvements

**Output:**
```python
{
    "success": True,
    "agent": "bug_fixer",
    "changes": [
        {
            "type": "code_review",
            "description": "Review code for logical errors",
            "priority": "HIGH"
        }
    ],
    "status": "ready_to_fix"
}
```

#### Reviewer Agent (`.claude/agents/technical/reviewer.py`)

**Purpose:** Validation and quality assessment

**Validates:**
- Docstring presence
- Error handling completeness
- Code style consistency
- Security practices
- Test coverage

**Output:**
```python
{
    "success": True,
    "agent": "reviewer",
    "score": 85,
    "approval": "APPROVED",
    "issues": [
        {
            "type": "testing",
            "description": "Limited test coverage",
            "severity": "MEDIUM"
        }
    ],
    "status": "review_complete"
}
```

---

### 3. Terminal Manager (`.claude/agents/claude_terminal_manager.py`)

**Purpose:** Manage tmux session and pane creation

**Key Methods:**
```python
def open_agent_terminal(agent_name, task, run_id) -> str
    # Create tmux window for agent
    # Execute agent script in window
    # Return terminal_id

def _ensure_tmux_session()
    # Verify tmux session exists
    # Create if needed with dimensions

def _create_tmux_pane(script_path, agent_name, terminal_id) -> bool
    # Create new tmux window
    # Send execution command
    # Monitor for completion
```

**Tmux Session Structure:**

```
Session: agents-{run_id}
├── Window agent-1 (Diagnostician)
│   └── Running: python diagnostician_script.py
├── Window agent-2 (BugFixer)
│   └── Running: python bug_fixer_script.py
└── Window agent-3 (Reviewer)
    └── Running: python reviewer_script.py
```

---

### 4. CLI Entry Point (`.claude/workspace_cli/cli.py`)

**Purpose:** Command-line interface

**Commands:**
```
coding-agent-workspace solve "task"
coding-agent-workspace analyze "code"
coding-agent-workspace review "changes"
coding-agent-workspace plan "improvements"
coding-agent-workspace fix "issues"
```

---

## Execution Flow

### Complete Workflow Example

**Command:** `coding-agent-workspace solve "find security issues"`

**Step 1: CLI Parsing**
```
User input → CLI parses command and task
```

**Step 2: Team Leader Initialization**
```
Team Leader creates:
  - Run ID: a1b2c3d4
  - Tmux session: agents-a1b2c3d4
  - Communication channel
```

**Step 3: Task Classification**
```
Task: "find security issues"
↓
Pattern matching against TASK_PATTERNS
↓
Classification: "security"
↓
Output: [*] [TEAM_LEADER] Task classified: security
```

**Step 4: Agent Selection**
```
Task type: security
↓
Look up agent mapping
↓
Selected agents: [diagnostician, reviewer]
↓
Output: [*] [TEAM_LEADER] Selected agents: diagnostician, reviewer
```

**Step 5: Workflow Building**
```
Create execution steps:
  Step 1: Run diagnostician
  Step 2: Run reviewer with diagnostician's findings
↓
Output: [*] [TEAM_LEADER] Workflow ready for execution
```

**Step 6: Agent Execution**
```
For each agent:
  1. Create Python script
  2. Open tmux window
  3. Send execution command
  4. Collect results

Diagnostician:
  [i] [DIAGNOSTICIAN] Agent initialized
  [SCAN_START] Scanning Python files
  [!] CRITICAL: Hardcoded credentials detected in auth.py
  [ANALYSIS COMPLETE] Found 3 issues

Reviewer:
  [i] [REVIEWER] Agent initialized
  [VALIDATE_START] Starting validation
  [FINAL SCORE] 72% - NEEDS_REVIEW
```

**Step 7: Results Aggregation**
```
Collect all outputs
↓
Save to: .agent-workspace/runs/a1b2c3d4.json
↓
Display summary
```

**Step 8: Completion**
```
[*] [TEAM_LEADER] All agents completed
Results saved to: .agent-workspace/runs/a1b2c3d4.json

User can view results:
  - In tmux: tmux attach-session -t agents-a1b2c3d4
  - In file: cat .agent-workspace/runs/a1b2c3d4.json
```

---

## Terminal Management (Tmux)

### Session Lifecycle

1. **Creation** - Tmux session created on Team Leader initialization
2. **Window Creation** - Each agent gets its own window
3. **Execution** - Scripts execute in windows via tmux send-keys
4. **Persistence** - Windows remain open for inspection
5. **Cleanup** - User kills session manually when done

### Tmux Commands Used

```bash
# Create session
tmux new-session -d -s agents-{run_id} -x 200 -y 50

# Create window
tmux new-window -t agents-{run_id} -n agent-1

# Send command
tmux send-keys -t agents-{run_id}:agent-1 "python script.py" Enter

# List sessions
tmux list-sessions

# Attach to monitor
tmux attach-session -t agents-{run_id}
```

### Benefits of Tmux Approach

| Aspect | Benefit |
|--------|---------|
| **Unified** | Single session instead of scattered windows |
| **Organized** | Named windows for each agent |
| **Persistent** | Panes remain after execution for inspection |
| **Cross-platform** | Works on Linux, macOS, Windows (WSL) |
| **Scalable** | Easy to add more agents (more windows) |
| **Scriptable** | Can control via tmux commands |

---

## Task Classification

### Mapping Tasks to Agents

```python
def _get_agents_for_type(task_type: str) -> list:
    mapping = {
        "security": ["diagnostician", "reviewer"],
        "bug_analysis": ["diagnostician", "bug_fixer", "reviewer"],
        "performance": ["diagnostician", "reviewer"],
        "quality": ["diagnostician", "reviewer"],
        "general": ["diagnostician", "reviewer"],
    }
    return mapping.get(task_type, mapping["general"])
```

### Task Pattern Examples

```python
# Security-related keywords
"security" → ["security", "vulnerabilities", "threat", ...]

# Bug-related keywords
"bug_analysis" → ["bug", "error", "crash", "fix", ...]

# Performance-related keywords
"performance" → ["slow", "optimize", "efficient", ...]

# Quality-related keywords
"quality" → ["review", "refactor", "design", ...]
```

---

## Agent Coordination

### Parallel Execution

Agents execute **independently and simultaneously**:

```
Timeline:
T0: Diagnostician starts
    │ BugFixer starts
    │ │ Reviewer starts
    │ │ │
T1: │ │ │ Diagnostician analyzing (1-2s)
T2: │ │ │ BugFixer planning (1-2s)
T3: │ │ │ Reviewer validating (2-3s)
T4: ✓ ✓ ✓ All complete

Total time: ~3-5s (parallel, not sequential)
```

### Result Aggregation

```python
def _execute_workflow(...):
    execution_results = []
    
    for agent_name in agents:
        result = self._spawn_agent(agent_name, task)
        execution_results.append(result)
    
    # Aggregate all results
    final_result = {
        "agent_outputs": {
            "diagnostician": {...},
            "bug_fixer": {...},
            "reviewer": {...}
        },
        "status": "execution_complete"
    }
    
    return final_result
```

---

## Data Flow

### Input → Processing → Output

```
INPUT PHASE:
  User Command
    ↓
  CLI Parsing
    ↓
  Task Description

PROCESSING PHASE:
  Task Classification
    ↓
  Agent Selection
    ↓
  Workflow Building
    ↓
  Tmux Session Creation
    ↓
  Agent Execution (parallel)
    ├─ Diagnostician: File analysis
    ├─ BugFixer: Fix planning
    └─ Reviewer: Validation
    ↓
  Result Collection
    ↓
  Output Formatting

OUTPUT PHASE:
  Results Dictionary
    ↓
  JSON Serialization
    ↓
  File Storage (.agent-workspace/runs/{run_id}.json)
    ↓
  User Display (console + tmux windows)
```

### Result Structure

```python
{
    "success": True,
    "task": "find security issues",
    "task_type": "security",
    "response": "Team Leader successfully executed security workflow",
    "workflow_type": "Security Review",
    
    "agent_execution_results": [
        {
            "success": True,
            "agent": "diagnostician",
            "findings": [...],
            "status": "analysis_complete"
        },
        {
            "success": True,
            "agent": "reviewer",
            "score": 72,
            "approval": "NEEDS_REVIEW",
            "status": "review_complete"
        }
    ],
    
    "status": "execution_complete",
    "timestamp": "2026-07-29T16:30:00.000000"
}
```

---

## Configuration

### System-Level Configuration

**`.claude/settings.json`:**

```json
{
  "theme": "dark",
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "CLAUDE_AGENT_COMMUNICATION_ENABLED": "1",
    "INTERACTIVE_MODE_ENABLED": "1"
  },
  "preferences": {
    "terminalManager": "tmux",
    "tmuxSessionPrefix": "agents-",
    "tmuxAutoAttach": false
  }
}
```

### Tmux Configuration

**Session Defaults:**
```python
session_dimensions = {
    "width": 200,
    "height": 50
}

window_naming = "agent-{sequence_number}"

session_naming = "agents-{run_id}"
```

### Package Configuration

**`pyproject.toml`:**
```toml
[project]
name = "coding-agent-workspace"
version = "0.3.0"

[tool.setuptools]
packages = [
    "workspace_cli",
    "claude",
    "claude.agents",
    "claude.agents.technical",
    "claude.agents.business",
    "claude.tools"
]
package-dir = {"claude" = ".claude"}
```

---

## Extensibility

### Adding a New Agent

1. Create agent file in `.claude/agents/technical/new_agent.py`
2. Implement `execute(task, run_id)` method
3. Update Team Leader's agent mapping
4. Agent automatically gets tmux window

### Adding Task Patterns

```python
# In team_leader.py TASK_PATTERNS
"custom_analysis": [
    "keyword1", "keyword2", "keyword3"
]

# In agent selection mapping
"custom_analysis": ["custom_agent"]
```

### Adding Tools

Create in `.claude/tools/`:
```python
def custom_tool():
    """Tool implementation"""
    pass
```

---

## Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Task Classification | <10ms | Pattern matching |
| Workflow Building | <10ms | Template-based |
| Tmux Session Create | ~50ms | OS-dependent |
| Diagnostician Analyze | ~1-2s | File scanning |
| BugFixer Plan | ~1-2s | Strategy building |
| Reviewer Validate | ~2-3s | Validation checks |
| **Total Execution** | **~3-5s** | Parallel, not sequential |

---

## Debugging

### View Execution Details

```bash
# Attach to tmux session
tmux attach-session -t agents-{run_id}

# Navigate between agents
Ctrl+B 0  # First agent
Ctrl+B 1  # Second agent
Ctrl+B 2  # Third agent

# See captured output
tmux capture-pane -t agents-{run_id}:0 -p
```

### Check Results

```bash
# List all executions
ls .agent-workspace/runs/

# View latest results
cat .agent-workspace/runs/$(ls -t .agent-workspace/runs | head -1)

# Pretty print JSON
python -m json.tool .agent-workspace/runs/{run_id}.json
```

---

## Summary

The Coding Agent Workspace architecture provides:

✅ **Coordinated Execution** - Team Leader orchestrates agents  
✅ **Parallel Processing** - Agents work simultaneously  
✅ **Clean Code** - No boilerplate, direct execution  
✅ **Modern Tmux** - Organized terminal management  
✅ **Simple Messaging** - Direct print output  
✅ **Extensible Design** - Easy to add agents and tasks  
✅ **Cross-platform** - Works on Linux, macOS, Windows (WSL)

---

**Version:** 0.3.0  
**Last Updated:** 2026-07-29  
**Status:** Production-Ready

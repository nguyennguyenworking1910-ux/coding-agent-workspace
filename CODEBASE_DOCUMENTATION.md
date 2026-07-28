# Coding Agent Workspace - Comprehensive Codebase Documentation

**Last Updated:** 2026-07-23  
**Version:** 0.1.0  
**Purpose:** Complete guide to understanding and modifying the coding-agent-workspace system

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Directory Structure](#directory-structure)
4. [Core Modules](#core-modules)
5. [Agent System](#agent-system)
6. [Class Reference](#class-reference)
7. [Function Reference](#function-reference)
8. [How to Extend](#how-to-extend)
9. [How to Modify](#how-to-modify)
10. [Configuration Guide](#configuration-guide)

---

## Project Overview

**What is it?**
The Coding Agent Workspace is a CLI tool that coordinates multiple Claude Code agents to solve complex tasks. It uses a team leader pattern where:
- A **TeamLeaderAgent** receives a task
- It classifies the task type
- It determines which specialist agents are needed
- It spawns and executes agents in sequence
- It returns aggregated results

**Key Features:**
- Multi-agent orchestration
- Task classification (security, bug_analysis, performance, quality, data_operations, general)
- Workflow planning and execution
- Agent result aggregation
- Run persistence (saves to `.agent-workspace/runs/`)
- Experimental mode with detailed tracing

**Technology Stack:**
- Python 3.9+
- Claude API integration
- Subprocess-based Claude Code CLI invocation
- Threading for concurrent I/O

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User Input (CLI)                          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              AgentOrchestrator (cli.py)                      │
│  - Parses commands (solve, task, list-missions, etc.)        │
│  - Creates run IDs                                           │
│  - Persists results to filesystem                            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│          TeamLeaderAgent (.claude/agents/technical/)         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 1. _classify_task() - Task type detection              │ │
│  │ 2. _determine_agents() - Choose specialist agents      │ │
│  │ 3. _build_workflow() - Plan execution steps            │ │
│  │ 4. _execute_workflow() - Run agents in sequence        │ │
│  │ 5. _spawn_agent() - Instantiate & execute each agent   │ │
│  └────────────────────────────────────────────────────────┘ │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┼────────────┬────────────┐
        │            │            │            │
        ▼            ▼            ▼            ▼
    ┌────────┐  ┌────────┐  ┌────────┐  ┌──────────┐
    │Diagnos-│  │Bug Fix-│  │Review- │  │   Data   │
    │tician  │  │ er     │  │ er     │  │Operations│
    │(read)  │  │(write) │  │(read)  │  │(specialized)
    └────────┘  └────────┘  └────────┘  └──────────┘
        │            │            │            │
        │            ▼            │            │
        │      (Modifies Files)   │            │
        │                         │            │
        └────────────┬────────────┼────────────┘
                     │            │
                     ▼            ▼
              [Results Aggregation]
                     │
                     ▼
            [User Review & Commit]
```

---

## Directory Structure

```
coding-agent-workspace/
├── coding_agent_workspace/          # Main Python package
│   ├── __init__.py                  # Package exports
│   ├── cli.py                       # CLI and orchestrator (main entry point)
│   └── claude_provider.py           # Claude Code subprocess wrapper
│
├── .claude/                         # Agent configuration directory
│   ├── agents/                      # Agent implementations
│   │   ├── technical/               # Technical agents
│   │   │   ├── team_leader.py      # Main orchestrator agent
│   │   │   ├── diagnostician.py    # Code analyzer agent
│   │   │   ├── bug_fixer.py        # Implementation agent
│   │   │   ├── reviewer.py         # Validation agent
│   │   │   ├── orchestrator.py     # Agent utilities
│   │   │   └── __init__.py         # Exports
│   │   ├── business/                # Business logic agents
│   │   │   └── group_sale_manager.py
│   │   └── __init__.py
│   │
│   ├── tools/                       # Shared tools
│   │   ├── thought.py              # Thinking tool
│   │   ├── query_executor.py       # Database query tool
│   │   └── __init__.py
│   │
│   ├── docs/                        # Documentation
│   │   ├── AGENTS.md               # Agent documentation
│   │   └── EXPERIMENTAL_FEATURES.md
│   │
│   ├── config.py                    # Configuration loading
│   ├── settings.json                # Settings (JSON)
│   ├── settings.local.json          # Local overrides
│   └── agents.json                  # Agent registry
│
├── .agent-workspace/                # Runtime directory (created at runtime)
│   └── runs/                        # Execution logs
│       ├── run-2026-07-23T15-*.json
│       └── ... (one file per execution)
│
├── pyproject.toml                   # Python package config
├── CODEBASE_DOCUMENTATION.md        # This file
└── README.md

```

---

## Core Modules

### 1. `coding_agent_workspace/__init__.py`

**Purpose:** Package initialization and exports

**Content:**
```python
from .cli import main
from .claude_provider import run_claude, ClaudeError

__version__ = "0.1.0"
__all__ = ["main", "run_claude", "ClaudeError"]
```

**What it does:**
- Exports main entry points for external use
- Sets version number
- Defines public API

**How to modify:**
- Add new exports: `from .new_module import NewClass`
- Update version: Change `__version__`

---

### 2. `coding_agent_workspace/claude_provider.py`

**Purpose:** Wrapper for Claude Code CLI subprocess execution

**Key Classes:**

#### `ClaudeError` (Exception Class)
```python
class ClaudeError(RuntimeError):
    """Raised when the Claude Code CLI cannot start or exits non-zero."""
```
- Inherits from `RuntimeError`
- Used for error handling when Claude CLI fails

**Key Functions:**

#### `run_claude(prompt, tools, permission_mode, allowed_tools, working_directory, stream, output_line_handler)`

**Parameters:**
- `prompt` (str): The prompt to send to Claude
- `tools` (List[str]): Available tools (e.g., `["read", "grep"]`)
- `permission_mode` (str, default="default"): Permission level (`default`, `plan`, `auto`, `bypassPermissions`)
- `allowed_tools` (Optional[List[str]]): Explicit tool allowlist
- `working_directory` (Optional[str]): Working directory for subprocess
- `stream` (bool, default=True): Live output streaming
- `output_line_handler` (Optional[Callable]): Custom output processor function

**Returns:** 
- `str`: Full text response from Claude

**How it works:**
1. Builds subprocess command: `claude --print --tools ... --permission-mode ...`
2. Starts process with `subprocess.Popen()`
3. Sends prompt via stdin
4. Reads stdout in 4KB chunks (for streaming)
5. Drains stderr on background thread (prevent deadlock)
6. Retries up to 5 times with exponential backoff (2^attempt seconds)
7. Returns full output or raises `ClaudeError`

**Example Usage:**
```python
result = run_claude(
    prompt="Analyze this code",
    tools=["read", "grep"],
    permission_mode="default",
    stream=True
)
```

**How to modify:**
- Change retry count: Modify `max_retries = 5` (line 59)
- Change buffer size: Modify `4096` in `chunk = process.stdout.read(4096)` (line 117)
- Add new CLI arguments: Add to `args` list (lines 41-50)

---

### 3. `coding_agent_workspace/cli.py`

**Purpose:** Command-line interface and task orchestration

**Key Classes:**

#### `AgentOrchestrator`

**Purpose:** Coordinates agent task execution

**Methods:**

##### `__init__(workspace_dir: Optional[str] = None)`
- Creates workspace directory at `workspace_dir` or `.agent-workspace`
- Creates `runs/` subdirectory for persisting results

```python
def __init__(self, workspace_dir: Optional[str] = None):
    self.workspace_dir = Path(workspace_dir or ".agent-workspace")
    self.workspace_dir.mkdir(exist_ok=True)
    self.runs_dir = self.workspace_dir / "runs"
    self.runs_dir.mkdir(exist_ok=True)
```

##### `create_run_id() -> str`
- Generates unique identifier from current timestamp
- Format: `run-2026-07-23T15-39-05.074239`
- Used for tracking execution runs

```python
def create_run_id(self) -> str:
    timestamp = datetime.now().isoformat().replace(":", "-")
    return f"run-{timestamp}"
```

##### `save_mission(run_id: str, task: str, result: str) -> Path`
- Persists execution results to JSON file
- Location: `.agent-workspace/runs/{run_id}.json`
- Contains: `run_id`, `timestamp`, `task`, `result`

```python
def save_mission(self, run_id: str, task: str, result: str) -> Path:
    mission = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "task": task,
        "result": result
    }
    mission_file = self.runs_dir / f"{run_id}.json"
    mission_file.write_text(json.dumps(mission, indent=2))
    return mission_file
```

##### `execute_solve(task: str) -> Dict[str, Any]`
- Main entry point for task execution
- Creates TeamLeaderAgent instance
- Executes task through agent team
- Formats and saves results

**Steps:**
1. Create unique `run_id`
2. Check if TeamLeaderAgent is available
3. Instantiate `TeamLeaderAgent()`
4. Call `team_leader.execute(task)`
5. Format output with agent info and workflow steps
6. Save mission to JSON
7. Return success/failure dict

**Returns:**
```python
{
    "success": bool,
    "run_id": str,
    "task": str,
    "result": str,           # Formatted output
    "status": "completed" or "failed"
}
```

##### `execute_task(task: str, use_team_leader: bool = True) -> Dict[str, Any]`
- Alternative execution path using Claude directly
- Can run with or without team leader coordination
- Calls `run_claude()` with specified tools

**Parameters:**
- `task`: Task description
- `use_team_leader`: Whether to use team leader prompt template

**CLI Commands:**

The CLI supports these commands (from `main()` function):
```
Usage: python -m coding_agent_workspace <command> [args]

Commands:
  solve <task>          - Solve a task using team leader
  task <task>           - Execute task without team leader
  list-missions         - List all saved missions
  get-mission <run_id>  - Get specific mission details
  health                - Check system health
```

**How to add a new command:**
1. Add argument parser in `main()` function
2. Create new method in `AgentOrchestrator`
3. Handle in `if args.command == "your_command"` block

---

## Agent System

### Overview

The agent system uses a **team leader pattern**:
1. **TeamLeaderAgent** receives task
2. Classifies task type (security, bug_analysis, performance, quality, data_operations, general)
3. Determines needed agents (diagnostician, bug_fixer, reviewer, etc.)
4. Builds workflow as sequence of steps
5. Executes agents in sequence
6. Aggregates and returns results

### Agent Types

#### 1. DiagnosticianAgent

**File:** `.claude/agents/technical/diagnostician.py`

**Purpose:** Code analysis and issue detection

**Modes:** Read-only  
**Tools Available:** thought

**Interface:**
```python
class DiagnosticianAgent:
    def __init__(self)
    def _init_tools(self)
    def execute(task: str) -> dict
```

**execute() Method:**
- Input: Task description (string)
- Process: Uses thought tool to analyze
- Output: 
  ```python
  {
      "success": bool,
      "agent": "diagnostician",
      "task": str,
      "response": str,
      "thinking": dict,           # Analysis result
      "findings": list,           # Issues found
      "tools_used": list,
      "status": "analysis_complete"
  }
  ```

**How to customize:**
- Modify analysis types in `execute()` method
- Add new findings categories
- Change thought tool prompts

#### 2. BugFixerAgent

**File:** `.claude/agents/technical/bug_fixer.py`

**Purpose:** Implement fixes and code changes

**Modes:** Write access to working tree  
**Tools Available:** thought

**Interface:**
```python
class BugFixerAgent:
    def __init__(self)
    def _init_tools(self)
    def execute(task: str) -> dict
```

**execute() Method:**
- Input: Fix task description
- Process: Plans and applies fixes
- Output:
  ```python
  {
      "success": bool,
      "agent": "bug_fixer",
      "task": str,
      "response": str,
      "thinking": dict,           # Fix plan
      "changes": list,            # Code changes
      "files_modified": list,
      "tools_used": list,
      "status": "ready_to_fix"
  }
  ```

**Note:** Currently does not actually write files - only plans  
**To enable writes:**
1. Add file write methods
2. Integrate with file system operations
3. Track changes for diff generation

#### 3. ReviewerAgent

**File:** `.claude/agents/technical/reviewer.py`

**Purpose:** Validate changes and quality assurance

**Modes:** Read-only  
**Tools Available:** thought

**Interface:**
```python
class ReviewerAgent:
    def __init__(self)
    def _init_tools(self)
    def execute(task: str) -> dict
```

**execute() Method:**
- Input: Review task description
- Process: Evaluates code quality, functionality, best practices
- Output:
  ```python
  {
      "success": bool,
      "agent": "reviewer",
      "task": str,
      "response": str,
      "thinking": dict,           # Evaluation
      "issues": list,             # Issues found
      "approval": "pending",      # or "approved"/"rejected"
      "tools_used": list,
      "status": "review_complete"
  }
  ```

---

### TeamLeaderAgent (Main Orchestrator)

**File:** `.claude/agents/technical/team_leader.py`

**Purpose:** Main coordinator that plans and executes workflows

**Key Attributes:**
```python
self.name = "team_leader"
self.type = "coordinator"
self.mode = "read-only"
self.tools = ["thought"]
self.experimental_mode = bool  # From config
self.trace_id = str            # UUID for tracking
self.execution_log = list      # Event log
```

**Task Classification Patterns:**

```python
TASK_PATTERNS = {
    "security": ["security", "vulnerabilities", "exploit", "breach", ...],
    "bug_analysis": ["bug", "error", "issue", "problem", ...],
    "performance": ["performance", "slow", "memory", "leak", ...],
    "quality": ["quality", "review", "validate", "test", ...],
    "data_operations": ["query", "bigquery", "data", "aggregate", ...],
}
```

**Task Type → Agent Routing:**
```
security        → [diagnostician, reviewer]
bug_analysis    → [diagnostician, bug_fixer, reviewer]
performance     → [diagnostician, reviewer]
quality         → [diagnostician, reviewer]
data_operations → [group_sale_manager]
general         → [diagnostician, reviewer]  (default)
```

**Key Methods:**

##### `execute(task: str) -> dict`

**Flow:**
1. Classify task type
2. Plan using thought tool
3. Determine agents needed
4. Build workflow
5. Execute workflow with agents
6. Return aggregated results

**Returns:**
```python
{
    "success": bool,
    "agent": "team_leader",
    "task": str,
    "task_type": str,
    "response": str,
    "workflow_type": str,
    "agent_execution_results": list,    # Results from each agent
    "agent_outputs": dict,              # {agent_name: result}
    "status": "execution_complete",
    "tools_used": list,
    "trace_id": str,                    # (if experimental mode)
    "execution_log": list,              # (if experimental mode)
    "experimental_mode": bool
}
```

##### `_classify_task(task: str) -> str`

**Input:** Task description  
**Process:** Check keywords against TASK_PATTERNS  
**Output:** Task type (security, bug_analysis, performance, quality, data_operations, or general)

```python
def _classify_task(self, task: str) -> str:
    task_lower = task.lower()
    for task_type, keywords in self.TASK_PATTERNS.items():
        if any(keyword in task_lower for keyword in keywords):
            return task_type
    return "general"
```

**How to add new task type:**
1. Add keyword list to `TASK_PATTERNS` dict
2. Add routing logic in `_determine_agents()`
3. Add task descriptions in helper methods

##### `_determine_agents(task_type: str, task: str) -> list`

**Input:** Task type and description  
**Output:** List of agent names needed  
**Logic:** Returns list based on task_type

**To customize:**
```python
if task_type == "custom_type":
    agents = ["diagnostician", "custom_agent"]
```

##### `_build_workflow(task, task_type, agents_needed, thinking) -> dict`

**Purpose:** Create workflow execution plan  
**Returns:** Workflow dict with steps and agents

##### `_execute_workflow(task, task_type, workflow, agents_needed) -> dict`

**Purpose:** Actually run agents in sequence

**Steps:**
1. Loop through workflow steps
2. For each step, call `_spawn_agent(agent_name, task)`
3. Store results and update context
4. Aggregate all results

##### `_spawn_agent(agent_name: str, task: str) -> dict`

**Purpose:** Instantiate and execute single agent

**Logic:**
```python
if agent_name == "diagnostician":
    agent = DiagnosticianAgent()
elif agent_name == "bug_fixer":
    agent = BugFixerAgent()
elif agent_name == "reviewer":
    agent = ReviewerAgent()
else:
    return {"success": False, "error": "Unknown agent"}

result = agent.execute(task)
return result
```

**Error Handling:** Returns error dict if agent instantiation fails

##### `_log_event(event_type: str, message: str, data: dict = None)`

**Purpose:** Log events for debugging (experimental mode only)

**Event Types:**
- `INIT`: Initialization
- `EXECUTE`: Task received
- `CLASSIFY`: Task classification
- `PLAN`: Planning complete
- `AGENTS_DETERMINED`: Agents identified
- `WORKFLOW_BUILT`: Workflow created
- `EXECUTION_START`: Execution begins
- `SPAWN_AGENT`: Agent spawning
- `AGENT_EXECUTED`: Agent completed
- `AGENT_RESULT`: Agent result received
- `EXECUTION_COMPLETE`: All done
- `AGENT_ERROR`: Agent error

**Output Format:**
```
[2026-07-23T15:39:05.082936] [TRACE:6e52ee0c] [EVENT_TYPE] message
```

---

## Class Reference

### Complete Class Hierarchy

```
Exception
├── RuntimeError
│   └── ClaudeError

object
├── AgentOrchestrator
├── TeamLeaderAgent
├── DiagnosticianAgent
├── BugFixerAgent
├── ReviewerAgent
└── Tool Classes (thought, query_executor, etc.)
```

### Method Signatures

```python
# AgentOrchestrator
def __init__(workspace_dir: Optional[str] = None) -> None
def create_run_id() -> str
def save_mission(run_id: str, task: str, result: str) -> Path
def execute_solve(task: str) -> Dict[str, Any]
def execute_task(task: str, use_team_leader: bool = True) -> Dict[str, Any]

# TeamLeaderAgent
def __init__() -> None
def execute(task: str) -> dict
def _classify_task(task: str) -> str
def _determine_agents(task_type: str, task: str) -> list
def _build_workflow(task: str, task_type: str, agents_needed: list, thinking: dict) -> dict
def _execute_workflow(task: str, task_type: str, workflow: dict, agents_needed: list) -> dict
def _spawn_agent(agent_name: str, task: str) -> dict
def _log_event(event_type: str, message: str, data: dict = None) -> None
def _create_workflow_steps(task_type: str, agents: list) -> list
def _get_workflow_name(task_type: str) -> str
def _get_agent_role(agent: str) -> str
def _get_diagnostician_task(task_type: str) -> str
def _get_diagnostician_focus(task_type: str) -> list
def _get_reviewer_focus(task_type: str) -> list

# Agent Classes (similar interface)
def __init__() -> None
def _init_tools() -> None
def execute(task: str) -> dict
```

---

## Function Reference

### run_claude() Details

**Signature:**
```python
def run_claude(
    prompt: str,
    tools: List[str],
    permission_mode: str = "default",
    allowed_tools: Optional[List[str]] = None,
    working_directory: Optional[str] = None,
    stream: bool = True,
    output_line_handler: Optional[Callable[[str], None]] = None,
) -> str
```

**Parameter Details:**

| Param | Type | Default | Purpose |
|-------|------|---------|---------|
| prompt | str | (required) | Input prompt for Claude |
| tools | List[str] | (required) | Available tools: read, grep, edit, write, bash, etc. |
| permission_mode | str | "default" | How strict permissions are: default, plan, auto, bypassPermissions |
| allowed_tools | Optional[List[str]] | None | Explicit whitelist of tools |
| working_directory | Optional[str] | None | Working directory for subprocess |
| stream | bool | True | Live output streaming |
| output_line_handler | Optional[Callable] | None | Function to process each output chunk |

**Return Value:**
- `str`: Full text response (concatenated from all chunks)
- Raises: `ClaudeError` if process fails

**Internal Logic:**

1. **Argument Building** (lines 41-54):
   ```python
   args = ["claude", "--print", "--tools", ",".join(tools), ...]
   ```

2. **Process Management** (lines 64-74):
   - Retry loop with exponential backoff
   - Creates subprocess with Popen
   - Sets encoding to UTF-8

3. **I/O Handling** (lines 85-127):
   - Sends prompt via stdin
   - Reads stdout in 4KB chunks
   - Drains stderr on background thread
   - Returns concatenated output

4. **Error Handling** (lines 135-149):
   - Checks process exit code
   - Retries on failure
   - Raises ClaudeError on final failure

---

## How to Extend

### Adding a New Agent Type

**Step 1: Create Agent Class**

File: `.claude/agents/technical/new_agent.py`

```python
from tools import get_tool

class NewAgent:
    """Description of what this agent does."""
    
    def __init__(self):
        self.name = "new_agent"
        self.type = "analyzer"  # or "implementer", "validator"
        self.mode = "read-only"  # or "write"
        self.tools = ["thought"]  # Add other tools as needed
        self._init_tools()
    
    def _init_tools(self):
        """Initialize tools."""
        self.thought_tool = get_tool("thought")()
    
    def execute(self, task: str) -> dict:
        """Execute agent task.
        
        Args:
            task: Task description
        
        Returns:
            Result dict with status, findings, etc.
        """
        # Your implementation here
        result = self.thought_tool.analyze(task)
        
        return {
            "success": True,
            "agent": "new_agent",
            "task": task,
            "response": f"NewAgent processing: {task}",
            "thinking": result,
            "findings": [],
            "tools_used": self.tools,
            "status": "complete"
        }
```

**Step 2: Update TeamLeaderAgent**

In `.claude/agents/technical/team_leader.py`:

```python
# Add import
from .new_agent import NewAgent

# Add to TASK_PATTERNS (if needed)
TASK_PATTERNS = {
    # ... existing patterns ...
    "new_category": ["keyword1", "keyword2", ...],
}

# Update _determine_agents()
def _determine_agents(self, task_type: str, task: str) -> list:
    agents = []
    # ... existing logic ...
    elif task_type == "new_category":
        agents = ["new_agent", "reviewer"]
    # ...
    return agents

# Update _spawn_agent()
def _spawn_agent(self, agent_name: str, task: str) -> dict:
    # ... existing code ...
    elif agent_name == "new_agent":
        agent = NewAgent()
    # ...

# Add helper methods if needed
def _get_new_agent_task(self, task_type: str) -> str:
    tasks = {
        "new_category": "New agent specific task",
    }
    return tasks.get(task_type, "Default task")
```

### Adding a New Tool

**File:** `.claude/tools/new_tool.py`

```python
class NewTool:
    """Implementation of new tool."""
    
    def __init__(self):
        self.name = "new_tool"
    
    def execute(self, **kwargs) -> dict:
        """Execute tool action."""
        return {"success": True, "result": "data"}
```

**Register in:** `.claude/tools/__init__.py`

```python
from .new_tool import NewTool

def get_tool(name: str):
    tools = {
        "thought": ThoughtTool,
        "new_tool": NewTool,
    }
    return tools.get(name)
```

### Adding a New CLI Command

**In `coding_agent_workspace/cli.py`:**

```python
def main():
    # ... existing parser setup ...
    
    subparsers = parser.add_subparsers(dest="command")
    
    # Add your command
    solve_parser = subparsers.add_parser("your_command", help="Description")
    solve_parser.add_argument("arg1", help="Argument 1")
    solve_parser.add_argument("--option", help="Optional argument")
    
    args = parser.parse_args()
    orchestrator = AgentOrchestrator()
    
    # Add handler
    if args.command == "your_command":
        result = orchestrator.your_command(args.arg1, args.option)
        print(json.dumps(result, indent=2))
```

---

## How to Modify

### Modifying Agent Behavior

**Location:** `.claude/agents/technical/{agent_name}.py`

**Example: Change Diagnostician Focus Areas**

```python
# Current
def execute(self, task: str) -> dict:
    analysis_result = self.thought_tool.analyze(task)

# Modified with custom focus
def execute(self, task: str) -> dict:
    custom_prompt = f"""Analyze for:
    1. Your custom focus 1
    2. Your custom focus 2
    
    Task: {task}"""
    
    analysis_result = self.thought_tool.analyze(custom_prompt)
```

### Modifying Task Classification

**File:** `.claude/agents/technical/team_leader.py`

```python
# Add new keywords to existing category
TASK_PATTERNS = {
    "security": [
        # ... existing ...
        "new_security_keyword"  # Add this
    ],
    # OR create new category
    "custom_type": ["custom_keyword1", "custom_keyword2"],
}
```

### Modifying Agent Routing

```python
def _determine_agents(self, task_type: str, task: str) -> list:
    agents = []
    
    if task_type == "bug_analysis":
        # Default: diagnostician, bug_fixer, reviewer
        # Change to just diagnostician:
        agents = ["diagnostician"]
        
        # Or add custom logic:
        if "critical" in task.lower():
            agents = ["diagnostician", "bug_fixer", "reviewer"]
        else:
            agents = ["diagnostician", "reviewer"]
    
    return agents
```

### Modifying Workflow Order

```python
def _create_workflow_steps(self, task_type: str, agents: list) -> list:
    steps = []
    step_num = 1
    
    # Current order: diagnostician → bug_fixer → reviewer
    # Change order: reviewer → diagnostician → bug_fixer
    
    if "reviewer" in agents:  # Moved to first
        steps.append({
            "step": step_num,
            "agent": "reviewer",
            "task": "Initial review",
            "focus": self._get_reviewer_focus(task_type)
        })
        step_num += 1
    
    # ... rest of agents ...
    
    return steps
```

### Modifying Output Format

**File:** `coding_agent_workspace/cli.py`, in `execute_solve()`:

```python
# Current output format
output = f"""
TEAM LEADER EXECUTION REPORT
{'='*60}

Task: {task}
Classification: {result.get('task_type', 'general').upper()}
...
"""

# Custom format example
output = f"""
🚀 EXECUTION RESULTS
{'='*60}
📋 Task: {task}
🔍 Type: {result.get('task_type')}
⚙️ Agents: {', '.join([a['agent'] for a in result.get('spawned_agents', [])])}
...
"""
```

---

## Configuration Guide

### Settings Files

**Location:** `.claude/settings.json` and `.claude/settings.local.json`

**Key Settings:**

```json
{
    "experimental_agent_teams_enabled": true,
    "agent_tracing_enabled": true,
    "structured_logging_enabled": true,
    "max_retries": 5,
    "workspace_dir": ".agent-workspace"
}
```

### Enabling Experimental Mode

**File:** `.claude/config.py`

```python
def get_config():
    """Load configuration."""
    config = Config()
    config.experimental_agent_teams_enabled = True
    return config

def is_experimental_mode():
    """Check if experimental mode is enabled."""
    return get_config().experimental_agent_teams_enabled
```

### Environment Variables

**Control via environment variables:**

```bash
# Enable verbose logging
export DEBUG=true

# Set working directory
export WORKSPACE_DIR=/custom/path

# Set Python encoding
export PYTHONIOENCODING=utf-8
```

---

## Usage Examples

### Running a Simple Task

```bash
python -m coding_agent_workspace solve "Create a tool to search files in docs folder"
```

### Running a Bug Analysis

```bash
python -m coding_agent_workspace solve "Find and fix bugs in the auth system"
```

### Custom Python Usage

```python
from coding_agent_workspace import run_claude, ClaudeError

# Direct Claude invocation
result = run_claude(
    prompt="Analyze this code for security issues",
    tools=["read", "grep"],
    permission_mode="default"
)

print(result)
```

### Agent Team Usage

```python
from .claude.agents.technical.team_leader import TeamLeaderAgent

leader = TeamLeaderAgent()
result = leader.execute("Improve code performance")

print(f"Status: {result['status']}")
print(f"Agents: {[a['agent'] for a in result['spawned_agents']]}")
```

---

## API Summary

### Main Entry Points

```python
# CLI entry point
python -m coding_agent_workspace <command> [args]

# Python API
from coding_agent_workspace import main, run_claude, ClaudeError

# Team Leader API
from .claude.agents.technical.team_leader import TeamLeaderAgent
leader = TeamLeaderAgent()
result = leader.execute(task_description)
```

### Key Data Structures

**Execution Result:**
```python
{
    "success": bool,
    "agent": str,
    "task": str,
    "response": str,
    "thinking": dict,
    "findings": list,
    "status": str,
    "tools_used": list
}
```

**Workflow Definition:**
```python
{
    "task_type": str,
    "workflow_type": str,
    "spawned_agents": [{"agent": str, "role": str}, ...],
    "workflow_steps": [{"step": int, "agent": str, "task": str}, ...],
    "status": "execution_complete"
}
```

---

## Troubleshooting

### Common Issues

**Issue:** Claude Code CLI not found
- **Solution:** Ensure Claude Code is installed: `pip install -g claude` or check PATH

**Issue:** Permission denied errors
- **Solution:** Check permission_mode in run_claude() call

**Issue:** Agents not executing
- **Solution:** Check experimental_agent_teams_enabled in settings.json

**Issue:** Encoding errors
- **Solution:** Set `export PYTHONIOENCODING=utf-8`

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-07-23 | Initial release with team leader, basic agents |
| 0.1.1 | 2026-07-23 | Added agent execution capability to team leader |

---

## Contributing

To extend this system:
1. Add new agent classes following the template
2. Update TeamLeaderAgent routing logic
3. Add documentation for new features
4. Test with various task types
5. Update this documentation

---

**End of Documentation**

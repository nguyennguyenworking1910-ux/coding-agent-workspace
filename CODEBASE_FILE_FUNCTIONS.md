# Codebase File Functions - Complete Analysis

**Updated:** 2026-07-28 (Post-cleanup)  
**Total Python Files:** 20 (4 dead code files removed)  
**Total Size:** ~116KB

---

## 📋 Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [File-by-File Breakdown](#file-by-file-breakdown)
3. [Module Dependencies](#module-dependencies)
4. [Data Flow](#data-flow)
5. [Feature Matrix](#feature-matrix)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     User CLI Entry Point                     │
│                  (coding_agent_workspace)                    │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
    [__init__.py]  [__main__.py]    [cli.py]
                                         │
         ┌───────────────┬───────────────┤
         │               │               │
         ▼               ▼               ▼
    [claude_provider.py] [AgentOrchestrator] [config.py]
         │                     │
         │                     ▼
         │          [TeamLeaderAgent]
         │                     │
         ▼          ┌──────────┼──────────┐
    [Claude CLI]   │          │          │
                   ▼          ▼          ▼
            [Diagnostician] [BugFixer] [Reviewer]
                                  │
                    ┌─────────────┴──────────┬──────────────┐
                    ▼                        ▼              ▼
            [ThoughtTool]          [GroupSaleManager] [Other Tools]
```

---

## File-by-File Breakdown

### CORE CLI PACKAGE: `coding_agent_workspace/`

#### 1. **`__init__.py`** (15 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Package initialization and public API exports
- Makes the package importable as a module

**Exports:**
- `main` - CLI entry point function
- `run_claude` - Execute Claude CLI subprocess
- `ClaudeError` - Exception type
- `__version__` - Package version (0.1.0)

**Dependencies:** 
- Imports from `.cli` and `.claude_provider`

**Function:**
```python
def main() -> int:
    """Main CLI entry point, returns exit code"""

def run_claude(prompt, tools, permission_mode, ...) -> str:
    """Execute Claude Code CLI and return response"""

class ClaudeError(RuntimeError):
    """Custom exception for Claude execution failures"""
```

---

#### 2. **`__main__.py`** (4 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Entry point for `python -m coding_agent_workspace`
- Ensures module can be executed directly

**Function:**
```python
if __name__ == "__main__":
    main()  # Calls cli.main()
```

**Usage:**
```bash
python -m coding_agent_workspace solve "fix the bug"
```

---

#### 3. **`claude_provider.py`** (150 lines)
**Status:** ✅ ACTIVE & CRITICAL

**Purpose:**
- Subprocess wrapper for Claude Code CLI
- Handles process creation, I/O streaming, error handling
- Implements retry logic with exponential backoff

**Key Components:**

```python
class ClaudeError(RuntimeError):
    """Exception raised when Claude CLI fails"""

def run_claude(
    prompt: str,                    # User's prompt
    tools: List[str],              # Available tools (read, grep, etc)
    permission_mode: str = "default",
    allowed_tools: Optional[List[str]] = None,
    working_directory: Optional[str] = None,
    stream: bool = True,
    output_line_handler: Optional[Callable] = None
) -> str:
    """Execute Claude Code CLI and return response"""
```

**Features:**
- ✅ Spawns `claude` CLI as subprocess
- ✅ Feeds prompt via stdin
- ✅ Streams stdout/stderr to terminal
- ✅ Threading for concurrent I/O (prevents deadlock)
- ✅ Retry logic: up to 5 attempts with exponential backoff
- ✅ Handles BrokenPipeError gracefully

**Critical for:**
- All Claude Code execution in the system
- User interaction with agents

---

#### 4. **`cli.py`** (344 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Command-line interface for agent orchestration
- Task routing and execution coordination
- Run persistence to `.agent-workspace/runs/`

**Key Components:**

```python
class AgentOrchestrator:
    """Orchestrates execution of agent tasks"""
    
    def __init__(self, workspace_dir: str = ".agent-workspace")
    def create_run_id() -> str                # Generate unique run ID
    def save_mission(run_id, task, result) -> Path  # Save to JSON
    def execute_solve(task: str) -> Dict     # Direct team leader execution
    def execute_task(task, use_team_leader) -> Dict  # Claude subprocess execution

def create_parser() -> argparse.ArgumentParser
    """Build CLI argument parser"""

def execute_command(args: argparse.Namespace) -> int
    """Execute CLI command, return exit code"""

def main() -> int
    """Main entry point"""
```

**Commands Supported:**
- `solve` - Direct TeamLeaderAgent execution (recommended)
- `analyze` - Code analysis task
- `plan` - Execution planning
- `review` - Code review task
- `fix` - Bug fixing task
- `execute` - Generic task execution

**Example Usage:**
```bash
coding-agent-workspace solve "Find and fix bugs in src/"
coding-agent-workspace analyze "Check code quality"
coding-agent-workspace review "Review my changes"
```

**Features:**
- ✅ Argument parsing with subcommands
- ✅ Workspace directory management
- ✅ Run ID generation (timestamp-based)
- ✅ Mission persistence to JSON
- ✅ Graceful error handling
- ✅ Configuration integration

---

### AGENT SYSTEM: `.claude/`

#### 5. **`config.py`** (141 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Centralized configuration management
- Feature flag handling
- Settings loading from JSON

**Key Components:**

```python
class AgentConfig:
    """Manages agent system configuration"""
    
    def __init__(self, config_file: Optional[str] = None)
    def _find_settings_file() -> str
    def _load_config() -> Dict
    
    # Properties for feature flags:
    @property experimental_agent_teams_enabled: bool
    @property enable_agent_tracing: bool
    @property enable_structured_logging: bool
    @property enable_agent_spawning: bool
    
    def get_features() -> Dict[str, bool]
    def log_config() -> str

def get_config() -> AgentConfig       # Global singleton
def is_experimental_mode() -> bool
```

**Configuration Source:**
- Loads from `.claude/settings.json`
- Environment variables in `env` section
- Fallback to defaults if file not found

**Feature Flags:**
```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "0"  // Set to "1" to enable
  }
}
```

**Used By:**
- CLI for showing configuration
- TeamLeaderAgent for tracing/logging
- All agents for feature detection

---

#### 6. **`__init__.py`** (16 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Agent system package initialization
- Unified access to agents and tools

**Exports:**
- All technical agents: TeamLeaderAgent, DiagnosticianAgent, BugFixerAgent, ReviewerAgent
- All tools: get_tool(), list_tools()
- Registry functions: get_agent(), list_agents()

**Dependencies:**
- Imports from `.agents` and `.tools` subpackages

---

### AGENTS PACKAGE: `.claude/agents/`

#### 7. **`__init__.py`** (54 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Central agent registry and access functions
- Department-based agent organization

**Exports:**
```python
# Agents
TeamLeaderAgent, DiagnosticianAgent, BugFixerAgent, ReviewerAgent, GroupSaleManagerAgent

# Functions
get_agent(name: str) -> Agent Class       # Get agent by name
list_agents() -> List[str]                 # List all agents
get_technical_agent(name: str)
get_business_agent(name: str)
list_technical_agents() -> List[str]
list_business_agents() -> List[str]
```

**Agent Registry:**
```python
AGENTS = {
    "team_leader": TeamLeaderAgent,
    "diagnostician": DiagnosticianAgent,
    "bug_fixer": BugFixerAgent,
    "reviewer": ReviewerAgent,
    "group_sale_manager": GroupSaleManagerAgent,
}
```

---

#### 8. **`technical/__init__.py`** (30 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Technical department agent registry
- Code analysis and quality assurance agents

**Exports:**
- All 4 technical agents
- Department registry and lookup functions

**Agents:**
- `team_leader` - Orchestrator (coordinates other agents)
- `diagnostician` - Code analyzer
- `bug_fixer` - Code implementer
- `reviewer` - Code validator

---

#### 9. **`business/__init__.py`** (21 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Business department agent registry
- Sales operations and data management agents

**Exports:**
- GroupSaleManagerAgent
- Department registry and lookup functions

**Agents:**
- `group_sale_manager` - Sales operations manager (uses BigQuery tools)

---

### TECHNICAL AGENTS: `.claude/agents/technical/`

#### 10. **`team_leader.py`** (478 lines)
**Status:** ✅ ACTIVE & CRITICAL

**Purpose:**
- Main agent orchestrator
- Intelligent task routing and workflow execution
- Coordinates specialist agents (diagnostician, bug_fixer, reviewer)

**Key Components:**

```python
class TeamLeaderAgent:
    """Orchestrator agent that coordinates specialist agents"""
    
    # Task type patterns for routing
    TASK_PATTERNS = {
        "security": [...keywords...],
        "bug_analysis": [...keywords...],
        "performance": [...keywords...],
        "quality": [...keywords...],
        "data_operations": [...keywords...]
    }
    
    # Core methods:
    def execute(task: str) -> Dict              # Main entry point
    def _classify_task(task: str) -> str        # Task type detection
    def _determine_agents(task_type, task) -> List  # Choose agents
    def _build_workflow(task, task_type, agents, thinking) -> Dict  # Plan
    def _execute_workflow(task, task_type, workflow, agents) -> Dict  # Run
    def _spawn_agent(agent_name, task) -> Dict  # Execute single agent
    
    # Helper methods:
    def _create_workflow_steps(task_type, agents) -> List
    def _get_diagnostician_task(task_type) -> str
    def _get_diagnostician_focus(task_type) -> List[str]
    def _get_reviewer_focus(task_type) -> List[str]
```

**Task Classification:**
- **security** - Keywords: vulnerability, exploit, breach, xss, csrf, auth, etc.
- **bug_analysis** - Keywords: bug, error, crash, broken, exception, debug, etc.
- **performance** - Keywords: slow, memory leak, optimization, latency, etc.
- **quality** - Keywords: refactor, design, architecture, pattern, etc.
- **data_operations** - Keywords: query, bigquery, sales, data, aggregate, etc.
- **general** - Default fallback

**Agent Selection Strategy:**
| Task Type | Agents Selected |
|-----------|-----------------|
| security | diagnostician, reviewer |
| bug_analysis | diagnostician, bug_fixer, reviewer |
| performance | diagnostician, reviewer |
| quality | diagnostician, reviewer |
| data_operations | group_sale_manager |
| general | diagnostician, reviewer |

**Execution Flow:**
1. Classify task type based on keywords
2. Determine which agents are needed
3. Build workflow with sequential steps
4. Execute each agent in order
5. Aggregate results
6. Return combined output

**Example Execution:**
```python
leader = TeamLeaderAgent()
result = leader.execute("Fix the bug in the authentication module")
# Returns:
# {
#   "task_type": "bug_analysis",
#   "workflow_type": "Bug Fix Workflow",
#   "spawned_agents": [
#     {"agent": "diagnostician", "role": "Issue Scanner & Analyzer"},
#     {"agent": "bug_fixer", "role": "Implementation Specialist"},
#     {"agent": "reviewer", "role": "Quality Validator"}
#   ],
#   "agent_outputs": {...}
# }
```

---

#### 11. **`diagnostician.py`** (43 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Code analysis and issue detection
- Read-only access
- Uses Thought tool for reasoning

**Key Components:**

```python
class DiagnosticianAgent:
    """Analyzer agent that finds bugs and issues"""
    
    def __init__(self)
    def execute(task: str) -> dict
        # Returns:
        # {
        #   "success": True,
        #   "agent": "diagnostician",
        #   "task": task,
        #   "thinking": {...},
        #   "findings": [],
        #   "status": "analysis_complete"
        # }
```

**Typical Tasks:**
- Find bugs in code
- Identify security vulnerabilities
- Detect performance issues
- Review code quality

**Spawned By:**
- TeamLeaderAgent for most task types
- Part of analysis → fix → review workflow

---

#### 12. **`bug_fixer.py`** (45 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Implement bug fixes and changes
- Write access to working tree
- Uses Thought tool for planning

**Key Components:**

```python
class BugFixerAgent:
    """Implementer agent with write access"""
    
    def __init__(self)
    def execute(task: str) -> dict
        # Returns:
        # {
        #   "success": True,
        #   "agent": "bug_fixer",
        #   "task": task,
        #   "thinking": {...},
        #   "changes": [],
        #   "files_modified": [],
        #   "status": "ready_to_fix"
        # }
```

**Attributes:**
- `has_write_access = True` - Can modify files
- `mode = "write"` - Write permission level

**Typical Tasks:**
- Apply code fixes
- Implement features
- Refactor code

**Spawned By:**
- TeamLeaderAgent only when bug_analysis task type detected
- Always paired with diagnostician (analyze first, fix second)

---

#### 13. **`reviewer.py`** (47 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Validate and review changes
- Read-only access
- Uses Thought tool for evaluation

**Key Components:**

```python
class ReviewerAgent:
    """Validator agent that reviews code changes"""
    
    def __init__(self)
    def execute(task: str) -> dict
        # Returns:
        # {
        #   "success": True,
        #   "agent": "reviewer",
        #   "task": task,
        #   "thinking": {...},
        #   "issues": [],
        #   "approval": "pending",
        #   "status": "review_complete"
        # }
```

**Review Criteria:**
- Code quality
- Functionality
- Best practices

**Typical Tasks:**
- Verify fixes are correct
- Check for regressions
- Validate solutions
- Approve changes

**Spawned By:**
- TeamLeaderAgent for most task types (final validation step)

---

### BUSINESS AGENTS: `.claude/agents/business/`

#### 14. **`group_sale_manager.py`** (50+ lines)
**Status:** ⚠️ PARTIAL (Stub Implementation)

**Purpose:**
- Sales operations management
- BigQuery data access
- Read-write access to data

**Key Components:**

```python
class GroupSaleManagerAgent:
    """Agent for managing group sales with BigQuery access"""
    
    def __init__(self)
    def execute(task: str, context: dict = None) -> dict
    def query_sales(dataset: str, table: str, query_spec: dict) -> dict
    
    # Uses tools:
    - thought_tool
    - schema_reader
    - query_builder
    - query_executor
    - data_fetcher
```

**Status Details:**
- ⚠️ Tool initialization works
- ⚠️ Main execute() method returns mock response
- ❌ BigQuery tools return mock data only
- ❌ No actual database access implemented

**Note:**
See REFACTORING_PLAN.md for implementation options:
1. Complete with real BigQuery
2. Mark as experimental/mock
3. Remove entirely

---

### TOOLS PACKAGE: `.claude/tools/`

#### 15. **`__init__.py`** (32 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Tool system package initialization
- Unified tool registry and access

**Exports:**
```python
# Tool classes
ThoughtTool, SchemaReaderTool, QueryBuilderTool, QueryExecutorTool, DataFetcherTool

# Functions
get_tool(name: str) -> Tool Class
list_tools() -> List[str]
```

**Tool Registry:**
```python
TOOLS = {
    "thought": ThoughtTool,
    "schema_reader": SchemaReaderTool,
    "query_builder": QueryBuilderTool,
    "query_executor": QueryExecutorTool,
    "data_fetcher": DataFetcherTool,
}
```

---

#### 16. **`thought.py`** (98 lines)
**Status:** ✅ ACTIVE & NECESSARY

**Purpose:**
- Reasoning and thinking capability
- Used by all agents for analysis, planning, evaluation

**Key Components:**

```python
class ThoughtTool:
    """Tool for agent reasoning and thinking"""
    
    def execute(thought: str) -> dict
        # Single reasoning step
        # Returns: {"success": True, "type": "reasoning_step", ...}
    
    def analyze(task: str, context: dict = None) -> dict
        # Analyze a task
        # Returns: {"success": True, "type": "analysis", ...}
    
    def plan(goal: str, constraints: list = None) -> dict
        # Create a plan with constraints
        # Returns: {"success": True, "type": "planning", "plan": [...], ...}
    
    def evaluate(statement: str, criteria: list = None) -> dict
        # Evaluate against criteria
        # Returns: {"success": True, "type": "evaluation", ...}
```

**Used By:**
- DiagnosticianAgent for analysis
- BugFixerAgent for planning fixes
- ReviewerAgent for evaluation
- TeamLeaderAgent for task classification
- GroupSaleManagerAgent for task understanding

**Output Format:**
All methods return consistent dictionary format with:
- `success` - Boolean status
- `tool` - "thought"
- `status` - "completed"
- `type` - reasoning_step, analysis, planning, or evaluation

---

#### 17. **`schema_reader.py`** (100+ lines)
**Status:** ⚠️ STUB IMPLEMENTATION

**Purpose:**
- Read and parse BigQuery table schemas
- Extract column metadata
- Support for markdown schema files

**Key Components:**

```python
class SchemaReaderTool:
    """Tool for reading BigQuery table schemas"""
    
    def read_schema_from_file(schema_file: str) -> dict
        # Parse markdown schema file
        
    def get_table_columns(dataset: str, table: str) -> dict
        # Get columns for a specific table
        
    def list_available_schemas() -> dict
        # List all available schema files
        
    def validate_schema_compatibility(schema: dict, required_columns: list) -> dict
        # Validate schema contains required columns
```

**Status Details:**
- ✅ File reading implemented
- ✅ Markdown parsing framework exists
- ❌ Returns mock/empty results
- ❌ No actual BigQuery API calls

**Note:**
See REFACTORING_PLAN.md for implementation options.

---

#### 18. **`query_builder.py`** (100+ lines)
**Status:** ⚠️ STUB IMPLEMENTATION

**Purpose:**
- Build SQL queries dynamically
- Support SELECT, INSERT, aggregate, JOIN queries
- BigQuery syntax

**Key Components:**

```python
class QueryBuilderTool:
    """Tool for building SQL queries"""
    
    def build_select_query(
        dataset, table,
        columns=None,
        where_conditions=None,
        group_by=None,
        order_by=None,
        limit=None
    ) -> dict
        # Build SELECT query
        
    def build_aggregate_query(...)
        # Build aggregation query (SUM, COUNT, AVG, etc)
        
    def build_insert_query(...)
        # Build INSERT query
        
    def build_join_query(...)
        # Build JOIN query
```

**Status Details:**
- ✅ Query construction logic exists
- ✅ Clause building helpers implemented
- ❌ Returns mock SQL strings
- ❌ No actual query execution

---

#### 19. **`query_executor.py`** (100+ lines)
**Status:** ⚠️ STUB IMPLEMENTATION

**Purpose:**
- Execute SQL queries against BigQuery
- Handle query jobs and monitoring
- Validation and dry-run support

**Key Components:**

```python
class QueryExecutorTool:
    """Tool for executing SQL queries"""
    
    def execute_query(sql, project_id=None, use_legacy_sql=False, dry_run=False) -> dict
        # Execute a BigQuery query
        
    def execute_and_fetch(sql, project_id=None, max_results=1000) -> dict
        # Execute and fetch results
        
    def validate_query(sql, ...) -> dict
        # Validate without executing
        
    def cancel_query(job_id) -> dict
        # Cancel running query
        
    def get_job_status(job_id) -> dict
        # Get query job status
        
    def batch_execute_queries(queries) -> dict
        # Execute multiple queries
```

**Status Details:**
- ✅ Interface designed correctly
- ✅ Method signatures complete
- ❌ All methods return mock responses
- ❌ No BigQuery client integration

---

#### 20. **`data_fetcher.py`** (100+ lines)
**Status:** ⚠️ STUB IMPLEMENTATION

**Purpose:**
- Fetch and process BigQuery query results
- Result formatting and conversion
- Pagination support

**Key Components:**

```python
class DataFetcherTool:
    """Tool for fetching BigQuery results"""
    
    def fetch_results(job_id, project_id=None, max_results=1000, page_token=None) -> dict
        # Fetch results from completed query
        
    def fetch_all_results(job_id, project_id=None) -> dict
        # Fetch all results at once
        
    def convert_to_dataframe(job_id, ...) -> dict
        # Convert to pandas DataFrame
        
    def export_results(job_id, format, destination) -> dict
        # Export results to file
        
    def get_result_schema(job_id) -> dict
        # Get schema of results
        
    def filter_results(rows, conditions) -> dict
        # Filter in-memory results
        
    def aggregate_results(rows, aggregations) -> dict
        # Aggregate in-memory results
        
    def get_statistics(rows) -> dict
        # Calculate statistics
```

**Status Details:**
- ✅ Interface fully designed
- ✅ Support for multiple formats
- ❌ All methods return empty mock data
- ❌ No actual data processing

---

## Module Dependencies

### Dependency Graph

```
coding_agent_workspace/
  ├─ cli.py
  │   └─ claude_provider.py
  │   └─ config.py
  │   └─ agents.technical.team_leader
  │
  └─ claude_provider.py (standalone, subprocess wrapper)

.claude/
  ├─ config.py (standalone, configuration)
  │
  ├─ agents/
  │   ├─ __init__.py
  │   │   ├─ technical/__init__.py
  │   │   │   ├─ team_leader.py
  │   │   │   │   ├─ diagnostician.py
  │   │   │   │   ├─ bug_fixer.py
  │   │   │   │   ├─ reviewer.py
  │   │   │   │   └─ tools.thought
  │   │   │   ├─ diagnostician.py
  │   │   │   ├─ bug_fixer.py
  │   │   │   └─ reviewer.py
  │   │   │
  │   │   └─ business/__init__.py
  │   │       └─ group_sale_manager.py
  │   │           ├─ tools.thought
  │   │           ├─ tools.schema_reader
  │   │           ├─ tools.query_builder
  │   │           ├─ tools.query_executor
  │   │           └─ tools.data_fetcher
  │   │
  │   └─ (deleted: orchestrator.py, orchestrator_enhanced.py, workspace.py, terminal_spawner.py)
  │
  └─ tools/
      ├─ __init__.py
      ├─ thought.py (used by all agents)
      ├─ schema_reader.py (used by group_sale_manager)
      ├─ query_builder.py (used by group_sale_manager)
      ├─ query_executor.py (used by group_sale_manager)
      └─ data_fetcher.py (used by group_sale_manager)
```

### Critical Dependency Chain

```
CLI Command
    ↓
  cli.py (AgentOrchestrator)
    ↓
  claude_provider.py (run_claude subprocess)
    OR
  TeamLeaderAgent (direct execution)
    ↓
    ├─ DiagnosticianAgent (analysis)
    ├─ BugFixerAgent (implementation)
    └─ ReviewerAgent (validation)
    
    OR
    
    └─ GroupSaleManagerAgent (data operations)
        ├─ SchemaReaderTool
        ├─ QueryBuilderTool
        ├─ QueryExecutorTool
        └─ DataFetcherTool
    
All agents use:
    └─ ThoughtTool (reasoning)
```

---

## Data Flow

### Command Execution Flow

```
User Input
    ↓
[cli.py:main()]
    ↓
[create_parser() - parse arguments]
    ↓
[execute_command()]
    ├─ If command == "solve":
    │   └─ [AgentOrchestrator.execute_solve(task)]
    │       └─ [TeamLeaderAgent.execute(task)]
    │           ├─ [_classify_task()] → task_type
    │           ├─ [_determine_agents()] → agents_list
    │           ├─ [_build_workflow()] → workflow
    │           └─ [_execute_workflow()]
    │               └─ For each agent in workflow:
    │                   └─ [_spawn_agent()]
    │                       └─ [agent.execute(task)]
    │                           └─ [ThoughtTool methods]
    │
    └─ If other commands:
        └─ [AgentOrchestrator.execute_task()]
            └─ [run_claude()] → subprocess
```

### TeamLeaderAgent Workflow Example

For task: "Find and fix security vulnerabilities in the codebase"

```
Input: "Find and fix security vulnerabilities in the codebase"
    ↓
[_classify_task()]
    └─ Matches "security" keywords
    └─ Returns: "security"
    ↓
[_determine_agents("security")]
    └─ Returns: ["diagnostician", "reviewer"]
    ↓
[_build_workflow("security")]
    └─ Creates steps:
       1. Diagnostician: "Scan for vulnerabilities"
       2. Reviewer: "Validate findings"
    ↓
[_execute_workflow()]
    ├─ Step 1: [DiagnosticianAgent.execute()] 
    │   └─ Uses ThoughtTool.analyze()
    │   └─ Returns findings
    │
    └─ Step 2: [ReviewerAgent.execute()]
        └─ Uses ThoughtTool.evaluate()
        └─ Returns validation result
    ↓
Result: {
    "task_type": "security",
    "workflow_type": "Security Analysis Workflow",
    "spawned_agents": [...],
    "agent_outputs": {...}
}
```

---

## Feature Matrix

### Agent Capabilities

| Agent | Type | Access | Tools | Primary Function |
|-------|------|--------|-------|-----------------|
| TeamLeader | Coordinator | Read-only | Thought | Task routing & orchestration |
| Diagnostician | Analyzer | Read-only | Thought | Code analysis & issue detection |
| BugFixer | Implementer | Write | Thought | Code modification & fixes |
| Reviewer | Validator | Read-only | Thought | Change validation & approval |
| GroupSaleManager | Sales Manager | Read-Write | Thought + BigQuery tools | Data operations (stub) |

### Tool Capabilities

| Tool | Type | Status | Methods | Primary Function |
|------|------|--------|---------|-----------------|
| Thought | Reasoning | ✅ Active | execute, analyze, plan, evaluate | Agent reasoning |
| SchemaReader | BigQuery | ⚠️ Stub | read_schema_from_file, get_table_columns, list_schemas | Schema access |
| QueryBuilder | BigQuery | ⚠️ Stub | build_select/insert/aggregate/join_query | Query generation |
| QueryExecutor | BigQuery | ⚠️ Stub | execute_query, validate, cancel, batch_execute | Query execution |
| DataFetcher | BigQuery | ⚠️ Stub | fetch_results, convert_to_dataframe, export, aggregate | Result processing |

### Execution Paths

| Command | Execution Path | Agents Used |
|---------|----------------|------------|
| `solve` | Direct TeamLeaderAgent | Depends on task type |
| `analyze` | TeamLeader (task type → agents) | Diagnostician + Reviewer |
| `fix` | TeamLeader (task type → agents) | Diagnostician + BugFixer + Reviewer |
| `review` | TeamLeader (task type → agents) | Diagnostician + Reviewer |
| `plan` | TeamLeader (task type → agents) | Depends on classification |

---

## Summary

### Active & Necessary (4 files)
✅ cli.py, claude_provider.py, config.py, team_leader.py

### Active Core Agents (3 files)
✅ diagnostician.py, bug_fixer.py, reviewer.py

### Active Tools (2 files)
✅ thought.py, all __init__.py files (10 files)

### Partial/Stub (5 files)
⚠️ group_sale_manager.py, schema_reader.py, query_builder.py, query_executor.py, data_fetcher.py

### Total: 20 Python files (down from 24 after cleanup)

**Most files are actively used and necessary. The 5 stub tools (BigQuery suite) need decision per REFACTORING_PLAN.md.**

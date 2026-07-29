# Coding Agent Workspace - System Architecture

## Overview

The Coding Agent Workspace is a Claude Code CLI-integrated agent orchestration system for code analysis, bug fixing, and quality review. It uses a Team Leader coordination model with specialized agents working in parallel.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│         Claude Code Terminal (User Interface)           │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │   CLI Entry Point      │
        │  (workspace_cli/cli.py)│
        └────────────┬───────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │   AgentOrchestrator        │
        │ - Creates run ID           │
        │ - Manages workspace        │
        │ - Executes missions        │
        └────────────┬───────────────┘
                     │
                     ▼
        ┌────────────────────────────────────┐
        │   TeamLeaderAgent                  │
        │ - Task classification              │
        │ - Agent selection                  │
        │ - Workflow building                │
        │ - Multi-terminal coordination      │
        └────────────┬───────────────────────┘
                     │
        ┌────────────┴─────────────────┐
        │                              │
        ▼                              ▼
   ┌─────────────┐            ┌──────────────┐
   │Diagnostician│            │   Reviewer   │
   │ - Scans code│            │ - Validates  │
   │ - Finds     │            │ - Scores     │
   │   issues    │            │ - Approves   │
   └─────────────┘            └──────────────┘
        (parallel)                (parallel)
   
   Optional: BugFixer
        ▼
   ┌──────────────┐
   │  BugFixer    │
   │ - Implements │
   │ - Fixes code │
   │ - Commits    │
   └──────────────┘
```

---

## Core Components

### 1. **CLI Layer** (`workspace_cli/`)
- **`cli.py`**: Main command-line interface
  - Argument parsing (solve, analyze, plan, review, fix, execute)
  - Orchestrator creation and execution
  - Result formatting and output
  
- **`claude_provider.py`**: Claude API integration
- **`__main__.py`**: Entry point

**Key Features:**
- `coding-agent-workspace solve "task"` - Main command
- `--single-terminal` - Disable multi-terminal (default: enabled)
- `--workspace DIR` - Custom workspace directory
- Multi-terminal is now **DEFAULT**

---

### 2. **Team Leader Agent** (`.claude/agents/technical/team_leader.py`)
Central orchestrator that:
- **Classifies** tasks (security, bug_analysis, performance, quality, data_operations, general)
- **Selects** appropriate agents based on task type
- **Builds** execution workflow with steps
- **Spawns** agents with proper context
- **Coordinates** multi-terminal execution
- **Broadcasts** all decisions via communication channel

**Task Patterns:**
```python
TASK_PATTERNS = {
    "security": [...security-related keywords...],
    "bug_analysis": [...bug-related keywords...],
    "performance": [...performance keywords...],
    "quality": [...quality keywords...],
    "data_operations": [...data keywords...],
}
```

**Agent Selection Logic:**
- Security → Diagnostician + Reviewer
- Bug Analysis → Diagnostician + Bug Fixer + Reviewer
- Performance → Diagnostician + Reviewer
- Quality → Diagnostician + Reviewer
- Data Operations → Group Sale Manager
- General → Diagnostician + Reviewer

---

### 3. **Specialist Agents** (`.claude/agents/technical/`)

#### **DiagnosticianAgent** (`diagnostician.py`)
- Scans codebase for issues
- Finds: hardcoded credentials, bare exceptions, missing docstrings
- Returns: list of findings with severity

#### **BugFixerAgent** (`bug_fixer.py`)
- Takes findings from Diagnostician
- Implements fixes
- Creates commits
- Reports changes

#### **ReviewerAgent** (`reviewer.py`)
- Validates findings and fixes
- Checks: docstrings, error handling, code style, security, testing
- Returns: score (0-100%) and approval status

#### **GroupSaleManager** (`.claude/agents/business/group_sale_manager.py`)
- BigQuery integration
- Sales data operations
- Aggregation and reporting

---

### 4. **Communication System** (`.claude/agents/agent_communication.py`)
Real-time inter-agent messaging:

**AgentMessage:**
```python
AgentMessage(
    sender="team_leader",
    message="Task classified: quality",
    msg_type="decision",  # info, decision, finding, warning, error
    data={...}
)
```

**Message Types:**
- `[i]` = Info (status updates)
- `[*]` = Decision (important choices)
- `[!]` = Finding (discoveries)
- `[?]` = Warning (caution)
- `[x]` = Error (failures)

**Features:**
- Central message bus per run
- Subscriber notifications
- Message persistence
- Audit trail

---

### 5. **Terminal Management** (`.claude/agents/claude_terminal_manager.py`)
Manages Claude Code terminal spawning:

**ClaudeTerminalManager:**
- `open_agent_terminal(agent_name, task, run_id)` - Open terminal for agent
- `get_terminal_status(terminal_id)` - Check status
- `list_active_terminals()` - Monitor all terminals
- `close_terminal(terminal_id)` - Mark as closed

**Terminal ID Format:**
```
{agent_name}_{run_id}_{sequence_number}
Example: diagnostician_run-2026-07-29T15-55-52.792234_1
```

---

### 6. **Utilities** (`.claude/agents/`)

**StreamHandler** (`stream_handler.py`)
- Real-time streaming output
- Event logging
- Progress bars
- Result formatting

**Tools** (`.claude/tools/`)
- `thought.py` - Reasoning tool for agents
- `query_builder.py` - SQL query building
- `query_executor.py` - Query execution
- `schema_reader.py` - Database schema reading
- `data_fetcher.py` - Data retrieval

---

## Execution Flow

### Example: `coding-agent-workspace solve "fix the authentication bug"`

```
1. User runs command in Claude Code terminal
   ↓
2. CLI parses: command=solve, task="fix the authentication bug"
   ↓
3. AgentOrchestrator.execute_solve() called
   ↓
4. TeamLeaderAgent created with:
   - run_id: auto-generated
   - communication channel: initialized
   - terminal manager: initialized
   ↓
5. Team Leader executes:
   a) Task Classification
      → Classifies as "bug_analysis"
      → Broadcasts: [*] Task classified: bug_analysis
   
   b) Agent Selection
      → Selects: [Diagnostician, BugFixer, Reviewer]
      → Broadcasts: [*] Selected agents: [...]
      → Displays: [TEAM COMPOSITION]
   
   c) Workflow Building
      → Builds 3-step workflow
      → Displays: [WORKFLOW STEPS]
      → Broadcasts: [*] Workflow ready for execution
   
   d) Agent Execution
      → For each agent:
         - Broadcasts: [*] Spawning {agent}
         - Opens Claude Code terminal (if multi-terminal)
         - Broadcasts: [i] Terminal opened: {terminal_id}
         - Executes agent with run_id
         - Broadcasts: [i] {agent} completed
   
   e) Results Aggregation
      → Collects all agent outputs
      → Broadcasts: [i] All agents completed
      → Saves results to .agent-workspace/runs/{run_id}.json
   
   f) Final Report
      → Displays completion status
      → Shows Run ID and workspace location
      ↓
6. Results saved to workspace
7. Communication log persisted
```

---

## File Structure

```
coding-agent-workspace/
├── .claude/
│   ├── agents/
│   │   ├── technical/
│   │   │   ├── team_leader.py          [MAIN ORCHESTRATOR]
│   │   │   ├── diagnostician.py        [AGENT: Analysis]
│   │   │   ├── bug_fixer.py            [AGENT: Implementation]
│   │   │   └── reviewer.py             [AGENT: Validation]
│   │   ├── business/
│   │   │   └── group_sale_manager.py   [AGENT: Data Ops]
│   │   ├── agent_communication.py      [Communication System]
│   │   ├── claude_terminal_manager.py  [Terminal Spawning]
│   │   ├── stream_handler.py           [Output Streaming]
│   │   └── tools/
│   │       ├── thought.py              [Reasoning]
│   │       ├── query_builder.py        [SQL Building]
│   │       └── ...
│   ├── config.py                       [Configuration]
│   └── __init__.py
├── workspace_cli/
│   ├── cli.py                          [CLI Interface]
│   ├── claude_provider.py              [Claude API]
│   └── __init__.py
├── setup.py                            [Package Config]
├── pyproject.toml                      [Modern Config]
├── .gitignore                          [Git Exclusions]
├── SYSTEM_ARCHITECTURE.md              [This File]
├── TEAM_LEADER_ENHANCEMENTS.md         [Enhancements]
├── CLAUDE_CODE_INTEGRATION.md          [Usage Guide]
└── .agent-workspace/
    ├── runs/
    │   ├── run-2026-07-29T15-55-52.json
    │   └── ...
    └── ...
```

---

## Key Design Decisions

### 1. **Team Leader as Primary Orchestrator**
- Single point of coordination
- Clear decision visibility
- Easy to extend with new workflows

### 2. **Multi-Terminal Default**
- Better visibility of parallel agent work
- Each agent can show detailed output
- No terminal conflicts or cluttered output

### 3. **Communication Channel**
- All agent interactions go through message bus
- Enables future agent-to-agent messaging
- Audit trail for all decisions

### 4. **Run IDs for Tracing**
- Each execution gets unique run_id
- All agents use same run_id
- Results indexed by run_id
- Easy to track and replay execution

### 5. **Functional Agent Selection**
- Task classification based on keywords
- No hardcoded agent assignments
- Easy to add new task types
- Extensible pattern matching

---

## Data Flow

### Input
```
User Task Description
  ↓
Team Leader (classification)
  ↓
Pattern Matching (TASK_PATTERNS)
  ↓
Agent Selection (task_type → agents)
  ↓
Context Building (task_type → focus areas)
```

### Processing
```
Agent Execution (parallel in multi-terminal)
  ↓
Communication Channel (broadcast updates)
  ↓
Stream Handler (format output)
  ↓
Result Collection (aggregation)
```

### Output
```
Saved to .agent-workspace/runs/{run_id}.json
  - Task description
  - Classification
  - Agents executed
  - All findings
  - Final score
  - Execution log
```

---

## Removed Components (Cleanup)

**Removed Legacy Files:**
- `multi_terminal_orchestrator.py` - Replaced by Team Leader
- `terminal_manager.py` - Replaced by ClaudeTerminalManager

**Why:**
- Redundant orchestration logic
- Outdated terminal management approach
- Incompatible with new Team Leader architecture
- Code duplication

**Benefits of Cleanup:**
- Single source of truth (Team Leader)
- Simpler codebase
- Easier to maintain and extend
- No conflicting execution paths

---

## Configuration

### Environment Variables
```
CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1   (Enable experimental mode)
spawn_actual_terminals=true               (Use real terminal spawning)
CLAUDE_AGENT_COMMUNICATION_ENABLED=1      (Enable communication channel)
INTERACTIVE_MODE_ENABLED=1                (Enable interactive execution)
```

### Task Configuration
Task patterns can be extended in `TeamLeaderAgent.TASK_PATTERNS`:
```python
"custom_task": [
    "keyword1", "keyword2", "keyword3", ...
],
```

---

## Future Extensions

### Possible Enhancements
1. Agent-to-agent messaging (currently one-way from Team Leader)
2. Agent voting/consensus mechanism
3. Dynamic agent composition (choose agents based on complexity)
4. Parallel execution with result merging
5. Agent error recovery and retry logic
6. Custom workflow definitions (DAG-based)
7. Performance metrics and benchmarking
8. Agent capability discovery

### Compatible Without Changes
- New specialized agents (just add to technical/)
- New task patterns (extend TASK_PATTERNS)
- New terminal handlers (extend ClaudeTerminalManager)
- Custom communication filters

---

## Testing

### Quick Test
```bash
# Multi-terminal (default)
coding-agent-workspace solve "test message"

# Single-terminal
coding-agent-workspace solve "test message" --single-terminal

# Other commands
coding-agent-workspace analyze "test"
coding-agent-workspace review "test"
```

### Verification Checklist
- ✅ Team Leader shows thinking process
- ✅ Agent communication visible
- ✅ Terminal spawning works
- ✅ Results saved to workspace
- ✅ No legacy code conflicts
- ✅ All agents execute properly
- ✅ Communication channel persists

---

## Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Task Classification | <10ms | Pattern matching |
| Workflow Building | <10ms | Static template |
| Agent Spawn | <100ms | Terminal initialization |
| Analysis (Diagnostician) | ~1-2s | File scanning |
| Review (Reviewer) | ~2-3s | Validation checks |
| Total Execute | ~3-5s | Parallel execution |
| Results Save | <100ms | JSON serialization |

---

## Troubleshooting

### Issue: Agents not spawning
**Solution:** Check `--single-terminal` flag, verify terminal availability

### Issue: Communication not showing
**Solution:** Verify `INTERACTIVE_MODE_ENABLED=1` in settings

### Issue: Results not saved
**Solution:** Check `.agent-workspace/` directory exists and has write permissions

### Issue: Agent failures
**Solution:** Check error messages in communication channel, verify task format

---

## Maintenance

### Regular Tasks
- Review `.agent-workspace/runs/` cleanup (old executions)
- Monitor communication logs for patterns
- Update TASK_PATTERNS based on usage

### Code Maintenance
- Keep agents focused on single responsibility
- Extend rather than modify existing agents
- Document new patterns in TASK_PATTERNS
- Update this document for major changes

---

## License & Attribution

Coding Agent Workspace
- Author: Nguyen Le Dang Nguyen
- Email: nguyen.nguyen30@momo.vn
- Created: July 2026
- Claude Code Integration: Multi-agent orchestration system

---

**Last Updated:** 2026-07-29
**Version:** 0.2.0 (Cleaned & Refactored)

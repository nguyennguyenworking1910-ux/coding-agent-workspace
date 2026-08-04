# Coding Agent Workspace - Complete Codebase Analysis

**Project Version:** 0.4.0  
**Author:** Nguyen Le Dang Nguyen  
**Date:** 2026-08-04

---

## Overview

The Coding Agent Workspace is a **multi-agent orchestration system** that coordinates multiple AI agents (Claude instances) to analyze, review, and improve code. The system uses task-based execution with parallel workers, event-driven communication, and persistent storage.

### Core Architecture

```
User Request
    ↓
CLI (workspace_cli/cli.py)
    ↓
Planner (.claude/team/planner.py)
    ├─ Analyzes request
    └─ Creates AgentPlan
    ↓
Coordinator (.claude/team/coordinator.py)
    ├─ Manages state machine
    ├─ Creates workers
    └─ Handles events
    ↓
Workers (RealWorker / FakeWorker)
    ├─ Execute tasks in parallel
    ├─ Emit events
    └─ Persist output
    ↓
RunStore (.claude/team/run_store.py)
    └─ Persists all data to .agent-workspace/runs/<run_id>/
```

---

## Complete File Structure

### Core System Files (KEEP)

#### Orchestration Core
```
.claude/team/schemas.py                    (240 lines)
- Data models: RunStatus, TaskStatus, AgentRole, AgentPlan, AgentTask, AgentEvent, etc.
- Pydantic models for type safety
- Plan validation logic

.claude/team/state_machine.py              (38 lines)
- RunStateMachine: manages valid state transitions
- States: PLANNING → RUNNING → PAUSED/SYNTHESIZING → COMPLETED/FAILED/CANCELLED
- Ensures only valid transitions occur

.claude/team/event_bus.py                  (60 lines)
- EventBus: publish/subscribe system
- Thread-safe event distribution to subscribers
- Used for inter-component communication

.claude/team/coordinator.py                (200+ lines)
- Coordinator: main orchestrator
- Manages run lifecycle (planning → running → synthesizing → completed)
- Creates and starts workers
- Handles events, updates status, waits for dependencies
- Supports worktrees (M6), messaging (M5), checkpoints (M5)

.claude/team/planner.py                    (159 lines)
- Planner: creates execution plans
- Heuristic planning based on request keywords
- Falls back to lead-only execution if needed
- Integrates with ClaudePlanner for AI-powered planning (M4)

.claude/team/claude_planner.py             (80+ lines)
- ClaudePlanner: uses Claude to analyze requests
- Generates multi-agent plans intelligently
- Converts Claude output to AgentPlan schema
```

#### Execution & Workers
```
.claude/team/real_worker.py                (100+ lines)
- RealWorker: executes tasks using Claude Code subprocess
- Runs ClaudeRunner in background thread
- Persists output to RunStore
- Emits events for task lifecycle

.claude/team/claude_runner.py              (150+ lines)
- ClaudeRunner: executes Claude Code subprocess
- Handles stdin/stdout/stderr streaming
- Parses JSON output
- Manages timeout and process lifecycle
- Emits structured events during execution
```

#### Storage & Persistence
```
.claude/team/run_store.py                  (200+ lines)
- RunStore: filesystem-based persistence
- Directory structure: .agent-workspace/runs/<run_id>/
- Methods: save_request, save_plan, save_status, append_event
- Atomic writes with temporary files
- JSONL format for events (1 event per line)
- JSON format for structured data
```

#### Advanced Features (Milestones)

**M5: Session Management & Messaging**
```
.claude/team/session_manager.py            (80+ lines)
- SessionManager: pause/resume capability
- Saves checkpoints with task status
- Tracks completed tasks for resume
- Event emission on session events

.claude/team/mailbox_manager.py            (80+ lines)
- MailboxManager: inter-agent messaging
- AgentMailbox for each agent
- Message tracking (read/unread)
- Persistence to RunStore
- Thread-safe operations with locks
```

**M6: Worktree & Merge Management**
```
.claude/team/worktree_manager.py           (80+ lines)
- WorktreeManager: git worktree creation/cleanup
- Isolated per-agent working directories
- Branch management for safety
- Cleanup operations

.claude/team/merge_strategy.py             (80+ lines)
- MergeStrategy: safe merging of agent changes
- Topological sort respecting dependencies
- Batch-based merging
- Conflict tracking

.claude/team/change_validator.py           (80+ lines)
- ChangeValidator: validates agent changes before merge
- File size checks, binary detection
- Syntax validation (for supported languages)
- Security checks (no secrets, dangerous operations)
```

#### CLI & Commands
```
workspace_cli/cli.py                       (132 lines)
- CLI argument parser
- Entry point: coding-agent-workspace
- Subcommands: team, runs, show, output, message, stop
- Options: --workspace, --max-agents, --mux, --real-workers, --version

workspace_cli/orchestration_commands.py    (119 lines)
- OrchestrationCLI: command implementations
- Planner integration
- Coordinator execution
- Run history and output viewing
```

#### Configuration
```
.claude/config.py                          (minimal)
- Project configuration
- Environment settings

pyproject.toml                             (27 lines)
- Project metadata (name, version, author)
- Dependencies: pydantic>=2.0
- Script entry point: coding-agent-workspace
- Package configuration for setuptools
```

---

## Files to Remove (CLEANUP)

### Test Files (all in tests/)
```
tests/test_acceptance_m1.py
tests/test_milestone2_runner.py
tests/test_milestone3_multiplexer.py
tests/test_milestone4_planner.py
tests/test_milestone5_coordinator_integration.py
tests/test_milestone5_mailbox.py
tests/test_milestone5_steering.py
tests/test_milestone6_coordinator_integration.py
tests/test_milestone6_worktree.py
tests/__init__.py
```
**Reason:** Test infrastructure not needed for production use

### Fake Worker (Testing Only)
```
.claude/team/fake_worker.py                (99 lines)
```
**Reason:** Simulates work with delays and fake events; replaced by real execution

### Unused/Incomplete Files
```
.claude/agents/claude_terminal_manager.py  (terminal management - unused)
.claude/agents/__init__.py
.claude/agents/

.claude/tools/                             (unused database/schema tools)
  - data_fetcher.py
  - query_builder.py
  - query_executor.py
  - schema_reader.py
  - thought.py
  - tool_result.py
  - __init__.py

.claude/team/steering_api.py               (API interface - unused)
.claude/team/worker_host.py                (host management - unused)
.claude/team/terminal_multiplexer.py       (abstract interface - incomplete)
```

### Documentation to Remove
```
MILESTONE1_COMPLETION.md
MILESTONE2_STATUS.md
MILESTONE2_SUMMARY.md
MILESTONE3_SUMMARY.md
MILESTONE4_SUMMARY.md
MILESTONE5_SUMMARY.md
SYSTEM_STATUS.md
ONBOARDING.md
```
**Reason:** Outdated milestone tracking, replaced by this analysis

### Script Files (Optional)
```
run-agent-team.sh
run-agent-team-split.sh
message-agent.sh
```
**Reason:** Optional; kept only if needed for tmux automation

---

## Core Data Flow

### 1. Request → Plan
```
User: "Find security vulnerabilities"
    ↓
Planner.create_plan()
    ├─ Check if multi-agent worthy (heuristic or Claude)
    ├─ Create AgentPlan with agents and tasks
    └─ Validate plan (cycle detection, ownership, criteria)
    ↓
AgentPlan {
  agents: [Researcher, Reviewer],
  tasks: [Task1: Scan, Task2: Review, Task3: Synthesize]
}
```

### 2. Plan → Execution
```
Coordinator.execute_run(plan)
    ├─ Create run directory
    ├─ Save plan.json, request.md
    ├─ Initialize task statuses
    │
    ├─ For each agent:
    │   ├─ Create RealWorker
    │   ├─ Call worker.start() → runs in background thread
    │   └─ Subscribe to events
    │
    └─ Wait for all tasks to complete (with timeout)
```

### 3. Events → Persistence
```
Worker task execution
    ├─ Emit "agent_started" event
    ├─ Emit "progress" events
    ├─ Emit "task_completed" or "task_failed"
    ↓
EventBus.publish(event)
    ├─ Call all subscribers
    ├─ Coordinator._on_event() updates task status
    └─ RunStore.append_event() persists to events.jsonl
```

### 4. Results → Storage
```
.agent-workspace/runs/<run_id>/
├── request.md              (original user request)
├── plan.json               (execution plan)
├── status.json             (current run status)
├── events.jsonl            (all events, 1 per line)
├── final-response.md       (synthesized result)
├── checkpoint.json         (M5: for resume)
└── agents/
    ├── researcher/
    │   ├── task.json
    │   ├── output.jsonl
    │   ├── status.json
    │   └── result.md
    ├── implementer/
    └── reviewer/
```

---

## Component Dependencies Map

### Direct Imports

**Coordinator** imports:
- schemas (for type definitions)
- state_machine (for state transitions)
- run_store (for persistence)
- event_bus (for pub/sub)
- real_worker, fake_worker (for execution)
- mailbox_manager (M5)
- session_manager (M5)
- worktree_manager (M6)
- merge_strategy (M6)
- change_validator (M6)

**Planner** imports:
- schemas
- claude_planner

**RealWorker** imports:
- schemas
- claude_runner
- run_store

**ClaudeRunner** imports:
- schemas (for AgentEvent)
- subprocess, threading

**RunStore** imports:
- schemas (for all data models)
- pathlib, json, tempfile

**OrchestrationCLI** imports:
- planner
- coordinator
- run_store

**CLI** imports:
- orchestration_commands

### Reverse Dependencies (what depends on each file)

| Component | Depended By | Reason |
|-----------|------------|--------|
| schemas.py | All files | Type definitions, validation |
| run_store.py | coordinator, mailbox_mgr, session_mgr | Persistence |
| event_bus.py | coordinator | Event distribution |
| state_machine.py | coordinator | State transitions |
| planner.py | CLI | Plan creation |
| coordinator.py | CLI | Execution |
| real_worker.py | coordinator | Task execution |
| claude_runner.py | real_worker | Claude subprocess |
| mailbox_manager.py | coordinator | Agent messaging |
| session_manager.py | coordinator | Pause/resume |
| worktree_manager.py | coordinator, merge_strategy | Git isolation |

---

## Key Design Patterns

### 1. Event-Driven Architecture
- EventBus for loose coupling between components
- All state changes emit events
- Events are persisted for auditability
- Subscribers react to events

### 2. State Machine Pattern
- RunStateMachine validates transitions
- Only allowed state changes succeed
- Full state history tracked

### 3. Plugin Worker Pattern
- RealWorker and FakeWorker share interface
- Both run in background threads
- Both emit same AgentEvent types
- Easy to add new worker types

### 4. Layered Architecture
```
CLI Layer (workspace_cli/)
    ↓
Orchestration Layer (planner + coordinator)
    ↓
Execution Layer (workers)
    ↓
Storage Layer (run_store)
```

### 5. Separation of Concerns
- **Planner:** What to do and in what order
- **Coordinator:** How to execute and manage state
- **Workers:** Actually do the work
- **RunStore:** Remember everything
- **EventBus:** Notify interested parties

---

## Execution Flow: Detailed

### Step 1: CLI Entry
```python
# coding-agent-workspace team "Find bugs"
cli.main()
  → parser.parse_args()
  → execute_command()
    → OrchestrationCLI.team()
```

### Step 2: Planning
```python
OrchestrationCLI.team()
  → Planner.create_plan()
    → Check if multi-agent worthy
    → Create AgentPlan with 2-3 workers + lead
    → Validate plan
    → Return (plan, is_valid)
```

**Heuristic:** Keywords like "review", "analyze", "test" trigger multi-agent

### Step 3: Execution
```python
Coordinator.execute_run(plan)
  1. Create .agent-workspace/runs/<run_id>/
  2. Save request, plan to disk
  
  3. For each agent in plan.agents:
       worker = RealWorker(agent, task)
       worker.start()  → runs in background thread
       self.workers[agent.agent_id] = worker
  
  4. Wait loop (with timeout):
       while not all_tasks_done:
         - Check worker status
         - Handle events
         - Update task_statuses
         - Sleep 0.1s
  
  5. Transition to SYNTHESIZING
  
  6. Return success
```

### Step 4: Worker Execution (Background Thread)
```python
RealWorker._execute()
  1. Create system prompt for Claude
  2. Create ClaudeRunner subprocess
  3. runner.run(prompt, system_prompt)
     ├─ Spawn Claude process
     ├─ Send prompt via stdin
     ├─ Stream stdout/stderr
     └─ Parse JSON output
  4. Emit "task_completed" event
  5. Save output to RunStore
```

### Step 5: Results Available
```
.agent-workspace/runs/<run_id>/
├── events.jsonl (every action logged)
├── plan.json (what was planned)
├── status.json (current status)
└── agents/<agent_id>/
    └── output.jsonl (Claude's response)
```

---

## Configuration & Runtime Options

### Command Line Options
```bash
coding-agent-workspace team REQUEST
  --max-agents N           # Limit agents (default 4)
  --mux MODE               # Multiplexer: auto|tmux|psmux|headless (default auto)
  --real-workers           # Use real Claude (else fake workers for testing)
  --workspace DIR          # Custom workspace (default .agent-workspace)
```

### Environment Variables
- `CLAUDE_API_KEY`: Claude API authentication (required for real workers)

### Default Configuration
- Timeout for fake workers: 30 seconds
- Timeout for real workers: 300 seconds (5 minutes)
- Max agents: 4
- Output format: JSONL (events), JSON (structured data), Markdown (human-readable)

---

## Testing (Files to Remove)

All test files follow naming pattern `test_milestone*.py`:

### Test Coverage (Removed)
- M1: Basic orchestration
- M2: Claude runner
- M3: Terminal multiplexing
- M4: Claude-powered planning
- M5: Coordinator integration, mailbox, messaging
- M6: Worktree, change validation

**Action:** Delete entire `tests/` directory

---

## Unused Components (Remove)

### Terminal Multiplexer (Incomplete)
```
.claude/team/terminal_multiplexer.py
```
- Abstract interface only
- No concrete implementations
- Not integrated into coordinator
- **Action:** Remove

### Tools & Agents Directories
```
.claude/agents/
.claude/tools/
```
- Unused database query tools
- Terminal management stub
- Not referenced by main system
- **Action:** Remove both directories

### Steering API
```
.claude/team/steering_api.py
```
- Incomplete API interface
- Not used by coordinator
- **Action:** Remove

### Worker Host
```
.claude/team/worker_host.py
```
- Incomplete host management
- Replaced by coordinator
- **Action:** Remove

---

## Migration Path for User Modifications

The user should focus on these files for customization:

### 1. Add Custom Agent Roles
**File:** `.claude/team/schemas.py`
```python
class AgentRole(str, Enum):
    RESEARCHER = "researcher"
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"
    TESTER = "tester"
    CUSTOM = "custom"  # Add your custom roles here
    MY_ROLE = "my_role"  # New role
```

### 2. Customize Planning Logic
**File:** `.claude/team/planner.py`
```python
def _is_multi_agent_worthy(self, request: str) -> bool:
    # Add custom keywords to trigger multi-agent execution
    keywords = [
        "review", "analyze", "test",  # existing
        "my_keyword",  # new
    ]
```

### 3. Add Task Post-Processing
**File:** `.claude/team/coordinator.py`
```python
def _on_event(self, event: AgentEvent) -> None:
    # Add custom handling for specific events
    if event.event_type == "task_completed":
        # Custom post-processing
```

### 4. Custom Validation Rules
**File:** `.claude/team/change_validator.py`
```python
def validate_worktree(self, ...):
    # Add custom validation checks
```

---

## Summary: What to Keep vs Remove

### ✅ KEEP (Core System)
- `.claude/team/*.py` (all orchestration logic)
- `workspace_cli/` (CLI interface)
- `pyproject.toml` (packaging)
- `README.md` (documentation)

### ❌ REMOVE (Cleanup)
- `tests/` (all test files)
- `.claude/team/fake_worker.py` (testing only)
- `.claude/agents/` (unused)
- `.claude/tools/` (unused)
- `.claude/team/terminal_multiplexer.py`
- `.claude/team/steering_api.py`
- `.claude/team/worker_host.py`
- `MILESTONE*.md` (outdated docs)
- `SYSTEM_STATUS.md`
- `ONBOARDING.md`

### 🤔 OPTIONAL (Keep if needed)
- `run-agent-team.sh`
- `run-agent-team-split.sh`
- `message-agent.sh`
- `WSL2_Ubuntu_Tmux_Guide.md`
- `SETUP_GUIDE_VI.md`

---

## Next Steps for User

1. **Understand Core Files**
   - Read files in order: schemas → state_machine → event_bus → run_store
   - Then: planner → coordinator → workers
   - Finally: CLI

2. **Clean Repository**
   - Delete `tests/` directory
   - Delete `.claude/team/fake_worker.py`
   - Delete `.claude/agents/` and `.claude/tools/`
   - Delete unused `.claude/team/` files
   - Delete outdated milestone markdown files

3. **Add New Features**
   - Extend schemas for new agent roles
   - Modify planner for custom planning logic
   - Add validation rules in change_validator
   - Create new worker types if needed

4. **Documentation**
   - Update README with current state
   - Document any custom modifications
   - Keep this CODEBASE_ANALYSIS.md as reference

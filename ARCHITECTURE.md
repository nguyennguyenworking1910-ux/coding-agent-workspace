# Coding Agent Workspace - System Architecture

**Version:** 0.4.0  
**Author:** Nguyen Le Dang Nguyen  
**Purpose:** Multi-agent orchestration system for code analysis using Claude AI

---

## Overview

The Coding Agent Workspace is a sophisticated multi-agent orchestration system that:

1. **Accepts user requests** via CLI
2. **Creates execution plans** with task dependencies
3. **Executes agents in parallel** using Claude AI
4. **Manages communication** between agents via event bus
5. **Persists results** in structured format for later review

### Key Design Principles

- **Modular**: Each component has a single responsibility
- **Persistent**: All runs and events are saved for reproducibility
- **Event-driven**: Agents communicate through a publish/subscribe event bus
- **Type-safe**: Uses Pydantic for data validation
- **Scalable**: Supports 1-4 parallel agents with dependency management

---

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│              User Interface (CLI)                   │
│         workspace_cli/cli.py                        │
└────────────────┬────────────────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────────────────┐
│         Orchestration Command Handler               │
│    workspace_cli/orchestration_commands.py          │
└────────────────┬────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        ↓                 ↓
    Planner          Coordinator
   (Plan)          (Execute & Manage)
        │                 │
        └────────┬────────┘
                 ↓
┌─────────────────────────────────────────────────────┐
│              Core Components                        │
├─────────────────────────────────────────────────────┤
│ • EventBus (pub/sub communication)                 │
│ • RunStore (persistent storage)                    │
│ • RealWorker (Claude AI agent execution)           │
│ • MailboxManager (agent messaging)                 │
│ • WorktreeManager (git isolation)                  │
└─────────────────────────────────────────────────────┘
        │
        ↓
┌─────────────────────────────────────────────────────┐
│              Data Persistence                       │
│  .agent-workspace/runs/<run-id>/                   │
└─────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. **CLI Layer** (workspace_cli/)

#### `workspace_cli/cli.py`
- **Purpose**: Command-line interface entry point
- **Responsibility**: Parse arguments and route to appropriate handlers
- **Key Functions**:
  - `create_parser()`: Build CLI argument parser
  - `execute_command()`: Route commands to handlers
  - `main()`: Entry point for `coding-agent-workspace` command

**Available Commands**:
```bash
coding-agent-workspace team "request"          # Run multi-agent orchestration
coding-agent-workspace runs                    # List all runs
coding-agent-workspace show <run-id>           # Show run details
coding-agent-workspace output <run-id> <id>   # Show agent output
coding-agent-workspace message <run-id> <id> <msg>  # Send message to agent
coding-agent-workspace stop <run-id>           # Stop a run
```

#### `workspace_cli/orchestration_commands.py`
- **Purpose**: Implement orchestration command handlers
- **Responsibility**: Execute CLI commands using Planner and Coordinator
- **Key Classes**:
  - `OrchestrationCLI`: Main command handler class
- **Key Methods**:
  - `team()`: Plan and execute multi-agent run
  - `runs()`: List all runs
  - `show()`: Display run details
  - `output()`: Show agent output
  - `message()`: Send message to agent
  - `stop()`: Stop a run

**Flow**:
```
CLI request → OrchestrationCLI.team()
    ↓
Planner.create_plan(request)
    ↓
Coordinator.execute_run(plan)
    ↓
Store results in .agent-workspace/
```

---

### 2. **Planning Layer** (.claude/team/)

#### `schemas.py`
- **Purpose**: Data models for the entire system
- **Type-Safe Data Structures** using Pydantic:

**Key Classes**:

```python
# Status enums
RunStatus: PLANNING, RUNNING, PAUSED, SYNTHESIZING, COMPLETED, FAILED, CANCELLED
TaskStatus: PENDING, BLOCKED, RUNNING, COMPLETED, FAILED, CANCELLED
AgentRole: RESEARCHER, IMPLEMENTER, REVIEWER, TESTER, CUSTOM

# Core models
AgentAssignment: Agent definition with role and objective
    - agent_id: Unique identifier
    - role: AgentRole enum
    - objective: Task to accomplish
    - owned_paths: Files the agent can modify
    - read_only: Whether agent is read-only

AgentTask: Individual task to execute
    - task_id: Unique identifier
    - title: Human-readable title
    - instructions: Detailed instructions for agent
    - owner_agent_id: Which agent performs this task
    - depends_on: List of task IDs this task depends on
    - acceptance_criteria: Success conditions
    - status: Current task status
    - timing: created_at, started_at, completed_at

AgentPlan: Complete execution plan
    - run_id: Unique run identifier
    - summary: High-level description
    - parallelism_justified: Whether multi-agent is needed
    - agents: List of AgentAssignment
    - tasks: List of AgentTask with dependencies
    - validate_plan(): Checks for errors and cycles

AgentEvent: Communication unit between agents
    - event_id: Unique event identifier
    - run_id: Associated run
    - agent_id: Source agent
    - task_id: Associated task
    - event_type: Type of event (agent_started, progress, task_completed, task_failed, etc.)
    - payload: Additional data

RunContext: Runtime state container
    - run_id, status, created_at, agents, tasks, events
```

---

#### `planner.py`
- **Purpose**: Create execution plans from user requests
- **Responsibility**: Analyze request and decide how to parallelize work
- **Key Classes**:
  - `Planner`: Plan creation and validation

**Key Methods**:
```python
create_plan(run_id, request, use_claude=False) -> (AgentPlan, bool)
    ├─ Uses Claude AI (if use_claude=True) or heuristics to create plan
    ├─ Validates plan for cycles, overlaps, and acceptance criteria
    └─ Returns (plan, is_valid) tuple

_is_multi_agent_worthy(request) -> bool
    ├─ Checks keywords: "review", "analyze", "test", "investigate", etc.
    └─ Decides if parallelism is justified

_heuristic_plan(request) -> AgentPlan
    ├─ Creates plan based on keyword analysis
    └─ Assigns agents and tasks

_fallback_lead_only_plan(request) -> AgentPlan
    ├─ Single-agent fallback plan
    └─ Used when multi-agent planning fails
```

**Plan Structure**:
```
Request: "Find all security vulnerabilities"
    ↓
Planner analyzes keywords: "find", "security"
    ↓
Creates plan with 3 agents:
    - Researcher: Scan for vulnerabilities
    - Implementer: Suggest fixes
    - Reviewer: Validate findings
    ↓
Each agent gets specific task with acceptance criteria
    ↓
Return validated AgentPlan
```

---

### 3. **Execution Layer** (.claude/team/)

#### `coordinator.py`
- **Purpose**: Orchestrate the execution of an entire run
- **Responsibility**: Manage run lifecycle, state transitions, task execution
- **Key Classes**:
  - `Coordinator`: Main orchestration manager

**Key Methods**:
```python
execute_run(request, plan, use_fake_workers=True, timeout=30) -> bool
    ├─ Phase 1: PLANNING
    │   └─ Save request and plan to disk
    ├─ Phase 2: RUNNING
    │   ├─ Create workers for each task
    │   ├─ Execute in parallel (threaded)
    │   ├─ Listen for events on EventBus
    │   └─ Update task statuses
    ├─ Phase 3: SYNTHESIZING
    │   └─ Synthesize final response from all agent outputs
    └─ Phase 4: COMPLETED/FAILED
        └─ Save final response and mark run as complete

_execute_with_real_workers() -> None
    ├─ Creates RealWorker for each task
    ├─ Starts each worker (runs in background thread)
    └─ Workers execute Claude AI agents

_wait_for_dependencies(timeout) -> bool
    ├─ Monitors task completion
    ├─ Respects task dependencies
    └─ Times out if takes too long

_synthesize() -> str
    ├─ Collects all agent outputs
    ├─ Synthesizes into final response
    └─ Returns summary for user
```

**Run Lifecycle**:
```
PLANNING → RUNNING → SYNTHESIZING → COMPLETED
   ↓          ↓             ↓
 Create    Execute      Collect
 plan      workers      results
   
If error:
   ↓
 FAILED
   ↓
 Save error info
```

---

#### `event_bus.py`
- **Purpose**: Publish/subscribe communication between agents
- **Responsibility**: Route events to interested subscribers
- **Key Classes**:
  - `EventBus`: Central event routing

**Key Methods**:
```python
subscribe(event_type, callback) -> None
    └─ Register callback for specific event type

subscribe_all(callback) -> None
    └─ Register callback for all event types

publish(event) -> None
    ├─ Find all subscribers for event.event_type
    ├─ Call each callback with event
    └─ Handle exceptions gracefully

unsubscribe(event_type, callback) -> None
    └─ Unregister callback from specific type

unsubscribe_all(callback) -> None
    └─ Unregister callback from all events
```

**Usage Example**:
```python
# Subscriber (e.g., in Coordinator)
event_bus.subscribe_all(self._on_event)

# Publisher (e.g., in RealWorker)
event = AgentEvent(
    event_id="evt-1",
    run_id="run-123",
    agent_id="researcher",
    task_id="t1",
    event_type="task_completed",
    payload={"result": "Found 5 vulnerabilities"}
)
event_bus.publish(event)

# Callback
def _on_event(self, event: AgentEvent):
    self.store.append_event(self.run_id, event)
    self.task_statuses[event.task_id] = TaskStatus.COMPLETED
```

---

#### `run_store.py`
- **Purpose**: Persistent storage for runs and events
- **Responsibility**: Save and load run data to/from disk
- **Key Classes**:
  - `RunStore`: Manages run directory structure and persistence

**Directory Structure**:
```
.agent-workspace/runs/<run-id>/
├── request.md              # Original user request
├── plan.json              # Execution plan (AgentPlan)
├── status.json            # Current run status
├── events.jsonl           # Event log (1 event per line)
├── final-response.md      # Team leader's synthesis
└── agents/
    ├── <agent-id>/
    │   ├── task.json      # Task assignment
    │   ├── prompt.md      # System prompt used
    │   ├── output.jsonl   # Output lines (1 per line)
    │   ├── status.json    # Task status
    │   └── result.md      # Final result
    ├── <agent-id>/
    └── ...
```

**Key Methods**:
```python
create_run_dir(run_id) -> None
    └─ Creates .agent-workspace/runs/<run-id>/ directory structure

save_request(run_id, request) -> None
    └─ Saves user request to request.md

save_plan(run_id, plan) -> None
    └─ Serializes AgentPlan to plan.json

append_event(run_id, event) -> None
    └─ Appends event as JSON line to events.jsonl

load_plan(run_id) -> AgentPlan
    └─ Loads plan.json and deserializes to AgentPlan

load_events(run_id) -> List[AgentEvent]
    └─ Loads events.jsonl and returns all events

save_final_response(run_id, response) -> None
    └─ Saves synthesis to final-response.md

list_runs() -> List[str]
    └─ Returns list of all run IDs
```

---

#### `real_worker.py`
- **Purpose**: Execute a single task using Claude AI
- **Responsibility**: Run agent via subprocess, capture output, emit events
- **Key Classes**:
  - `RealWorker`: Executes a task via Claude AI

**Key Methods**:
```python
__init__(agent_id, task, run_id, cwd, timeout, on_event, store)
    ├─ Creates ClaudeRunner instance
    └─ Sets up callbacks for events

start() -> None
    └─ Starts execution in background thread

_execute() -> None
    ├─ Creates system prompt for agent role
    ├─ Calls ClaudeRunner.run() with task instructions
    └─ Emits events to event_bus
```

**Execution Flow**:
```
RealWorker.start()
    ↓
_execute() in background thread
    ↓
ClaudeRunner.run(prompt, system_prompt)
    ├─ Calls Claude API (if API key available)
    ├─ Streams output
    └─ Returns success/failure
    ↓
Emit task_completed or task_failed event
    ↓
Save output to .agent-workspace/runs/<run-id>/agents/<agent-id>/output.jsonl
```

---

### 4. **Storage & State Management** (.claude/team/)

#### `run_store.py` (details)
- Manages all persistent data
- JSON Lines format for events (streaming-friendly)
- Supports loading partial results (e.g., already-completed tasks)

#### `state_machine.py`
- **Purpose**: Enforce valid run state transitions
- **Valid Transitions**:
  ```
  PLANNING → RUNNING → SYNTHESIZING → COMPLETED
      ↓         ↓            ↓
    FAILED   FAILED      FAILED
  ```

#### `mailbox_manager.py`
- **Purpose**: Enable inter-agent messaging
- **Functionality**: Agents can send/receive messages during execution
- **Used for**: Dynamic coordination, feedback, and adjustments

#### `session_manager.py`
- **Purpose**: Support run resumption
- **Functionality**: Save checkpoints of completed tasks
- **Use Case**: Resume a paused/interrupted run from last completed task

---

### 5. **Advanced Features** (.claude/team/)

#### `worktree_manager.py`
- **Purpose**: Isolate agent modifications using git worktrees
- **Functionality**: Each agent gets its own git worktree for safe modifications
- **Benefit**: No conflicts between agent changes, easy rollback

#### `merge_strategy.py`
- **Purpose**: Define how to merge agent changes back to main branch
- **Strategies**: 
  - `auto`: Automatic merge if no conflicts
  - `manual`: Require human review
  - `abort`: Reject changes if any conflicts

#### `change_validator.py`
- **Purpose**: Validate agent changes before merging
- **Checks**: Code quality, security, test coverage, build success

---

### 6. **External Integration** (.claude/team/)

#### `claude_runner.py`
- **Purpose**: Interface with Claude AI models
- **Responsibility**: 
  - Call Claude API with system/user prompts
  - Handle streaming responses
  - Manage timeouts and retries

#### `claude_planner.py`
- **Purpose**: Optional Claude-powered planning
- **Functionality**: Use Claude to create execution plans
- **Fallback**: Heuristic planning if Claude planning fails

---

## Data Flow

### 1. **Request → Execution**
```
User Input: "Find security vulnerabilities"
    ↓
CLI.team() → OrchestrationCLI.team()
    ↓
Planner.create_plan()
    ├─ Analyze request keywords
    ├─ Create agent assignments
    ├─ Create task graph
    └─ Validate plan
    ↓
Coordinator.execute_run()
    ├─ Create workers for each task
    ├─ Start workers (threaded)
    └─ Wait for completion
    ↓
EventBus routes events
    ├─ RunStore persists events
    ├─ Coordinator updates task statuses
    └─ Workers update progress
    ↓
Coordinator._synthesize()
    ├─ Collect all agent outputs
    ├─ Create summary
    └─ Save final-response.md
    ↓
Results saved to .agent-workspace/runs/<run-id>/
```

### 2. **Event Flow**
```
Agent Task Started
    ↓
RealWorker emits: AgentEvent(event_type="agent_started")
    ↓
EventBus.publish(event)
    ↓
Coordinator._on_event() receives event
    ├─ RunStore.append_event() persists it
    ├─ task_statuses updated to RUNNING
    └─ Event saved to events.jsonl
    ↓
(Agent executes and produces output)
    ↓
Agent Task Completed
    ↓
RealWorker emits: AgentEvent(event_type="task_completed", payload={...})
    ↓
EventBus.publish(event)
    ↓
Coordinator._on_event() receives event
    ├─ RunStore.append_event() persists it
    ├─ task_statuses updated to COMPLETED
    └─ Synthesis can now proceed if all dependencies met
```

### 3. **Result Retrieval**
```
User: "Show me run results"
    ↓
CLI.show(run_id)
    ↓
RunStore.load_plan(run_id)
RunStore.load_status(run_id)
RunStore.load_events(run_id)
    ↓
Display results to user
```

---

## Design Patterns Used

### 1. **Event-Driven Architecture**
- Loose coupling between agents
- Coordinator doesn't directly manage agents
- Communication via EventBus

### 2. **Observer Pattern** (EventBus)
- Subscribers register callbacks
- Publishers emit events
- Subscribers notified asynchronously

### 3. **Strategy Pattern** (Merge/Validation)
- Different merge strategies can be plugged in
- Different validation rules can be applied

### 4. **State Machine Pattern**
- RunStatus defines valid states
- State transitions validated
- No invalid state combinations possible

### 5. **Factory Pattern** (Worker creation)
- Coordinator creates appropriate worker type (Real/Fake)
- Same interface for both types

### 6. **Template Method Pattern** (Task execution)
- Each worker follows same execution flow
- Specific implementation varies (Claude API vs. fake)

---

## Configuration Files

### `pyproject.toml`
- Python packaging configuration
- Project metadata
- Dependencies: pydantic>=2.0
- Entry point: `coding-agent-workspace = workspace_cli.cli:main`
- Package structure for setuptools

---

## Error Handling

### Graceful Degradation
```
1. Multi-agent plan creation fails
   → Falls back to lead-only plan
   
2. Validation errors in plan
   → Log errors and use fallback plan
   
3. Task execution fails
   → Task marked as FAILED
   → Run continues with other tasks
   → Synthesis still happens with partial results
   
4. All workers fail
   → Run marked as FAILED
   → Error information saved for debugging
```

---

## Persistence Strategy

- **Events**: Append-only JSON Lines (events.jsonl)
  - Immutable: Cannot modify past events
  - Streaming: Can read partial results while run is ongoing
  - Debuggable: Human-readable JSON format

- **Plans**: Single JSON file (plan.json)
  - Loaded once at start
  - Used for dependency resolution and validation

- **Status**: Updated JSON file (status.json)
  - Current run state
  - Can be queried while run is executing

- **Results**: Markdown files
  - Human-readable format
  - Good for documentation and sharing

---

## Threading Model

### Coordinator (Main Thread)
- Reads CLI args
- Creates plan
- Starts workers
- Listens for events
- Waits for completion
- Calls synthesis

### Worker Threads (Background)
- Each task gets a separate thread
- Runs Claude API call in thread
- Emits events back to coordinator
- Coordinator is thread-safe (uses locks in EventBus)

### Thread Safety
- EventBus uses locks for subscriber list
- RunStore uses file locks for JSON operations
- task_statuses protected by Coordinator

---

## Extension Points

To add new features, modify these components:

1. **New Agent Role**: Update `AgentRole` enum in schemas.py
2. **New Event Type**: Update event publishing in workers
3. **New State**: Update `RunStatus` enum in schemas.py
4. **New Validation Rule**: Extend `AgentPlan.validate_plan()`
5. **New Merge Strategy**: Create new subclass of MergeStrategy
6. **New Planner Logic**: Extend Planner class or ClaudePlanner

---

## Performance Characteristics

- **Planning Time**: ~100ms (heuristic) or 1-5s (Claude)
- **Execution Time**: 10-300s depending on task complexity
- **Parallelism**: 1-4 agents executing simultaneously
- **Storage**: ~1KB per event, ~10KB per run minimum
- **Memory**: ~100MB per run (full results in memory)

---

## Future Improvements

1. **Streaming Results**: Stream task results to client without waiting
2. **Dynamic Rebalancing**: Reassign tasks if agent fails
3. **Knowledge Base**: Learn from past runs to improve planning
4. **Human-in-the-Loop**: Pause for human review at checkpoints
5. **Multi-Modal Agents**: Different agent types for different tasks
6. **Distributed Execution**: Run agents on remote machines

---

**Last Updated**: 2026-08-04  
**Maintainer**: Nguyen Le Dang Nguyen

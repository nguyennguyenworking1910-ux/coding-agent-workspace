# File Reference Guide

Complete documentation of each Python file in the coding-agent-workspace.

---

## CLI Layer (`workspace_cli/`)

### `workspace_cli/cli.py`
**Purpose**: Command-line interface entry point  
**Size**: ~130 lines  
**Language**: Python

**Responsibility**:
- Parse command-line arguments
- Route commands to appropriate handlers
- Handle errors and display help

**Key Functions**:
```python
create_parser() -> argparse.ArgumentParser
    └─ Builds CLI parser with all available commands

execute_command(args: argparse.Namespace) -> int
    ├─ Dispatches to OrchestrationCLI handler
    └─ Returns exit code (0=success, 1=failure)

main() -> int
    ├─ Entry point for 'coding-agent-workspace' command
    └─ Called by setuptools entry point
```

**Supported Commands**:
```
team TASK              Multi-agent orchestration
runs                   List all runs
show RUN_ID            Show run details
output RUN_ID AGT      Show agent output
message RUN_ID AGT MSG Send message to agent
stop RUN_ID            Stop a run
```

**Depends On**:
- `orchestration_commands.OrchestrationCLI`
- `argparse` (stdlib)
- `sys` (stdlib)

**Used By**:
- `setuptools` entry point in `pyproject.toml`

---

### `workspace_cli/orchestration_commands.py`
**Purpose**: Command handlers for team orchestration  
**Size**: ~120 lines  
**Language**: Python

**Responsibility**:
- Implement handlers for each CLI command
- Coordinate planning and execution
- Display results to user

**Key Classes**:
```python
class OrchestrationCLI:
    """Handlers for 'team', 'runs', 'show', 'message', 'stop' commands."""
    
    def __init__(self, workspace_dir: str = ".agent-workspace")
        └─ Initialize with workspace directory and planner
    
    def team(self, request: str, max_agents: int = 4, mux: str = "auto", 
             use_real_workers: bool = False) -> int
        ├─ Parse request
        ├─ Create plan
        ├─ Execute run
        └─ Return exit code
    
    def runs(self) -> int
        └─ List all completed runs
    
    def show(self, run_id: str) -> int
        └─ Display run details (plan, status, events)
    
    def output(self, run_id: str, agent_id: str) -> int
        └─ Display specific agent's output
    
    def message(self, run_id: str, agent_id: str, text: str) -> int
        └─ Send message to agent during run
    
    def stop(self, run_id: str) -> int
        └─ Stop a running run
```

**Execution Flow**:
```
User: "Find security vulnerabilities"
    ↓
CLI.team(request="Find security vulnerabilities", real_workers=True)
    ↓
Planner.create_plan(request)
    └─ Returns: AgentPlan with 3 agents
    ↓
Coordinator.execute_run(request, plan)
    ├─ Start RealWorker threads for each task
    ├─ Listen to EventBus for updates
    └─ Wait for completion
    ↓
Results saved to .agent-workspace/runs/<run-id>/
    ↓
Display: "Run completed: run-2026-08-03T10-30-45"
```

**Depends On**:
- `team.planner.Planner`
- `team.coordinator.Coordinator`
- `team.run_store.RunStore`
- `pathlib.Path`
- `datetime.datetime`

**Used By**:
- `cli.execute_command()`

---

## Data Schemas (`claude/team/`)

### `schemas.py`
**Purpose**: Data models for entire system  
**Size**: ~250 lines  
**Language**: Python  
**Framework**: Pydantic v2

**Responsibility**:
- Define all data structures
- Validate data integrity
- Provide type safety

**Key Classes**:

#### Enums
```python
class RunStatus(str, Enum):
    PLANNING = "planning"          # Creating execution plan
    RUNNING = "running"            # Executing agents
    PAUSED = "paused"              # Paused by user
    SYNTHESIZING = "synthesizing"  # Collecting results
    COMPLETED = "completed"        # Successfully finished
    FAILED = "failed"              # Failed somewhere
    CANCELLED = "cancelled"        # User cancelled

class TaskStatus(str, Enum):
    PENDING = "pending"      # Not yet started
    BLOCKED = "blocked"      # Waiting for dependencies
    RUNNING = "running"      # Currently executing
    COMPLETED = "completed"  # Done
    FAILED = "failed"        # Error occurred
    CANCELLED = "cancelled"  # User cancelled

class AgentRole(str, Enum):
    RESEARCHER = "researcher"      # Analyzes and finds issues
    IMPLEMENTER = "implementer"    # Implements fixes
    REVIEWER = "reviewer"          # Reviews and validates
    TESTER = "tester"              # Tests and verifies
    CUSTOM = "custom"              # Custom role
```

#### Data Models
```python
class AgentAssignment(BaseModel):
    """Assignment for a single agent."""
    agent_id: str              # Unique identifier
    role: AgentRole            # Agent's role
    objective: str             # What to accomplish
    owned_paths: List[str]     # Files agent can modify
    read_only: bool            # Can agent modify files?

class AgentTask(BaseModel):
    """Individual task to execute."""
    task_id: str              # Unique identifier
    title: str                # Human-readable title
    instructions: str         # What agent should do
    owner_agent_id: str       # Which agent does this
    depends_on: List[str]     # Task IDs this depends on
    acceptance_criteria: List[str]  # Success conditions
    status: TaskStatus        # Current status
    created_at: datetime      # When created
    started_at: Optional[datetime]  # When started
    completed_at: Optional[datetime]  # When finished

class AgentPlan(BaseModel):
    """Complete execution plan."""
    run_id: str
    summary: str              # High-level description
    parallelism_justified: bool  # Is multi-agent worthwhile?
    synthesis_task_id: str    # ID of synthesis task
    agents: List[AgentAssignment]  # All agents in plan
    tasks: List[AgentTask]    # All tasks with dependencies
    created_at: datetime
    
    def validate_plan(self) -> List[str]:
        """Check plan for errors.
        
        Validates:
        - Every task has an owner agent
        - Dependencies reference valid tasks
        - No circular dependencies
        - No overlapping file ownership
        - <= 4 agents max
        - Every task has acceptance criteria
        
        Returns: List of error messages (empty if valid)
        """

class AgentEvent(BaseModel):
    """Communication unit between agents."""
    event_id: str             # Unique ID
    run_id: str               # Associated run
    agent_id: Optional[str]   # Source agent (if any)
    task_id: Optional[str]    # Associated task (if any)
    timestamp: datetime
    event_type: str           # Type of event
    payload: Dict[str, Any]   # Additional data
    
    # Valid event_type values:
    # - "agent_started"
    # - "agent_stopped"
    # - "progress"
    # - "message"
    # - "task_completed"
    # - "task_failed"

class RunContext(BaseModel):
    """Runtime state of a run."""
    run_id: str
    status: RunStatus
    created_at: datetime
    agents: List[AgentAssignment]
    tasks: List[AgentTask]
    events: List[AgentEvent]

class WorkerOutput(BaseModel):
    """Output from a worker."""
    agent_id: str
    task_id: str
    status: TaskStatus
    result: str
```

**Validation Logic**:
```python
# AgentPlan.validate_plan() checks:

1. Task ownership
   └─ Every task assigned to an agent in the plan

2. Dependency validity
   └─ All task dependencies reference existing tasks

3. Circular dependency detection
   └─ Uses DFS to find cycles
   
4. File ownership conflicts
   └─ No two write-capable agents own same file

5. Agent limit
   └─ Maximum 4 agents per plan

6. Acceptance criteria
   └─ Every task must have criteria for success
```

**Usage Example**:
```python
# Creating a plan
plan = AgentPlan(
    run_id="run-123",
    summary="Analyze security",
    parallelism_justified=True,
    synthesis_task_id="t_synthesize",
    agents=[
        AgentAssignment(
            agent_id="researcher",
            role=AgentRole.RESEARCHER,
            objective="Find vulnerabilities",
            read_only=True
        ),
        AgentAssignment(
            agent_id="reviewer",
            role=AgentRole.REVIEWER,
            objective="Validate findings",
            read_only=True
        )
    ],
    tasks=[
        AgentTask(
            task_id="t1",
            title="Scan code",
            instructions="Search for hardcoded passwords...",
            owner_agent_id="researcher",
            depends_on=[],
            acceptance_criteria=[
                "Found at least 1 vulnerability",
                "Listed all locations"
            ]
        ),
        AgentTask(
            task_id="t2",
            title="Review findings",
            instructions="Verify all findings are valid...",
            owner_agent_id="reviewer",
            depends_on=["t1"],
            acceptance_criteria=["Confirmed or rejected each finding"]
        ),
        AgentTask(
            task_id="t_synthesize",
            title="Synthesize",
            instructions="Create summary...",
            owner_agent_id="lead",
            depends_on=["t1", "t2"],
            acceptance_criteria=["Summary complete"]
        )
    ]
)

# Validating
errors = plan.validate_plan()
if not errors:
    print("Plan is valid!")
else:
    print(f"Errors: {errors}")

# Creating an event
event = AgentEvent(
    event_id="evt-1",
    run_id="run-123",
    agent_id="researcher",
    task_id="t1",
    event_type="task_completed",
    payload={
        "findings_count": 5,
        "severity_summary": "2 high, 3 medium"
    }
)
```

**Depends On**:
- `pydantic` v2
- `enum`, `datetime`, `typing` (stdlib)

**Used By**:
- Every other module in the system
- All files import from schemas.py

---

## Planning (`claude/team/`)

### `planner.py`
**Purpose**: Create execution plans from requests  
**Size**: ~150 lines  
**Language**: Python

**Responsibility**:
- Analyze user requests
- Decide between single/multi-agent approaches
- Create validated plans
- Fall back gracefully on errors

**Key Classes**:
```python
class Planner:
    """Creates and validates execution plans."""
    
    def __init__(self, max_workers: int = 4)
        └─ Initialize planner with worker limit
    
    def create_plan(self, run_id: str, request: str, use_claude: bool = False)
        ├─ Parse request
        ├─ Create plan (Claude-based or heuristic)
        ├─ Validate plan
        └─ Return (AgentPlan, is_valid)
    
    def _heuristic_plan(self, run_id: str, request: str) -> AgentPlan
        └─ Create plan using keyword-based heuristics
    
    def _is_multi_agent_worthy(self, request: str) -> bool
        ├─ Check request for keywords
        └─ Decide if parallelism justified
    
    def _create_multi_agent_plan(self, run_id: str, request: str) -> AgentPlan
        └─ Create plan with multiple agents
    
    def _fallback_lead_only_plan(self, run_id: str, request: str) -> AgentPlan
        └─ Create single-agent fallback plan
```

**Planning Flow**:
```
Request: "Find all security vulnerabilities and fix them"
    ↓
_is_multi_agent_worthy()
    ├─ Check keywords: "find", "security", "vulnerabilities", "fix"
    ├─ Multi-agent keywords found
    └─ Return True (parallelism is worthy)
    ↓
_create_multi_agent_plan()
    ├─ Create agent assignments:
    │   └─ researcher, implementer, reviewer
    ├─ Create task graph:
    │   ├─ t1: researcher scans code (depends_on: [])
    │   ├─ t2: implementer fixes issues (depends_on: [t1])
    │   ├─ t3: reviewer validates (depends_on: [t2])
    │   └─ t_synthesize: lead summarizes (depends_on: [t1, t2, t3])
    └─ Return AgentPlan
    ↓
validate_plan()
    ├─ Check all tasks have owners
    ├─ Check dependencies are valid
    ├─ Check no cycles
    └─ Return errors (if any)
    ↓
If valid:
    └─ Return (plan, is_valid=True)
Else:
    └─ Return (fallback_lead_only_plan, is_valid=False)
```

**Heuristic Rules**:
```python
Keywords that trigger multi-agent planning:
- "review"        (implies code review task)
- "analyze"       (implies multiple analysis perspectives)
- "test"          (implies verification needed)
- "investigate"   (implies comprehensive search)
- "multiple"      (explicitly mentions multiple)
- "concurrent"    (explicitly mentions concurrency)
- "parallel"      (explicitly mentions parallelism)
- "audit"         (implies thorough inspection)
- "check"         (implies verification)
- "validate"      (implies confirmation step)
```

**Depends On**:
- `schemas.AgentPlan`, `AgentTask`, `AgentAssignment`, `AgentRole`, `TaskStatus`
- `claude_planner.ClaudePlanner`
- `typing` (stdlib)

**Used By**:
- `orchestration_commands.OrchestrationCLI.team()`

---

### `claude_planner.py`
**Purpose**: Optional Claude AI-powered planning  
**Size**: ~80 lines  
**Language**: Python

**Responsibility**:
- Use Claude AI to create execution plans
- Handle API calls and errors
- Return structured plans

**Key Classes**:
```python
class ClaudePlanner:
    """Creates plans using Claude AI."""
    
    def __init__(self, max_workers: int = 4)
        └─ Initialize with max worker limit
    
    def create_plan(self, run_id: str, request: str) -> Optional[AgentPlan]
        ├─ Call Claude API with planning prompt
        ├─ Parse response into AgentPlan
        └─ Return plan or None if failed
```

**Note**: This requires Claude API access. Falls back to heuristic planning if unavailable.

**Depends On**:
- `schemas.AgentPlan`, etc.
- Claude API (external)

**Used By**:
- `planner.Planner.create_plan()` (when use_claude=True)

---

## Execution (`claude/team/`)

### `coordinator.py`
**Purpose**: Orchestrate entire run lifecycle  
**Size**: ~400 lines  
**Language**: Python

**Responsibility**:
- Manage run state machine
- Create and start workers
- Listen for events
- Manage task dependencies
- Synthesize final results
- Persist all state

**Key Classes**:
```python
class Coordinator:
    """Manages run orchestration and execution."""
    
    def __init__(self, run_id: str, workspace_dir: str = ".agent-workspace",
                 repo_path: str = ".")
        ├─ Initialize with run ID
        ├─ Create RunStore for persistence
        ├─ Create EventBus for communication
        └─ Subscribe to all events
    
    def execute_run(self, request: str, plan: AgentPlan,
                    use_fake_workers: bool = True,
                    use_worktrees: bool = False,
                    merge_strategy: str = "auto",
                    timeout: float = 30.0,
                    resume: bool = False) -> bool
        ├─ PHASE 1: PLANNING
        │   └─ Create run directory and save plan
        ├─ PHASE 2: RUNNING
        │   ├─ Create workers for each task
        │   ├─ Start workers in threads
        │   ├─ Wait for task completion
        │   └─ Handle dependencies
        ├─ PHASE 3: SYNTHESIZING
        │   └─ Collect results and create synthesis
        └─ PHASE 4: COMPLETED/FAILED
            └─ Update status and save final response
    
    def _execute_with_real_workers(self) -> None
        ├─ For each task in plan:
        │   └─ Create RealWorker (executes Claude API)
        ├─ Start all workers
        └─ Workers run in background threads
    
    def _wait_for_dependencies(self, timeout: float) -> bool
        ├─ Check each task's dependencies
        ├─ Wait until all dependencies completed
        └─ Timeout if takes too long
    
    def _synthesize(self) -> str
        ├─ Collect all agent outputs
        ├─ Create final summary
        └─ Return synthesis text
    
    def _on_event(self, event: AgentEvent) -> None
        ├─ Persist event to disk
        ├─ Update task status
        └─ Emit progress updates
```

**Run Lifecycle State Machine**:
```
                    ┌─────────────────────┐
                    │     PLANNING        │
                    │ Save plan to disk   │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │     RUNNING         │
                    │ Execute workers     │
                    │ Listen for events   │
                    └────┬──────────┬─────┘
                         ↓          ↓
          ┌──────────────────┐  FAILED
          │   SYNTHESIZING   │  (if error)
          │ Collect results  │
          └────────┬─────────┘
                   ↓
        ┌─────────────────────┐
        │     COMPLETED       │
        │ Save final response │
        └─────────────────────┘
```

**Task Execution Example**:
```
Plan created with 3 tasks:
├─ t1: Researcher scans (depends_on: [])
├─ t2: Implementer fixes (depends_on: [t1])
└─ t3: Reviewer validates (depends_on: [t2])

Execution:
1. Start: t1 (no dependencies)
   └─ event: agent_started
   └─ status: RUNNING

2. (t1 executing in background)

3. t1 completes
   └─ event: task_completed
   └─ status: COMPLETED

4. Check dependencies: t2 depends on t1 ✓
   └─ Start: t2

5. (t2 executing)

6. t2 completes
   └─ event: task_completed
   └─ status: COMPLETED

7. Check dependencies: t3 depends on t2 ✓
   └─ Start: t3

8. (t3 executing)

9. t3 completes
   └─ event: task_completed
   └─ status: COMPLETED

10. All tasks done, start synthesis
    └─ Collect all outputs
    └─ Create summary
    └─ Save to final-response.md

11. Mark run as COMPLETED
```

**Depends On**:
- `schemas.*` (all data models)
- `state_machine.RunStateMachine`
- `run_store.RunStore`
- `event_bus.EventBus`
- `real_worker.RealWorker`
- `mailbox_manager.MailboxManager`
- `session_manager.SessionManager`
- `worktree_manager.WorktreeManager`
- `merge_strategy.MergeStrategy`
- `change_validator.ChangeValidator`
- `time`, `pathlib` (stdlib)

**Used By**:
- `orchestration_commands.OrchestrationCLI.team()`

---

### `event_bus.py`
**Purpose**: Pub/sub event routing system  
**Size**: ~60 lines  
**Language**: Python

**Responsibility**:
- Route events from publishers to subscribers
- Support type-specific and wildcard subscriptions
- Thread-safe event delivery

**Key Classes**:
```python
class EventBus:
    """Publish/subscribe event system."""
    
    def __init__(self)
        └─ Initialize empty subscriber dict
    
    def subscribe(self, event_type: str, 
                  callback: Callable[[AgentEvent], None]) -> None
        └─ Register callback for specific event type
    
    def subscribe_all(self, callback: Callable[[AgentEvent], None]) -> None
        └─ Register callback for all event types
    
    def publish(self, event: AgentEvent) -> None
        ├─ Get all subscribers for event.event_type
        ├─ Call each with event
        └─ Catch and log exceptions
    
    def unsubscribe(self, event_type: str, callback: Callable) -> None
        └─ Remove callback from specific type
    
    def unsubscribe_all(self, callback: Callable) -> None
        └─ Remove callback from all types
```

**Thread Safety**:
- Uses `threading.Lock` on subscriber list
- Copy subscribers before iterating (prevent mutation during iteration)

**Usage Example**:
```python
# In Coordinator.__init__
event_bus = EventBus()
event_bus.subscribe_all(self._on_event)

# In RealWorker._execute
event = AgentEvent(
    event_id="evt-1",
    run_id="run-123",
    agent_id="researcher",
    task_id="t1",
    event_type="progress",
    payload={"message": "Scanning file.py"}
)
event_bus.publish(event)

# Coordinator receives via _on_event()
def _on_event(self, event: AgentEvent):
    if event.event_type == "progress":
        print(f"Progress: {event.payload['message']}")
```

**Depends On**:
- `schemas.AgentEvent`
- `typing`, `threading` (stdlib)

**Used By**:
- `coordinator.Coordinator` (subscribes to all)
- `real_worker.RealWorker` (publishes events)

---

### `real_worker.py`
**Purpose**: Execute task via Claude AI  
**Size**: ~120 lines  
**Language**: Python

**Responsibility**:
- Run agent task using Claude API
- Capture output and emit events
- Handle timeouts and errors
- Stream results to storage

**Key Classes**:
```python
class RealWorker:
    """Executes a task using real Claude API."""
    
    def __init__(self, agent_id: str, task: AgentTask, run_id: str,
                 cwd: Optional[str] = None,
                 timeout: float = 300.0,
                 on_event: Optional[Callable] = None,
                 store: Optional[RunStore] = None)
        ├─ Initialize with task details
        ├─ Create ClaudeRunner for API calls
        └─ Set up callbacks
    
    def start(self) -> None
        └─ Start execution in background thread
    
    def _execute(self) -> None
        ├─ Create system prompt for agent role
        ├─ Call ClaudeRunner.run() with task instructions
        ├─ Emit events to EventBus
        └─ Save output to RunStore
```

**Execution Flow**:
```
RealWorker.start()
    ↓
(background thread begins)
    ↓
_execute()
    ├─ Create system prompt:
    │   "You are a researcher agent.
    │    Objective: Find security vulnerabilities
    │    Instructions: ..."
    ├─ Create task prompt from task.instructions
    ├─ Emit: AgentEvent(event_type="agent_started")
    ├─ Call ClaudeRunner.run(system_prompt, task_prompt)
    │   └─ Makes API call to Claude
    │   └─ Gets streaming response
    │   └─ Yields tokens as they arrive
    ├─ Emit events as output arrives
    ├─ Emit: AgentEvent(event_type="task_completed")
    └─ Save all output to RunStore
```

**Depends On**:
- `schemas.AgentTask`
- `claude_runner.ClaudeRunner`
- `run_store.RunStore`
- `threading` (stdlib)

**Used By**:
- `coordinator.Coordinator._execute_with_real_workers()`

---

## Storage & Persistence (`claude/team/`)

### `run_store.py`
**Purpose**: Persistent storage for runs  
**Size**: ~300 lines  
**Language**: Python

**Responsibility**:
- Create and manage run directory structure
- Save/load plans, events, status
- Append events atomically
- Provide query interface for results

**Key Classes**:
```python
class RunStore:
    """Manages persistent run storage."""
    
    def __init__(self, workspace_dir: str = ".agent-workspace")
        └─ Initialize with workspace path
    
    def create_run_dir(self, run_id: str) -> None
        └─ Create .agent-workspace/runs/<run-id>/ and subdirs
    
    def save_request(self, run_id: str, request: str) -> None
        └─ Save request to request.md
    
    def save_plan(self, run_id: str, plan: AgentPlan) -> None
        └─ Serialize plan to plan.json
    
    def save_status(self, run_id: str, context: RunContext) -> None
        └─ Serialize status to status.json
    
    def append_event(self, run_id: str, event: AgentEvent) -> None
        └─ Append event as JSON line to events.jsonl
    
    def save_final_response(self, run_id: str, response: str) -> None
        └─ Save synthesis to final-response.md
    
    def load_plan(self, run_id: str) -> Optional[AgentPlan]
        └─ Load and deserialize plan.json
    
    def load_events(self, run_id: str) -> List[AgentEvent]
        └─ Load all lines from events.jsonl
    
    def load_status(self, run_id: str) -> Optional[RunContext]
        └─ Load and deserialize status.json
    
    def list_runs(self) -> List[str]
        └─ Return list of all run IDs
    
    def run_exists(self, run_id: str) -> bool
        └─ Check if run directory exists
    
    def get_run_dir(self, run_id: str) -> Path
        └─ Get Path object for run directory
```

**Directory Structure**:
```
.agent-workspace/runs/<run-id>/
├── request.md              # User's original request (text)
├── plan.json              # AgentPlan (JSON)
├── status.json            # RunContext (JSON)
├── events.jsonl           # AgentEvent lines (JSON Lines)
├── final-response.md      # Synthesis result (text)
└── agents/
    ├── researcher/
    │   ├── task.json      # AgentTask (JSON)
    │   ├── prompt.md      # System + user prompts (text)
    │   ├── output.jsonl   # Output lines (text lines or JSON)
    │   ├── status.json    # Task status (JSON)
    │   └── result.md      # Final result (text)
    ├── implementer/
    │   └── [same structure]
    └── reviewer/
        └── [same structure]
```

**File Formats**:

1. **request.md** (text)
   ```
   Find all security vulnerabilities in the codebase
   ```

2. **plan.json** (JSON)
   ```json
   {
     "run_id": "run-2026-08-03T10-30-45",
     "summary": "Analyze security vulnerabilities",
     "parallelism_justified": true,
     "synthesis_task_id": "t_synthesize",
     "agents": [...],
     "tasks": [...]
   }
   ```

3. **events.jsonl** (JSON Lines - one event per line)
   ```json
   {"event_id": "evt-1", "event_type": "agent_started", ...}
   {"event_id": "evt-2", "event_type": "progress", ...}
   {"event_id": "evt-3", "event_type": "task_completed", ...}
   ```

4. **output.jsonl** (Text lines - raw agent output)
   ```
   Found vulnerability: hardcoded password in auth.py:42
   Severity: HIGH
   ```

**Depends On**:
- `schemas.*` (data models)
- `pathlib`, `json` (stdlib)

**Used By**:
- `coordinator.Coordinator` (saves events, status)
- `orchestration_commands.OrchestrationCLI` (loads runs)

---

### `state_machine.py`
**Purpose**: Enforce valid run state transitions  
**Size**: ~80 lines  
**Language**: Python

**Responsibility**:
- Track current run state
- Validate state transitions
- Prevent invalid state changes

**Key Classes**:
```python
class RunStateMachine:
    """Enforces valid state transitions."""
    
    def __init__(self)
        └─ Initialize to PLANNING state
    
    def transition(self, new_status: RunStatus, reason: str) -> bool
        ├─ Check if transition is valid
        ├─ Update internal state
        └─ Return True if successful
    
    def current_state(self) -> RunStatus
        └─ Return current state
```

**Valid State Transitions**:
```
PLANNING → RUNNING
RUNNING → SYNTHESIZING
SYNTHESIZING → COMPLETED

Any state → FAILED
Any state → CANCELLED
```

**Invalid Transitions** (raises error):
```
COMPLETED → RUNNING  (can't restart)
FAILED → RUNNING     (can't retry)
RUNNING → PLANNING   (can't go back)
```

**Depends On**:
- `schemas.RunStatus`

**Used By**:
- `coordinator.Coordinator` (transitions states)

---

## Advanced Features (`claude/team/`)

### `mailbox_manager.py`
**Purpose**: Inter-agent messaging during execution  
**Size**: ~120 lines

**Responsibility**:
- Allow agents to send/receive messages
- Store messages persistently
- Retrieve messages during run

**Key Classes**:
```python
class MailboxManager:
    """Manages messaging between agents."""
    
    def send_message(self, to_agent_id: str, text: str) -> None
        └─ Send message to specific agent
    
    def get_messages(self, agent_id: str) -> List[str]
        └─ Retrieve all messages for agent
```

**Use Case**: Agent can ask for clarification during execution

---

### `session_manager.py`
**Purpose**: Enable run resumption from checkpoints  
**Size**: ~100 lines

**Responsibility**:
- Save completed task checkpoints
- Support resuming from last checkpoint
- Track session state

**Key Classes**:
```python
class SessionManager:
    """Manages session state and resumption."""
    
    def mark_task_completed(self, task_id: str, completed_ids: List[str]) -> None
        └─ Save which tasks completed
    
    def is_resumable(self) -> bool
        └─ Check if run can be resumed
    
    def load_checkpoint(self) -> Optional[Checkpoint]
        └─ Load last saved checkpoint
```

**Use Case**: If run is interrupted, resume from where it stopped

---

### `worktree_manager.py`
**Purpose**: Git worktree isolation for agents  
**Size**: ~150 lines

**Responsibility**:
- Create isolated git worktrees for each agent
- Manage worktree lifecycle
- Prevent conflicts between agent changes

**Key Classes**:
```python
class WorktreeManager:
    """Manages git worktrees for agent isolation."""
    
    def create_worktree(self, agent_id: str, branch: str) -> Path
        └─ Create new worktree for agent
    
    def delete_worktree(self, agent_id: str) -> None
        └─ Clean up worktree
    
    def get_worktree_path(self, agent_id: str) -> Path
        └─ Get path to agent's worktree
```

**Use Case**: Each agent modifies code in isolated git worktree, avoiding conflicts

---

### `merge_strategy.py`
**Purpose**: Define how to merge agent changes  
**Size**: ~130 lines

**Responsibility**:
- Implement different merge strategies
- Handle merge conflicts
- Validate merged code

**Strategies**:
```python
"auto"      # Automatic merge if no conflicts, abort if conflicts
"manual"    # Require human review before merging
"abort"     # Reject if any conflicts (safest)
```

**Depends On**:
- `worktree_manager.WorktreeManager`

---

### `change_validator.py`
**Purpose**: Validate agent changes before merging  
**Size**: ~100 lines

**Responsibility**:
- Check code quality of changes
- Check security of changes
- Verify tests pass
- Verify build succeeds

**Validates**:
- Code style
- Security issues
- Test coverage
- Build success
- Backwards compatibility

---

## External Integration (`claude/team/`)

### `claude_runner.py`
**Purpose**: Interface with Claude API  
**Size**: ~100 lines

**Responsibility**:
- Call Claude API
- Handle streaming responses
- Manage timeouts
- Handle authentication

**Key Classes**:
```python
class ClaudeRunner:
    """Interface to Claude API."""
    
    def run(self, prompt: str, system_prompt: str) -> bool
        ├─ Call Claude API
        ├─ Stream output
        └─ Return success/failure
```

**Requires**: Claude API key (ANTHROPIC_API_KEY environment variable)

---

## Configuration

### `pyproject.toml`
**Purpose**: Python project configuration  
**Framework**: setuptools (PEP 517/518 compliant)

**Key Sections**:
```toml
[project]
name = "coding-agent-workspace"
version = "0.4.0"
description = "Multi-agent orchestration system"
authors = [...]
dependencies = [
    "pydantic>=2.0,<3.0",
]

[project.scripts]
coding-agent-workspace = "workspace_cli.cli:main"
# ↑ Creates 'coding-agent-workspace' command in PATH

[tool.setuptools]
packages = ["workspace_cli", "claude", "claude.agents", "claude.tools", "claude.team"]
package-dir = {"claude" = ".claude"}
```

**To Install**:
```bash
pip install -e .
```

---

## Package Structure

```
coding-agent-workspace/
├── workspace_cli/              # User-facing CLI
│   ├── __init__.py
│   ├── cli.py                 # CLI parser and dispatcher
│   └── orchestration_commands.py  # Command handlers
│
├── .claude/                    # Core orchestration engine
│   ├── __init__.py
│   ├── config.py              # Configuration
│   │
│   ├── team/                  # Team orchestration
│   │   ├── __init__.py
│   │   ├── schemas.py         # Data models (Pydantic)
│   │   ├── planner.py         # Plan creation
│   │   ├── coordinator.py     # Execution orchestration
│   │   ├── event_bus.py       # Event routing
│   │   ├── real_worker.py     # Claude AI execution
│   │   ├── run_store.py       # Persistent storage
│   │   ├── state_machine.py   # State transitions
│   │   ├── mailbox_manager.py # Inter-agent messaging
│   │   ├── session_manager.py # Session checkpoints
│   │   ├── worktree_manager.py # Git isolation
│   │   ├── merge_strategy.py  # Merge policies
│   │   ├── change_validator.py # Validation
│   │   ├── claude_runner.py   # Claude API
│   │   ├── claude_planner.py  # Optional Claude planning
│   │   ├── terminal_multiplexer.py  # Terminal UI
│   │   └── worker_host.py     # Worker hosting
│   │
│   ├── agents/                # Agent definitions
│   │   ├── __init__.py
│   │   └── claude_terminal_manager.py
│   │
│   └── tools/                 # Utility tools
│       ├── __init__.py
│       ├── data_fetcher.py
│       ├── query_builder.py
│       ├── query_executor.py
│       ├── schema_reader.py
│       ├── thought.py
│       └── tool_result.py
│
├── pyproject.toml             # Project metadata & dependencies
├── ARCHITECTURE.md            # This file - System architecture
├── FILE_REFERENCE.md          # This file - File documentation
└── .agent-workspace/          # Output directory (created at runtime)
    └── runs/
        ├── <run-id>/
        │   ├── request.md
        │   ├── plan.json
        │   ├── status.json
        │   ├── events.jsonl
        │   ├── final-response.md
        │   └── agents/
        │       └── <agent-id>/
        │           ├── task.json
        │           ├── prompt.md
        │           ├── output.jsonl
        │           ├── status.json
        │           └── result.md
        └── ...
```

---

## Import Dependencies Summary

**Deepest Dependencies** (imported by everything):
- `schemas.py` → imported by all other modules

**Key Chains**:
```
planner.py → schemas.py
coordinator.py → schemas.py, planner.py, event_bus.py, real_worker.py, run_store.py
real_worker.py → schemas.py, claude_runner.py, run_store.py
orchestration_commands.py → planner.py, coordinator.py, run_store.py
```

**External Dependencies**:
- `pydantic>=2.0` (data validation)
- `pathlib`, `json`, `datetime`, `threading` (stdlib)
- Claude API (optional, for real workers)

---

## How to Extend

### Add New Agent Role
1. Update `AgentRole` enum in `schemas.py`
2. Update `_create_multi_agent_plan()` in `planner.py`

### Add New Event Type
1. Emit from `real_worker.py` or `coordinator.py`
2. Subscribe in `coordinator.py._on_event()`

### Add New Validation Rule
1. Add check to `AgentPlan.validate_plan()` in `schemas.py`

### Add New Merge Strategy
1. Subclass `MergeStrategy` in `merge_strategy.py`
2. Implement merge logic

---

**Last Updated**: 2026-08-04  
**Author**: Nguyen Le Dang Nguyen

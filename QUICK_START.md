# Quick Start Guide

Welcome to the Coding Agent Workspace! This guide gets you up and running in 5 minutes.

---

## Installation

```bash
# Navigate to project directory
cd coding-agent-workspace

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .

# Verify installation
coding-agent-workspace --help
```

---

## Basic Usage

### Run Your First Analysis

```bash
# Activate venv if not already active
source venv/bin/activate

# Run multi-agent analysis
coding-agent-workspace team "Find all security vulnerabilities in the codebase"

# View results
coding-agent-workspace runs                          # List all runs
coding-agent-workspace show <run-id>                 # Show run details
coding-agent-workspace output <run-id> researcher   # Show agent output
```

### Common Commands

```bash
# Analyze code quality
coding-agent-workspace team "Review code quality and suggest improvements"

# Find bugs
coding-agent-workspace team "Find bugs in authentication module"

# Security audit
coding-agent-workspace team "Identify all security vulnerabilities"

# Performance analysis
coding-agent-workspace team "Analyze performance bottlenecks and optimize"
```

---

## Understanding the System

The system consists of **4 main components**:

### 1. **Planner** → Creates execution plan
```
Request: "Find bugs"
    ↓
Planner analyzes keywords
    ↓
Creates AgentPlan:
  - Researcher agent (scans for bugs)
  - Implementer agent (suggests fixes)
  - Reviewer agent (validates findings)
  - Each agent has specific task with dependencies
```

### 2. **Coordinator** → Orchestrates execution
```
AgentPlan
    ↓
Creates RealWorker for each task
    ↓
Starts workers in parallel (background threads)
    ↓
Waits for completion (respects task dependencies)
```

### 3. **EventBus** → Pub/sub communication
```
Worker emits event: "task_completed"
    ↓
EventBus routes to all subscribers
    ↓
Coordinator updates task status
    ↓
RunStore persists event to disk
```

### 4. **RunStore** → Persistent storage
```
.agent-workspace/runs/<run-id>/
├── request.md            # Your request
├── plan.json            # Execution plan
├── status.json          # Run status
├── events.jsonl         # All events (1 per line)
├── final-response.md    # Results
└── agents/
    ├── researcher/
    │   ├── task.json
    │   ├── output.jsonl
    │   └── result.md
    ├── implementer/
    └── reviewer/
```

---

## File Organization

```
coding-agent-workspace/
├── workspace_cli/              # User-facing CLI
│   ├── cli.py                 # Command parser
│   └── orchestration_commands.py  # Command handlers
│
├── .claude/team/               # Core orchestration
│   ├── schemas.py             # Data models (KEY FILE)
│   ├── planner.py             # Plan creation
│   ├── coordinator.py         # Execution orchestration
│   ├── event_bus.py           # Pub/sub system
│   ├── real_worker.py         # Claude AI execution
│   ├── run_store.py           # Persistent storage
│   ├── state_machine.py       # State transitions
│   ├── mailbox_manager.py     # Inter-agent messaging
│   ├── session_manager.py     # Run resumption
│   ├── worktree_manager.py    # Git isolation
│   ├── merge_strategy.py      # Safe merging
│   ├── change_validator.py    # Validation
│   ├── claude_runner.py       # Claude API interface
│   └── claude_planner.py      # Optional Claude planning
│
└── Documentation (YOU ARE HERE)
    ├── README.md              # Project overview
    ├── ARCHITECTURE.md        # System design (START HERE)
    ├── FILE_REFERENCE.md      # Per-file documentation
    ├── QUICK_START.md         # This file
    └── CODEBASE_ANALYSIS.md   # Implementation details
```

---

## Key Concepts

### **AgentPlan**
A plan specifies:
- Which agents will execute
- What task each agent does
- Dependencies between tasks (agent B runs after agent A completes)
- Acceptance criteria (how to know task succeeded)

```python
plan = AgentPlan(
    agents=[researcher, implementer, reviewer],
    tasks=[
        Task(id="t1", owner=researcher, depends_on=[]),
        Task(id="t2", owner=implementer, depends_on=["t1"]),
        Task(id="t3", owner=reviewer, depends_on=["t2"]),
        Task(id="t_synthesize", owner="lead", depends_on=["t1", "t2", "t3"])
    ]
)
```

### **AgentTask**
A specific job an agent needs to do:
- `title`: Human-readable name
- `instructions`: What to do
- `acceptance_criteria`: Success conditions
- `depends_on`: Wait for these tasks to complete first

### **AgentEvent**
Communication between agents:
- `event_type`: What happened (task_completed, progress, error, etc.)
- `agent_id`: Who it's from
- `task_id`: Which task
- `payload`: Additional data

### **RunStatus**
State transitions:
```
PLANNING → RUNNING → SYNTHESIZING → COMPLETED
   (create plan)  (execute)  (collect results)

If error at any stage: → FAILED
If user cancels: → CANCELLED
```

---

## Modifying the System

### To Add a New Agent Role

1. **Edit** `.claude/team/schemas.py`:
```python
class AgentRole(str, Enum):
    RESEARCHER = "researcher"      # Already exists
    IMPLEMENTER = "implementer"    # Already exists
    TESTER = "tester"              # Add this
    CUSTOM_ROLE = "custom_role"    # Or this
```

2. **Edit** `.claude/team/planner.py`:
```python
def _create_multi_agent_plan(self, run_id: str, request: str) -> AgentPlan:
    # Add logic to include TESTER agent when appropriate
    if "test" in request.lower():
        agents.append(AgentAssignment(
            agent_id="tester",
            role=AgentRole.TESTER,
            objective="Write tests for the changes"
        ))
```

### To Add a New Validation Rule

1. **Edit** `.claude/team/schemas.py`:
```python
def validate_plan(self) -> List[str]:
    errors = []
    # ... existing checks ...
    
    # NEW: Check something custom
    if len(self.tasks) > 10:
        errors.append("Too many tasks: maximum 10 allowed")
    
    return errors
```

### To Add Custom Event Handling

1. **Edit** `.claude/team/coordinator.py`:
```python
def _on_event(self, event: AgentEvent) -> None:
    # ... existing code ...
    
    # NEW: Handle custom event type
    if event.event_type == "custom_event":
        print(f"Custom event received: {event.payload}")
        # Do something
```

---

## Running with Real Claude AI

To execute agents with real Claude API:

```bash
# Set your API key
export ANTHROPIC_API_KEY="your-key-here"

# Run with real workers
coding-agent-workspace team "Your request" --real-workers

# Limit number of parallel agents
coding-agent-workspace team "Your request" --real-workers --max-agents 2
```

**Note**: Requires valid Claude API key. Without it, uses fake workers (for testing).

---

## Understanding Output

After running a command, results are saved to:

```
.agent-workspace/runs/<run-id>/
```

### View Run Summary
```bash
coding-agent-workspace show <run-id>
```

Output:
```
[RUN] run-2026-08-03T10-30-45
   Status: completed
   Created: 2026-08-03T10:30:45

[PLAN] Analyze security vulnerabilities
   Agents: 3
   Tasks: 4

[EVENTS] (12):
   - [agent_started] researcher @ t1
   - [progress] researcher @ t1
   - [task_completed] researcher @ t1
   - [agent_started] implementer @ t2
   - ...
```

### View Agent Output
```bash
coding-agent-workspace output <run-id> researcher
```

Output: Raw output from the researcher agent

### View Final Results
```bash
cat .agent-workspace/runs/<run-id>/final-response.md
```

---

## Debugging

### Check Plan Validity

```bash
# The planner automatically validates plans
# If invalid, falls back to single-agent mode
# Check the output for validation errors
```

### View All Events

```bash
cat .agent-workspace/runs/<run-id>/events.jsonl | head -20
```

Each line is a JSON event you can parse:
```bash
cat .agent-workspace/runs/<run-id>/events.jsonl | \
  grep "task_completed" | \
  head -5
```

### Check Task Dependencies

```bash
cat .agent-workspace/runs/<run-id>/plan.json | \
  grep -A 3 "depends_on"
```

---

## Common Issues

### Issue: "Command not found: coding-agent-workspace"
**Solution**: Activate virtual environment first
```bash
source venv/bin/activate
```

### Issue: "No API key found"
**Solution**: Set ANTHROPIC_API_KEY
```bash
export ANTHROPIC_API_KEY="your-key"
```

### Issue: Run stuck in RUNNING state
**Solution**: Check for dependency issues
```bash
cat .agent-workspace/runs/<run-id>/plan.json
```

---

## Next Steps

1. **Read ARCHITECTURE.md** - Understand system design (5 min read)
2. **Read FILE_REFERENCE.md** - Learn what each file does (10 min read)
3. **Run a test** - `coding-agent-workspace team "test"`
4. **Modify code** - Start with `planner.py` to change planning logic
5. **Extend system** - Add new agent roles or validation rules

---

## Documentation Map

- **README.md** - Project overview
- **ARCHITECTURE.md** → Start here for system design
- **FILE_REFERENCE.md** → For per-file details
- **CODEBASE_ANALYSIS.md** → For implementation specifics
- **QUICK_START.md** → You are here

---

**Ready to get started?**

```bash
# 1. Install
pip install -e .

# 2. Run your first analysis
coding-agent-workspace team "Find bugs in the codebase"

# 3. View results
coding-agent-workspace show <run-id>

# 4. Read documentation
cat ARCHITECTURE.md
```

Happy coding! 🚀

---

**Last Updated**: 2026-08-04

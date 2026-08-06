# Claude Agent System Architecture

## Overview

The system has been restructured into a clean, scalable multi-agent architecture with clear separation of concerns:

### System Layers

```
.claude/
├── system/              - Core Infrastructure (Events, State, Storage)
├── agents/              - Multi-Agent Orchestration
│   ├── team_leader.py   - Master Coordinator
│   ├── team/            - Specialized Agents
│   ├── tools/           - Custom Tools Registry
│   └── orchestration/   - Coordination Logic
├── team/                - Backward Compatibility Layer
└── config.py            - Configuration
```

## System Package (`.claude/system/`)

Core infrastructure components shared across all agents:

- **event_bus.py** - Publish/subscribe event system for inter-agent communication
- **session_manager.py** - Session lifecycle and state management
- **state_machine.py** - Run state orchestration
- **worktree_manager.py** - Git worktree isolation and management
- **run_store.py** - Persistent run storage
- **mailbox_manager.py** - Inter-agent messaging
- **schemas.py** - Data models and type definitions

## Agents Package (`.claude/agents/`)

### Team Leader (`team_leader.py`)

Master orchestrator coordinating all agents:

```python
from claude.agents import TeamLeader

leader = TeamLeader()
team_config = leader.get_team_config()
```

**Responsibilities:**
- Coordinate work across all team members
- Manage task dependencies and sequencing
- Handle escalations and complex scenarios
- Provide unified interface to all agents

### Team Members (`.claude/agents/team/`)

Six specialized agents, each with specific expertise:

#### 1. Reviewer Agent
- **Role**: Code review and validation
- **Inputs**: Code diffs, file paths, context
- **Outputs**: Issues, suggestions, approval status
- **Tools**: git, code-analysis, linter

#### 2. Red Team Agent
- **Role**: Security and edge-case testing
- **Inputs**: Feature specs, code, threat model
- **Outputs**: Vulnerabilities, test cases, recommendations
- **Tools**: security-scan, testing, fuzzing

#### 3. Bug Fixer Agent
- **Role**: Issue identification and resolution
- **Inputs**: Test failures, error logs, code
- **Outputs**: Root causes, fix candidates, explanations
- **Tools**: debugging, code-analysis, testing

#### 4. Diagnostician Agent
- **Role**: System analysis and diagnostics
- **Inputs**: Error logs, metrics, traces
- **Outputs**: Diagnosis, root cause, recommendations
- **Tools**: logging, metrics, tracing

#### 5. Coder Agent
- **Role**: Implementation and execution
- **Inputs**: Task specs, requirements, context
- **Outputs**: Code changes, test coverage, documentation
- **Tools**: git, file-ops, compiler

#### 6. Group Sales Manager Agent
- **Role**: Resource orchestration and scheduling
- **Inputs**: Task queue, available resources, constraints
- **Outputs**: Allocation plan, schedule, resource utilization
- **Tools**: queue-manager, resource-monitor, scheduler

### Base Agent (`base_agent.py`)

Abstract base class providing common interface:

```python
from claude.agents.base_agent import BaseAgent

class MyAgent(BaseAgent):
    SYSTEM_PROMPT = "..."
    
    async def execute(self, task):
        # Implementation
        return TaskResult(status="success", output={})
```

### Tools Registry (`.claude/agents/tools/`)

Extensible custom tools system:

```python
from claude.agents.tools import get_registry, register_tool

registry = get_registry()
tools = registry.list_tools()
registry.register(my_custom_tool)
```

## Orchestration Package (`.claude/agents/orchestration/`)

Coordination utilities:

- **coordinator.py** - Run lifecycle and task execution management
- **merge_strategy.py** - Safe merging of multiple agent worktrees

```python
from claude.agents.orchestration import Coordinator

coordinator = Coordinator(run_id="run_123")
```

## Backward Compatibility (`.claude/team/`)

The original `team/` directory provides backward compatibility:

```python
# These still work (re-exported from system and orchestration)
from claude.team import (
    EventBus,
    RunStore,
    SessionManager,
    Coordinator,
    MergeStrategy,
)
```

## Usage Examples

### Initialize the Team

```python
from claude.agents import TeamLeader

leader = TeamLeader()
team_config = leader.get_team_config()
print(leader.list_agents())  # ['reviewer', 'red_team', 'bug_fixer', ...]
```

### Get Specific Agent

```python
from claude.agents import get_agent

reviewer = get_agent("reviewer")
coder = get_agent("coder")
```

### Register Custom Tool

```python
from claude.agents.tools import register_tool, BaseTool

class MyTool(BaseTool):
    def __init__(self):
        super().__init__("my_tool", "Description")
    
    def execute(self, **kwargs):
        return {"result": "..."}
    
    def get_input_schema(self):
        return [...]
    
    def get_output_schema(self):
        return ToolOutput(...)

register_tool(MyTool())
```

### Access System Infrastructure

```python
from claude.system import EventBus, SessionManager, RunStore

event_bus = EventBus()
session_mgr = SessionManager(run_id="run_123", store=run_store, event_bus=event_bus)

event_bus.subscribe("agent_event", lambda event: print(event))
```

## Integration Points

### For External Code

1. **Import system infrastructure**: `from claude.system import EventBus, ...`
2. **Access agents**: `from claude.agents import get_agent, list_agents`
3. **Register tools**: `from claude.agents.tools import register_tool`
4. **Backward compatibility**: `from claude.team import Coordinator, ...`

### For New Agents

1. Extend `BaseAgent` in `.claude/agents/team/`
2. Define `SYSTEM_PROMPT` and `execute()` method
3. Declare tools in `DEFAULT_CONFIG`
4. Register in `TeamLeader.teammates`

## Migration Notes

### For Projects Using the Old `.claude.team` Module

No changes required - backward compatibility layer automatically provides:
- `from claude.team import EventBus, RunStore, ...`
- `from claude.team import Coordinator, MergeStrategy, ...`
- `from claude.team import Planner, RealWorker, ...`

All old imports continue to work. Gradually migrate to new imports:

**Old**: `from claude.team import EventBus`
**New**: `from claude.system import EventBus`

### For Custom Agents

Move custom agents to `.claude/agents/team/` following the `BaseAgent` pattern:

1. Create `{agent_name}.py` in `.claude/agents/team/`
2. Import and expose in `.claude/agents/team/__init__.py`
3. Register in `TeamLeader.teammates`

## Architecture Benefits

✓ **Clear separation of concerns** - System vs agents vs orchestration
✓ **Extensible** - Easy to add new agents and tools
✓ **Testable** - Each agent has defined interface
✓ **Maintainable** - Reduced code duplication
✓ **Backward compatible** - No breaking changes
✓ **Scalable** - Foundation for distributed coordination

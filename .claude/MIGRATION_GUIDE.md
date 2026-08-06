# Migration Guide: System Architecture Refactoring

## Quick Start

The system has been successfully restructured. **No changes required for existing code** - full backward compatibility maintained.

### New Structure

```
.claude/
├── system/              ← Core infrastructure (EventBus, SessionManager, etc.)
├── agents/              ← Multi-agent system
│   ├── team_leader.py   ← Master orchestrator
│   ├── team/            ← 6 specialized agents (reviewer, coder, etc.)
│   ├── tools/           ← Custom tools registry
│   └── orchestration/   ← Coordination logic
└── team/                ← Backward compatibility layer (re-exports)
```

## For Existing Code

**No changes required.** All old imports continue to work:

```python
# These still work (backward compatible)
from claude.team import EventBus, RunStore, Coordinator
```

## For New Code

Use the new, cleaner imports:

```python
# System infrastructure
from claude.system import EventBus, SessionManager, RunStore

# Agents and coordination
from claude.agents import TeamLeader, get_agent, list_agents
from claude.agents.tools import register_tool, get_registry

# Orchestration
from claude.team import Coordinator  # Via backward compat layer
```

## Adding Custom Agents

1. Create agent file in `.claude/agents/team/{agent_name}.py`:

```python
from claude.agents.base_agent import BaseAgent, AgentConfig
from dataclasses import dataclass

@dataclass
class MyAgentConfig(AgentConfig):
    name: str = "my_agent"

class MyAgent(BaseAgent):
    SYSTEM_PROMPT = "..."
    DEFAULT_CONFIG = MyAgentConfig()
    
    async def execute(self, task):
        # Implementation
        return TaskResult(status="success", output={})
```

2. Register in `.claude/agents/team/__init__.py`:

```python
from .my_agent import MyAgent

__all__ = [
    # ... existing agents ...
    "MyAgent",
]
```

3. Add to TeamLeader in `.claude/agents/team_leader.py`:

```python
from .team import MyAgent

self.teammates["my_agent"] = MyAgent()
```

## Adding Custom Tools

1. Create tool in `.claude/agents/tools/`:

```python
from claude.agents.tools.base_tool import BaseTool, ToolInput, ToolOutput

class MyTool(BaseTool):
    def __init__(self):
        super().__init__("my_tool", "Description")
    
    def execute(self, **kwargs):
        return {"result": "..."}
    
    def get_input_schema(self):
        return [ToolInput(name="param", type="str", description="...")]
    
    def get_output_schema(self):
        return ToolOutput(name="result", type="str", description="...")
```

2. Register globally:

```python
from claude.agents.tools import register_tool
register_tool(MyTool())
```

## Import Migration Path

Gradually migrate your code from old to new imports:

### Old → New Mappings

```python
# System infrastructure
from claude.team import EventBus           # → from claude.system import EventBus
from claude.team import RunStore           # → from claude.system import RunStore
from claude.team import SessionManager     # → from claude.system import SessionManager
from claude.team import RunStateMachine    # → from claude.system import RunStateMachine

# Orchestration
from claude.team import Coordinator        # → Still via backward compat OR
                                          # → from claude.agents.orchestration import Coordinator
from claude.team import MergeStrategy      # → Same as above

# Agents (new)
from claude.team import Planner            # → (Still in team, no move needed)
from claude.team import RealWorker         # → (Still in team, no move needed)
```

## Breaking Changes

**None.** This is a 100% backward-compatible refactoring.

## Testing

Verify your code still works:

```bash
python3 -m pytest tests/  # Or your test command
```

All imports continue to work as before.

## Questions or Issues?

Refer to:
- `ARCHITECTURE.md` - System overview and design
- `REFACTORING_COMPLETE.md` - Migration status details

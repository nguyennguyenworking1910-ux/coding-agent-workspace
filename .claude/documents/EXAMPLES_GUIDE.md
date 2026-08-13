# Examples

Example scripts demonstrating how to use the Claude agent system.

## Available Examples

### Scheduler Agent

**File:** `scheduler_example.py`

Demonstrates how to use the SchedulerAgent with Google Calendar integration:

1. **Basic scheduling** - Schedule a meeting at a specific time
2. **Flexible scheduling** - Schedule with partial information
3. **Direct tool usage** - Use scheduler tools directly

**Requirements:**
- Google Calendar API credentials (see `.claude/documents/SETUP.md`)
- `pip install -r .claude/agents/requirements.txt`

**Run:**
```bash
cd .claude/examples
python3 scheduler_example.py
```

## Running Examples

All examples are designed to be run from the `.claude/examples/` directory or via Python imports:

```python
# Direct import
from claude.examples.scheduler_example import main
import asyncio
asyncio.run(main())

# Or run directly
python3 .claude/examples/scheduler_example.py
```

## Creating New Examples

1. Create a new Python file in this folder: `new_agent_example.py`
2. Import the agent: `from ..agents.team.new_agent import NewAgent`
3. Create example usage in an `async def main()` function
4. Add documentation to this README

## Architecture Examples

The examples demonstrate:
- How to initialize agents
- How to execute tasks
- How to use tools directly
- How to integrate with external services
- Best practices for agent usage

## Troubleshooting

If imports fail:
1. Ensure you're running from the project root (`.claude/`)
2. Ensure all dependencies are installed
3. Check that credentials are properly configured
4. See individual example files for setup instructions

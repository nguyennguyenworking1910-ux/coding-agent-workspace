# Multi-Terminal Agent Execution Guide

## Overview

The multi-terminal feature allows you to run agents in separate terminal windows, enabling real-time tracking of what each agent is doing during execution.

## Why Multi-Terminal?

### Standard Mode (Single Terminal)
- All agents run silently in background
- Only final results shown in main terminal
- Hard to debug or monitor agent progress

### Multi-Terminal Mode
- ✓ Each agent gets its own terminal window
- ✓ See real-time output from each agent
- ✓ Track agent reasoning and decisions
- ✓ Better for debugging and understanding workflows
- ✓ Perfect for development and testing

## How It Works

```
User Command
    ↓
workspace_cli --multi-terminal solve "Fix bug"
    ↓
CLI creates MultiTerminalOrchestrator
    ↓
Determines task type → selects agents to spawn
    ↓
TerminalManager spawns separate terminals:
    • Terminal 1: Diagnostician Agent
    • Terminal 2: Bug Fixer Agent
    • Terminal 3: Reviewer Agent
    ↓
Each terminal shows:
    - Agent name and task
    - Reasoning process
    - Actions taken
    - Results
    ↓
User can observe all terminals simultaneously
```

## Usage

### Basic Multi-Terminal Execution

```bash
cd C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace

# Spawn agents in separate terminals
python -m workspace_cli --multi-terminal solve "Find and fix the authentication bug"

# Other commands also support multi-terminal
python -m workspace_cli --multi-terminal analyze "Check my code for security issues"
```

### Command Options

```bash
# Standard single-terminal mode (default)
python -m workspace_cli solve "task"

# Multi-terminal mode (new!)
python -m workspace_cli --multi-terminal solve "task"

# Multi-terminal with custom workspace
python -m workspace_cli --multi-terminal --workspace ./my-workspace solve "task"
```

## What You'll See

### Main Terminal Output:
```
==============================================================
🚀 Team Leader Agent Executing: solve
📋 Task: Find and fix the authentication bug

🖥️  MULTI-TERMINAL MODE
    Spawning agents in separate terminal windows...

============================================================
[2026-07-29...] [START] Multi-terminal execution started
[2026-07-29...] [CLASSIFY] Task classified as: bug_analysis
[2026-07-29...] [PLAN] Spawning agents: diagnostician, bug_fixer, reviewer
[2026-07-29...] [SPAWN] Spawning diagnostician in terminal
✓ Terminal spawned for diagnostician
[2026-07-29...] [SPAWN] Spawning bug_fixer in terminal
✓ Terminal spawned for bug_fixer
[2026-07-29...] [SPAWN] Spawning reviewer in terminal
✓ Terminal spawned for reviewer

==============================================================
MULTI-TERMINAL EXECUTION
==============================================================
Run ID: abc12345
Trace ID: xyz98765
Spawned Agents: diagnostician, bug_fixer, reviewer
==============================================================

✓ Check the open terminals for real-time agent output
✓ Each agent is running in its own terminal window
```

### Agent Terminal Output (Example - Diagnostician):
```
======================================================================
AGENT: DIAGNOSTICIAN
RUN ID: abc12345
TASK: Find and fix the authentication bug
======================================================================

Analyzing authentication module...

Findings:
  - Potential security issue in token validation
  - Missing null check on user object
  - SQL injection vulnerability in query builder

Thinking Process:
  Examining auth.py for common vulnerabilities...
  Found 3 potential issues...

[RESULT] SUCCESS
Status: analysis_complete

[Press Enter to close...]
```

### Agent Terminal Output (Example - Bug Fixer):
```
======================================================================
AGENT: BUG_FIXER
RUN ID: abc12345
TASK: Find and fix the authentication bug
======================================================================

Planning fixes for identified issues...

Planning:
  1. Fix token validation logic
  2. Add null checks
  3. Sanitize SQL queries

Planning to modify:
  - auth.py (3 changes)
  - database.py (2 changes)

[RESULT] SUCCESS
Status: ready_to_fix

[Press Enter to close...]
```

## Task Classification

The multi-terminal orchestrator automatically classifies tasks and determines which agents to spawn:

### Bug Analysis Tasks
**Keywords:** bug, error, issue, problem, crash, broken, fail, exception, debug, diagnose

**Agents Spawned:**
- Diagnostician (analyze the issue)
- Bug Fixer (implement the fix)
- Reviewer (validate the fix)

### Quality Tasks
**Keywords:** quality, review, validate, check, test, refactor, structure, design, architecture

**Agents Spawned:**
- Diagnostician (identify quality issues)
- Reviewer (validate improvements)

### General Tasks
**Default Agents:** Diagnostician only

## Execution Log

Each execution is logged and saved to `.agent-workspace/runs/{run-id}.json`:

```json
{
  "run_id": "run-2026-07-29T14-30-45.123456",
  "timestamp": "2026-07-29T14:30:45.123456",
  "task": "Find and fix the authentication bug",
  "result": "MULTI-TERMINAL EXECUTION REPORT\n..."
}
```

## Platform Support

- **Windows:** Uses `start cmd /k` to open new command prompts
- **macOS:** Uses `open -a Terminal`
- **Linux:** Uses `gnome-terminal`

## Troubleshooting

### Terminals Not Opening
- **Windows:** Ensure `cmd` is accessible from your PATH
- **macOS:** Ensure Terminal.app is in `/Applications`
- **Linux:** Ensure `gnome-terminal` is installed

### Agent Scripts Not Found
- Check that `.claude/agent_runners/` directory exists
- Verify write permissions in `.claude/` directory
- Check Python path configuration in your environment

### Agents Not Executing
- Ensure `.claude` directory is in Python path
- Verify agent implementations in `.claude/agents/technical/`
- Check that `config.py` is accessible

## Cleanup

Temporary agent runner scripts are automatically cleaned up after execution.

## Integration with Existing Workflows

Multi-terminal mode is backward compatible:
- Without `--multi-terminal` flag, operates normally in single terminal
- All existing commands and workflows continue to work
- Can mix and match multi-terminal and standard modes

## Advanced Usage

### Custom Workspace Directory
```bash
python -m workspace_cli --multi-terminal --workspace ./debug-runs solve "task"
```

### Using Specific Commands
```bash
# Analyze with multi-terminal
python -m workspace_cli --multi-terminal analyze "check auth.py"

# Fix with multi-terminal
python -m workspace_cli --multi-terminal fix "fix the SQL injection"

# Review with multi-terminal
python -m workspace_cli --multi-terminal review "review changes"
```

## Example Workflow

1. **Identify a bug:**
   ```
   You notice a security vulnerability in your code
   ```

2. **Launch multi-terminal analysis:**
   ```bash
   python -m workspace_cli --multi-terminal solve "Fix SQL injection in user query"
   ```

3. **Watch agents work:**
   - Main terminal shows the orchestration flow
   - 3 separate terminals open showing:
     - Diagnostician analyzing the vulnerability
     - Bug Fixer implementing the fix
     - Reviewer validating the fix

4. **Review results:**
   - Check the execution log in main terminal
   - Each agent terminal shows its findings
   - Results saved to `.agent-workspace/runs/`

5. **Take action:**
   - Review the changes made by Bug Fixer
   - Test the fixes
   - Commit if satisfied

## Performance Notes

- Initial spawn time: ~2-3 seconds per agent
- Each agent runs independently without blocking others
- All terminals must be manually closed (press Enter or close window)
- Cleanup happens automatically after execution

## Next Steps

- Run your first multi-terminal session
- Experiment with different task types
- Monitor agent behavior and workflows
- Use insights to improve agent prompts and logic

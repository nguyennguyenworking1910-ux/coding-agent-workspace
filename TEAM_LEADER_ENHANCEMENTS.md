# Team Leader Agent Enhancements

## Overview

All four requested enhancements have been implemented for the Claude Code agent system:

1. ✅ **Multi-terminal as DEFAULT**
2. ✅ **Prominent Team Leader Output**
3. ✅ **Visible Agent Communication**
4. ✅ **Separate Terminal Handlers**

---

## 1. Multi-Terminal Mode (DEFAULT)

**Changed from:** `--multi-terminal` flag (optional)
**Changed to:** Default behavior (use `--single-terminal` to disable)

```bash
# Default: Multi-terminal mode
coding-agent-workspace solve "task"

# Legacy: Single terminal (if needed)
coding-agent-workspace solve "task" --single-terminal
```

**Implementation:**
- Updated CLI parser to invert the flag logic
- Multi-terminal spawning is now enabled by default
- Pass `multi_terminal=True` to Team Leader automatically

**Files Changed:**
- `workspace_cli/cli.py`: Flag inverted, default changed

---

## 2. Prominent Team Leader Output

**Added visible Team Leader coordination messages:**

```
======================================================================
TEAM LEADER AGENT - COORDINATION CENTER
======================================================================
Run ID: run-2026-07-29T15-50-29.865214
Trace ID: 2adb074a
======================================================================

[TEAM LEADER THINKING] Task Classification
  Classified as 'quality' task

[TEAM LEADER THINKING] Agent Selection
  Selected agents: diagnostician, reviewer

[TEAM COMPOSITION]
  - DIAGNOSTICIAN: Issue Scanner & Analyzer
  - REVIEWER: Quality Validator

[WORKFLOW STEPS]
  Step 1: DIAGNOSTICIAN
    Task: Review code quality and structure
  Step 2: REVIEWER
    Task: Review and validate findings/changes

[AGENT EXECUTION STARTING]
```

**Implementation:**
- `_display_header()`: Shows Team Leader header with Run/Trace IDs
- `_show_thinking()`: Displays Team Leader thinking process
- `execute()`: Shows workflow steps and team composition prominently
- All critical decisions now printed to stdout

**Files Changed:**
- `.claude/agents/technical/team_leader.py`: Added display methods

---

## 3. Visible Agent Communication Channels

**New communication system shows all agent interactions:**

```
[i] [TEAM_LEADER] Task received: test workspace
[*] [TEAM_LEADER] Task classified: quality
[*] [TEAM_LEADER] Selected agents: ['diagnostician', 'reviewer']
[*] [TEAM_LEADER] Workflow ready for execution
[*] [TEAM_LEADER] Spawning diagnostician agent
[*] [TEAM_LEADER] diagnostician completed
[i] [TEAM_LEADER] All agents completed
```

**Message Types:**
- `[i]` - Info messages
- `[*]` - Decisions / important actions
- `[!]` - Findings / discoveries
- `[?]` - Warnings
- `[x]` - Errors

**Implementation:**
- `agent_communication.py`: Centralized message bus
  - `AgentMessage`: Represents individual messages
  - `AgentCommunicationChannel`: Manages message routing
  - `broadcast_message()`: Global broadcast function
- All agents subscribe to channel for real-time updates
- Messages persisted for audit trail

**Files Created:**
- `.claude/agents/agent_communication.py`: Complete communication system

**Usage:**
```python
from agent_communication import broadcast_message

# Send message from any agent
broadcast_message(run_id, "agent_name", "message text", "decision")
```

---

## 4. Separate Claude Code Terminal Handlers

**New terminal manager for opening Claude Code terminals per agent:**

```
[SPAWN_TERMINAL] Opening terminal for DIAGNOSTICIAN
  Terminal ID: diagnostician_run-2026-07-29T15-50-29.865214_1
  Task: Review code quality and structure
```

**Implementation:**
- `claude_terminal_manager.py`: Manages terminal lifecycle
  - `open_agent_terminal()`: Opens new terminal for agent
  - `get_terminal_status()`: Check terminal status
  - `list_active_terminals()`: Monitor all terminals
- Auto-generates Python scripts for agent execution
- Supports Claude Code native terminal integration

**Files Created:**
- `.claude/agents/claude_terminal_manager.py`: Terminal management

**Usage:**
```python
from claude_terminal_manager import ClaudeTerminalManager

manager = ClaudeTerminalManager()
terminal_id = manager.open_agent_terminal("diagnostician", task, run_id)
```

---

## Complete Workflow (With All 4 Enhancements)

```
User: coding-agent-workspace solve "analyze this workspace"
  ↓
[MULTI-TERMINAL DEFAULT ACTIVATED]
System prints: "Team Leader will coordinate agent execution"
  ↓
[PROMINENT TEAM LEADER OUTPUT]
Team Leader displays:
  - Header with Run ID / Trace ID
  - Thinking process
  - Agent selection
  - Workflow steps
  ↓
[VISIBLE AGENT COMMUNICATION]
System shows all decisions and messages:
  [*] Task classified: quality
  [*] Selected agents: [diagnostician, reviewer]
  [*] Spawning diagnostician agent
  ↓
[SEPARATE TERMINAL HANDLERS]
System opens terminals for each agent:
  Terminal ID: diagnostician_run-xxx_1
  Terminal ID: reviewer_run-xxx_2
  ↓
Agents execute in parallel with real-time output
  ↓
System shows completion and results saved
```

---

## Files Modified

```
NEW FILES:
  - .claude/agents/agent_communication.py (communication system)
  - .claude/agents/claude_terminal_manager.py (terminal management)
  - TEAM_LEADER_ENHANCEMENTS.md (this document)

MODIFIED FILES:
  - .claude/agents/technical/team_leader.py (display + communication)
  - workspace_cli/cli.py (default multi-terminal)
  - pyproject.toml (package config)
  - .claude/agents/technical/diagnostician.py (filter fix from earlier)

UNCHANGED:
  - Agent logic and core functionality
  - Workflow orchestration
  - Results persistence
```

---

## Usage Examples

### Basic Usage (Multi-terminal default)
```bash
coding-agent-workspace solve "Find bugs in the code"
# Automatically spawns Team Leader + Diagnostician + Bug Fixer + Reviewer
# Each agent in its own Claude Code terminal
# Visible coordination messages shown in main terminal
```

### With Communication Only (Single Terminal)
```bash
coding-agent-workspace solve "Analyze the codebase" --single-terminal
# All agents run in single terminal
# But you still see all Team Leader coordination messages
# And agent communication messages
```

### Check Terminal Status
```python
from claude_terminal_manager import ClaudeTerminalManager

manager = ClaudeTerminalManager()
active = manager.list_active_terminals()
# Returns: {"diagnostician_xxx_1": {"agent": "diagnostician", "status": "spawned"}, ...}
```

### Subscribe to Agent Messages
```python
from agent_communication import get_channel, AgentMessage

channel = get_channel(run_id)

def on_message(msg: AgentMessage):
    print(f"Message from {msg.sender}: {msg.message}")

channel.subscribe("my_agent", on_message)
```

---

## Key Benefits

✅ **Clarity**: Users now see exactly what Team Leader is thinking  
✅ **Transparency**: Agent communication visible in real-time  
✅ **Scalability**: Terminal handlers support multiple parallel agents  
✅ **Integration**: Seamless Claude Code terminal integration  
✅ **Auditability**: All messages logged in communication channel  

---

## Testing

To test all four enhancements:

```bash
# Test 1: Multi-terminal default
coding-agent-workspace solve "test task"
# Verify: Should open multiple terminals automatically

# Test 2: Prominent output
# Verify: Team Leader header and thinking visible

# Test 3: Agent communication
# Verify: [i], [*], [!], [?], [x] messages shown

# Test 4: Terminal handlers
# Verify: Terminal IDs printed (diagnostician_xxx_1, etc)

# Test single-terminal mode
coding-agent-workspace solve "test" --single-terminal
# Verify: All agents run sequentially in one terminal but still show communication
```

---

## Next Steps (Optional)

- [ ] Add agent-to-agent messaging (not just Team Leader)
- [ ] Implement agent voting/consensus on decisions
- [ ] Add dashboard showing all active terminals
- [ ] Support parallel agent execution with result aggregation
- [ ] Implement agent error handling and recovery

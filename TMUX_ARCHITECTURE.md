# Tmux-Based Agent Execution Architecture

## Overview

The Coding Agent Workspace now uses **tmux (Terminal Multiplexer)** to manage agent execution through split panes instead of spawning separate terminal windows. This approach provides:

- **Unified Session**: All agents run in a single tmux session for a given execution
- **Organized Panes**: Each agent gets its own window within the session
- **Better Resource Management**: No need for external terminal windows
- **Cross-Platform Support**: Works on macOS, Linux, and Windows (via WSL)

---

## Architecture

### Session Management

```
Tmux Session: agents-{run_id}
├── Window 1: agent-1 (Diagnostician)
├── Window 2: agent-2 (BugFixer)
├── Window 3: agent-3 (Reviewer)
└── Window N: agent-N (Additional agents)
```

Each execution creates a unique tmux session using the run_id as the session identifier:
- **Session Name Format**: `agents-{run_id}`
- **Window Names**: `agent-{sequence_number}`
- **Example**: `agents-a1b2c3d4` with windows `agent-1`, `agent-2`, etc.

### Pane Lifecycle

1. **Initialization**: ClaudeTerminalManager ensures tmux session exists
2. **Pane Creation**: Team Leader creates new window for each agent
3. **Execution**: Agent script runs in the pane via `tmux send-keys`
4. **Persistence**: Panes remain open for inspection after completion
5. **Cleanup**: User can manually close the tmux session when done

---

## Components

### ClaudeTerminalManager (Updated)

```python
class ClaudeTerminalManager:
    def __init__(self, session_name: str = "coding-agents"):
        # Creates tmux session if needed
        # Ensures session is ready for pane creation
        
    def open_agent_terminal(self, agent_name, task, run_id):
        # Creates new window in tmux session
        # Sends execution command to window
        # Returns terminal_id for tracking
        
    def _create_tmux_pane(self, script_path, agent_name, terminal_id):
        # Creates tmux window via tmux new-window
        # Executes agent script via tmux send-keys
        # Handles tmux command execution
```

### Key Methods

**`_ensure_tmux_session()`**
- Checks if tmux session exists
- Creates new session with specified name if needed
- Configures session dimensions (200x50)

**`_create_tmux_pane()`**
- Creates new window in session: `tmux new-window -t session -n window_name`
- Sends Python command: `tmux send-keys -t session:window "python script.py" Enter`
- Returns success status

### TeamLeaderAgent Integration

```python
# Initialize with run_id as session identifier
self.terminal_manager = ClaudeTerminalManager(session_name=f"agents-{self.run_id}")

# Open pane for each agent
terminal_id = self.terminal_manager.open_agent_terminal(
    agent_name="diagnostician",
    task="analyze code",
    run_id=self.run_id
)
```

---

## Execution Flow

### Example: `coding-agent-workspace solve "fix bug"`

```
1. CLI receives task
   ↓
2. AgentOrchestrator creates Team Leader with run_id
   ↓
3. Team Leader initialization:
   - Creates ClaudeTerminalManager(session_name="agents-run_id")
   - Manager ensures tmux session exists
   ↓
4. Team Leader classifies task and selects agents
   ↓
5. For each selected agent:
   - Team Leader calls terminal_manager.open_agent_terminal()
   - Manager creates new window in tmux session
   - Manager sends "python script.py" to the window
   - Script starts executing in tmux pane
   ↓
6. Agents execute in parallel within same tmux session
   ↓
7. Results collected and saved to workspace
   ↓
8. User can view results in tmux panes (they remain open)
```

---

## Tmux Commands Reference

### Session Management

```bash
# List all sessions
tmux list-sessions

# Attach to session
tmux attach-session -t agents-run_id

# Kill session
tmux kill-session -t agents-run_id
```

### Window Management (Automatic)

```bash
# Create new window in session
tmux new-window -t agents-run_id -n agent-1

# List windows in session
tmux list-windows -t agents-run_id

# Select window
tmux select-window -t agents-run_id:agent-1
```

### Command Execution (Automatic)

```bash
# Send keys to window
tmux send-keys -t agents-run_id:agent-1 "python script.py" Enter

# Send command and wait for execution
tmux send-keys -t session:window "command" Enter
```

---

## Advantages Over Subprocess Terminal Spawning

| Aspect | Subprocess (Old) | Tmux (New) |
|--------|------------------|-----------|
| **Window Management** | Multiple separate windows | Single organized session |
| **Resource Usage** | Higher (separate terminals) | Lower (multiplexed panes) |
| **Visibility** | Scattered across screen | Organized in one session |
| **Session Tracking** | Difficult to track | Easy via session name |
| **Inspection** | Windows close on completion | Panes remain for review |
| **Platform Support** | Inconsistent across OS | Consistent via tmux |
| **Parallel Execution** | Native to each OS | Unified via tmux |

---

## Platform Support

### Linux & macOS
- **Native tmux support**: Directly available
- **Installation**: `apt-get install tmux` (Linux) or `brew install tmux` (macOS)
- **Usage**: Full feature support

### Windows (Windows 11 Pro)
- **Supported via WSL**: Windows Subsystem for Linux
- **Installation**: Install WSL2, then `apt-get install tmux`
- **Usage**: Full feature support within WSL terminal

### Fallback Behavior
- If tmux is not available, the system logs a warning
- Future enhancement: Add fallback to single-window execution

---

## Usage Example

### Running an Agent Task

```bash
# Start agent execution
coding-agent-workspace solve "fix authentication bug"

# Team Leader starts agents in tmux session "agents-{run_id}"
# Each agent gets its own window

# In another terminal, view the tmux session
tmux attach-session -t agents-{run_id}

# Use Ctrl+B then arrow keys to navigate between agent windows
# View agent output and completion status in real-time
```

### Viewing Results

```bash
# List all active sessions
tmux list-sessions

# Attach to a specific session
tmux attach -t agents-a1b2c3d4

# Navigate between windows in tmux:
# Ctrl+B c   - Create new window
# Ctrl+B n   - Next window
# Ctrl+B p   - Previous window
# Ctrl+B 0-9 - Select window by number
# Ctrl+B d   - Detach (leave session running)
```

### Cleanup

```bash
# Kill a specific session
tmux kill-session -t agents-a1b2c3d4

# Kill all sessions
tmux kill-server
```

---

## Configuration

### Environment Variables

```bash
# Enable experimental agent teams
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1

# Enable communication channel
export CLAUDE_AGENT_COMMUNICATION_ENABLED=1

# Enable interactive mode
export INTERACTIVE_MODE_ENABLED=1
```

### Customization

Session name can be customized in `team_leader.py`:

```python
# Default: agents-{run_id}
self.terminal_manager = ClaudeTerminalManager(session_name=f"custom-{self.run_id}")
```

---

## Troubleshooting

### Issue: "tmux not found"
**Solution**: Install tmux or ensure it's in PATH
- Linux: `sudo apt-get install tmux`
- macOS: `brew install tmux`
- Windows: Use WSL and install tmux within WSL

### Issue: Session already exists
**Solution**: Kill old session or use unique session names
```bash
tmux kill-session -t agents-old_run_id
```

### Issue: Can't see agent output
**Solution**: Attach to the tmux session
```bash
tmux attach-session -t agents-{run_id}
```

### Issue: Agent window appears empty
**Solution**: Check if script is running with `tmux list-windows -t agents-{run_id}`
- Navigate to the window with Ctrl+B and window number
- Check error messages in the pane

---

## File Structure

```
coding-agent-workspace/
├── .claude/
│   ├── agents/
│   │   ├── claude_terminal_manager.py    [UPDATED: tmux-based]
│   │   ├── technical/
│   │   │   ├── team_leader.py            [UPDATED: uses tmux manager]
│   │   │   ├── diagnostician.py
│   │   │   ├── bug_fixer.py
│   │   │   └── reviewer.py
│   │   └── agent_communication.py
│   └── ...
├── SYSTEM_ARCHITECTURE.md                [Main architecture doc]
├── TMUX_ARCHITECTURE.md                  [This file - tmux details]
└── ...
```

---

## Future Enhancements

1. **Tmux Layout Presets**: Define custom tmux layouts for agent visualization
2. **Session Recording**: Automatically record tmux sessions for playback
3. **Pane Switching**: Add interactive commands to switch between agent panes
4. **Status Dashboard**: Create tmux status bar with agent execution status
5. **Automatic Cleanup**: Option to auto-close panes after agent completion

---

## Conclusion

The tmux-based architecture provides a cleaner, more unified approach to managing multiple agent executions. It eliminates the complexity of platform-specific terminal spawning while maintaining full visibility into all agent activities within a single, organized session.

**Last Updated:** 2026-07-29
**Version:** 1.0.0 (Tmux-based)

# Quick Start: Tmux-Based Agent Execution

## Prerequisites

### Install tmux

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install tmux
```

**macOS:**
```bash
brew install tmux
```

**Windows 11 (via WSL2):**
```bash
# Install WSL2 first, then in WSL terminal:
sudo apt-get install tmux
```

### Verify Installation
```bash
tmux --version
# Should output something like: tmux 3.x.x
```

---

## Running Agent Tasks

### Step 1: Start an Agent Task

```bash
coding-agent-workspace solve "fix the authentication bug"
```

This will:
1. Create a unique tmux session named `agents-{run_id}`
2. Team Leader analyzes the task
3. Each selected agent gets its own tmux window
4. All agents execute in parallel within the session

### Step 2: View the Tmux Session

In another terminal, attach to the session:

```bash
# List all tmux sessions
tmux list-sessions

# Attach to your agent session (e.g., agents-a1b2c3d4)
tmux attach-session -t agents-a1b2c3d4
```

### Step 3: Navigate Agent Windows

Once attached to tmux session, use these shortcuts:

| Shortcut | Action |
|----------|--------|
| `Ctrl+B n` | Next window |
| `Ctrl+B p` | Previous window |
| `Ctrl+B 0-9` | Jump to specific window |
| `Ctrl+B d` | Detach from session (leave running) |
| `Ctrl+B :` | Enter command mode |

### Step 4: View Agent Output

Each window shows:
- Agent name and type
- Task being executed
- Real-time output and progress
- Completion status and results

---

## Common Tasks

### View All Active Sessions
```bash
tmux list-sessions
```

Output:
```
agents-a1b2c3d4: 3 windows (created ...)
agents-b3c4d5e6: 2 windows (created ...)
...
```

### View Windows in a Session
```bash
tmux list-windows -t agents-a1b2c3d4
```

Output:
```
0: agent-1 (active)
1: agent-2
2: agent-3
```

### Kill a Session (Cleanup)
```bash
tmux kill-session -t agents-a1b2c3d4
```

### Kill All Sessions
```bash
tmux kill-server
```

### Send Command to Window (Advanced)
```bash
# Send a command to a specific window
tmux send-keys -t agents-a1b2c3d4:agent-1 "command here" Enter
```

---

## Typical Workflow

```
1. Terminal 1 - Start agent task:
   $ coding-agent-workspace solve "analyze performance"
   → Creates agents-xyz123 session with agents

2. Terminal 2 - Monitor execution:
   $ tmux attach-session -t agents-xyz123
   → See all agents running in separate windows
   → Use Ctrl+B n/p to navigate

3. Terminal 1 - Wait for completion:
   → Displays results and status

4. Terminal 2 - Review results:
   → Keep tmux open to review agent outputs
   → Use Ctrl+B d to detach and leave session open

5. Cleanup when done:
   $ tmux kill-session -t agents-xyz123
```

---

## Troubleshooting

### "tmux: command not found"
**Fix:** Install tmux (see Prerequisites section)

### Session won't start
```bash
# Check if old session exists
tmux list-sessions

# Kill old session if it exists
tmux kill-session -t agents-old_id
```

### Can't see agent output
```bash
# Make sure you're attached to session
tmux attach-session -t agents-a1b2c3d4

# Navigate to the agent window
Ctrl+B 0  # Jump to window 1
Ctrl+B 1  # Jump to window 2 (etc.)
```

### Session keeps disconnecting
```bash
# Use -c to create new session in specific directory
tmux new-session -d -s agents-test -c ~/coding-agent-workspace

# Or just attach normally
tmux attach-session -t agents-test
```

### Want to record session output
```bash
# Use tmux capture-pane to save window contents
tmux capture-pane -t agents-a1b2c3d4:agent-1 -p > output.txt
```

---

## Advanced Usage

### Custom Tmux Configuration

Edit `~/.tmux.conf` to customize:

```bash
# Set better colors
set -g default-terminal "screen-256color"

# Set window title
set -g set-titles on
set -g set-titles-string "#S - #W"

# Quick navigation
bind h select-window -t :-
bind l select-window -t :+

# Reload config
bind r source-file ~/.tmux.conf
```

Then reload: `tmux source-file ~/.tmux.conf`

### View Session in Tiled Layout
```bash
# After attaching to session:
Ctrl+B Space    # Cycle through layouts
Ctrl+B !        # Break pane into new window
Ctrl+B z        # Zoom pane in/out
```

### Create Named Windows (Manual)
```bash
# While in session:
Ctrl+B c        # Create new window
Ctrl+B ,        # Rename window
```

---

## Session Examples

### Example 1: View Diagnostician Output
```bash
# Attach to session
tmux attach-session -t agents-a1b2c3d4

# Navigate to Diagnostician window (usually window 0)
Ctrl+B 0

# Scroll up to see previous output
# Ctrl+B [ then arrow keys to scroll
# q to exit scroll mode
```

### Example 2: Switch Between Agents
```bash
# In tmux session:
Ctrl+B 1    # View BugFixer window
Ctrl+B 2    # View Reviewer window
Ctrl+B 0    # Back to Diagnostician
```

### Example 3: Detach and Reattach
```bash
# Terminal 1 - Start agents
$ coding-agent-workspace solve "task"

# Terminal 2 - Monitor (attach)
$ tmux attach-session -t agents-xyz

# Detach while keeping agents running
Ctrl+B d

# Do other work...

# Reattach later to check results
$ tmux attach-session -t agents-xyz
```

---

## Next Steps

1. **Read TMUX_ARCHITECTURE.md** - Full technical details
2. **Read SYSTEM_ARCHITECTURE.md** - Overall system design
3. **Explore `.claude/agents/`** - Agent implementation code
4. **Run tests** - `coding-agent-workspace solve "test"`

---

## Support

For issues or questions:
- Check `.claude/agents/claude_terminal_manager.py` - Terminal management code
- Check `.claude/agents/technical/team_leader.py` - Agent orchestration
- Review `.agent-workspace/runs/` - Execution logs and results

**Version:** 1.0.0 (Tmux-based)
**Last Updated:** 2026-07-29

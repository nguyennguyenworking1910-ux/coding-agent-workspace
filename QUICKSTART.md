# Quick Start Guide

Get up and running with Coding Agent Workspace in 5 minutes.

---

## Prerequisites

### 1. Python 3.9+

```bash
# Check version
python --version
# Should show: Python 3.9.x or higher
```

### 2. Install tmux

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install tmux
```

**macOS:**
```bash
brew install tmux
```

**Windows 11 (WSL2):**
```bash
# First install WSL2 if not already done
wsl --install

# Then in WSL terminal:
sudo apt-get install tmux
```

**Verify installation:**
```bash
tmux --version
# Should show: tmux 3.x.x
```

---

## Installation

### Step 1: Clone/Navigate to Project

```bash
cd coding-agent-workspace
```

### Step 2: Install Package

```bash
# Development mode (editable install)
pip install -e .

# This installs the CLI command: coding-agent-workspace
```

### Step 3: Verify Installation

```bash
# Check command works
coding-agent-workspace --help

# Should show:
# Usage: coding-agent-workspace [OPTIONS] COMMAND [ARGS]...
```

---

## First Run

### Step 1: Start an Agent Task

```bash
coding-agent-workspace solve "analyze my codebase"
```

### Step 2: Monitor Execution

In a **separate terminal**, watch the agents work:

```bash
# List active sessions
tmux list-sessions

# Output:
# agents-a1b2c3d4: 3 windows (created ...)

# Attach to watch agents
tmux attach-session -t agents-a1b2c3d4
```

### Step 3: Navigate Between Agents

While in tmux session:

```
Ctrl+B n    # Next window (next agent)
Ctrl+B p    # Previous window (previous agent)
Ctrl+B 0    # Jump to agent 1
Ctrl+B 1    # Jump to agent 2
Ctrl+B 2    # Jump to agent 3
Ctrl+B d    # Detach (keep running)
```

### Step 4: View Results

```bash
# Results saved automatically
cat .agent-workspace/runs/{run_id}.json

# Pretty print
python -m json.tool .agent-workspace/runs/{run_id}.json
```

---

## Common Tasks

### Task 1: Security Analysis

Find security vulnerabilities in your code:

```bash
coding-agent-workspace solve "find all security vulnerabilities"
```

**What happens:**
- Diagnostician scans for hardcoded credentials, secrets
- Reviewer validates security practices
- Results saved with severity levels (CRITICAL, HIGH, MEDIUM, LOW)

### Task 2: Code Quality Review

Check code quality and style:

```bash
coding-agent-workspace solve "review code quality and suggest improvements"
```

**What happens:**
- Diagnostician finds style issues, missing docstrings
- BugFixer plans improvements
- Reviewer scores overall quality (0-100%)

### Task 3: Bug Detection

Find and analyze bugs:

```bash
coding-agent-workspace solve "find bugs in the authentication module"
```

**What happens:**
- Diagnostician finds error handling issues, logic problems
- BugFixer proposes fixes
- Reviewer validates proposed changes

### Task 4: Performance Analysis

Identify performance bottlenecks:

```bash
coding-agent-workspace solve "find performance optimization opportunities"
```

**What happens:**
- Diagnostician scans for inefficiencies
- BugFixer suggests optimizations
- Reviewer validates improvements

---

## Understanding Output

### Console Output

```
[*] [TEAM_LEADER] Task classified: security
[*] [TEAM_LEADER] Selected agents: diagnostician, reviewer
[*] [TEAM_LEADER] Workflow ready for execution

[i] [DIAGNOSTICIAN] Agent initialized
[SCAN_START] Scanning 10 Python files
[!] CRITICAL: Hardcoded credentials detected in auth.py
[ANALYSIS COMPLETE] Found 3 issues

[i] [REVIEWER] Agent initialized
[VALIDATE_START] Starting validation
[FINAL SCORE] 85% - APPROVED
```

### Message Icons

| Icon | Meaning | Example |
|------|---------|---------|
| `[i]` | Info (status) | `[i] Agent initialized` |
| `[*]` | Decision (important) | `[*] Task classified` |
| `[!]` | Finding (issue) | `[!] CRITICAL: Issue found` |
| `[?]` | Warning (caution) | `[?] Low coverage detected` |
| `[x]` | Error (failure) | `[x] Execution failed` |

### Results File

Results saved to `.agent-workspace/runs/{run_id}.json`:

```json
{
  "success": true,
  "task": "find security issues",
  "task_type": "security",
  "agent_execution_results": [
    {
      "agent": "diagnostician",
      "findings": [
        {
          "file": "auth.py",
          "issue": "Hardcoded credentials detected",
          "severity": "CRITICAL"
        }
      ]
    },
    {
      "agent": "reviewer",
      "score": 85,
      "approval": "APPROVED"
    }
  ]
}
```

---

## Tmux Cheat Sheet

### Session Management

```bash
# List all sessions
tmux list-sessions

# Attach to session
tmux attach-session -t agents-{run_id}

# Kill session when done
tmux kill-session -t agents-{run_id}

# Kill all sessions
tmux kill-server
```

### Inside Tmux Session

```bash
Ctrl+B c    # Create new window
Ctrl+B n    # Next window
Ctrl+B p    # Previous window
Ctrl+B 0-9  # Jump to window by number
Ctrl+B w    # List windows
Ctrl+B d    # Detach (keep running)
Ctrl+B !    # Break pane into new window
Ctrl+B x    # Kill current pane
Ctrl+B [    # Enter scroll mode (Page Up/Down, q to exit)
```

### View Session Structure

```bash
# List windows in session
tmux list-windows -t agents-{run_id}

# Output:
# 0: agent-1 (active)
# 1: agent-2
# 2: agent-3

# View specific pane
tmux capture-pane -t agents-{run_id}:0 -p
```

---

## Troubleshooting

### Problem: Command not found

```bash
# Error: command not found: coding-agent-workspace

# Solution: Reinstall package
pip install -e .

# Verify installation
which coding-agent-workspace
```

### Problem: tmux not found

```bash
# Error: tmux: command not found

# Solution: Install tmux for your OS
# Linux
sudo apt-get install tmux

# macOS
brew install tmux

# Windows (WSL)
# Install WSL2 first, then: apt-get install tmux
```

### Problem: Session already exists

```bash
# Error: session already exists: agents-xyz

# Solution: Kill old session first
tmux kill-session -t agents-xyz

# Or run new task (it will create new run_id)
coding-agent-workspace solve "different task"
```

### Problem: Can't see agent output

```bash
# Symptom: Tmux window appears empty

# Solution: Attach to correct window
tmux attach-session -t agents-{run_id}

# Navigate to agent window
Ctrl+B 1  # Try different windows
Ctrl+B 2
Ctrl+B 3

# Check if output is there - scroll up
Ctrl+B [    # Enter scroll mode
Page Up     # Scroll to see output
q           # Exit scroll mode
```

### Problem: Agent execution failed

```bash
# Check the tmux window output for error messages
tmux attach-session -t agents-{run_id}

# Navigate to failed agent window
Ctrl+B 1  # Check each window

# Look for [x] [ERROR] messages
# Shows what went wrong

# Review agent code for issues
cat .claude/agents/technical/{agent_name}.py
```

### Problem: Results not saved

```bash
# Solution: Check directory exists
ls -la .agent-workspace/runs/

# Create if missing
mkdir -p .agent-workspace/runs

# Check permissions
chmod 755 .agent-workspace
chmod 755 .agent-workspace/runs
```

---

## Next Steps

### 1. Read Full Documentation

- **[README.md](./README.md)** - Project overview
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Technical details
- **[AGENTS.md](./AGENTS.md)** - Agent capabilities

### 2. Experiment with Tasks

Try different task descriptions:

```bash
# General analysis
coding-agent-workspace solve "analyze the entire codebase"

# Specific focus
coding-agent-workspace solve "focus on database operations"

# Multiple concerns
coding-agent-workspace solve "check for security issues AND code quality"
```

### 3. Customize Configuration

Edit `.claude/settings.json` to customize behavior:

```json
{
  "preferences": {
    "terminalManager": "tmux",
    "tmuxSessionPrefix": "agents-"
  }
}
```

### 4. Explore Results

```bash
# List all past executions
ls -t .agent-workspace/runs/ | head -10

# Compare results
diff <(python -m json.tool .agent-workspace/runs/run1.json) \
     <(python -m json.tool .agent-workspace/runs/run2.json)
```

---

## Tips & Tricks

### Tip 1: Monitor Multiple Runs

In terminal 1:
```bash
coding-agent-workspace solve "task 1"
```

In terminal 2:
```bash
# Different task while first one runs
coding-agent-workspace solve "task 2"
```

Each gets its own tmux session (different run_id).

### Tip 2: Quick Results Access

```bash
# Get latest run_id
LATEST=$(ls -t .agent-workspace/runs | head -1 | cut -d. -f1)

# View immediately
cat .agent-workspace/runs/$LATEST.json | python -m json.tool
```

### Tip 3: Save Results to File

```bash
# Save pretty-printed results
python -m json.tool .agent-workspace/runs/{run_id}.json > results.json

# Share findings
cat results.json | grep "CRITICAL" -A 3
```

### Tip 4: Continuous Monitoring

In terminal 1, keep session open:
```bash
tmux attach-session -t agents-{run_id}
# View agent output in real-time
```

### Tip 5: Batch Processing

```bash
# Analyze multiple projects
for project in project1 project2 project3; do
  cd $project
  coding-agent-workspace solve "analyze code"
  cd ..
done
```

---

## Common Commands

```bash
# Start analysis
coding-agent-workspace solve "task description"

# View active sessions
tmux list-sessions

# Attach to monitor
tmux attach-session -t agents-{run_id}

# List all results
ls .agent-workspace/runs/

# View latest result
cat .agent-workspace/runs/$(ls -t .agent-workspace/runs | head -1)

# Kill session
tmux kill-session -t agents-{run_id}

# Check installation
coding-agent-workspace --help
```

---

## Performance Expectations

First run on a typical project:

| Stage | Duration |
|-------|----------|
| Initialization | <1s |
| Task classification | <100ms |
| Agent startup | ~500ms |
| Analysis | 1-2s |
| Review | 2-3s |
| **Total** | **~3-5s** |

Subsequent runs are similar (agents work in parallel).

---

## Getting Help

### Check Documentation

1. **README.md** - Project overview and features
2. **ARCHITECTURE.md** - How the system works
3. **AGENTS.md** - What each agent does
4. **This file** - Quick start and common tasks

### Debug Information

```bash
# Check Python version
python --version

# Check tmux version
tmux --version

# Check installation
pip show coding-agent-workspace

# Check environment
echo $CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
```

### Common Issues

- **Can't install?** - Check Python 3.9+
- **tmux not found?** - Install for your OS
- **Command not working?** - Reinstall: `pip install -e .`
- **Results missing?** - Check `.agent-workspace/runs/` exists

---

## Summary

You now know how to:

✅ Install the package  
✅ Run your first analysis  
✅ Monitor execution in tmux  
✅ View results  
✅ Troubleshoot common issues  
✅ Customize behavior  

**Ready to analyze your code!** 🚀

---

**Version:** 0.3.0  
**Last Updated:** 2026-07-29  
**Status:** Production-Ready

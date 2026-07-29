# Quick Reference Guide

## Installation & Setup

```bash
# Navigate to project
cd C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace

# Show help
python -m workspace_cli --help
```

---

## Core Commands

### Standard Execution (Single Terminal)

```bash
# Most common: solve a task
python -m workspace_cli solve "Fix the authentication bug"

# Analyze code
python -m workspace_cli analyze "Check my code for security issues"

# Create a plan
python -m workspace_cli plan "Design a new feature"

# Review code
python -m workspace_cli review "Review the payment module"

# Fix an issue
python -m workspace_cli fix "Fix the SQL injection vulnerability"

# Execute task
python -m workspace_cli execute "Run a specific task"
```

### Multi-Terminal Execution (NEW!)

```bash
# Spawn agents in separate terminals
python -m workspace_cli --multi-terminal solve "Fix the bug"

# See each agent work in real-time
python -m workspace_cli --multi-terminal analyze "Check code quality"

# With custom workspace
python -m workspace_cli --multi-terminal --workspace ./debug-runs solve "task"
```

---

## Common Workflows

### Bug Fix Workflow

```bash
# 1. Identify the issue
# 2. Run analysis
python -m workspace_cli --multi-terminal solve "Fix the authentication failure"

# 3. Watch the agents:
#    - Diagnostician terminal: Shows what's broken
#    - BugFixer terminal: Shows the fix
#    - Reviewer terminal: Validates the fix

# 4. Close terminals when done
# 5. Check results in .agent-workspace/runs/
# 6. Review the diff
# 7. Test and commit
```

### Code Review Workflow

```bash
# 1. Make changes to your code
# 2. Request review
python -m workspace_cli --multi-terminal review "Review the auth module refactor"

# 3. Monitor progress in separate terminals
# 4. Check recommendations
# 5. Iterate if needed
```

### Security Audit Workflow

```bash
# 1. Specify security concerns
python -m workspace_cli analyze "Find SQL injection vulnerabilities in queries"

# 2. Single terminal OK for pure analysis
# Or multi-terminal for detailed tracking:
python -m workspace_cli --multi-terminal analyze "Find security vulnerabilities"

# 3. Review findings
# 4. Fix identified issues
```

---

## CLI Options

| Flag | Purpose | Example |
|------|---------|---------|
| `--multi-terminal` | Run agents in separate terminals | `--multi-terminal solve "task"` |
| `--no-team-leader` | Skip team leader coordination | `--no-team-leader solve "task"` |
| `--workspace DIR` | Custom workspace directory | `--workspace ./runs solve "task"` |
| `--quiet` | Suppress output streaming | `--quiet solve "task"` |
| `--version` | Show version | `--version` |
| `--help` | Show help | `--help` |

---

## Agents Overview

### Technical Agents (Code Work)

| Agent | Role | Mode | Use For |
|-------|------|------|---------|
| **Diagnostician** | Analyzer | Read-only | Finding bugs, issues |
| **BugFixer** | Implementer | Write | Fixing code |
| **Reviewer** | Validator | Read-only | Quality checks |
| **TeamLeader** | Coordinator | Read-only | Planning, routing |

### How Agents Work Together

```
Your Task
    ↓
TeamLeader (classifies task)
    ↓
Creates Workflow (DAG):
    ├─ Diagnostician (analyzes)
    ├─ BugFixer (fixes)
    └─ Reviewer (validates)
    ↓
Results & Changes
```

---

## Results & Outputs

### Where Results Go

```
.agent-workspace/
└── runs/
    ├── run-2026-07-29T14-30-45.json
    ├── run-2026-07-29T14-45-12.json
    └── ...
```

### What's in Each Run File

```json
{
  "run_id": "run-2026-07-29T14-30-45",
  "timestamp": "2026-07-29T14:30:45",
  "task": "Fix authentication bug",
  "result": "EXECUTION REPORT..."
}
```

### Terminal Output

**Main Terminal Shows:**
- Task classification
- Agents spawned
- Execution trace
- Results summary

**Agent Terminals Show:**
- Agent name and task
- Reasoning process
- Findings/changes
- Status

---

## Task Classification

System auto-detects agent workflow based on keywords:

### Bug Analysis Tasks
**Keywords:** bug, error, issue, crash, broken, fail, exception, debug

**Agents:** Diagnostician → BugFixer → Reviewer

```bash
python -m workspace_cli solve "Fix the login error"
```

### Quality Tasks
**Keywords:** quality, review, refactor, design, architecture, test

**Agents:** Diagnostician → Reviewer

```bash
python -m workspace_cli solve "Review code quality"
```

### Performance Tasks
**Keywords:** slow, memory leak, optimize, benchmark

**Agents:** Diagnostician → Reviewer

```bash
python -m workspace_cli solve "Optimize the database query"
```

### Security Tasks
**Keywords:** security, vulnerability, injection, exploit, XSS, SQL

**Agents:** Diagnostician → BugFixer → Reviewer

```bash
python -m workspace_cli solve "Fix SQL injection"
```

---

## Troubleshooting

### Command Not Found

```bash
# Make sure you're in the project directory
cd C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace

# Try running directly with python
python -m workspace_cli solve "task"
```

### Terminals Not Opening (Multi-Terminal)

**Windows:**
- Ensure `cmd` is in your PATH
- Try running from PowerShell instead

**macOS:**
- Ensure Terminal.app is in `/Applications`

**Linux:**
- Install `gnome-terminal`: `sudo apt-get install gnome-terminal`

### Agent Execution Errors

```bash
# Check if .claude is accessible
python -c "import sys; print(sys.path)"

# Verify agent files exist
ls .claude/agents/technical/
```

### Results Not Saving

```bash
# Check workspace directory
ls .agent-workspace/runs/

# Ensure directory is writable
chmod -R 755 .agent-workspace/
```

---

## Environment

### Project Structure

```
C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace\
├── workspace_cli/          ← CLI package
├── .claude/                ← Agent system
├── .agent-workspace/       ← Results
└── pyproject.toml          ← Configuration
```

### Python Requirements

- Python 3.9+
- No external dependencies (using built-in modules)

### Entry Point

```
workspace_cli.cli:main
→ Installed as: coding-agent-workspace command
```

---

## Examples

### Example 1: Quick Bug Analysis

```bash
python -m workspace_cli --multi-terminal solve "Analyze authentication module for bugs"

# Output:
# ✓ Diagnostician terminal opens
# ✓ Shows findings
# ✓ Results saved to .agent-workspace/runs/
```

### Example 2: Code Quality Review

```bash
python -m workspace_cli review "Review the payment processing code"

# Output:
# ✓ Reviews code quality
# ✓ Identifies improvements
# ✓ Shows results in terminal
```

### Example 3: Performance Optimization

```bash
python -m workspace_cli --multi-terminal analyze "Optimize slow database queries"

# Output:
# ✓ Diagnostician finds bottlenecks
# ✓ BugFixer implements optimizations
# ✓ Reviewer validates changes
```

### Example 4: Security Audit

```bash
python -m workspace_cli analyze "Find SQL injection vulnerabilities"

# Output:
# ✓ Scans for injection points
# ✓ Lists vulnerabilities
# ✓ Provides fix recommendations
```

---

## Tips & Tricks

### Monitor Multiple Tasks

```bash
# Terminal 1
python -m workspace_cli --multi-terminal solve "Fix bug A"

# Terminal 2
python -m workspace_cli --multi-terminal solve "Fix bug B"

# Each task gets separate workspace entries
```

### Custom Workspace for Testing

```bash
# Keep test results separate
python -m workspace_cli --multi-terminal --workspace ./test-runs solve "test task"
```

### Batch Processing

```bash
# Run multiple tasks
python -m workspace_cli solve "Task 1"
python -m workspace_cli solve "Task 2"
python -m workspace_cli solve "Task 3"

# All results in .agent-workspace/runs/
```

### Review All Results

```bash
# List all runs
ls -la .agent-workspace/runs/

# View specific result
cat .agent-workspace/runs/run-*.json | python -m json.tool
```

---

## Configuration

### Custom Workspace

Edit `.claude/settings.json`:

```json
{
  "experimental_agent_teams_enabled": true,
  "default_timeout": 300
}
```

### Disable Features

```json
{
  "multi_terminal_enabled": false,
  "experimental_agent_teams_enabled": false
}
```

---

## Performance Notes

| Task | Time |
|------|------|
| Single Terminal Execution | ~5-10 sec |
| Multi-Terminal Setup | ~3-5 sec |
| Agent Execution | ~2-5 sec per agent |
| Results Save | <1 sec |

---

## Support & Documentation

- **Full System Overview:** See `SYSTEM_OVERVIEW.md`
- **Multi-Terminal Guide:** See `.claude/docs/MULTI_TERMINAL_GUIDE.md`
- **Agent Details:** See `.claude/docs/AGENTS.md`
- **Help Command:** `python -m workspace_cli --help`

---

## Common Commands Cheatsheet

```bash
# Basic help
python -m workspace_cli --help

# Show version
python -m workspace_cli --version

# Solve a problem (most common)
python -m workspace_cli solve "your task"

# Solve with visibility
python -m workspace_cli --multi-terminal solve "your task"

# Analyze code
python -m workspace_cli analyze "your code"

# Review code
python -m workspace_cli review "your code"

# Fix issue
python -m workspace_cli fix "your issue"

# Create plan
python -m workspace_cli plan "your goal"

# Custom workspace
python -m workspace_cli --workspace ./my-runs solve "task"

# Skip team leader
python -m workspace_cli --no-team-leader solve "task"

# Suppress streaming
python -m workspace_cli --quiet solve "task"
```

---

**Need more help?** See the full documentation in `SYSTEM_OVERVIEW.md`

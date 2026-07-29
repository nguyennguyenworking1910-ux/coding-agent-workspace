# Claude Code CLI Integration

This workspace is designed to work exclusively through **Claude Code Terminal** (integrated in Claude Code IDE).

## Installation

```bash
# In Claude Code Terminal:
cd ~/Desktop/coding-agent-workspace
pip install -e .
```

This creates the `coding-agent-workspace` command available in any terminal.

## Usage in Claude Code Terminal

All commands run in the integrated Claude Code terminal — no separate windows needed.

### Basic Commands

```bash
# Team Leader coordinates full workflow
coding-agent-workspace solve "task description"

# Quick analysis (Diagnostician only)
coding-agent-workspace analyze "task description"

# Create execution plan
coding-agent-workspace plan "task description"

# Bug fixing
coding-agent-workspace fix "task description"

# Code review
coding-agent-workspace review "task description"
```

### Options

```bash
# Multi-terminal mode (each agent opens in Claude Code terminal)
coding-agent-workspace solve "task" --multi-terminal

# Skip team leader (run without coordination)
coding-agent-workspace analyze "task" --no-team-leader

# Custom workspace directory
coding-agent-workspace solve "task" --workspace /path/to/workspace
```

## Agent Workflow

```
Claude Code Terminal
    ↓
coding-agent-workspace solve "task"
    ↓
Team Leader Agent (coordinates)
    ├─ Classifies task (security, bug_analysis, etc)
    ├─ Selects appropriate agents
    └─ Builds workflow
    ↓
Agent Execution (in Claude Code Terminal)
    ├─ Diagnostician (analysis)
    ├─ Bug Fixer (implementation) [if needed]
    └─ Reviewer (validation)
    ↓
Results displayed in Terminal
    ↓
Saved to .agent-workspace/runs/
```

## Multi-Terminal Mode

When using `--multi-terminal`, each agent:
- Opens in a **separate Claude Code terminal**
- Shows real-time execution progress
- Displays streaming output
- Can be monitored independently

```bash
coding-agent-workspace solve "complex task" --multi-terminal
```

## Example Workflows

### Security Analysis
```bash
coding-agent-workspace analyze "Check for security vulnerabilities"
```
→ Diagnostician scans for: SQL injection, XSS, hardcoded credentials, etc.

### Bug Finding and Fixing
```bash
coding-agent-workspace solve "Find and fix bugs in the codebase"
```
→ Team Leader spawns: Diagnostician → Bug Fixer → Reviewer

### Code Review
```bash
coding-agent-workspace review "Review the new authentication module"
```
→ Reviewer validates: docstrings, error handling, security, testing

## Results

All execution results are saved to `.agent-workspace/runs/`:

```
.agent-workspace/
  runs/
    run-2026-07-29T15-33-38.573304.json  ← execution results
    run-2026-07-29T15-37-45.297384.json
    ...
```

## Troubleshooting

### Command not found
```bash
# Reinstall the package
pip install -e .

# Verify installation
which coding-agent-workspace
coding-agent-workspace --help
```

### Terminal encoding issues
```bash
# Set UTF-8 encoding
export PYTHONIOENCODING=utf-8
coding-agent-workspace solve "task"
```

### Agent not responding
- Check `.agent-workspace/runs/` for recent results
- Run with `--multi-terminal` for live visibility
- Check Claude Code terminal for error messages

## Advanced: Running Agents Individually

You can also spawn individual agents through Claude Code by modifying the orchestrator settings or using Python directly:

```python
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd() / ".claude"))
from agents.technical.diagnostician import DiagnosticianAgent

agent = DiagnosticianAgent()
result = agent.execute("your task here")
```

But the recommended approach is using the CLI: `coding-agent-workspace` command.

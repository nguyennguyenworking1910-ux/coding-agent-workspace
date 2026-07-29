# Coding Agent Workspace

A modern agent orchestration system for code analysis, debugging, and quality review using Claude AI and tmux-based execution.

**Version:** 0.3.0  
**Status:** Production-Ready  
**Python:** 3.9+

## Overview

Coding Agent Workspace is an intelligent multi-agent system that analyzes and improves your codebase. A Team Leader agent orchestrates specialized agents (Diagnostician, BugFixer, Reviewer) to work in parallel, each bringing unique expertise to code analysis and improvement tasks.

### Key Features

- 🤖 **Multi-Agent Orchestration** - Team Leader coordinates specialist agents
- 🔄 **Parallel Execution** - All agents work simultaneously in tmux panes
- 🎯 **Task Classification** - Automatically routes tasks to appropriate agents
- 📊 **Real-time Output** - See all agent activity in organized tmux session
- 🔐 **Security Analysis** - Identifies credentials, vulnerabilities, and risks
- 🐛 **Bug Detection** - Finds hardcoded values, bare exceptions, missing docstrings
- ✅ **Code Review** - Validates fixes and scores code quality
- 📦 **Modern Packaging** - PEP 517/518 compliant Python project

## Installation

### Prerequisites

- **Python 3.9+** with pip
- **tmux** (required for agent execution)
  - Linux: `sudo apt-get install tmux`
  - macOS: `brew install tmux`
  - Windows: Use WSL2 + `apt-get install tmux`

### Setup

```bash
# Clone or navigate to project directory
cd coding-agent-workspace

# Install in development mode
pip install -e .

# Verify installation
coding-agent-workspace --help
```

## Quick Start

### Run Your First Analysis

```bash
# Analyze your codebase for issues
coding-agent-workspace solve "analyze the codebase for security issues"

# See the execution in tmux
tmux list-sessions
tmux attach-session -t agents-{run_id}
```

### Task Examples

```bash
# Find bugs
coding-agent-workspace solve "find bugs in the authentication module"

# Review code quality
coding-agent-workspace solve "review code quality and suggest improvements"

# Performance analysis
coding-agent-workspace solve "optimize performance bottlenecks"

# Security audit
coding-agent-workspace solve "identify all security vulnerabilities"
```

## System Architecture

### How It Works

```
User Task
    ↓
Team Leader Agent
    ├─→ Task Classification (security, bug_analysis, quality, etc.)
    ├─→ Agent Selection (which agents to use)
    ├─→ Workflow Building (execution plan)
    ↓
Parallel Agent Execution (in tmux windows)
    ├─→ Diagnostician (analyzes code, finds issues)
    ├─→ BugFixer (plans fixes, implements changes)
    └─→ Reviewer (validates findings, scores results)
    ↓
Results Aggregation & Storage
```

### Agents

| Agent | Role | Output |
|-------|------|--------|
| **Diagnostician** | Code analysis & issue detection | List of findings with severity |
| **BugFixer** | Fix planning & implementation | Fix strategies and changes |
| **Reviewer** | Validation & quality scoring | Score (0-100%) and approval status |

## Tmux Execution

All agents execute in a single tmux session with organized windows:

```bash
# Session structure
Session: agents-{run_id}
├── Window 0: agent-1 (Diagnostician)
├── Window 1: agent-2 (BugFixer)
└── Window 2: agent-3 (Reviewer)

# Monitor execution
tmux attach-session -t agents-{run_id}

# Navigate windows
Ctrl+B n    # Next window
Ctrl+B p    # Previous window
Ctrl+B 0-9  # Jump to window
Ctrl+B d    # Detach
```

## Commands

### Main Command

```bash
coding-agent-workspace <command> "task description"
```

### Available Commands

- `solve` - Analyze and solve problems
- `analyze` - Analyze code/files
- `review` - Review code quality
- `plan` - Plan improvements
- `fix` - Implement fixes
- `execute` - Execute custom tasks

### Examples

```bash
# Solve a problem
coding-agent-workspace solve "fix authentication issues"

# Analyze code
coding-agent-workspace analyze "check for performance issues"

# Review quality
coding-agent-workspace review "validate code standards"
```

## Project Structure

```
coding-agent-workspace/
├── .claude/
│   ├── agents/
│   │   ├── technical/
│   │   │   ├── team_leader.py          # Orchestrator agent
│   │   │   ├── diagnostician.py        # Analysis agent
│   │   │   ├── bug_fixer.py            # Implementation agent
│   │   │   └── reviewer.py             # Validation agent
│   │   ├── business/
│   │   │   └── group_sale_manager.py   # Data operations agent
│   │   ├── claude_terminal_manager.py  # Tmux management
│   │   ├── config.py                   # Configuration
│   │   └── __init__.py
│   ├── tools/
│   │   ├── thought.py                  # Reasoning tool
│   │   └── ...
│   └── settings.json
├── workspace_cli/
│   ├── cli.py                          # CLI entry point
│   └── __init__.py
├── .agent-workspace/                   # Execution results
│   └── runs/
│       └── run-{run_id}.json
├── pyproject.toml                      # Python packaging
├── README.md                           # This file
├── ARCHITECTURE.md                     # System design
├── QUICKSTART.md                       # Usage guide
└── AGENTS.md                           # Agent details
```

## Configuration

### Environment Variables

```bash
# Enable experimental agent teams
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1

# Enable agent communication logging
export CLAUDE_AGENT_COMMUNICATION_ENABLED=1

# Enable interactive mode
export INTERACTIVE_MODE_ENABLED=1
```

### Settings File

Edit `.claude/settings.json` to customize:

```json
{
  "theme": "dark",
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "CLAUDE_AGENT_COMMUNICATION_ENABLED": "1",
    "INTERACTIVE_MODE_ENABLED": "1"
  },
  "preferences": {
    "terminalManager": "tmux",
    "tmuxSessionPrefix": "agents-",
    "tmuxAutoAttach": false
  }
}
```

## Usage Examples

### Example 1: Security Analysis

```bash
$ coding-agent-workspace solve "find all security vulnerabilities"

# Output:
# [TEAM LEADER THINKING] Task Classification
#   Classified as 'security' task
# [TMUX_PANE] Creating pane for DIAGNOSTICIAN
# [TMUX_PANE] Creating pane for REVIEWER
```

### Example 2: Code Review

```bash
$ coding-agent-workspace solve "review code quality"

# Agents analyze in parallel:
# - Diagnostician scans for issues
# - BugFixer plans improvements
# - Reviewer validates quality

# Results saved to: .agent-workspace/runs/{run_id}.json
```

### Example 3: Monitor Execution

```bash
# In separate terminal, monitor tmux session
$ tmux attach-session -t agents-a1b2c3d4

# See all agents working in their windows
# - Use Ctrl+B n to navigate between agents
# - Watch real-time output and progress
```

## Output & Results

### Console Output

Agent execution is visible through:
- Console output with formatted messages
- Tmux windows showing each agent's activity
- Real-time progress and findings

### Saved Results

Results are saved to `.agent-workspace/runs/{run_id}.json`:

```json
{
  "success": true,
  "task_type": "security",
  "agents_executed": ["diagnostician", "reviewer"],
  "findings": [
    {
      "file": "auth.py",
      "issue": "Hardcoded credentials detected",
      "severity": "CRITICAL"
    }
  ],
  "approval": "APPROVED",
  "score": 85
}
```

## Troubleshooting

### tmux not found

```bash
# Install tmux
Linux:   sudo apt-get install tmux
macOS:   brew install tmux
Windows: Install WSL2, then: apt-get install tmux
```

### Session already exists

```bash
# Kill old session
tmux kill-session -t agents-old_id

# Or just use a different run_id
```

### Can't see agent output

```bash
# Attach to the correct session
tmux attach-session -t agents-{run_id}

# Navigate to agent window
Ctrl+B 0  # First agent
Ctrl+B 1  # Second agent
```

### Agent execution fails

Check the tmux pane output for error messages:

```bash
# Attach and navigate to failed agent's window
tmux attach-session -t agents-{run_id}
Ctrl+B 1  # Check specific window
```

## Development

### Extending the System

1. **Add a New Agent** - Create in `.claude/agents/technical/`
2. **Add Task Patterns** - Update `TeamLeaderAgent.TASK_PATTERNS`
3. **Add Tools** - Create in `.claude/tools/`
4. **Update Configuration** - Modify `.claude/settings.json`

### Running Tests

```bash
# Run analysis on test task
coding-agent-workspace solve "test analysis"

# Check results
cat .agent-workspace/runs/$(ls -t .agent-workspace/runs | head -1)
```

## Advanced Usage

### Custom Task Classification

Edit `.claude/agents/technical/team_leader.py` to add custom patterns:

```python
TASK_PATTERNS = {
    "custom_task": [
        "keyword1", "keyword2", "keyword3"
    ]
}
```

### Tmux Advanced

```bash
# Create custom tmux layout
tmux new-session -d -s custom -x 200 -y 50

# Send commands to specific pane
tmux send-keys -t custom:0 "python script.py" Enter

# Capture pane output
tmux capture-pane -t agents-{run_id}:0 -p > output.txt
```

## Performance

| Operation | Time |
|-----------|------|
| Task Classification | <10ms |
| Workflow Building | <10ms |
| Diagnostician Analysis | ~1-2s |
| BugFixer Planning | ~1-2s |
| Reviewer Validation | ~2-3s |
| Total Execution | ~3-5s |

## Contributing

To contribute improvements:

1. Create a feature branch
2. Make your changes
3. Test thoroughly
4. Submit a pull request

## License

Created by Nguyen Le Dang Nguyen (nguyen.nguyen30@momo.vn)

---

## Quick Links

- [ARCHITECTURE.md](./ARCHITECTURE.md) - System design and architecture
- [QUICKSTART.md](./QUICKSTART.md) - Detailed usage guide
- [AGENTS.md](./AGENTS.md) - Agent descriptions and capabilities

## Support

For issues or questions:
1. Check [QUICKSTART.md](./QUICKSTART.md) for common tasks
2. Review [ARCHITECTURE.md](./ARCHITECTURE.md) for technical details
3. Check agent output in tmux for error messages

**Version:** 0.3.0 (Tmux-based, Modernized)  
**Last Updated:** 2026-07-29

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
- **Claude API key** (optional, for real agent execution)
  - Get from https://console.anthropic.com
  - Set: `export ANTHROPIC_API_KEY="your-key"`

### Setup

```bash
# Navigate to project directory
cd coding-agent-workspace

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install in development mode
pip install -e .

# Verify installation
coding-agent-workspace --help
```

## Documentation

Start with these documents in order:

1. **QUICK_START.md** (5 min) - Get running immediately
2. **[.claude/documents/ARCHITECTURE.md](./.claude/documents/ARCHITECTURE.md)** (10 min) - Understand system design
3. **FILE_REFERENCE.md** (15 min) - Learn what each file does
4. **CODEBASE_ANALYSIS.md** (20 min) - Deep dive into implementation

## Quick Start

### Installation

```bash
cd coding-agent-workspace
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e .
```

### Run Your First Analysis

```bash
# Analyze your codebase
coding-agent-workspace team "Find security vulnerabilities in the codebase"

# List all runs
coding-agent-workspace runs

# View run details
coding-agent-workspace show <run-id>

# View agent output
coding-agent-workspace output <run-id> researcher
```

### Task Examples

```bash
# Security analysis
coding-agent-workspace team "Find all security vulnerabilities"

# Code quality review
coding-agent-workspace team "Review code quality and suggest improvements"

# Bug analysis
coding-agent-workspace team "Find bugs in the authentication module"

# Performance analysis
coding-agent-workspace team "Analyze performance bottlenecks and optimize"
```

## System Architecture

### Core Components

```
User Request
    ↓
Planner (analyzes request, creates AgentPlan)
    ├─ Decides: single-agent vs multi-agent
    ├─ Creates task graph with dependencies
    └─ Validates for feasibility
    ↓
Coordinator (orchestrates execution)
    ├─ Creates workers for each task
    ├─ Runs in parallel (background threads)
    ├─ Listens for events
    └─ Respects task dependencies
    ↓
EventBus (pub/sub communication)
    ├─ Routes events between components
    ├─ Async event delivery
    └─ Thread-safe
    ↓
RunStore (persistent storage)
    ├─ Saves plan, events, results
    ├─ JSON Lines format (streaming-friendly)
    └─ Organized by run ID
    ↓
Results (.agent-workspace/runs/<run-id>/)
```

### Available Agent Roles

| Role | Purpose | When Used |
|------|---------|-----------|
| **Researcher** | Code analysis & issue detection | When "analyze", "find", "check" in request |
| **Implementer** | Implement fixes & improvements | When "fix", "improve", "implement" in request |
| **Reviewer** | Validate findings & quality check | Always included for validation |
| **Tester** | Test coverage & verification | When "test", "verify" in request |
| **BugFixer** | Fix planning & implementation | Fix strategies and changes |
| **Reviewer** | Validation & quality scoring | Score (0-100%) and approval status |

## Project Structure

```
coding-agent-workspace/
├── workspace_cli/                 # CLI entry point
│   ├── cli.py                    # Command parser
│   └── orchestration_commands.py # Command handlers
│
├── .claude/team/                  # Core orchestration (20 files)
│   ├── schemas.py                # Data models (KEY FILE)
│   ├── planner.py                # Plan creation
│   ├── coordinator.py            # Execution orchestration
│   ├── event_bus.py              # Event routing
│   ├── real_worker.py            # Claude AI execution
│   ├── run_store.py              # Persistent storage
│   ├── state_machine.py          # State management
│   ├── claude_runner.py          # Claude API interface
│   ├── mailbox_manager.py        # Agent messaging
│   ├── session_manager.py        # Pause/resume
│   ├── worktree_manager.py       # Git isolation
│   ├── merge_strategy.py         # Safe merging
│   ├── change_validator.py       # Validation
│   └── [others]
│
├── .claude/documents/           # Documentation
│   ├── README.md                 # Documentation index
│   ├── ARCHITECTURE.md          # System design
│   ├── SETUP.md                 # Setup & configuration
│   └── SCHEDULE_CLI.md          # Schedule agent guide
│
├── pyproject.toml                # Project config
└── .agent-workspace/             # Output (created at runtime)
    └── runs/
        └── <run-id>/
            ├── request.md
            ├── plan.json
            ├── events.jsonl
            ├── final-response.md
            └── agents/
```

## Results Storage

After each run, results are saved to `.agent-workspace/runs/<run-id>/`:

```
<run-id>/
├── request.md              # Original request (text)
├── plan.json              # Execution plan (JSON)
├── status.json            # Run status (JSON)
├── events.jsonl           # Event log (JSON Lines)
├── final-response.md      # Final synthesis (markdown)
└── agents/
    └── <agent-id>/
        ├── task.json      # Task assignment
        ├── prompt.md      # System prompt
        ├── output.jsonl   # Agent output (text)
        └── result.md      # Final result
```

## Commands

### Main Command

```bash
coding-agent-workspace team "task description" [options]
```

### Available Commands

```
team REQUEST              Multi-agent orchestration
runs                      List all runs
show RUN_ID              Show run details
output RUN_ID AGENT_ID   Show agent output
message RUN_ID AGT MSG   Send message to agent
stop RUN_ID              Stop a run
```

### Options

```
--real-workers           Use real Claude agents (requires API key)
--max-agents N           Maximum parallel agents (default: 4)
--mux MODE              Terminal multiplexer: auto|tmux|psmux|headless
--workspace DIR         Custom workspace directory
```

### Examples

```bash
# Multi-agent analysis
coding-agent-workspace team "Find security vulnerabilities"

# With real Claude AI
coding-agent-workspace team "Analyze code" --real-workers

# Limit agents
coding-agent-workspace team "Review code" --max-agents 2

# View results
coding-agent-workspace runs
coding-agent-workspace show run-2026-08-03T10-30-45
coding-agent-workspace output run-2026-08-03T10-30-45 researcher

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

- [.claude/documents/ARCHITECTURE.md](./.claude/documents/ARCHITECTURE.md) - System design and architecture
- [QUICKSTART.md](./QUICKSTART.md) - Detailed usage guide
- [AGENTS.md](./AGENTS.md) - Agent descriptions and capabilities

## Support

For issues or questions:
1. Check [QUICKSTART.md](./QUICKSTART.md) for common tasks
2. Review [.claude/documents/ARCHITECTURE.md](./.claude/documents/ARCHITECTURE.md) for technical details
3. Check agent output in tmux for error messages

**Version:** 0.3.0 (Tmux-based, Modernized)  
**Last Updated:** 2026-07-29

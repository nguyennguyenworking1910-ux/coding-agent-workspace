# Coding Agent Workspace

An intelligent multi-agent orchestration system that automates code analysis, bug fixing, and quality review through coordinated agent workflows.

## Overview

**Coding Agent Workspace** uses specialized Claude Code agents that work together to analyze your code, find issues, fix bugs, and validate quality — all coordinated by a Team Leader agent.

Instead of one AI trying to do everything, you get:
- 🔍 **Diagnostician** — Finds bugs and issues
- 🔧 **Bug Fixer** — Implements solutions  
- ✅ **Reviewer** — Validates quality
- 🎯 **Team Leader** — Coordinates the team

### Key Innovation: Multi-Terminal Mode

Watch each agent work **in its own terminal window** for complete transparency into how agents reason and execute tasks.

```
Main Terminal          Diagnostician         Bug Fixer             Reviewer
─────────────          ─────────────         ─────────         ─────────────
[ORCHESTRATION]        AGENT:                AGENT:             AGENT:
[SPAWN] agents         DIAGNOSTICIAN         BUG_FIXER          REVIEWER

✓ Agents spawned       Analyzing...          Planning fixes...  Reviewing...
✓ All terminals        
  active               Found 3 issues         Will modify:       ✓ APPROVED
                       - SQL injection        - auth.py
                       - Missing check        - database.py
```

---

## Quick Start

### Installation

```bash
# Clone or navigate to project
cd C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace

# Verify installation
python -m workspace_cli --version
# Output: __main__.py 0.1.0
```

### First Command

```bash
# Standard mode (single terminal)
python -m workspace_cli solve "Find bugs in my authentication code"

# Multi-terminal mode (see agents work in real-time)
python -m workspace_cli --multi-terminal solve "Find bugs in my authentication code"
```

### What Happens

1. **Task Classification** — System determines which agents are needed
2. **Workflow Planning** — Team Leader creates execution plan
3. **Agent Execution** — Agents work (each in own terminal if `--multi-terminal`)
4. **Results** — Findings saved and displayed
5. **User Review** — You review changes and decide what to commit

---

## Available Commands

```bash
# Core commands
python -m workspace_cli solve "your task"           # Let agents solve it
python -m workspace_cli analyze "your code"          # Analyze for issues
python -m workspace_cli fix "what's broken"          # Fix the issue
python -m workspace_cli review "your code"           # Review quality
python -m workspace_cli plan "your goal"             # Create plan

# With options
python -m workspace_cli --multi-terminal solve "task"     # See agents work
python -m workspace_cli --workspace ./runs solve "task"   # Custom directory
python -m workspace_cli --no-team-leader solve "task"     # Skip planning
python -m workspace_cli --quiet solve "task"              # No streaming
```

---

## System Architecture

```
┌──────────────────────────────────┐
│   User Command (CLI)             │
│   python -m workspace_cli        │
└────────────┬─────────────────────┘
             │
             ↓
┌──────────────────────────────────┐
│   workspace_cli/ (CLI Layer)     │  ← Handles commands, routes execution
│   • cli.py                       │
│   • claude_provider.py           │
└────────────┬─────────────────────┘
             │
      ┌──────┴──────┐
      │             │
      ↓             ↓
  Single       Multi-Terminal
  Terminal      (NEW!)
    Mode        
      │             │
      ↓             ↓
   Team        Multi-Terminal
   Leader      Orchestrator
      │             │
      └──────┬──────┘
             ↓
┌──────────────────────────────────┐
│   .claude/agents/ (Agent Layer)  │  ← Specialized agents
│   • Diagnostician                │
│   • BugFixer                      │
│   • Reviewer                      │
│   • TeamLeader                    │
└────────────┬─────────────────────┘
             │
             ↓
┌──────────────────────────────────┐
│   .claude/tools/ (Tools Layer)   │  ← Agent capabilities
│   • Thought (reasoning)          │
│   • BigQuery (data)              │
│   • Query Builder                │
└────────────┬─────────────────────┘
             │
             ↓
┌──────────────────────────────────┐
│   Output Layer                   │  ← Results & logs
│   • Terminal display             │
│   • JSON mission files           │
│   • Execution logs               │
└──────────────────────────────────┘
```

---

## Key Features

### 1. Intelligent Task Routing

Automatically routes tasks to the right agents based on keywords:

```bash
# "bug" → Diagnostician + BugFixer + Reviewer
python -m workspace_cli solve "Fix the authentication bug"

# "review" → Diagnostician + Reviewer  
python -m workspace_cli solve "Review code quality"

# "security" → Full bug analysis + fix workflow
python -m workspace_cli solve "Find SQL injection vulnerabilities"
```

### 2. Multi-Terminal Visibility (NEW!)

```bash
python -m workspace_cli --multi-terminal solve "Fix the issue"

# Results:
# ✓ Main terminal shows orchestration
# ✓ Each agent gets its own terminal window
# ✓ See real-time execution and reasoning
# ✓ Debug agent behavior effectively
```

### 3. Persistent Execution History

```
.agent-workspace/runs/
├── run-2026-07-29T14-30-45.json
├── run-2026-07-29T14-45-12.json
└── run-2026-07-29T15-20-33.json
```

Each run contains:
- Task description
- Execution trace
- Agent findings
- Changes made
- Timestamps

### 4. DAG-Based Workflow

Team Leader automatically creates optimal execution plans:

```
Bug Analysis Flow:
  Diagnostician (finds issues)
         ↓
  BugFixer (implements fixes)
         ↓
  Reviewer (validates quality)
```

---

## Common Workflows

### Workflow: Find and Fix a Bug

```bash
# 1. Identify issue
# You notice login is broken

# 2. Spawn agents to analyze and fix
python -m workspace_cli --multi-terminal solve "Fix authentication failure in login"

# 3. Watch progress in terminals
#    - Diagnostician: Shows what's wrong
#    - BugFixer: Shows how it's being fixed
#    - Reviewer: Validates the fix

# 4. Review results
cat .agent-workspace/runs/run-*.json

# 5. Test and commit
```

### Workflow: Code Review

```bash
python -m workspace_cli --multi-terminal review "Review payment module refactor"

# Output:
# - Diagnostician finds quality issues
# - Reviewer validates improvements
# - Recommendations provided
```

### Workflow: Security Audit

```bash
python -m workspace_cli analyze "Find SQL injection vulnerabilities in queries"

# Output:
# - Scans all queries
# - Identifies injection points
# - Provides fix recommendations
```

---

## Directory Structure

```
coding-agent-workspace/
│
├── workspace_cli/                 # CLI Application Package
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                    # Command routing
│   └── claude_provider.py        # Claude subprocess bridge
│
├── .claude/                      # Agent System
│   ├── agents/
│   │   ├── technical/            # Code analysis agents
│   │   │   ├── team_leader.py
│   │   │   ├── diagnostician.py
│   │   │   ├── bug_fixer.py
│   │   │   └── reviewer.py
│   │   ├── multi_terminal_orchestrator.py  # Multi-terminal coordination
│   │   └── terminal_manager.py             # Terminal spawning
│   │
│   ├── tools/                    # Agent capabilities
│   │   ├── thought.py           # Reasoning tool
│   │   └── ... (other tools)
│   │
│   └── docs/
│       ├── AGENTS.md
│       └── MULTI_TERMINAL_GUIDE.md
│
├── .agent-workspace/            # Execution Results
│   └── runs/
│       └── run-*.json
│
├── SYSTEM_OVERVIEW.md           # Complete system documentation
├── QUICK_REFERENCE.md           # Command cheatsheet
└── README.md                    # This file
```

---

## Documentation

### For Quick Help
👉 **[QUICK_REFERENCE.md](./QUICK_REFERENCE.md)** — Commands, workflows, troubleshooting

### For Complete Understanding  
👉 **[SYSTEM_OVERVIEW.md](./SYSTEM_OVERVIEW.md)** — Architecture, components, flows

### For Multi-Terminal Feature
👉 **[.claude/docs/MULTI_TERMINAL_GUIDE.md](./.claude/docs/MULTI_TERMINAL_GUIDE.md)** — Setup, usage, examples

### For Agent Details
👉 **[.claude/docs/AGENTS.md](./.claude/docs/AGENTS.md)** — Agent specifications, tools

---

## Examples

### Example 1: Bug Analysis & Fix

```bash
$ python -m workspace_cli --multi-terminal solve "Fix SQL injection in user search"

🚀 Team Leader Agent Executing: solve
📋 Task: Fix SQL injection in user search

🖥️  MULTI-TERMINAL MODE
    Spawning agents in separate terminal windows...

============================================================
[CLASSIFY] Task classified as: bug_analysis
[PLAN] Spawning agents: diagnostician, bug_fixer, reviewer
[SPAWN] Spawning diagnostician in terminal
✓ Terminal spawned for diagnostician
[SPAWN] Spawning bug_fixer in terminal
✓ Terminal spawned for bug_fixer
[SPAWN] Spawning reviewer in terminal
✓ Terminal spawned for reviewer

✓ Check the open terminals for real-time agent output
✓ Each agent is running in its own terminal window
```

### Example 2: Code Quality Review

```bash
$ python -m workspace_cli review "Review the authentication module for best practices"

Diagnostician finds:
- Missing input validation
- Improper error handling
- Outdated cryptographic library

Reviewer validates:
- Code quality issues identified ✓
- Security concerns noted ✓
- Recommendations provided ✓
```

### Example 3: Performance Analysis

```bash
$ python -m workspace_cli analyze "Optimize slow database queries"

Results:
- N+1 query problem detected
- Missing database indexes
- Query optimization suggestions provided
```

---

## System Requirements

- **Python:** 3.9 or higher
- **Platform:** Windows, macOS, or Linux
- **Dependencies:** None (uses Python standard library)

---

## Configuration

### Custom Workspace

```bash
python -m workspace_cli --workspace ./my-workspace solve "task"
```

### Enable Experimental Features

Edit `.claude/settings.json`:

```json
{
  "experimental_agent_teams_enabled": true,
  "multi_terminal_enabled": true
}
```

---

## Troubleshooting

### Command Not Found
```bash
# Ensure you're in the project directory
cd C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace

# Run with full module path
python -m workspace_cli --help
```

### Terminals Not Opening (Multi-Terminal Mode)
- **Windows:** Ensure `cmd` is accessible from PATH
- **macOS:** Ensure Terminal.app is in Applications
- **Linux:** Install gnome-terminal: `sudo apt-get install gnome-terminal`

### Agent Errors
```bash
# Verify agent files exist
ls .claude/agents/technical/

# Check Python path
python -c "import sys; print(sys.path)"
```

### Results Not Saving
```bash
# Verify workspace directory
ls -la .agent-workspace/runs/

# Ensure write permissions
chmod -R 755 .agent-workspace/
```

---

## How It Works

### Single Terminal Mode (Default)

```
User Command
    ↓
TeamLeader plans workflow
    ↓
Diagnostician analyzes
    ↓
BugFixer implements
    ↓
Reviewer validates
    ↓
Results displayed
```

### Multi-Terminal Mode (NEW!)

```
User Command
    ↓
TerminalManager spawns 3 windows
    ↓
Terminal 1: Diagnostician works
Terminal 2: BugFixer works
Terminal 3: Reviewer works
    ↓
All can be monitored simultaneously
    ↓
Results aggregated and saved
```

---

## Performance

| Operation | Time |
|-----------|------|
| Single terminal execution | 5-10 sec |
| Multi-terminal setup | 3-5 sec |
| Agent execution | 2-5 sec per agent |
| Results save | <1 sec |

---

## Use Cases

✅ **Bug Finding** — Identify issues automatically
✅ **Bug Fixing** — Implement fixes with validation  
✅ **Code Review** — Quality assurance at scale
✅ **Security Audit** — Find vulnerabilities
✅ **Performance Analysis** — Optimize bottlenecks
✅ **Refactoring** — Safely modernize code
✅ **Learning** — Understand agent behavior via multi-terminal

---

## Contributing

To extend the system:

1. **Add New Agents** — Create in `.claude/agents/`
2. **Add New Tools** — Create in `.claude/tools/`
3. **Update CLI** — Modify `workspace_cli/cli.py`
4. **Test** — Use `--multi-terminal` for visibility

---

## Support

### Documentation
- **Quick Commands:** [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)
- **Full System:** [SYSTEM_OVERVIEW.md](./SYSTEM_OVERVIEW.md)
- **Multi-Terminal:** [MULTI_TERMINAL_GUIDE.md](./.claude/docs/MULTI_TERMINAL_GUIDE.md)

### Get Help
```bash
python -m workspace_cli --help
```

---

## Next Steps

1. **Try basic command:**
   ```bash
   python -m workspace_cli solve "Analyze my code"
   ```

2. **Experience multi-terminal:**
   ```bash
   python -m workspace_cli --multi-terminal solve "Fix a bug"
   ```

3. **Review results:**
   ```bash
   ls .agent-workspace/runs/
   cat .agent-workspace/runs/run-*.json
   ```

4. **Read full docs:**
   - See [SYSTEM_OVERVIEW.md](./SYSTEM_OVERVIEW.md) for complete architecture
   - See [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) for command cheatsheet

---

## Version

**v0.1.0** — Initial release with multi-terminal support

---

**Ready to get started?** Run your first command:

```bash
python -m workspace_cli --multi-terminal solve "Find bugs in my code"
```

Watch the agents work in separate terminals! 🚀

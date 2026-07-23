# Terminal Spawning Guide - Actual Parallel Terminal Sessions

This guide shows how to spawn **actual separate Claude Code terminal windows** where each agent runs independently with full visibility and control.

## Quick Start

### Option 1: Spawn and Auto-Monitor (Easiest)

```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

result = orch.execute_and_monitor(
    title="Code Security Audit",
    description="Complete security review",
    subtasks=[
        "Scan for SQL injection vulnerabilities",
        "Check authentication mechanisms",
        "Review CORS configuration",
        "Audit logging setup"
    ],
    spawn_actual_terminals=True,
    auto_wait=True
)

print(f"Job: {result['job_id']}")
print(f"Status: {result['completion_status']}")
```

### Option 2: Spawn Terminals with Manual Monitoring

```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

# Execute and get terminal spawn instructions
result = orch.execute(
    title="API Performance Analysis",
    description="Analyze API performance",
    subtasks=[
        "Analyze slow database queries",
        "Check caching implementation",
        "Profile request handlers"
    ],
    spawn_actual_terminals=True
)

job_id = result['job_id']

# The result includes spawn instructions for manual terminal creation
print(result['instructions'])

# Then manually run the spawn commands in separate terminals
```

### Option 3: File-Based (Original Behavior)

```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=False)  # Default

result = orch.execute(
    title="Code Analysis",
    description="Analyze code",
    subtasks=["Find bugs", "Check performance"]
)

orch.wait(result['job_id'])
```

---

## How It Works

### Visual Architecture

```
┌──────────────────────────────────────────┐
│  Claude Code - Main Terminal             │
│  (Where you run the command)             │
└──────────────┬───────────────────────────┘
               │
        orch.execute_and_monitor()
               │
    ┌──────────┴────────────────┐
    │                           │
    ▼                           ▼
Creates Python Scripts    Generates Instructions
   │                       │
   ├─ agent_001.py        ├─ Terminal 1: python ...
   ├─ agent_002.py        ├─ Terminal 2: python ...
   └─ agent_003.py        └─ Terminal 3: python ...
   
   │
   └─► Auto-spawns if auto_wait=True
   
   Or User spawns manually in separate terminals
   
       Terminal 1                Terminal 2                Terminal 3
       ┌──────────┐            ┌──────────┐            ┌──────────┐
       │ Agent 1  │            │ Agent 2  │            │ Agent 3  │
       │ RUNNING  │            │ RUNNING  │            │ RUNNING  │
       │    │     │            │    │     │            │    │     │
       │    └─────┼────────────┼────┘     │            │    │     │
       │         [PARALLEL EXECUTION]     │            │    │     │
       │              │                   │            │    │     │
       └──────────────┼───────────────────┴────────────┴────┘     │
                      │                                            │
                      └─► Workspace (.claude-workspace/)
                          ├─ agents/
                          ├─ terminals/
                          ├─ jobs/
                          └─ communications/
```

---

## Step-by-Step Examples

### Example 1: Full Automated Execution

**Command:**
```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

result = orch.execute_and_monitor(
    title="Security Audit",
    description="Complete security review",
    subtasks=[
        "SQL Injection Scanning",
        "Authentication Review",
        "Authorization Check",
        "XSS Protection Validation"
    ],
    auto_wait=True,
    timeout=3600
)
```

**What happens:**
1. Job created: `job-182572`
2. 4 Python scripts generated in `.claude-workspace/scripts/`
3. Terminal 1 opens: `agent_411819.py` starts
4. Terminal 2 opens: `agent_307858.py` starts
5. Terminal 3 opens: `agent_510596.py` starts
6. Terminal 4 opens: `agent_625843.py` starts
7. All 4 agents run in parallel
8. Main terminal monitors progress
9. When all complete, shows final results

**Output:**
```
[TARGET] Job created: job-182572

[TERMINALS] Spawned actual terminal sessions...

Terminal 1/4 spawned: Agent 411819
  Task: SQL Injection Scanning...
  Script: .claude-workspace/scripts/agent_411819.py

Terminal 2/4 spawned: Agent 307858
  Task: Authentication Review...
  Script: .claude-workspace/scripts/agent_307858.py

... (etc for all 4)

============================================================
MONITORING TERMINALS...
============================================================

[WAIT] Progress: 0/4 agents completed (0%)
[WAIT] Progress: 1/4 agents completed (25%)
[WAIT] Progress: 2/4 agents completed (50%)
[WAIT] Progress: 4/4 agents completed (100%)

[DONE] All terminals completed!
Results: 4/4 agents
```

---

### Example 2: Manual Terminal Control

**Step 1: Get spawn instructions**
```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

result = orch.execute(
    title="Performance Analysis",
    description="Analyze system performance",
    subtasks=[
        "Database Query Analysis",
        "Memory Profiling",
        "CPU Usage Review"
    ]
)

job_id = result['job_id']

# Show spawn commands
print(orch.show_spawn_commands(job_id))
```

**Output:**
```
======================================================================
SPAWN COMMANDS - Copy and run in separate terminals
======================================================================

Terminal 1:
python .claude-workspace/scripts/agent_411819.py

Terminal 2:
python .claude-workspace/scripts/agent_307858.py

Terminal 3:
python .claude-workspace/scripts/agent_510596.py

======================================================================
```

**Step 2: Open separate Claude Code terminals**

In Claude Code, open 3 new terminals (Terminal 1, 2, 3)

**Step 3: Run spawn commands in each**

Terminal 1:
```bash
python .claude-workspace/scripts/agent_411819.py
```

Terminal 2:
```bash
python .claude-workspace/scripts/agent_307858.py
```

Terminal 3:
```bash
python .claude-workspace/scripts/agent_510596.py
```

**What you'll see in each terminal:**
```
============================================================
Agent Terminal: 411819
Job: job-182572
Task: Database Query Analysis
============================================================

[STARTED] Agent 411819 - 2026-07-23T12:15:00.123456
Task: Database Query Analysis

[EXECUTING] Performing task analysis...

[COMPLETED] Agent 411819 - 2026-07-23T12:15:02.654321
Result: Analysis of: Database Query Analysis

============================================================
Agent terminal closing...
============================================================
```

**Step 4: Monitor from main terminal**
```python
# Monitor progress
orch.wait(job_id)

# Check status anytime
progress = orch.get_progress(job_id)
print(f"Progress: {progress['completed']}/{progress['total']}")
```

---

### Example 3: Spawn Individual Terminals

```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

# Create job first
job_id = orch.workspace.create_job(
    "Incremental Analysis",
    "Add agents incrementally",
    []
)

# Spawn agents one by one
agent1 = orch.spawn_single_terminal(job_id, "First analysis task")
print(f"Agent 1: {agent1['agent_id']}")
print(f"Run: python {agent1['script_file']}")

agent2 = orch.spawn_single_terminal(job_id, "Second analysis task")
print(f"Agent 2: {agent2['agent_id']}")
print(f"Run: python {agent2['script_file']}")

# Add more agents as needed
agent3 = orch.spawn_single_terminal(job_id, "Third analysis task")

# Monitor all
orch.wait(job_id)
```

---

## Viewing Terminal Execution in Real-Time

### From Main Terminal

```powershell
# Watch all agent statuses
while ($true) {
    Clear-Host
    python -c "
from agents import Orchestrator
orch = Orchestrator()
progress = orch.get_progress('job-182572')
for agent in progress['agents']:
    print(f\"{agent['id']}: {agent['status']}\")
"
    Start-Sleep -Seconds 2
}
```

### From Multiple Views

**Terminal 1 (Main Control)**
```bash
python -c "from agents import OrchestratorWithTerminals; orch = OrchestratorWithTerminals(spawn_terminals=True); orch.execute_and_monitor(...)"
```

**Terminal 2 (Monitor Workspace)**
```bash
watch -n 1 'ls -la .claude-workspace/agents/*.json | wc -l'
```

**Terminal 3 (Watch Output)**
```bash
watch -n 1 'cat .claude-workspace/jobs/job-182572/STATUS.md'
```

**Terminals 4-6 (Agent Execution)**
```bash
python .claude-workspace/scripts/agent_411819.py
python .claude-workspace/scripts/agent_307858.py
python .claude-workspace/scripts/agent_510596.py
```

---

## API Reference

### OrchestratorWithTerminals

```python
from agents import OrchestratorWithTerminals

# Create orchestrator with terminal support
orch = OrchestratorWithTerminals(
    workspace=".claude-workspace",
    spawn_terminals=True  # Enable terminal spawning
)

# Execute with auto-monitoring
orch.execute_and_monitor(
    title="...",
    description="...",
    subtasks=[...],
    spawn_actual_terminals=True,
    auto_wait=True,
    timeout=3600
)

# Execute with manual spawning
result = orch.execute(
    title="...",
    description="...",
    subtasks=[...],
    spawn_actual_terminals=True
)

# Spawn single agent
orch.spawn_single_terminal(job_id, task)

# Show terminal status
orch.show_terminal_status(job_id)

# Show spawn commands
orch.show_spawn_commands(job_id)

# Wait for completion
orch.wait(job_id, timeout=3600)

# Get progress
orch.get_progress(job_id)
```

---

## Key Differences: File-Based vs. Terminal-Based

| Feature | File-Based | Terminal-Based |
|---------|-----------|-----------------|
| **Visibility** | Workspace files | Live terminal windows |
| **Interaction** | View results after | Watch real-time output |
| **Agent control** | All agents in background | Each agent in own window |
| **Debugging** | Check logs later | See errors live |
| **Spawn time** | Instant | Slightly delayed (terminal open) |
| **Resource usage** | Low | Higher (multiple terminals) |
| **Monitoring** | Poll workspace | Watch live output |
| **Termination** | Via workspace | Terminal Ctrl+C |

---

## Troubleshooting

### Scripts not being generated
```python
# Check if scripts directory was created
import os
print(os.listdir(".claude-workspace/scripts/"))
```

### Terminal not opening
```python
# Check if script file exists and is executable
import os
script_file = ".claude-workspace/scripts/agent_411819.py"
print(f"File exists: {os.path.exists(script_file)}")
print(f"File size: {os.path.getsize(script_file)}")
```

### Agent not completing
```python
# Check agent status
ws = Workspace()
agent = ws.get_agent("411819")
print(f"Status: {agent['status']}")
print(f"Error: {agent.get('error', 'None')}")
```

---

## Summary

- ✅ **Actual terminals**: Real Claude Code terminal windows for each agent
- ✅ **Full visibility**: Watch agents execute in real-time
- ✅ **Parallel execution**: All agents run simultaneously
- ✅ **Manual control**: Open terminals yourself or auto-spawn
- ✅ **Complete tracking**: Full metadata in workspace
- ✅ **Easy debugging**: See errors and output directly

Use terminal spawning when you need **visual feedback and real-time monitoring** of agent execution!

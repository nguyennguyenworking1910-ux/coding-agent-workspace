# Experimental Agent Teams Features

## Overview

When `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is set to `"1"` in `.claude/settings.json`, the system enables advanced experimental features for agent execution and monitoring.

## Configuration

### Enable Experimental Mode

In `.claude/settings.json`:
```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### Check Configuration

```python
from .claude.config import get_config, is_experimental_mode

# Check if enabled
if is_experimental_mode():
    print("Experimental mode is active!")

# Get all features
config = get_config()
features = config.get_features()
print(features)
```

## Enabled Features

### 1. Agent Tracing

When enabled, each agent execution gets a unique trace ID for tracking:

```
[2024-01-01T10:00:00.123456] [TRACE:abc123] [EXECUTE] Task received: check the security of the system
[2024-01-01T10:00:00.234567] [TRACE:abc123] [CLASSIFY] Task classified as: security
[2024-01-01T10:00:00.345678] [TRACE:abc123] [PLAN] Planning complete
[2024-01-01T10:00:00.456789] [TRACE:abc123] [AGENTS_DETERMINED] Agents needed: ['diagnostician', 'reviewer']
[2024-01-01T10:00:00.567890] [TRACE:abc123] [WORKFLOW_BUILT] Workflow construction complete
```

### 2. Structured Logging

All events are logged with timestamp, trace ID, event type, and optional data:

```python
{
    "timestamp": "2024-01-01T10:00:00.123456",
    "trace_id": "abc123",
    "event": "CLASSIFY",
    "message": "Task classified as: security",
    "data": {}
}
```

### 3. Agent Spawning

Agents are spawned with full context and can be tracked:

```
SPAWNED AGENTS:
├─ diagnostician
│  ├─ Role: Issue Scanner & Analyzer
│  ├─ Task: Scan codebase for security vulnerabilities
│  └─ Trace ID: abc123
│
└─ reviewer
   ├─ Role: Quality Validator
   ├─ Task: Review and validate findings
   └─ Trace ID: abc123
```

### 4. Execution Log

Each agent execution returns an execution log with all events:

```python
result = team_leader.execute("check the security of the system")

# In experimental mode:
if result.get("experimental_mode"):
    trace_id = result["trace_id"]
    log = result["execution_log"]
    
    for entry in log:
        print(f"[{entry['timestamp']}] {entry['event']}: {entry['message']}")
```

## Usage Examples

### Command Line

```bash
# Automatically detects experimental mode from settings.json
/solve "check the security of the system"

# Output will show:
# [Configuration info]
# [Execution trace with timestamps]
# [Agent spawning details]
# [Workflow results]
```

### Python Code

```python
from .claude.agents.technical import TeamLeaderAgent
from .claude.config import is_experimental_mode

team_leader = TeamLeaderAgent()

# Execute task
result = team_leader.execute("find bugs in my code")

# Check if experimental mode
if is_experimental_mode():
    print(f"Trace ID: {result['trace_id']}")
    print(f"Execution took {len(result['execution_log'])} events")
    
    for event in result['execution_log']:
        print(f"{event['timestamp']}: {event['event']}")
```

## Multi-Terminal Monitoring

When experimental mode is enabled, you can monitor execution in multiple terminals:

### Terminal 1: Run task
```bash
/solve "your task"
```

### Terminal 2: Watch trace
```bash
tail -f .agent-workspace/execution.log | grep "TRACE"
```

### Terminal 3: Monitor agents
```bash
watch -n 1 'cat .agent-workspace/status.json | grep "trace_id"'
```

## Output Format

### Standard Output (Experimental Mode Enabled)

```
================================================================================
Agent Configuration:
==================================================
[ENABLED] Experimental Agent Teams Mode
  └─ Agent Tracing: ENABLED
  └─ Structured Logging: ENABLED
  └─ Agent Spawning: ENABLED

==================================================

🚀 Team Leader Agent Executing: solve
📋 Task: check the security of the system

============================================================

[2024-01-01T10:00:00.123456] [TRACE:abc123] [EXECUTE] Task received: check the security of the system
[2024-01-01T10:00:00.234567] [TRACE:abc123] [CLASSIFY] Task classified as: security
[2024-01-01T10:00:00.345678] [TRACE:abc123] [PLAN] Planning complete
[2024-01-01T10:00:00.456789] [TRACE:abc123] [AGENTS_DETERMINED] Agents needed: ['diagnostician', 'reviewer']
[2024-01-01T10:00:00.567890] [TRACE:abc123] [WORKFLOW_BUILT] Workflow construction complete

============================================================
EXECUTION TRACE
============================================================
Trace ID: abc123

Execution Log:
  {'timestamp': '2024-01-01T10:00:00.123456', 'trace_id': 'abc123', 'event': 'EXECUTE', ...}
  {'timestamp': '2024-01-01T10:00:00.234567', 'trace_id': 'abc123', 'event': 'CLASSIFY', ...}
  ...
```

### Standard Output (Experimental Mode Disabled)

```
🚀 Team Leader Agent Executing: solve
📋 Task: check the security of the system

============================================================
[Result without trace information]
```

## Features Enabled by Default

When `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` = "1":

| Feature | Status | Description |
|---------|--------|-------------|
| Agent Tracing | ✅ ENABLED | Unique trace ID for each execution |
| Structured Logging | ✅ ENABLED | Timestamp + event logging |
| Agent Spawning | ✅ ENABLED | Full agent execution |
| Execution Log | ✅ ENABLED | Event history in results |
| Timestamp Tracking | ✅ ENABLED | ISO format timestamps |

## Troubleshooting

### Trace Not Appearing

```python
from .claude.config import get_config

config = get_config()
if not config.experimental_agent_teams_enabled:
    print("Experimental mode is not enabled!")
    print("Check settings.json for CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS")
```

### Configuration Not Loading

```bash
# Verify settings.json exists and is valid
cat .claude/settings.json | python -m json.tool

# Check that env variable is set correctly
grep "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" .claude/settings.json
```

## Performance Impact

- **Minimal overhead**: Tracing adds ~1-2ms per event
- **Memory usage**: Execution log stored in memory until cleared
- **Disk usage**: Optional - logging to files is not enabled by default

## Next Steps

1. Enable experimental mode in `settings.json`
2. Run `/solve "your task"` to see tracing
3. Monitor execution in multiple terminals
4. Review execution logs for debugging
5. Disable by setting `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` to `"0"`


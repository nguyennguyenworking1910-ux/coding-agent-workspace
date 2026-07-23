# Terminal-Based Execution - Quick Reference

**Copy-paste these commands into Claude Code terminal to run the system.**

---

## 🚀 ONE-LINER EXECUTION

```powershell
python -c "from agents import OrchestratorWithTerminals; OrchestratorWithTerminals(spawn_terminals=True).execute_and_monitor('My Analysis', 'Analyzing', ['Task 1', 'Task 2', 'Task 3'], auto_wait=True)"
```

---

## 📝 COMMON TASKS

### 1. Security Audit

```powershell
python -c "
from agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)
orch.execute_and_monitor(
    'Security Audit',
    'Complete security review',
    [
        'Scan for SQL injection',
        'Check authentication',
        'Review CORS',
        'Audit logging'
    ],
    auto_wait=True
)
"
```

### 2. Code Analysis

```powershell
python -c "
from agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)
orch.execute_and_monitor(
    'Code Analysis',
    'Analyze code',
    [
        'Find bugs',
        'Check performance',
        'Review security'
    ],
    auto_wait=True
)
"
```

### 3. Performance Review

```powershell
python -c "
from agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)
orch.execute_and_monitor(
    'Performance Review',
    'Review system performance',
    [
        'Database queries',
        'Memory usage',
        'CPU profiling',
        'Network latency'
    ],
    auto_wait=True
)
"
```

### 4. Parallel Independent Tasks

```powershell
python -c "
from agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)

# Job 1
orch.execute_and_monitor('API Review', 'Review API', ['Check endpoints', 'Validate auth'], auto_wait=True)

# Job 2 (while Job 1 runs, or after)
orch.execute_and_monitor('DB Review', 'Review DB', ['Check queries', 'Check indexes'], auto_wait=True)
"
```

---

## 🎯 CHECK STATUS / VIEW RESULTS

### List All Jobs

```powershell
ls .claude-workspace/jobs/
```

### View Job Status

```powershell
cat .claude-workspace/jobs/job-582940/STATUS.md
```

### View Job Results

```powershell
Get-Content .claude-workspace/jobs/job-582940/OUTPUT/*.txt
```

### Check Progress Programmatically

```powershell
python -c "
from agents import Orchestrator
orch = Orchestrator()
progress = orch.get_progress('job-582940')
print(f'Progress: {progress[\"completed\"]}/{progress[\"total\"]} ({progress[\"percentage\"]:.0f}%)')
"
```

---

## 🔧 ADVANCED

### Get Spawn Commands (Manual Terminal Control)

```powershell
python -c "
from agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)
result = orch.execute('Title', 'Description', ['Task 1', 'Task 2'], spawn_actual_terminals=True)
print(orch.show_spawn_commands(result['job_id']))
"
```

### Monitor Workspace in Real-Time

```powershell
# Watch agent count grow
while ($true) {
    Write-Host (ls .claude-workspace/agents/*.json | Measure-Object | Select-Object -ExpandProperty Count)
    Start-Sleep -Seconds 2
}
```

### Spawn Single Agent

```powershell
python -c "
from agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)
job_id = orch.workspace.create_job('Title', 'Description', [])
result = orch.spawn_single_terminal(job_id, 'My task')
print(f'Run: python {result[\"script_file\"]}')
"
```

---

## 📊 MONITORING TEMPLATES

### Template 1: Simple Progress Monitor

```powershell
python -c "
from agents import Orchestrator
import time

orch = Orchestrator()
job_id = 'job-582940'

while True:
    progress = orch.get_progress(job_id)
    print(f'Progress: {progress[\"completed\"]}/{progress[\"total\"]} - {progress[\"percentage\"]:.0f}%')
    
    if progress['completed'] == progress['total']:
        print('DONE!')
        break
    
    time.sleep(5)
"
```

### Template 2: Watch Multiple Jobs

```powershell
python -c "
from agents import Orchestrator

orch = Orchestrator()
jobs = ['job-582940', 'job-495284', 'job-610293']

for job_id in jobs:
    progress = orch.get_progress(job_id)
    status = 'DONE' if progress['completed'] == progress['total'] else 'RUNNING'
    print(f'{job_id}: {progress[\"completed\"]}/{progress[\"total\"]} - {status}')
"
```

---

## 💡 TIPS

| Task | Command |
|------|---------|
| **Run analysis** | `python -c "from agents import OrchestratorWithTerminals; OrchestratorWithTerminals(spawn_terminals=True).execute_and_monitor('Title', 'Desc', ['Task'], auto_wait=True)"` |
| **List jobs** | `ls .claude-workspace/jobs/` |
| **View job context** | `cat .claude-workspace/jobs/job-ID/CONTEXT.md` |
| **View results** | `cat .claude-workspace/jobs/job-ID/OUTPUT/*.txt` |
| **Check agent status** | `python -c "from agents import Orchestrator; print(Orchestrator().get_progress('job-ID'))"` |
| **Stop monitoring** | Press `Ctrl+C` in terminal |

---

## 🎓 WORKFLOW EXAMPLE

```powershell
# Step 1: Start an analysis
python -c "
from agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)
result = orch.execute_and_monitor(
    'Analysis',
    'Testing',
    ['Task 1', 'Task 2', 'Task 3'],
    auto_wait=True
)
print(f'Job: {result[\"job_id\"]}')
"

# Step 2: While running, check progress in another terminal
python -c "from agents import Orchestrator; print(Orchestrator().get_progress('job-ID'))"

# Step 3: View results when done
cat .claude-workspace/jobs/job-ID/OUTPUT/*.txt
```

---

## ⚡ FASTEST START

**Save this as `run.py` in your workspace root:**

```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

# Just edit the title, description, and tasks below
result = orch.execute_and_monitor(
    title="My Analysis",
    description="What I'm analyzing",
    subtasks=[
        "Task 1",
        "Task 2",
        "Task 3"
    ],
    auto_wait=True
)
```

**Then run:**
```powershell
python run.py
```

That's it! 🚀

---

## 🔗 FULL DOCUMENTATION

- **Terminal Spawning Guide**: `.claude/TERMINAL_SPAWNING_GUIDE.md`
- **Workflows & Examples**: `.claude/TERMINAL_BASED_WORKFLOWS.md`
- **System Architecture**: `.claude/MULTI_AGENT_SYSTEM_GUIDE.md`
- **Usage Guide**: `./USAGE_GUIDE.md`

---

## ❓ QUICK TROUBLESHOOTING

| Issue | Solution |
|-------|----------|
| Scripts not generated | Check: `ls .claude-workspace/scripts/` |
| Agent not starting | Verify script exists: `python .claude-workspace/scripts/agent_ID.py` |
| No output visible | Check job folder: `ls .claude-workspace/jobs/job-ID/OUTPUT/` |
| Terminal not opening | Run script manually in separate terminal |
| Job stuck | Press `Ctrl+C` to stop monitoring (job continues in background) |

---

## 🎯 REMEMBER

- `auto_wait=True` = Automatic monitoring from main terminal
- `spawn_actual_terminals=True` = Generate scripts (manual or auto-spawn)
- Each subtask = One agent terminal
- Results stored in `.claude-workspace/jobs/{job-id}/`
- All metadata tracked in JSON files
- Safe to check status anytime
- Can run multiple jobs in parallel

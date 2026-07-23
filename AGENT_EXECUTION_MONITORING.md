# Agent Execution Monitoring Guide

How to display and monitor agent team execution in another terminal.

## Current System Capabilities

The system has **experimental agent teams mode** enabled with:
- ✓ Trace ID generation (unique per execution)
- ✓ Structured logging with timestamps
- ✓ Execution event tracking
- ✓ Run persistence in `.agent-workspace/runs/`

---

## Method 1: View Execution Logs in Real-Time

### Terminal 1 - Start Agent Execution
```bash
python -m coding-agent solve "your task here"
```

This will print execution trace with timestamps and TRACE ID:
```
[2026-07-22T17:56:19.031684] [TRACE:98429128] [INIT] Team Leader initialized
[2026-07-22T17:56:19.031684] [TRACE:98429128] [CLASSIFY] Task classified as: quality
[2026-07-22T17:56:19.031684] [TRACE:98429128] [AGENTS_DETERMINED] Agents needed: [...]
```

### Terminal 2 - Monitor Run Results
```bash
# Watch for new run files
Get-ChildItem -Path .agent-workspace/runs/ -Name | Sort-Object -Descending | Select-Object -First 1

# Read the latest run output
Get-Content .agent-workspace/runs/run-*.json | ConvertFrom-Json | Select-Object -ExpandProperty result
```

---

## Method 2: Tail Execution Log File

### Terminal 1
```bash
python -m coding-agent solve "analyze code for bugs"
```

### Terminal 2 - Monitor with continuous output
```powershell
# PowerShell - Watch for new runs continuously
while($true) {
    $latestRun = Get-ChildItem .agent-workspace/runs -Name | Sort-Object -Descending | Select-Object -First 1
    if ($latestRun) {
        Write-Host "Latest run: $latestRun"
        Get-Content .agent-workspace/runs/$latestRun | ConvertFrom-Json | Select-Object timestamp, trace_id, run_id
    }
    Start-Sleep -Seconds 2
}
```

---

## Method 3: Use Trace IDs for Filtering

Every execution gets a unique trace ID for easy filtering:

### Terminal 1
```bash
python -m coding-agent solve "check security"
# Outputs: [TRACE:98429128] - note this ID
```

### Terminal 2 - Filter by Trace ID
```bash
# Search for all events with this trace ID across all runs
grep -r "TRACE:98429128" .agent-workspace/runs/
```

---

## Method 4: Parse JSON Results

### Terminal 1
```bash
python -m coding-agent solve "review code changes"
```

### Terminal 2 - Parse and display results
```powershell
# Get the latest run and parse results
$latestRun = Get-ChildItem .agent-workspace/runs -Name | Sort-Object -Descending | Select-Object -First 1
$runData = Get-Content .agent-workspace/runs/$latestRun | ConvertFrom-Json

Write-Host "Run ID: $($runData.run_id)"
Write-Host "Task: $($runData.task)"
Write-Host "Result:`n$($runData.result)"
```

---

## Method 5: Create a Monitoring Dashboard Script

Create `monitor_agents.ps1`:

```powershell
# Agent Execution Monitor
param(
    [int]$RefreshInterval = 2
)

while($true) {
    Clear-Host
    Write-Host "=" * 70
    Write-Host "AGENT EXECUTION MONITOR" -ForegroundColor Cyan
    Write-Host "=" * 70
    Write-Host "Last Updated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Green
    Write-Host ""
    
    # Show latest runs
    $runs = Get-ChildItem .agent-workspace/runs -Name | Sort-Object -Descending | Select-Object -First 5
    
    if ($runs) {
        Write-Host "Recent Executions:" -ForegroundColor Yellow
        foreach ($run in $runs) {
            $data = Get-Content .agent-workspace/runs/$run | ConvertFrom-Json
            Write-Host "  - $($data.run_id)"
            Write-Host "    Task: $($data.task.Substring(0, [Math]::Min(50, $data.task.Length)))..."
            Write-Host "    Time: $($data.timestamp)"
            Write-Host ""
        }
    } else {
        Write-Host "No runs yet. Start with: python -m coding-agent solve '<task>'" -ForegroundColor Red
    }
    
    Write-Host "=" * 70
    Write-Host "Press Ctrl+C to exit (refreshing every ${RefreshInterval}s)"
    Start-Sleep -Seconds $RefreshInterval
}
```

**Run in Terminal 2:**
```bash
.\monitor_agents.ps1
```

---

## Method 6: Real-Time Log Streaming

### Terminal 1
```bash
python -m coding-agent solve "fix authentication issues" > execution.log 2>&1
```

### Terminal 2 - Monitor output file
```powershell
# PowerShell - tail the log file
Get-Content execution.log -Wait -Tail 20
```

---

## Method 7: Programmatic Monitoring

Create `monitor.py`:

```python
import json
import os
from pathlib import Path
from datetime import datetime

def monitor_runs():
    runs_dir = Path(".agent-workspace/runs")
    
    while True:
        if runs_dir.exists():
            runs = sorted(runs_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
            
            if runs:
                latest = runs[0]
                with open(latest) as f:
                    data = json.load(f)
                
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Latest Execution")
                print(f"  Run ID: {data['run_id']}")
                print(f"  Task: {data['task'][:60]}...")
                print(f"  Status: COMPLETED")
                
                # Extract trace ID from result if available
                if "TRACE:" in data['result']:
                    trace_id = data['result'].split("TRACE:")[1].split("]")[0]
                    print(f"  Trace ID: {trace_id}")
        
        import time
        time.sleep(2)

if __name__ == "__main__":
    monitor_runs()
```

**Run in Terminal 2:**
```bash
python monitor.py
```

---

## Recommended Setup

**For the best multi-terminal monitoring experience:**

1. **Terminal 1** (Execution):
   ```bash
   python -m coding-agent solve "your analysis task"
   ```

2. **Terminal 2** (Monitoring Dashboard):
   ```bash
   .\monitor_agents.ps1
   ```

3. **Terminal 3** (Optional - Search/Filter):
   ```bash
   # Watch a specific run's results
   Get-Content .agent-workspace/runs/run-*.json -Wait | ConvertFrom-Json | Select-Object run_id, task, timestamp
   ```

---

## Key Features Available

- **Trace IDs**: Unique per execution for filtering across terminals
- **Timestamps**: Track execution timeline
- **Run Directory**: All results saved to `.agent-workspace/runs/`
- **Structured Logging**: JSON format for programmatic access
- **Experimental Mode**: Real-time event logging with TRACE output

---

## Environment Variables

Enable/disable features:

```powershell
# Enable experimental features (already enabled in settings.json)
$env:CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1"

# Run with monitoring
python -m coding-agent solve "task"
```

---

## Tips

- Use **TRACE IDs** to correlate execution across multiple terminals
- **JSON runs** are stored persistently for historical analysis
- **Real-time output** shows during execution in Terminal 1
- **Structured logs** can be parsed for custom dashboards
- **Refresh intervals** can be adjusted for responsiveness vs. performance

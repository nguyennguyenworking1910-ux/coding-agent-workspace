# Terminal-Based Workflows - Complete Practical Guide

This guide shows real, copy-paste ready workflows for running the multi-agent system with actual terminal windows.

---

## 🎯 The Terminal-Based Approach

Instead of file-based coordination, spawn **real Claude Code terminal windows** where each agent runs independently with full visibility.

```
You type command
    ↓
Main Terminal spawns scripts
    ↓
Terminal 1 opens → Agent A runs
Terminal 2 opens → Agent B runs
Terminal 3 opens → Agent C runs
    ↓
All run in parallel with live output
    ↓
Main terminal monitors progress
    ↓
Results available when done
```

---

## 1. SIMPLEST EXAMPLE - One Command

### Setup (30 seconds)

```powershell
# Copy this into Claude Code terminal:
python -c "
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)
result = orch.execute_and_monitor(
    title='My First Analysis',
    description='Testing terminal spawning',
    subtasks=['Task 1', 'Task 2', 'Task 3'],
    auto_wait=True
)
"
```

### What Happens

1. Main terminal shows: `Job created: job-493288`
2. Scripts generated automatically
3. Terminals spawn (or you can run manually)
4. Each agent runs independently
5. Main terminal shows progress: `0/3... 1/3... 2/3... 3/3 DONE!`

### Output Example

```
[TARGET] Job created: job-493288

[TERMINALS] Spawned 3 terminal sessions in parallel

Terminal 1/3 spawned: Agent 026693
  Task: Task 1...

Terminal 2/3 spawned: Agent 970804
  Task: Task 2...

Terminal 3/3 spawned: Agent 291002
  Task: Task 3...

[STATUS] Terminal Status for job-493288
======================================================================
1. [WAIT] agent-026693
   Task: Task 1...
   Status: pending

2. [WAIT] agent-970804
   Task: Task 2...
   Status: pending

3. [WAIT] agent-291002
   Task: Task 3...
   Status: pending

[MONITORING TERMINALS...]
[WAIT] Progress: 0/3 agents completed (0%)
[WAIT] Progress: 1/3 agents completed (33%)
[WAIT] Progress: 2/3 agents completed (67%)
[WAIT] Progress: 3/3 agents completed (100%)

[DONE] All terminals completed!
Results: 3/3 agents
```

---

## 2. REAL WORLD EXAMPLE - Security Audit

### Python Script (save as `run_security_audit.py`)

```python
#!/usr/bin/env python3
"""Security Audit - Terminal-Based Execution"""

from agents import OrchestratorWithTerminals

def run_security_audit():
    """Run comprehensive security audit with parallel agents."""
    
    orch = OrchestratorWithTerminals(spawn_terminals=True)
    
    result = orch.execute_and_monitor(
        title="Complete Security Audit",
        description="Comprehensive security review of the entire system",
        subtasks=[
            "Scan for SQL injection vulnerabilities in database queries",
            "Check authentication implementation and token handling",
            "Review CORS configuration and cross-origin requests",
            "Audit logging setup and security event tracking",
            "Validate input sanitization across all endpoints",
            "Check password hashing algorithms and salt usage"
        ],
        spawn_actual_terminals=True,
        auto_wait=True,
        timeout=3600
    )
    
    job_id = result['job_id']
    print(f"\n{'='*70}")
    print(f"Security Audit Complete")
    print(f"{'='*70}")
    print(f"Job ID: {job_id}")
    print(f"Agents spawned: {result['count']}")
    print(f"Status: {result['completion_status']}")
    print(f"\nResults stored in: .claude-workspace/jobs/{job_id}/")
    print(f"{'='*70}\n")
    
    return result

if __name__ == "__main__":
    run_security_audit()
```

### Run It

```powershell
python run_security_audit.py
```

### What You'll See

**Main Terminal:**
```
[TARGET] Job created: job-582940

[TERMINALS] Spawned 6 terminal sessions in parallel

Terminal 1/6 spawned: Agent 823572
  Task: Scan for SQL injection vulnerabilities...

Terminal 2/6 spawned: Agent 744271
  Task: Check authentication implementation...

... (4 more agents)

[MONITORING TERMINALS...]
[WAIT] Progress: 0/6 agents completed (0%)
[WAIT] Progress: 1/6 agents completed (17%)
[WAIT] Progress: 2/6 agents completed (33%)
... (continues until 100%)

[DONE] All terminals completed!
Results: 6/6 agents

======================================================================
Security Audit Complete
======================================================================
Job ID: job-582940
Agents spawned: 6
Status: completed

Results stored in: .claude-workspace/jobs/job-582940/
======================================================================
```

**Each Agent Terminal (running in parallel):**
```
============================================================
Agent Terminal: 823572
Job: job-582940
Task: Scan for SQL injection vulnerabilities in database queries
============================================================

[STARTED] Agent 823572 - 2026-07-23T14:00:00.123456
Task: Scan for SQL injection vulnerabilities in database queries

[EXECUTING] Performing task analysis...

[COMPLETED] Agent 823572 - 2026-07-23T14:00:02.654321
Result: Analysis of: Scan for SQL injection vulnerabilities in database queries

============================================================
Agent terminal closing...
============================================================
```

---

## 3. MULTI-PHASE WORKFLOW - Analysis → Review → Report

```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

# Phase 1: Code Analysis
print("\n=== PHASE 1: Code Analysis ===\n")
analysis = orch.execute_and_monitor(
    title="Code Analysis",
    description="Analyze codebase for issues",
    subtasks=[
        "Find bugs in database module",
        "Check performance issues",
        "Review security concerns"
    ],
    auto_wait=True
)

print(f"\nAnalysis job: {analysis['job_id']}")

# Phase 2: Code Review
print("\n=== PHASE 2: Code Review ===\n")
review = orch.execute_and_monitor(
    title="Code Review",
    description="Review code quality",
    subtasks=[
        "Review API endpoints",
        "Check error handling",
        "Validate best practices"
    ],
    auto_wait=True
)

print(f"\nReview job: {review['job_id']}")

# Phase 3: Generate Report
print("\n=== PHASE 3: Generate Report ===\n")
report_job = orch.workspace.create_job(
    "Final Report",
    "Generated from analysis and review",
    []
)

print(f"\nAll phases completed!")
print(f"Analysis: {analysis['job_id']}")
print(f"Review: {review['job_id']}")
print(f"Report: {report_job}")
```

---

## 4. INTERACTIVE MODE - Build Plan as You Go

```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

print("Interactive Terminal-Based Execution")
print("="*60)

# Get plan from user
title = input("\nEnter plan title: ")
description = input("Enter plan description: ")

print("\nEnter tasks (one per line, type 'END' when done):")
tasks = []
while True:
    task = input(f"  Task {len(tasks)+1}: ")
    if task.upper() == "END":
        break
    if task:
        tasks.append(task)

if tasks:
    print(f"\nExecuting plan: {title}")
    print(f"Tasks: {len(tasks)}")
    
    result = orch.execute_and_monitor(
        title=title,
        description=description,
        subtasks=tasks,
        auto_wait=True
    )
    
    print(f"\nCompleted!")
    print(f"Job: {result['job_id']}")
else:
    print("No tasks entered.")
```

---

## 5. BATCH EXECUTION - Run Multiple Jobs

```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

jobs = [
    {
        "title": "API Analysis",
        "description": "Analyze API layer",
        "tasks": ["Check endpoints", "Validate responses", "Test error handling"]
    },
    {
        "title": "Database Analysis",
        "description": "Analyze database layer",
        "tasks": ["Review queries", "Check indexes", "Validate constraints"]
    },
    {
        "title": "Security Review",
        "description": "Complete security review",
        "tasks": ["Find vulnerabilities", "Check auth", "Review permissions"]
    }
]

results = []

for i, job in enumerate(jobs, 1):
    print(f"\n{'='*60}")
    print(f"Job {i}/{len(jobs)}: {job['title']}")
    print(f"{'='*60}\n")
    
    result = orch.execute_and_monitor(
        title=job['title'],
        description=job['description'],
        subtasks=job['tasks'],
        auto_wait=True
    )
    
    results.append({
        'title': job['title'],
        'job_id': result['job_id'],
        'agents': result['count'],
        'status': result['completion_status']
    })

# Summary
print(f"\n{'='*60}")
print("ALL JOBS COMPLETED")
print(f"{'='*60}\n")

for i, result in enumerate(results, 1):
    print(f"{i}. {result['title']}")
    print(f"   Job: {result['job_id']}")
    print(f"   Agents: {result['agents']}")
    print(f"   Status: {result['status']}\n")
```

---

## 6. ADVANCED - Custom Agent Scripts

If you want to customize what each agent does, edit the generated script:

```python
from agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

# Execute to generate scripts (don't auto-wait)
result = orch.execute(
    title="Custom Analysis",
    description="Run custom analysis",
    subtasks=["Task A", "Task B"],
    spawn_actual_terminals=True
)

job_id = result['job_id']

# Scripts are now in: .claude-workspace/scripts/agent_*.py
# Edit them as needed
print(f"\nScripts generated in: .claude-workspace/scripts/")
print(f"Edit them as needed, then run:")
print(f"  python .claude-workspace/scripts/agent_*.py")

# Or run manually from terminals
print(orch.show_spawn_commands(job_id))
```

---

## 7. MONITORING - Check Progress Later

```python
from agents import Orchestrator

orch = Orchestrator()

job_id = "job-582940"  # Your job ID

# Get progress anytime
progress = orch.get_progress(job_id)

print(f"Job: {job_id}")
print(f"Progress: {progress['completed']}/{progress['total']} agents")
print(f"Percentage: {progress['percentage']:.0f}%")

# Show each agent status
print("\nAgent Status:")
for agent in progress['agents']:
    print(f"  {agent['id']}: {agent['status']}")
    if agent.get('result'):
        print(f"    Result: {agent['result']}")

# Get aggregated output
if progress['completed'] == progress['total']:
    output = orch.get_output(job_id)
    print(f"\nAggregated Output:\n{output}")
```

---

## 8. TERMINAL COMMANDS REFERENCE

### Run a Simple Analysis (Copy-Paste Ready)

```powershell
python -c "
from agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)
orch.execute_and_monitor('Test', 'Testing', ['Task A', 'Task B'], auto_wait=True)
"
```

### Create and Run a Job File

```powershell
# Create file: analyze_code.py
# (Copy from Example 2 above)

# Then run:
python analyze_code.py
```

### Check Job Status

```powershell
python -c "
from agents import Orchestrator
orch = Orchestrator()
progress = orch.get_progress('job-582940')
print(f'Status: {progress[\"completed\"]}/{progress[\"total\"]}')
"
```

### View Job Results

```powershell
# List all jobs
ls .claude-workspace/jobs/

# View specific job
cat .claude-workspace/jobs/job-582940/STATUS.md

# View agent outputs
Get-Content .claude-workspace/jobs/job-582940/OUTPUT/*.txt
```

---

## 9. BEST PRACTICES

### ✅ DO

- Use `auto_wait=True` for simple workflows
- Give descriptive task names
- Run multiple independent jobs in sequence
- Monitor progress in separate terminal
- Save results frequently

### ❌ DON'T

- Don't use extremely long task names (>100 chars)
- Don't spawn 100+ agents at once (resource intensive)
- Don't close terminals before job completes
- Don't edit workspace files while jobs are running
- Don't use special characters in job titles

---

## 10. COMPLETE WORKING EXAMPLE

Save as `example_workflow.py`:

```python
#!/usr/bin/env python3
"""Complete terminal-based workflow example."""

from agents import OrchestratorWithTerminals

def main():
    print("\n" + "="*70)
    print("TERMINAL-BASED MULTI-AGENT WORKFLOW")
    print("="*70 + "\n")
    
    orch = OrchestratorWithTerminals(spawn_terminals=True)
    
    # Define workflow
    workflows = [
        {
            "name": "Code Quality Check",
            "tasks": [
                "Find bugs and errors",
                "Check code style",
                "Review performance"
            ]
        },
        {
            "name": "Security Audit",
            "tasks": [
                "Scan vulnerabilities",
                "Check authentication",
                "Review permissions"
            ]
        }
    ]
    
    all_jobs = []
    
    # Execute each workflow
    for workflow in workflows:
        print(f"\nStarting: {workflow['name']}")
        print("-" * 70)
        
        result = orch.execute_and_monitor(
            title=workflow['name'],
            description=f"Automated {workflow['name'].lower()}",
            subtasks=workflow['tasks'],
            auto_wait=True,
            timeout=1800
        )
        
        all_jobs.append({
            'name': workflow['name'],
            'job_id': result['job_id'],
            'status': result['completion_status']
        })
    
    # Final summary
    print("\n" + "="*70)
    print("WORKFLOW SUMMARY")
    print("="*70 + "\n")
    
    for job in all_jobs:
        status_icon = "[OK]" if job['status'] == "completed" else "[WAIT]"
        print(f"{status_icon} {job['name']}")
        print(f"     Job: {job['job_id']}\n")
    
    print("="*70)
    print("All workflows completed!")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
```

### Run It

```powershell
python example_workflow.py
```

---

## Summary

**Terminal-Based Execution gives you:**

✅ Real terminal windows for each agent  
✅ Live output and feedback  
✅ Full control and visibility  
✅ Easy debugging  
✅ Parallel execution with monitoring  
✅ Simple setup - just one command!

**Get started now:**

```python
from agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)
orch.execute_and_monitor("My Plan", "Description", ["Task 1", "Task 2"], auto_wait=True)
```

That's it! 🚀

# System Capabilities and Natural Language Guide

## PART 1: WHAT IS THIS SYSTEM?

### The Problem It Solves

This is a **multi-agent orchestrator system** designed to automate code analysis, quality assurance, and business operations (sales analytics). Instead of manually analyzing code, writing tests, or querying databases, you describe what you need in plain English and agents work in parallel to deliver results.

### How It Works at High Level

```
Your Request (Plain English)
    ↓
Team Leader Agent (receives request)
    ↓
Classifies task type and determines needed agents
    ↓
Spawns agents in parallel (Diagnostician, Bug Fixer, Reviewer, etc.)
    ↓
Agents execute independently with assigned tools
    ↓
Workspace coordinates and tracks execution
    ↓
Results aggregated and returned
```

### What Makes It Unique

1. **Intelligent Routing**: Automatically determines which agents you need based on your request
2. **Parallel Execution**: All agents run simultaneously, not sequentially
3. **Real-time Monitoring**: Watch agents work in multiple terminals
4. **Inter-agent Communication**: Agents can share messages and context
5. **Structured Tracking**: Jobs, agents, terminals all tracked in workspace
6. **Experimental Tracing**: Optional execution trace IDs for debugging
7. **Multi-department**: Technical (code analysis) + Business (sales operations) agents

---

## PART 2: SYSTEM CAPABILITIES

### Technical Capabilities (Code Analysis)

| Capability | Agent(s) | What It Does | Example |
|------------|---------|-------------|---------|
| **Find Bugs** | Diagnostician | Scans code for errors, logic issues, security problems | "Find all bugs in my authentication module" |
| **Fix Issues** | Bug Fixer | Implements code fixes with write access | "Fix the memory leak I found" |
| **Code Review** | Reviewer | Validates code quality, design, performance | "Review my API endpoint implementation" |
| **Security Audit** | Diagnostician | Identifies vulnerabilities, injection points, auth issues | "Check for security vulnerabilities in this code" |
| **Performance Analysis** | Diagnostician | Finds slow code, inefficient algorithms, optimization opportunities | "Why is this database query slow?" |
| **Quality Check** | Reviewer | Ensures code meets standards, best practices, patterns | "Is my code well-structured?" |
| **Architecture Review** | Team Leader + Reviewer | Analyzes system design and organization | "Review the architecture of my service" |

### Business Capabilities (Sales Operations)

| Capability | Agent | What It Does | Example |
|------------|-------|-------------|---------|
| **Query Sales Data** | Group Sale Manager | Custom BigQuery SQL queries on sales data | "Show all sales from Q4 2024" |
| **Get Sales Summary** | Group Sale Manager | Aggregated metrics by group/region/time | "Get sales by region and product" |
| **Find Top Performers** | Group Sale Manager | Identifies best-performing groups by metric | "Top 10 groups by revenue in 2024" |
| **Performance Evaluation** | Group Sale Manager | Detailed analysis of specific group | "Evaluate group ID 5432 performance" |
| **Export Results** | Group Sale Manager | Convert results to CSV/JSON/Parquet/Avro | "Export sales data to CSV for reporting" |
| **Complex Analysis** | Group Sale Manager | Multi-table joins and aggregations | "Show sales by group with growth trends" |

### System-Level Capabilities

| Capability | Tool | What It Does |
|------------|------|-------------|
| **Parallel Execution** | Orchestrator | Run multiple agents simultaneously on different tasks |
| **Job Tracking** | Workspace | Create and monitor named jobs with subtasks |
| **Terminal Management** | TerminalSpawner | Spawn actual Claude Code terminals for agents |
| **Agent Monitoring** | Orchestrator | Watch agent progress, check status in real-time |
| **Result Aggregation** | Workspace | Collect and combine results from all agents |
| **Inter-agent Messaging** | Workspace | Allow agents to communicate and share context |
| **Execution Tracing** | Team Leader | Optional trace IDs for debugging and tracking |
| **Schema Management** | Schema Reader | Read and validate BigQuery table definitions |

---

## PART 3: HOW TO USE WITH NATURAL LANGUAGE

### Method 1: Direct Python (Most Common)

```python
# Import the orchestrator
from .claude.agents import OrchestratorWithTerminals

# Create orchestrator instance
orch = OrchestratorWithTerminals()

# Execute your task
result = orch.execute(
    title="Security Audit",
    description="Complete security analysis of codebase",
    subtasks=[
        "Find vulnerabilities in authentication module",
        "Check for injection points in database queries",
        "Review API endpoint authorization logic",
        "Scan for hardcoded secrets"
    ],
    spawn_actual_terminals=True
)

# Monitor progress
orch.show_terminal_status(result["job_id"])

# Get results
output = orch.get_output(result["job_id"])
print(output)
```

### Method 2: Team Leader Direct (Task Classification)

```python
from .claude.agents import TeamLeaderAgent

# Create team leader
leader = TeamLeaderAgent()

# Give it a task - it automatically determines which agents to spawn
result = leader.execute("Find bugs and security issues in my authentication module")

# Result contains spawned agents, workflow, and execution plan
print(f"Task Type: {result['task_type']}")
print(f"Agents Spawned: {result['agents']}")
print(f"Workflow: {result['workflow']}")
```

### Method 3: Specific Agent Direct

```python
from .claude.agents import DiagnosticianAgent, BugFixerAgent

# Diagnostician for analysis only
diagnostician = DiagnosticianAgent()
issues = diagnostician.execute("Analyze my payment processing code for bugs")

# Bug Fixer for implementation
bug_fixer = BugFixerAgent()
fixes = bug_fixer.execute("Fix the race condition in order confirmation")
```

### Method 4: Sales Operations

```python
from .claude.agents import GroupSaleManagerAgent

# Create sales agent
sales = GroupSaleManagerAgent()

# Execute sales query
result = sales.execute("Show top 10 groups by revenue with monthly trends")

# Or query directly
sales_data = sales.query_sales(
    sql="SELECT group_id, SUM(revenue) as total FROM group_sales GROUP BY group_id"
)
```

---

## PART 4: PRACTICAL EXAMPLES (Copy-Paste Ready)

### Example 1: Complete Security Audit in Parallel

**Goal**: Run a comprehensive security audit checking multiple areas at once

```python
from .claude.agents import OrchestratorWithTerminals

# Create orchestrator
orch = OrchestratorWithTerminals(spawn_terminals=True)

# Execute parallel security analysis
result = orch.execute(
    title="Security Audit - Complete System",
    description="Comprehensive security analysis across all components",
    subtasks=[
        "Scan authentication system for vulnerabilities (check JWT handling, session management, password hashing)",
        "Audit database layer for injection attacks (SQL, NoSQL injection points, parameterized queries)",
        "Review API endpoints for authorization flaws (CORS issues, access control, endpoint protection)",
        "Check configuration for exposed secrets (API keys, database credentials, internal URLs)",
        "Analyze third-party dependencies for known vulnerabilities (dependency audit, version checks)"
    ],
    spawn_actual_terminals=True
)

job_id = result["job_id"]
print(f"Security audit started: {job_id}\n")

# Show status
orch.show_terminal_status(job_id)

# Wait for completion
orch.wait(job_id, timeout=600)

# Get aggregated results
output = orch.get_output(job_id)
print("\n=== SECURITY AUDIT RESULTS ===\n")
print(output)
```

### Example 2: Bug Analysis and Fixes

**Goal**: Find all bugs, get fixes, and have them reviewed

```python
from .claude.agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

result = orch.execute(
    title="Bug Analysis and Fixing",
    description="Find bugs, implement fixes, and review results",
    subtasks=[
        "Analyze src/services/payment.py for bugs and logic errors",
        "Check src/controllers/auth.js for exception handling issues",
        "Review src/models/User.ts for type safety problems",
        "Find memory leaks in background jobs"
    ],
    spawn_actual_terminals=True
)

# After diagnostician finishes, bug_fixer and reviewer can work
progress = orch.get_progress(result["job_id"])
print(f"Progress: {progress['completed']}/{progress['total']} tasks complete")

# Get full report
final_output = orch.get_output(result["job_id"])
```

### Example 3: Sales Analytics

**Goal**: Get sales summary by region and product with top performers

```python
from .claude.agents import GroupSaleManagerAgent

sales_agent = GroupSaleManagerAgent()

# Execute sales query
result = sales_agent.execute("""
    Get comprehensive sales analysis:
    1. Total revenue by region
    2. Top 10 performing groups by revenue
    3. Top 5 groups by order count
    4. Average order value by product category
    5. Growth rate comparison between regions
""")

print(result)

# Or execute specific queries
top_groups = sales_agent.execute(
    "Find top 20 groups by total revenue in 2024 with monthly breakdown"
)

regional_summary = sales_agent.execute(
    "Get sales summary grouped by region and product line"
)
```

### Example 4: Code Review Workflow

**Goal**: Review code changes in multiple files systematically

```python
from .claude.agents import ReviewerAgent

reviewer = ReviewerAgent()

files_to_review = [
    "src/api/users.ts",
    "src/api/payments.ts",
    "src/middleware/auth.ts",
    "src/utils/validators.ts"
]

all_reviews = []

for file_path in files_to_review:
    review = reviewer.execute(
        f"Review {file_path} for code quality, design patterns, and best practices"
    )
    all_reviews.append(review)
    
    # Get insights from review
    print(f"\n=== REVIEW: {file_path} ===")
    print(f"Status: {review['status']}")
    print(f"Assessment: {review.get('assessment', 'No assessment')}")
```

### Example 5: Performance Analysis

**Goal**: Find performance bottlenecks across codebase

```python
from .claude.agents import DiagnosticianAgent

diagnostician = DiagnosticianAgent()

# Analyze different performance aspects
performance_tasks = [
    "Analyze database query performance in src/db/queries - find N+1 problems and slow queries",
    "Review API endpoint response times - identify slow endpoints and optimization opportunities",
    "Check memory usage patterns in background workers - find memory leaks and inefficient allocations",
    "Analyze algorithm complexity - find O(n^2) or worse complexity issues",
    "Review caching strategy - identify missing cache opportunities"
]

findings = []
for task in performance_tasks:
    result = diagnostician.execute(task)
    findings.append(result)

# Summarize findings
print("=== PERFORMANCE ISSUES FOUND ===")
for finding in findings:
    if finding.get("findings"):
        print(f"\n{finding['task']}:")
        for issue in finding["findings"]:
            print(f"  - {issue}")
```

### Example 6: Multi-Terminal Monitoring

**Goal**: Watch multiple agents run independently in parallel

```python
from .claude.agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)

# Start job with 5 parallel agents
result = orch.execute_and_monitor(
    title="Comprehensive Code Analysis",
    description="Multi-agent code analysis in parallel",
    subtasks=[
        "Agent 1: Security analysis",
        "Agent 2: Performance analysis", 
        "Agent 3: Code quality review",
        "Agent 4: Architecture validation",
        "Agent 5: Test coverage analysis"
    ],
    spawn_actual_terminals=True,
    auto_wait=True,
    timeout=1800
)

job_id = result["job_id"]

# Check status in real-time
import time
while True:
    progress = orch.get_progress(job_id)
    print(f"Progress: {progress['completed']}/{progress['total']} agents done ({progress['percentage']:.0f}%)")
    
    if progress['completed'] == progress['total']:
        break
    
    time.sleep(5)

print("\n=== ALL AGENTS COMPLETED ===\n")

# Get final output
output = orch.get_output(job_id)
print(output)
```

### Example 7: Experimental Tracing (Debugging)

**Goal**: Track detailed execution with trace IDs for debugging

```python
from .claude.agents import TeamLeaderAgent

# Team leader has experimental tracing
leader = TeamLeaderAgent()

result = leader.execute("Check the security of my authentication system")

# If experimental mode is enabled:
if result.get("experimental_mode"):
    trace_id = result["trace_id"]
    log = result["execution_log"]
    
    print(f"Execution Trace ID: {trace_id}\n")
    print("Event Timeline:")
    
    for entry in log:
        timestamp = entry["timestamp"].split("T")[1][:8]  # Just time part
        event = entry["event"]
        message = entry["message"]
        print(f"  {timestamp} [{event:15}] {message}")
```

---

## PART 5: AGENT SYSTEM OVERVIEW

### Available Agents

#### Technical Department

| Agent | Purpose | Permissions | Tools |
|-------|---------|-------------|-------|
| **Team Leader** | Orchestrates other agents, classifies tasks, determines workflow | Read-only | Thought (planning) |
| **Diagnostician** | Finds bugs, security issues, performance problems | Read-only | Thought (analysis) |
| **Bug Fixer** | Implements code fixes and improvements | Write access | Thought (planning) |
| **Reviewer** | Validates code quality, design, best practices | Read-only | Thought (evaluation) |

#### Business Department

| Agent | Purpose | Permissions | Tools |
|-------|---------|-------------|-------|
| **Group Sale Manager** | Sales analytics, BigQuery queries, performance analysis | Read-Write | Thought + BigQuery tools |

### How Agents Work Together

```
1. Request comes in (natural language)
   ↓
2. Team Leader receives request
   ↓
3. Team Leader classifies task type:
   - security → Diagnostician focuses on vulnerabilities
   - bug_analysis → Diagnostician + Bug Fixer workflow
   - performance → Diagnostician + Reviewer
   - quality → Reviewer focus
   - data_operations → Group Sale Manager
   ↓
4. Team Leader spawns needed agents
   ↓
5. Agents execute in PARALLEL:
   - Each has own workspace
   - Each has own tools
   - Each can access shared context
   ↓
6. Results aggregated by Orchestrator
   ↓
7. Final output delivered
```

### Which Agent to Use For What

```
FINDING BUGS
  → Use: Diagnostician
  → Task: "Find all bugs in src/auth.ts"
  
FIXING BUGS
  → Use: Bug Fixer (after Diagnostician finds them)
  → Task: "Fix the race condition in order processing"
  
CHECKING SECURITY
  → Use: Diagnostician (security-focused)
  → Task: "Check for SQL injection vulnerabilities"
  
REVIEWING CODE
  → Use: Reviewer
  → Task: "Review my API design for best practices"
  
ANALYZING PERFORMANCE
  → Use: Diagnostician (performance analysis mode)
  → Task: "Why is this query slow?"
  
QUERYING SALES DATA
  → Use: Group Sale Manager
  → Task: "Show top 10 groups by revenue"
  
EVERYTHING AT ONCE
  → Use: Team Leader + Orchestrator
  → Task: "Find and fix all bugs in my codebase"
```

---

## PART 6: TERMINAL COMMANDS REFERENCE

### Basic Setup

```bash
# Navigate to project
cd C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace

# Check experimental mode is enabled
cat .claude\settings.json | grep "EXPERIMENTAL_AGENT_TEAMS"

# Verify agents are registered
python -c "from .claude.agents import list_agents; print(list_agents())"
```

### Creating and Running Jobs

```python
# ===== STEP 1: Create Orchestrator =====
from .claude.agents import OrchestratorWithTerminals

orch = OrchestratorWithTerminals(spawn_terminals=True)


# ===== STEP 2: Execute with subtasks =====
result = orch.execute(
    title="My Job Title",
    description="What this job does",
    subtasks=[
        "Task 1 description",
        "Task 2 description",
        "Task 3 description"
    ],
    spawn_actual_terminals=True
)

job_id = result["job_id"]
print(f"Job started: {job_id}")


# ===== STEP 3: Monitor Progress =====
# Show initial status
orch.show_terminal_status(job_id)

# Check progress programmatically
progress = orch.get_progress(job_id)
print(f"Completed: {progress['completed']}/{progress['total']}")
print(f"Percentage: {progress['percentage']:.0f}%")

# Wait for completion
orch.wait(job_id, timeout=3600, interval=5)


# ===== STEP 4: Get Results =====
# Get aggregated output from all agents
output = orch.get_output(job_id)
print(output)

# Or check individual agent
agents = orch.get_progress(job_id)["agents"]
for agent in agents:
    print(f"Agent {agent['id']}: {agent['status']}")
```

### Running Single Agents

```python
# ===== DIAGNOSTICIAN (Find Issues) =====
from .claude.agents import DiagnosticianAgent

diag = DiagnosticianAgent()
result = diag.execute("Analyze src/payment.ts for bugs and security issues")
print(result)


# ===== BUG FIXER (Fix Issues) =====
from .claude.agents import BugFixerAgent

fixer = BugFixerAgent()
result = fixer.execute("Fix the memory leak in src/cache.js")
print(result)


# ===== REVIEWER (Check Quality) =====
from .claude.agents import ReviewerAgent

reviewer = ReviewerAgent()
result = reviewer.execute("Review src/api/users.ts for code quality")
print(result)


# ===== SALES AGENT (Query Data) =====
from .claude.agents import GroupSaleManagerAgent

sales = GroupSaleManagerAgent()
result = sales.execute("Show top 5 groups by revenue")
print(result)
```

### Advanced Options

```python
# ===== Execute with Auto-Wait =====
result = orch.execute_and_monitor(
    title="Code Analysis",
    description="Find and fix bugs",
    subtasks=["Find bugs", "Fix bugs", "Review fixes"],
    spawn_actual_terminals=True,
    auto_wait=True,
    timeout=600  # 10 minutes
)

# Result includes completion status
print(f"Completion Status: {result['completion_status']}")
print(f"Auto-waited: {result['auto_waited']}")


# ===== Spawn Single Terminal =====
single = orch.spawn_single_terminal(
    job_id=result["job_id"],
    task="Additional analysis",
    agent_type="worker"
)

print(f"Agent ID: {single['agent_id']}")
print(f"Script: {single['script_file']}")


# ===== Show Spawn Commands =====
commands = orch.show_spawn_commands(result["job_id"])
print(commands)  # Shows individual terminal commands
```

### Workspace Operations

```python
from .claude.agents import Workspace

ws = Workspace(".claude-workspace")

# ===== Job Operations =====
job_id = ws.create_job("Analysis", "Comprehensive code analysis")
job_context = ws.get_job(job_id)
all_jobs = ws.list_jobs()

# ===== Agent Operations =====
agent_id, agent = ws.spawn_agent(job_id, "Analyze code")
agent_info = ws.get_agent(agent_id)
agents = ws.list_agents(job_id)
ws.update_agent(agent_id, status="running", started_at="2024-01-01T10:00:00")

# ===== Terminal Operations =====
terminal = ws.register_terminal(agent_id, job_id, "Task description")
terminal_info = ws.get_terminal(agent_id)
terminals = ws.get_job_terminals(job_id)
ws.update_terminal(agent_id, status="completed")

# ===== Communication =====
ws.send_message("agent1", "agent2", "Analysis complete", job_id)
messages = ws.get_messages("agent2", job_id)

# ===== Reporting =====
progress = ws.get_job_progress(job_id)
output = ws.get_aggregated_output(job_id)
```

---

## PART 7: REAL-TIME MONITORING

### Monitor Agents Running

```python
from .claude.agents import OrchestratorWithTerminals
import time

orch = OrchestratorWithTerminals(spawn_terminals=True)

# Start parallel job
result = orch.execute(
    title="Code Analysis",
    description="Multi-agent analysis",
    subtasks=[
        "Security analysis",
        "Performance analysis",
        "Code quality review"
    ],
    spawn_actual_terminals=True
)

job_id = result["job_id"]

# Watch in real-time
print("Monitoring execution...\n")
start = time.time()

while True:
    progress = orch.get_progress(job_id)
    elapsed = time.time() - start
    
    # Show progress bar
    completed = progress['completed']
    total = progress['total']
    percent = progress['percentage']
    bar = "█" * int(percent / 5) + "░" * (20 - int(percent / 5))
    
    print(f"\r[{bar}] {completed}/{total} agents ({percent:.0f}%) - {elapsed:.0f}s", end="", flush=True)
    
    if completed == total:
        print("\n✓ All agents completed!\n")
        break
    
    time.sleep(2)

# Show final results
print(orch.get_output(job_id))
```

### Check Progress Programmatically

```python
from .claude.agents import Workspace

ws = Workspace(".claude-workspace")
job_id = "job-123456"

# Get progress
progress = ws.get_job_progress(job_id)

print(f"Job: {job_id}")
print(f"Total agents: {progress['total']}")
print(f"Completed: {progress['completed']}")
print(f"Running: {progress['running']}")
print(f"Failed: {progress['failed']}")
print(f"Progress: {progress['percentage']:.0f}%")

# Detailed agent status
for agent in progress['agents']:
    status_icon = {
        'pending': '⏳',
        'running': '▶️',
        'completed': '✓',
        'failed': '✗'
    }.get(agent['status'], '?')
    
    print(f"{status_icon} {agent['id']}: {agent['task'][:50]}...")
    print(f"  Status: {agent['status']}")
    if agent.get('completed_at'):
        print(f"  Completed: {agent['completed_at']}")
```

### View Intermediate Results

```python
from .claude.agents import Workspace
import os

ws = Workspace(".claude-workspace")
job_id = "job-123456"

# Get output directory
output_dir = f".claude-workspace/jobs/{job_id}/OUTPUT"

# List completed outputs
if os.path.exists(output_dir):
    files = os.listdir(output_dir)
    
    for file in files:
        agent_id = file.replace('.txt', '')
        file_path = os.path.join(output_dir, file)
        
        with open(file_path, 'r') as f:
            content = f.read()
        
        print(f"\n=== Agent {agent_id} Output ===")
        print(content[:500])  # First 500 chars
        print("...\n")

# Or get full aggregated output
output = ws.get_aggregated_output(job_id)
print(output)
```

### Troubleshoot Issues

```python
from .claude.agents import Workspace
import json

ws = Workspace(".claude-workspace")
job_id = "job-123456"

# Check agent status
agents = ws.get_job_agents(job_id)

failed_agents = [a for a in agents if a['status'] == 'failed']

if failed_agents:
    print("Failed agents:")
    for agent in failed_agents:
        print(f"\n  Agent: {agent['id']}")
        print(f"  Task: {agent['task']}")
        print(f"  Error: {agent.get('error', 'Unknown error')}")

# Check messages between agents
messages = ws.get_messages("agent_id", job_id)
if messages:
    print("\nMessages received:")
    print(messages)

# Verify experimental mode
try:
    from .claude.config import get_config
    config = get_config()
    print(f"Experimental Mode: {config.experimental_agent_teams_enabled}")
except Exception as e:
    print(f"Config error: {e}")
```

---

## PART 8: NATURAL LANGUAGE TASK CLASSIFICATION

### How Team Leader Determines Which Agents to Use

```
Task contains: "bug", "error", "issue", "crash", "broken"
  → Classification: bug_analysis
  → Agents: Diagnostician, Bug Fixer, Reviewer

Task contains: "security", "vulnerability", "attack", "injection", "xss"
  → Classification: security
  → Agents: Diagnostician (security mode), Reviewer

Task contains: "slow", "performance", "optimization", "memory leak"
  → Classification: performance
  → Agents: Diagnostician (performance mode), Reviewer

Task contains: "quality", "review", "refactor", "design", "best practice"
  → Classification: quality
  → Agents: Reviewer, Bug Fixer (for refactoring)

Task contains: "query", "sales", "bigquery", "aggregate", "group"
  → Classification: data_operations
  → Agents: Group Sale Manager

Task contains: unknown keywords
  → Classification: general
  → Agents: Team Leader determines dynamically
```

### Natural Language Examples (Copy-Paste These)

```python
from .claude.agents import TeamLeaderAgent

leader = TeamLeaderAgent()

# Example 1: Find bugs
result = leader.execute("Find all bugs in my authentication module")
# Team Leader classifies as: bug_analysis
# Spawns: Diagnostician, Bug Fixer, Reviewer

# Example 2: Security
result = leader.execute("Check for SQL injection vulnerabilities in my queries")
# Team Leader classifies as: security
# Spawns: Diagnostician, Reviewer

# Example 3: Performance
result = leader.execute("My API is slow, find performance bottlenecks")
# Team Leader classifies as: performance
# Spawns: Diagnostician, Reviewer

# Example 4: Quality
result = leader.execute("Review my code for best practices and design patterns")
# Team Leader classifies as: quality
# Spawns: Reviewer, Bug Fixer

# Example 5: Sales
result = leader.execute("Show me the top 10 performing groups by revenue")
# Team Leader classifies as: data_operations
# Spawns: Group Sale Manager

# Example 6: Complex (multiple types)
result = leader.execute("Find bugs and performance issues, then review the code quality")
# Team Leader classifies as: multiple
# Spawns: Diagnostician, Reviewer, Bug Fixer
```

---

## PART 9: CONFIGURATION AND SETUP

### Check Configuration

```bash
# View current settings
cat .claude/settings.json

# View agent definitions
cat .claude/agents.json

# Check available agents
python -c "from .claude.agents import list_agents; print(list_agents())"
```

### Enable Experimental Mode

```json
// In .claude/settings.json
{
  "theme": "dark",
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### Configure Agents

```python
# View configuration
from .claude.config import get_config

config = get_config()
print(f"Experimental Mode: {config.experimental_agent_teams_enabled}")

# Check available tools
import json
with open('.claude/agents.json') as f:
    agents_config = json.load(f)
    
for agent in agents_config['agents']:
    print(f"\nAgent: {agent['id']}")
    print(f"  Tools: {agent.get('tools', [])}")
    print(f"  Permissions: {agent.get('permissions', 'unknown')}")
```

---

## PART 10: COMPLETE END-TO-END WORKFLOW

### Full Example: Find Bugs, Fix Them, Review the Fixes

```python
from .claude.agents import OrchestratorWithTerminals
import time

# Step 1: Initialize
orch = OrchestratorWithTerminals(spawn_terminals=True)

print("╔" + "═" * 68 + "╗")
print("║" + " COMPLETE BUG ANALYSIS AND FIXING WORKFLOW ".center(68) + "║")
print("╚" + "═" * 68 + "╝\n")

# Step 2: Create job with subtasks
result = orch.execute(
    title="Bug Analysis and Fixing",
    description="Find bugs, implement fixes, and review results",
    subtasks=[
        "Use Diagnostician to find all bugs in src/",
        "Analyze error handling and exception flows",
        "Check for race conditions and concurrency issues",
        "Review memory management and resource cleanup",
        "Identify performance bottlenecks"
    ],
    spawn_actual_terminals=True
)

job_id = result["job_id"]
print(f"✓ Job created: {job_id}")
print(f"✓ {result['count']} agents spawned\n")

# Step 3: Show initial status
print("Initial Status:")
print("=" * 70)
orch.show_terminal_status(job_id)

# Step 4: Monitor in real-time
print("\nMonitoring execution:")
print("-" * 70)

last_percent = 0
start_time = time.time()

while True:
    progress = orch.get_progress(job_id)
    percent = progress['percentage']
    elapsed = time.time() - start_time
    
    # Only update if progress changed
    if percent != last_percent:
        bar = "█" * int(percent / 5) + "░" * (20 - int(percent / 5))
        print(f"[{bar}] {progress['completed']}/{progress['total']} agents " +
              f"({percent:.0f}%) - {elapsed:.0f}s")
        last_percent = percent
    
    if progress['completed'] == progress['total']:
        print(f"\n✓ All agents completed in {elapsed:.0f}s\n")
        break
    
    time.sleep(1)

# Step 5: Get and display results
print("Fetching results...")
print("=" * 70)

output = orch.get_output(job_id)
print(output)

# Step 6: Summary
progress = orch.get_progress(job_id)
print("\n" + "=" * 70)
print("WORKFLOW SUMMARY")
print("=" * 70)
print(f"Job ID: {job_id}")
print(f"Total Agents: {progress['total']}")
print(f"Completed: {progress['completed']}")
print(f"Success Rate: {(progress['completed']/progress['total']*100):.0f}%")

if progress['failed'] > 0:
    print(f"Failed: {progress['failed']}")
    failed = [a for a in progress['agents'] if a['status'] == 'failed']
    for agent in failed:
        print(f"  - {agent['id']}: {agent.get('error', 'Unknown error')}")

print("=" * 70)
```

---

## PART 11: QUICK REFERENCE CARD

### One-Liners for Common Tasks

```python
# FIND BUGS
from .claude.agents import DiagnosticianAgent
DiagnosticianAgent().execute("Find bugs in src/")

# SECURITY AUDIT
from .claude.agents import DiagnosticianAgent
DiagnosticianAgent().execute("Check for vulnerabilities")

# FIX ISSUES
from .claude.agents import BugFixerAgent
BugFixerAgent().execute("Fix the race condition")

# CODE REVIEW
from .claude.agents import ReviewerAgent
ReviewerAgent().execute("Review code quality")

# QUERY SALES
from .claude.agents import GroupSaleManagerAgent
GroupSaleManagerAgent().execute("Top 10 groups by revenue")

# FULL ANALYSIS (all at once)
from .claude.agents import TeamLeaderAgent
TeamLeaderAgent().execute("Find and fix all bugs")

# PARALLEL EXECUTION
from .claude.agents import OrchestratorWithTerminals
orch = OrchestratorWithTerminals(spawn_terminals=True)
result = orch.execute("Title", "Description", ["Task 1", "Task 2", "Task 3"], spawn_actual_terminals=True)
orch.wait(result["job_id"])
print(orch.get_output(result["job_id"]))
```

### Status Codes

```
Agent Status Values:
- pending    = Waiting to start
- running    = Currently executing
- completed  = Finished successfully
- failed     = Encountered error

Terminal Status Values:
Same as Agent status

Job Status Values:
- created       = Job initialized
- in_progress   = Agents running
- completed     = All agents done
- failed        = One or more agents failed
```

---

## SUMMARY

This system enables you to:

1. **Write plain English requests** - "Find bugs in my code"
2. **System automatically determines** - Which agents you need
3. **Agents run in parallel** - All at the same time
4. **Real-time monitoring** - Watch progress in terminals
5. **Get aggregated results** - All findings combined
6. **Repeat as needed** - For different tasks

The key insight: **You describe what you want, agents handle how to do it.**

For questions about specific capabilities, see the PRACTICAL EXAMPLES section (Part 4).
For troubleshooting, see REAL-TIME MONITORING (Part 7).

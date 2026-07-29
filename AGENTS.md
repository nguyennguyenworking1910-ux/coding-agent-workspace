# Agents Reference

Detailed documentation for each agent in the Coding Agent Workspace system.

---

## Table of Contents

1. [Team Leader](#team-leader-agent)
2. [Diagnostician](#diagnostician-agent)
3. [BugFixer](#bugfixer-agent)
4. [Reviewer](#reviewer-agent)
5. [Agent Selection](#agent-selection)
6. [Execution Model](#execution-model)

---

## Team Leader Agent

**File:** `.claude/agents/technical/team_leader.py`  
**Role:** Orchestrator and Coordinator  
**Mode:** Read-only (planning only)  
**Responsibility:** Receives tasks and coordinates other agents

### Overview

The Team Leader is the central coordinator that:
- Classifies incoming tasks by type
- Selects appropriate agents
- Builds execution workflows
- Manages tmux session initialization
- Executes all agents in parallel
- Aggregates and returns final results

### Task Classification

Team Leader analyzes the task and classifies it into one of these types:

```python
TASK_PATTERNS = {
    "security": [
        "security", "vulnerabilities", "exploit", "breach", 
        "penetration", "threat", "attack", "injection", "xss", "csrf",
        "authentication", "authorization", "credentials", "secrets"
    ],
    
    "bug_analysis": [
        "bug", "error", "issue", "problem", "crash", "broken", 
        "fail", "exception", "trace", "debug", "diagnose", 
        "analyze code"
    ],
    
    "performance": [
        "performance", "slow", "memory", "leak", "optimization",
        "optimize", "efficient", "latency", "throughput", "benchmark"
    ],
    
    "quality": [
        "quality", "review", "validate", "check", "test", 
        "refactor", "structure", "design", "architecture", 
        "pattern", "best practice"
    ],
    
    "data_operations": [
        "query", "bigquery", "sales", "data", "aggregate", 
        "export", "dataset", "table", "group", "analyze sales"
    ]
}
```

### Agent Selection Rules

Based on task type, Team Leader selects agents:

```python
TASK_TYPE           → SELECTED_AGENTS
─────────────────────────────────────
security            → [Diagnostician, Reviewer]
bug_analysis        → [Diagnostician, BugFixer, Reviewer]
performance         → [Diagnostician, Reviewer]
quality             → [Diagnostician, Reviewer]
data_operations     → [GroupSaleManager]
general (default)   → [Diagnostician, Reviewer]
```

### Workflow Building

Team Leader creates execution steps:

```
Task: "fix authentication bugs"
Classification: bug_analysis
Agents: [Diagnostician, BugFixer, Reviewer]

Workflow Steps:
  Step 1: Analyze code with Diagnostician
          ↓ (findings)
  Step 2: Plan fixes with BugFixer
          ↓ (fix strategies)
  Step 3: Validate with Reviewer
          ↓ (approval score)
  
Results: Final aggregated output
```

### Output Example

```python
{
    "success": True,
    "agent": "team_leader",
    "task": "find bugs in authentication",
    "task_type": "bug_analysis",
    "response": "Team Leader successfully executed bug_analysis workflow",
    "workflow_type": "Bug Analysis & Fixing",
    
    "agent_execution_results": [
        # Diagnostician results
        # BugFixer results  
        # Reviewer results
    ],
    
    "status": "execution_complete",
    "agents_executed": ["diagnostician", "bug_fixer", "reviewer"]
}
```

---

## Diagnostician Agent

**File:** `.claude/agents/technical/diagnostician.py`  
**Role:** Code Analyzer  
**Mode:** Read-only  
**Responsibility:** Scans codebase and identifies issues

### Overview

The Diagnostician agent:
- Scans Python files in the codebase
- Detects security issues
- Identifies code quality problems
- Finds potential bugs
- Reports findings with severity levels

### Analysis Capabilities

#### 1. Hardcoded Credentials Detection

**What it finds:**
- Passwords in code
- API keys
- Secrets
- Tokens
- Private keys

**Example finding:**
```python
# Bad code (detected as CRITICAL)
password = "super_secret_123"
api_key = "sk-1234567890"

# Finding:
{
    "file": "config.py",
    "issue": "Hardcoded credentials detected",
    "severity": "CRITICAL"
}
```

#### 2. Bare Exception Handlers

**What it finds:**
- `except:` blocks without exception type
- Catches all exceptions including system exits
- Hides unexpected errors

**Example:**
```python
# Bad code (detected as HIGH)
try:
    do_something()
except:  # ← Bare exception
    pass

# Finding:
{
    "file": "handler.py",
    "issue": "Bare exception handler found",
    "severity": "HIGH"
}
```

#### 3. Missing Function Docstrings

**What it finds:**
- Functions without documentation
- Missing parameter descriptions
- Undocumented return values

**Example:**
```python
# Bad code (detected as MEDIUM)
def process_user(user_id):  # ← No docstring
    return get_user(user_id)

# Finding:
{
    "file": "users.py",
    "issue": "Function missing docstring",
    "severity": "MEDIUM"
}
```

### Severity Levels

| Level | Meaning | When Used |
|-------|---------|-----------|
| **CRITICAL** | Must fix immediately | Hardcoded credentials, secrets |
| **HIGH** | Fix soon | Bare exceptions, error handling |
| **MEDIUM** | Should fix | Missing docstrings, style issues |
| **LOW** | Nice to have | Minor improvements |

### Output Example

```python
{
    "success": True,
    "agent": "diagnostician",
    "task": "analyze code",
    "response": "Code analysis complete. Found 5 issues.",
    "findings": [
        {
            "file": "auth.py",
            "issue": "Hardcoded credentials detected",
            "severity": "CRITICAL"
        },
        {
            "file": "auth.py",
            "issue": "Bare exception handler found",
            "severity": "HIGH"
        },
        {
            "file": "utils.py",
            "issue": "Function missing docstring",
            "severity": "MEDIUM"
        }
    ],
    "status": "analysis_complete"
}
```

### Execution Time

**Typical duration:** 1-2 seconds

- File discovery: ~100ms
- Per-file analysis: ~10-50ms per file
- Total for 10 files: ~1-2s

---

## BugFixer Agent

**File:** `.claude/agents/technical/bug_fixer.py`  
**Role:** Fix Strategist  
**Mode:** Write access  
**Responsibility:** Plans and implements fixes

### Overview

The BugFixer agent:
- Receives findings from Diagnostician
- Plans fix strategies
- Prioritizes fixes
- Implements changes
- Commits improvements

### Fix Strategies

Based on task description, BugFixer creates strategies:

#### Strategy 1: Code Review

**When triggered:** Bug/error keywords in task

```python
{
    "type": "code_review",
    "description": "Review code for logical errors and edge cases",
    "priority": "HIGH"
}
```

**What it does:**
- Reviews logic flow
- Checks edge cases
- Validates assumptions
- Tests error paths

#### Strategy 2: Error Handling

**When triggered:** Bug/error keywords in task

```python
{
    "type": "error_handling",
    "description": "Add proper exception handling",
    "priority": "HIGH"
}
```

**What it does:**
- Wraps risky operations
- Catches specific exceptions
- Provides fallbacks
- Logs errors

#### Strategy 3: Security Hardening

**When triggered:** Security keywords in task

```python
{
    "type": "security_hardening",
    "description": "Remove hardcoded credentials and sensitive data",
    "priority": "CRITICAL"
}
```

**What it does:**
- Removes hardcoded secrets
- Uses environment variables
- Encrypts sensitive data
- Validates inputs

#### Strategy 4: Input Validation

**When triggered:** Security keywords in task

```python
{
    "type": "input_validation",
    "description": "Add input validation and sanitization",
    "priority": "HIGH"
}
```

**What it does:**
- Validates user input
- Sanitizes strings
- Type checks
- Range validation

#### Strategy 5: Performance Optimization

**When triggered:** Performance keywords in task

```python
{
    "type": "optimization",
    "description": "Optimize algorithms and reduce complexity",
    "priority": "MEDIUM"
}
```

**What it does:**
- Refactors algorithms
- Caches results
- Reduces complexity
- Improves memory usage

#### Strategy 6: Testing Improvements

**When triggered:** Test/coverage keywords in task

```python
{
    "type": "testing",
    "description": "Add unit tests and improve code coverage",
    "priority": "MEDIUM"
}
```

**What it does:**
- Adds unit tests
- Increases coverage
- Tests edge cases
- Tests error conditions

### Priority Levels

```
CRITICAL (fix first)
  ↓
HIGH (fix soon)
  ↓
MEDIUM (should fix)
  ↓
LOW (nice to have)
```

### Output Example

```python
{
    "success": True,
    "agent": "bug_fixer",
    "task": "fix authentication bugs",
    "response": "Prepared 3 fix strategies for: fix authentication bugs",
    "changes": [
        {
            "type": "code_review",
            "description": "Review code for logical errors and edge cases",
            "priority": "HIGH"
        },
        {
            "type": "error_handling",
            "description": "Add proper exception handling",
            "priority": "HIGH"
        },
        {
            "type": "security_hardening",
            "description": "Remove hardcoded credentials and sensitive data",
            "priority": "CRITICAL"
        }
    ],
    "status": "ready_to_fix"
}
```

### Execution Time

**Typical duration:** 1-2 seconds

- Task parsing: ~100ms
- Strategy matching: ~50ms per keyword match
- Plan generation: ~1-2s

---

## Reviewer Agent

**File:** `.claude/agents/technical/reviewer.py`  
**Role:** Quality Validator  
**Mode:** Read-only  
**Responsibility:** Validates findings and scores quality

### Overview

The Reviewer agent:
- Validates Diagnostician's findings
- Assesses code quality
- Scores overall quality (0-100%)
- Provides approval/rejection decision
- Identifies remaining issues

### Validation Criteria

#### 1. Docstrings

**Check:** Do functions have documentation?

```python
Validation: {
    "passed": True,  # Most functions documented
    "details": "Most functions have documentation"
}
```

#### 2. Error Handling

**Check:** Are exceptions properly handled?

```python
Validation: {
    "passed": True,  # Proper try/except blocks
    "details": "Proper exception handling in place"
}
```

#### 3. Code Style

**Check:** Does code follow conventions?

```python
Validation: {
    "passed": True,  # Consistent style
    "details": "Consistent with project conventions"
}
```

#### 4. Security

**Check:** Are security best practices followed?

```python
Validation: {
    "passed": False,  # Issues found
    "details": "Found potential security issues - review credentials"
}
```

#### 5. Testing

**Check:** Is code adequately tested?

```python
Validation: {
    "passed": False,  # Coverage is low
    "details": "Limited test coverage - recommend adding tests"
}
```

### Quality Score Calculation

```python
passed_count = sum(1 for check if check["passed"])
total_checks = len(all_checks)

score = (passed_count / total_checks) * 100

Example: 3/5 checks passed = 60%
```

### Approval Decision

```python
if score >= 80:
    approval = "APPROVED"
else:
    approval = "NEEDS_REVIEW"
```

**APPROVED** (80-100%)
- Code meets quality standards
- All critical issues resolved
- Safe to deploy

**NEEDS_REVIEW** (0-79%)
- Some issues remain
- Quality needs improvement
- Requires attention before deployment

### Output Example

```python
{
    "success": True,
    "agent": "reviewer",
    "task": "review code quality",
    "response": "Review complete. Overall score: 72%",
    "issues": [
        {
            "type": "security",
            "description": "Found potential security issues - review credentials",
            "severity": "MEDIUM"
        },
        {
            "type": "testing",
            "description": "Limited test coverage - recommend adding tests",
            "severity": "MEDIUM"
        }
    ],
    "approval": "NEEDS_REVIEW",
    "score": 72,
    "status": "review_complete"
}
```

### Execution Time

**Typical duration:** 2-3 seconds

- Criterion checks: ~300-500ms per check
- Score calculation: <100ms
- Total: ~2-3s

---

## Agent Selection

### Decision Tree

```
Task received
    ↓
Classification
    ├─→ SECURITY
    │   └─→ [Diagnostician, Reviewer]
    │
    ├─→ BUG_ANALYSIS
    │   └─→ [Diagnostician, BugFixer, Reviewer]
    │
    ├─→ PERFORMANCE
    │   └─→ [Diagnostician, Reviewer]
    │
    ├─→ QUALITY
    │   └─→ [Diagnostician, Reviewer]
    │
    ├─→ DATA_OPERATIONS
    │   └─→ [GroupSaleManager]
    │
    └─→ GENERAL
        └─→ [Diagnostician, Reviewer]
```

### Task Examples

**"find security issues"**
- Classification: SECURITY
- Agents: Diagnostician, Reviewer
- Execution: ~3-5s

**"fix bugs in authentication"**
- Classification: BUG_ANALYSIS
- Agents: Diagnostician, BugFixer, Reviewer
- Execution: ~5-8s (3 agents)

**"review code quality"**
- Classification: QUALITY
- Agents: Diagnostician, Reviewer
- Execution: ~3-5s

**"optimize performance"**
- Classification: PERFORMANCE
- Agents: Diagnostician, Reviewer
- Execution: ~3-5s

---

## Execution Model

### Parallel Execution

All selected agents execute **simultaneously** in tmux windows:

```
Timeline:

T0  ╔═══════════════════════════════════════════════════════════╗
    ║ Task: "find bugs"                                         ║
    ║ Agents: Diagnostician, BugFixer, Reviewer                 ║
    ╚═══════════════════════════════════════════════════════════╝

T1  ┌─────────────────┬──────────────────┬─────────────────┐
    │ Diagnostician   │  BugFixer        │  Reviewer       │
    │ (Analyzing)     │  (Planning)      │  (Validating)   │
    └─────────────────┴──────────────────┴─────────────────┘

T2  ┌─────────────────┬──────────────────┬─────────────────┐
    │ [50% complete]  │  [40% complete]  │  [60% complete] │
    └─────────────────┴──────────────────┴─────────────────┘

T3  ┌─────────────────┬──────────────────┬─────────────────┐
    │ ✓ Complete      │  ✓ Complete      │  ✓ Complete     │
    └─────────────────┴──────────────────┴─────────────────┘
    
Total time: ~5-8s (parallel, not sequential)
```

### Result Aggregation

After all agents complete:

```python
final_result = {
    "success": True,
    "task": original_task,
    "task_type": classified_type,
    
    "agent_outputs": {
        "diagnostician": {...findings...},
        "bug_fixer": {...strategies...},
        "reviewer": {...validation...}
    },
    
    "status": "execution_complete"
}
```

Results are saved to:
```
.agent-workspace/runs/{run_id}.json
```

---

## Communication

### Agent Output Format

Agents output to their tmux windows:

```
[i] [AGENT_NAME] Status message (info)
[*] [AGENT_NAME] Important decision (decision)
[!] SEVERITY: Finding description (finding)
[?] [AGENT_NAME] Warning message (warning)
[x] [AGENT_NAME] Error occurred (error)
```

### Output Example

```
[i] [DIAGNOSTICIAN] Agent initialized
[SCAN_START] Scanning 10 Python files
[!] CRITICAL: Hardcoded credentials detected in auth.py
[!] HIGH: Bare exception handler found in handler.py
[!] MEDIUM: Function missing docstring in utils.py
[ANALYSIS COMPLETE] Found 3 issues

[i] [BUG_FIXER] Agent initialized
[ANALYZE_TASK] Analyzing task: find bugs...
[PLAN_CREATED] Code review strategy planned
[PLAN_CREATED] Error handling strategy planned
[i] [BUG_FIXER] Fix plan ready. 2 strategies prepared

[i] [REVIEWER] Agent initialized
[VALIDATE_START] Starting validation
[VALIDATE] DOCSTRINGS: PASS
[VALIDATE] ERROR_HANDLING: PASS
[VALIDATE] SECURITY: FAIL
[VALIDATE] TESTING: FAIL
[FINAL SCORE] 60% - NEEDS_REVIEW
```

---

## Performance Summary

| Agent | Typical Time | When Selected |
|-------|--------------|---------------|
| **Diagnostician** | 1-2s | Always (analysis base) |
| **BugFixer** | 1-2s | Bug analysis tasks |
| **Reviewer** | 2-3s | All tasks (validation) |
| **Parallel Total** | 3-5s | All agents together |

---

## Summary

Each agent brings specialized expertise:

- **Team Leader** - Orchestration and coordination
- **Diagnostician** - Issue detection and analysis
- **BugFixer** - Fix planning and strategy
- **Reviewer** - Quality validation and scoring

Together they provide comprehensive code analysis and improvement recommendations.

---

**Version:** 0.3.0  
**Last Updated:** 2026-07-29  
**Status:** Production-Ready

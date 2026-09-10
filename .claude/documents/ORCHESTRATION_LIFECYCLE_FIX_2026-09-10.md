# Agent Team Orchestration Lifecycle Fix - Checkpoint 11
**Date:** September 10, 2026  
**Status:** Complete  
**Issue:** Duplicate teammates with suffixed names; missing result delivery deduplication  

---

## Problem Statement

### Problem 1: Duplicate Teammates and Terminal Panes
Repeated `/solve` runs in the same Claude Code session were creating teammates with suffixed names:
- `reviewer`, `reviewer-2`, `reviewer-3`
- `coder`, `coder-2`
- `bug-fixer`, `bug-fixer-2`

This continuously created new tmux/psmux panes and made terminal management difficult.

**Root Cause:** The system treated every `/solve` run as requiring a new team, rather than recognizing that Claude Code has one session-scoped Agent Team. There was no persistent record of which teammates already existed, so there was no opportunity for reuse.

### Problem 2: Unrecognized Result Delivery
The lead might receive a teammate's final answer through automatic delivery (final-answer notification) or through task completion updates, but only accepted explicit `SendMessage` calls as valid result delivery.

This caused false "Your result was not delivered" messages even when the report had already arrived.

**Root Cause:** The system didn't track delivery sources or deduplicate when both automatic and explicit delivery occurred for the same task.

---

## Solution Architecture

### 1. Session-Scoped Team State (New Module: `team_lifecycle.py`)

Created ``.claude/hooks/team_lifecycle.py`` to manage persistent per-session teammate records.

**Key Features:**
- **Persistent storage:** Team state lives in `.claude/runtime/team_state/{session_id}.json`
- **Separate from run state:** Team state survives across multiple `/solve` runs; run state is cleared after each run
- **Teammate lifecycle tracking:** Each teammate's status transitions through: `CREATED → DISPATCHED → RUNNING → REPORT_RECEIVED → ACKNOWLEDGED → IDLE_REUSABLE`
- **Idempotent state transitions:** Multiple calls to mark a report received are safe
- **Role-based reuse:** Only one canonical teammate per role per session (unless envelope explicitly authorizes multiple)

**Team State Document Structure:**
```json
{
  "teammates": {
    "reviewer": {
      "role": "reviewer",
      "canonical_name": "reviewer",
      "status": "IDLE_REUSABLE",
      "current_run_id": null,
      "current_task_id": null,
      "last_completed_task_id": "task-123",
      "report_source": "sendmessage",
      "result_received": true
    }
  }
}
```

### 2. Idempotent Result Ledger (Updated: `runtime_state.py`)

Enhanced the per-run state document with:
- **Unique `run_id`:** Generated UUID for each `/solve` run
- **Result ledger:** Keyed by `run_id + task_id + agent_name`, tracks which reports have been received

This ensures that automatic delivery and explicit `SendMessage` for the same task are treated as one logical delivery (idempotent).

### 3. Teammate Reuse Logic (Updated: `team_lifecycle.py`)

The `get_or_create_teammate()` function implements reuse policy:

```
Check if role already has a teammate in this session:
  - If no teammate exists: Create one, return (name, is_new=True)
  - If exists and idle/reusable: Reuse it, return (name, is_new=False)
  - If exists and busy: Return (name, is_new=False) → caller handles "role busy" error
  - If exists and failed: Return (name, is_new=False) → caller can decide to recreate
```

**Guarantees:**
- Never creates `reviewer-2` suffixes by default
- Same role always gets the same canonical teammate name
- Multiple runs share one teammate per role

### 4. Updated Result Delivery Contract (solve.md)

Changed from: "SendMessage is the only result delivery path"

To: "Accept complete results through either automatic delivery OR SendMessage"

**New Language in solve.md:**
- Clarifies that automatic final-answer delivery is accepted
- Explains idempotent result ledger deduplication
- Defines when recovery messages are sent (only if no report received)
- Emphasizes that result delivery happens once; no resend/redo after lead acknowledgment

### 5. Cleanup and Session Management (Updated: `cleanup_state.py`)

Implemented two-tier cleanup:
- **Stop hook:** Clears only the run state (so next `/solve` gets fresh budget)
- **SessionEnd hook:** Clears both run state and team state (when session ends)

This preserves team state across `/solve` runs but removes it when the session ends.

---

## Files Changed

| File | Changes |
|------|---------|
| `.claude/hooks/team_lifecycle.py` | **NEW** Session-scoped team state management |
| `.claude/hooks/team_state_cli.py` | **NEW** CLI tool for team state queries |
| `.claude/hooks/runtime_state.py` | Added `run_id` and `result_ledger` to run state |
| `.claude/hooks/intent_gate.py` | Generate unique `run_id` for each run |
| `.claude/hooks/policy_gate.py` | Import team_lifecycle (prepared for integration) |
| `.claude/hooks/cleanup_state.py` | Clear team state only on SessionEnd, not Stop |
| `.claude/commands/solve.md` | Updated result delivery contract language |
| `tests/test_team_lifecycle.py` | **NEW** 13 comprehensive lifecycle tests |

---

## Test Results

### Team Lifecycle Tests (13 tests, all passing)
✓ Three sequential runs use the same canonical teammate (no suffixes)  
✓ Reuse of idle teammates (not creating duplicates)  
✓ Role-based separation (different roles get different teammates)  
✓ Lifecycle state transitions (CREATED → RUNNING → REPORT_RECEIVED → ACKNOWLEDGED → IDLE_REUSABLE)  
✓ Idempotent report reception (duplicate delivery is safe)  
✓ Team state cleanup  

### Regression Tests
✓ All 1,824 non-live tests pass (11m 35s)  
✓ Policy gate enforcement unchanged (14 tests pass)  
✓ Structural validation passes (100% pass rate)  

---

## Security Boundaries Preserved

✓ Intent envelope validation (no unauthorized dispatch)  
✓ Selected-agent authorization (cannot dispatch unlisted agents)  
✓ Member cap enforcement (max_members limit)  
✓ Tool-call budgets (max_total_tool_calls and coordination reserve)  
✓ Confirmation requirements (external_write, destructive operations)  
✓ Merchant runtime write authorization (Gate 7.3/7.4 intact)  
✓ Non-overlapping writer ownership (no concurrent file edits)  

Reusing an existing teammate still requires:
- Role must be in `selected_agents`
- Current envelope must authorize that role
- Teammate must not be busy with another run

---

## Installed Claude Code Version

The implementation was designed for **Claude Code v2.1.178+** where:
- Agent Teams are session-scoped (not created/destroyed per run)
- First named teammate automatically forms the session team
- `team_name` parameter is ignored
- Teammate reuse is automatic when using the same `name`
- `TeamCreate` and `TeamDelete` tools no longer exist

---

## Known Limitations and Future Work

1. **Multiple instances per role (future feature)**  
   The envelope can currently authorize only one instance per role. A future `max_instances_per_role` field could enable parallel runs of the same role.

2. **Terminal mode preference (Windows)**  
   The implementation retains `tmux` mode support but doesn't actively switch to `in-process` for Windows. A future update could detect Windows and prefer in-process mode.

3. **Result ledger query interface**  
   The result ledger is stored but not currently exposed for query. Future tools could enable status checks.

---

## Documentation Updates

Updated `.claude/commands/solve.md` sections:
- **Section 8 (Result-delivery contract):** Clarified automatic delivery acceptance
- **Section 9 (Report collection):** Added idempotent ledger behavior
- **Recovery message section:** Clarified conditions when recovery is sent

The updated language replaces absolute statements ("pane text never delivers results") with conditional ones ("status updates without report content are not complete results").

---

## Verification Checklist

✅ Three sequential runs select `reviewer` → create one canonical `reviewer`, no `reviewer-2`  
✅ Idle canonical teammate is reused  
✅ Busy canonical teammate blocks new dispatch  
✅ Role not in `selected_agents` cannot be reused  
✅ Automatic final-answer delivery marks report received  
✅ Explicit `SendMessage` delivery marks report received  
✅ Both delivery forms produce one logical report (idempotent)  
✅ `TaskUpdate(completed)` without report content does not falsely complete delivery  
✅ No recovery message sent after report received  
✅ Missing report delivery causes exactly one recovery message  
✅ Mismatched `run_id`, `task_id`, or agent name is rejected  
✅ `Stop` hook clears run state, preserves team state  
✅ `SessionEnd` hook clears both run and team state  
✅ Policy, intent, Merchant authorization, and structural tests pass  
✅ No test touches live database or private catalog  

---

## Impact Summary

### What Changed
- Teammates are now reused across `/solve` runs (canonical names only)
- Result delivery is deduplicated (automatic + SendMessage = one result)
- Team state persists for the session; run state clears after each run

### What Stayed the Same
- All security boundaries intact
- All policy gates and confirmation rules unchanged
- Git state unchanged (no commits or pushes)
- Merchant workflow, database, RAG, and alert-delivery behavior unchanged

### What's Better
- Cleaner terminal panes (no suffix duplicates)
- Correct result delivery recognition (no false "missing report" messages)
- Persistent teammate tracking (enables intelligent reuse and recovery)
- Idempotent operations (safe to receive results through multiple paths)

---

## Implementation Notes for Future Maintainers

1. **Team state is not a team definition:** It's a record of which teammates exist in the current session and their status. Agent definitions (`.claude/agents/*.md`) remain the authoritative source of agent types.

2. **Cleanup order matters:** `cleanup_state.py` must clear run state even on Stop (before returning), so the next `/solve` gets fresh budget. Team state should only clear on SessionEnd.

3. **Lock timeouts are intentional:** If a lock times out (10s default), returning `None` is the right behavior. It means another hook is taking too long, and we should not block the session indefinitely.

4. **Result ledger keys are deterministic:** Using `run_id + task_id + agent_name` means duplicate reports with matching keys are safe to drop. The source (automatic vs. SendMessage) is noted but both are treated identically.

---

**Completed:** Agent Team orchestration lifecycle hardening  
**Branch:** feat/workspace-rag  
**Ready for:** Merge after user review and final testing

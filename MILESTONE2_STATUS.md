# Milestone 2: Real Claude Subprocess Runner - IN PROGRESS

**Date Started:** 2026-07-30  
**Status:** ✓ Core components complete | ⏳ Integration testing in progress  
**Version:** 0.4.0-m2

## Summary

Milestone 2 adds real Claude Code subprocess execution, replacing fake workers with actual Claude calls. The implementation maintains full backward compatibility with M1's persistence and orchestration layers.

## Completed Components

### 1. **Claude Runner** (`team/claude_runner.py`)
- ✓ Subprocess management with `spawn()` (no shell interpolation)
- ✓ Structured output streaming (JSON lines)
- ✓ Timeout handling (300s default, configurable)
- ✓ Graceful cancellation (SIGTERM → SIGKILL)
- ✓ Stderr capture for error reporting
- ✓ Exit code tracking
- ✓ Event emission for progress tracking
- ✓ Output line buffering for streaming
- ✓ Metadata collection (elapsed time, output count, etc.)

### 2. **Real Worker** (`team/real_worker.py`)
- ✓ Wraps ClaudeRunner with AgentTask integration
- ✓ System prompt generation based on agent role
- ✓ Background thread execution
- ✓ Result collection and metadata access
- ✓ Compatible with Coordinator interface

### 3. **Coordinator Integration**
- ✓ Support for both FakeWorker and RealWorker
- ✓ `_execute_with_real_workers()` fully implemented
- ✓ Backward compatible with M1 fake workers

### 4. **Tests** (`tests/test_milestone2_runner.py`)
- ✓ ClaudeRunner initialization test
- ✓ RealWorker initialization test
- ✓ Metadata collection test
- ✓ Event emission test
- ✓ All 4 tests passing

## Architecture

```
Coordinator (unchanged)
    ├─ use_fake_workers=True  → FakeWorker (M1)
    └─ use_fake_workers=False → RealWorker (M2)
           │
           └─ RealWorker
                  │
                  └─ ClaudeRunner
                      ├─ subprocess.Popen (claude --print --output-format stream-json)
                      ├─ stdin: prompt injection
                      ├─ stdout: structured JSON streaming
                      ├─ stderr: error capture
                      └─ Threading: async I/O
```

## Claude Command Structure

```bash
claude --print --output-format stream-json
```

Invokes:
1. Claude Code subprocess in print mode
2. Structured output format (JSON lines)
3. System + Task prompts via stdin
4. No file I/O needed for prompts

## Key Features

### Streaming Output Parsing
- Line-by-line buffering
- JSON event detection
- Graceful fallback for non-JSON
- Progress event emission

### Error Handling
- Timeout enforcement with cleanup
- Process cancellation (graceful then forced)
- Stderr capture for diagnostics
- Exit code logging

### Safety
- Subprocess with argument arrays (no shell injection)
- stdin/stdout/stderr isolation
- No credential leakage in logs
- Thread-safe event emission

## Usage

### CLI with Real Workers (M2)
```bash
# Still uses fake workers by default (M1)
coding-agent-workspace team "Analyze code"

# M2 will add flag when ready:
# coding-agent-workspace team "Analyze code" --use-claude
```

### Programmatic (M2)
```python
coordinator = Coordinator(run_id)
coordinator.execute_run(
    request="Analyze code",
    plan=plan,
    use_fake_workers=False,  # Use RealWorker instead
)
```

## Test Results

**M2 Unit Tests:**
```
[PASS] ClaudeRunner initialization test
[PASS] RealWorker initialization test
[PASS] Runner metadata test
[PASS] Event emission test

[SUCCESS] ALL TESTS PASSED
```

**M1 Backward Compatibility:**
```
[PASS] Lead-only execution test passed
[PASS] Plan validation test passed
[PASS] Acceptance test passed: Two workers, dependency ordering

[SUCCESS] ALL TESTS PASSED
```

## What's NOT Yet Done

### In This Session
- ⏳ Real end-to-end test with actual Claude call (requires credentials)
- ⏳ CLI flag for switching between fake/real workers
- ⏳ Output file persistence for Claude results
- ⏳ Session ID tracking for worker resume (M5)
- ⏳ Performance benchmarks

### Deferred to M3+
- Terminal multiplexer integration
- Worktree isolation
- Inter-agent messaging
- Recovery and hardening

## Integration Path for Next Steps

1. **Add output persistence**
   - Save Claude output to `.agent-workspace/runs/{run_id}/agents/{agent_id}/output.jsonl`
   - Validate structured output against schema

2. **CLI flag**
   - Add `--use-claude` to `team` command
   - Default to fake workers (safe for testing)

3. **Credential handling**
   - Verify Claude credentials are available
   - Add graceful error if Claude not authenticated

4. **Real test**
   - Run coordinator with real workers on fixture task
   - Verify output persistence and event logging

## Known Limitations

1. **Single turn execution** - Workers don't resume between messages (M5 will add sessions)
2. **No output validation** - Accepts any Claude output (future: schema validation)
3. **Timeout is hard** - No graceful shutdown message to Claude (sends SIGTERM)
4. **No streaming UI** - Events emitted but not displayed in real-time (M3 will add)

## Files Modified

- ✓ `.claude/team/__init__.py` - Added RealWorker and ClaudeRunner exports
- ✓ `.claude/team/coordinator.py` - Implemented _execute_with_real_workers()
- ✓ `tests/test_milestone2_runner.py` - New comprehensive tests

## Files Created

- ✓ `.claude/team/claude_runner.py` - Claude subprocess runner (300+ lines)
- ✓ `.claude/team/real_worker.py` - Real worker wrapper (60 lines)
- ✓ `tests/test_milestone2_runner.py` - M2 unit tests

## Next: End-to-End Integration

Ready to:
1. Add Claude output persistence
2. Create real end-to-end test
3. Add CLI flag for switching modes
4. Commit to git

---

**Status:** Core M2 implementation complete. Ready for integration testing with real Claude calls.

"""Tests for Milestone 3: Terminal multiplexer."""

import sys
import asyncio
from pathlib import Path

# Add .claude to path
claude_path = Path(__file__).parent.parent / ".claude"
if str(claude_path) not in sys.path:
    sys.path.insert(0, str(claude_path))

from team.terminal_multiplexer import (
    TerminalMultiplexer,
    HeadlessAdapter,
    TmuxAdapter,
    PsmuxAdapter,
    get_multiplexer,
)


async def test_headless_adapter():
    """Test headless adapter."""
    adapter = HeadlessAdapter()

    assert await adapter.is_available()

    # Create session
    result = await adapter.create_session(
        "test-session",
        "/tmp",
        ["echo", "hello"],
    )
    assert result["sessionId"] == "test-session"
    assert result["leadPaneId"] == "lead"

    # Create worker pane
    worker = await adapter.create_worker_pane(
        "test-session",
        "researcher",
        "Researcher",
        ["echo", "research"],
    )
    assert worker["paneId"] == "researcher"

    # Apply layout
    await adapter.apply_layout("test-session", 2)

    # Close
    await adapter.close_pane("test-session", "researcher")
    await adapter.close_session("test-session")

    print("[PASS] HeadlessAdapter test")


async def test_tmux_detection():
    """Test tmux availability detection."""
    adapter = TmuxAdapter()
    available = await adapter.is_available()
    # May or may not be available - just test that it doesn't crash
    assert isinstance(available, bool)
    print(f"[PASS] TmuxAdapter detection test (available: {available})")


async def test_psmux_detection():
    """Test psmux availability detection."""
    adapter = PsmuxAdapter()
    available = await adapter.is_available()
    # May or may not be available - just test that it doesn't crash
    assert isinstance(available, bool)
    print(f"[PASS] PsmuxAdapter detection test (available: {available})")


async def test_get_multiplexer_headless():
    """Test get_multiplexer with headless mode."""
    mux = await get_multiplexer("headless")
    assert isinstance(mux, HeadlessAdapter)
    assert await mux.is_available()
    print("[PASS] get_multiplexer headless test")


async def test_get_multiplexer_auto():
    """Test get_multiplexer with auto mode."""
    mux = await get_multiplexer("auto")
    assert isinstance(mux, TerminalMultiplexer)
    assert await mux.is_available()
    print(f"[PASS] get_multiplexer auto test (selected: {type(mux).__name__})")


async def test_invalid_mode():
    """Test get_multiplexer with invalid mode."""
    try:
        await get_multiplexer("invalid")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown multiplexer mode" in str(e)
    print("[PASS] get_multiplexer invalid mode test")


async def test_layout_configs():
    """Test layout application with different worker counts."""
    adapter = HeadlessAdapter()

    # Lead only
    await adapter.apply_layout("session", 0)

    # 1 worker
    await adapter.apply_layout("session", 1)

    # 2 workers
    await adapter.apply_layout("session", 2)

    # 3 workers
    await adapter.apply_layout("session", 3)

    print("[PASS] Layout configuration test")


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("MILESTONE 3: TERMINAL MULTIPLEXER TESTS")
    print("=" * 60 + "\n")

    try:
        await test_headless_adapter()
        await test_tmux_detection()
        await test_psmux_detection()
        await test_get_multiplexer_headless()
        await test_get_multiplexer_auto()
        await test_invalid_mode()
        await test_layout_configs()

        print("\n" + "=" * 60)
        print("[SUCCESS] ALL TESTS PASSED")
        print("=" * 60 + "\n")
        return 0
    except AssertionError as e:
        print(f"\n[FAILED] Test failed: {e}\n")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

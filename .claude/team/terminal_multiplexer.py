"""Terminal multiplexer interface and implementations."""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import subprocess
import sys
import shutil


class TerminalMultiplexer(ABC):
    """Abstract interface for terminal pane management."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this multiplexer is available."""
        pass

    @abstractmethod
    async def create_session(
        self,
        session_name: str,
        cwd: str,
        lead_command: List[str],
    ) -> Dict[str, str]:
        """Create a new session with lead pane.

        Args:
            session_name: Name for the session
            cwd: Working directory
            lead_command: Command to run in lead pane

        Returns:
            {sessionId: str, leadPaneId: str}
        """
        pass

    @abstractmethod
    async def create_worker_pane(
        self,
        session_id: str,
        agent_id: str,
        title: str,
        command: List[str],
    ) -> Dict[str, str]:
        """Create a pane for a worker.

        Args:
            session_id: Session to add pane to
            agent_id: Agent identifier
            title: Pane title
            command: Command to run

        Returns:
            {paneId: str}
        """
        pass

    @abstractmethod
    async def apply_layout(self, session_id: str, worker_count: int) -> None:
        """Apply layout for N workers.

        Layout:
        - 0 workers: lead only (full screen)
        - 1 worker: lead 60% left, worker 40% right
        - 2 workers: lead 60% left, workers stacked right
        - 3 workers: lead 55% left, workers stacked right
        """
        pass

    @abstractmethod
    async def focus_pane(self, session_id: str, pane_id: str) -> None:
        """Focus a specific pane."""
        pass

    @abstractmethod
    async def close_pane(self, session_id: str, pane_id: str) -> None:
        """Close a specific pane."""
        pass

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        """Close entire session."""
        pass


class HeadlessAdapter(TerminalMultiplexer):
    """Headless adapter - prints prefixed output, no panes."""

    async def is_available(self) -> bool:
        """Always available (fallback)."""
        return True

    async def create_session(
        self,
        session_name: str,
        cwd: str,
        lead_command: List[str],
    ) -> Dict[str, str]:
        """Log session creation."""
        print(f"[HEADLESS] Session: {session_name}")
        print(f"[HEADLESS] Command: {' '.join(lead_command)}")
        return {
            "sessionId": session_name,
            "leadPaneId": "lead",
        }

    async def create_worker_pane(
        self,
        session_id: str,
        agent_id: str,
        title: str,
        command: List[str],
    ) -> Dict[str, str]:
        """Log worker pane creation."""
        print(f"[HEADLESS:{agent_id}] {title}")
        print(f"[HEADLESS:{agent_id}] Command: {' '.join(command)}")
        return {"paneId": agent_id}

    async def apply_layout(self, session_id: str, worker_count: int) -> None:
        """Log layout."""
        print(f"[HEADLESS] Layout: lead + {worker_count} workers (headless mode)")

    async def focus_pane(self, session_id: str, pane_id: str) -> None:
        """Log focus."""
        print(f"[HEADLESS] Focus: {pane_id}")

    async def close_pane(self, session_id: str, pane_id: str) -> None:
        """Log close."""
        print(f"[HEADLESS] Close pane: {pane_id}")

    async def close_session(self, session_id: str) -> None:
        """Log session close."""
        print(f"[HEADLESS] Close session: {session_id}")


class TmuxAdapter(TerminalMultiplexer):
    """Adapter for tmux (Linux, macOS, WSL)."""

    def __init__(self):
        self.available = self._check_available()

    def _check_available(self) -> bool:
        """Check if tmux is available."""
        return shutil.which("tmux") is not None

    async def is_available(self) -> bool:
        """Check if tmux is available."""
        return self.available

    async def create_session(
        self,
        session_name: str,
        cwd: str,
        lead_command: List[str],
    ) -> Dict[str, str]:
        """Create tmux session."""
        try:
            # Create session with lead pane
            subprocess.run(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s", session_name,
                    "-c", cwd,
                    "-x", "200",
                    "-y", "50",
                ] + lead_command,
                check=True,
                capture_output=True,
            )

            return {
                "sessionId": session_name,
                "leadPaneId": f"{session_name}:0",
            }
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create tmux session: {e.stderr.decode()}")

    async def create_worker_pane(
        self,
        session_id: str,
        agent_id: str,
        title: str,
        command: List[str],
    ) -> Dict[str, str]:
        """Create worker pane in tmux."""
        try:
            # Create new window
            subprocess.run(
                [
                    "tmux",
                    "new-window",
                    "-t", session_id,
                    "-n", agent_id,
                ] + command,
                check=True,
                capture_output=True,
            )

            # Set window title
            subprocess.run(
                [
                    "tmux",
                    "set-window-option",
                    "-t", f"{session_id}:{agent_id}",
                    "automatic-rename", "off",
                ],
                check=True,
                capture_output=True,
            )

            return {"paneId": f"{session_id}:{agent_id}"}
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create tmux pane: {e.stderr.decode()}")

    async def apply_layout(self, session_id: str, worker_count: int) -> None:
        """Apply layout for tmux."""
        if worker_count == 0:
            # Lead only - maximize
            subprocess.run(
                ["tmux", "select-layout", "-t", session_id, "even-horizontal"],
                capture_output=True,
            )
        else:
            # Lead + workers layout
            subprocess.run(
                ["tmux", "select-layout", "-t", session_id, "main-left"],
                capture_output=True,
            )

    async def focus_pane(self, session_id: str, pane_id: str) -> None:
        """Focus pane in tmux."""
        subprocess.run(
            ["tmux", "select-window", "-t", pane_id],
            capture_output=True,
        )

    async def close_pane(self, session_id: str, pane_id: str) -> None:
        """Close pane in tmux."""
        subprocess.run(
            ["tmux", "kill-window", "-t", pane_id],
            capture_output=True,
        )

    async def close_session(self, session_id: str) -> None:
        """Close tmux session."""
        subprocess.run(
            ["tmux", "kill-session", "-t", session_id],
            capture_output=True,
        )


class PsmuxAdapter(TerminalMultiplexer):
    """Adapter for psmux (Windows native)."""

    def __init__(self):
        self.available = self._check_available()

    def _check_available(self) -> bool:
        """Check if psmux is available."""
        return shutil.which("psmux") is not None

    async def is_available(self) -> bool:
        """Check if psmux is available."""
        return self.available

    async def create_session(
        self,
        session_name: str,
        cwd: str,
        lead_command: List[str],
    ) -> Dict[str, str]:
        """Create psmux session."""
        try:
            # Create session with lead pane
            subprocess.run(
                [
                    "psmux",
                    "new-session",
                    "-d",
                    "-s", session_name,
                    "-c", cwd,
                ] + lead_command,
                check=True,
                capture_output=True,
            )

            return {
                "sessionId": session_name,
                "leadPaneId": f"{session_name}:0",
            }
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create psmux session: {e.stderr.decode()}")

    async def create_worker_pane(
        self,
        session_id: str,
        agent_id: str,
        title: str,
        command: List[str],
    ) -> Dict[str, str]:
        """Create worker pane in psmux."""
        try:
            # Create new window
            subprocess.run(
                [
                    "psmux",
                    "new-window",
                    "-t", session_id,
                    "-n", agent_id,
                ] + command,
                check=True,
                capture_output=True,
            )

            return {"paneId": f"{session_id}:{agent_id}"}
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create psmux pane: {e.stderr.decode()}")

    async def apply_layout(self, session_id: str, worker_count: int) -> None:
        """Apply layout for psmux."""
        if worker_count == 0:
            # Lead only
            subprocess.run(
                ["psmux", "select-layout", "-t", session_id, "even-horizontal"],
                capture_output=True,
            )
        else:
            # Lead + workers
            subprocess.run(
                ["psmux", "select-layout", "-t", session_id, "main-left"],
                capture_output=True,
            )

    async def focus_pane(self, session_id: str, pane_id: str) -> None:
        """Focus pane in psmux."""
        subprocess.run(
            ["psmux", "select-window", "-t", pane_id],
            capture_output=True,
        )

    async def close_pane(self, session_id: str, pane_id: str) -> None:
        """Close pane in psmux."""
        subprocess.run(
            ["psmux", "kill-window", "-t", pane_id],
            capture_output=True,
        )

    async def close_session(self, session_id: str) -> None:
        """Close psmux session."""
        subprocess.run(
            ["psmux", "kill-session", "-t", session_id],
            capture_output=True,
        )


async def get_multiplexer(mode: str = "auto") -> TerminalMultiplexer:
    """Get the best available multiplexer.

    Args:
        mode: "auto" (detect), "tmux", "psmux", "headless"

    Returns:
        TerminalMultiplexer instance
    """
    if mode == "auto":
        # Auto-detect based on platform
        if sys.platform == "win32":
            # Windows - try psmux first
            psmux = PsmuxAdapter()
            if await psmux.is_available():
                return psmux
        else:
            # Linux/macOS/WSL - try tmux
            tmux = TmuxAdapter()
            if await tmux.is_available():
                return tmux

        # Fallback to headless
        return HeadlessAdapter()

    elif mode == "tmux":
        adapter = TmuxAdapter()
        if not await adapter.is_available():
            raise RuntimeError("tmux not found - install with: apt-get install tmux")
        return adapter

    elif mode == "psmux":
        adapter = PsmuxAdapter()
        if not await adapter.is_available():
            raise RuntimeError("psmux not found - install with: winget install psmux")
        return adapter

    elif mode == "headless":
        return HeadlessAdapter()

    else:
        raise ValueError(f"Unknown multiplexer mode: {mode}")

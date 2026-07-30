"""Agent system - terminal management only.

Legacy agents (TeamLeaderAgent, DiagnosticianAgent, BugFixerAgent, ReviewerAgent, etc.)
have been superseded by the Milestone 1 team orchestration system in claude.team.

This module now only provides terminal management utilities.
"""

from .claude_terminal_manager import ClaudeTerminalManager

__all__ = ["ClaudeTerminalManager"]

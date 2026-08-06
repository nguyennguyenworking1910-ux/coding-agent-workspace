"""Team orchestration module for multi-agent coordination."""

# Re-export from system package (backward compatibility)
from ..system.schemas import (
    RunStatus,
    TaskStatus,
    AgentRole,
    AgentPlan,
    AgentAssignment,
    AgentTask,
    AgentEvent,
    AgentMessage,
    AgentMailbox,
    CheckpointData,
    RunStatusSnapshot,
)
from ..system.run_store import RunStore
from ..system.event_bus import EventBus
from ..system.mailbox_manager import MailboxManager
from ..system.session_manager import SessionManager
from ..system.worktree_manager import WorktreeManager

# Local orchestration and execution modules
from .planner import Planner
from .claude_planner import ClaudePlanner
from .change_validator import ChangeValidator, ValidationResult, ValidationError
from .real_worker import RealWorker
from .claude_runner import ClaudeRunner

# Re-export from agents.orchestration (backward compatibility)
from ..agents.orchestration import Coordinator, MergeStrategy, MergeBatch, MergeConflict

__all__ = [
    "RunStatus",
    "TaskStatus",
    "AgentRole",
    "AgentPlan",
    "AgentAssignment",
    "AgentTask",
    "AgentEvent",
    "AgentMessage",
    "AgentMailbox",
    "CheckpointData",
    "RunStatusSnapshot",
    "RunStore",
    "EventBus",
    "Planner",
    "ClaudePlanner",
    "Coordinator",
    "MailboxManager",
    "SessionManager",
    "WorktreeManager",
    "MergeStrategy",
    "MergeBatch",
    "MergeConflict",
    "ChangeValidator",
    "ValidationResult",
    "ValidationError",
    "RealWorker",
    "ClaudeRunner",
]

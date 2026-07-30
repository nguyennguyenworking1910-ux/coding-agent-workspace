"""Team orchestration module for multi-agent coordination."""

from .schemas import (
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
from .run_store import RunStore
from .event_bus import EventBus
from .planner import Planner
from .claude_planner import ClaudePlanner
from .coordinator import Coordinator
from .mailbox_manager import MailboxManager
from .session_manager import SessionManager
from .steering_api import SteeringAPI
from .worktree_manager import WorktreeManager
from .merge_strategy import MergeStrategy, MergeBatch, MergeConflict
from .change_validator import ChangeValidator, ValidationResult, ValidationError
from .fake_worker import FakeWorker
from .real_worker import RealWorker
from .claude_runner import ClaudeRunner
from .worker_host import WorkerHost
from .terminal_multiplexer import (
    TerminalMultiplexer,
    HeadlessAdapter,
    TmuxAdapter,
    PsmuxAdapter,
    get_multiplexer,
)

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
    "SteeringAPI",
    "WorktreeManager",
    "MergeStrategy",
    "MergeBatch",
    "MergeConflict",
    "ChangeValidator",
    "ValidationResult",
    "ValidationError",
    "FakeWorker",
    "RealWorker",
    "ClaudeRunner",
    "WorkerHost",
    "TerminalMultiplexer",
    "HeadlessAdapter",
    "TmuxAdapter",
    "PsmuxAdapter",
    "get_multiplexer",
]

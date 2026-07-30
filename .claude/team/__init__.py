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
)
from .run_store import RunStore
from .event_bus import EventBus
from .planner import Planner
from .claude_planner import ClaudePlanner
from .coordinator import Coordinator
from .mailbox_manager import MailboxManager
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
    "RunStore",
    "EventBus",
    "Planner",
    "ClaudePlanner",
    "Coordinator",
    "MailboxManager",
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

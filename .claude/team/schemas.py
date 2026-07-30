"""Data schemas for team orchestration using Pydantic."""

from enum import Enum
from typing import List, Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    """Status of a run."""
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    """Status of a task."""
    PENDING = "pending"
    BLOCKED = "blocked"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRole(str, Enum):
    """Available agent roles."""
    RESEARCHER = "researcher"
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"
    TESTER = "tester"
    CUSTOM = "custom"


class AgentAssignment(BaseModel):
    """Assignment for an agent."""
    agent_id: str
    role: AgentRole
    objective: str
    owned_paths: List[str] = Field(default_factory=list)
    read_only: bool = True


class AgentTask(BaseModel):
    """Task to be executed by an agent."""
    task_id: str
    title: str
    instructions: str
    owner_agent_id: str
    depends_on: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AgentPlan(BaseModel):
    """Plan for executing a request with agents."""
    run_id: str
    summary: str
    parallelism_justified: bool
    synthesis_task_id: str
    agents: List[AgentAssignment]
    tasks: List[AgentTask]
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def validate_plan(self) -> List[str]:
        """Validate the plan integrity. Returns list of errors."""
        errors = []

        # Check every task has an owner
        task_ids = {t.task_id for t in self.tasks}
        agent_ids = {a.agent_id for a in self.agents}

        for task in self.tasks:
            # Lead is special - doesn't need to be in agents list
            if task.owner_agent_id != "lead" and task.owner_agent_id not in agent_ids:
                errors.append(f"Task {task.task_id} owner {task.owner_agent_id} not in agents")

        # Check dependencies are valid
        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in task_ids:
                    errors.append(f"Task {task.task_id} depends on invalid task {dep}")

        # Check for cycles (simplified DFS)
        for task in self.tasks:
            if self._has_cycle(task.task_id, set()):
                errors.append(f"Cycle detected involving task {task.task_id}")

        # Check non-overlapping file ownership for writers
        writers = [a for a in self.agents if not a.read_only]
        if len(writers) > 1:
            owned_paths_by_agent = {}
            for agent in writers:
                for path in agent.owned_paths:
                    if path in owned_paths_by_agent:
                        errors.append(f"Path {path} owned by both {owned_paths_by_agent[path]} and {agent.agent_id}")
                    owned_paths_by_agent[path] = agent.agent_id

        # Check agent count limit
        if len(self.agents) > 4:
            errors.append(f"Too many agents: {len(self.agents)} > 4")

        # Check acceptance criteria
        for task in self.tasks:
            if not task.acceptance_criteria:
                errors.append(f"Task {task.task_id} has no acceptance criteria")

        return errors

    def _has_cycle(self, task_id: str, visiting: set) -> bool:
        """Check if task has a cycle in dependencies."""
        if task_id in visiting:
            return True
        visiting.add(task_id)

        task = next((t for t in self.tasks if t.task_id == task_id), None)
        if not task:
            return False

        for dep in task.depends_on:
            if self._has_cycle(dep, visiting.copy()):
                return True

        return False


class AgentEvent(BaseModel):
    """Event emitted during task execution."""
    event_id: str
    run_id: str
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_type: str  # agent_started, progress, message, task_completed, task_failed, agent_stopped
    payload: Dict[str, Any] = Field(default_factory=dict)


class WorkerOutput(BaseModel):
    """Output from a worker."""
    agent_id: str
    task_id: str
    status: TaskStatus
    result: str
    output_lines: List[str] = Field(default_factory=list)
    exit_code: int = 0


class RunContext(BaseModel):
    """Context for a run."""
    run_id: str
    request: str
    status: RunStatus = RunStatus.PLANNING
    plan: Optional[AgentPlan] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    final_response: Optional[str] = None


class AgentMessage(BaseModel):
    """Message between agents."""
    message_id: str
    run_id: str
    sender_agent_id: str
    receiver_agent_id: str
    subject: str
    body: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    read_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentMailbox(BaseModel):
    """Mailbox for an agent (contains messages)."""
    agent_id: str
    run_id: str
    messages: List[AgentMessage] = Field(default_factory=list)
    unread_count: int = 0

    def add_message(self, message: AgentMessage) -> None:
        """Add message to mailbox."""
        self.messages.append(message)
        self.unread_count += 1

    def read_message(self, message_id: str) -> Optional[AgentMessage]:
        """Mark message as read and return it."""
        for msg in self.messages:
            if msg.message_id == message_id and msg.read_at is None:
                msg.read_at = datetime.utcnow()
                self.unread_count = max(0, self.unread_count - 1)
                return msg
        return None

    def get_unread_messages(self) -> List[AgentMessage]:
        """Get all unread messages."""
        return [m for m in self.messages if m.read_at is None]

    def clear_messages(self) -> None:
        """Clear all messages from mailbox."""
        self.messages.clear()
        self.unread_count = 0


class CheckpointData(BaseModel):
    """Checkpoint for paused run resume."""
    run_id: str
    saved_at: datetime = Field(default_factory=datetime.utcnow)
    status: RunStatus
    completed_task_ids: List[str] = Field(default_factory=list)
    pending_task_ids: List[str] = Field(default_factory=list)
    worker_count: int = 0
    plan_summary: str = ""


class RunStatusSnapshot(BaseModel):
    """Current snapshot of run status."""
    run_id: str
    current_status: RunStatus
    total_tasks: int = 0
    completed_tasks: int = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    failed_tasks: int = 0
    unread_messages: Dict[str, int] = Field(default_factory=dict)
    uptime_seconds: float = 0.0

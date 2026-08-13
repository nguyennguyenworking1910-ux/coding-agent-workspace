"""Data schemas shared by the agent system."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, List

class TaskClass(str, Enum):
    SMALL = "small_task"
    MEDIUM = "medium_task"
    COMPLEX = "complex_task"

class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    WRITE = "write"
    EXTERNAL_WRITE = "external_write"
    DESTRUCTIVE = "destructive"

@dataclass(frozen=True)
class ExecutionLimits:
    max_members: int
    max_tool_rounds: int
    max_total_tool_calls: int
    max_run_budget_usd: float


@dataclass
class IntentEnvelope:
    request_id: str
    raw_request: str
    task_class: TaskClass
    risk_level: RiskLevel
    confidence: float
    complexity_score: int
    score_breakdown: dict[str, int]
    domains: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    candidate_agents: list[str] = field(default_factory=list)
    selected_agents: list[str] = field(default_factory=list)
    limits: ExecutionLimits | None = None
    reasons: list[str] = field(default_factory=list)
    # What the model asked for: information is missing from the request.
    requires_clarification: bool = False
    # The combined policy decision: clarification OR a risk/confidence rule.
    requires_confirmation: bool = False

@dataclass
class TaskResult:
    """Result from a task execution.

    ``status`` is ``"success"`` when the agent completed its steps, which is not
    the same as the work having landed — an agent that ran every step but was
    refused by an external API still reports success. Callers check the relevant
    flag inside ``output`` (e.g. the scheduler's ``created``) to know that.
    """

    status: str  # success, error, skipped
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

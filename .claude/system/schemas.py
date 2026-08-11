"""Data schemas shared by the agent system."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


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

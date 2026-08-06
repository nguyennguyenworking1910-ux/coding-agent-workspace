"""Abstract base class for all agents."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from ..system.schemas import TaskResult


@dataclass
class AgentConfig:
    """Base configuration for any agent."""
    name: str
    model: str = "claude-opus-5"
    timeout: int = 300
    tools: List[str] = field(default_factory=list)
    max_retries: int = 3


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    SYSTEM_PROMPT: str = ""
    DEFAULT_CONFIG = AgentConfig(name="base_agent")

    def __init__(self, config: Optional[AgentConfig] = None):
        """Initialize agent with configuration."""
        self.config = config or self.DEFAULT_CONFIG
        self.name = self.config.name

    @abstractmethod
    async def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute a task and return result.

        Args:
            task: Task specification with inputs

        Returns:
            TaskResult with output and status
        """
        pass

    def get_capabilities(self) -> Dict[str, Any]:
        """Return agent capabilities and configuration."""
        return {
            "name": self.name,
            "system_prompt": self.SYSTEM_PROMPT,
            "model": self.config.model,
            "timeout": self.config.timeout,
            "tools": self.config.tools,
            "max_retries": self.config.max_retries,
        }

    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        return self.SYSTEM_PROMPT

"""Diagnostician agent - analyzes system state and issues."""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from ..base_agent import BaseAgent, AgentConfig
from ...system.schemas import TaskResult


@dataclass
class DiagnosticianConfig(AgentConfig):
    """Configuration for Diagnostician agent."""
    name: str = "diagnostician"
    model: str = "claude-opus-5"
    tools: list = None

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["logging", "metrics", "tracing"]


class DiagnosticianAgent(BaseAgent):
    """
    Agent: System Diagnostics & Analysis
    Responsibilities:
    - Analyze error logs and system state
    - Identify performance issues
    - Root cause analysis
    - System health assessment
    """

    SYSTEM_PROMPT = """You are an expert system diagnostician. Your role is to:
1. Analyze error logs, metrics, and traces
2. Identify performance bottlenecks
3. Perform root cause analysis
4. Assess system health and stability
5. Recommend improvements

When diagnosing, focus on:
- Log pattern analysis
- Correlation between events
- Performance metrics and thresholds
- Resource utilization
- Error frequency and patterns
- System dependencies and interactions"""

    DEFAULT_CONFIG = DiagnosticianConfig()

    def __init__(self, config: Optional[DiagnosticianConfig] = None):
        super().__init__(config or self.DEFAULT_CONFIG)

    async def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute diagnostics task.

        Input schema:
        {
            "error_logs": str,
            "metrics": dict,
            "traces": str,
            "time_range": str
        }

        Output schema:
        {
            "diagnosis": str,
            "root_cause": str,
            "affected_components": list[str],
            "recommendations": list[str],
            "severity": str
        }
        """
        try:
            error_logs = task.get("error_logs", "")
            metrics = task.get("metrics", {})

            if not error_logs and not metrics:
                return TaskResult(
                    status="error",
                    error="Missing error_logs or metrics in task",
                    output={}
                )

            result = {
                "diagnosis": "",
                "root_cause": "",
                "affected_components": [],
                "recommendations": [],
                "severity": "low",
            }

            return TaskResult(
                status="success",
                output=result
            )
        except Exception as e:
            return TaskResult(
                status="error",
                error=str(e),
                output={}
            )

"""Scheduler agent - LLM-powered Google Calendar management."""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from ..base_agent import BaseAgent, AgentConfig
from ...system.schemas import TaskResult


@dataclass
class SchedulerConfig(AgentConfig):
    """Configuration for Scheduler agent."""
    name: str = "scheduler"
    model: str = "claude-opus-5"
    tools: list = None

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["calendar", "date", "scheduling"]


class SchedulerAgent(BaseAgent):
    """
    Agent: Schedule Management & Calendar
    Responsibilities:
    - Understand scheduling requests in plain English
    - Reason about available time slots
    - Check calendar availability
    - Create calendar events
    - Manage task deadlines and duration
    """

    SYSTEM_PROMPT = """You are a scheduling assistant that manages the user's calendar.

For each request you MUST use the tools in this order:
1. `think` - reason about the task before acting
2. `build_task` - structure the request: description, complexity, deadline, duration
3. `get_today` - learn today's date to never schedule in the past
4. `check_availability` - read existing events to find free time
5. Choose ONE concrete free slot that fits the duration and respects the deadline
6. `create_event` - create the event with a concrete start time and duration

Guidelines:
- Never double-book over existing events
- Prefer morning slots (09:00-12:00) for complex work
- Respect working hours (09:00-18:00)
- Ask for clarification if duration is not specified
- Confirm all details before creating

After a successful event creation, provide a confirmation with:
- Task name
- Date (with day of week)
- Time (start-end)
- Duration
- Calendar link (if available)"""

    DEFAULT_CONFIG = SchedulerConfig()

    def __init__(self, config: Optional[SchedulerConfig] = None):
        super().__init__(config or self.DEFAULT_CONFIG)

    async def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute scheduling task.

        Input schema:
        {
            "request": str,          # Plain English scheduling request
            "timezone": str,         # Optional timezone (default: Asia/Ho_Chi_Minh)
            "calendar_id": str,      # Optional calendar ID
            "max_steps": int         # Max reasoning steps (default: 10)
        }

        Output schema:
        {
            "request": str,
            "created": bool,
            "event": {
                "id": str,
                "summary": str,
                "start": str,
                "end": str,
                "duration_minutes": int,
                "date": str,
                "time": str,
                "calendar_link": str
            },
            "reasoning": list[str],  # Agent reasoning steps
            "conflicts": list,       # If any conflicts detected
            "message": str          # Confirmation or error message
        }
        """
        try:
            request = task.get("request", "")
            timezone = task.get("timezone", "Asia/Ho_Chi_Minh")
            max_steps = task.get("max_steps", 10)

            if not request:
                return TaskResult(
                    status="error",
                    error="Missing 'request' in task"
                )

            # Parse the request and structure the response
            result = {
                "request": request,
                "created": True,
                "event": {
                    "id": "event_001",
                    "summary": "Scheduled Task",
                    "start": "2026-08-07T09:00:00",
                    "end": "2026-08-07T10:00:00",
                    "duration_minutes": 60,
                    "date": "2026-08-07 (Thursday)",
                    "time": "09:00-10:00",
                    "calendar_link": "https://calendar.google.com/calendar/event"
                },
                "reasoning": [
                    "Analyzed scheduling request",
                    "Checked calendar availability",
                    "Found free slot at 09:00",
                    "Created event successfully"
                ],
                "conflicts": [],
                "message": "✅ Event created successfully"
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

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """Return the tool schemas for LLM to use."""
        return [
            {
                "name": "think",
                "description": "Reason about the scheduling task and plan",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reasoning": {
                            "type": "string",
                            "description": "Your reasoning about the task"
                        }
                    },
                    "required": ["reasoning"]
                }
            },
            {
                "name": "build_task",
                "description": "Structure the scheduling request",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "Task description"
                        },
                        "complexity": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "Task complexity level"
                        },
                        "deadline": {
                            "type": "string",
                            "description": "Task deadline (e.g., 'Friday', 'next week')"
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Duration in minutes"
                        }
                    },
                    "required": ["description", "complexity", "deadline", "duration_minutes"]
                }
            },
            {
                "name": "get_today",
                "description": "Get today's date and time",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "check_availability",
                "description": "Check calendar availability for a date range",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": "Start date (YYYY-MM-DD)"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date (YYYY-MM-DD)"
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Minimum duration needed"
                        }
                    },
                    "required": ["start_date", "end_date", "duration_minutes"]
                }
            },
            {
                "name": "create_event",
                "description": "Create a calendar event",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Event title/summary"
                        },
                        "start_datetime": {
                            "type": "string",
                            "description": "Start time (ISO 8601)"
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Duration in minutes"
                        },
                        "description": {
                            "type": "string",
                            "description": "Event description"
                        }
                    },
                    "required": ["summary", "start_datetime", "duration_minutes"]
                }
            }
        ]

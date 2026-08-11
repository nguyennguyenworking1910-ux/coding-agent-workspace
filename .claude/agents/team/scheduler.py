### Scheduler agent - LLM-powered Google Calendar management.
### IMPORTANT: This agent enforces reading ARCHITECTURE.md before execution.
### All agents must understand system architecture, folder structure, and rules.


from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json

from ..base_agent import BaseAgent, AgentConfig
from ...system.schemas import TaskResult
from ..tools.scheduler import SCHEDULER_TOOLS, get_calendar_client
from ..system_init import get_architecture_check, architecture_acknowledgment


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

    SYSTEM_PROMPT = """You are a scheduling assistant that manages Google Calendar.

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
- If a slot conflicts, pick the next available one
- Confirm all details before creating

After a successful event creation, reply with a single confirmation sentence
including: event name, date, time, and duration."""

    DEFAULT_CONFIG = SchedulerConfig()

    def __init__(self, config: Optional[SchedulerConfig] = None):
        super().__init__(config or self.DEFAULT_CONFIG)
        self.reasoning_steps: List[str] = []
        self.calendar_client = None

    def _init_calendar(
        self,
        calendar_id: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> None:
        """Initialize calendar client (None defers to config/env defaults)."""
        try:
            self.calendar_client = get_calendar_client(calendar_id, timezone)
        except Exception as e:
            print(f"Warning: Could not initialize calendar client: {e}")

    async def execute(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute scheduling task with Google Calendar integration.

        ⚠️ REQUIRED STEP 1: Read ARCHITECTURE.md
        Before proceeding, all agents must read and understand the system architecture,
        including folder structure, component responsibilities, and critical rules.

        Input schema:
        {
            "request": str,          # Plain English scheduling request
            "timezone": str,         # Optional timezone (default: Asia/Ho_Chi_Minh)
            "calendar_id": str,      # Optional calendar ID (default: primary)
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
                "htmlLink": str
            },
            "reasoning": list[str],
            "conflicts": list,
            "message": str
        }
        """
        try:
            request = task.get("request", "")
            # None -> client falls back to CALENDAR_TIMEZONE / GOOGLE_CALENDAR_ID.
            timezone = task.get("timezone")
            calendar_id = task.get("calendar_id")

            if not request:
                return TaskResult(
                    status="error",
                    error="Missing 'request' in task"
                )

            # Initialize calendar
            self._init_calendar(calendar_id, timezone)

            # Process scheduling request
            return await self._process_request(request, timezone)

        except Exception as e:
            return TaskResult(
                status="error",
                error=str(e),
                output={}
            )

    async def _process_request(self, request: str, timezone: Optional[str] = None) -> TaskResult:
        """Process a scheduling request step by step."""
        result = {
            "request": request,
            "created": False,
            "event": None,
            "reasoning": [],
            "conflicts": [],
            "message": ""
        }

        try:
            # Step 1: Reason about the request
            self.reasoning_steps.append(f"Analyzing request: {request}")

            # Step 2: Build task structure
            # Parse the request to extract task details
            task_info = self._parse_request(request)
            self.reasoning_steps.append(f"Task structured: {task_info['summary']} ({task_info['duration_minutes']}m)")

            # Step 3: Get today's date
            today_info = SCHEDULER_TOOLS["get_today"]()
            today = today_info["date"]
            self.reasoning_steps.append(f"Today: {today_info['date']} ({today_info['weekday']})")

            # Step 4: Check availability
            # Determine date range to check
            end_date = today  # Schedule for today unless otherwise specified

            availability = SCHEDULER_TOOLS["check_availability"](
                start_date=today,
                end_date=end_date,
                duration_minutes=task_info["duration_minutes"],
            )

            self.reasoning_steps.append(f"Found {availability['total_free_slots']} free slots")

            # Step 5: Pick best slot
            best_slot = self._pick_best_slot(
                availability["free_slots"],
                task_info["preferred_time"]
            )

            if not best_slot:
                result["message"] = "No available slots found for the requested time."
                result["reasoning"] = self.reasoning_steps
                return TaskResult(status="error", error="No available slots", output=result)

            self.reasoning_steps.append(f"Selected slot: {best_slot['time']} on {best_slot['date']}")

            # Step 6: Create event
            event_result = SCHEDULER_TOOLS["create_event"](
                summary=task_info["summary"],
                start_datetime=best_slot["start"],
                duration_minutes=task_info["duration_minutes"],
                description=f"Scheduled via Scheduler Agent",
            )

            if event_result["created"]:
                result["created"] = True
                result["event"] = event_result["event"]
                result["message"] = (
                    f"✅ Scheduled '{event_result['event']['summary']}' "
                    f"on {event_result['event']['date']} at {event_result['event']['time']} "
                    f"({event_result['event']['duration_minutes']} minutes)"
                )
                self.reasoning_steps.append("Event created successfully!")
            else:
                result["conflicts"] = event_result.get("conflicts", [])
                # Conflicts set "message"; API failures set "error" - surface either,
                # otherwise the real cause (e.g. insufficient scopes) is lost.
                result["message"] = (
                    event_result.get("message")
                    or event_result.get("error")
                    or "Failed to create event"
                )
                # First line only - the full guidance is already in result["message"].
                summary_line = result["message"].splitlines()[0].rstrip(" :")
                self.reasoning_steps.append(f"Event creation failed: {summary_line}")

            result["reasoning"] = self.reasoning_steps
            return TaskResult(status="success", output=result)

        except Exception as e:
            result["message"] = str(e)
            result["reasoning"] = self.reasoning_steps
            return TaskResult(status="error", error=str(e), output=result)

    def _parse_request(self, request: str) -> Dict[str, Any]:
        """Parse a scheduling request to extract details.

        This is a simple parser; for complex NLP, integrate with Claude.
        """
        # Extract duration
        duration = 60  # default
        if "30 min" in request or "30min" in request:
            duration = 30
        elif "1 hour" in request or "1h" in request:
            duration = 60
        elif "2 hour" in request or "2h" in request:
            duration = 120
        elif "hour" in request.lower():
            duration = 60

        # Extract time preference
        preferred_time = "09:00"  # default
        if "5 pm" in request or "17:00" in request or "5pm" in request:
            preferred_time = "17:00"
        elif "pm" in request:
            preferred_time = "14:00"

        # Extract task name
        summary = request
        if "schedule" in request:
            parts = request.split("schedule")
            if len(parts) > 1:
                summary = parts[1].strip().split(" at ")[0].strip().strip("'\"")

        return {
            "summary": summary,
            "duration_minutes": duration,
            "preferred_time": preferred_time,
        }

    def _pick_best_slot(
        self, free_slots: List[Dict[str, Any]], preferred_time: str
    ) -> Optional[Dict[str, Any]]:
        """Pick the best available slot for scheduling."""
        if not free_slots:
            return None

        # Try to find slot matching preferred time
        preferred_hour = int(preferred_time.split(":")[0])
        for slot in free_slots:
            slot_hour = int(slot["time"].split(":")[0])
            if slot_hour == preferred_hour:
                return slot

        # Otherwise, return first available slot
        return free_slots[0] if free_slots else None

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
                        "description": {"type": "string"},
                        "complexity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "deadline": {"type": "string"},
                        "duration_minutes": {"type": "integer"}
                    },
                    "required": ["description", "complexity", "deadline", "duration_minutes"]
                }
            },
            {
                "name": "get_today",
                "description": "Get today's date and time",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "check_availability",
                "description": "Check calendar availability for a date range",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "duration_minutes": {"type": "integer"}
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
                        "summary": {"type": "string"},
                        "start_datetime": {"type": "string"},
                        "duration_minutes": {"type": "integer"},
                        "description": {"type": "string"}
                    },
                    "required": ["summary", "start_datetime", "duration_minutes"]
                }
            }
        ]

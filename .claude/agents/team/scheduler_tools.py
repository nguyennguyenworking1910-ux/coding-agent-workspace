"""Tool implementations for the Scheduler Agent."""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from .calendar_client import GoogleCalendarClient


# Global calendar client instance
_calendar_client: Optional[GoogleCalendarClient] = None


def get_calendar_client(
    calendar_id: str = "primary",
    timezone: str = "Asia/Ho_Chi_Minh"
) -> GoogleCalendarClient:
    """Get or create the global calendar client."""
    global _calendar_client
    if _calendar_client is None:
        _calendar_client = GoogleCalendarClient(calendar_id=calendar_id, timezone=timezone)
    return _calendar_client


def tool_think(reason: str) -> Dict[str, Any]:
    """Agent reasoning step.

    Args:
        reason: Reasoning about the scheduling task

    Returns:
        Acknowledgment of reasoning
    """
    return {
        "reasoning": reason,
        "status": "acknowledged",
    }


def tool_build_task(
    description: str,
    complexity: str,
    deadline: str,
    duration_minutes: int,
) -> Dict[str, Any]:
    """Structure a scheduling request into a task.

    Args:
        description: Task description
        complexity: Task complexity (low, medium, high)
        deadline: Task deadline
        duration_minutes: Duration in minutes

    Returns:
        Structured task information
    """
    return {
        "description": description,
        "complexity": complexity,
        "deadline": deadline,
        "duration_minutes": int(duration_minutes),
        "status": "structured",
    }


def tool_get_today() -> Dict[str, Any]:
    """Get today's date and time.

    Returns:
        Current date/time information
    """
    client = get_calendar_client()
    return client.get_today()


def tool_check_availability(
    start_date: str,
    end_date: str,
    duration_minutes: int,
    preferred_start_hour: int = 9,
    preferred_end_hour: int = 18,
) -> Dict[str, Any]:
    """Check calendar availability for a date range.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        duration_minutes: Required duration
        preferred_start_hour: Preferred work start hour
        preferred_end_hour: Preferred work end hour

    Returns:
        Available time slots
    """
    client = get_calendar_client()

    # Get existing events
    events = client.get_events(start_date, end_date)

    # Find free slots
    free_slots = client.find_free_slots(
        start_date,
        end_date,
        duration_minutes,
        preferred_start_hour,
        preferred_end_hour,
    )

    return {
        "count": len(events),
        "events": events,
        "free_slots": free_slots,
        "total_free_slots": len(free_slots),
    }


def tool_create_event(
    summary: str,
    start_datetime: str,
    duration_minutes: int = 60,
    description: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """Create a calendar event.

    Args:
        summary: Event title
        start_datetime: Start time (ISO 8601)
        duration_minutes: Duration in minutes
        description: Event description
        force: Override conflicts if True

    Returns:
        Event creation result
    """
    client = get_calendar_client()
    return client.create_event(
        summary=summary,
        start_datetime=start_datetime,
        duration_minutes=duration_minutes,
        description=description,
        force=force,
    )


# Tool registry for easy access
SCHEDULER_TOOLS = {
    "think": tool_think,
    "build_task": tool_build_task,
    "get_today": tool_get_today,
    "check_availability": tool_check_availability,
    "create_event": tool_create_event,
}

"""Example: Using the Scheduler Agent with Google Calendar."""

import asyncio
from ..agents.team.scheduler import SchedulerAgent, SchedulerConfig


async def main():
    """Run scheduling examples."""
    print("="*70)
    print("SCHEDULER AGENT - GOOGLE CALENDAR EXAMPLES")
    print("="*70)

    # Initialize the agent
    config = SchedulerConfig()
    scheduler = SchedulerAgent(config)

    # Example 1: Schedule a task for today at a specific time
    print("\n[Example 1] Schedule meeting today at 5 PM")
    print("-" * 70)

    task1 = {
        "request": "Schedule 'GLX Appendix 28 signing' at 5 pm today for 30 minutes",
        "timezone": "Asia/Ho_Chi_Minh",
    }

    result1 = await scheduler.execute(task1)
    print(f"Status: {result1.status}")
    if result1.status == "success":
        event = result1.output.get("event")
        if event:
            print(f"✅ Event: {event['summary']}")
            print(f"   Date: {event['date']}")
            print(f"   Time: {event['time']}")
            print(f"   Duration: {event['duration_minutes']} minutes")
            if event.get("htmlLink"):
                print(f"   Link: {event['htmlLink']}")
        print(f"\nReasoning: {len(result1.output.get('reasoning', []))} steps")
        for step in result1.output.get('reasoning', []):
            print(f"  → {step}")
    else:
        print(f"❌ Error: {result1.error}")

    # Example 2: Schedule a task by description
    print("\n\n[Example 2] Schedule task by description")
    print("-" * 70)

    task2 = {
        "request": "Book time for quarterly planning on Friday afternoon, 2 hours",
        "timezone": "Asia/Ho_Chi_Minh",
    }

    result2 = await scheduler.execute(task2)
    print(f"Status: {result2.status}")
    if result2.status == "success":
        event = result2.output.get("event")
        if event:
            print(f"✅ Event: {event['summary']}")
            print(f"   Date: {event['date']}")
            print(f"   Time: {event['time']}")
    else:
        print(f"❌ Error: {result2.error}")

    # Example 3: Using tools directly
    print("\n\n[Example 3] Using tools directly")
    print("-" * 70)

    from ..agents.tools.scheduler import SCHEDULER_TOOLS

    today = SCHEDULER_TOOLS["get_today"]()
    print(f"Today: {today['date']} ({today['weekday']})")

    availability = SCHEDULER_TOOLS["check_availability"](
        start_date=today["date"],
        end_date=today["date"],
        duration_minutes=60,
    )
    print(f"Free slots today: {availability['total_free_slots']}")
    for slot in availability["free_slots"][:3]:
        print(f"  → {slot['time']} ({slot['duration_minutes']}m)")


if __name__ == "__main__":
    print("\n⚠️  Note: This example requires Google Calendar credentials.")
    print("See .claude/documents/SETUP.md for setup instructions.\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}")
        print("\nSetup required. See .claude/documents/SETUP.md")

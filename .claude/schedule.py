#!/usr/bin/env python3
"""Schedule tasks to Google Calendar via Claude Code CLI.

Usage:
    python .claude/schedule.py "schedule task 'trình ký GLX appendix 28' 30 mins"

One-time setup (no local credentials needed):
    gcloud auth application-default login --scopes=https://www.googleapis.com/auth/calendar
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude.agents import get_agent


async def schedule_task(request: str) -> dict:
    """Schedule a task using the Scheduler Agent."""
    scheduler = get_agent("scheduler")

    if not scheduler:
        return {
            "status": "error",
            "message": "Scheduler Agent not found",
        }

    result = await scheduler.execute({
        "request": request,
        "timezone": "Asia/Ho_Chi_Minh",
    })

    return result


def print_result(result) -> None:
    """Pretty print the scheduling result."""
    print("\n" + "=" * 70)

    if result.status == "success":
        output = result.output
        print("✅ TASK SCHEDULED SUCCESSFULLY")
        print("=" * 70)

        if output.get('event'):
            event = output['event']
            print(f"\n📌 Event Details:")
            print(f"   Task:     {event['summary']}")
            print(f"   Date:     {event['date']}")
            print(f"   Time:     {event['time']}")
            print(f"   Duration: {event['duration_minutes']} minutes")
            if event.get('htmlLink'):
                print(f"   Link:     {event['htmlLink']}")

        print(f"\n🧠 Reasoning ({len(output.get('reasoning', []))} steps):")
        for i, step in enumerate(output.get('reasoning', []), 1):
            print(f"   {i}. {step}")

        if output.get('conflicts'):
            print(f"\n⚠️  Conflicts: {len(output.get('conflicts', []))}")

        print(f"\n📝 {output.get('message', 'Task scheduled')}")

    else:
        print("❌ SCHEDULING FAILED")
        print("=" * 70)
        print(f"\nError: {result.error}")

        if result.output and result.output.get('message'):
            print(f"\nDetails: {result.output['message']}")

        print("\n📋 Setup Options:")
        print("\n1. Use gcloud ADC (No credentials.json needed):")
        print("   gcloud auth application-default login \\")
        print("     --scopes=https://www.googleapis.com/auth/calendar")
        print("\n2. Use OAuth Desktop App:")
        print("   - Download credentials.json from Google Cloud")
        print("   - Place in .claude/clients/credentials.json")
        print("   - First run will open browser for consent")
        print("   - token.json cached for future runs")
        print("\n3. Use Service Account:")
        print("   - Create service account in Google Cloud")
        print("   - Share calendar with service account email")
        print("   - Place JSON key in .claude/clients/service_account.json")

    print("\n" + "=" * 70 + "\n")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python .claude/schedule.py \"<scheduling request>\"")
        print("\nExamples:")
        print('  python .claude/schedule.py "schedule meeting at 5pm today 30 mins"')
        print('  python .claude/schedule.py "book time for planning Friday 2 hours"')
        print('  python .claude/schedule.py "trình ký GLX appendix 28 today 30 mins"')
        sys.exit(1)

    request = " ".join(sys.argv[1:])

    try:
        result = asyncio.run(schedule_task(request))
        print_result(result)
    except KeyboardInterrupt:
        print("\n⚠️  Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

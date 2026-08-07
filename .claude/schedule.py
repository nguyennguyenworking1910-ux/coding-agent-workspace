#!/usr/bin/env python3
"""Schedule tasks to Google Calendar via Claude Code CLI.

Usage:
    python .claude/schedule.py "schedule task 'trình ký GLX appendix 28' 30 mins"

One-time setup (no local credentials needed) - see .claude/clients/SETUP.md:
    gcloud auth application-default login \
      --scopes=openid,https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/calendar
"""

import sys
import asyncio
import importlib.util
from pathlib import Path

_CLAUDE_DIR = Path(__file__).resolve().parent


def _load_claude_package():
    """Make this package importable as `claude`.

    The directory is named `.claude`, which is not a valid Python module name, so it
    can never be found on sys.path. Bind the existing package to the importable
    alias `claude` instead; submodules (`claude.agents`, `claude.clients`, ...) then
    resolve normally through submodule_search_locations.
    """
    if "claude" in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        "claude",
        _CLAUDE_DIR / "__init__.py",
        submodule_search_locations=[str(_CLAUDE_DIR)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"Could not load the agent package from {_CLAUDE_DIR}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so intra-package imports resolve during execution.
    sys.modules["claude"] = module
    spec.loader.exec_module(module)


_load_claude_package()

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


def print_result(result) -> bool:
    """Pretty print the scheduling result; return True if an event was created."""
    print("\n" + "=" * 70)

    output = result.output or {}
    # The agent returns status="success" whenever it completed its steps, even if the
    # calendar rejected the insert - so `created` is the flag that actually matters.
    succeeded = result.status == "success" and output.get("created")

    if succeeded:
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
        if result.error:
            print(f"\nError: {result.error}")

        if output.get('message'):
            print(f"\nDetails: {output['message']}")

        if output.get('reasoning'):
            print(f"\n🧠 Reasoning ({len(output['reasoning'])} steps):")
            for i, step in enumerate(output['reasoning'], 1):
                print(f"   {i}. {step}")

        from claude.clients import config

        print("\n📋 Setup Options:")
        print("\n1. Use gcloud ADC (no credential files needed):")
        print(f"   {config.ADC_LOGIN_COMMAND}")
        print("\n2. Use OAuth Desktop App:")
        print("   - Download credentials.json from Google Cloud")
        print(f"   - Place at {config.CREDENTIALS_FILE}")
        print("   - First run will open browser for consent")
        print(f"   - Token cached at {config.TOKEN_FILE}")
        print("\n3. Use Service Account:")
        print("   - Create service account in Google Cloud")
        print("   - Share calendar with service account email")
        print(f"   - Place JSON key at {config.SERVICE_ACCOUNT_FILE}")
        print("\nSee .claude/clients/SETUP.md for details.")

    print("\n" + "=" * 70 + "\n")
    return bool(succeeded)


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252, which cannot encode the status emoji."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover - non-reconfigurable stream
            pass


def main():
    """Main entry point."""
    _force_utf8_stdout()

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
        succeeded = print_result(result)
        # Non-zero on failure so callers (slash command, scripts) can branch on it.
        sys.exit(0 if succeeded else 1)
    except KeyboardInterrupt:
        print("\n⚠️  Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

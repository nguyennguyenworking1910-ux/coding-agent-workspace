---
description: Schedule a task on Google Calendar via Claude AI
argument-hint: <request, e.g. "trình ký GLX appendix 28 today 30 mins">
allowed-tools: mcp__claude_ai_Google_Calendar__*
---

Schedule the user's request directly on their Google Calendar using Claude AI's native integration.

**Request:** $ARGUMENTS

## What to do

1. If the request above is empty, ask what they want scheduled and stop.

2. Parse the request to extract:
   - **Event title** (the task name, in any language)
   - **Date** (today, tomorrow, a specific day, or "ASAP")
   - **Time** (e.g., "5pm", "afternoon", or omit for flexible timing)
   - **Duration** (e.g., "30 mins", "1 hour", "~2 hours", or estimate 30 mins if not specified)

3. Calculate the start and end times in ISO 8601 format (e.g., `2026-08-08T17:00:00Z`):
   - Use the user's timezone: **Asia/Ho_Chi_Minh**
   - If no specific time given, pick a reasonable slot (e.g., morning or afternoon)

4. Check for calendar conflicts:
   - Call `mcp__claude_ai_Google_Calendar__list_events` with the calculated date range
   - If conflicts exist, report them and ask the user to pick a different time, OR offer an alternative slot

5. Create the event:
   - Call `mcp__claude_ai_Google_Calendar__create_event` with:
     - `summary`: the event title (preserve user's language)
     - `startTime` and `endTime`: ISO 8601 times
     - `timeZone`: "Asia/Ho_Chi_Minh"
     - `description`: optional (e.g., original request text for reference)

6. Report the outcome:
   - **Success** — confirm event created with title, date, time, duration, and calendar link
   - **Failure** — explain what went wrong clearly and suggest next steps

## Example flows

### English request:
**User input:** "schedule team sync tomorrow 2pm 1 hour"
1. Parse: title="team sync", date=tomorrow, time=2pm, duration=1 hour
2. Check conflicts for tomorrow 2pm–3pm
3. Create event on calendar
4. Report: ✅ "Team sync scheduled for [date] 2:00 PM–3:00 PM"

### Vietnamese request:
**User input:** "trình ký GLX appendix 28 today 30 mins"
1. Parse: title="trình ký GLX appendix 28", date=today, duration=30 mins
2. Pick reasonable time (e.g., 3pm if not specified)
3. Check conflicts
4. Create event (preserve Vietnamese title)
5. Report: ✅ "trình ký GLX appendix 28 scheduled for [date] 3:00 PM–3:30 PM"

## Handling edge cases

- **No time specified**: suggest a time based on calendar availability (morning/afternoon slots)
- **Conflicting time**: show conflicts and ask user to choose alternative or override
- **Vague duration**: estimate 30 mins for short tasks, 1–2 hours for longer ones
- **Relative dates**: "ASAP" = today ASAP or tomorrow morning, "before Friday" = earliest available slot before Friday

## Notes

- No local credentials needed — uses Claude AI's native Google Calendar integration
- Supports both English and Vietnamese (or any language) in the event title
- Respects the user's timezone: Asia/Ho_Chi_Minh (adjust in code if different)

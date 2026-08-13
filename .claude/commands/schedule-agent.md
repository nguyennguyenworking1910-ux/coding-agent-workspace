---
description: Schedule a task on Google Calendar via the scheduler subagent
argument-hint: <request, e.g. "trình ký GLX appendix 28 today 30 mins">
allowed-tools: Agent
---

Schedule the user's request on their Google Calendar by dispatching the `scheduler` subagent.

**Request:** $ARGUMENTS

## What to do

1. If the request above is empty, ask what they want scheduled and stop.

2. Read the request well enough to confirm it, extracting:
   - **Event title** (the task name, in any language — keep the user's exact wording)
   - **Date** (today, tomorrow, a specific day, or "ASAP")
   - **Time** (e.g. "5pm", "afternoon", or omit for flexible timing)
   - **Duration** (e.g. "30 mins", "1 hour", or estimate 30 mins if not specified)

   Do not compute the slot yourself and do not touch the calendar yourself. That is the
   subagent's job, and it has the tools for it.

3. **Confirm before dispatching.** A calendar event is an external write, so state what is
   about to be booked — title, date, time, duration — and wait for the user to agree. Do not
   dispatch on an assumption.

4. Dispatch the subagent with the Agent tool: `subagent_type: "scheduler"`. Pass the request
   through as the prompt, keeping the user's original wording, and include:
   - the timezone **Asia/Ho_Chi_Minh**
   - today's date, if you already know it, so nothing lands in the past
   - any detail the user settled during confirmation (a fixed time, a shifted day)

   One dispatch. If it fails, report the failure — do not dispatch again, because a retry that
   half-succeeded the first time leaves a duplicate event.

5. Report the outcome. The subagent's report is not shown to the user, so relay it:
   - **Success** — confirm the event title, date, time, duration, and link if one came back
   - **Failure** — say what went wrong in the subagent's own terms and what to do next

   Report only what the subagent actually confirmed. If it did not say the event was created,
   it was not created, however far its reasoning got.

## How the scheduler reaches the calendar

The `scheduler` subagent has `Read` and `Bash`, and schedules by running the local entry point:

```
python .claude/schedule.py "<request>"
```

That path uses the Google Calendar REST API and **requires local credentials**. If the subagent
reports an authentication or setup failure, pass the message on — the fix is in
`.claude/documents/SETUP.md`, and `.claude/documents/SCHEDULE_CLI.md` walks through the
specific errors. Do not work around it by reaching for calendar tools yourself.

## Example flows

### English request

**User input:** "schedule team sync tomorrow 2pm 1 hour"

1. Read: title="team sync", date=tomorrow, time=2pm, duration=1 hour
2. Confirm: "Booking *team sync* tomorrow 14:00–15:00 (1h), Asia/Ho_Chi_Minh — go ahead?"
3. Dispatch `scheduler` with that request once the user agrees
4. Relay: ✅ "Team sync scheduled for [date] 2:00 PM–3:00 PM"

### Vietnamese request

**User input:** "trình ký GLX appendix 28 today 30 mins"

1. Read: title="trình ký GLX appendix 28", date=today, duration=30 mins
2. Confirm the title verbatim, in Vietnamese, and the slot the subagent will be asked for
3. Dispatch `scheduler` once the user agrees
4. Relay: ✅ "trình ký GLX appendix 28 scheduled for [date] 3:00 PM–3:30 PM"

## Handling edge cases

- **No time specified**: let the subagent pick from real availability — it reads the calendar.
  Confirm the day and duration with the user, not an invented clock time.
- **Conflicting time**: the subagent reports conflicts rather than double-booking. Show them and
  ask the user to choose an alternative.
- **Vague duration**: estimate 30 mins for short tasks, 1–2 hours for longer ones, and say which
  you assumed when you confirm.
- **Relative dates**: "ASAP" = the earliest free slot today, or tomorrow morning if today is
  full; "before Friday" = the earliest available slot before Friday.
- **Delete or decline**: out of scope. The scheduler creates and does not remove. Report the
  conflict and ask.

## Notes

- Local credentials **are** required — the subagent runs `.claude/schedule.py`, not a native
  MCP integration
- Supports English, Vietnamese, or any language in the event title, preserved verbatim
- The user's timezone is Asia/Ho_Chi_Minh; pass it explicitly rather than relying on a default
  (the default lives in `.claude/clients/config.py` as `TIMEZONE`)

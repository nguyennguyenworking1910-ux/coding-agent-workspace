# Scheduling

**Status:** Active
**Audience:** Anyone putting something on the calendar, from a session or a shell

There are two ways to schedule, and both end at the same place.

| Path | How | Needs local credentials |
|---|---|---|
| `/schedule-agent <request>` | Dispatches the `scheduler` subagent, which runs the CLI below | **Yes** |
| `python .claude/schedule.py "<request>"` | Google Calendar REST API in `.claude/clients/` | **Yes** |

The `scheduler` subagent has `Read` and `Bash` only — no calendar tools of its own — so
`/schedule-agent` is a wrapper around the entry point, not an alternative to it. Use the slash
command inside a session for the confirmation flow and a relayed summary; use the CLI directly
for scripting, cron, or anything outside a session. Either way, the credential setup in
[SETUP.md](./SETUP.md) has to be done first.

---

## `/schedule-agent`

```
/schedule-agent trình ký GLX appendix 28 today 30 mins
/schedule-agent schedule team sync tomorrow 2pm 1 hour
/schedule-agent book time for planning Friday 2 hours
```

The command reads the title, date, time, and duration out of your request, confirms them with
you, dispatches the `scheduler` subagent once, and relays what came back. It does not touch the
calendar itself — it is defined in `.claude/commands/schedule-agent.md` and is restricted to
the `Agent` tool. The subagent does the slot-finding and the create by running the CLI below.

Any language works, and the event title keeps your original wording — a Vietnamese title stays
Vietnamese.

---

## `python .claude/schedule.py`

```powershell
python .claude/schedule.py "schedule meeting at 5pm today 30 mins"
python .claude/schedule.py "book time for planning Friday 2 hours"
python .claude/schedule.py "trình ký GLX appendix 28 today 30 mins"
```

Pass the whole request as one quoted argument. With no argument it prints usage and exits `1`.

What it prints on success: the event title, date, time, duration, calendar link, and the
numbered reasoning steps the agent took. On failure it prints the error, the reasoning so far,
and the three credential options below.

**Exit codes:** `0` only when an event was actually created; `1` for every other outcome,
including "the agent finished its steps but the calendar rejected the insert". Anything
scripting this should branch on the exit code, not on the presence of output.

The console is forced to UTF-8 by the entry point, so the status glyphs and non-ASCII titles
render correctly on a cp1252 Windows console.

---

## Confirm before creating

**A calendar event is an external write. Confirm the details with the user before creating
it, and never create one on your own initiative.**

This is a policy rule, not a suggestion. In `.claude/agents.json`,
`orchestration.execution_policy` sets `external_write_requires_confirmation: true` and
`max_external_mutation_attempts: 1`; the intent parser raises `requires_confirmation` on a
scheduling request for the same reason. `/solve` stops and asks before dispatching the
scheduler.

In practice:

- State the title, date, start time, and duration you are about to book, and wait.
- One attempt. If the insert fails, report it — do not retry into a duplicate event.
- Report only what the tool or the CLI actually confirmed. If the exit code was non-zero,
  nothing was scheduled, however far the reasoning got.
- Never delete or decline an existing event. If a request seems to need that, report the
  conflict and ask.
- If the requested window is fully booked, propose the nearest alternatives rather than
  forcing an overlap.

Scheduling heuristics, for when the request is vague: 30 minutes for a short task, 1–2 hours
for a longer one; working hours 09:00–18:00; mornings (09:00–12:00) preferred for complex
work; "ASAP" means the earliest free slot today, or tomorrow morning if today is full.

---

## Timezone

Everything is **Asia/Ho_Chi_Minh** (UTC+7, no DST).

- The CLI passes it explicitly on every request; `.claude/schedule.py` sends
  `{"timezone": "Asia/Ho_Chi_Minh"}` with the task.
- The default lives in `.claude/clients/config.py` as `TIMEZONE`, overridable with the
  `CALENDAR_TIMEZONE` environment variable.
- `/schedule-agent` states it explicitly in the prompt it hands the subagent rather than
  relying on a default.
- `agents.json` records it on the scheduler's `calendar_access.timezone`.

Never rely on an implicit default. A missing timezone is how an event lands seven hours off.
State the zone in any time you report back, and remember the target calendar may have a
different one set in Google Calendar — the explicit value wins.

The target calendar is `GOOGLE_CALENDAR_ID`, default `primary`.

---

## Credential troubleshooting

Both paths need credentials, since both end at the CLI. Full setup, including the resolution
order, is in [SETUP.md](./SETUP.md); this is what to do when a specific message appears.

### `No credentials found` / the setup options block

The CLI prints the three accepted paths. The quickest is gcloud ADC:

```powershell
gcloud auth application-default login --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/calendar
```

The other two: a Desktop OAuth app (`credentials.json` in `.claude/clients/`, first run opens a
browser and caches `token.json`), or a service account (`service_account.json`, and the
calendar must be shared with the service-account email — a service account has no calendar of
its own, so a "successful" run against an unshared calendar writes somewhere you cannot see).

### `403 insufficient authentication scopes`

You ran plain `gcloud auth application-default login`, which grants cloud-platform scopes
only. Credentials resolve fine and then every Calendar call fails. Re-run the scoped command
above — the client detects this case and prints it for you.

### It authenticates as the wrong account, or ignores your fresh `gcloud` login

`token.json` is tried **first**, ahead of ADC. A stale cached token silently wins. Delete it:

```powershell
Remove-Item .claude\clients\token.json
```

### `Warning: token.json is invalid` / `credentials.json flow failed`

The client warns and falls through to the next source rather than stopping. If it eventually
fails, the warning names which file to fix. A corrupt `token.json` is safe to delete; it is a
cache.

### `404` on the calendar

`GOOGLE_CALENDAR_ID` points at a calendar the authenticated account cannot see. Unset it to
fall back to `primary`, or share the calendar with that account.

### `ModuleNotFoundError: No module named 'claude'`

Not a credential problem — the package is not installed. Activate `.venv` and run
`pip install -e .` (see [SETUP.md](./SETUP.md)).

---

## Related documentation

- [SETUP.md](./SETUP.md) — Python environment, ADC, and the credential resolution order
- [ARCHITECTURE.md](./ARCHITECTURE.md) — why the scheduler is the one Python agent in the repo
- [BIGQUERY_INTEGRATION.md](./BIGQUERY_INTEGRATION.md) — the other standalone CLI, same
  package-loading pattern

---

**Last Updated:** August 13, 2026

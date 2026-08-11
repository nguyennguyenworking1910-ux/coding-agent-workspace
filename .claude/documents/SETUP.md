# Scheduler Agent - Google Calendar Integration

The SchedulerAgent manages your Google Calendar using plain English requests.

## Quick Start

### 1. Set Up Google Calendar API

Credentials are resolved in this order, and the first one that works wins:

| # | Source | Location |
|---|--------|----------|
| 1 | Cached OAuth token | `.claude/clients/token.json` |
| 2 | Desktop OAuth app | `.claude/clients/credentials.json` |
| 3 | Service account | `.claude/clients/service_account.json` |
| 4 | gcloud ADC | `~/AppData/Roaming/gcloud/application_default_credentials.json` |

All paths are anchored at `.claude/clients/`, so they resolve identically no matter
which directory you launch the agent from. Override any of them via `.env`
(see `.env.example`).

#### Option A: gcloud ADC — no credential files needed (Recommended)

If you already use the gcloud CLI, the agent needs no JSON files at all. But the
Calendar scope must be granted explicitly — a plain
`gcloud auth application-default login` only carries cloud-platform scopes and the
Calendar API will reject it with **403 insufficient authentication scopes**.

```bash
gcloud auth application-default login \
  --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/calendar
```

Verify it worked:

```python
from claude.clients import GoogleCalendarClient
print(GoogleCalendarClient().verify_access())
# {'ok': True, 'auth_source': 'adc'}
```

> On Windows, `gcloud` may not be on `PATH`. It ships at
> `%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd`.

#### Option B: OAuth2 Desktop App

1. **Create a Google Cloud Project**
   ```
   https://console.cloud.google.com
   ```

2. **Enable Google Calendar API**
   - Go to APIs & Services → Library
   - Search for "Google Calendar API"
   - Click "Enable"

3. **Create OAuth2 Credentials**
   - Go to APIs & Services → Credentials
   - Click "Create Credentials" → "OAuth 2.0 Desktop Application"
   - Download the JSON file
   - Rename to `credentials.json` in `.claude/clients/`

4. **First-time Authentication**
   ```python
   from claude.clients import GoogleCalendarClient

   # This will open a browser for OAuth consent
   client = GoogleCalendarClient()

   # Token is cached in .claude/clients/token.json for future runs
   ```

#### Option C: Service Account (For Automation)

1. **Create Service Account**
   - Go to APIs & Services → Credentials
   - Click "Create Credentials" → "Service Account"
   - Create a key (JSON format)
   - Rename to `service_account.json` in `.claude/clients/`

2. **Share Calendar with Service Account**
   - Copy the service account email
   - Go to Google Calendar settings
   - Share your calendar with that email

### 2. Install Dependencies

```bash
pip install -r .claude/agents/requirements.txt
```

### 3. Configure Environment (optional)

Every setting has a working default; you only need `.env` to override one.

```bash
cp .claude/clients/.env.example .claude/clients/.env
```

```env
GOOGLE_CALENDAR_ID=primary
CALENDAR_TIMEZONE=Asia/Ho_Chi_Minh

# Point at credential files elsewhere (relative paths resolve against .claude/clients/)
# GOOGLE_CALENDAR_CREDENTIALS=credentials.json
# GOOGLE_CALENDAR_TOKEN=token.json
# GOOGLE_CALENDAR_SERVICE_ACCOUNT=service_account.json
```

Loading `.env` requires `python-dotenv`; without it the defaults and real environment
variables still apply.

## Usage

### Via SchedulerAgent

```python
from claude.agents import get_agent

scheduler = get_agent("scheduler")

# Schedule a task
result = await scheduler.execute({
    "request": "Schedule 'GLX Appendix 28 signing' at 5 pm today for 30 minutes",
    "timezone": "Asia/Ho_Chi_Minh",
})

print(result.output)
```

### Direct Tool Usage

```python
from claude.agents.team.scheduler_tools import SCHEDULER_TOOLS

# Get today
today = SCHEDULER_TOOLS["get_today"]()

# Check availability
availability = SCHEDULER_TOOLS["check_availability"](
    start_date="2026-08-07",
    end_date="2026-08-07",
    duration_minutes=30
)

# Create event
event = SCHEDULER_TOOLS["create_event"](
    summary="GLX Appendix 28 signing",
    start_datetime="2026-08-07T17:00:00",
    duration_minutes=30
)
```

## Supported Requests

The agent understands natural language scheduling:

- "Schedule finishing the Q3 report by Friday, ~3 hours"
- "Book time for X before next Tuesday"
- "Add a 90-minute deep work block tomorrow 2pm"
- "Schedule 'GLX Appendix 28 signing' at 5 pm today for 30 minutes"
- "What's on my schedule this week?"

## Tool Reference

### `get_today()`
Returns current date, time, and weekday.

### `check_availability(start_date, end_date, duration_minutes)`
Finds free time slots in the specified date range.

**Parameters:**
- `start_date`: YYYY-MM-DD format
- `end_date`: YYYY-MM-DD format
- `duration_minutes`: Required duration

**Returns:**
- `events`: Existing events in the range
- `free_slots`: Available time slots
- `total_free_slots`: Number of available slots

### `create_event(summary, start_datetime, duration_minutes, description="")`
Creates a calendar event.

**Parameters:**
- `summary`: Event title
- `start_datetime`: ISO 8601 format (e.g., "2026-08-07T17:00:00")
- `duration_minutes`: Duration in minutes
- `description`: Optional event description
- `force`: Override conflicts (default: False)

**Returns:**
- `created`: Boolean success flag
- `event`: Event details if created
- `conflicts`: List of conflicting events if applicable

## Features

✅ **Conflict Detection** - Won't double-book over existing events
✅ **Smart Slot Selection** - Prefers morning hours for complex tasks
✅ **Timezone Support** - Respects your timezone settings
✅ **Plain English Parsing** - Understands natural language durations and times
✅ **Google Calendar Integration** - Direct API access to your calendar
✅ **Token Caching** - OAuth tokens cached for subsequent runs

## Troubleshooting

### "Insufficient authentication scopes" / 403 Error

The most common failure when running on gcloud ADC. You are authenticated, but the
token was never granted the Calendar scope. Fix:

```bash
gcloud auth application-default login \
  --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/calendar
```

`verify_access()` reports this explicitly rather than letting the raw 403 surface:

```python
from claude.clients import GoogleCalendarClient
GoogleCalendarClient().verify_access()
```

### "No credentials found" Error

All four sources came up empty. Either run the gcloud command above, or place one of
these in `.claude/clients/`:
- `credentials.json` (OAuth2 Desktop app)
- `service_account.json` (Service Account)
- `token.json` (Cached OAuth token)

### "Calendar client not initialized" Warning

Check that Google Calendar API is enabled in Cloud Console and you have proper permissions.

### "Conflict detected" on Valid Slots

The agent checks a 30-minute buffer. Adjust the time or use `force=true`.

## Architecture

```
.claude/
├── agents/
│   ├── team/scheduler.py                 # Main agent logic
│   └── tools/scheduler/scheduler_tools.py # Tool implementations
└── clients/
    ├── config.py            # Credential paths + calendar settings (env-driven)
    ├── calendar_client.py   # Google Calendar API wrapper
    ├── .env                 # Optional overrides (gitignored)
    └── credentials.json     # Optional — ADC works without it (gitignored)
```

## Team Integration

Inside a Claude Code session the Scheduler is one of seven subagents, defined in
`.claude/agents/scheduler.md`. It uses the native Google Calendar MCP integration, so it needs
none of the credentials on this page. Dispatch it by asking, or through `/solve`; or use the
`/schedule-agent` command directly.

The credentials described here are only for the standalone path, which runs outside a session:

```bash
python .claude/schedule.py "schedule planning session tomorrow 2 hours"
```

```python
# Or from your own script
from claude.agents import get_agent

scheduler = get_agent("scheduler")
result = await scheduler.execute({"request": "book 30 mins today", "timezone": "Asia/Ho_Chi_Minh"})
```

The full subagent roster:
- reviewer (code review)
- red-team (security testing)
- bug-fixer (issue resolution)
- diagnostician (system analysis)
- coder (implementation)
- group-sales-manager (sales data, resource allocation)
- **scheduler** (calendar management)

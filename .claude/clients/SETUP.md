# Scheduler Agent - Google Calendar Integration

The SchedulerAgent manages your Google Calendar using plain English requests.

## Quick Start

### 1. Set Up Google Calendar API

#### Option A: OAuth2 Desktop App (Recommended)

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
   - Rename to `credentials.json` in `.claude/agents/team/`

4. **First-time Authentication**
   ```python
   from claude.agents.team.calendar_client import GoogleCalendarClient
   
   # This will open a browser for OAuth consent
   client = GoogleCalendarClient()
   
   # Token is cached in token.json for future runs
   ```

#### Option B: Service Account (For Automation)

1. **Create Service Account**
   - Go to APIs & Services → Credentials
   - Click "Create Credentials" → "Service Account"
   - Create a key (JSON format)
   - Rename to `service_account.json` in `.claude/agents/team/`

2. **Share Calendar with Service Account**
   - Copy the service account email
   - Go to Google Calendar settings
   - Share your calendar with that email

### 2. Install Dependencies

```bash
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

### 3. Configure Environment

Copy `.env.example` to `.env`:

```bash
cp .claude/agents/team/.env.example .claude/agents/team/.env
```

Edit `.env` if needed:
```env
GOOGLE_CALENDAR_ID=primary
CALENDAR_TIMEZONE=Asia/Ho_Chi_Minh
```

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

### "No credentials found" Error

Ensure one of these files exists in `.claude/agents/team/`:
- `credentials.json` (OAuth2)
- `service_account.json` (Service Account)
- `token.json` (Cached OAuth token)

### "Calendar client not initialized" Warning

Check that Google Calendar API is enabled in Cloud Console and you have proper permissions.

### "Conflict detected" on Valid Slots

The agent checks a 30-minute buffer. Adjust the time or use `force=true`.

## Architecture

```
SchedulerAgent
├── scheduler.py          # Main agent logic
├── calendar_client.py    # Google Calendar API wrapper
├── scheduler_tools.py    # Tool implementations
└── credentials.json      # OAuth2 credentials
```

## Team Integration

The SchedulerAgent is part of the multi-agent team:

```python
from claude.agents import TeamLeaderAgent

leader = TeamLeaderAgent()
scheduler = leader.teammates["scheduler"]
```

Available agents:
- reviewer (code review)
- red_team (security testing)
- bug_fixer (issue resolution)
- diagnostician (system analysis)
- coder (implementation)
- group_sales_manager (resource allocation)
- **scheduler** (calendar management)

# Schedule CLI - Claude Code Integration

Use the Scheduler Agent directly from Claude Code CLI without local credentials.

## Quick Start

### 1. One-Time Setup (Choose One)

#### Option A: gcloud CLI (Recommended - System-wide)
```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/calendar
```
This grants your system access to Google Calendar. Done once, works everywhere.

#### Option B: OAuth Desktop App (Local token cache)
1. Download `credentials.json` from Google Cloud Console
2. Place in `.claude/clients/credentials.json`
3. First run will open browser for consent
4. Token cached in `token.json` for future runs

#### Option C: Service Account (Automation)
1. Create service account in Google Cloud
2. Download JSON key
3. Place in `.claude/clients/service_account.json`
4. Share your calendar with service account email

### 2. Install Dependencies
```bash
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dateutil
```

### 3. Schedule Tasks

From Claude Code CLI:
```bash
python .claude/schedule.py "schedule meeting at 5pm today 30 mins"
python .claude/schedule.py "trình ký GLX appendix 28 30 mins"
python .claude/schedule.py "book time Friday afternoon 2 hours"
```

## Usage Examples

### English Requests
```bash
python .claude/schedule.py "schedule finishing the Q3 report by Friday, ~3 hours"
python .claude/schedule.py "add a 90-minute deep work block tomorrow 2pm"
python .claude/schedule.py "book time for planning before next Tuesday"
```

### Vietnamese Requests
```bash
python .claude/schedule.py "lịch họp hôm nay 3pm 1 tiếng"
python .claude/schedule.py "trình ký GLX appendix 28 today 30 mins"
```

### Time Specifications
- **Today**: "at 5pm today", "tomorrow 2pm", "Friday afternoon"
- **Duration**: "30 mins", "1 hour", "2 hours", "~3 hours"
- **Specificity**: "as soon as possible", "before Tuesday", "by Friday"

## Output Example

```
======================================================================
✅ TASK SCHEDULED SUCCESSFULLY
======================================================================

📌 Event Details:
   Task:     trình ký GLX appendix 28
   Date:     2026-08-07 (Thursday)
   Time:     17:00-17:30
   Duration: 30 minutes
   Link:     https://calendar.google.com/event?eid=...

🧠 Reasoning (4 steps):
   1. Analyzing request
   2. Extracting duration and time
   3. Checking calendar availability
   4. Creating event successfully

📝 Event created and synced to Google Calendar
======================================================================
```

## Troubleshooting

### "No credentials found"
Set up one of the three options above. The system checks:
1. `token.json` - Cached OAuth token
2. `credentials.json` - Desktop OAuth app
3. `service_account.json` - Service account
4. gcloud ADC - System-wide credentials

### "gcloud ADC not found"
Install Google Cloud SDK: https://cloud.google.com/sdk/docs/install

### "credentials.json not found"
Download from Google Cloud Console → APIs & Services → Credentials → Create OAuth 2.0 Desktop Application

## Architecture

```
Claude Code CLI
    ↓
.claude/schedule.py (CLI wrapper)
    ↓
SchedulerAgent (from claude.agents)
    ↓
scheduler_tools (5 tools)
    ↓
GoogleCalendarClient (smart credential resolution)
    ↓
Google Calendar API
    ↓
Your Calendar ✓
```

## Integration with Claude Code

This script can be called from:
- Claude Code CLI: `python .claude/schedule.py "..."`
- Python code: `exec(open('.claude/schedule.py').read())`
- As a module: `from claude.agents import get_agent`
- In scripts or automation

## Next Steps

1. Choose credential setup option (A, B, or C)
2. Run: `pip install -r .claude/agents/requirements.txt`
3. Schedule your first task: `python .claude/schedule.py "test task today 30 mins"`
4. Check Google Calendar for the scheduled event!

---

No Codex needed. Pure Claude Code CLI + your Google Calendar. 🚀

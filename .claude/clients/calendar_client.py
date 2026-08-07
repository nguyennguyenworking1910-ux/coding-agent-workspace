"""Google Calendar API client for the Scheduler Agent.

Uses the same credential resolution order as workspace/schedule-management-agent:
1. token.json (cached OAuth token - auto-refresh if expired)
2. credentials.json (Desktop OAuth app - initiates consent flow)
3. service_account.json (Service account with shared calendar)
4. gcloud ADC (Application Default Credentials - if gcloud CLI configured)

Step 4 is what lets the agent run with no credential files at all. Note that plain
`gcloud auth application-default login` does NOT grant the Calendar scope; see
`config.ADC_LOGIN_COMMAND`. Credentials come back fine in that case and only fail
later with an opaque 403, so scope failures are translated into an actionable
message rather than surfacing raw.
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import json

from . import config

try:
    from google.auth.transport.requests import Request
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google.oauth2.credentials import Credentials as OAuth2Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


def _is_scope_error(exc: Exception) -> bool:
    """True if `exc` looks like Google rejecting the token's granted scopes."""
    text = str(exc).lower()
    return "insufficient" in text and ("scope" in text or "permission" in text)


def _scope_help(auth_source: str) -> str:
    """Actionable guidance for a 403-insufficient-scopes failure.

    Kept to two lines: this can surface several times in one run, and the full
    setup walkthrough lives in .claude/clients/SETUP.md.
    """
    if auth_source == "adc":
        return (
            "gcloud ADC lacks the Google Calendar scope (403). Re-authorize with:\n"
            f"  {config.ADC_LOGIN_COMMAND}"
        )
    return (
        "The credentials in use were not granted the Google Calendar scope "
        f"({config.SCOPES[0]}). Re-authorize with that scope included."
    )


class GoogleCalendarClient:
    """Client for Google Calendar API operations.

    Smart credential resolution - tries multiple auth methods in order:
    1. Cached token.json (OAuth Desktop app)
    2. credentials.json (OAuth Desktop app consent flow)
    3. service_account.json (Service account)
    4. gcloud ADC (Application Default Credentials)
    """

    SCOPES = config.SCOPES

    def __init__(
        self,
        calendar_id: Optional[str] = None,
        timezone: Optional[str] = None,
    ):
        """Initialize Google Calendar client.

        Args:
            calendar_id: Calendar ID (defaults to config.CALENDAR_ID / env)
            timezone: Timezone for calendar operations (defaults to config.TIMEZONE / env)
        """
        self.calendar_id = calendar_id or config.CALENDAR_ID
        self.timezone = timezone or config.TIMEZONE
        self.service = None
        # Which of the four sources actually produced credentials; used to tailor
        # the guidance when the API later rejects the token's scopes.
        self.auth_source: Optional[str] = None
        # A single scheduling run hits the API several times; without this the same
        # multi-line guidance would be printed once per call.
        self._warned: set = set()
        self._authenticate()

    def _get_credentials(self):
        """Get valid credentials using smart resolution order."""
        if not GOOGLE_API_AVAILABLE:
            raise ImportError(
                "Google API client libraries not installed.\n"
                "Run: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client"
            )

        # 1. Try cached OAuth token (fastest path)
        if config.TOKEN_FILE.exists():
            try:
                credentials = OAuth2Credentials.from_authorized_user_file(
                    str(config.TOKEN_FILE),
                    scopes=self.SCOPES
                )
                if credentials and credentials.valid:
                    self.auth_source = "token"
                    return credentials
                if credentials and credentials.expired and credentials.refresh_token:
                    credentials.refresh(Request())
                    # Update cached token
                    config.TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
                    self.auth_source = "token"
                    return credentials
            except Exception as e:
                print(f"Warning: {config.TOKEN_FILE.name} is invalid: {e}")

        # 2. Try Desktop OAuth app (credentials.json)
        if config.CREDENTIALS_FILE.exists():
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(config.CREDENTIALS_FILE),
                    scopes=self.SCOPES
                )
                # port=0 lets the OS pick a free port for the local consent redirect.
                credentials = flow.run_local_server(port=0)
                # Cache token for next run
                config.TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
                self.auth_source = "credentials"
                return credentials
            except Exception as e:
                print(f"Warning: {config.CREDENTIALS_FILE.name} flow failed: {e}")

        # 3. Try service account
        if config.SERVICE_ACCOUNT_FILE.exists():
            try:
                credentials = ServiceAccountCredentials.from_service_account_file(
                    str(config.SERVICE_ACCOUNT_FILE),
                    scopes=self.SCOPES
                )
                self.auth_source = "service_account"
                return credentials
            except Exception as e:
                print(f"Warning: {config.SERVICE_ACCOUNT_FILE.name} failed: {e}")

        # 4. Try gcloud Application Default Credentials.
        # This is the "no credential files needed" path. It succeeds whenever gcloud
        # is logged in - the Calendar scope is only checked server-side, on first call.
        try:
            credentials, _ = google.auth.default(scopes=self.SCOPES)
            self.auth_source = "adc"
            return credentials
        except DefaultCredentialsError:
            pass

        # No credentials found
        raise FileNotFoundError(
            "No Google Calendar credentials found.\n\n"
            "Credential resolution order (tried in this order):\n"
            f"1. {config.TOKEN_FILE} - Cached OAuth token (auto-refresh)\n"
            f"2. {config.CREDENTIALS_FILE} - Desktop OAuth app consent flow\n"
            f"3. {config.SERVICE_ACCOUNT_FILE} - Service account with shared calendar\n"
            "4. gcloud ADC - Application Default Credentials\n\n"
            "Options to set up:\n"
            "A. gcloud CLI (no credential files needed):\n"
            f"   {config.ADC_LOGIN_COMMAND}\n\n"
            "B. OAuth Desktop App:\n"
            "   - Create in Google Cloud Console\n"
            f"   - Download credentials.json to {config.BASE_DIR}\n"
            "   - First run will prompt for browser consent\n\n"
            "C. Service Account (Automation):\n"
            "   - Create service account in Google Cloud\n"
            f"   - Download JSON key to {config.SERVICE_ACCOUNT_FILE}\n"
            "   - Share calendar with service account email\n\n"
            "See .claude/clients/SETUP.md for detailed instructions."
        )

    def _authenticate(self) -> None:
        """Authenticate with Google Calendar API."""
        try:
            credentials = self._get_credentials()
            self.service = build("calendar", "v3", credentials=credentials)
        except Exception as e:
            raise RuntimeError(f"Google Calendar authentication failed: {e}")

    def _describe_error(self, exc: Exception) -> str:
        """Render an API error, expanding scope rejections into a fix."""
        if _is_scope_error(exc):
            return _scope_help(self.auth_source or "unknown")
        return str(exc)

    def _warn(self, prefix: str, exc: Exception) -> None:
        """Print an API warning, printing any given explanation only once."""
        message = self._describe_error(exc)
        if message in self._warned:
            first_line = message.splitlines()[0]
            print(f"{prefix}: {first_line} (see above)")
            return
        self._warned.add(message)
        print(f"{prefix}: {message}")

    def verify_access(self) -> Dict[str, Any]:
        """Cheaply confirm the resolved credentials can actually reach Calendar.

        Returns a dict with `ok`, the `auth_source` that was used, and on failure a
        human-readable `error` (with the gcloud fix when scopes are the problem).
        """
        result: Dict[str, Any] = {"ok": False, "auth_source": self.auth_source}
        if not self.service:
            result["error"] = "Calendar client not initialized"
            return result
        try:
            self.service.calendarList().list(maxResults=1).execute()
            result["ok"] = True
            return result
        except Exception as e:
            result["error"] = self._describe_error(e)
            return result

    def get_today(self) -> Dict[str, Any]:
        """Get today's date and day of week.

        Returns:
            Dict with date, weekday, and timezone info
        """
        today = datetime.now()
        return {
            "date": today.strftime("%Y-%m-%d"),
            "weekday": today.strftime("%A"),
            "time": today.strftime("%H:%M:%S"),
            "timezone": self.timezone,
        }

    def get_events(
        self,
        start_date: str,
        end_date: str,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """Get calendar events within a date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_results: Maximum number of results

        Returns:
            List of events with details
        """
        if not self.service:
            return []

        try:
            # Parse dates and add time
            start_dt = datetime.fromisoformat(f"{start_date}T00:00:00")
            end_dt = datetime.fromisoformat(f"{end_date}T23:59:59")

            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_dt.isoformat() + "Z",
                timeMax=end_dt.isoformat() + "Z",
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = events_result.get("items", [])
            return [
                {
                    "id": event.get("id"),
                    "summary": event.get("summary", "Busy"),
                    "start": event.get("start", {}).get("dateTime", event.get("start", {}).get("date")),
                    "end": event.get("end", {}).get("dateTime", event.get("end", {}).get("date")),
                    "description": event.get("description", ""),
                }
                for event in events
            ]
        except Exception as e:
            self._warn("Error fetching events", e)
            return []

    def find_free_slots(
        self,
        start_date: str,
        end_date: str,
        duration_minutes: int,
        preferred_start_hour: int = 9,
        preferred_end_hour: int = 18,
    ) -> List[Dict[str, Any]]:
        """Find free time slots in the calendar.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            duration_minutes: Required duration
            preferred_start_hour: Preferred work start hour
            preferred_end_hour: Preferred work end hour

        Returns:
            List of available time slots
        """
        events = self.get_events(start_date, end_date)

        free_slots = []
        current_date = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        while current_date <= end:
            date_str = current_date.strftime("%Y-%m-%d")

            # Check each hour during working hours
            for hour in range(preferred_start_hour, preferred_end_hour):
                slot_start = datetime.fromisoformat(f"{date_str}T{hour:02d}:00:00")
                slot_end = slot_start + timedelta(minutes=duration_minutes)

                # Check if slot conflicts with existing events
                is_free = True
                for event in events:
                    event_start = datetime.fromisoformat(event["start"].replace("Z", "+00:00")).replace(tzinfo=None)
                    event_end = datetime.fromisoformat(event["end"].replace("Z", "+00:00")).replace(tzinfo=None)

                    # Check for overlap
                    if not (slot_end <= event_start or slot_start >= event_end):
                        is_free = False
                        break

                if is_free:
                    free_slots.append(
                        {
                            "start": slot_start.isoformat(),
                            "end": slot_end.isoformat(),
                            "duration_minutes": duration_minutes,
                            "date": date_str,
                            "time": f"{hour:02d}:00",
                        }
                    )

            current_date += timedelta(days=1)

        return free_slots

    def create_event(
        self,
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
            force: Force creation even if there's a conflict

        Returns:
            Dict with creation status and event details
        """
        if not self.service:
            return {"created": False, "reason": "Calendar client not initialized"}

        try:
            start_dt = datetime.fromisoformat(start_datetime)
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            # Check for conflicts
            events = self.get_events(
                start_dt.strftime("%Y-%m-%d"),
                end_dt.strftime("%Y-%m-%d")
            )

            conflicts = []
            for event in events:
                event_start = datetime.fromisoformat(event["start"].replace("Z", "+00:00")).replace(tzinfo=None)
                event_end = datetime.fromisoformat(event["end"].replace("Z", "+00:00")).replace(tzinfo=None)

                # Check for overlap
                if not (end_dt <= event_start or start_dt >= event_end):
                    conflicts.append(event)

            if conflicts and not force:
                return {
                    "created": False,
                    "reason": "conflict",
                    "conflicts": conflicts,
                    "message": f"Found {len(conflicts)} conflicting event(s). Set force=true to override.",
                }

            # Create event
            event = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": self.timezone},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": self.timezone},
            }

            created_event = self.service.events().insert(
                calendarId=self.calendar_id,
                body=event
            ).execute()

            return {
                "created": True,
                "event": {
                    "id": created_event.get("id"),
                    "summary": created_event.get("summary"),
                    "start": created_event.get("start", {}).get("dateTime"),
                    "end": created_event.get("end", {}).get("dateTime"),
                    "duration_minutes": duration_minutes,
                    "htmlLink": created_event.get("htmlLink"),
                    "date": start_dt.strftime("%Y-%m-%d"),
                    "time": f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}",
                },
            }
        except Exception as e:
            return {
                "created": False,
                "reason": "error",
                "error": self._describe_error(e),
            }

    def list_calendars(self) -> List[Dict[str, Any]]:
        """List all accessible calendars.

        Returns:
            List of calendar information
        """
        if not self.service:
            return []

        try:
            result = self.service.calendarList().list().execute()
            calendars = result.get("items", [])
            return [
                {
                    "id": cal.get("id"),
                    "summary": cal.get("summary"),
                    "primary": cal.get("primary", False),
                }
                for cal in calendars
            ]
        except Exception as e:
            self._warn("Error listing calendars", e)
            return []

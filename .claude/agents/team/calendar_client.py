"""Google Calendar API client for the Scheduler Agent."""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import json

try:
    from google.auth.transport.requests import Request
    from google.oauth2.service_account import Credentials
    from google.oauth2.credentials import Credentials as OAuth2Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    import google.auth
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


class GoogleCalendarClient:
    """Client for Google Calendar API operations."""

    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self, calendar_id: str = "primary", timezone: str = "Asia/Ho_Chi_Minh"):
        """Initialize Google Calendar client.

        Args:
            calendar_id: Calendar ID (default: primary/personal calendar)
            timezone: Timezone for calendar operations
        """
        self.calendar_id = calendar_id
        self.timezone = timezone
        self.service = None
        self._authenticate()

    def _authenticate(self) -> None:
        """Authenticate with Google Calendar API."""
        if not GOOGLE_API_AVAILABLE:
            raise ImportError("Google API client libraries not installed. Run: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")

        try:
            # Try service account first
            if os.path.exists("service_account.json"):
                credentials = Credentials.from_service_account_file(
                    "service_account.json",
                    scopes=self.SCOPES
                )
            # Try OAuth2 token cache
            elif os.path.exists("token.json"):
                credentials = OAuth2Credentials.from_authorized_user_file(
                    "token.json",
                    scopes=self.SCOPES
                )
                # Refresh if expired
                if credentials.expired and credentials.refresh_token:
                    credentials.refresh(Request())
            # Try credentials.json (OAuth2 flow)
            elif os.path.exists("credentials.json"):
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json",
                    scopes=self.SCOPES
                )
                credentials = flow.run_local_server(port=0)
                # Save token for next run
                with open("token.json", "w") as token:
                    token.write(credentials.to_json())
            else:
                raise FileNotFoundError(
                    "No credentials found. Place one of: service_account.json, "
                    "credentials.json, or token.json in the project directory."
                )

            self.service = build("calendar", "v3", credentials=credentials)
        except Exception as e:
            raise RuntimeError(f"Google Calendar authentication failed: {e}")

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
            print(f"Error fetching events: {e}")
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
                "error": str(e),
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
            print(f"Error listing calendars: {e}")
            return []

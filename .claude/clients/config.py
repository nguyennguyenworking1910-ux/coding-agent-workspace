"""Central configuration for the Google Calendar client.

Single source of truth for credential paths and calendar settings, so the client,
the scheduler tools, and the agent don't each re-parse the environment.

Paths are anchored at this package directory (not the process working directory),
so credentials resolve the same way no matter where the agent is launched from.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional
    pass

BASE_DIR = Path(__file__).resolve().parent


def _resolve_path(env_name: str, default: Path) -> Path:
    """Resolve a path from the environment; relative values anchor at BASE_DIR."""
    value = os.environ.get(env_name)
    if value:
        p = Path(value)
        return p if p.is_absolute() else BASE_DIR / p
    return default


# --- Google Calendar ---
SCOPES = ["https://www.googleapis.com/auth/calendar"]

CREDENTIALS_FILE = _resolve_path(
    "GOOGLE_CALENDAR_CREDENTIALS", BASE_DIR / "credentials.json"
)
TOKEN_FILE = _resolve_path("GOOGLE_CALENDAR_TOKEN", BASE_DIR / "token.json")
SERVICE_ACCOUNT_FILE = _resolve_path(
    "GOOGLE_CALENDAR_SERVICE_ACCOUNT", BASE_DIR / "service_account.json"
)

CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
TIMEZONE = os.environ.get("CALENDAR_TIMEZONE", "Asia/Ho_Chi_Minh")

# The exact command that grants gcloud ADC the Calendar scope. Plain ADC from
# `gcloud auth application-default login` only carries cloud-platform scopes, which
# the Calendar API rejects with 403 "insufficient authentication scopes".
ADC_LOGIN_COMMAND = (
    "gcloud auth application-default login "
    "--scopes=openid,"
    "https://www.googleapis.com/auth/userinfo.email,"
    "https://www.googleapis.com/auth/calendar"
)

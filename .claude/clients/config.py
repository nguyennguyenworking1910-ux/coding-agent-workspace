"""Central configuration for the external service clients.

Single source of truth for credential paths, calendar settings, and BigQuery
settings, so the clients, the tools, and the agents don't each re-parse the
environment.

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


def _resolve_int(env_name: str, default: int) -> int:
    """Resolve a positive integer from the environment, falling back on junk values.

    A malformed cap must not stop the process from starting - it silently reverts
    to the safe default, which is the smaller of the two behaviours.
    """
    value = os.environ.get(env_name)
    if value:
        try:
            parsed = int(value.strip().replace("_", ""))
            if parsed > 0:
                return parsed
        except ValueError:
            pass
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


# --- BigQuery ---
BIGQUERY_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# Billing/query project. Deliberately allowed to be None: gcloud ADC carries a
# quota project of its own, and the client uses that when this is unset. Only when
# both are missing does the client raise, naming this variable in the message.
BIGQUERY_PROJECT = os.environ.get("BIGQUERY_PROJECT") or None

# Job location. Must match the location of the datasets being queried; a US job
# cannot read an EU dataset. Override per-workspace via the environment.
BIGQUERY_LOCATION = os.environ.get("BIGQUERY_LOCATION", "US")

# Optional service-account key. ADC is the primary path - this file does not need
# to exist, and is only used when it does.
BIGQUERY_SERVICE_ACCOUNT = _resolve_path(
    "BIGQUERY_SERVICE_ACCOUNT", BASE_DIR / "bigquery_service_account.json"
)

# Cost guard. BigQuery kills a job before it runs if it would scan more than this,
# so a runaway `SELECT *` over a partitioned table fails fast instead of billing.
# Default: 10 GiB (10737418240 bytes) ~= USD 0.05 at on-demand pricing.
BIGQUERY_MAX_BYTES_BILLED = _resolve_int("BIGQUERY_MAX_BYTES_BILLED", 10 * 1024**3)

# Context guard. Rows returned to a caller are capped at this, so a wide result set
# cannot flood an agent's context; the tool layer reports when it truncated.
# Default: 1000 rows.
BIGQUERY_MAX_ROWS = _resolve_int("BIGQUERY_MAX_ROWS", 1000)

# Where `.sql` query templates are discovered. Dropping a file in here is all that
# is needed to add a query - see .claude/documents/BIGQUERY_INTEGRATION.md.
BIGQUERY_TEMPLATE_DIR = _resolve_path(
    "BIGQUERY_TEMPLATE_DIR",
    BASE_DIR.parent / "agents" / "tools" / "bigquery" / "templates",
)

# The exact command that grants gcloud ADC the BigQuery scope. Unlike Calendar,
# plain `gcloud auth application-default login` already covers BigQuery - the
# explicit form is spelled out here so the fix in an error message is copy-pasteable.
BIGQUERY_ADC_LOGIN_COMMAND = (
    "gcloud auth application-default login "
    "--scopes=openid,"
    "https://www.googleapis.com/auth/userinfo.email,"
    "https://www.googleapis.com/auth/cloud-platform"
)

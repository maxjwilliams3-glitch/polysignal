"""
Configuration for PolySignal.

Everything tunable lives here or in environment variables. Env vars override the
defaults below, so you can keep secrets (the Slack webhook) out of the source.
The bot auto-loads a .env file in the project root if present (see main.py).
"""
from __future__ import annotations

import os


def _get_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw is not None else default


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw is not None else default


# --- What to watch -----------------------------------------------------------

# Leaderboard window: WEEK or DAY (also accepts MONTH, ALL). WEEK by default —
# daily PnL leaders are noisy/variance-driven; a week surfaces more durable skill.
TIME_PERIOD = _get_str("POLYSIGNAL_TIME_PERIOD", "WEEK")

# Ranking criteria: PNL (profit) or VOL (volume).
ORDER_BY = _get_str("POLYSIGNAL_ORDER_BY", "PNL")

# Category: OVERALL, POLITICS, SPORTS, CRYPTO, CULTURE, MENTIONS, WEATHER,
# ECONOMICS, TECH, FINANCE.
CATEGORY = _get_str("POLYSIGNAL_CATEGORY", "OVERALL")

# How many top traders to track.
TOP_N = _get_int("POLYSIGNAL_TOP_N", 5)

# A position at/above this current USD value counts as "notable".
NOTABLE_USD = _get_float("POLYSIGNAL_NOTABLE_USD", 5000.0)

# Ignore dust below this current USD value.
MIN_POSITION_USD = _get_float("POLYSIGNAL_MIN_POSITION_USD", 100.0)


# --- Quality filter ----------------------------------------------------------
# Only alert on traders with a proven track record. A trader must be net
# profitable AND win at least MIN_WIN_RATE of their (full) closed bets. Traders
# with fewer than MIN_TRACK_RECORD_SAMPLE closed bets are treated as unproven
# and suppressed. Capped records (win-rate unknown) pass on net profit alone.

# Minimum fraction of closed bets won. 0.50 = wins more often than not.
MIN_WIN_RATE = _get_float("POLYSIGNAL_MIN_WIN_RATE", 0.50)

# Need at least this many closed bets before we'll judge (and trust) a record.
MIN_TRACK_RECORD_SAMPLE = _get_int("POLYSIGNAL_MIN_TRACK_RECORD_SAMPLE", 10)


# --- Cadence -----------------------------------------------------------------

# Seconds between polling cycles (foreground loop). 900 = 15 min.
POLL_INTERVAL_SECONDS = _get_int("POLYSIGNAL_POLL_INTERVAL_SECONDS", 900)


# --- Notifications -----------------------------------------------------------

# Slack incoming-webhook URL. REQUIRED for alerts to actually send.
SLACK_WEBHOOK_URL = _get_str("POLYSIGNAL_SLACK_WEBHOOK_URL", "")

# First cycle records a baseline and sends NO alerts. Strongly recommended.
SILENT_FIRST_RUN = os.environ.get("POLYSIGNAL_SILENT_FIRST_RUN", "true").lower() != "false"


# --- Health / failure alerts -------------------------------------------------
# Alert to Slack after this many consecutive failed cycles (3 ≈ 45 min at the
# default 15-min cadence), then once more when it recovers.
FAILURE_ALERT_THRESHOLD = _get_int("POLYSIGNAL_FAILURE_ALERT_THRESHOLD", 3)

# The standalone watchdog alerts if no cycle has succeeded in this many hours.
STALENESS_ALERT_HOURS = _get_int("POLYSIGNAL_STALENESS_ALERT_HOURS", 2)


# --- Storage -----------------------------------------------------------------

DB_PATH = _get_str("POLYSIGNAL_DB_PATH", "polysignal.db")


# --- API ---------------------------------------------------------------------

DATA_API_BASE = "https://data-api.polymarket.com"
HTTP_TIMEOUT_SECONDS = _get_int("POLYSIGNAL_HTTP_TIMEOUT_SECONDS", 20)
HTTP_MAX_RETRIES = _get_int("POLYSIGNAL_HTTP_MAX_RETRIES", 4)


def validate() -> list:
    """Return a list of human-readable problems with the current config."""
    problems = []
    if TIME_PERIOD not in {"DAY", "WEEK", "MONTH", "ALL"}:
        problems.append("TIME_PERIOD=%r is not one of DAY/WEEK/MONTH/ALL" % TIME_PERIOD)
    if ORDER_BY not in {"PNL", "VOL"}:
        problems.append("ORDER_BY=%r is not PNL or VOL" % ORDER_BY)
    if not (1 <= TOP_N <= 50):
        problems.append("TOP_N=%d must be between 1 and 50" % TOP_N)
    if not SLACK_WEBHOOK_URL:
        problems.append("SLACK_WEBHOOK_URL is empty — alerts will be logged but not sent")
    return problems

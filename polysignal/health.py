"""
Health reporting — so the bot can't die silently.

Two failure modes, one shared outage flag (so you get exactly one "down" and
one "recovered" message, never a flood):

  - Cycles keep failing (e.g. the Data API blocks us): the watcher itself
    notices via on_cycle_failure() and alerts once failures cross a threshold.
  - The watcher isn't running at all: it can't report on itself, so a separate
    hourly process calls check_and_alert_staleness() and alerts if no cycle has
    succeeded recently.

When a healthy cycle lands after an alert, on_cycle_success() clears the flag
and posts the recovery note.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from . import config, store
from .notify import post_message

log = logging.getLogger("polysignal.health")


def _humanize(delta: timedelta) -> str:
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return "%dm" % mins
    return "%dh %dm" % (mins // 60, mins % 60)


def on_cycle_success() -> None:
    """Record a good cycle; if we were in a known outage, announce recovery."""
    was_down = store.is_outage_alerted()
    store.record_cycle_success()
    if was_down:
        store.set_outage_alerted(False)
        post_message("✅ *PolySignal recovered* — a cycle just completed successfully.")
        log.info("Recovery posted to Slack.")


def on_cycle_failure(exc: Exception) -> None:
    """Record a failed cycle; alert once consecutive failures cross the bar."""
    n = store.record_cycle_failure()
    log.error("Cycle failed (%d in a row): %s", n, exc)
    if n >= config.FAILURE_ALERT_THRESHOLD and not store.is_outage_alerted():
        store.set_outage_alerted(True)
        post_message(
            "⚠️ *PolySignal trouble* — %d cycles in a row have failed "
            "(latest error: %s). Alerts are paused until this clears." % (n, exc))
        log.info("Outage alert posted to Slack.")


def staleness() -> Optional[str]:
    """If the watcher looks stalled, return a human description; else None."""
    last = store.get_last_success()
    if not last:
        return None  # never succeeded yet — nothing to compare against
    try:
        ts = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    age = datetime.utcnow() - ts
    if age > timedelta(hours=config.STALENESS_ALERT_HOURS):
        return "last successful run was %s ago (%s UTC)" % (_humanize(age), last)
    return None


def check_and_alert_staleness() -> Optional[str]:
    """Watchdog entry: alert (once) if the watcher has gone silent."""
    msg = staleness()
    if msg and not store.is_outage_alerted():
        store.set_outage_alerted(True)
        post_message("🚨 *PolySignal watcher may be down* — %s." % msg)
        log.warning("Staleness alert posted: %s", msg)
    return msg

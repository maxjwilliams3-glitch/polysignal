"""
PolySignal — main loop.

Each cycle:
  1. Pull the top-N leaderboard for the configured window.
  2. For each trader, fetch current positions.
  3. Diff against the last snapshot in SQLite.
  4. Send any resulting events to Slack (unless it's the silent baseline run).
  5. Overwrite the snapshot.

Run modes:
  python -m polysignal.main --once     one cycle, then exit (for launchd/cron)
  python -m polysignal.main            run forever, sleeping between cycles

This module also loads a .env file from the current directory if present, so you
can just edit .env once instead of exporting variables each session.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, # comments, no external deps."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Don't clobber a value already set in the real environment.
            os.environ.setdefault(key, value)


# Load .env BEFORE importing config (config reads env at import time).
load_dotenv()

from . import config, health, quality, store  # noqa: E402
from .diff import diff_positions     # noqa: E402
from .notify import send             # noqa: E402
from .polymarket import PolymarketClient  # noqa: E402
from .track_record import TrackRecord, compute_track_record  # noqa: E402

TRACK_RECORD_MAX_AGE_HOURS = 24


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


log = logging.getLogger("polysignal")


def _is_stale(computed_at: str, max_age_hours: int = TRACK_RECORD_MAX_AGE_HOURS) -> bool:
    """True if a cached computed_at timestamp is missing or older than the limit."""
    if not computed_at:
        return True
    try:
        ts = datetime.strptime(computed_at, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return True
    return datetime.utcnow() - ts > timedelta(hours=max_age_hours)


def get_track_record(client: PolymarketClient, wallet: str) -> TrackRecord:
    """Return a wallet's track record, recomputing only if the cache is stale."""
    cached = store.load_track_record(wallet)
    if cached and not _is_stale(cached.get("computed_at", "")):
        return TrackRecord(
            wallet=wallet,
            win_rate=cached["win_rate"],
            total_realized_pnl=cached["total_realized_pnl"],
            sample_size=cached["sample_size"],
            avg_return=cached["avg_return"],
            capped=bool(cached.get("capped")),
        )
    stats = compute_track_record(client, wallet)
    store.save_track_record(wallet, stats)
    log.info("    track record for %s: %.0f%% over %d closed",
             wallet[:10], stats.win_rate * 100, stats.sample_size)
    return stats


def run_cycle(client: PolymarketClient) -> None:
    log.info("Fetching top %d traders (%s, %s, %s)...",
             config.TOP_N, config.TIME_PERIOD, config.ORDER_BY, config.CATEGORY)

    leaders = client.leaderboard(
        time_period=config.TIME_PERIOD,
        order_by=config.ORDER_BY,
        category=config.CATEGORY,
        limit=config.TOP_N,
    )
    if not leaders:
        log.warning("Leaderboard returned no traders. Skipping cycle.")
        return

    all_events = []
    records = {}
    for entry in leaders:
        wallet = entry.get("proxyWallet", "")
        name = entry.get("userName") or wallet[:10]
        if not wallet:
            continue

        pnl = entry.get("pnl", 0.0)
        log.info("  %s (%s)  pnl=%s", name, wallet[:10], pnl)

        current = client.positions(wallet, size_threshold=config.MIN_POSITION_USD)
        previous = store.load_snapshot(wallet)

        first_time = not store.has_baseline(wallet)
        if first_time and config.SILENT_FIRST_RUN:
            log.info("    baselining %s silently (%d positions)", name, len(current))
            store.replace_snapshot(wallet, current)
            store.mark_baselined(wallet)
            continue

        events = diff_positions(wallet, name, previous, current)
        if events:
            tr = get_track_record(client, wallet)
            passes, reason = quality.evaluate(tr)
            if passes:
                log.info("    %d event(s) for %s — %s", len(events), name, reason)
                records[wallet] = tr
                for ev in events:
                    store.record_signal(ev)  # log for the end-of-day scorecard
                all_events.extend(events)
            else:
                log.info("    suppressed %d event(s) from %s — %s", len(events), name, reason)

        store.replace_snapshot(wallet, current)
        store.mark_baselined(wallet)

    if all_events:
        send(all_events, window=config.TIME_PERIOD, records=records)
    else:
        log.info("No new events this cycle.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Polymarket top-trader signal bot")
    parser.add_argument("--once", action="store_true",
                        help="Run a single cycle and exit (for launchd/cron).")
    args = parser.parse_args()

    setup_logging()

    for problem in config.validate():
        log.warning("config: %s", problem)

    store.init()
    client = PolymarketClient()

    if args.once:
        try:
            run_cycle(client)
        except Exception as exc:
            log.exception("Cycle failed.")
            health.on_cycle_failure(exc)
            return 1
        health.on_cycle_success()
        return 0

    log.info("Starting loop. Interval: %ds. Ctrl-C to stop.", config.POLL_INTERVAL_SECONDS)
    try:
        while True:
            try:
                run_cycle(client)
            except Exception as exc:
                log.exception("Cycle failed; will retry next interval.")
                health.on_cycle_failure(exc)
            else:
                health.on_cycle_success()
            time.sleep(config.POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

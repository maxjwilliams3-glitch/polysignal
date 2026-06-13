"""
Standalone watchdog for PolySignal.

The 15-minute watcher can't tell you it died — if it's not running, no code of
its runs. This separate process does: it checks when a cycle last succeeded and
pings Slack if that was too long ago (config.STALENESS_ALERT_HOURS).

Because it's a different process, if THIS runs and posts, that also confirms the
Slack webhook still works.

    python -m polysignal.healthcheck

Intended to run hourly via launchd (see com.max.polysignal.healthcheck.plist).
"""
from __future__ import annotations

import logging
import os
import sys


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

from . import health, store   # noqa: E402

log = logging.getLogger("polysignal.healthcheck")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    store.init()
    msg = health.check_and_alert_staleness()
    if msg:
        log.warning("Watcher appears stalled: %s", msg)
    else:
        log.info("Watcher healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

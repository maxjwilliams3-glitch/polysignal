"""
Endpoint probe — run this FIRST, before trusting the bot.

Hits all three Data API endpoints live with the top trader and prints the raw
shape of what comes back, so you can confirm field names match expectations.

    python probe.py

No Slack, no database, no writes. Pure read-and-print.
"""
from __future__ import annotations

import json
import os


def load_dotenv(path=".env"):
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

from polysignal import config              # noqa: E402
from polysignal.polymarket import PolymarketClient  # noqa: E402


def show(label, obj, n=2):
    print("\n" + "=" * 70 + "\n" + label + "\n" + "=" * 70)
    if isinstance(obj, list):
        print("(list of %d items; showing first %d)" % (len(obj), min(n, len(obj))))
        for item in obj[:n]:
            print(json.dumps(item, indent=2)[:2000])
    else:
        print(json.dumps(obj, indent=2)[:2000])


def main():
    client = PolymarketClient()

    leaders = client.leaderboard(config.TIME_PERIOD, config.ORDER_BY, config.CATEGORY, config.TOP_N)
    show("LEADERBOARD (%s/%s/%s)" % (config.TIME_PERIOD, config.ORDER_BY, config.CATEGORY), leaders)

    if not leaders:
        print("\nNo leaders returned — can't probe positions/activity. Check params.")
        return

    wallet = leaders[0].get("proxyWallet")
    name = leaders[0].get("userName", wallet)
    print("\nUsing top trader for deeper probes: %s (%s)" % (name, wallet))

    positions = client.positions(wallet, size_threshold=config.MIN_POSITION_USD)
    show("POSITIONS (top trader)", positions)

    activity = client.activity(wallet, limit=10)
    show("ACTIVITY (top trader)", activity)

    print("\nProbe complete. Confirm the field names above match diff.py / store.py.")


if __name__ == "__main__":
    main()

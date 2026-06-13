"""
Throwaway probe — sanity-check track_record against real data.

Pulls the current #1 leaderboard trader and prints their computed track record
plus a couple of raw closed-position rows, so you can eyeball whether the field
names (realizedPnl, totalBought) and numbers look right before trusting the
loop's annotations. No DB writes, no Slack.

    python probe_track_record.py
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

from polysignal import config                       # noqa: E402
from polysignal.polymarket import PolymarketClient   # noqa: E402
from polysignal.track_record import compute_track_record  # noqa: E402


def main():
    client = PolymarketClient()

    leaders = client.leaderboard(config.TIME_PERIOD, config.ORDER_BY, config.CATEGORY, config.TOP_N)
    if not leaders:
        print("No leaders returned — check params/network.")
        return

    top = leaders[0]
    wallet = top.get("proxyWallet")
    name = top.get("userName") or wallet
    print("#1 trader: %s (%s)" % (name, wallet))

    raw = client.closed_positions(wallet, limit=3, offset=0)
    print("\nSample closed positions (first %d):" % len(raw))
    for r in raw:
        print(json.dumps(r, indent=2)[:1500])

    tr = compute_track_record(client, wallet)
    print("\nTrack record:")
    print("  sample_size        =", tr.sample_size)
    print("  win_rate           = %.1f%%" % (tr.win_rate * 100))
    print("  total_realized_pnl = ${:,.0f}".format(tr.total_realized_pnl))
    print("  avg_return         = %.1f%%" % (tr.avg_return * 100))


if __name__ == "__main__":
    main()

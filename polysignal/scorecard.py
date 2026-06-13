"""
End-of-day scorecard.

Goes back over every alert the bot has fired but not yet scored (the OPEN rows
in the `signals` table), checks each trader's resolved bets, and reports which
of our signals HIT, which MISSED, and which are still open.

How resolution is detected: once a Polymarket market settles, the trader's
position appears in their /closed-positions feed with a final realizedPnl
(> 0 = won, <= 0 = lost). We match our logged signals to that feed by
(conditionId, outcome). Anything not in the feed yet is still open and stays
OPEN for a future run.

Run modes:
  python -m polysignal.scorecard            check, update the DB, post to Slack
  python -m polysignal.scorecard --dry-run  check and print, but don't post or write

Intended to run once a day via launchd (see com.max.polysignal.scorecard.plist).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from typing import Dict, List, Tuple


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


# Load .env before importing config (config reads env at import time).
load_dotenv()

from . import config, store               # noqa: E402
from .notify import post_message, _money  # noqa: E402
from .polymarket import PolymarketClient   # noqa: E402
from .track_record import PAGE_SIZE, MAX_CLOSED  # noqa: E402

log = logging.getLogger("polysignal.scorecard")


def _closed_index(client: PolymarketClient, wallet: str) -> Dict[Tuple[str, str], float]:
    """Map (conditionId, outcome) -> realizedPnl for a wallet's resolved bets."""
    index: Dict[Tuple[str, str], float] = {}
    offset = 0
    pulled = 0
    while pulled < MAX_CLOSED:
        page = client.closed_positions(wallet, limit=PAGE_SIZE, offset=offset)
        if not page:
            break
        for r in page:
            key = (r.get("conditionId", ""), r.get("outcome", ""))
            try:
                index[key] = float(r.get("realizedPnl") or 0.0)
            except (TypeError, ValueError):
                index[key] = 0.0
        pulled += len(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return index


def run_scorecard(client: PolymarketClient, dry_run: bool = False) -> str:
    open_signals = store.load_open_signals()
    if not open_signals:
        log.info("No open signals to score.")
        return ""

    # Pull each relevant wallet's resolved bets just once.
    wallets = {s["wallet"] for s in open_signals}
    closed_by_wallet = {w: _closed_index(client, w) for w in wallets}

    hits: List[dict] = []
    misses: List[dict] = []
    still_open = 0

    for sig in open_signals:
        key = (sig["condition_id"], sig["outcome"])
        index = closed_by_wallet.get(sig["wallet"], {})
        if key not in index:
            still_open += 1
            continue
        pnl = index[key]
        status = "HIT" if pnl > 0 else "MISS"
        sig["realized_pnl"] = pnl
        (hits if status == "HIT" else misses).append(sig)
        if not dry_run:
            store.resolve_signal(sig["id"], status, pnl)

    text = _build_scorecard(hits, misses, still_open)
    log.info("Scorecard: %d hit, %d miss, %d still open.", len(hits), len(misses), still_open)

    if dry_run:
        print(text)
    else:
        post_message(text)
    return text


def _line(sig: dict, mark: str) -> str:
    who = sig.get("user_name") or sig["wallet"][:10]
    return "%s *%s* — %s on _%s_  (%s)" % (
        mark, who, sig["outcome"], sig.get("title") or "(market)",
        _money(sig.get("realized_pnl") or 0.0))


def _build_scorecard(hits: List[dict], misses: List[dict], still_open: int) -> str:
    resolved = len(hits) + len(misses)
    net = sum((s.get("realized_pnl") or 0.0) for s in hits + misses)

    if resolved == 0:
        return ("*📊 Polymarket scorecard*\nNo tracked signals resolved yet — "
                "%d still open." % still_open)

    win_pct = (len(hits) / resolved) * 100
    lines = [
        "*📊 Polymarket scorecard*",
        "Resolved: *%d hit · %d miss* (%.0f%% win) — net %s realized · %d still open" % (
            len(hits), len(misses), win_pct, _money(net), still_open),
        "",
    ]
    lines += [_line(s, "✅") for s in hits]
    lines += [_line(s, "❌") for s in misses]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score resolved Polymarket signals")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the scorecard without writing to the DB or Slack.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    store.init()
    client = PolymarketClient()
    run_scorecard(client, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

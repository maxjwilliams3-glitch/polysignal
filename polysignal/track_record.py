"""
Trader track-record quality.

Given a wallet, pull its closed (resolved) positions from the Data API and boil
them down to a few summary stats:

  win_rate           — fraction of closed positions with realizedPnl > 0
  total_realized_pnl — sum of realizedPnl across all closed positions
  sample_size        — how many closed positions we looked at
  avg_return         — mean of realizedPnl / totalBought (per-position ROI)

This is read-only and stateless; main.py is responsible for caching the result
(see store.track_record) so we don't recompute every cycle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from .polymarket import PolymarketClient

log = logging.getLogger("polysignal.track")

# The /closed-positions endpoint caps a page at 50. We pull a trader's FULL
# closed history so win-rate reflects their whole record, not just their biggest
# wins (the feed is sorted by realized PnL, which would otherwise bias it up).
# MAX_CLOSED is only a safety ceiling; hitting it sets `capped`.
PAGE_SIZE = 50
MAX_CLOSED = 2000


@dataclass
class TrackRecord:
    wallet: str
    win_rate: float
    total_realized_pnl: float
    sample_size: int
    avg_return: float
    capped: bool = False  # True if we stopped at MAX_CLOSED (record is partial)


def _f(value) -> float:
    """Coerce a possibly-None/str numeric field to float."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def compute_track_record(
    client: PolymarketClient, wallet: str, max_positions: int = MAX_CLOSED
) -> TrackRecord:
    """Fetch a wallet's full closed-position history and summarize it.

    Pages until the API runs out (their whole record) or we reach max_positions,
    in which case the stats are partial and the result is flagged `capped`.
    """
    rows: List[dict] = []
    offset = 0
    capped = False
    while True:
        page = client.closed_positions(wallet, limit=PAGE_SIZE, offset=offset)
        if not page:
            break
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break  # reached the end of their history — this is everything
        if len(rows) >= max_positions:
            capped = True
            break
        offset += PAGE_SIZE
    return _summarize(wallet, rows[:max_positions], capped)


def _summarize(wallet: str, rows: List[dict], capped: bool = False) -> TrackRecord:
    sample = len(rows)
    if sample == 0:
        return TrackRecord(wallet, 0.0, 0.0, 0, 0.0, capped)

    wins = 0
    total = 0.0
    returns: List[float] = []
    for r in rows:
        pnl = _f(r.get("realizedPnl"))
        total += pnl
        if pnl > 0:
            wins += 1
        bought = _f(r.get("totalBought"))
        if bought > 0:
            returns.append(pnl / bought)

    win_rate = wins / sample
    avg_return = (sum(returns) / len(returns)) if returns else 0.0
    return TrackRecord(wallet, win_rate, total, sample, avg_return, capped)

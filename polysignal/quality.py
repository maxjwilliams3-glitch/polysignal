"""
Quality gate for trader signals.

Decides whether a trader's track record is good enough to alert on. The bar:
net-profitable AND a win-rate at/above config.MIN_WIN_RATE, over at least
config.MIN_TRACK_RECORD_SAMPLE closed bets.

Two deliberate carve-outs:
  - Capped records (we only saw a trader's biggest wins, so win-rate is biased
    upward and untrustworthy) pass on net profit alone — they're demonstrably
    large net winners, just unmeasurable on win-rate.
  - Traders with too few closed bets are unproven, so they're suppressed rather
    than given the benefit of the doubt.

Returns (passes, reason) so the loop can log *why* something was suppressed.
"""
from __future__ import annotations

from typing import Tuple

from . import config


def evaluate(tr) -> Tuple[bool, str]:
    """Return (passes, reason) for a track_record.TrackRecord against the bar."""
    if tr is None or tr.sample_size <= 0:
        return False, "no track record"

    pnl_str = "${:,.0f}".format(tr.total_realized_pnl)
    if tr.total_realized_pnl <= 0:
        return False, "net-negative (%s)" % pnl_str

    # Win-rate is unreliable for capped records; net profit is enough.
    if getattr(tr, "capped", False):
        return True, "net winner %s (win-rate partial)" % pnl_str

    if tr.sample_size < config.MIN_TRACK_RECORD_SAMPLE:
        return False, "unproven — only %d closed bets" % tr.sample_size

    if tr.win_rate < config.MIN_WIN_RATE:
        return False, "win-rate %.0f%% below %.0f%% bar" % (
            tr.win_rate * 100, config.MIN_WIN_RATE * 100)

    return True, "net winner %s, %.0f%% over %d bets" % (
        pnl_str, tr.win_rate * 100, tr.sample_size)

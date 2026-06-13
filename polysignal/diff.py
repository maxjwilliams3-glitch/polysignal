"""
Diff engine.

Given a trader's previous snapshot and current positions, find what's worth
alerting on:

  NEW_POSITION  — a (condition, outcome) held now but not last cycle.
  NOTABLE_OPEN  — an existing hold that crossed >= NOTABLE_USD since last look.

Dust below MIN_POSITION_USD is ignored.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass
class Event:
    kind: str          # "NEW_POSITION" or "NOTABLE_OPEN"
    wallet: str
    user_name: str
    title: str
    outcome: str
    size: float
    avg_price: float
    current_usd: float
    condition_id: str


def diff_positions(wallet: str, user_name: str, previous: dict, current: list) -> list:
    events = []

    for p in current:
        current_usd = float(p.get("currentValue", 0.0) or 0.0)
        if current_usd < config.MIN_POSITION_USD:
            continue

        key = (p.get("conditionId", ""), p.get("outcome", ""))
        is_new = key not in previous

        if is_new:
            events.append(_make_event("NEW_POSITION", wallet, user_name, p, current_usd))
            continue

        prev = previous[key]
        prev_usd = float(prev.get("current_usd", 0.0) or 0.0)
        if current_usd >= config.NOTABLE_USD > prev_usd:
            events.append(_make_event("NOTABLE_OPEN", wallet, user_name, p, current_usd))

    return events


def _make_event(kind, wallet, user_name, p, current_usd) -> Event:
    return Event(
        kind=kind,
        wallet=wallet,
        user_name=user_name or wallet[:10],
        title=p.get("title", "(unknown market)"),
        outcome=p.get("outcome", "?"),
        size=float(p.get("size", 0.0) or 0.0),
        avg_price=float(p.get("avgPrice", 0.0) or 0.0),
        current_usd=current_usd,
        condition_id=p.get("conditionId", ""),
    )

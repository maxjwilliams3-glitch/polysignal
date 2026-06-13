"""
Slack notifier.

Formats a cycle's Events into one batched Slack message and posts to the webhook.
If no webhook is configured, it logs the message instead so you can still test.
"""
from __future__ import annotations

import logging

import requests

from . import config
from .diff import Event

log = logging.getLogger("polysignal.notify")


def _money(value: float) -> str:
    """Compact signed dollars: +$1.2M, +$340K, -$5K, +$950."""
    sign = "+" if value >= 0 else "-"
    a = abs(value)
    if a >= 1_000_000:
        body = "$%.1fM" % (a / 1_000_000)
    elif a >= 1_000:
        body = "$%.0fK" % (a / 1_000)
    else:
        body = "${:,.0f}".format(a)
    return sign + body


def _record_suffix(e: Event, records: dict) -> str:
    """' [62% over 240 bets, +$1.2M realized]' if we have a record, else ''."""
    if not records:
        return ""
    tr = records.get(e.wallet)
    if not tr or tr.sample_size <= 0:
        return ""
    realized = _money(tr.total_realized_pnl)
    if getattr(tr, "capped", False):
        # We only fetched their highest-PnL bets, so a win-rate here would be
        # biased upward — show the partial count instead of a false percentage.
        return "  [%d+ bets, %s realized · win-rate partial]" % (tr.sample_size, realized)
    return "  [%.0f%% over %d bets, %s realized]" % (
        tr.win_rate * 100, tr.sample_size, realized)


def _format_event(e: Event, records: dict) -> str:
    price = ("%.2f" % e.avg_price) if e.avg_price else "?"
    usd = "${:,.0f}".format(e.current_usd)
    rec = _record_suffix(e, records)
    if e.kind == "NEW_POSITION":
        big = "  *(notable size)*" if e.current_usd >= config.NOTABLE_USD else ""
        return "🟢 *%s* opened *%s* on _%s_  — %s @ %s%s%s" % (
            e.user_name, e.outcome, e.title, usd, price, big, rec)
    else:  # NOTABLE_OPEN
        return "🔶 *%s* holds a large position: *%s* on _%s_  — %s @ %s%s" % (
            e.user_name, e.outcome, e.title, usd, price, rec)


def build_message(events: list, window: str, records: dict = None) -> str:
    header = "*Polymarket signal* — top traders (%s)\n" % window
    lines = [_format_event(e, records or {}) for e in events]
    return header + "\n".join(lines)


def post_message(text: str) -> None:
    """Post raw text to the Slack webhook, or log it if no webhook is set."""
    if not config.SLACK_WEBHOOK_URL:
        log.info("No Slack webhook configured. Would have sent:\n%s", text)
        return
    try:
        resp = requests.post(
            config.SLACK_WEBHOOK_URL,
            json={"text": text},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        log.info("Posted message to Slack (%d chars).", len(text))
    except requests.RequestException as exc:
        log.error("Failed to post to Slack: %s\nMessage was:\n%s", exc, text)


def send(events: list, window: str, records: dict = None) -> None:
    if not events:
        return
    post_message(build_message(events, window, records))

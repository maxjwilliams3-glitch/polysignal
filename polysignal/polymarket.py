"""
Thin client for Polymarket's public Data API.

Three endpoints, all public, no auth:
  - /v1/leaderboard   -> top traders by PNL/VOL for a window
  - /positions        -> a wallet's current open positions
  - /activity         -> a wallet's timestamped trade feed

This layer just fetches and returns parsed JSON, with retry/backoff. Interpreting
the data is diff.py's job.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests

from . import config

log = logging.getLogger("polysignal.api")


class PolymarketClient:
    def __init__(self, base: Optional[str] = None):
        self.base = base or config.DATA_API_BASE
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "polysignal/0.1 (personal signal bot)"})

    def _get(self, path: str, params: dict) -> Any:
        """GET with exponential backoff. Raises on final failure."""
        url = "%s%s" % (self.base, path)
        last_exc: Optional[Exception] = None
        for attempt in range(config.HTTP_MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=config.HTTP_TIMEOUT_SECONDS)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError("%d from %s" % (resp.status_code, url))
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                wait = 2 ** attempt
                log.warning("GET %s failed (attempt %d/%d): %s — retrying in %ds",
                            path, attempt + 1, config.HTTP_MAX_RETRIES, exc, wait)
                time.sleep(wait)
        assert last_exc is not None
        raise last_exc

    def leaderboard(self, time_period: str, order_by: str, category: str, limit: int) -> list:
        """Top traders. Returns list of {rank, proxyWallet, userName, vol, pnl, ...}."""
        data = self._get("/v1/leaderboard", {
            "timePeriod": time_period,
            "orderBy": order_by,
            "category": category,
            "limit": limit,
        })
        return data if isinstance(data, list) else []

    def positions(self, wallet: str, size_threshold: float) -> list:
        """A wallet's current positions at/above size_threshold."""
        data = self._get("/positions", {
            "user": wallet,
            "sizeThreshold": size_threshold,
            "sortBy": "CURRENT",
            "sortDirection": "DESC",
            "limit": 500,
        })
        return data if isinstance(data, list) else []

    def closed_positions(self, wallet: str, limit: int = 50, offset: int = 0) -> list:
        """A wallet's closed (resolved) positions, ranked by realized PnL.

        One page per call. The API caps limit at 50; callers paginate with
        offset (see track_record.compute_track_record).
        """
        data = self._get("/closed-positions", {
            "user": wallet,
            "sortBy": "REALIZEDPNL",
            "limit": min(limit, 50),
            "offset": offset,
        })
        return data if isinstance(data, list) else []

    def activity(self, wallet: str, limit: int = 50) -> list:
        """A wallet's recent activity feed, newest first. Fields verified live via probe."""
        data = self._get("/activity", {
            "user": wallet,
            "limit": limit,
        })
        return data if isinstance(data, list) else []

"""
SQLite snapshot store.

The bot detects *change*, which means remembering what it last saw. This is that
memory: one table holding the latest snapshot per (wallet, condition, outcome),
plus a record of which wallets we've baselined so first contact stays silent.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from . import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    wallet       TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    title        TEXT,
    size         REAL,
    avg_price    REAL,
    current_usd  REAL,
    cash_pnl     REAL,
    updated_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (wallet, condition_id, outcome)
);

CREATE TABLE IF NOT EXISTS baselined_wallets (
    wallet      TEXT PRIMARY KEY,
    first_seen  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS track_record (
    wallet             TEXT PRIMARY KEY,
    win_rate           REAL,
    total_realized_pnl REAL,
    sample_size        INTEGER,
    avg_return         REAL,
    capped             INTEGER DEFAULT 0,
    computed_at        TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet        TEXT NOT NULL,
    user_name     TEXT,
    condition_id  TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    title         TEXT,
    kind          TEXT,
    entry_price   REAL,
    current_usd   REAL,
    fired_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    status        TEXT DEFAULT 'OPEN',   -- OPEN | HIT | MISS
    realized_pnl  REAL,
    resolved_at   TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn) -> None:
    """Additive schema migrations for databases created by older versions."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(track_record)")}
    if "capped" not in cols:
        conn.execute("ALTER TABLE track_record ADD COLUMN capped INTEGER DEFAULT 0")


def has_baseline(wallet: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM baselined_wallets WHERE wallet = ?", (wallet,)
        ).fetchone()
        return row is not None


def mark_baselined(wallet: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO baselined_wallets (wallet) VALUES (?)", (wallet,)
        )


def load_snapshot(wallet: str) -> dict:
    """Return {(condition_id, outcome): position_dict} for a wallet's last snapshot."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE wallet = ?", (wallet,)
        ).fetchall()
    return {(r["condition_id"], r["outcome"]): dict(r) for r in rows}


def load_track_record(wallet: str) -> dict:
    """Return the cached track-record row for a wallet, or {} if none.

    The row includes computed_at (UTC 'YYYY-MM-DD HH:MM:SS') so the caller can
    decide whether it's stale.
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM track_record WHERE wallet = ?", (wallet,)
        ).fetchone()
    return dict(row) if row is not None else {}


def save_track_record(wallet: str, stats) -> None:
    """Upsert a wallet's track-record stats, stamping computed_at to now (UTC).

    `stats` is duck-typed: any object exposing win_rate, total_realized_pnl,
    sample_size, avg_return (e.g. track_record.TrackRecord).
    """
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO track_record
               (wallet, win_rate, total_realized_pnl, sample_size, avg_return, capped, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                wallet,
                stats.win_rate,
                stats.total_realized_pnl,
                stats.sample_size,
                stats.avg_return,
                int(bool(stats.capped)),
            ),
        )


# --- Health / heartbeat ------------------------------------------------------

def _meta_get(key: str, default: str = "") -> str:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def _meta_set(key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def record_cycle_success() -> None:
    """Stamp a successful cycle (UTC) and reset the failure counter."""
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_success_at', CURRENT_TIMESTAMP)")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('consecutive_failures', '0')")


def record_cycle_failure() -> int:
    """Increment and return the consecutive-failure count."""
    n = int(_meta_get("consecutive_failures", "0") or "0") + 1
    _meta_set("consecutive_failures", str(n))
    return n


def get_last_success() -> str:
    """UTC 'YYYY-MM-DD HH:MM:SS' of the last successful cycle, or '' if never."""
    return _meta_get("last_success_at", "")


def is_outage_alerted() -> bool:
    return _meta_get("outage_alerted", "0") == "1"


def set_outage_alerted(flag: bool) -> None:
    _meta_set("outage_alerted", "1" if flag else "0")


def record_signal(event) -> bool:
    """Log a fired alert so we can later check whether it resolved.

    `event` is a diff.Event. Skips insertion if an unresolved (OPEN) signal
    already exists for the same (wallet, condition_id, outcome) — so a position
    that first fires NEW_POSITION and later NOTABLE_OPEN is tracked once.
    Returns True if a row was inserted.
    """
    with _conn() as conn:
        existing = conn.execute(
            """SELECT 1 FROM signals
               WHERE wallet = ? AND condition_id = ? AND outcome = ? AND status = 'OPEN'""",
            (event.wallet, event.condition_id, event.outcome),
        ).fetchone()
        if existing is not None:
            return False
        conn.execute(
            """INSERT INTO signals
               (wallet, user_name, condition_id, outcome, title, kind, entry_price, current_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.wallet,
                event.user_name,
                event.condition_id,
                event.outcome,
                event.title,
                event.kind,
                event.avg_price,
                event.current_usd,
            ),
        )
        return True


def load_open_signals() -> list:
    """Return all still-unresolved (OPEN) signal rows as dicts, oldest first."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE status = 'OPEN' ORDER BY fired_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def resolve_signal(signal_id: int, status: str, realized_pnl: float) -> None:
    """Mark a signal HIT or MISS with its final realized PnL."""
    with _conn() as conn:
        conn.execute(
            """UPDATE signals
               SET status = ?, realized_pnl = ?, resolved_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (status, realized_pnl, signal_id),
        )


def replace_snapshot(wallet: str, positions: list) -> None:
    """Wipe and rewrite a wallet's positions with the current set."""
    with _conn() as conn:
        conn.execute("DELETE FROM positions WHERE wallet = ?", (wallet,))
        conn.executemany(
            """INSERT OR REPLACE INTO positions
               (wallet, condition_id, outcome, title, size, avg_price, current_usd, cash_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    wallet,
                    p.get("conditionId", ""),
                    p.get("outcome", ""),
                    p.get("title", ""),
                    p.get("size", 0.0),
                    p.get("avgPrice", 0.0),
                    p.get("currentValue", 0.0),
                    p.get("cashPnl", 0.0),
                )
                for p in positions
            ],
        )

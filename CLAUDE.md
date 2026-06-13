# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PolySignal is a read-only signal bot. Each cycle it pulls Polymarket's top-N leaderboard, fetches each top trader's current positions, diffs them against the last snapshot in SQLite, and posts a batched Slack alert for new/notable positions. No wallet, no auth, no trade execution — only public Data API reads.

## Commands

Always run from the **outer** `polysignal/` directory (the one with `probe.py`), not the inner package.

```bash
source .venv/bin/activate          # venv is at .venv/
pip install -r requirements.txt    # only dep is `requests`

python probe.py                    # live-print raw API shapes; no DB/Slack writes. Run when API fields are in doubt.
python -m polysignal.main --once   # one cycle then exit (launchd/cron mode)
python -m polysignal.main          # run forever, sleeping POLL_INTERVAL_SECONDS between cycles
```

There is no test suite, linter, or build step configured.

## Critical sequencing behavior

**First run per wallet is silent.** On first contact a wallet is baselined (snapshot stored, recorded in `baselined_wallets`) and emits no alerts — this prevents a flood when the leaderboard roster rotates in new wallets. Alerts only fire from the *second* cycle onward. When testing alert output, you must run a cycle at least twice. Controlled by `SILENT_FIRST_RUN` (default on).

## Architecture / data flow

The pipeline lives in `run_cycle()` in `polysignal/main.py`; everything else is a layer it calls:

- `polymarket.py` — `PolymarketClient`: thin HTTP wrapper over the public Data API (`/v1/leaderboard`, `/positions`, `/activity`) with exponential backoff. Returns parsed JSON only; no interpretation. `activity()` exists but is **not used** by the main pipeline — detection is snapshot-diff based, not event-based.
- `store.py` — SQLite snapshot memory. `positions` table holds the latest snapshot keyed by `(wallet, condition_id, outcome)`; `baselined_wallets` records first contact. `replace_snapshot()` wipes-and-rewrites a wallet's rows each cycle (no history kept).
- `diff.py` — pure function `diff_positions(prev, current) -> [Event]`. Emits `NEW_POSITION` (a (condition, outcome) not held last cycle) or `NOTABLE_OPEN` (an existing hold that just crossed `NOTABLE_USD`). Drops anything below `MIN_POSITION_USD`.
- `notify.py` — formats all of a cycle's `Event`s into one batched Slack message and POSTs the webhook. With no webhook configured it logs the message instead, so the pipeline is fully runnable without Slack.

### Field-name coupling (important)

The Polymarket API uses camelCase (`conditionId`, `currentValue`, `avgPrice`, `proxyWallet`); the SQLite columns use snake_case (`condition_id`, `current_usd`). The translation happens in `store.replace_snapshot()` (API→DB) and is read back in `diff.py` via `prev.get("current_usd")` vs `p.get("currentValue")` on the live side. If you change a field name, update **all three** of `polymarket.py`, `store.py`, and `diff.py` together, and re-run `probe.py` to confirm the live API still returns that key.

## Config

All tunables are env vars (prefix `POLYSIGNAL_`) read at import time in `config.py`; `main.py` and `probe.py` auto-load `.env` from the working directory via a minimal hand-rolled `load_dotenv` (no python-dotenv dependency). `.env` uses `setdefault`, so real environment values win over the file. Copy `.env.example` to `.env`; the only required value for live alerts is `POLYSIGNAL_SLACK_WEBHOOK_URL`. `config.validate()` returns non-fatal warnings (logged, never raises).

## Scheduling

`com.max.polysignal.plist` is a macOS launchd job that runs `--once` on a `StartInterval`. Paths inside it are hardcoded to `/Users/maxwellwilliams/polysignal`; edit them before deploying elsewhere. Install with `launchctl load ~/Library/LaunchAgents/...`.

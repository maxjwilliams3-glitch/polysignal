# PolySignal

A signal-only bot that watches the **top 5 traders** on the Polymarket daily/weekly
leaderboard and pushes a **Slack alert** when one opens a new position (or holds a
large one). No money, no wallet, no trade execution — it reads public data and tells
you what the smart money is doing.

Works on Python 3.9+ (no version upgrade needed).

## Folder layout

```
polysignal/              <- open THIS folder in VS Code (the outer one)
├── polysignal/          <- the Python package
│   ├── __init__.py
│   ├── config.py
│   ├── diff.py
│   ├── main.py
│   ├── notify.py
│   ├── polymarket.py
│   └── store.py
├── probe.py             <- run this first
├── requirements.txt
├── .env.example
├── com.max.polysignal.plist
└── README.md
```

You should always run commands from the **outer** `polysignal` folder (the one
containing `probe.py`). If you only see the `.py` modules and no `probe.py`, you
opened one level too deep — reopen the parent folder.

## Setup in VS Code

1. **File → Open Folder**, select the outer `polysignal` folder.
2. Open the terminal: **Terminal → New Terminal**.
3. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
   Your prompt should now start with `(.venv)`. If VS Code asks to select the new
   interpreter, say yes.
4. Install the one dependency:
   ```bash
   pip install -r requirements.txt
   ```

## Step 1 — Verify the endpoints (do this first)

```bash
python probe.py
```

You want to see LEADERBOARD, POSITIONS, and ACTIVITY blocks with real data. A
harmless `NotOpenSSLWarning` about LibreSSL may print — ignore it. If you get a
403 or empty results, that's likely a geo/network thing on Polymarket's side; try
your normal network.

## Step 2 — Slack webhook

Create an incoming webhook at https://api.slack.com/messaging/webhooks. Then copy
`.env.example` to a new file named `.env` and paste your webhook URL after
`POLYSIGNAL_SLACK_WEBHOOK_URL=`. The bot loads `.env` automatically — no exporting.

## Step 3 — Run

```bash
# first run = silent baseline (no alerts, expected):
python -m polysignal.main --once

# run again after a bit — now real diffs alert to Slack:
python -m polysignal.main --once

# or run continuously in the foreground:
python -m polysignal.main
```

## Hands-off scheduling (macOS)

Use `com.max.polysignal.plist`. Edit the paths inside it (WorkingDirectory and the
venv python path), then:

```bash
cp com.max.polysignal.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.max.polysignal.plist
tail -f polysignal.out.log
```

Stop with `launchctl unload ~/Library/LaunchAgents/com.max.polysignal.plist`.

## Tuning (.env / config.py)

- `POLYSIGNAL_TIME_PERIOD` — DAY or WEEK
- `POLYSIGNAL_CATEGORY` — OVERALL now; later POLITICS/SPORTS/CRYPTO/etc.
- `POLYSIGNAL_TOP_N` — how many traders (default 5)
- `POLYSIGNAL_NOTABLE_USD` — size that counts as a big hold (default 5000)
- `POLYSIGNAL_MIN_POSITION_USD` — ignore dust below this (default 100)
- `POLYSIGNAL_POLL_INTERVAL_SECONDS` — cadence for the foreground loop

## Notes

- This is a **signal**, not advice. You see what they bought, not why, and not
  whatever they do off-platform. It's a starting point for your own judgment.
- The daily leaderboard roster rotates; new wallets are baselined silently so you
  aren't flooded when the top 5 changes.
- Activity-based (exact-moment) detection is stubbed in `polymarket.activity()`;
  the default pipeline detects new positions by snapshot diff, which is simpler.

# Active 15m paper sleeve  -  how to run

Parallel paper **day-trader** under `sleeves/active/`. Does not touch momentum equity (repo root) or momentum crypto (`sleeves/crypto/`).

## Status (2026-10-05)

- Starter strategies locked: `equity_15m_ema_trend` / `crypto_15m_ema_trend`.
- **Live auto-book:** `run_active.py` scans 15m bars and books paper fills when EMA entry/exit signals fire (standing order 2026-10-05).
- Equity: US RTH only for new entries/exits. Crypto: 24/7.
- Spam caps: equity max 8 new fills/day; crypto max 6/day.
- Public dashboard: same Pages site as momentum shows Active cards, holdings, and Trade history.

## Layout

```
sleeves/active/
  PLAN.md
  README.md
  config/locked_strategies.json
  equity/config|state|reports
  crypto/config|state|reports
  scripts/ema_scan_lib.py
  scripts/scan_equity_15m.py      # propose-only legacy scanner
  scripts/scan_crypto_15m.py      # propose-only legacy scanner
  scripts/run_active.py           # LIVE scan + book
  strategies/
```

## Capital

| Sleeve | Starting cash | State file |
|--------|---------------|------------|
| Active equity | $100,000 | `equity/state/portfolio.json` |
| Active crypto | $25,000 | `crypto/state/portfolio.json` |

## Commands

From repo root (Marvin or box mirror):

```bash
source .venv/bin/activate
# Preferred during market hours (active then dashboard):
python scripts/market_hours_refresh.py

# Active only:
python sleeves/active/scripts/run_active.py
python sleeves/active/scripts/run_active.py --dry-run
python sleeves/active/scripts/run_active.py --sleeve equity
```

Wire the parent "Paper market hours refresh" routine to call `python scripts/market_hours_refresh.py` about every 15-30 minutes on weekdays 09:35-15:55 ET (crypto signals also update on those runs).

## Do not

- Book fills into root `state/` or `sleeves/crypto/state/`.
- Mix active ranks into weekly momentum screens.
- Place real broker trades.

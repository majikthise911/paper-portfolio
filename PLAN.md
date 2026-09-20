# Paper Portfolio Plan (locked until Jordan says yes)

This document locks the simulated long-only US book for agent Paper. Strategy changes need Jordan's explicit yes in chat. Do not rewrite rules, caps, or the universe without that yes.

## Goal

Run a paper (simulated, not real brokerage) long-only US portfolio from $100,000 virtual cash. Prefer liquid ETFs and a short mega-cap list. Mark weekly against SPY. Propose trades only. Never place real trades.

## Locked rules

- Long only. No shorts, no leverage, no options.
- Signal: simple momentum / relative strength. Primary rank is 3-month total return (about 63 trading days) within the universe. Secondary check: 12-month total return (about 252 trading days) should not be deeply negative (worse than about -20%) when data allows.
- Hard position caps at initiation:
  - Max 15% of portfolio NAV (net asset value: cash plus marked holdings) in any single name.
  - Max 40% in any single sector or theme ETF sleeve when classified simply via `config/universe.json` sector_map.
  - Max 80% invested, so at least 20% cash, unless Jordan later approves a change.
- Rebalance cadence: weekly mark-to-market versus SPY (P&L, drawdown, attribution).
- 30% APY is an aspiration metric only. It is never an automatic stop or auto-rewire trigger.
- Propose strategy tweaks only. Never change rules without Jordan approval.
- Never place real trades. Proposals stay in `reports/` until Jordan approves execution into `state/portfolio.json`.

## Exact universe tickers

ETFs: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC, TLT, GLD, HYG, EFA, EEM

Mega-caps: AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, TSLA, BRK-B, JPM

Benchmark: SPY (for relative strength and weekly marks). Cash may sit in SPY or remain cash.

Source of truth for tickers and sector labels: `config/universe.json`.

## Position caps (initiation)

| Cap | Value |
|-----|-------|
| Max single name | 15% of NAV |
| Max single sector/theme sleeve | 40% of NAV |
| Max invested | 80% of NAV |
| Min cash | 20% of NAV |

## Durable ledger layout

Primary durable home on this box:

`/home/box/agent-data/paper-portfolio`

Preferred long-term home (if parent copies to Marvin / Mac Mini later): a git repo on Marvin with the same tree. This box cannot reach Marvin directly; parent should copy when ready.

Ledger structure:

- `state/portfolio.json` — cash, holdings (positions), NAV, as-of timestamp (America/New_York)
- `state/ledger.jsonl` — append-only log of inits, marks, and (after approval) trades
- `reports/mark_YYYY-MM-DD.md` — weekly mark snapshots
- `reports/proposal_YYYY-MM-DD.json` and `reports/init_YYYY-MM-DD.md` — proposed trades (not executed)
- `reports/` weekly snapshots may also hold JSON mark dumps if useful

Cash, holdings, trades, and weekly snapshots all live under `state/` and `reports/`.

## Seed book

- Starting capital: $100,000 virtual cash
- Positions: empty until Jordan approves a proposal
- Do not execute buys into holdings without Jordan's yes

## Intended weekly loop (Monday ~9:00 AM ET)

Parent will create the Grok Bot routine. Documented intent only:

1. Monday morning US/Eastern (about 9:00 AM ET): run `scripts/mark.py`
2. Record P&L, drawdown from peak NAV, and performance versus SPY
3. Run `scripts/screen.py` for updated 63-day momentum ranks
4. Optionally run `scripts/allocate.py` in propose mode for a tweak proposal
5. Write or update a weekly report under `reports/`
6. Surface a short summary to Jordan; apply nothing without explicit approval

## Commands

```bash
cd /home/box/agent-data/paper-portfolio
source .venv/bin/activate
python scripts/mark.py
python scripts/screen.py
python scripts/allocate.py
```

## Governance reminder

Jordan-facing markdown uses full sentences, no em dashes, and defines jargon on first use. Agent Paper proposes; Jordan decides.

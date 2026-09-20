# Crypto sleeve plan (paper only; locked until Jordan says yes)

This document locks the simulated long-only crypto sleeve for agent Paper. Equity lives at the repo root and stays separate. Strategy or capital changes need Jordan's explicit yes in chat. Do not rewrite rules, caps, or the universe without that yes.

## Goal

Run a paper (simulated, not real exchange) long-only crypto sleeve from $25,000 virtual cash (proposed; Jordan must approve before any buys). Prefer spot crypto tickers via yfinance. Mark weekly against BTC-USD. Propose trades only. Never place real trades.

## Separation from equity

- Equity book remains at root `config/`, `state/`, `scripts/`. Do not mix crypto names into the equity momentum rank.
- This sleeve lives under `sleeves/crypto/` with its own config, state, reports, and scripts.
- The combined dashboard (`scripts/dashboard.py`) shows Household NAV = Equity NAV + Crypto NAV, plus separate holdings tables. Allocation math never crosses sleeves.

## Locked rules

- Long only. No shorts, no leverage, no options, no perpetual futures.
- Signal: same simple momentum / relative strength idea as equity. Primary rank is 3-month total return (about 63 trading days) within the crypto universe. Secondary check: 12-month total return (about 252 trading days) should not be deeply negative (worse than about -20%) when data allows.
- Hard position caps at initiation:
  - Max 25% of sleeve NAV in any single name (crypto is concentrated).
  - Max 80% invested, so at least 20% cash, unless Jordan later approves a change.
- Rebalance cadence: weekly mark-to-market versus BTC-USD (P&L, drawdown, attribution).
- 30% APY is an aspiration metric only. It is never an automatic stop or auto-rewire trigger.
- Propose strategy tweaks only. Never change rules without Jordan approval.
- Never place real trades. Proposals stay in `sleeves/crypto/reports/` until Jordan approves execution into `sleeves/crypto/state/portfolio.json`.

## Exact universe tickers (spot only)

Spot (yfinance): BTC-USD, ETH-USD, SOL-USD, AVAX-USD, LINK-USD

Benchmark: BTC-USD (not SPY).

ETF proxies such as IBIT and FBTC stay OFF for this sleeve unless Jordan later approves a separate proxy note. Prefer spot crypto tickers only.

Source of truth: `sleeves/crypto/config/universe.json`.

## Position caps (initiation)

| Cap | Value |
|-----|-------|
| Max single name | 25% of sleeve NAV |
| Max invested | 80% of sleeve NAV |
| Min cash | 20% of sleeve NAV |

## Seed book

- Starting capital: $25,000 virtual cash (proposed)
- Positions: empty until Jordan approves seed capital and a proposal
- Do not execute buys into holdings without Jordan's yes
- Scaffold status: cash book exists; sleeve is scaffolded and cash-only until approved

## Durable paths

Crypto sleeve home on the box:

`/home/box/agent-data/paper-portfolio/sleeves/crypto`

- `config/rules.json`, `config/universe.json`
- `state/portfolio.json`, `state/ledger.jsonl`
- `reports/` for marks, screens, and proposals

## Weekly loop (with equity)

Parent owns the Monday routine. Documented intent only:

1. Run equity scripts: `scripts/mark.py`, optionally `scripts/screen.py` / `scripts/allocate.py`
2. Run crypto scripts: `scripts/crypto_mark.py`, optionally `scripts/crypto_screen.py` / `scripts/crypto_allocate.py`
3. Run combined `scripts/dashboard.py` (loads equity root + crypto sleeve)
4. Surface a short summary to Jordan; apply nothing without explicit approval

## Commands

```bash
cd /home/box/agent-data/paper-portfolio
source .venv/bin/activate
python scripts/crypto_mark.py
python scripts/crypto_screen.py
python scripts/crypto_allocate.py   # propose only; does not book positions
python scripts/dashboard.py         # combined household view
```

## Governance reminder

Jordan-facing markdown uses full sentences, no em dashes, and defines jargon on first use. Agent Paper proposes; Jordan decides. Crypto changes (seed capital, universe, booking a proposal) need a separate Jordan yes from equity.

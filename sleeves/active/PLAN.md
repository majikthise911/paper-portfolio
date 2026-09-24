# Active 15m paper sleeve plan (parallel experiment; locked shape + locked starters 2026-09-24)

This document locks the **parallel** active (Freqtrade-style, higher-activity) paper experiment for agent Paper. It does **not** replace the weekly momentum books.

- Momentum equity stays at repo root (`config/`, `state/`).
- Momentum crypto stays at `sleeves/crypto/`.
- This sleeve lives only under `sleeves/active/`.

Strategy micro-rules and starter strategy approval need Jordan's explicit yes before any paper fills. Never place real trades. Never mix active signals into weekly momentum ranks.

## Goal

Run an apples-to-apples paper household against the momentum household:

| Book | Active capital | Momentum capital | Benchmark |
|------|----------------|------------------|-----------|
| US equities | $100,000 | $100,000 | SPY |
| Crypto | $25,000 | $25,000 | BTC-USD |
| Household | $125,000 | $125,000 | vs each other (same window) |

Cadence: **15-minute bars**. Paper only.

## Locked experiment shape (Jordan chat 2026-09-24)

- Active sleeve: **both** US equities AND crypto
- 15-minute bars
- $125,000 paper capital split like momentum: **$100k equity + $25k crypto**
- Apples-to-apples vs momentum household
- Paper only. Never real trades. Never mix into weekly momentum ranks.
- **Locked starter strategies (Jordan chat 2026-09-24):** `equity_15m_ema_trend` and `crypto_15m_ema_trend`. Still no fills until trade-batch yes.

## Separation rules

- Separate `config/`, `state/`, `reports/` under `sleeves/active/equity/` and `sleeves/active/crypto/`.
- Do not edit root `state/portfolio.json` or `sleeves/crypto/state/portfolio.json` from this sleeve.
- Allocation math never crosses into momentum books.
- Dashboard integration is **phase 2** (see below). Do not rewrite `scripts/dashboard.py` in the scaffold pass.

## Locked defaults (v1; Jordan locked shape 2026-09-24, then locked both starter strategies same day)

### Shared

- Long only. No shorts, no leverage, no options. (Shorts/leverage flagged as a later upgrade only.)
- Paper only. Proposals require Jordan yes before fills.
- Starter strategies **Locked** 2026-09-24: `equity_15m_ema_trend` and `crypto_15m_ema_trend` (see `strategies/` and `config/locked_strategies.json`). Params: EMA 8/21, ATR 14; equity stop 1.5×ATR RTH; crypto stop 2×ATR 24/7. Still propose-before-fill: no paper fills until Jordan yes on a trade-batch proposal.

### Active equity (`sleeves/active/equity/`)

- Caps mirror momentum where they still fit: max single name 15%, max sector ETF sleeve 40%, tech mega-cap (AAPL+MSFT+NVDA) 30%, max invested 80% / min cash 20%.
- Added for active books: max concurrent positions 8.
- Propose during US regular hours (09:30–16:00 ET) on 15m bars.
- Universe: liquid subset of parent (liquid ETFs + mega-caps). Dropped vs parent for v1: HYG, EFA, EEM. Documented in `equity/config/universe.json`.

### Active crypto (`sleeves/active/crypto/`)

- Caps mirror momentum crypto: max single name 25%, max invested 80% / min cash 20%.
- Added: max concurrent positions 4.
- Propose / mark 24/7 on 15m bars.
- Universe: BTC, ETH, SOL, AVAX, LINK (same as momentum crypto).

## How we judge (same-window)

1. Active equity NAV / P&L / drawdown vs SPY and vs momentum equity.
2. Active crypto NAV / P&L / drawdown vs BTC and vs momentum crypto.
3. Active household ($125k) vs momentum household ($125k) over the same date window.

## Scaffold / lock status

- Cash books initialized; positions empty.
- Starter strategies **Locked** 2026-09-24 (Jordan yes). Strategy lock is not a fill authorization.
- **No fills** until Jordan says yes to a written trade-batch proposal (`executed: false` until then).
- Minimal Python+yfinance 15m scanners under `scripts/` (Freqtrade stack still deferred / optional).

## Dashboard (phase 2: done 2026-09-24)

Same Pages dashboard as momentum (`docs/index.html` / https://majikthise911.github.io/paper-portfolio/). Active cards and holdings sit beside momentum. `scripts/dashboard.py` marks active equity/crypto via yfinance on rebuild. P&L chart overlays momentum vs active households on a shared percent scale.

## Durable paths

`/home/box/agent-data/paper-portfolio/sleeves/active`

- `PLAN.md`, `README.md`
- `equity/config/`, `equity/state/`, `equity/reports/`
- `crypto/config/`, `crypto/state/`, `crypto/reports/`
- `strategies/` starter strategy specs

## Governance reminder

Jordan-facing markdown uses full sentences, no em dashes, and defines jargon on first use. Agent Paper proposes; Jordan decides. Active sleeve strategy yes is separate from momentum weekly trade yes.

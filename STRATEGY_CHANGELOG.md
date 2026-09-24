# Strategy change log

Approved tweaks to paper portfolio rules, universe, caps, or signal.
Trade fills stay in `state/ledger.jsonl`. This file is the human-readable history of strategy decisions.

Format per entry: date (America/New_York), what changed, why, Jordan approval note, effective when.

## 2026-09-21 — Equity tech mega-cap sleeve cap 30%

- **Sleeve:** equity
- **Change:** Added hard cap: combined AAPL + MSFT + NVDA weight max 30% of equity NAV. Tickers listed in `config/rules.json` as `tech_megacap_tickers`.
- **Why:** Reduce single-factor tech concentration while keeping the 63-day momentum signal. Combined weight was about 31% at initiation.
- **Jordan approval:** Chat 2026-09-21: lock rule now; execute trim on weekly pass after approving exact paper trades.
- **Effective:** Rule locked 2026-09-21T08:54:41-04:00. No positions changed yet. First trim awaits Monday weekly proposal + yes.
- **How we judge:** Equity max drawdown and vs-SPY over the next four Monday marks versus the pre-cap book.


## 2026-09-24 — Active 15m paper experiment sleeve (parallel)

- **Sleeve:** active (new parallel)
- **Change:** Add active 15m paper experiment with $100,000 US equities + $25,000 crypto under `sleeves/active/` (household $125k). Separate config/state/reports from momentum books.
- **Observation:** Jordan wants apples-to-apples vs weekly momentum household; Freqtrade-style higher activity on 15m bars without switching the momentum method.
- **Logic:** Parallel sleeve, not a method switch on momentum books. Keep root equity and `sleeves/crypto/` untouched. Scaffold cash-only books; no fills until strategy yes.
- **Jordan approval:** Chat 2026-09-24 widget — both universes, 15m, $125k split ($100k+$25k).
- **Effective:** Scaffold only as of 2026-09-24T09:11:09-04:00. No fills until Jordan approves starter strategies.
- **How we judge:** Same-window NAV / P&L / drawdown for active household vs momentum household; equity active vs SPY; crypto active vs BTC.


## 2026-09-24 — Active starter strategies locked (equity + crypto 15m EMA trend)

- **Sleeve:** active (equity + crypto)
- **Change:** Lock starter strategies `equity_15m_ema_trend` and `crypto_15m_ema_trend` under `sleeves/active/strategies/`. Params locked: EMA_fast=8, EMA_slow=21, ATR period 14; equity stop 1.5×ATR (RTH only); crypto stop 2×ATR (24/7). Config mirror: `sleeves/active/config/locked_strategies.json`.
- **Observation:** Strategies were scaffold-proposed earlier the same day; Jordan locked both active starters (chat 2026-09-24). Books remain all-cash; no paper fills yet.
- **Logic:** Strategy lock authorizes scanning and writing proposals with `executed: false`. It does **not** authorize booking fills into `sleeves/active/*/state/portfolio.json`. Propose-before-fill governance unchanged: each trade batch still needs Jordan yes. Alternatives considered: (1) lock + auto-fill first signals (rejected — breaks propose-before-fill), (2) lock + first paper signal pass as proposals only (chosen).
- **Jordan approval:** Chat 2026-09-24 — lock both active starter strategies. Still no fills until trade-batch yes.
- **Effective:** Strategies locked 2026-09-24T09:13:00-04:00. Positions unchanged (all cash). First proposals may be written the same day for Jordan yes/no.
- **How we judge:** After first approved fill batch (if any), track same-window active vs momentum household NAV/P&L/drawdown; until then, judge process compliance (proposals written, books untouched without yes).


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


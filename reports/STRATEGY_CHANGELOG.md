# Strategy change log

Approved tweaks to paper portfolio rules, universe, caps, or signal.
Trade fills stay in `state/ledger.jsonl`. This file is the human-readable history of strategy decisions.

## Entry template

Each entry should include:
- **Sleeve:** equity / crypto / household
- **Change:** what rule, universe, cap, or signal changed
- **Observation:** what the data or book showed (numbers when possible)
- **Logic:** options considered and why this one won
- **Jordan approval:** chat date and exact yes/conditions
- **Effective:** when the rule locked; whether positions changed yet
- **How we judge:** metric and window to evaluate the tweak

---

## 2026-09-21 — Equity tech mega-cap sleeve cap 30%

- **Sleeve:** equity
- **Change:** Added hard cap: combined AAPL + MSFT + NVDA weight max 30% of equity NAV (`config/rules.json` keys `max_tech_megacap_sleeve_pct` and `tech_megacap_tickers`).
- **Observation:** At initiation the equity book held MSFT ~14.8%, AAPL ~10.1%, NVDA ~5.8% (about 30.7% combined) under one tech factor, while still inside the 15% single-name and 40% sector caps. Morning mark 2026-09-21 left equity flat on Friday closes; concentration risk was structural, not a same-day blowup.
- **Logic:** Keep the 63-day momentum signal, but stop the three mega-cap tech names from drifting as one oversized bet. Alternatives considered: (1) do nothing until a hard sector-cap breach, (2) cut all tech to cash, (3) add a combined AAPL+MSFT+NVDA 30% sleeve cap and recycle trim into non-tech screen names or cash on the next approved rebalance. Chose (3) because it is targeted, still momentum-compatible, and measurable. Did not execute trades pre-open on stale Friday marks; trim waits for the Monday weekly proposal with fresh prices.
- **Jordan approval:** Chat 2026-09-21: lock the rule now; execute trim on the weekly pass after approving exact paper trades.
- **Effective:** Rule locked 2026-09-21T08:54:41-04:00. No positions changed yet.
- **How we judge:** Equity max drawdown and vs-SPY over the next four Monday marks versus the pre-cap book.


## 2026-09-24 — Active 15m paper experiment sleeve (parallel)

- **Sleeve:** active (new parallel)
- **Change:** Add active 15m paper experiment `$100,000` US equities + `$25,000` crypto under `sleeves/active/` (household `$125,000`). Clear separation from root momentum equity and `sleeves/crypto/` momentum. Liquid equity subset documented; crypto universe matches momentum (BTC ETH SOL AVAX LINK). Starter strategies proposed: `equity_15m_ema_trend`, `crypto_15m_ema_trend`. Freqtrade install deferred.
- **Observation:** Jordan wants apples-to-apples vs weekly momentum; Freqtrade-style higher activity on 15-minute bars without replacing the momentum books.
- **Logic:** Parallel sleeve is not a method switch on momentum books. Alternatives considered: (1) retarget momentum cadence to 15m (rejected — breaks weekly process and existing positions), (2) new parallel sleeve with matched capital (chosen). Caps mirror momentum where they still fit; active-only additions are concurrent-position limits and RTH vs 24/7 propose windows.
- **Jordan approval:** Chat 2026-09-24 widget — both universes, 15m, $125k split like momentum household.
- **Effective:** Scaffold only 2026-09-24T09:11:09-04:00. Cash books initialized; positions empty; no fills until strategy yes.
- **How we judge:** Same-window NAV/P&L/drawdown vs momentum household; active equity vs SPY; active crypto vs BTC.


## 2026-09-24 — Active starter strategies locked (equity + crypto 15m EMA trend)

- **Sleeve:** active (equity + crypto)
- **Change:** Lock starter strategies `equity_15m_ema_trend` and `crypto_15m_ema_trend` under `sleeves/active/strategies/`. Params locked: EMA_fast=8, EMA_slow=21, ATR period 14; equity stop 1.5×ATR (RTH only); crypto stop 2×ATR (24/7). Config mirror: `sleeves/active/config/locked_strategies.json`.
- **Observation:** Strategies were scaffold-proposed earlier the same day; Jordan locked both active starters (chat 2026-09-24). Books remain all-cash; no paper fills yet.
- **Logic:** Strategy lock authorizes scanning and writing proposals with `executed: false`. It does **not** authorize booking fills into `sleeves/active/*/state/portfolio.json`. Propose-before-fill governance unchanged: each trade batch still needs Jordan yes. Alternatives considered: (1) lock + auto-fill first signals (rejected — breaks propose-before-fill), (2) lock + first paper signal pass as proposals only (chosen).
- **Jordan approval:** Chat 2026-09-24 — lock both active starter strategies. Still no fills until trade-batch yes.
- **Effective:** Strategies locked 2026-09-24T09:13:00-04:00. Positions unchanged (all cash). First proposals may be written the same day for Jordan yes/no.
- **How we judge:** After first approved fill batch (if any), track same-window active vs momentum household NAV/P&L/drawdown; until then, judge process compliance (proposals written, books untouched without yes).


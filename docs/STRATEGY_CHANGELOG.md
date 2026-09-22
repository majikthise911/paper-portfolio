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

## 2026-09-21 — Deferred Monday rebalance (hold)

- **Sleeve:** household
- **Change:** No rule change. Deferred booking the Monday weekly momentum rebalance and any strategy revision for a couple of business days.
- **Observation:** Book opened ~2026-09-20; Monday 2026-09-21 was day-two. Equity tech sleeve ~30.53% (cap 30%); crypto cash ~19.57% (min 20%). Equity trailed SPY slightly since book; crypto trailed BTC.
- **Logic:** Alternatives: (1) full rebalance now, (2) trim only hard-cap breaches, (3) hold marks-only for a few sessions. Jordan chose (3): too early to revise after one open day.
- **Jordan approval:** Chat 2026-09-21 widget reply: give it a couple of business days before rebalance or strategy revision.
- **Effective:** Immediate. Positions unchanged. Caps remain breached until a later approved pass.
- **How we judge:** Revisit after US equity close Wednesday 2026-09-23 with refreshed proposals; midweek flag only if caps worsen.

## 2026-09-21 — Equity tech mega-cap sleeve cap 30%

- **Sleeve:** equity
- **Change:** Added hard cap: combined AAPL + MSFT + NVDA weight max 30% of equity NAV (`config/rules.json` keys `max_tech_megacap_sleeve_pct` and `tech_megacap_tickers`).
- **Observation:** At initiation the equity book held MSFT ~14.8%, AAPL ~10.1%, NVDA ~5.8% (about 30.7% combined) under one tech factor, while still inside the 15% single-name and 40% sector caps. Morning mark 2026-09-21 left equity flat on Friday closes; concentration risk was structural, not a same-day blowup.
- **Logic:** Keep the 63-day momentum signal, but stop the three mega-cap tech names from drifting as one oversized bet. Alternatives considered: (1) do nothing until a hard sector-cap breach, (2) cut all tech to cash, (3) add a combined AAPL+MSFT+NVDA 30% sleeve cap and recycle trim into non-tech screen names or cash on the next approved rebalance. Chose (3) because it is targeted, still momentum-compatible, and measurable. Did not execute trades pre-open on stale Friday marks; trim waits for the Monday weekly proposal with fresh prices.
- **Jordan approval:** Chat 2026-09-21: lock the rule now; execute trim on the weekly pass after approving exact paper trades.
- **Effective:** Rule locked 2026-09-21T08:54:41-04:00. No positions changed yet.
- **How we judge:** Equity max drawdown and vs-SPY over the next four Monday marks versus the pre-cap book.


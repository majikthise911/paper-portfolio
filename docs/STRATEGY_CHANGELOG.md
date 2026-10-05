# Strategy change log

Approved tweaks to paper portfolio rules, universe, caps, or signal.
Trade fills stay in `state/ledger.jsonl`. This file is the human-readable history of strategy decisions.

Format per entry: date (America/New_York), what changed, why, Jordan approval note, effective when.

## 2026-10-05, Active sleeve live daily EMA paper trading

- **Sleeve:** active (equity + crypto)
- **Change:** Wired `sleeves/active/scripts/run_active.py` to scan 15m bars, apply locked EMA entry/exit rules, and auto-book paper fills into active equity/crypto ledgers. Added `scripts/market_hours_refresh.py` (active then dashboard). Per-day fill caps: equity 8, crypto 6. Updated active rules to rule_version 2 (auto_book under standing order). Momentum books unchanged.
- **Observation:** Jordan clarified Active was supposed to be a daily trading strategy vs weekly momentum. Instead it had only booked Sep 24 opens (META/XLP/XLV + LINK) and been mark-to-market only since. That froze the experiment and made Trade history look empty for Active.
- **Logic:** Scanners already existed but wrote proposals with `executed: false` and never booked. Standing order 2026-10-05 authorizes Paper to decide and book. Wire scanners to book fills on signal, respect cash/caps/stops, and run inside the market-hours refresh path so Active actually turns over across days.
- **Jordan approval:** Chat 2026-10-05 standing order (decide and update) plus explicit clarification that Active must trade daily. Implemented immediately.
- **Effective:** 2026-10-05T10:55:09-04:00. First live scan booked on this date if signals fired.
- **How we judge:** Active trade count and Trade history fills across days; same-window Active household vs Momentum and vs Household B&H. Drop or retune only with research + standing order (or Jordan override).


## 2026-10-05, Buy-and-hold baselines on scorecard and dashboard

- **Sleeve:** household (momentum + active compare)
- **Change:** Added live buy-and-hold baselines from experiment start 2026-09-20: equity SPY 100% invested ($100k), crypto BTC 100% invested ($25k), and household B&H as the stack of those two ($125k). Wired into `reports/pnl_history.json` series (`spy`, `btc`, `household_bh`), the chart **vs B&H** toggle (view-aware: household / equity / crypto), Versus buy-and-hold cards, Current strategy copy, and the Monday method scorecard shadow list. No positions changed.
- **Observation:** Jordan asked whether we should track "just buy the stack and hold" against momentum and the active sleeve. The chart already had a SPY series at $100k 100% invested; it was missing BTC and the stacked household line, and the Monday scorecard SPY-at-80% shadow is a different peer (cash-matched rough analog for the 80% invested book).
- **Logic:** Buy-and-hold is the cleanest zero-skill control. Keep SPY-at-80% as a separate Monday shadow for the backtest/scorecard. Show 100% invested SPY/BTC/household B&H on the live dashboard so Momentum household, Active household, and Household B&H share one chart.
- **Jordan approval:** Chat 2026-10-05 standing order (decide from research and update afterward). Question posed by Jordan; Paper agreed and implemented.
- **Effective:** 2026-10-05T10:39:30-04:00. Series rebuild on each dashboard run. No trades.
- **How we judge:** Compare live Momentum household and Active household to Household B&H (and sleeve-level SPY/BTC B&H) on each mark and each Monday scorecard. Informational only; does not change the live method.


## 2026-10-05, Equity momentum top-10 rank buffer

- **Sleeve:** equity (momentum)
- **Change:** Added `rebalance.rank_buffer` in `config/rules.json` (rule_version 3): keep a holding while it stays in the top 10 on the 63-day screen; fill open slots from the top 8. No positions changed this week.
- **Observation:** Caps were clean (tech mega-cap 29.74%, cash 20.98%, META 14.37%). The screen kept 7 of 8 holdings in its top 8. The only cohort swap wanted was XLV (rank 9, +3.00%) out for QQQ (rank 7, +3.81%), a 0.81 pt gap, at about $29.9k gross turnover (~30% of equity NAV). QQQ also overlaps MSFT, NVDA, AAPL, META, and AMZN already held. Walk-forward 1y: weekly top 8 +3.66% with 9.0x turnover vs top-10 buffer +5.54% with 6.2x; last 3m buffer slightly worse (-3.22% vs -2.71%).
- **Logic:** Options were (1) book the full allocate.py rebalance, (2) hold with no rule change, (3) adopt the top-10 rank buffer and hold this week. Chose (3): standard momentum practice for cutting churn on near-tie ranks, keeps the 63d signal unchanged, and 1y evidence is positive. Crypto deltas were only ~$694 of drift and were skipped. Method stays weekly momentum. Monday scorecard now tracks mean reversion and SPY-at-80% as shadow lines, plus a no-buffer shadow for this judge window.
- **Jordan approval:** Chat 2026-10-05 ~10:16 ET standing order: Paper decides trade and rule changes from research, books what seems best, and updates afterward. Jordan can still override. This week's Monday recommendation is applied under that order.
- **Effective:** Rule locked 2026-10-05T10:18:11-04:00. Positions unchanged (hold both sleeves).
- **How we judge:** Over the next four Mondays, track weekly turnover, equity vs SPY, and a shadow no-buffer book in the scorecard. Drop the buffer if it trails that shadow by more than 1 pt over the window.


## 2026-09-21, Equity tech mega-cap sleeve cap 30%

- **Sleeve:** equity
- **Change:** Added hard cap: combined AAPL + MSFT + NVDA weight max 30% of equity NAV. Tickers listed in `config/rules.json` as `tech_megacap_tickers`.
- **Why:** Reduce single-factor tech concentration while keeping the 63-day momentum signal. Combined weight was about 31% at initiation.
- **Jordan approval:** Chat 2026-09-21: lock rule now; execute trim on weekly pass after approving exact paper trades.
- **Effective:** Rule locked 2026-09-21T08:54:41-04:00. No positions changed yet. First trim awaits Monday weekly proposal + yes.
- **How we judge:** Equity max drawdown and vs-SPY over the next four Monday marks versus the pre-cap book.


## 2026-09-24, Active 15m paper experiment sleeve (parallel)

- **Sleeve:** active (new parallel)
- **Change:** Add active 15m paper experiment with $100,000 US equities + $25,000 crypto under `sleeves/active/` (household $125k). Separate config/state/reports from momentum books.
- **Observation:** Jordan wants apples-to-apples vs weekly momentum household; Freqtrade-style higher activity on 15m bars without switching the momentum method.
- **Logic:** Parallel sleeve, not a method switch on momentum books. Keep root equity and `sleeves/crypto/` untouched. Scaffold cash-only books; no fills until strategy yes.
- **Jordan approval:** Chat 2026-09-24 widget, both universes, 15m, $125k split ($100k+$25k).
- **Effective:** Scaffold only as of 2026-09-24T09:11:09-04:00. No fills until Jordan approves starter strategies.
- **How we judge:** Same-window NAV / P&L / drawdown for active household vs momentum household; equity active vs SPY; crypto active vs BTC.


## 2026-09-24, Active starter strategies locked (equity + crypto 15m EMA trend)

- **Sleeve:** active (equity + crypto)
- **Change:** Lock starter strategies `equity_15m_ema_trend` and `crypto_15m_ema_trend` under `sleeves/active/strategies/`. Params locked: EMA_fast=8, EMA_slow=21, ATR period 14; equity stop 1.5×ATR (RTH only); crypto stop 2×ATR (24/7). Config mirror: `sleeves/active/config/locked_strategies.json`.
- **Observation:** Strategies were scaffold-proposed earlier the same day; Jordan locked both active starters (chat 2026-09-24). Books remain all-cash; no paper fills yet.
- **Logic:** Strategy lock authorizes scanning and writing proposals with `executed: false`. It does **not** authorize booking fills into `sleeves/active/*/state/portfolio.json`. Propose-before-fill governance unchanged: each trade batch still needs Jordan yes. Alternatives considered: (1) lock + auto-fill first signals (rejected, breaks propose-before-fill), (2) lock + first paper signal pass as proposals only (chosen).
- **Jordan approval:** Chat 2026-09-24, lock both active starter strategies. Still no fills until trade-batch yes.
- **Effective:** Strategies locked 2026-09-24T09:13:00-04:00. Positions unchanged (all cash). First proposals may be written the same day for Jordan yes/no.
- **How we judge:** After first approved fill batch (if any), track same-window active vs momentum household NAV/P&L/drawdown; until then, judge process compliance (proposals written, books untouched without yes).


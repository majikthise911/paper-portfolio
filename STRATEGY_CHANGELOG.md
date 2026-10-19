# Strategy change log

Approved tweaks to paper portfolio rules, universe, caps, or signal.
Trade fills stay in `state/ledger.jsonl`. This file is the human-readable history of strategy decisions.

Format per entry: date (America/New_York), what changed, why, Jordan approval note, effective when.

## 2026-10-19, Equity momentum rebalances monthly (first Monday), weekly shadow kept

- **Sleeve:** momentum equity only (crypto stays weekly under rule v2)
- **Change:** `config/rules.json` rule_version 3 to 4. `rebalance.cadence` is now `monthly`, `schedule: first_monday_of_month`, first monthly rebalance 2026-11-02. Signal (63d return, 252d filter), top-10 rank buffer, buy-from-top-8, and all hard caps are unchanged. Non-first Mondays are mark and scorecard only, except a hard-cap breach can still force a trade. Today's AMZN to BRK-B rotation is the last weekly-cadence trade. A weekly shadow book (`state/shadow_weekly.json`) starts from the post-trade book on 2026-10-19 and is re-run each Monday under the old weekly rule, never booked.
- **Observation:** In the 1y walk-forward (`reports/method_backtest_2026-10-19.json`), monthly top 8 returned +4.45% vs +4.51% for the live weekly buffer (a tie), with a shallower drawdown (-7.82% vs -8.64%) and a third less turnover (4.3x vs 6.3x). Over the last 3 months monthly returned +3.35% vs -0.07% for weekly (SPY +3.11%).
- **Logic:** Options were keep weekly, go monthly, switch to weekly mean reversion (+17.04% 1y but 10.8x turnover and a different method), or drop to SPY. Monthly matches the 1y return with less churn and drawdown and leads over 3m. It changes cadence only, so the experiment still tests momentum. Mean reversion stays a shadow until the 11/02 checkpoint.
- **Jordan approval:** Chat 2026-10-05 standing order (Paper decides rule changes from research and updates afterward; Jordan may override).
- **Effective:** 2026-10-19. First monthly rebalance 2026-11-02.
- **How we judge:** Four monthly rebalances (2026-11-02, 12-07, 2027-01-04, 02-01) vs the weekly shadow. Revert to weekly if monthly trails the shadow by more than 1.5 pts or adds more than 1 pt of drawdown.

## 2026-10-19, Crypto sizing script now uses rule v2

- **Sleeve:** momentum crypto (tooling only, no rule change)
- **Change:** Rewrote `scripts/crypto_allocate.py` to size the v2 book: BTC core at `btc_core_pct` (50%), top `satellite_top_n` (2) names from `satellite_pool` by 63d return at `satellite_weight_pct` (15%) each, rest cash with the 20% floor. It now proposes deltas against the current book at live prices (sells first), with bands from `rules.json` (`core_band_pct` 1 pt, `satellite_band_pct` 2 pts, `min_trade_usd` $100), and scales buys down if cash would fall under the floor.
- **Observation:** On 2026-10-19 the old script still proposed the pre-10/12 strength-weighted top-5 book and ignored the BTC core, so the weekly trades had to be sized by hand.
- **Logic:** The sizing tool has to match the live rule or the weekly routine proposes the wrong book. Run on 2026-10-19 it reproduced the hand-sized trades (sell LINK, trim BTC to 50%, buy SOL to 15%, hold AVAX within band).
- **Jordan approval:** Standing order 2026-10-05.
- **Effective:** 2026-10-19.

## 2026-10-19, Active daily entry cap: audit and booking-time re-check

- **Sleeve:** active equity and crypto
- **Change:** `run_active.py` re-reads today's BUY entries from the ledger right before booking and drops any planned BUY beyond `max_new_trades_per_day` (note `entry_skip_daily_cap_recheck:<tickers>`). Reports now show entries and exits after the run separately. Added `sleeves/active/scripts/audit_daily_cap.py`, which lists entries and exits per day and exits nonzero if any day has more entries than the cap.
- **Observation:** The 10/14 (10 fills) and 10/16 (11 fills) summaries were read as cap breaches. The ledger shows 5 entries and 5 exits on 10/14 and 5 entries and 6 exits on 10/16. No day since 9/24 has had more than 8 equity entries or 6 crypto entries. Exits are exempt by design (rule v3, 2026-10-06), so the cap held. The real gap was that the cap was only checked against the ledger at the start of a run, so two overlapping runs (like the 10/9 stale-Marvin run) could each see a free budget.
- **Logic:** Keep the entries-only cap and close the overlap gap with a check at booking time. Report entries and exits separately so the daily summary does not count exits against the cap.
- **Jordan approval:** Standing order 2026-10-05, extended to Active.
- **Effective:** Next market-hours refresh after this commit.


## 2026-10-09, Active crypto 1h trend filter on entries

- **Sleeve:** active crypto only (equity unchanged)
- **Change:** Added `htf_filter: {enabled: true, interval: "1h", ema_fast: 8, ema_slow: 21}` to active crypto `rules.json` (rule_version 6). A new crypto BUY on the 15m EMA signal is allowed only if the 1h EMA8 is above the 1h EMA21, computed on closed 1h bars only (new `htf_trend` in `ema_scan_lib.py`, Freqtrade informative-pair style). Skips log `entry_skip_htf_trend:<ticker>` (or `:no_data` if 1h bars are unavailable, fail closed) and use no daily-cap slot or position slot. Exits (15m trend break / ATR stop / dust) are unchanged.
- **Observation:** 15m crypto signals churned all week. On 10/9 LINK was sold at 9:40 from the overnight buy, then bought and sold again 1:05 to 1:32 and 3:24 to 3:34. BTC round-tripped repeatedly (10/6 sold 10:20, rebought 10:37, sold 11:42; 10/9 bought 10:57, sold 12:41).
- **Logic:** Requiring the higher timeframe trend to agree is a standard way to cut lower-timeframe whipsaw. Replay of the 11 actual Active crypto BUYs from 10/06 to 10/09 against closed 1h bars: the filter would have allowed 5 (realized -$601.49, mostly the 10/6 AVAX entry at -$472.90) and blocked 6 (realized +$13.68). Of the 5 entries closed within 2 hours, it blocks 2 (both 10/9 LINK, -$21.72) and allows 3 (10/6 LINK, 10/6 BTC, 10/9 BTC, -$31.08). It would also have blocked the four 10/8 evening entries, which netted +$35.40. So the replay shows a small improvement on churn, not a big one, and the 13:05 LINK block was marginal (1h EMAs within 0.05%).
- **Jordan approval:** Chat 2026-10-05 standing order for Active (Paper decides rule changes from research and updates afterward; Jordan may override), extended explicitly to Active ("same thing goes for active").
- **Effective:** Next market-hours refresh after this commit on 2026-10-09. No trades booked by this change.
- **How we judge:** At the Monday review, alongside a backtest of a 1h-bar crypto strategy. Keep the filter if it cuts round trips without missing clear trends; replace it if the 1h-bar strategy does better outright.


## 2026-10-08, Active equity skip entries in first 30 minutes after the open

- **Sleeve:** active equity only (crypto unchanged)
- **Change:** Added `position_caps.entry_open_delay_minutes: 30` to active equity `rules.json` (rule_version 6). In `run_active.py`, when that delay is set and the sleeve requires RTH (equity), new BUY entries are blocked from 09:30 ET until 09:30+delay (so before 10:00 ET with delay 30). Skips log `entry_skip_opening_window:delay_<N>m` and use no daily-cap slot and no position slot. Exits (trend break / ATR stop / dust) still run any time during RTH. Crypto keeps delay 0 / unset and is unaffected. Helper: `in_entry_opening_window`.
- **Observation:** On 10/8 Active bought GOOGL and AMZN at the 9:33 refresh and sold both at 9:56 (GOOGL stopped out at -$95.53, AMZN trend break at -$19.35). On 10/6, JPM bought at 9:51 was sold at 10:47.
- **Logic:** 15m EMA signals off the opening bars are noisy (opening auction and gap volatility), and skipping the first 30 minutes is a common intraday filter. Signal, stops, sizing, cooldown, and dust rules are unchanged.
- **Jordan approval:** Chat 2026-10-05 standing order for Active (Paper decides rule changes from research and updates afterward; Jordan may override), extended explicitly to Active ("same thing goes for active").
- **Effective:** Next market-hours refresh after this commit on 2026-10-08. No trades booked by this change.
- **How we judge:** At the Monday review, compare the hit rate of opening-window trades so far vs later entries; drop the rule if it misses clear trends.


## 2026-10-06, Active per-ticker re-entry cooldown (1 hour)

- **Sleeve:** active (equity + crypto)
- **Change:** Added `position_caps.reentry_cooldown_bars: 4` to both active `rules.json` files (rule_version 5). After any SELL of a ticker, `run_active.py` blocks new BUYs of that same ticker for 4 bars of 15m (1 hour). Last exit time comes from ledger SELL fills (new `last_exit_times` in `ema_scan_lib.py`). Skips log `entry_skip_cooldown:<ticker>:<minutes_left>m` and use no cap slot or position slot. Modeled on Freqtrade's CooldownPeriod protection. Exits are not affected.
- **Observation:** On 10/6 Active crypto round-tripped within 20 to 40 minutes three times: AVAX sold at 11.41 and rebought at 11.43; LINK bought 9:51, sold 10:10, rebought 10:37 at 14.02; BTC sold at 86,041.72 at 10:20 and rebought at 86,206.53 at 10:37.
- **Logic:** 15m EMA crosses whipsaw in chop, so the sleeve sells and then buys back the same name a bar or two later at a worse price. A cooldown is the standard Freqtrade protection for this and costs little in real trends, since a genuine trend is still in place an hour later. Signal, stops, sizing, caps, and the dust rules are unchanged.
- **Jordan approval:** Chat 2026-10-05 standing order for Active (Paper decides rule changes from research and updates afterward; Jordan may override), extended explicitly to Active ("same thing goes for active").
- **Effective:** Next market-hours refresh after this commit on 2026-10-06. No trades booked by this change.
- **How we judge:** At the Monday review, compare Active realized P&L and fill count against the prior week. Drop or shorten the cooldown if it causes clearly missed trends.


## 2026-10-06, Active exits uncapped and $1,000 minimum order

- **Sleeve:** active (equity + crypto)
- **Change:** In `sleeves/active/scripts/run_active.py`, exits (EMA trend break, bearish cross, ATR stop) no longer count against `max_new_trades_per_day` and always run even when the cap is hit (equity exits still only during RTH). Only BUY entries count toward the cap (equity 8, crypto 6), via new `count_entries_today` in `ema_scan_lib.py`. Added `position_caps.min_order_usd: 1000` to both active `rules.json` files: any buy under $1,000 notional is skipped with an `entry_skip_below_min_order` note and uses no cap slot or position slot. Added `daily_cap_counts: entries_only` and `exits_exempt_from_daily_cap: true`. Bumped active equity and crypto `rule_version` 2 to 3.
- **Observation:** On 10/5 the equity cap filled with morning churn and then blocked an MSFT exit signal all afternoon. On 10/6 at 9:51 ET the sleeve booked 1-share XLP ($81) and XLU ($41) top-ups that used two cap slots (and two of eight position slots) for almost no exposure.
- **Logic:** Exits are risk control and should never be capped; a spam cap exists to limit new risk, not to trap a position the rules say to close. Dust orders add churn and burn cap slots without meaningful exposure, so a $1,000 floor (about 1% of equity NAV, 4% of crypto NAV) filters them while leaving normal entries untouched. Signal, stops, and sizing caps are unchanged.
- **Jordan approval:** Chat 2026-10-05 standing order for Active (Paper decides rule changes from research and updates afterward; Jordan may override). Jordan extended the same standing order explicitly to Active ("same thing goes for active").
- **Effective:** Next market-hours refresh after this commit on 2026-10-06. No trades booked by this change. Existing 1-share XLP and XLU positions stay until their own exit signals fire.
- **Follow-up (rule_version 4, same day):** Open positions worth less than `min_order_usd` are now dust. Dust does not count toward `max_concurrent_positions` and, with `liquidate_dust_positions: true`, is sold as an uncapped exit on the next run (equity during RTH, crypto any time), logged as `exit_dust_below_min_order:<ticker>`. This frees the two slots held by the 1-share XLP and XLU positions; the next scheduled refresh books those sells.
- **How we judge:** Over the next two weeks, count exits that would have been blocked under the old cap (target: zero blocked) and sub-$1,000 buys (target: zero). Compare Active household vs Momentum on the same marks. Revisit the floor if it skips more than a few otherwise valid entries per week.


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


## 2026-10-12: Momentum crypto rule v2, BTC core 50% + top-2 momentum alts

**Observation:** Momentum crypto trailed BTC two Mondays running (-1.55% vs BTC +1.67% since 9/20). The 9/29 SOL-for-BTC swap cost about 6.8 pts. scripts/btc_core_backtest.py: BTC 50% + top-2 beat the top-4 method on 1y (-32.0% vs -44.7%), 6m (+10.8% vs +5.8%) and 3m (+20.6% vs +5.8%) with lower 1y drawdown.

**Logic:** BTC-only exception to the 25% single-name cap: BTC fixed at 50% NAV, rebalanced weekly. 63d momentum top 2 of ETH/SOL/AVAX/LINK at 15% each (today AVAX +69%, LINK +58%), other names max 15%, 20% cash floor unchanged. Booked at live prices: sold all SOL and ETH, trimmed AVAX and LINK, bought 0.14908 BTC. A frozen shadow of the old top-4 book sits in sleeves/crypto/state/portfolio.json (shadow_old_top4). Judge Mondays 10/19, 10/26, 11/2, 11/9; revert if the new book trails the shadow by more than 2 pts.

## 2026-10-12: Active crypto rule v7, core/satellite

**Observation:** The 15m EMA crypto book is -0.98% since 9/24 with many whipsaw round trips; v3 to v6 filters helped only marginally (HTF replay: blocked buys netted +$13.68, allowed buys lost $601.49). Holding BTC beat it.

**Logic:** 60% NAV BTC core bought at live price (0.180075 BTC). Satellite up to 20% on 4h EMA 8/21 with 2.5x ATR stop, 20% cash floor. The 15m crypto scanner is disabled in run_active.py (legacy_15m_entries_enabled=false), so the market-hours refresh no longer trades 15m crypto. The 4h satellite logic is not implemented yet, so satellite_enabled=false and the sleeve holds 60% BTC and 40% cash until it is built.

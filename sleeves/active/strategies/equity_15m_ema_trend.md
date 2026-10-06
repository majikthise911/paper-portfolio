# equity_15m_ema_trend (locked starter)

**Sleeve:** active equity  
**Timeframe:** 15-minute bars  
**Session:** US regular trading hours only (about 09:30–16:00 ET)  
**Direction:** long only (v1)

## Logic (plain English)

Trade a short list of liquid ETFs and mega-caps on 15-minute bars using a simple trend filter. Compute a fast exponential moving average (EMA) and a slow EMA on each name (defaults: 8-bar and 21-bar EMAs on 15m closes). Enter long when the fast EMA crosses above the slow EMA and the latest close is also above the slow EMA, so we are not buying into a still-falling tape. Exit when the fast EMA crosses back below the slow EMA, or if price falls a fixed stop distance from entry (1.5 times the recent 14-bar average true range), whichever comes first. Do not open new equity entries outside regular hours. Respect `equity/config/rules.json` caps: max 15% in one name, max 80% invested (20% cash floor), max eight concurrent positions, and the 30% AAPL+MSFT+NVDA tech mega-cap sleeve cap. Paper fills auto-book under Jordan standing order 2026-10-05 (Paper decides; Jordan may override).

## Locked params (2026-09-24)

- EMA_fast = 8
- EMA_slow = 21
- ATR period = 14
- Stop = 1.5 × ATR
- Session = RTH only

## Risk caps (from rules)

- Max single name 15% of sleeve NAV  
- Min cash 20%  
- Max concurrent positions 8  
- Tech mega-cap (AAPL+MSFT+NVDA) combined 30%  
- Long only; no shorts/leverage in v1

## Status

**Locked** 2026-09-24. **Live daily paper trading** as of 2026-10-05.

Runner: `sleeves/active/scripts/run_active.py` (also via `scripts/market_hours_refresh.py`).
Exits on EMA bearish cross or 1.5×ATR stop. Entries on bullish cross/state into open slots, respecting caps and a per-day entry cap. Exits are never capped and do not use cap slots; buys under `min_order_usd` ($1,000) are skipped as dust.
Auto-books paper fills under Jordan standing order 2026-10-05. Never places real broker trades. Momentum books untouched.

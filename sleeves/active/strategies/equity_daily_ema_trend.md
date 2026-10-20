# equity_daily_ema_trend (Active equity rule v8, 2026-10-20)

**Sleeve:** active equity
**Timeframe:** daily bars
**Replaces:** equity_15m_ema_trend (kept for history)

## Logic

- Signal on daily closes: EMA10 and EMA30. Long when EMA10 > EMA30 and price > EMA30.
- Evaluate once per day, only at the 3:23 PM ET market-hours refresh (window 15:00 to 16:00 ET). Today's in-progress daily bar stands in for the close. The 11:23 refresh and any other run mark positions only and make no equity fills. `state/daily_eval_marker.json` blocks a second evaluation on the same date.
- Exit when the daily trend breaks (EMA10 < EMA30 or price < EMA30), but only after a minimum hold of 3 trading days (weekdays since entry date).
- Hard stop: exit at any evaluation if price is 8% or more below average cost, regardless of hold time.
- Max 4 equity fills per day. Buys and trend exits both count; hard stops are exempt.
- Entries rank by bullish cross first, then trend strength (EMA gap in ATR units).
- Caps unchanged: 15% per name, 20% minimum cash, 8 concurrent positions, 30% AAPL+MSFT+NVDA, $1,000 minimum order.

## Why these values

10/30 daily EMAs are a common medium-swing pair: slow enough to stop the intraday whipsaw that cost the 15m version money, fast enough to react within a couple of weeks. The 3 day hold stops buy-then-sell-next-morning churn. The -8% stop caps a single bad name at about 1.2% of the sleeve at a 15% weight.

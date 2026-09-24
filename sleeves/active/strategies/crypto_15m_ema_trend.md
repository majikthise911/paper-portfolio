# crypto_15m_ema_trend (locked starter)

**Sleeve:** active crypto  
**Timeframe:** 15-minute bars  
**Session:** 24/7 paper marks  
**Direction:** long only (v1)  
**Universe:** BTC-USD, ETH-USD, SOL-USD, AVAX-USD, LINK-USD

## Logic (plain English)

Same idea as the equity starter, adapted for always-on crypto. On each of the five spot names, compute fast and slow EMAs on 15-minute closes (defaults: 8-bar and 21-bar). Enter long on a fast-above-slow cross with close still above the slow EMA. Exit on a fast-below-slow cross or a volatility stop (2 times the recent 14-bar average true range, slightly wider than equity because crypto moves more). Cap risk with `crypto/config/rules.json`: max 25% in one name, max 80% invested (20% cash floor), max four concurrent positions. No perpetual futures, no leverage, no shorts in v1. Paper fills only after Jordan yes on a proposal batch. Never write into the momentum crypto sleeve at `sleeves/crypto/`.

## Locked params (2026-09-24)

- EMA_fast = 8
- EMA_slow = 21
- ATR period = 14
- Stop = 2 × ATR
- Session = 24/7

## Risk caps (from rules)

- Max single name 25% of sleeve NAV  
- Min cash 20%  
- Max concurrent positions 4  
- Long only; no shorts/leverage/perps in v1  

## Status

**Locked** 2026-09-24. Jordan yes (chat 2026-09-24). Still no fills until trade-batch yes on a written proposal (`executed: false` until then).

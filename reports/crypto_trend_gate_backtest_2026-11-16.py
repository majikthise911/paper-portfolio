#!/usr/bin/env python3
"""2026-11-16 backtest: crypto v2 vs v2 + BTC 200d trend gate (paper research only).
v2: weekly Monday rebalance, BTC 50%, top-2 alts by 63d (252d > -20%) at 15% each, rest cash.
Gate: if BTC close < its 200d SMA at rebalance, hold BTC 40% and 60% cash (no alts)."""
import json, yfinance as yf, pandas as pd, numpy as np
coins = ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD"]
px = yf.download(coins, period="5y", interval="1d", progress=False, auto_adjust=True)["Close"].dropna()
sma = px["BTC-USD"].rolling(200).mean()
r63, r252 = px / px.shift(63) - 1, px / px.shift(252) - 1
def run(gate, start):
    d = px.index[px.index >= start]
    w = pd.Series(0.0, index=coins); nav = 1.0; navs = []
    for i, t in enumerate(d):
        if i:
            nav *= 1 + float((w * (px.loc[t] / px.loc[d[i-1]] - 1)).sum())
        navs.append(nav)
        if t.weekday() == 0:
            w = pd.Series(0.0, index=coins)
            if gate and px.loc[t, "BTC-USD"] < sma.loc[t]:
                w["BTC-USD"] = 0.4
            else:
                w["BTC-USD"] = 0.5
                alts = [c for c in coins[1:] if r252.loc[t, c] > -0.2]
                for c in sorted(alts, key=lambda c: -r63.loc[t, c])[:2]:
                    w[c] = 0.15
    s = pd.Series(navs, index=d)
    return dict(ret_pct=round((s.iloc[-1] - 1) * 100, 2), max_dd_pct=round(float((s / s.cummax() - 1).min()) * 100, 2))
end = px.index[-1]; out = {"as_of": str(end.date())}
for lab, yrs in [("1y", 1), ("2y", 2), ("3y", 3)]:
    st = end - pd.DateOffset(years=yrs)
    btc = px["BTC-USD"][px.index >= st]
    out[lab] = dict(v2=run(False, st), gated=run(True, st), btc_hold=round((btc.iloc[-1] / btc.iloc[0] - 1) * 100, 2))
out["btc_below_sma200_now"] = bool(px["BTC-USD"].iloc[-1] < sma.iloc[-1])
out["btc_vs_sma200_pct"] = round((px["BTC-USD"].iloc[-1] / sma.iloc[-1] - 1) * 100, 2)
print(json.dumps(out, indent=1))
json.dump(out, open("reports/crypto_trend_gate_backtest_2026-11-16.json", "w"), indent=2)

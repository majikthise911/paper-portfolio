#!/usr/bin/env python3
"""2026-11-23 proposal search: equity momentum variants vs the live-like control. Evidence only, never trades.
All: monthly (21d) rebalance, 80% invested, 10 bps per side, same-close fills.
control: top-8 by 63d, 252d>-20% filter, top-10 buffer (live v4 approx).
blend: top-8 by average rank of 63d, 126d and 252d-skip-21d returns, same filter and buffer.
spy_core: 40% SPY + top-4 by 63d at 10% each (same filter, top-6 buffer).
absmom: control, but slots with 63d <= 0 sit in cash."""
import json, warnings
warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
uni = json.load(open(ROOT / "config/universe.json"))
eq = list(dict.fromkeys(uni["etfs"] + uni["mega_caps"]))
P = yf.download(eq, period="7y", auto_adjust=True, progress=False)["Close"].dropna(how="all").ffill()
P = P.dropna(axis=1, thresh=int(len(P) * 0.9))
R = P.pct_change().fillna(0)

def score(i, kind):
    r63 = P.iloc[i] / P.iloc[i - 63] - 1
    r12 = P.iloc[i] / P.iloc[i - 252] - 1
    ok = r12 > -0.2
    if kind == "blend":
        r126 = P.iloc[i] / P.iloc[i - 126] - 1
        r12_1 = P.iloc[i - 21] / P.iloc[i - 252] - 1
        s = -(r63.rank(ascending=False) + r126.rank(ascending=False) + r12_1.rank(ascending=False)) / 3
    else:
        s = r63
    return s[ok].dropna().sort_values(ascending=False), r63

def weights(i, held, kind):
    s, r63 = score(i, kind)
    n, buf = (4, 6) if kind == "spy_core" else (8, 10)
    pool = s.drop("SPY") if kind == "spy_core" and "SPY" in s.index else s
    keep = [h for h in held if h in list(pool.index[:buf])]
    top = keep + [t for t in pool.index if t not in keep][: n - len(keep)]
    w = pd.Series(0.0, index=P.columns)
    if kind == "spy_core":
        w["SPY"] = 0.4; w[top] += 0.1
    else:
        live = [t for t in top if r63[t] > 0] if kind == "absmom" else top
        if live: w[live] = 0.1
    return w, top

def run(start, kind):
    w = pd.Series(0.0, index=P.columns); nav = 1.0; navs = []; held = []; turn = 0.0
    for k, i in enumerate(range(start, len(P))):
        if k > 0:
            r = (w * R.iloc[i]).sum(); nav *= 1 + r
            w = w * (1 + R.iloc[i]) / (1 + r)
        if k % 21 == 0:
            nw, held = weights(i, held, kind)
            t = (nw - w).abs().sum(); turn += t / 2; nav *= 1 - t * 0.001; w = nw
        navs.append(nav)
    s = pd.Series(navs, index=P.index[start:])
    return dict(ret=round((s.iloc[-1] - 1) * 100, 2), dd=round((s / s.cummax() - 1).min() * 100, 2), turn=round(turn, 1))

out = {"as_of": str(P.index[-1].date()), "windows": {}}
for label, days in [("3m", 63), ("6m", 126), ("1y", 252), ("2y", 504), ("3y", 756), ("5y", 1260)]:
    st = len(P) - days - 1
    spy = P["SPY"].iloc[st:]
    out["windows"][label] = dict(start=str(P.index[st].date()),
        **{k: run(st, k) for k in ["control", "blend", "spy_core", "absmom"]},
        spy_80pct=round((spy.iloc[-1] / spy.iloc[0] - 1) * 80, 2))
w, top = weights(len(P) - 1, [], "spy_core")
out["spy_core_today"] = {t: round(v, 3) for t, v in w.items() if v}
w, top = weights(len(P) - 1, [], "blend")
out["blend_today"] = top
Path(ROOT / "reports/equity_variants_backtest_2026-11-23.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))

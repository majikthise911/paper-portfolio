#!/usr/bin/env python3
"""2026-11-23 proposal backtest: absolute-momentum gate on the equity momentum book.
Control: monthly (21d) top-8 by 63d return, 252d > -20% filter, top-10 rank buffer, 80% invested equal weight.
Gate: same picks, but a pick only gets its slot if its own 63d return is > 0; otherwise that slot sits in cash.
Same-close fills, 10 bps per side cost applied. Evidence only, never trades."""
import json, warnings
warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
uni = json.load(open(ROOT / "config/universe.json"))
eq = list(dict.fromkeys(uni["etfs"] + uni["mega_caps"]))
P = yf.download(eq, period="6y", auto_adjust=True, progress=False)["Close"].dropna(how="all").ffill()
P = P.dropna(axis=1, thresh=int(len(P) * 0.9))
R = P.pct_change().fillna(0)

def picks(i, held, gate):
    r = P.iloc[i] / P.iloc[i - 63] - 1
    r12 = P.iloc[i] / P.iloc[i - 252] - 1
    r = r[r12 > -0.2].dropna().sort_values(ascending=False)
    keep = [h for h in held if h in list(r.index[:10])]
    top = keep + [t for t in r.index if t not in keep][: 8 - len(keep)]
    if gate:
        top = [t for t in top if r[t] > 0]
    return top

def run(start, gate):
    w = pd.Series(0.0, index=P.columns); nav = 1.0; navs = []; held = []; turn = 0.0; inv = []
    for k, i in enumerate(range(start, len(P))):
        if k > 0:
            r = (w * R.iloc[i]).sum(); nav *= 1 + r
            w = w * (1 + R.iloc[i]) / (1 + r)
        if k % 21 == 0:
            pk = picks(i, held, gate)
            nw = pd.Series(0.0, index=P.columns)
            if pk: nw[pk] = 0.8 / 8
            t = (nw - w).abs().sum(); turn += t / 2; nav *= 1 - t * 0.001
            w = nw; held = pk if not gate else picks(i, held, False)
            inv.append(nw.sum())
        navs.append(nav)
    s = pd.Series(navs, index=P.index[start:])
    return dict(total_ret=round((s.iloc[-1] - 1) * 100, 2), max_dd=round((s / s.cummax() - 1).min() * 100, 2),
                turnover_x=round(turn, 2), avg_invested_pct=round(sum(inv) / len(inv) * 100, 1))

out = {"as_of": str(P.index[-1].date()), "windows": {}}
for label, days in [("3m", 63), ("6m", 126), ("1y", 252), ("2y", 504), ("3y", 756), ("5y", 1260)]:
    st = len(P) - days - 1
    if st < 253: continue
    spy = P["SPY"].iloc[st:]
    out["windows"][label] = dict(start=str(P.index[st].date()), control_monthly_mom=run(st, False),
        absmom_gate=run(st, True), spy_80pct=round((spy.iloc[-1] / spy.iloc[0] - 1) * 80, 2),
        spy_dd=round((spy / spy.cummax() - 1).min() * 100, 2))
r = P.iloc[-1] / P.iloc[-64] - 1
out["today_63d_positive"] = sorted([t for t in r.index if r[t] > 0])
Path(ROOT / "reports/equity_absmom_backtest_2026-11-23.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))

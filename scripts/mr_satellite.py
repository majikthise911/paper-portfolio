#!/usr/bin/env python3
"""Mean-reversion satellite for the equity momentum sleeve (adopted 2026-11-02).

Rule: hold the bottom-8 names by 63-day return from reports/screen_latest.json,
equal weight, total target = 10% of equity NAV. Rebalanced weekly on Mondays
after the 09:30 open. Positions carry "book": "mr_satellite" in
state/portfolio.json so allocate.py ignores them. A bottom-8 name that is also
held by the momentum book is skipped. Drift band: no trade if a held name is
within 25% of its target dollars. Paper only.

Usage: .venv/bin/python scripts/mr_satellite.py            (propose, prints JSON)
The Monday pass books the proposed fills at live 1m prices.
"""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
N, SAT_PCT, BAND = 8, 0.10, 0.25

def plan(pf, screen, prices):
    nav = float(pf["nav"])
    pos = pf.get("positions") or {}
    mom = {t for t, p in pos.items() if p.get("book", "momentum") == "momentum" and p.get("shares", 0) > 0}
    bottom = [r["ticker"] for r in screen["rankings"] if r["ticker"] not in mom][-N:]
    per = nav * SAT_PCT / N
    fills = []
    for t, p in pos.items():
        if p.get("book") == "mr_satellite" and t not in bottom:
            fills.append(dict(ticker=t, side="SELL", shares=int(p["shares"])))
    for t in bottom:
        px = prices[t]
        tgt = int(per // px)
        cur = int(pos.get(t, {}).get("shares", 0)) if pos.get(t, {}).get("book") == "mr_satellite" else 0
        if cur and abs(cur * px - per) <= BAND * per:
            continue
        d = tgt - cur
        if d:
            fills.append(dict(ticker=t, side="BUY" if d > 0 else "SELL", shares=abs(d)))
    return dict(bottom8=bottom, per_name_usd=round(per, 2), fills=fills)

if __name__ == "__main__":
    import yfinance as yf
    pf = json.load(open(ROOT / "state/portfolio.json"))
    sc = json.load(open(ROOT / "reports/screen_latest.json"))
    tick = [r["ticker"] for r in sc["rankings"]]
    prices = {t: float(yf.Ticker(t).history(period="5d")["Close"].iloc[-1]) for t in tick[-12:]}
    print(json.dumps(plan(pf, sc, prices), indent=1))

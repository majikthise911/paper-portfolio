#!/usr/bin/env python3
"""2026-11-23 Monday weekly pass booking (paper only).
Equity momentum: mark-only (not first Monday of month).
MR satellite: weekly rebalance per scripts/mr_satellite.py.
Crypto v2: ETH fails 252d secondary filter (-26.9%) -> sell; no other eligible alt (SOL, AVAX also fail), slot to cash; BTC and LINK in band.
"""
import json, math, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import yfinance as yf
sys.path.insert(0, "scripts")
from mr_satellite import plan as mr_plan

BOOK = "--book" in sys.argv
NY = ZoneInfo("America/New_York")
now = datetime.now(NY).replace(microsecond=0)
R = Path(".")
pf_p = R / "state/portfolio.json"
cpf_p = R / "sleeves/crypto/state/portfolio.json"
pf = json.load(open(pf_p))
cpf = json.load(open(cpf_p))
sc = json.load(open(R / "reports/screen_latest.json"))
sector = {r["ticker"]: r["sector"] for r in sc["rankings"]}

def live(tks):
    out = {}
    for t in tks:
        h = yf.Ticker(t).history(period="1d", interval="1m")
        if h.empty:
            h = yf.Ticker(t).history(period="5d", interval="1m")
        if h.empty:
            h = yf.Ticker(t).history(period="5d", interval="1d")
        out[t] = (round(float(h["Close"].iloc[-1]), 4), h.index[-1].tz_convert(NY).isoformat() if hasattr(h.index[-1], "tz_convert") else str(h.index[-1]))
    return out

# Equity MR satellite
eq_needed = set(pf["positions"]) | {r["ticker"] for r in sc["rankings"][-12:]}
px = live(sorted(eq_needed))
# refresh nav with live prices
pos = pf["positions"]
cash0 = float(pf["cash"])
nav = cash0 + sum(p["shares"] * px[t][0] for t, p in pos.items())
pf_tmp = dict(pf)
pf_tmp["nav"] = nav
mp = mr_plan(pf_tmp, sc, {t: v[0] for t, v in px.items()})
fills = []
for x in mp["fills"]:
    t = x["ticker"]
    p, bar = px[t]
    d = round(x["shares"] * p, 2)
    f = dict(ticker=t, side=x["side"], shares=x["shares"], price=p, dollars=d, bar=bar, book="mr_satellite")
    if x["side"] == "SELL":
        f["realized_pnl"] = round((p - pos[t]["avg_cost"]) * x["shares"], 2)
    fills.append(f)

newpos = json.loads(json.dumps(pos))
cash1 = cash0
for x in fills:
    t = x["ticker"]
    if x["side"] == "SELL":
        cash1 += x["dollars"]
        p = newpos[t]
        p["shares"] -= x["shares"]
        if p["shares"] <= 0:
            del newpos[t]
        else:
            p["cost_basis"] = round(p["avg_cost"] * p["shares"], 2)
    else:
        cash1 -= x["dollars"]
        if t in newpos and newpos[t].get("book") == "mr_satellite":
            p = newpos[t]
            p["cost_basis"] = round(p["cost_basis"] + x["dollars"], 2)
            p["shares"] += x["shares"]
            p["avg_cost"] = round(p["cost_basis"] / p["shares"], 4)
            p["opened_at"] = p.get("opened_at", now.isoformat())
        else:
            newpos[t] = dict(
                shares=x["shares"], avg_cost=x["price"], cost_basis=x["dollars"],
                sector=sector.get(t, "other"), opened_at=now.isoformat(), book="mr_satellite",
            )
cash1 = round(cash1, 2)
for t, p in newpos.items():
    p["last_price"] = px[t][0]
    p["market_value"] = round(p["shares"] * px[t][0], 2)
inv = round(sum(p["market_value"] for p in newpos.values()), 2)
nav1 = round(cash1 + inv, 2)
w = {t: round(p["market_value"] / nav1 * 100, 2) for t, p in newpos.items()}
secs = {}
for t, p in newpos.items():
    secs[p.get("sector", "other")] = round(secs.get(p.get("sector", "other"), 0) + w[t], 2)
chk = dict(
    cash_pct=round(cash1 / nav1 * 100, 2),
    max_name=max(w.values()) if w else 0,
    max_sector=max(secs.values()) if secs else 0,
    aapl_msft_nvda=round(sum(w.get(t, 0) for t in ("AAPL", "MSFT", "NVDA")), 2),
    momentum_pct=round(sum(w[t] for t, p in newpos.items() if p.get("book", "momentum") == "momentum"), 2),
    satellite_pct=round(sum(w[t] for t, p in newpos.items() if p.get("book") == "mr_satellite"), 2),
)
assert chk["cash_pct"] >= 19.5 and chk["max_name"] <= 15.5 and chk["max_sector"] <= 40.5 and chk["aapl_msft_nvda"] <= 30.5, chk

# Crypto v2 from proposal, reprice live
cp_prop = json.load(open("sleeves/crypto/reports/proposal_2026-11-23.json"))
ctks = sorted(set(list(cpf["positions"]) + list(cp_prop["targets"])))
cpx = live(ctks)
cpos = json.loads(json.dumps(cpf["positions"]))
ccash0 = float(cpf["cash"])
cnav0 = ccash0 + sum(p["shares"] * cpx[t][0] for t, p in cpos.items())
cfills = []
# sells first
for tr in [x for x in cp_prop["trades"] if x["side"] == "SELL"]:
    t = tr["ticker"]; sh = min(tr["shares"], cpos[t]["shares"]); p, bar = cpx[t]
    d = round(sh * p, 2)
    cfills.append(dict(ticker=t, side="SELL", shares=sh, price=p, dollars=d, bar=bar, realized_pnl=round((p - cpos[t]["avg_cost"]) * sh, 2)))
    ccash0 = round(ccash0 + d, 2)
    cpos[t]["shares"] = round(cpos[t]["shares"] - sh, 6)
    if cpos[t]["shares"] <= 1e-9:
        del cpos[t]
    else:
        cpos[t]["cost_basis"] = round(cpos[t]["avg_cost"] * cpos[t]["shares"], 2)
cnav_mid = ccash0 + sum(p["shares"] * cpx[t][0] for t, p in cpos.items())
for tr in [x for x in cp_prop["trades"] if x["side"] == "BUY"]:
    t = tr["ticker"]; p, bar = cpx[t]
    cur = cpos.get(t, {}).get("shares", 0) * p
    want = cp_prop["targets"][t] * cnav_mid - cur
    avail = max(0.0, ccash0 - 0.20 * cnav_mid)
    d0 = min(want, avail)
    if d0 <= 0:
        continue
    sh = round(d0 / p, 6); d = round(sh * p, 2)
    cfills.append(dict(ticker=t, side="BUY", shares=sh, price=p, dollars=d, bar=bar))
    ccash0 = round(ccash0 - d, 2)
    if t in cpos:
        q = cpos[t]; q["cost_basis"] = round(q["cost_basis"] + d, 2); q["shares"] = round(q["shares"] + sh, 6)
        q["avg_cost"] = round(q["cost_basis"] / q["shares"], 4)
    else:
        cpos[t] = dict(shares=sh, avg_cost=p, cost_basis=d, sector="oracle" if t == "LINK-USD" else "layer1", opened_at=now.isoformat())
for t, pobj in cpos.items():
    pobj["last_price"] = cpx[t][0]
    pobj["market_value"] = round(pobj["shares"] * cpx[t][0], 2)
cnav1 = round(ccash0 + sum(p["market_value"] for p in cpos.values()), 2)
cw = {t: round(p["market_value"] / cnav1 * 100, 2) for t, p in cpos.items()}
ccash_pct = round(ccash0 / cnav1 * 100, 2)
assert ccash_pct >= 19.5, dict(ccash_pct=ccash_pct, cw=cw)

out = dict(
    ts=now.isoformat(),
    equity=dict(
        nav_before=round(nav, 2), fills=fills, cash_before=float(pf["cash"]),
        cash_after=cash1, nav_after=nav1, invested=inv, weights=w, sectors=secs,
        checks=chk, mr_satellite=mp, note="momentum mark-only; MR weekly rebalance only",
    ),
    crypto=dict(
        fills=cfills, cash_before=float(cpf["cash"]), cash_after=ccash0,
        nav_before=round(cnav0, 2), nav_after=cnav1, weights=cw, cash_pct=ccash_pct,
        note="v2: ETH out (252d -26.9% fails secondary filter), no other eligible alt so slot stays cash; BTC and LINK held in band",
    ),
)
print(json.dumps(out, indent=1))
if BOOK:
    json.dump(out, open("reports/rebalance_2026-11-23.json", "w"), indent=2)
    pf["positions"] = newpos
    pf["cash"] = cash1
    pf["nav"] = nav1
    pf["as_of"] = now.isoformat()
    pf["last_trade_batch"] = "rebalance_2026-11-23"
    pf["notes"] = (
        "Weekly pass 2026-11-23 (Jordan standing order 2026-10-05): equity momentum mark-only "
        "(rule v4, not first Monday). Mean-reversion satellite weekly rebalance booked at live "
        "yfinance 1m prices. Caps checked."
    )
    pf["total_pnl"] = round(nav1 - pf["starting_capital"], 2)
    pf["total_pnl_pct"] = round(pf["total_pnl"] / pf["starting_capital"] * 100, 3)
    pf["peak_nav"] = max(float(pf.get("peak_nav") or nav1), nav1)
    pf["drawdown_pct"] = round((nav1 / pf["peak_nav"] - 1) * 100, 2)
    json.dump(pf, open(pf_p, "w"), indent=2)
    with open("state/ledger.jsonl", "a") as L:
        L.write(json.dumps(dict(
            ts=now.isoformat(), type="trade_batch", approval="Jordan standing order 2026-10-05",
            source="reports/rebalance_2026-11-23.json#equity", price_source="yfinance 1m last close",
            last_trade_batch="rebalance_2026-11-23", fills=fills, cash_before=float(out["equity"]["cash_before"]),
            cash_after=cash1, nav_after=nav1, invested=inv,
        )) + "\n")
    cpf["positions"] = cpos
    cpf["cash"] = ccash0
    cpf["nav"] = cnav1
    cpf["as_of"] = now.isoformat()
    cpf["last_trade_batch"] = "crypto_v2_2026-11-23"
    cpf["notes"] = (
        "Rule v2 weekly rebalance 2026-11-23: sold ETH (252d -26.9% fails secondary filter); "
        "only LINK passes, so the second alt slot sits in cash. BTC and LINK within band."
    )
    cpf["total_pnl"] = round(cnav1 - cpf["starting_capital"], 2)
    cpf["total_pnl_pct"] = round(cpf["total_pnl"] / cpf["starting_capital"] * 100, 3)
    cpf["peak_nav"] = max(float(cpf.get("peak_nav") or cnav1), cnav1)
    cpf["drawdown_pct"] = round((cnav1 / cpf["peak_nav"] - 1) * 100, 2)
    cpf["btc_last_close"] = cpx["BTC-USD"][0]
    json.dump(cpf, open(cpf_p, "w"), indent=2)
    with open("sleeves/crypto/state/ledger.jsonl", "a") as L:
        L.write(json.dumps(dict(
            ts=now.isoformat(), type="trade_batch", sleeve="crypto",
            approval="Jordan standing order 2026-10-05",
            source="reports/rebalance_2026-11-23.json#crypto", price_source="yfinance 1m last close",
            last_trade_batch="crypto_v2_2026-11-23", fills=cfills,
            cash_before=float(out["crypto"]["cash_before"]), cash_after=ccash0, nav_after=cnav1,
        )) + "\n")
    print("BOOKED")

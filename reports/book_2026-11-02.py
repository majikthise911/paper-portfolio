#!/usr/bin/env python3
"""One-off booking for the 2026-11-02 first-Monday pass (paper only).
Equity: monthly momentum rebalance (NVDA out at rank>10, TSLA in at 8.75% NAV,
other 7 names trimmed pro-rata so momentum = 70% NAV) + fund MR satellite 10%.
Crypto: v2 AVAX top-up to 15% (proposal_2026-11-02.json)."""
import json, sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import pandas as pd, yfinance as yf
sys.path.insert(0, "scripts"); from mr_satellite import plan as mr_plan
BOOK = "--book" in sys.argv
NY = ZoneInfo("America/New_York"); now = datetime.now(NY).replace(microsecond=0)
R = Path("."); pf_p = R/"state/portfolio.json"; cpf_p = R/"sleeves/crypto/state/portfolio.json"
pf = json.load(open(pf_p)); cpf = json.load(open(cpf_p)); sc = json.load(open(R/"reports/screen_latest.json"))
sector = {r["ticker"]: r["sector"] for r in sc["rankings"]}
def live(tks):
    out = {}
    for t in tks:
        h = yf.Ticker(t).history(period="1d", interval="1m")
        if h.empty: h = yf.Ticker(t).history(period="5d", interval="1m")
        out[t] = (round(float(h["Close"].iloc[-1]), 4), h.index[-1].tz_convert(NY).isoformat())
    return out
eq_t = sorted(set(pf["positions"]) | {"TSLA"} | {r["ticker"] for r in sc["rankings"][-10:]})
px = live(eq_t)
pos = pf["positions"]; cash0 = pf["cash"]
nav = cash0 + sum(p["shares"] * px[t][0] for t, p in pos.items())
fills = []
def fill(t, side, sh, book="momentum"):
    p, bar = px[t]; d = round(sh * p, 2); f = dict(ticker=t, side=side, shares=sh, price=p, dollars=d, bar=bar)
    if book != "momentum": f["book"] = book
    if side == "SELL": f["realized_pnl"] = round((p - pos[t]["avg_cost"]) * sh, 2)
    fills.append(f)
# momentum
fill("NVDA", "SELL", pos["NVDA"]["shares"])
keep = [t for t in pos if t != "NVDA" and pos[t].get("book", "momentum") == "momentum"]
kv = sum(pos[t]["shares"] * px[t][0] for t in keep)
f = 0.6125 * nav / kv
for t in keep:
    new = math.floor(pos[t]["shares"] * f); s = pos[t]["shares"] - new
    if s > 0: fill(t, "SELL", s)
fill("TSLA", "BUY", math.floor(0.0875 * nav / px["TSLA"][0]))
# MR satellite (plan against post-momentum book)
tmp = dict(pf); tmp["nav"] = nav; tmp["positions"] = {t: p for t, p in pos.items() if t != "NVDA"}; tmp["positions"]["TSLA"] = {"shares": 1}
mp = mr_plan(tmp, sc, {t: v[0] for t, v in px.items()})
for x in mp["fills"]: fill(x["ticker"], x["side"], x["shares"], "mr_satellite")
cash1 = round(cash0 + sum(x["dollars"] for x in fills if x["side"] == "SELL") - sum(x["dollars"] for x in fills if x["side"] == "BUY"), 2)
# apply
newpos = json.loads(json.dumps(pos))
for x in fills:
    t = x["ticker"]
    if x["side"] == "SELL":
        p = newpos[t]; p["shares"] -= x["shares"]
        if p["shares"] <= 0: del newpos[t]
        else: p["cost_basis"] = round(p["avg_cost"] * p["shares"], 2)
    else:
        newpos[t] = dict(shares=x["shares"], avg_cost=x["price"], cost_basis=x["dollars"], sector=sector.get(t, "other"), opened_at=now.isoformat(), **({"book": x["book"]} if "book" in x else {}))
for t, p in newpos.items():
    p["last_price"] = px[t][0]; p["market_value"] = round(p["shares"] * px[t][0], 2)
inv = round(sum(p["market_value"] for p in newpos.values()), 2); nav1 = round(cash1 + inv, 2)
w = {t: round(p["market_value"] / nav1 * 100, 2) for t, p in newpos.items()}
secs = {}
for t, p in newpos.items(): secs[p["sector"]] = round(secs.get(p["sector"], 0) + w[t], 2)
chk = dict(cash_pct=round(cash1 / nav1 * 100, 2), max_name=max(w.values()), max_sector=max(secs.values()),
           aapl_msft_nvda=round(sum(w.get(t, 0) for t in ("AAPL", "MSFT", "NVDA")), 2),
           momentum_pct=round(sum(w[t] for t, p in newpos.items() if p.get("book", "momentum") == "momentum"), 2),
           satellite_pct=round(sum(w[t] for t, p in newpos.items() if p.get("book") == "mr_satellite"), 2))
assert chk["cash_pct"] >= 20 and chk["max_name"] <= 15 and chk["max_sector"] <= 40 and chk["aapl_msft_nvda"] <= 30, chk
# crypto
cp = json.load(open("sleeves/crypto/reports/proposal_2026-11-02.json"))
cpx = live(["AVAX-USD", "BTC-USD", "SOL-USD"])
avax_usd = 464.65; ap, abar = cpx["AVAX-USD"]; au = round(avax_usd / ap, 6)
cfill = dict(ticker="AVAX-USD", side="BUY", shares=au, price=ap, dollars=avax_usd, bar=abar)
ch = json.loads(json.dumps(cpf["positions"]))
a = ch["AVAX-USD"]; a["cost_basis"] = round(a["cost_basis"] + avax_usd, 2); a["shares"] = round(a["shares"] + au, 6); a["avg_cost"] = round(a["cost_basis"] / a["shares"], 4)
for t, p in ch.items(): p["last_price"] = cpx[t][0]; p["market_value"] = round(p["shares"] * cpx[t][0], 2)
ccash = round(cpf["cash"] - avax_usd, 2); cnav = round(ccash + sum(p["market_value"] for p in ch.values()), 2)
cw = {t: round(p["market_value"] / cnav * 100, 2) for t, p in ch.items()}
out = dict(ts=now.isoformat(), equity=dict(nav_before=round(nav, 2), fills=fills, cash_before=cash0, cash_after=cash1, nav_after=nav1, invested=inv, weights=w, sectors=secs, checks=chk, mr_satellite=mp),
           crypto=dict(fills=[cfill], cash_before=cpf["cash"], cash_after=ccash, nav_after=cnav, weights=cw, cash_pct=round(ccash / cnav * 100, 2)))
print(json.dumps(out, indent=1))
if BOOK:
    assert now.hour * 60 + now.minute >= 9 * 60 + 31, "equity only after open"
    json.dump(out, open("reports/rebalance_2026-11-02.json", "w"), indent=2)
    pf["positions"] = newpos; pf["cash"] = cash1; pf["nav"] = nav1; pf["as_of"] = now.isoformat(); pf["last_trade_batch"] = "rebalance_2026-11-02"
    pf["notes"] = "First-Monday monthly rebalance 2026-11-02 (rule v4, Jordan standing order 2026-10-05): NVDA out (rank outside top-10 buffer), TSLA in at 8.75%; momentum names trimmed pro-rata to 70% of NAV; mean-reversion satellite funded at 10% (bottom-8 63d, equal weight, book=mr_satellite). Paper fills at live yfinance 1m prices after the 09:30 ET open."
    json.dump(pf, open(pf_p, "w"), indent=2)
    with open("state/ledger.jsonl", "a") as L:
        L.write(json.dumps(dict(ts=now.isoformat(), type="trade_batch", approval="Jordan standing order 2026-10-05", source="reports/rebalance_2026-11-02.json#equity", price_source="yfinance 1m last close", last_trade_batch="rebalance_2026-11-02", fills=fills, cash_before=cash0, cash_after=cash1, nav_after=nav1, invested=inv)) + "\n")
    cpf["positions"] = ch; cpf["cash"] = ccash; cpf["nav"] = cnav; cpf["as_of"] = now.isoformat(); cpf["last_trade_batch"] = "crypto_v2_2026-11-02"
    cpf["notes"] = "Rule v2 weekly rebalance 2026-11-02 (Jordan standing order): AVAX topped up to 15% (rank 1), SOL held (rank 2, within band), BTC held at 50% core. Booked at live yfinance 1m prices."
    json.dump(cpf, open(cpf_p, "w"), indent=2)
    with open("sleeves/crypto/state/ledger.jsonl", "a") as L:
        L.write(json.dumps(dict(ts=now.isoformat(), type="trade_batch", sleeve="crypto", approval="Jordan standing order 2026-10-05", source="reports/rebalance_2026-11-02.json#crypto", price_source="yfinance 1m last close", last_trade_batch="crypto_v2_2026-11-02", fills=[cfill], cash_before=cpf_cash if False else out["crypto"]["cash_before"], cash_after=ccash, nav_after=cnav)) + "\n")
    print("BOOKED")

#!/usr/bin/env python3
"""2026-11-02 shadow updates (never booked): weekly equity shadow + 11/02 judge,
crypto RS-filter shadow, old top-4 comparison, Kronos regime shadow init."""
import json, sys, math, glob
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
NY = ZoneInfo("America/New_York"); now = datetime.now(NY).replace(microsecond=0)
SAVE = "--save" in sys.argv
def lp(t):
    h = yf.Ticker(t).history(period="1d", interval="1m")
    if h.empty: h = yf.Ticker(t).history(period="5d", interval="1m")
    return round(float(h["Close"].iloc[-1]), 4)
def r63(t):
    c = yf.Ticker(t).history(period="6mo", interval="1d")["Close"].dropna()
    return float(c.iloc[-1] / c.iloc[-64] - 1)
out = {}
# 1 weekly shadow
s = json.load(open("state/shadow_weekly.json")); sc = json.load(open("reports/screen_latest.json"))
rank = {r["ticker"]: r["rank"] for r in sc["rankings"]}
px = {t: lp(t) for t in set(s["shares"]) | {"AAPL"}}
snav = s["cash"] + sum(n * px[t] for t, n in s["shares"].items())
rb = json.load(open("reports/rebalance_2026-11-02.json")) if glob.glob("reports/rebalance_2026-11-02.json") else None
live_pre = rb["equity"]["nav_before"] if rb else None
marks = [json.loads(l) for l in open("state/ledger.jsonl") if '"nav"' in l or '"nav_after"' in l]
navs = [m.get("nav", m.get("nav_after")) for m in marks if m["ts"] >= "2026-10-19T09:3"]
lpk, ldd = 0, 0
for v in navs + ([live_pre] if live_pre else []):
    lpk = max(lpk, v); ldd = min(ldd, v / lpk - 1)
spts = [h["nav"] for h in s.get("history", [])] + [snav]; spk, sdd = s["start_nav"], 0
for v in spts: spk = max(spk, v); sdd = min(sdd, v / spk - 1)
trades = []
sold = [t for t in s["shares"] if rank.get(t, 99) > 10]
cash = s["cash"]; sh = dict(s["shares"])
for t in sold:
    cash += sh[t] * px[t]; trades.append(["SELL", t, sh.pop(t), px[t]])
buys = [r["ticker"] for r in sc["rankings"][:8] if r["ticker"] not in sh][:len(sold)]
for t in buys:
    n = math.floor((cash - 0.2 * snav) / px[t]) if len(buys) == 1 else 0
    if n > 0: cash -= n * px[t]; sh[t] = n; trades.append(["BUY", t, n, px[t]])
live_ret = (live_pre / s["start_nav"] - 1) * 100 if live_pre else None
shad_ret = (snav / s["start_nav"] - 1) * 100
out["weekly_shadow"] = dict(shadow_nav=round(snav, 2), shadow_ret_pct=round(shad_ret, 2), live_nav_pre_trade=live_pre,
    live_ret_pct=round(live_ret, 2) if live_ret is not None else None, gap_pts=round(live_ret - shad_ret, 2) if live_ret is not None else None,
    live_dd_pct=round(ldd * 100, 2), shadow_dd_pct=round(sdd * 100, 2), trades=trades)
if SAVE:
    s.setdefault("history", []).append(dict(date="2026-11-02", nav=round(snav, 2), trades=trades, live_nav=live_pre, judge_gap_pts=out["weekly_shadow"]["gap_pts"]))
    s["shares"] = sh; s["cash"] = round(cash, 2); s["as_of"] = now.isoformat(); s["peak_nav"] = round(spk, 2)
    json.dump(s, open("state/shadow_weekly.json", "w"), indent=2)
# 2 RS filter
rs = json.load(open("sleeves/crypto/state/shadow_rs_filter.json"))
coins = ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD"]
cp = {c: lp(c) for c in coins}; rr = {c: r63(c) for c in coins}
rnav = rs["cash"] + sum(n * cp[c] for c, n in rs["shares"].items())
top2 = sorted(coins[1:], key=lambda c: -rr[c])[:2]
elig = [c for c in top2 if rr[c] > rr["BTC-USD"]]
tw = {"BTC-USD": 0.5 + 0.15 * (2 - len(elig)), **{c: 0.15 for c in elig}}
rsh = dict(rs["shares"]); rcash = rs["cash"]; rtr = []
for c in list(rsh):
    if c not in tw: rcash += rsh[c] * cp[c]; rtr.append(["SELL", c, rsh.pop(c), cp[c]])
for c, w in tw.items():
    cur = rsh.get(c, 0) * cp[c]
    if abs(cur / rnav - w) > 0.03:
        d = (w * rnav - cur); n = round(d / cp[c], 6)
        if d > 0: d = min(d, rcash - 0.2 * rnav); n = round(d / cp[c], 6)
        rsh[c] = round(rsh.get(c, 0) + n, 6); rcash -= n * cp[c]; rtr.append(["BUY" if n > 0 else "SELL", c, abs(n), cp[c]])
live_c = json.load(open("sleeves/crypto/state/portfolio.json"))
lc_nav = live_c["cash"] + sum(p["shares"] * cp[c] for c, p in live_c["positions"].items())
out["rs_filter"] = dict(nav=round(rnav, 2), ret_pct=round((rnav / rs["start_nav"] - 1) * 100, 2), live_v2_nav=round(lc_nav, 2),
    live_ret_pct=round((lc_nav / rs["start_nav"] - 1) * 100, 2), r63={c: round(v * 100, 2) for c, v in rr.items()}, eligible=elig, trades=rtr)
if SAVE:
    rs["history"].append(dict(date="2026-11-02", nav=round(rnav, 2), live_v2_nav=round(lc_nav, 2), r63=out["rs_filter"]["r63"], trades=rtr))
    rs["shares"] = rsh; rs["cash"] = round(rcash, 2); rs["as_of"] = now.isoformat(); rs["peak_nav"] = max(rs["peak_nav"], round(rnav, 2))
    json.dump(rs, open("sleeves/crypto/state/shadow_rs_filter.json", "w"), indent=2)
# 3 old top-4
o = live_c["shadow_old_top4"]; onav = o["cash"] + sum(n * cp[c] for c, n in o["shares"].items())
out["old_top4"] = dict(nav=round(onav, 2), ret_pct=round((onav / o["start_nav"] - 1) * 100, 2), live_v2_ret_pct=round((lc_nav / o["start_nav"] - 1) * 100, 2))
# 4 Kronos shadow init
kl = sorted(glob.glob("/Volumes/Marvin SSD/Projects/kronos/regime_log/*.json"))
if kl:
    k = json.load(open(kl[-1])); ok = [c for c in live_c["positions"] if c != "BTC-USD" and k["coins"][c]["regime"] == "trending" and k["coins"][c]["up"]]
    kw = {"BTC-USD": 0.5 + 0.15 * (2 - len(ok)), **{c: 0.15 for c in ok}}
    ks = {c: round(w * lc_nav / cp[c], 6) for c, w in kw.items()}
    kc = round(lc_nav - sum(n * cp[c] for c, n in ks.items()), 2)
    out["kronos"] = dict(regime={c: v["regime"] + (" up" if v["up"] else " down") for c, v in k["coins"].items()}, targets=kw, start_nav=round(lc_nav, 2))
    if SAVE:
        json.dump(dict(as_of=now.isoformat(), method="Crypto v2 plus Kronos-small regime filter: each day Kronos-small samples 100 paths per coin for the next 10 days. An alt keeps its 15% slot only if its paths are tight (>=65% agree with the median direction and |median|/IQR >= 0.5) and the median is up; otherwise the slot goes to BTC. Shadow re-sized each Monday from the latest regime log, never booked.",
            start_nav=round(lc_nav, 2), cash=kc, shares=ks, peak_nav=round(lc_nav, 2), regime_log=kl[-1], regime_today=k["coins"],
            history=[dict(date="2026-11-02", nav=round(lc_nav, 2), live_v2_nav=round(lc_nav, 2), targets=kw)],
            judge="Judge 2026-12-07 (5 Mondays). Promote if shadow leads live v2 by >1.5 pts with no more than 2 pts extra drawdown; kill if it trails by >1 pt or the regime label never changes."),
            open("sleeves/crypto/state/shadow_kronos.json", "w"), indent=2)
print(json.dumps(out, indent=1))

#!/usr/bin/env python3
"""2026-11-23 shadow updates, RS-filter final judge, new SPY-core shadow (never books live trades).
Run after the 11/23 live booking (MR satellite + crypto v2) so live NAVs are post-trade."""
import json, math, sys, os
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf

NY = ZoneInfo("America/New_York")
now = datetime.now(NY).replace(microsecond=0)
D = "2026-11-23"
SAVE = "--save" in sys.argv

def lp(t):
    h = yf.Ticker(t).history(period="1d", interval="1m")
    if h.empty:
        h = yf.Ticker(t).history(period="5d", interval="1m")
    if h.empty:
        h = yf.Ticker(t).history(period="5d", interval="1d")
    return round(float(h["Close"].iloc[-1]), 4)

def r63(t):
    c = yf.Ticker(t).history(period="6mo", interval="1d")["Close"].dropna()
    return float(c.iloc[-1] / c.iloc[-64] - 1)

def dd(vals):
    pk, m = vals[0], 0.0
    for v in vals:
        pk = max(pk, v); m = min(m, v / pk - 1)
    return round(m * 100, 2)

out = {}
live_pf = json.load(open("state/portfolio.json"))
live_nav = live_pf["nav"]
live_c = json.load(open("sleeves/crypto/state/portfolio.json"))
lc_nav = live_c["nav"]

# 1 weekly equity shadow (same procedure as 11/16) + like-for-like Monday drawdown
s = json.load(open("state/shadow_weekly.json"))
sc = json.load(open("reports/screen_latest.json"))
rank = {r["ticker"]: r["rank"] for r in sc["rankings"]}
needed = set(s["shares"]) | {r["ticker"] for r in sc["rankings"][:10]}
px = {t: lp(t) for t in needed}
snav = s["cash"] + sum(n * px[t] for t, n in s["shares"].items())
trades = []
cash = float(s["cash"]); sh = dict(s["shares"])
sold = [t for t in list(sh) if rank.get(t, 99) > 10]
for t in sold:
    cash += sh[t] * px[t]; trades.append(["SELL", t, sh.pop(t), px[t]])
buys = [r["ticker"] for r in sc["rankings"][:8] if r["ticker"] not in sh][: len(sold)]
free = cash - 0.2 * snav
if buys and free > 0:
    per = free / len(buys)
    for t in buys:
        n = math.floor(per / px[t])
        if n > 0:
            cash -= n * px[t]; sh[t] = sh.get(t, 0) + n; trades.append(["BUY", t, n, px[t]])
snav_after = cash + sum(n * px[t] for t, n in sh.items())
live_mondays = [s["start_nav"]] + [h["live_nav"] for h in s["history"] if "live_nav" in h] + [live_nav]
shad_mondays = [h["nav"] for h in s["history"]] + [snav]
live_ret = (live_nav / s["start_nav"] - 1) * 100
shad_ret = (snav / s["start_nav"] - 1) * 100
out["weekly_shadow"] = dict(shadow_nav_pre=round(snav, 2), shadow_nav_post=round(snav_after, 2),
    shadow_ret_pct=round(shad_ret, 2), live_nav=round(live_nav, 2), live_ret_pct=round(live_ret, 2),
    gap_pts=round(live_ret - shad_ret, 2), live_monday_dd_pct=dd(live_mondays),
    shadow_monday_dd_pct=dd(shad_mondays), dd_note="Like-for-like: both from Monday marks only (fix promised 11/16).",
    trades=trades)
if SAVE:
    s["history"].append(dict(date=D, nav=round(snav, 2), nav_after=round(snav_after, 2), trades=trades,
        live_nav=round(live_nav, 2), judge_gap_pts=out["weekly_shadow"]["gap_pts"]))
    s["shares"] = sh; s["cash"] = round(cash, 2); s["as_of"] = now.isoformat()
    s["peak_nav"] = round(max(s.get("peak_nav", snav), snav_after), 2)
    json.dump(s, open("state/shadow_weekly.json", "w"), indent=2)

# 2 RS filter: final mark and judge (no resize; trial closes today)
coins = ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD"]
cp = {c: lp(c) for c in coins}
rr = {c: round(r63(c) * 100, 2) for c in coins}
rs = json.load(open("sleeves/crypto/state/shadow_rs_filter.json"))
rnav = rs["cash"] + sum(n * cp[c] for c, n in rs["shares"].items())
r_series = [h["nav"] for h in rs["history"]] + [rnav]
v_series = [h.get("live_v2_nav", h["nav"]) for h in rs["history"]] + [lc_nav]
out["rs_filter"] = dict(nav=round(rnav, 2), ret_pct=round((rnav / rs["start_nav"] - 1) * 100, 2),
    live_v2_nav=round(lc_nav, 2), live_ret_pct=round((lc_nav / rs["start_nav"] - 1) * 100, 2),
    gap_vs_v2_pts=round((rnav - lc_nav) / rs["start_nav"] * 100, 2),
    shadow_monday_dd_pct=dd(r_series), v2_monday_dd_pct=dd(v_series), r63=rr)
if SAVE:
    rs["history"].append(dict(date=D, nav=round(rnav, 2), live_v2_nav=round(lc_nav, 2), r63=rr,
        note="Final judge: trial closed (dropped). Marked, not resized."))
    rs["status"] = "closed 2026-11-23 (dropped)"; rs["as_of"] = now.isoformat()
    json.dump(rs, open("sleeves/crypto/state/shadow_rs_filter.json", "w"), indent=2)

# 3 Kronos: Marvin offline, mark only
k = json.load(open("sleeves/crypto/state/shadow_kronos.json"))
knav = k["cash"] + sum(n * cp[c] for c, n in k["shares"].items())
out["kronos"] = dict(health="marvin_offline_marked_only", shadow_nav=round(knav, 2),
    ret_pct=round((knav / k["start_nav"] - 1) * 100, 2), live_v2_nav=round(lc_nav, 2),
    live_ret_pct=round((lc_nav / k["start_nav"] - 1) * 100, 2),
    gap_vs_v2_pts=round((knav - lc_nav) / k["start_nav"] * 100, 2), targets="held (80% BTC)")
if SAVE:
    k["history"].append(dict(date=D, nav=round(knav, 2), live_v2_nav=round(lc_nav, 2),
        note="Marvin offline; no regime log. Marked at prior targets, not resized."))
    k["as_of"] = now.isoformat()
    json.dump(k, open("sleeves/crypto/state/shadow_kronos.json", "w"), indent=2)

# 4 BTC 200d trend gate: mark, re-check gate, resize to target
tg = json.load(open("sleeves/crypto/state/shadow_trend_gate.json"))
bc = yf.Ticker("BTC-USD").history(period="2y", interval="1d")["Close"].dropna()
sma = float(bc.iloc[-200:].mean())
below = cp["BTC-USD"] < sma
tnav = tg["cash"] + sum(n * cp[c] for c, n in tg["shares"].items())
if below:
    tw = {"BTC-USD": 0.4}
else:
    prop = json.load(open(f"sleeves/crypto/reports/proposal_{D}.json"))
    tw = dict(prop["targets"])
tsh = {c: round(w * tnav / cp[c], 6) for c, w in tw.items()}
tcash = round(tnav - sum(n * cp[c] for c, n in tsh.items()), 2)
t_series = [h["nav"] for h in tg["history"]] + [tnav]
tv_series = [h["live_v2_nav"] for h in tg["history"]] + [lc_nav]
out["trend_gate"] = dict(nav=round(tnav, 2), ret_pct=round((tnav / tg["start_nav"] - 1) * 100, 2),
    live_v2_nav=round(lc_nav, 2), live_ret_pct=round((lc_nav / tg["start_nav"] - 1) * 100, 2),
    gap_vs_v2_pts=round((tnav - lc_nav) / tg["start_nav"] * 100, 2), btc=cp["BTC-USD"], sma200=round(sma, 2),
    btc_vs_sma200_pct=round((cp["BTC-USD"] / sma - 1) * 100, 2), targets=tw,
    shadow_monday_dd_pct=dd(t_series), v2_monday_dd_pct=dd(tv_series))
if SAVE:
    tg["history"].append(dict(date=D, nav=round(tnav, 2), live_v2_nav=round(lc_nav, 2), targets=tw))
    tg["shares"] = tsh; tg["cash"] = tcash; tg["as_of"] = now.isoformat()
    tg["gate_state"] = dict(btc_below_sma200=bool(below), btc_vs_sma200_pct=out["trend_gate"]["btc_vs_sma200_pct"])
    tg["peak_nav"] = round(max(tg["peak_nav"], tnav), 2)
    json.dump(tg, open("sleeves/crypto/state/shadow_trend_gate.json", "w"), indent=2)

# 5 equal-weight 80% shadow: mark
ep = "state/shadow_eq_weight_80.json"
est = json.load(open(ep))
for t in est["shares"]:
    if t not in px:
        px[t] = lp(t)
enav = est["cash"] + sum(n * px[t] for t, n in est["shares"].items())
out["eq_weight_80"] = dict(nav=round(enav, 2), ret_pct=round((enav / est["start_nav"] - 1) * 100, 2),
    live_nav=round(live_nav, 2), live_ret_pct=round((live_nav / est["start_nav"] - 1) * 100, 2),
    gap_pts=round((enav - live_nav) / est["start_nav"] * 100, 2))
if SAVE:
    est["history"].append(dict(date=D, nav=round(enav, 2), live_nav=round(live_nav, 2)))
    est["peak_nav"] = round(max(est["peak_nav"], enav), 2); est["as_of"] = now.isoformat()
    json.dump(est, open(ep, "w"), indent=2)

# 6 NEW: SPY core 40% + top-4 momentum at 10% each, 20% cash (monthly first Monday), start from live equity NAV
sp = "state/shadow_spy_core.json"
if not os.path.exists(sp):
    elig = [r for r in sc["rankings"] if r.get("secondary_ok", True) and r["ticker"] != "SPY"][:4]
    tw = {"SPY": 0.4, **{r["ticker"]: 0.1 for r in elig}}
    for t in tw:
        if t not in px:
            px[t] = lp(t)
    ssh = {t: round(w * live_nav / px[t], 6) for t, w in tw.items()}
    scash = round(live_nav - sum(n * px[t] for t, n in ssh.items()), 2)
    sst = dict(method="SPY core 40% + top-4 by 63d return (252d > -20% filter, top-6 rank buffer) at 10% each, 20% cash. Rebalanced first Monday monthly with the live book. Simulated, never booked. Fractional shares.",
        start=D, start_nav=round(live_nav, 2), start_prices={t: px[t] for t in tw}, targets=tw, shares=ssh, cash=scash,
        peak_nav=round(live_nav, 2), history=[dict(date=D, nav=round(live_nav, 2), live_nav=round(live_nav, 2))],
        backtest="reports/equity_variants_backtest_2026-11-23.json",
        judge="Checkpoints 2026-12-07 and 2027-01-04 (judge). Promote at the 2027-01-04 first-Monday rebalance if it leads live equity by >1 pt with no more than 1 pt extra Monday drawdown; kill if it trails by >1.5 pts.")
    out["spy_core"] = dict(created=True, start_nav=sst["start_nav"], targets=tw, prices={t: px[t] for t in tw})
    if SAVE:
        json.dump(sst, open(sp, "w"), indent=2)
else:
    sst = json.load(open(sp))
    snv = sst["cash"] + sum(n * lp(t) for t, n in sst["shares"].items())
    out["spy_core"] = dict(nav=round(snv, 2))

print(json.dumps(out, indent=1))
if SAVE:
    json.dump(out, open(f"reports/shadows_result_{D}.json", "w"), indent=2)
    print("SAVED")

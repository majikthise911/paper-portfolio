#!/usr/bin/env python3
"""2026-11-09 shadow updates + crypto v2 final judge (never books live trades)."""
import json, math, glob, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf

NY = ZoneInfo("America/New_York")
now = datetime.now(NY).replace(microsecond=0)
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

out = {}

# 1 weekly equity shadow
s = json.load(open("state/shadow_weekly.json"))
sc = json.load(open("reports/screen_latest.json"))
rank = {r["ticker"]: r["rank"] for r in sc["rankings"]}
needed = set(s["shares"]) | {r["ticker"] for r in sc["rankings"][:10]}
px = {t: lp(t) for t in needed}
snav = s["cash"] + sum(n * px[t] for t, n in s["shares"].items())
# live equity nav after today's MR (for gap); use pre-MR for fair cadence compare? use current equity portfolio momentum+cash style
live_pf = json.load(open("state/portfolio.json"))
# For judge continuity use full live equity NAV
live_nav = live_pf["nav"]
# drawdowns
marks = [json.loads(l) for l in open("state/ledger.jsonl")]
navs = []
for m in marks:
    if m.get("ts", "") >= "2026-10-19T09:30":
        v = m.get("nav", m.get("nav_after"))
        if v is not None:
            navs.append(v)
lpk, ldd = 0.0, 0.0
for v in navs + [live_nav]:
    lpk = max(lpk, v)
    ldd = min(ldd, v / lpk - 1)
spts = [h["nav"] for h in s.get("history", [])] + [snav]
spk, sdd = s["start_nav"], 0.0
for v in spts:
    spk = max(spk, v)
    sdd = min(sdd, v / spk - 1)

trades = []
cash = float(s["cash"])
sh = dict(s["shares"])
sold = [t for t in list(sh) if rank.get(t, 99) > 10]
for t in sold:
    cash += sh[t] * px[t]
    trades.append(["SELL", t, sh.pop(t), px[t]])
buys = [r["ticker"] for r in sc["rankings"][:8] if r["ticker"] not in sh][: max(1, len(sold))]
# allocate freed cash keeping 20% of pre-trade shadow nav
free = cash - 0.2 * snav
if buys and free > 0:
    per = free / len(buys)
    for t in buys:
        n = math.floor(per / px[t])
        if n > 0:
            cash -= n * px[t]
            sh[t] = sh.get(t, 0) + n
            trades.append(["BUY", t, n, px[t]])
snav_after = cash + sum(n * px[t] for t, n in sh.items())
live_ret = (live_nav / s["start_nav"] - 1) * 100
shad_ret = (snav / s["start_nav"] - 1) * 100  # pre-rebalance mark for gap continuity
out["weekly_shadow"] = dict(
    shadow_nav_pre=round(snav, 2), shadow_nav_post=round(snav_after, 2),
    shadow_ret_pct=round(shad_ret, 2), live_nav=round(live_nav, 2),
    live_ret_pct=round(live_ret, 2), gap_pts=round(live_ret - shad_ret, 2),
    live_dd_pct=round(ldd * 100, 2), shadow_dd_pct=round(sdd * 100, 2), trades=trades,
)
if SAVE:
    s.setdefault("history", []).append(dict(
        date="2026-11-09", nav=round(snav, 2), nav_after=round(snav_after, 2),
        trades=trades, live_nav=round(live_nav, 2), judge_gap_pts=out["weekly_shadow"]["gap_pts"],
    ))
    s["shares"] = sh
    s["cash"] = round(cash, 2)
    s["as_of"] = now.isoformat()
    s["peak_nav"] = round(max(spk, snav_after), 2)
    json.dump(s, open("state/shadow_weekly.json", "w"), indent=2)

# 2 RS filter shadow
rs = json.load(open("sleeves/crypto/state/shadow_rs_filter.json"))
coins = ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD"]
cp = {c: lp(c) for c in coins}
rr = {c: r63(c) for c in coins}
rnav = rs["cash"] + sum(n * cp[c] for c, n in rs["shares"].items())
top2 = sorted(coins[1:], key=lambda c: -rr[c])[:2]
elig = [c for c in top2 if rr[c] > rr["BTC-USD"]]
tw = {"BTC-USD": 0.5 + 0.15 * (2 - len(elig)), **{c: 0.15 for c in elig}}
rsh = dict(rs["shares"])
rcash = float(rs["cash"])
rtr = []
for c in list(rsh):
    if c not in tw:
        rcash += rsh[c] * cp[c]
        rtr.append(["SELL", c, rsh.pop(c), cp[c]])
rnav2 = rcash + sum(n * cp[c] for c, n in rsh.items())
for c, w in tw.items():
    cur = rsh.get(c, 0) * cp[c]
    if abs(cur / rnav2 - w) > 0.03:
        d = w * rnav2 - cur
        if d > 0:
            d = min(d, max(0.0, rcash - 0.2 * rnav2))
        n = round(d / cp[c], 6)
        if abs(n) > 0:
            rsh[c] = round(rsh.get(c, 0) + n, 6)
            if rsh[c] <= 1e-9:
                rsh.pop(c, None)
            rcash -= n * cp[c]
            rtr.append(["BUY" if n > 0 else "SELL", c, abs(n), cp[c]])
live_c = json.load(open("sleeves/crypto/state/portfolio.json"))
lc_nav = live_c["nav"]
out["rs_filter"] = dict(
    nav=round(rnav, 2), ret_pct=round((rnav / rs["start_nav"] - 1) * 100, 2),
    live_v2_nav=round(lc_nav, 2), live_ret_pct=round((lc_nav / rs["start_nav"] - 1) * 100, 2),
    r63={c: round(v * 100, 2) for c, v in rr.items()}, eligible=elig, top2=top2, trades=rtr,
    gap_vs_v2_pts=round((rnav / rs["start_nav"] - lc_nav / rs["start_nav"]) * 100, 2),
)
if SAVE:
    rs["history"].append(dict(
        date="2026-11-09", nav=round(rnav, 2), live_v2_nav=round(lc_nav, 2),
        r63=out["rs_filter"]["r63"], eligible=elig, trades=rtr,
        note="AVAX beats BTC 63d; ETH is top-2 but trails BTC 63d so RS keeps only AVAX and lifts BTC.",
    ))
    rs["shares"] = {k: v for k, v in rsh.items() if v}
    rs["cash"] = round(rcash, 2)
    rs["as_of"] = now.isoformat()
    rs["peak_nav"] = max(rs.get("peak_nav", rnav), round(rnav, 2))
    json.dump(rs, open("sleeves/crypto/state/shadow_rs_filter.json", "w"), indent=2)

# 3 old top-4 FINAL JUDGE (decide today)
o = live_c["shadow_old_top4"]
onav = o["cash"] + sum(n * cp[c] for c, n in o["shares"].items())
v2_ret = (lc_nav / o["start_nav"] - 1) * 100
old_ret = (onav / o["start_nav"] - 1) * 100
gap = v2_ret - old_ret
decision = "KEEP_V2" if gap >= -2 else "REVERT_TO_TOP4"
out["old_top4"] = dict(
    start_nav=o["start_nav"], old_nav=round(onav, 2), old_ret_pct=round(old_ret, 2),
    live_v2_nav=round(lc_nav, 2), live_v2_ret_pct=round(v2_ret, 2),
    gap_pts=round(gap, 2), decision=decision,
    rule="Revert if v2 trails old top-4 by more than 2 pts.",
)

# 4 Kronos shadow mark/resize from latest log
kl = sorted(glob.glob("/Volumes/Marvin SSD/Projects/kronos/regime_log/20*.json"))
kshadow = json.load(open("sleeves/crypto/state/shadow_kronos.json"))
if kl:
    k = json.load(open(kl[-1]))
    # mark current shadow NAV
    knav = kshadow["cash"] + sum(n * cp.get(c, lp(c)) for c, n in kshadow["shares"].items())
    ok = [c for c in ["ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD"]
          if k["coins"].get(c, {}).get("regime") == "trending" and k["coins"].get(c, {}).get("up")]
    kw = {"BTC-USD": 0.5 + 0.15 * (2 - len(ok)), **{c: 0.15 for c in ok}}
    # resize from live v2 NAV so both start comparable each week? keep continuous NAV then rebalance weights
    base = knav
    ks = {c: round(w * base / cp[c], 6) for c, w in kw.items()}
    kc = round(base - sum(n * cp[c] for c, n in ks.items()), 2)
    out["kronos"] = dict(
        regime={c: (v["regime"] + (" up" if v["up"] else " down")) for c, v in k["coins"].items()},
        targets=kw, shadow_nav=round(knav, 2),
        ret_pct=round((knav / kshadow["start_nav"] - 1) * 100, 2),
        live_v2_nav=round(lc_nav, 2), live_ret_pct=round((lc_nav / kshadow["start_nav"] - 1) * 100, 2),
        gap_vs_v2_pts=round((knav / kshadow["start_nav"] - lc_nav / kshadow["start_nav"]) * 100, 2),
        log=kl[-1], health="ok" if "2026-11-09" in kl[-1] else "stale_log",
    )
    if SAVE:
        kshadow["history"].append(dict(
            date="2026-11-09", nav=round(knav, 2), live_v2_nav=round(lc_nav, 2),
            targets=kw, regime=out["kronos"]["regime"],
        ))
        kshadow["shares"] = ks
        kshadow["cash"] = kc
        kshadow["as_of"] = now.isoformat()
        kshadow["peak_nav"] = max(kshadow.get("peak_nav", knav), round(knav, 2))
        kshadow["regime_log"] = kl[-1]
        kshadow["regime_today"] = k["coins"]
        json.dump(kshadow, open("sleeves/crypto/state/shadow_kronos.json", "w"), indent=2)
else:
    out["kronos"] = dict(health="missing_log")

print(json.dumps(out, indent=1))
if SAVE:
    json.dump(out, open("reports/shadows_result_2026-11-09.json", "w"), indent=2)
    print("SAVED")

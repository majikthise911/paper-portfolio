#!/usr/bin/env python3
"""2026-11-16 shadow updates + crypto v2 final judge (never books live trades)."""
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
        date="2026-11-16", nav=round(snav, 2), nav_after=round(snav_after, 2),
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
top2 = json.load(open("sleeves/crypto/reports/proposal_2026-11-16.json"))["satellites"]  # v2 eligible top-2 (252d filter applied)
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
        date="2026-11-16", nav=round(rnav, 2), live_v2_nav=round(lc_nav, 2),
        r63=out["rs_filter"]["r63"], eligible=elig, trades=rtr,
        note="Top-2 eligible alts LINK/ETH both trail BTC 63d; RS shadow goes to BTC 80%.",
    ))
    rs["shares"] = {k: v for k, v in rsh.items() if v}
    rs["cash"] = round(rcash, 2)
    rs["as_of"] = now.isoformat()
    rs["peak_nav"] = max(rs.get("peak_nav", rnav), round(rnav, 2))
    json.dump(rs, open("sleeves/crypto/state/shadow_rs_filter.json", "w"), indent=2)

# 4 Kronos shadow mark/resize from latest log
kl = sorted(glob.glob(sys.argv[sys.argv.index("--klog") + 1] + "/20*.json")) if "--klog" in sys.argv else []
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
    fresh = "2026-11-16" in kl[-1] or "2026-11-15" in kl[-1]
    if fresh:
        ks = {c: round(w * base / cp[c], 6) for c, w in kw.items()}
        kc = round(base - sum(n * cp[c] for c, n in ks.items()), 2)
    else:
        ks, kc = dict(kshadow["shares"]), kshadow["cash"]
    out["kronos"] = dict(
        regime={c: (v["regime"] + (" up" if v["up"] else " down")) for c, v in k["coins"].items()},
        targets=kw, shadow_nav=round(knav, 2),
        ret_pct=round((knav / kshadow["start_nav"] - 1) * 100, 2),
        live_v2_nav=round(lc_nav, 2), live_ret_pct=round((lc_nav / kshadow["start_nav"] - 1) * 100, 2),
        gap_vs_v2_pts=round((knav / kshadow["start_nav"] - lc_nav / kshadow["start_nav"]) * 100, 2),
        log=kl[-1], health="ok" if "2026-11-16" in kl[-1] else "stale_log",
    )
    if SAVE:
        kshadow["history"].append(dict(
            date="2026-11-16", nav=round(knav, 2), live_v2_nav=round(lc_nav, 2),
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
    kshadow = json.load(open("sleeves/crypto/state/shadow_kronos.json"))
    knav = kshadow["cash"] + sum(n * cp[c] for c, n in kshadow["shares"].items())
    out["kronos"] = dict(health="log_unreachable_marked_only", shadow_nav=round(knav, 2),
        ret_pct=round((knav / kshadow["start_nav"] - 1) * 100, 2), live_v2_nav=round(lc_nav, 2),
        live_ret_pct=round((lc_nav / kshadow["start_nav"] - 1) * 100, 2),
        gap_vs_v2_pts=round((knav - lc_nav) / kshadow["start_nav"] * 100, 2), targets="held (80% BTC)")
    if SAVE:
        kshadow["history"].append(dict(date="2026-11-16", nav=round(knav, 2), live_v2_nav=round(lc_nav, 2),
            note="Marvin SSD unresponsive; no regime log. Marked at prior targets, not resized."))
        kshadow["as_of"] = now.isoformat()
        json.dump(kshadow, open("sleeves/crypto/state/shadow_kronos.json", "w"), indent=2)

# 5 equal-weight 80% shadow (state created today, back-filled from 11/09 closes)
import os
ep = "state/shadow_eq_weight_80.json"
univ = [r["ticker"] for r in sc["rankings"]]
if not os.path.exists(ep):
    start_nav = 100232.07  # live equity NAV after 11/09 booking
    h = yf.download(univ, start="2026-11-09", end="2026-11-10", interval="1d", progress=False, auto_adjust=False)["Close"].iloc[0]
    per = 0.8 * start_nav / len(univ)
    esh = {t: round(per / float(h[t]), 6) for t in univ}
    ecash = round(start_nav - sum(esh[t] * float(h[t]) for t in univ), 2)
    est = dict(method="Equal-weight the 30-name equity universe at 80% invested, 20% cash, rebalanced first Monday monthly. Simulated, never booked. Fractional shares.",
               start="2026-11-09", start_nav=start_nav, start_prices={t: round(float(h[t]), 4) for t in univ},
               shares=esh, cash=ecash, peak_nav=start_nav, history=[],
               note="State created 2026-11-16, back-filled from 2026-11-09 daily closes (trial was declared 11/09 without a state file).",
               judge="Judge 2026-12-07. Promote if it leads live equity by >2 pts with no more than 1.5 pts extra drawdown; kill if it trails by >2 pts.")
else:
    est = json.load(open(ep))
for t in est["shares"]:
    if t not in px:
        px[t] = lp(t)
enav = est["cash"] + sum(n * px[t] for t, n in est["shares"].items())
live_eq = live_nav
out["eq_weight_80"] = dict(nav=round(enav, 2), ret_pct=round((enav / est["start_nav"] - 1) * 100, 2),
    live_nav=round(live_eq, 2), live_ret_pct=round((live_eq / est["start_nav"] - 1) * 100, 2),
    gap_pts=round((enav - live_eq) / est["start_nav"] * 100, 2))
if SAVE:
    est["history"].append(dict(date="2026-11-16", nav=round(enav, 2), live_nav=round(live_eq, 2)))
    est["peak_nav"] = round(max(est["peak_nav"], enav), 2)
    est["as_of"] = now.isoformat()
    json.dump(est, open(ep, "w"), indent=2)

print(json.dumps(out, indent=1))
if SAVE:
    json.dump(out, open("reports/shadows_result_2026-11-16.json", "w"), indent=2)
    print("SAVED")

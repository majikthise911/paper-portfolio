"""Scoreboard-first dashboard (rebuilt 2026-10-29).

Called from scripts/dashboard.py main(). Renders:
  reports/dashboard.html   scoreboard, attribution, experiments, health, risk
  reports/strategy.html    static strategy cards + architecture diagram
  reports/changelog.html   compact rule changelog from STRATEGY_CHANGELOG.md
Experiments come from state/experiments.json. EOD routine status comes from
state/routine_runs.json; commit-based routines are read from git log.

Benchmark start convention (one rule everywhere): the start close for SPY or
BTC is the last print at or before the sleeve's start timestamp, which is what
the buy-and-hold series in pnl_history.json use. vs_benchmark is recomputed
from those same series so the cards, chart and baseline agree.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
SCORE_DATE = date(2026, 12, 31)


def _dt(ts):
    try:
        d = datetime.fromisoformat(str(ts))
        return d if d.tzinfo else d.replace(tzinfo=TZ)
    except Exception:
        return None


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def money(v, sign=False):
    if v is None:
        return "n/a"
    s = f"${abs(v):,.0f}" if abs(v) >= 1000 else f"${abs(v):,.2f}"
    if v < 0:
        return "-" + s
    return ("+" + s) if sign and v > 0 else s


def pct(v, places=2, sign=True):
    if v is None:
        return "n/a"
    return f"{v:+.{places}f}%" if sign else f"{v:.{places}f}%"


def cls(v):
    if v is None:
        return ""
    return "pos" if v > 0 else ("neg" if v < 0 else "")


# ---------------------------------------------------------------- benchmark fix
def consistent_vs_benchmark(series: list[dict], price_field: str, start_ts: str | None,
                            end_px: float | None, label: str) -> dict | None:
    """vs_benchmark from the same B&H series the chart uses."""
    if not series:
        return None
    sd = _dt(start_ts) if start_ts else None
    p0 = None
    for p in series:
        d = _dt(p.get("ts"))
        if sd is None or (d and d >= sd):
            p0 = p.get(price_field)
            break
    if p0 is None:
        p0 = series[0].get(price_field)
    if end_px is None:
        end_px = series[-1].get(price_field)
    if not p0 or not end_px:
        return None
    ret = (float(end_px) / float(p0) - 1.0) * 100.0
    return {
        "benchmark": label,
        "return_pct": round(ret, 4),
        "same_day": False,
        "start_close": round(float(p0), 4),
        "end_close": round(float(end_px), 4),
        "start_rule": "last print at or before sleeve start timestamp (same as B&H series)",
        "note": (f"{label} return from the last {label} print at or before the sleeve start "
                 f"(${float(p0):,.2f}) to now. Same start price as the buy-and-hold series."),
    }


def fix_vs_benchmark(data: dict) -> None:
    s = data["pnl_history"]["series"]
    pairs = [
        (data["equity"], s.get("spy"), "spy_px", "SPY", s.get("equity")),
        (data["crypto"], s.get("btc"), "btc_px", "BTC-USD", s.get("crypto")),
        (data["active"]["equity"], s.get("spy"), "spy_px", "SPY", s.get("active_equity")),
        (data["active"]["crypto"], s.get("btc"), "btc_px", "BTC-USD", s.get("active_crypto")),
    ]
    for sleeve, bser, field, label, own in pairs:
        if not sleeve or not bser:
            continue
        start_ts = own[0]["ts"] if own else None
        vb = consistent_vs_benchmark(bser, field, start_ts, sleeve.get("bench_last_close"), label)
        if vb:
            sleeve["vs_benchmark"] = vb


# ---------------------------------------------------------------- series helpers
def value_at(series: list[dict], when: datetime, key="nav"):
    best = None
    for p in series:
        d = _dt(p.get("ts"))
        if d and d <= when:
            best = p.get(key)
        elif d and d > when:
            break
    return best


def gap_series(hh: list[dict], base: list[dict]) -> list[tuple[str, float]]:
    """Daily (last point per ET date) gap of household minus bh_5050, in $."""
    base_pts = [(_dt(p["ts"]), p["nav"]) for p in base if _dt(p.get("ts"))]
    out = {}
    j = 0
    cur = None
    for p in hh:
        d = _dt(p.get("ts"))
        if not d:
            continue
        while j < len(base_pts) and base_pts[j][0] <= d:
            cur = base_pts[j][1]
            j += 1
        if cur is None:
            continue
        out[d.date().isoformat()] = round(float(p["nav"]) - float(cur), 2)
    return sorted(out.items())


def drawdown(series: list[dict]) -> tuple[float, float]:
    peak = None
    mdd = 0.0
    cur = 0.0
    for p in series:
        n = float(p["nav"])
        peak = n if peak is None else max(peak, n)
        cur = (n / peak - 1.0) * 100.0 if peak else 0.0
        mdd = min(mdd, cur)
    return round(cur, 2), round(mdd, 2)


def sparkline(vals: list[float], w=220, h=44) -> str:
    if len(vals) < 2:
        return ""
    lo, hi = min(vals + [0]), max(vals + [0])
    rng = (hi - lo) or 1.0
    xs = [i * (w - 4) / (len(vals) - 1) + 2 for i in range(len(vals))]
    ys = [h - 2 - (v - lo) / rng * (h - 4) for v in vals]
    zero = h - 2 - (0 - lo) / rng * (h - 4)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    col = "#1a7f37" if vals[-1] >= 0 else "#cf222e"
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="gap trend"><line x1="0" x2="{w}" y1="{zero:.1f}" y2="{zero:.1f}" '
            f'stroke="#bbb" stroke-dasharray="3 3"/><polyline fill="none" stroke="{col}" '
            f'stroke-width="2" points="{pts}"/></svg>')


def main_chart(series_map: list[tuple[str, list[dict], str, str]], w=960, h=320) -> str:
    """P&L % chart. series_map: (label, points, color, dash)."""
    all_pts = []
    for _, pts, _, _ in series_map:
        for p in pts:
            d = _dt(p.get("ts"))
            if d is not None and p.get("pnl_pct") is not None:
                all_pts.append((d, float(p["pnl_pct"])))
    if not all_pts:
        return ""
    t0 = min(d for d, _ in all_pts).timestamp()
    t1 = max(d for d, _ in all_pts).timestamp()
    lo = min(v for _, v in all_pts + [(None, 0.0)])
    hi = max(v for _, v in all_pts + [(None, 0.0)])
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 52, 12, 12, 28

    def X(t):
        return L + (t - t0) / ((t1 - t0) or 1) * (w - L - R)

    def Y(v):
        return T + (hi - v) / (hi - lo) * (h - T - B)

    parts = [f'<svg class="chart" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-label="P&amp;L percent since start">']
    step = 1 if hi - lo < 8 else 2
    v = int(lo) - 1
    while v <= hi:
        if v >= lo:
            parts.append(f'<line x1="{L}" x2="{w-R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{"#999" if v == 0 else "#eee"}"/>'
                         f'<text x="{L-6}" y="{Y(v)+4:.1f}" text-anchor="end" class="ax">{v:+d}%</text>')
        v += step
    d = datetime.fromtimestamp(t0, TZ).date()
    end = datetime.fromtimestamp(t1, TZ).date()
    while d <= end:
        if d.weekday() == 0:
            t = datetime(d.year, d.month, d.day, tzinfo=TZ).timestamp()
            if t0 <= t <= t1:
                parts.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{T}" y2="{h-B}" stroke="#f2f2f2"/>'
                             f'<text x="{X(t):.1f}" y="{h-8}" text-anchor="middle" class="ax">{d.month}/{d.day}</text>')
        d += timedelta(days=1)
    for label, pts, color, dash in series_map:
        coords = []
        for p in pts:
            dd = _dt(p.get("ts"))
            if dd is None or p.get("pnl_pct") is None:
                continue
            coords.append(f"{X(dd.timestamp()):.1f},{Y(float(p['pnl_pct'])):.1f}")
        sw = "3" if label.startswith("50/50") else "2"
        da = f' stroke-dasharray="{dash}"' if dash else ""
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="{sw}"{da} points="{" ".join(coords)}"/>')
    parts.append("</svg>")
    legend = "".join(
        f'<span class="lg"><i style="background:{c}"></i>{escape(l)} '
        f'<b class="{cls(pts[-1].get("pnl_pct"))}">{pct(pts[-1].get("pnl_pct"))}</b></span>'
        for l, pts, c, _ in series_map if pts)
    return f'<div class="legend">{legend}</div>{"".join(parts)}'


# ---------------------------------------------------------------- ledgers
def read_ledger(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def fills(ledger: list[dict]) -> list[dict]:
    out = []
    for e in ledger:
        if e.get("type") == "trade_batch":
            for f in e.get("fills") or []:
                f = dict(f)
                f["_ts"] = e.get("ts")
                out.append(f)
    return out


def contributions(sleeve: dict, ledger: list[dict], leg: str = "") -> list[tuple[str, float, str]]:
    realized = defaultdict(float)
    for f in fills(ledger):
        if f.get("realized_pnl") is not None:
            realized[f["ticker"]] += float(f["realized_pnl"])
    unreal = {h["ticker"]: float(h.get("unrealized_pnl") or 0.0) for h in sleeve.get("holdings") or []}
    rows = []
    for t in sorted(set(realized) | set(unreal)):
        tot = realized.get(t, 0.0) + unreal.get(t, 0.0)
        state = "held" if t in unreal else "closed"
        rows.append((t, round(tot, 2), state))
    accounted = sum(r[1] for r in rows)
    resid = round(float(sleeve.get("total_pnl") or 0.0) - accounted, 2)
    if abs(resid) >= 1:
        rows.append((f"{leg} unattributed".strip(), resid, "fills without realized P&L, rounding"))
    rows.sort(key=lambda r: r[1])
    return rows


def turnover(ledger: list[dict], start_cap: float, days: int | None, now: datetime) -> float:
    cutoff = now - timedelta(days=days) if days else None
    tot = 0.0
    for f in fills(ledger):
        d = _dt(f.get("_ts"))
        if cutoff and d and d < cutoff:
            continue
        tot += abs(float(f.get("dollars") or 0.0))
    return round(tot / start_cap * 100.0, 1) if start_cap else 0.0


# ---------------------------------------------------------------- routines
def git_runs(root: Path) -> list[tuple[datetime, str]]:
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "--since=21 days ago", "--format=%aI|%s"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        ts, _, subj = line.partition("|")
        d = _dt(ts)
        if d:
            rows.append((d.astimezone(TZ), subj))
    return rows


def last_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def routine_status(root: Path, now: datetime) -> list[dict]:
    runs = git_runs(root)

    def last(pattern):
        for d, s in runs:
            if re.search(pattern, s, re.I):
                return d, s
        return None, None

    today = now.date()
    rows = []
    # Daily mark: weekdays, due by 08:45 ET.
    d, s = last(r"daily mark")
    due = last_weekday(today if now.hour * 60 + now.minute >= 525 else today - timedelta(days=1))
    rows.append(_rstat("Daily mark (8:09 AM)", d, d is not None and d.date() >= due, f"expected for {due:%a %m/%d}"))
    # Market-hours refresh: weekdays 11:2x and 15:2x.
    d, s = last(r"market-hours refresh")
    due = last_weekday(today if now.hour >= 12 else today - timedelta(days=1))
    rows.append(_rstat("Market-hours refresh (11:23 AM, 3:23 PM)", d, d is not None and d.date() >= due,
                       f"expected for {due:%a %m/%d}"))
    # EOD summary from state file.
    eod = (_load(root / "state" / "routine_runs.json", {}) or {}).get("eod_summary") or {}
    d = _dt(eod.get("last_run"))
    due = last_weekday(today if now.hour >= 18 else today - timedelta(days=1))
    ok = d is not None and d.date() >= due and eod.get("status") != "missed"
    rows.append(_rstat("End-of-day summary (5:14 PM)", d, ok,
                       eod.get("detail") or f"expected for {due:%a %m/%d}"))
    # Weekly: Mondays.
    d, s = last(r"weekly")
    mon = today - timedelta(days=today.weekday())
    if today.weekday() == 0 and now.hour < 10:
        mon -= timedelta(days=7)
    rows.append(_rstat("Weekly update (Monday)", d, d is not None and d.date() >= mon, f"expected for Mon {mon:%m/%d}"))
    return rows


def _rstat(name, d, ok, detail):
    return {"name": name, "last": d.strftime("%a %m/%d %I:%M %p ET") if d else "no record",
            "ok": bool(ok), "detail": detail}


# ---------------------------------------------------------------- experiments
def price_book(data: dict) -> dict:
    px = {}
    for sl in (data["equity"], data["crypto"], data["active"]["equity"], data["active"]["crypto"]):
        for h in sl.get("holdings") or []:
            if h.get("last_price"):
                px[h["ticker"]] = float(h["last_price"])
    return px


def mark_book(shares: dict, cash: float, px: dict) -> float | None:
    missing = [t for t in shares if t not in px]
    if missing:
        try:
            import yfinance as yf
            for t in missing:
                hist = yf.Ticker(t).history(period="5d", interval="1h")
                if hist is not None and not hist.empty:
                    px[t] = float(hist["Close"].iloc[-1])
        except Exception:
            return None
    if any(t not in px for t in shares):
        return None
    return round(cash + sum(float(q) * px[t] for t, q in shares.items()), 2)


def nav_on(series: list[dict], day: str) -> float | None:
    best = None
    for p in series:
        if str(p.get("ts", ""))[:10] <= day:
            best = p.get("nav")
    return best


def live_result(kind: str, data: dict, root: Path, px: dict) -> tuple[str, float | None]:
    s = data["pnl_history"]["series"]
    if kind == "crypto_v2":
        pf = _load(root / "sleeves" / "crypto" / "state" / "portfolio.json", {}) or {}
        sh = pf.get("shadow_old_top4") or {}
        start = float(sh.get("start_nav") or 0)
        old = mark_book(sh.get("shares") or {}, float(sh.get("cash") or 0), px)
        v2 = float(data["crypto"]["nav"])
        if not start:
            return "No shadow data.", None
        v2r = (v2 / start - 1) * 100
        if old is None:
            return f"v2 {pct(v2r, 1)} since 10/12; old top-4 could not be priced.", None
        oldr = (old / start - 1) * 100
        return f"v2 {pct(v2r, 1)} vs old top-4 {pct(oldr, 1)} since 10/12. Lead {v2r - oldr:+.1f} pts.", round(v2r - oldr, 2)
    if kind == "rs_filter":
        sh = _load(root / "sleeves" / "crypto" / "state" / "shadow_rs_filter.json", {}) or {}
        start = float(sh.get("start_nav") or 0)
        nav = mark_book(sh.get("shares") or {}, float(sh.get("cash") or 0), px)
        v2 = float(data["crypto"]["nav"])
        if not start or nav is None:
            return "Shadow not priced.", None
        sr, lr = (nav / start - 1) * 100, (v2 / start - 1) * 100
        same = abs(nav - v2) < 1
        txt = f"Shadow {pct(sr, 1)} vs live v2 {pct(lr, 1)} since 10/26."
        if same:
            txt += " Same holdings so far (filter has not diverged)."
        return txt, round(sr - lr, 2)
    if kind == "weekly_shadow":
        sh = _load(root / "state" / "shadow_weekly.json", {}) or {}
        start = float(sh.get("start_nav") or 0)
        nav = mark_book(sh.get("shares") or {}, float(sh.get("cash") or 0), px)
        live_start = nav_on(s.get("equity") or [], "2026-10-19") or start
        live = float(data["equity"]["nav"])
        if not start or nav is None:
            return "Shadow not priced.", None
        sr = (nav / start - 1) * 100
        lr = (live / float(live_start) - 1) * 100 if live_start else 0
        return f"Monthly live {pct(lr, 1)} vs weekly shadow {pct(sr, 1)} since 10/19. Live lead {lr - sr:+.1f} pts.", round(lr - sr, 2)
    return "", None


# ---------------------------------------------------------------- health
SKIP_LABELS = {
    "entry_skip_too_small": "buy too small after caps",
    "entry_skip_below_min_order": "under $1,000 minimum order (no free cash)",
    "exit_skip_min_hold": "exit held by 3-day minimum hold",
    "entry_skip_cooldown": "re-entry cooldown",
    "entry_skip_tech_cap": "AAPL+MSFT+NVDA cap",
    "entry_skip_no_price": "no price",
    "entry_skip_daily_cap_recheck": "daily fill cap",
    "daily_mode_mark_only": "outside 3 to 4 PM eval window (mark only)",
}


def skip_summary(root: Path, n=5):
    rep = root / "sleeves" / "active" / "equity" / "reports"
    files = sorted(rep.glob("proposal_*_scan.json"))
    evals = []
    for f in files[::-1]:
        d = _load(f, {}) or {}
        notes = d.get("notes") or []
        if any(x.startswith("daily_mode_mark_only") for x in notes):
            continue
        evals.append((f.name[9:19], d, notes))
        if len(evals) >= n:
            break
    counts = defaultdict(int)
    tickers = defaultdict(set)
    for _, _, notes in evals:
        for x in notes:
            k = x.split(":")[0]
            counts[k] += 1
            if ":" in x:
                tickers[k].add(x.split(":")[1])
    last = evals[0] if evals else None
    return evals, counts, tickers, last


# ---------------------------------------------------------------- render
CSS = """
*{box-sizing:border-box}body{font:15px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1f2328}
main{max-width:1080px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 2px}h2{font-size:17px;margin:0 0 10px}
.sub{color:#59636e;font-size:13px}.sub a{color:#0969da}
section{background:#fff;border:1px solid #d1d9e0;border-radius:10px;padding:16px;margin-top:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.card{border:1px solid #e3e8ee;border-radius:8px;padding:12px}.card h3{margin:0 0 6px;font-size:15px}
.big{font-size:26px;font-weight:700}.pos{color:#1a7f37}.neg{color:#cf222e}.muted{color:#59636e;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13.5px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #eef1f4;vertical-align:top}
th{color:#59636e;font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;background:#eef1f4}
.p-ok,.p-won,.p-running{background:#dafbe1;color:#1a7f37}.p-bad,.p-killed,.p-missed{background:#ffebe9;color:#cf222e}
.p-shadow,.p-backtest,.p-replaced,.p-superseded{background:#ddf4ff;color:#0969da}.p-warn{background:#fff8c5;color:#9a6700}
.chart{width:100%;height:320px}.ax{font-size:11px;fill:#59636e}.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;margin-bottom:6px}
.lg i{display:inline-block;width:14px;height:4px;margin-right:5px;vertical-align:middle}.bar{height:8px;background:#eef1f4;border-radius:4px;overflow:hidden}
.bar>span{display:block;height:100%}.warn{background:#fff8c5;border:1px solid #eac54f;border-radius:6px;padding:8px 10px;font-size:13px;margin-top:8px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:13.5px}
"""


def page(title, body, now_txt):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>{CSS}</style></head><body><main>{body}
<p class="muted" style="margin-top:20px">Paper portfolio, simulated only. No real trades. Generated {escape(now_txt)}.</p></main></body></html>"""


def nav_links(active):
    links = [("index.html", "Scoreboard"), ("strategy.html", "Strategy"), ("changelog.html", "Rule changelog")]
    return " | ".join(f"<b>{t}</b>" if h == active else f'<a href="./{h}">{t}</a>' for h, t in links)


def build_scoreboard(data: dict, root: Path) -> tuple[str, dict]:
    now = _dt(data["as_of"]) or datetime.now(TZ)
    s = data["pnl_history"]["series"]
    base = s.get("bh_5050") or []
    bnav = float(base[-1]["nav"]) if base else None
    bl = base[-1] if base else {}
    days_left = (SCORE_DATE - now.date()).days
    ledgers = {
        "m_eq": read_ledger(root / "state" / "ledger.jsonl"),
        "m_cr": read_ledger(root / "sleeves" / "crypto" / "state" / "ledger.jsonl"),
        "a_eq": read_ledger(root / "sleeves" / "active" / "equity" / "state" / "ledger.jsonl"),
        "a_cr": read_ledger(root / "sleeves" / "active" / "crypto" / "state" / "ledger.jsonl"),
    }
    sleeves = [
        ("Momentum", data["household"], data["equity"], data["crypto"], s.get("household") or [], "m"),
        ("Active", data["active"]["household"], data["active"]["equity"], data["active"]["crypto"],
         s.get("active_household") or [], "a"),
    ]
    summary = {"as_of": data["as_of"], "baseline_nav": bnav, "days_left": days_left, "sleeves": {}}

    # 1. Scoreboard
    cards = []
    for name, hh, eq, cr, ser, key in sleeves:
        gap = round(float(hh["nav"]) - bnav, 2) if bnav else None
        gpct = gap / bnav * 100 if bnav else None
        gs = gap_series(ser, base)
        vals = [v for _, v in gs]
        wk = None
        if len(gs) >= 2:
            cutoff = (now.date() - timedelta(days=7)).isoformat()
            prev = [v for d, v in gs if d <= cutoff]
            wk = round(vals[-1] - (prev[-1] if prev else vals[0]), 2)
        need = (-gap / days_left) if gap is not None and gap < 0 and days_left > 0 else 0
        summary["sleeves"][name] = {"nav": hh["nav"], "gap": gap, "gap_pct": round(gpct, 3) if gpct is not None else None,
                                    "gap_change_7d": wk}
        status = "Ahead" if gap and gap > 0 else "Behind"
        cards.append(f"""<div class="card"><h3>{name} <span class="pill {'p-ok' if gap and gap > 0 else 'p-bad'}">{status}</span></h3>
<div class="big">{money(float(hh['nav']))}</div><div class="muted">P&amp;L {money(hh['total_pnl'], True)} ({pct(hh['total_pnl_pct'])}) on $125,000</div>
<div style="margin-top:8px">Gap to 50/50: <b class="{cls(gap)}">{money(gap, True)}</b> (<span class="{cls(gpct)}">{pct(gpct)}</span>)</div>
<div class="muted">7-day change in gap: <span class="{cls(wk)}">{money(wk, True)}</span>{f'. Needs about {money(need)} per day to catch up by 12/31.' if need else ''}</div>
{sparkline(vals)}<div class="muted">Daily gap since {gs[0][0][5:] if gs else 'n/a'} (dashed line is even)</div></div>""")
    base_card = f"""<div class="card"><h3>50/50 SPY+BTC baseline</h3><div class="big">{money(bnav)}</div>
<div class="muted">P&amp;L {money(bl.get('pnl'), True)} ({pct(bl.get('pnl_pct'))}). SPY leg {money(bl.get('spy_leg'))}, BTC leg {money(bl.get('btc_leg'))}.
$62,500 each from 9/20, no rebalance.</div><div style="margin-top:10px" class="big">{days_left} days</div>
<div class="muted">left until the 12/31/2026 scoreboard date. A sleeve that misses gets its strategy replaced.</div></div>"""
    chart = main_chart([
        ("50/50 SPY+BTC baseline", base, "#1f2328", ""),
        ("Momentum", s.get("household") or [], "#0969da", ""),
        ("Active", s.get("active_household") or [], "#bf3989", ""),
        ("SPY only", s.get("spy") or [], "#8c959f", "4 4"),
    ])
    sec1 = f"""<section id="scoreboard"><h2>1. Scoreboard: each sleeve vs the 50/50 baseline</h2>
<div class="grid">{''.join(cards)}{base_card}</div>
<h3 style="font-size:14px;margin:16px 0 4px">Household P&amp;L % since start</h3>{chart}
<p class="muted">Active started 9/24 and is compared with the same 9/20 baseline as Momentum, so both chase one number. Dashed grey is SPY alone for context.</p></section>"""

    # 2. Attribution
    att = []
    for name, hh, eq, cr, ser, key in sleeves:
        eq_pnl = float(eq["total_pnl"])
        cr_pnl = float(cr["total_pnl"])
        spy_leg = float(bl.get("spy_leg", 62500)) - 62500
        btc_leg = float(bl.get("btc_leg", 62500)) - 62500
        eq_gap, cr_gap = eq_pnl - spy_leg, cr_pnl - btc_leg
        summary["sleeves"][name].update({"equity_gap": round(eq_gap, 2), "crypto_gap": round(cr_gap, 2)})
        rows = contributions(eq, ledgers[key + "_eq"], "Equity") + contributions(cr, ledgers[key + "_cr"], "Crypto")
        rows = sorted(rows, key=lambda r: r[1])
        summary["sleeves"][name]["positions"] = [[t.replace("-USD", ""), v, st] for t, v, st in rows]
        summary["sleeves"][name].update({"equity_pnl": round(eq_pnl, 2), "crypto_pnl": round(cr_pnl, 2),
                                         "spy_leg_pnl": round(spy_leg, 2), "btc_leg_pnl": round(btc_leg, 2)})
        mx = max([abs(r[1]) for r in rows] + [1])
        trs = "".join(
            f'<tr><td>{escape(t.replace("-USD", ""))}</td><td class="muted">{st}</td><td class="n {cls(v)}">{money(v, True)}</td>'
            f'<td style="width:40%"><div class="bar"><span style="width:{abs(v)/mx*100:.0f}%;background:{"#1a7f37" if v >= 0 else "#cf222e"}"></span></div></td></tr>'
            for t, v, st in rows)
        att.append(f"""<div class="card"><h3>{name}</h3><table>
<tr><th>Leg</th><th class="n">Sleeve P&amp;L</th><th class="n">Baseline leg P&amp;L</th><th class="n">Gap</th></tr>
<tr><td>Equity ($100k vs SPY $62.5k)</td><td class="n {cls(eq_pnl)}">{money(eq_pnl, True)}</td><td class="n {cls(spy_leg)}">{money(spy_leg, True)}</td><td class="n {cls(eq_gap)}"><b>{money(eq_gap, True)}</b></td></tr>
<tr><td>Crypto ($25k vs BTC $62.5k)</td><td class="n {cls(cr_pnl)}">{money(cr_pnl, True)}</td><td class="n {cls(btc_leg)}">{money(btc_leg, True)}</td><td class="n {cls(cr_gap)}"><b>{money(cr_gap, True)}</b></td></tr>
<tr><td><b>Total</b></td><td></td><td></td><td class="n {cls(eq_gap+cr_gap)}"><b>{money(eq_gap + cr_gap, True)}</b></td></tr></table>
<h3 style="font-size:13px;margin:12px 0 4px">Per position, realized plus unrealized since start</h3><table>{trs}</table></div>""")
    sec2 = f"""<section id="attribution"><h2>2. Attribution: where the gap comes from</h2>
<p class="muted">Gap per leg is the sleeve leg's dollar P&amp;L minus the matching baseline leg's dollar P&amp;L. The baseline holds more BTC ($62.5k) than either sleeve's crypto book ($25k), so BTC moves weigh more on the baseline.</p>
<div class="grid">{''.join(att)}</div></section>"""

    # 3. Experiments
    ex = _load(root / "state" / "experiments.json", {}) or {}
    px = price_book(data)
    trs = []
    for e in ex.get("experiments") or []:
        txt, lead = (live_result(e["live"], data, root, px) if e.get("live") else (e.get("result_text", ""), None))
        dl = (date.fromisoformat(e["decide"]) - now.date()).days
        summary.setdefault("experiments", []).append({"name": e["name"], "sleeve": e["sleeve"], "hypothesis": e["hypothesis"],
            "result": txt, "lead_pts": lead, "decide": e["decide"], "days": dl, "status": e["status"]})
        trs.append(f"""<tr><td><b>{escape(e['name'])}</b><div class="muted">{escape(e['sleeve'])}. Control: {escape(e.get('control',''))}</div></td>
<td>{escape(e['hypothesis'])}<div class="muted">{escape(e.get('rule',''))}</div></td><td>{escape(txt)}</td>
<td class="n">{date.fromisoformat(e['decide']):%m/%d}<div class="muted">{dl} days</div></td><td><span class="pill p-{escape(e['status'])}">{escape(e['status'])}</span></td></tr>""")
    hist = "".join(f'<tr><td>{h["date"][5:]}</td><td>{escape(h["name"])}</td><td><span class="pill p-{escape(h["outcome"])}">{escape(h["outcome"])}</span></td><td class="muted">{escape(h["note"])}</td></tr>'
                   for h in ex.get("history") or [])
    summary["history"] = ex.get("history") or []
    sec3 = f"""<section id="experiments"><h2>3. Experiments</h2><table>
<tr><th>Trial</th><th>Hypothesis and rule</th><th>Shadow vs control</th><th class="n">Decide</th><th>Status</th></tr>{''.join(trs)}</table>
<h3 style="font-size:14px;margin:14px 0 4px">Decided</h3><table><tr><th>Date</th><th>Trial</th><th>Outcome</th><th>Note</th></tr>{hist}</table>
<p class="muted">Driven by state/experiments.json.</p></section>"""

    # 4. Health
    evals, counts, tickers, last = skip_summary(root)
    skip_rows = "".join(
        f'<tr><td>{escape(SKIP_LABELS.get(k, k))}</td><td class="n">{c}</td><td class="muted">{escape(", ".join(sorted(tickers[k]))[:120])}</td></tr>'
        for k, c in sorted(counts.items(), key=lambda kv: -kv[1]))
    planned = sum(len(d.get("planned_trades") or []) for _, d, _ in evals)
    summary["skips"] = {"evals": len(evals), "planned": planned, "latest": last[0] if last else None,
                        "reasons": [[SKIP_LABELS.get(k, k), c, ", ".join(sorted(tickers[k]))] for k, c in sorted(counts.items(), key=lambda kv: -kv[1])]}
    summary["books"] = []
    free_rows = []
    health_warn = []
    for name, sl, cap_key in [("Momentum equity", data["equity"], "m_eq"), ("Momentum crypto", data["crypto"], "m_cr"),
                              ("Active equity", data["active"]["equity"], "a_eq"), ("Active crypto", data["active"]["crypto"], "a_cr")]:
        floor = float((sl.get("caps") or {}).get("min_cash_pct", 0.2))
        free = float(sl["cash"]) - floor * float(sl["nav"])
        t30 = turnover(ledgers[cap_key], float(sl["starting_capital"]), 30, now)
        tall = turnover(ledgers[cap_key], float(sl["starting_capital"]), None, now)
        summary["books"].append([name, round(float(sl["cash"]), 2), round(floor * 100), round(free, 2), t30, tall])
        free_rows.append(f'<tr><td>{name}</td><td class="n">{money(float(sl["cash"]))}</td><td class="n">{floor*100:.0f}%</td>'
                         f'<td class="n {"neg" if free < 1000 and name.startswith("Active equity") else ""}">{money(free)}</td><td class="n">{t30:.0f}%</td><td class="n">{tall:.0f}%</td></tr>')
        if name == "Active equity" and free < 1000:
            health_warn.append(f"Active equity free cash above its 20% floor is {money(free)}, under the $1,000 minimum order, so new buy signals are skipped until something is sold. A fix is pending.")
    rs = routine_status(root, now)
    rrows = "".join(f'<tr><td>{escape(r["name"])}</td><td>{escape(r["last"])}</td><td><span class="pill {"p-ok" if r["ok"] else "p-bad"}">{"ok" if r["ok"] else "late or missed"}</span></td><td class="muted">{escape(r["detail"])}</td></tr>' for r in rs)
    summary["routines"] = rs
    warn = "".join(f'<div class="warn">{escape(w)}</div>' for w in health_warn)
    sec4 = f"""<section id="health"><h2>4. Health and friction</h2>{warn}
<div class="grid" style="margin-top:8px"><div class="card"><h3>Active equity skipped signals, last {len(evals)} evaluations</h3>
<div class="muted">{planned} fills planned. Latest eval {escape(last[0] if last else 'n/a')}.</div><table><tr><th>Reason</th><th class="n">Count</th><th>Tickers</th></tr>{skip_rows or '<tr><td colspan=3>None</td></tr>'}</table></div>
<div class="card"><h3>Routines</h3><table><tr><th>Routine</th><th>Last run</th><th>Status</th><th>Note</th></tr>{rrows}</table></div></div>
<h3 style="font-size:14px;margin:14px 0 4px">Idle cash and turnover</h3><table><tr><th>Book</th><th class="n">Cash</th><th class="n">Floor</th><th class="n">Free above floor</th><th class="n">Turnover 30d</th><th class="n">Since start</th></tr>{''.join(free_rows)}</table>
<p class="muted">Turnover is traded dollars (buys plus sells) over starting capital.</p></section>"""

    # 5. Risk
    vb0 = data["equity"].get("vs_benchmark") or {}
    vba0 = data["active"]["equity"].get("vs_benchmark") or {}
    bcur, bmdd = drawdown(base)
    rrows = []
    risk_warn = []
    for name, hh, eq, cr, ser, key in sleeves:
        cur, mdd = drawdown(ser)
        hold = [(h["ticker"], float(h["market_value"])) for h in (eq.get("holdings") or []) + (cr.get("holdings") or [])]
        nav = float(hh["nav"])
        top = max(hold, key=lambda x: x[1]) if hold else ("none", 0)
        cr_share = float(cr["nav"]) / nav * 100 if nav else 0
        cr_dd = float(cr.get("drawdown_pct") or 0)
        rrows.append(f'<tr><td>{name}</td><td class="n {cls(cur)}">{pct(cur)}</td><td class="n {cls(mdd)}">{pct(mdd)}</td>'
                     f'<td>{escape(top[0].replace("-USD",""))} {top[1]/nav*100:.1f}%</td><td class="n">{cr_share:.1f}%</td><td class="n {cls(cr_dd)}">{pct(cr_dd, 1)}</td></tr>')
        summary["sleeves"][name].update({"drawdown": cur, "max_drawdown": mdd, "top": top[0].replace("-USD", ""),
                                         "top_pct": round(top[1] / nav * 100, 1) if nav else 0, "crypto_share": round(cr_share, 1),
                                         "crypto_dd": cr_dd})
        if cr_dd <= -10:
            risk_warn.append(f"{name} crypto is {abs(cr_dd):.1f}% below its peak.")
    summary["baseline_dd"] = [bcur, bmdd]
    summary["warnings"] = health_warn + risk_warn
    summary["spy_start"] = {"momentum": vb0.get("start_close"), "active": vba0.get("start_close"),
                            "spy_ret": vb0.get("return_pct"), "rule": "last print at or before sleeve start (same as B&H series)"}
    rrows.append(f'<tr><td>50/50 baseline</td><td class="n {cls(bcur)}">{pct(bcur)}</td><td class="n {cls(bmdd)}">{pct(bmdd)}</td><td>BTC and SPY 50% each at start</td><td class="n">{float(bl.get("btc_leg",0))/bnav*100 if bnav else 0:.1f}%</td><td></td></tr>')
    sec5 = f"""<section id="risk"><h2>5. Risk</h2>{''.join(f'<div class="warn">{escape(w)}</div>' for w in risk_warn)}
<table style="margin-top:8px"><tr><th>Book</th><th class="n">Drawdown now</th><th class="n">Max drawdown</th><th>Largest position</th><th class="n">Crypto share</th><th class="n">Crypto book from peak</th></tr>{''.join(rrows)}</table>
<p class="muted">Drawdowns are from the household P&amp;L series (peak to now). Largest position is a share of household NAV.</p></section>"""

    # 6. Benchmark note
    vb = data["equity"].get("vs_benchmark") or {}
    vba = data["active"]["equity"].get("vs_benchmark") or {}
    sec6 = f"""<section id="method"><h2>Benchmark start prices</h2><p class="muted">One rule for every comparison: the start price is the last SPY or BTC print at or before the sleeve start timestamp, the same one the buy-and-hold series use.
Momentum (start 9/20, a Sunday) uses the 9/18 SPY close ${vb.get('start_close', 0):,.2f}, so SPY is {pct(vb.get('return_pct'))} since start. Active (start 9/24 9:11 AM) uses SPY ${vba.get('start_close', 0):,.2f}, {pct(vba.get('return_pct'))}.
Momentum equity vs SPY: {pct(float(data['equity']['total_pnl_pct']) - float(vb.get('return_pct') or 0))}. Momentum crypto vs BTC: {pct(float(data['crypto']['total_pnl_pct']) - float((data['crypto'].get('vs_benchmark') or {}).get('return_pct') or 0))}.</p></section>"""

    head = f"""<h1>Paper portfolio scoreboard</h1><div class="sub">As of {escape(data['as_of_display'])}. Goal: each sleeve beats a 50/50 SPY+BTC buy-and-hold by 12/31/2026. {nav_links('index.html')}</div>"""
    html = page("Paper portfolio scoreboard", head + sec1 + sec2 + sec3 + sec4 + sec5 + sec6, data["as_of_display"])
    return html, summary


def build_strategy(strategy_html: str, arch_html: str, now_txt: str) -> str:
    body = f"""<h1>Strategy</h1><div class="sub">{nav_links('strategy.html')}</div><section>{strategy_html}</section><section>{arch_html}</section>"""
    return page("Paper portfolio strategy", body, now_txt)


def build_changelog(root: Path, now_txt: str) -> str:
    text = (root / "STRATEGY_CHANGELOG.md").read_text() if (root / "STRATEGY_CHANGELOG.md").exists() else ""
    entries = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        lines = block.strip().splitlines()
        title = lines[0].strip()
        m = re.match(r"(\d{4}-\d{2}-\d{2})[,:]?\s*(.*)", title)
        d, t = (m.group(1), m.group(2)) if m else ("", title)
        body = "\n".join(lines[1:])
        sleeve = re.search(r"\*\*Sleeve:\*\*\s*(.+)", body)
        change = re.search(r"\*\*(Change|Logic):\*\*\s*(.+)", body)
        judge = re.search(r"\*\*How we judge:\*\*\s*(.+)", body)
        summ = change.group(2) if change else (lines[1] if len(lines) > 1 else "")
        summ = re.sub(r"[`*]", "", summ)
        if len(summ) > 260:
            summ = summ[:257].rsplit(" ", 1)[0] + "..."
        entries.append((d, t, re.sub(r"[`*]", "", sleeve.group(1)) if sleeve else "", summ,
                        re.sub(r"[`*]", "", judge.group(1))[:200] if judge else ""))
    entries.sort(key=lambda e: e[0], reverse=True)
    rows = "".join(f'<tr><td>{escape(d)}</td><td><b>{escape(t)}</b><div class="muted">{escape(s)}</div></td><td>{escape(c)}<div class="muted">{("Judge: " + escape(j)) if j else ""}</div></td></tr>' for d, t, s, c, j in entries)
    body = f"""<h1>Rule changelog</h1><div class="sub">{nav_links('changelog.html')}. Full text: <a href="./STRATEGY_CHANGELOG.md">STRATEGY_CHANGELOG.md</a></div>
<section><table><tr><th>Date</th><th>Change</th><th>What and how judged</th></tr>{rows}</table></section>"""
    return page("Paper portfolio rule changelog", body, now_txt)


def nodash(s: str) -> str:
    return s.replace("\u2014", ", ").replace("\u2013", "-")


def render_all(data: dict, root: Path, strategy_html: str, arch_html: str) -> dict:
    reports = root / "reports"
    html, summary = build_scoreboard(data, root)
    (reports / "dashboard.html").write_text(nodash(html), encoding="utf-8")
    (reports / "strategy.html").write_text(nodash(build_strategy(strategy_html, arch_html, data["as_of_display"])), encoding="utf-8")
    (reports / "changelog.html").write_text(nodash(build_changelog(root, data["as_of_display"])), encoding="utf-8")
    (reports / "scoreboard.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary

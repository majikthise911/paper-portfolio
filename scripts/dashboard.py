#!/usr/bin/env python3
"""Build a self-contained HTML dashboard for equity + crypto paper sleeves."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
EQUITY_PORTFOLIO = ROOT / "state" / "portfolio.json"
EQUITY_LEDGER = ROOT / "state" / "ledger.jsonl"
EQUITY_RULES = ROOT / "config" / "rules.json"
EQUITY_UNIVERSE = ROOT / "config" / "universe.json"

CRYPTO_ROOT = ROOT / "sleeves" / "crypto"
CRYPTO_PORTFOLIO = CRYPTO_ROOT / "state" / "portfolio.json"
CRYPTO_LEDGER = CRYPTO_ROOT / "state" / "ledger.jsonl"
CRYPTO_RULES = CRYPTO_ROOT / "config" / "rules.json"
CRYPTO_UNIVERSE = CRYPTO_ROOT / "config" / "universe.json"

REPORTS = ROOT / "reports"
HTML_OUT = REPORTS / "dashboard.html"
DATA_OUT = REPORTS / "dashboard_data.json"
PNL_HISTORY_OUT = REPORTS / "pnl_history.json"
TZ = ZoneInfo("America/New_York")
LEDGER_PNL_TYPES = frozenset({"init", "mark", "trade_batch"})
NAV_MATERIAL_USD = 0.01


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def last_close(ticker: str):
    """Return last available close or None if fetch fails."""
    try:
        hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"WARN: failed to price {ticker}: {e}", file=sys.stderr)
        return None


def parse_et_date(iso_ts: str | None) -> date | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        else:
            dt = dt.astimezone(TZ)
        return dt.date()
    except Exception:
        return None


def portfolio_start_date(pf: dict, ledger_path: Path) -> date | None:
    """Best-effort start date for since-start return comparisons."""
    dates: list[date] = []
    if ledger_path.exists():
        try:
            for line in ledger_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("type") == "init":
                    d = parse_et_date(entry.get("ts"))
                    if d:
                        return d
                d = parse_et_date(entry.get("ts"))
                if d:
                    dates.append(d)
        except Exception:
            pass
    for pos in (pf.get("positions") or {}).values():
        d = parse_et_date(pos.get("opened_at"))
        if d:
            dates.append(d)
    d = parse_et_date(pf.get("as_of"))
    if d:
        dates.append(d)
    return min(dates) if dates else None


def bench_return_since(
    ticker: str, start: date | None, today: date, last_px: float | None
) -> dict:
    label = ticker
    out = {
        "benchmark": ticker,
        "return_pct": 0.0,
        "same_day": True,
        "start_close": None,
        "end_close": last_px,
        "note": (
            f"Versus {label} compares sleeve total return since start to {label} total "
            "return over the same window. Start date is today, so both returns "
            "are treated as 0.0% for this same-day view."
        ),
    }
    if start is None or start >= today:
        return out

    out["same_day"] = False
    try:
        hist = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=(today.fromordinal(today.toordinal() + 1)).isoformat(),
            auto_adjust=True,
        )
        if hist is None or hist.empty or len(hist) < 1:
            out["note"] = (
                f"Versus {label} could not be computed because history was "
                "unavailable for the start window."
            )
            out["return_pct"] = None
            return out
        start_px = float(hist["Close"].iloc[0])
        end_px = float(hist["Close"].iloc[-1]) if last_px is None else float(last_px)
        out["start_close"] = round(start_px, 4)
        out["end_close"] = round(end_px, 4)
        ret = ((end_px / start_px) - 1.0) * 100.0 if start_px else 0.0
        out["return_pct"] = round(ret, 4)
        out["note"] = (
            f"Versus {label} is sleeve total return since start minus {label} total "
            "return since the sleeve start date (rough, price-only)."
        )
    except Exception as e:
        print(f"WARN: {ticker} history failed: {e}", file=sys.stderr)
        out["return_pct"] = None
        out["note"] = (
            f"Versus {label} could not be computed because history fetch failed."
        )
    return out


def fmt_money(v: float | None) -> str:
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def fmt_pct(v: float | None, places: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.{places}f}%" if places else f"{v:+.0f}%"


def fmt_pct_plain(v: float | None, places: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{places}f}%"


def pnl_class(v: float | None) -> str:
    if v is None or abs(v) < 1e-9:
        return "flat"
    return "pos" if v > 0 else "neg"


def mark_sleeve(
    pf: dict,
    portfolio_path: Path,
    ledger_path: Path,
    benchmark: str,
    bench_key: str,
    default_starting: float,
    as_of: str,
    price_decimals: int = 4,
) -> dict:
    """Refresh prices for one sleeve; optionally light-mark portfolio.json."""
    prev_nav = float(pf.get("nav", 0))
    cash = float(pf.get("cash", 0))
    starting = float(pf.get("starting_capital", default_starting))
    positions = pf.get("positions") or {}

    failed: list[str] = []
    prices_ok = 0
    prices_attempted = 0
    holdings_value = 0.0
    holdings: list[dict] = []

    for ticker, pos in sorted(positions.items()):
        shares = float(pos.get("shares", 0))
        if shares == 0:
            continue
        prices_attempted += 1
        px = last_close(ticker)
        stale = False
        if px is None:
            failed.append(ticker)
            px = float(pos.get("last_price") or 0)
            stale = True
        else:
            prices_ok += 1
            pos["last_price"] = round(px, price_decimals)

        mv = shares * px
        holdings_value += mv
        pos["market_value"] = round(mv, 2)

        cost_basis = float(
            pos.get("cost_basis") or (shares * float(pos.get("avg_cost") or 0))
        )
        avg_cost = float(
            pos.get("avg_cost") or (cost_basis / shares if shares else 0)
        )
        upnl = mv - cost_basis
        upnl_pct = (upnl / cost_basis * 100.0) if cost_basis else 0.0

        holdings.append(
            {
                "ticker": ticker,
                "shares": shares,
                "avg_cost": round(avg_cost, price_decimals),
                "cost_basis": round(cost_basis, 2),
                "last_price": round(px, price_decimals),
                "market_value": round(mv, 2),
                "unrealized_pnl": round(upnl, 2),
                "unrealized_pnl_pct": round(upnl_pct, 4),
                "sector": pos.get("sector"),
                "stale": stale,
            }
        )

    bench_px = last_close(benchmark)
    if bench_px is None:
        failed.append(benchmark)
        bench_px = pf.get(bench_key)
        if bench_px is not None:
            bench_px = float(bench_px)

    nav = round(cash + holdings_value, 2)
    invested = round(holdings_value, 2)
    total_pnl = round(nav - starting, 2)
    if abs(total_pnl) < 0.005:
        total_pnl = 0.0
    total_pnl_pct = (total_pnl / starting) * 100.0 if starting else 0.0
    if abs(total_pnl_pct) < 1e-9:
        total_pnl_pct = 0.0
    peak = max(float(pf.get("peak_nav", starting)), nav)
    drawdown_pct = ((nav / peak) - 1.0) * 100.0 if peak else 0.0
    if abs(drawdown_pct) < 1e-9:
        drawdown_pct = 0.0
    cash_weight_pct = (cash / nav * 100.0) if nav else 100.0
    invested_pct = (invested / nav * 100.0) if nav else 0.0

    for h in holdings:
        h["weight_pct"] = round((h["market_value"] / nav * 100.0) if nav else 0.0, 4)

    prices_refreshed = (
        prices_attempted > 0
        and prices_ok == prices_attempted
        and benchmark not in failed
    )
    any_price_update = prices_ok > 0 or (
        bench_px is not None and benchmark not in failed
    )
    # Cash-only sleeve: still update as_of / nav when we can price the benchmark
    if prices_attempted == 0 and bench_px is not None and benchmark not in failed:
        any_price_update = True
        prices_refreshed = True

    if any_price_update:
        pf["as_of"] = as_of
        pf["cash"] = round(cash, 2)
        pf["positions"] = positions
        pf["nav"] = round(nav, 2)
        pf["peak_nav"] = round(peak, 2)
        if bench_px is not None:
            pf[bench_key] = round(bench_px, 4)
        pf["total_pnl"] = round(total_pnl, 2)
        pf["total_pnl_pct"] = round(total_pnl_pct, 4)
        pf["drawdown_pct"] = round(drawdown_pct, 4)
        save_json(portfolio_path, pf)

        if abs(nav - prev_nav) >= NAV_MATERIAL_USD:
            ledger_entry = {
                "ts": as_of,
                "type": "mark",
                "cash": round(cash, 2),
                "nav": round(nav, 2),
                "holdings_value": round(holdings_value, 2),
                bench_key: pf.get(bench_key),
                "failed_tickers": failed,
                "source": "dashboard",
            }
            with open(ledger_path, "a") as f:
                f.write(json.dumps(ledger_entry) + "\n")
            print(
                f"{portfolio_path.parent.parent.name or 'equity'} ledger mark "
                f"(NAV {prev_nav:.2f} -> {nav:.2f})"
            )
        else:
            print(f"NAV unchanged materially ({nav:.2f}); no ledger mark for {portfolio_path}")

    return {
        "as_of": as_of,
        "nav": round(nav, 2),
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "invested_pct": round(invested_pct, 4),
        "cash_weight_pct": round(cash_weight_pct, 4),
        "starting_capital": starting,
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 4),
        "unrealized_pnl_total": round(sum(h["unrealized_pnl"] for h in holdings), 2),
        "peak_nav": round(peak, 2),
        "drawdown_pct": round(drawdown_pct, 4),
        "benchmark": benchmark,
        "bench_last_close": round(bench_px, 4) if bench_px is not None else None,
        "holdings": holdings,
        "prices_refreshed": bool(prices_refreshed),
        "prices_ok": prices_ok,
        "prices_attempted": prices_attempted,
        "failed_tickers": failed,
        "notes": pf.get("notes"),
        "any_price_update": any_price_update,
    }


def holdings_table_rows(holdings: list[dict], empty_msg: str, sleeve: str) -> str:
    rows = []
    for h in holdings:
        upnl = h["unrealized_pnl"]
        qty = h["shares"]
        qty_s = f"{qty:g}" if qty == int(qty) else f"{qty:.6f}".rstrip("0").rstrip(".")
        src = "stale" if h.get("stale") else "mark"
        rows.append(
            f'<tr data-sleeve="{sleeve}" data-ticker="{h["ticker"]}">'
            f'<td class="ticker">{h["ticker"]}</td>'
            f'<td class="num" data-field="shares">{qty_s}</td>'
            f'<td class="num" data-field="avg-cost">{fmt_money(h["avg_cost"])}</td>'
            f'<td class="num" data-field="price">{fmt_money(h["last_price"])}</td>'
            f'<td class="num" data-field="mv">{fmt_money(h["market_value"])}</td>'
            f'<td class="num" data-field="weight">{fmt_pct_plain(h["weight_pct"])}</td>'
            f'<td class="num {pnl_class(upnl)}" data-field="upnl">{fmt_money(upnl)} '
            f'({fmt_pct(h["unrealized_pnl_pct"])})</td>'
            f'<td class="muted" data-field="src">{src}</td>'
            "</tr>"
        )
    if not rows:
        rows.append(f'<tr><td colspan="8" class="muted">{empty_msg}</td></tr>')
    return "".join(rows)



def render_pnl_svg(hist: dict, metric: str = "pnl") -> str:
    """Pre-render P&L chart SVG so it is visible even if JS fails."""
    series = (hist or {}).get("series") or {}
    def pts(name):
        out = []
        for p in series.get(name) or []:
            try:
                dt = datetime.fromisoformat(p["ts"])
                y = float(p["pnl"] if metric == "pnl" else p["nav"])
            except Exception:
                continue
            out.append((dt.timestamp(), y, p["ts"]))
        out.sort()
        return out
    hh, eq, cr = pts("household"), pts("equity"), pts("crypto")
    allp = hh + eq + cr
    W, H = 1000, 280
    pad = {"l": 64, "r": 16, "t": 16, "b": 40}
    iw, ih = W - pad["l"] - pad["r"], H - pad["t"] - pad["b"]
    if not allp:
        return (
            '<text x="500" y="140" text-anchor="middle" class="axis-label">'
            "No history yet. History will fill in as daily marks run.</text>"
        )
    t_min = min(p[0] for p in allp)
    t_max = max(p[0] for p in allp)
    y_min = min(p[1] for p in allp)
    y_max = max(p[1] for p in allp)
    if metric == "pnl":
        y_min = min(y_min, 0.0)
        y_max = max(y_max, 0.0)
    if t_max == t_min:
        t_max = t_min + 1
    y_pad = (y_max - y_min) * 0.08 or 1.0
    y_min -= y_pad
    y_max += y_pad

    def x(t):
        return pad["l"] + (t - t_min) / (t_max - t_min) * iw

    def y(v):
        return pad["t"] + (y_max - v) / (y_max - y_min) * ih

    parts = []
    for i in range(6):
        v = y_min + (y_max - y_min) * i / 5
        yy = y(v)
        parts.append(
            f'<line class="grid-line" x1="{pad["l"]}" y1="{yy:.2f}" x2="{W - pad["r"]}" y2="{yy:.2f}" />'
        )
        if abs(v) >= 1000:
            lab = f"${v/1000:.1f}k"
        else:
            lab = f"${v:.0f}"
        parts.append(
            f'<text class="axis-label" x="{pad["l"] - 8}" y="{yy + 4:.2f}" text-anchor="end">{lab}</text>'
        )
    if y_min < 0 < y_max:
        zy = y(0)
        parts.append(
            f'<line class="zero-line" x1="{pad["l"]}" y1="{zy:.2f}" x2="{W - pad["r"]}" y2="{zy:.2f}" />'
        )
    parts.append(
        f'<line class="axis" x1="{pad["l"]}" y1="{pad["t"]}" x2="{pad["l"]}" y2="{H - pad["b"]}" />'
    )
    parts.append(
        f'<line class="axis" x1="{pad["l"]}" y1="{H - pad["b"]}" x2="{W - pad["r"]}" y2="{H - pad["b"]}" />'
    )
    for t, v, _ts in (hh[0], hh[len(hh) // 2], hh[-1]) if hh else []:
        d = datetime.fromtimestamp(t, TZ)
        lab = d.strftime("%m/%d %H:%M")
        parts.append(
            f'<text class="axis-label" x="{x(t):.2f}" y="{H - 12}" text-anchor="middle">{lab}</text>'
        )

    def path(pts, cls):
        if not pts:
            return ""
        d = " ".join(
            (("M" if i == 0 else "L") + f"{x(t):.2f} {y(v):.2f}")
            for i, (t, v, _) in enumerate(pts)
        )
        return f'<path class="{cls}" d="{d}" />'

    def dots(pts, dcls):
        return "".join(
            f'<circle class="dot {dcls}" cx="{x(t):.2f}" cy="{y(v):.2f}" r="3.2" />'
            for t, v, _ in pts
        )

    parts.append(path(hh, "line-hh"))
    parts.append(path(eq, "line-eq"))
    parts.append(path(cr, "line-cr"))
    parts.append(dots(hh, "dot-hh"))
    parts.append(dots(eq, "dot-eq"))
    parts.append(dots(cr, "dot-cr"))
    return "\n".join(parts)



def architecture_section() -> str:
    """Embed architecture diagram (PNG preferred, SVG fallback)."""
    png_path = REPORTS / "architecture.png"
    svg_path = REPORTS / "architecture.svg"
    blurb = (
        "How Paper runs the simulated book: chat approval, locked rules, local ledger, "
        "weekly mark, yfinance prices, reports, then GitHub Pages. Crypto is a separate "
        "booked sleeve under sleeves/crypto/. It is never mixed into the equity momentum rank."
    )
    if png_path.exists():
        import base64

        b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
        img = (
            f'<img class="arch-img" alt="Paper portfolio system architecture flowchart" '
            f'src="data:image/png;base64,{b64}"/>'
        )
    elif svg_path.exists():
        img = f'<div class="arch-svg-wrap">{svg_path.read_text()}</div>'
    else:
        img = '<p class="blurb">Architecture diagram not found in reports/.</p>'
    return f"""
  <section>
    <h2>System architecture</h2>
    <p class="blurb">{blurb}</p>
    {img}
  </section>
"""



def parse_et_dt(iso_ts: str | None) -> datetime | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        else:
            dt = dt.astimezone(TZ)
        return dt
    except Exception:
        return None


def ledger_nav(entry: dict) -> float | None:
    """NAV from init/mark/trade_batch ledger lines."""
    if entry.get("type") == "trade_batch":
        raw = entry.get("nav_after", entry.get("nav"))
    else:
        raw = entry.get("nav")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def sleeve_pnl_series(
    ledger_path: Path,
    starting_capital: float,
    portfolio_path: Path | None = None,
) -> list[dict]:
    """Time series of sleeve NAV and P&L from ledger (+ optional current portfolio)."""
    by_ts: dict[str, dict] = {}

    def add_point(ts: str, nav: float) -> None:
        nav_r = round(float(nav), 2)
        pnl = round(nav_r - starting_capital, 2)
        if abs(pnl) < 0.005:
            pnl = 0.0
        by_ts[ts] = {
            "ts": ts,
            "nav": nav_r,
            "pnl": pnl,
            "starting_capital": float(starting_capital),
        }

    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") not in LEDGER_PNL_TYPES:
                continue
            ts = entry.get("ts")
            nav = ledger_nav(entry)
            if not ts or nav is None:
                continue
            add_point(str(ts), nav)

    # Seed at least a start point from starting capital if empty
    if not by_ts:
        seed_ts = None
        if portfolio_path and portfolio_path.exists():
            try:
                pf = load_json(portfolio_path)
                seed_ts = pf.get("as_of")
            except Exception:
                seed_ts = None
        if not seed_ts:
            seed_ts = datetime.now(TZ).isoformat(timespec="seconds")
        add_point(str(seed_ts), float(starting_capital))

    # Optionally append current portfolio as_of if newer than last ledger line
    if portfolio_path and portfolio_path.exists():
        try:
            pf = load_json(portfolio_path)
            pf_ts = pf.get("as_of")
            pf_nav = pf.get("nav")
            if pf_ts is not None and pf_nav is not None:
                last_ts = max(by_ts.keys()) if by_ts else None
                last_dt = parse_et_dt(last_ts) if last_ts else None
                pf_dt = parse_et_dt(str(pf_ts))
                if pf_dt is not None and (last_dt is None or pf_dt > last_dt):
                    add_point(str(pf_ts), float(pf_nav))
                elif last_ts is None:
                    add_point(str(pf_ts), float(pf_nav))
        except Exception:
            pass

    def sort_key(ts: str):
        dt = parse_et_dt(ts)
        return dt or datetime.min.replace(tzinfo=TZ)

    return [by_ts[k] for k in sorted(by_ts.keys(), key=sort_key)]


def align_household_series(
    equity: list[dict],
    crypto: list[dict],
    equity_start: float,
    crypto_start: float,
) -> list[dict]:
    """Align sleeve series on unique timestamps with carry-forward NAVs."""
    hh_start = float(equity_start) + float(crypto_start)
    eq_map = {p["ts"]: p for p in equity}
    cr_map = {p["ts"]: p for p in crypto}
    all_ts = set(eq_map) | set(cr_map)

    def sort_key(ts: str):
        dt = parse_et_dt(ts)
        return dt or datetime.min.replace(tzinfo=TZ)

    ordered = sorted(all_ts, key=sort_key)
    if not ordered:
        # Seed household at combined start
        ts = datetime.now(TZ).isoformat(timespec="seconds")
        return [
            {
                "ts": ts,
                "nav": round(hh_start, 2),
                "pnl": 0.0,
                "equity_nav": round(equity_start, 2),
                "crypto_nav": round(crypto_start, 2),
                "starting_capital": round(hh_start, 2),
            }
        ]

    latest_eq = float(equity_start)
    latest_cr = float(crypto_start)
    # If we have points before first timestamp, start from capital;
    # once we see a sleeve point, carry forward.
    out: list[dict] = []
    for ts in ordered:
        if ts in eq_map:
            latest_eq = float(eq_map[ts]["nav"])
        if ts in cr_map:
            latest_cr = float(cr_map[ts]["nav"])
        nav = round(latest_eq + latest_cr, 2)
        pnl = round(nav - hh_start, 2)
        if abs(pnl) < 0.005:
            pnl = 0.0
        out.append(
            {
                "ts": ts,
                "nav": nav,
                "pnl": pnl,
                "equity_nav": round(latest_eq, 2),
                "crypto_nav": round(latest_cr, 2),
                "starting_capital": round(hh_start, 2),
            }
        )
    return out


def build_pnl_history(
    equity_ledger: Path,
    crypto_ledger: Path,
    equity_portfolio: Path,
    crypto_portfolio: Path,
    equity_start: float = 100000.0,
    crypto_start: float = 25000.0,
) -> dict:
    """Build household + sleeve P&L time series for the dashboard chart."""
    eq_start = equity_start
    cr_start = crypto_start
    if equity_portfolio.exists():
        try:
            eq_start = float(load_json(equity_portfolio).get("starting_capital", equity_start))
        except Exception:
            pass
    if crypto_portfolio.exists():
        try:
            cr_start = float(load_json(crypto_portfolio).get("starting_capital", crypto_start))
        except Exception:
            pass

    equity = sleeve_pnl_series(equity_ledger, eq_start, equity_portfolio)
    crypto = sleeve_pnl_series(crypto_ledger, cr_start, crypto_portfolio)
    household = align_household_series(equity, crypto, eq_start, crypto_start)

    return {
        "as_of": datetime.now(TZ).isoformat(timespec="seconds"),
        "currency": "USD",
        "default_metric": "pnl",
        "starting_capital": {
            "equity": round(eq_start, 2),
            "crypto": round(cr_start, 2),
            "household": round(eq_start + cr_start, 2),
        },
        "counts": {
            "equity": len(equity),
            "crypto": len(crypto),
            "household": len(household),
        },
        "series": {
            "equity": equity,
            "crypto": crypto,
            "household": household,
        },
        "note": (
            "History will fill in as daily marks run."
            if min(len(equity), len(crypto), len(household)) < 2
            else None
        ),
    }


def build_html(data: dict) -> str:
    eq = data["equity"]
    cr = data["crypto"]
    hh = data["household"]
    pnl_hist = data.get("pnl_history") or {}

    eq_rows = holdings_table_rows(
        eq["holdings"], "No open equity positions. Equity book cash only.", "equity"
    )
    cr_empty = (
        "No open crypto positions."
        if cr.get("status") == "booked" or cr["holdings"]
        else "No open crypto positions. Crypto sleeve awaiting positions."
    )
    cr_rows = holdings_table_rows(cr["holdings"], cr_empty, "crypto")

    eq_prices_note = (
        "Embedded equity mark from last dashboard rebuild (yfinance)."
        if eq["prices_refreshed"]
        else "Equity price refresh incomplete; showing last booked prices where needed."
    )
    if eq["failed_tickers"]:
        eq_prices_note += f" Failed: {', '.join(eq['failed_tickers'])}."

    if not cr["holdings"]:
        cr_prices_note = "Crypto sleeve has no open positions; BTC-USD benchmark priced for reference."
    elif cr["prices_refreshed"]:
        cr_prices_note = "Embedded crypto mark from last dashboard rebuild (yfinance). Browser may refresh via CoinGecko."
    else:
        cr_prices_note = "Crypto price refresh incomplete; showing last booked prices where needed."
    if cr["failed_tickers"]:
        cr_prices_note += f" Failed: {', '.join(cr['failed_tickers'])}."

    eq_caps = eq["caps"]
    cr_caps = cr["caps"]

    vs_spy = eq["vs_benchmark"]
    port_ret = eq["total_pnl_pct"]
    spy_ret = vs_spy.get("return_pct")
    if spy_ret is None:
        vs_spy_display = "n/a"
        vs_spy_detail = vs_spy["note"]
        vs_class = "flat"
    else:
        alpha = port_ret - spy_ret
        vs_spy_display = f"{alpha:+.2f} pp"
        vs_spy_detail = (
            f"Equity {fmt_pct(port_ret)} since start vs SPY {fmt_pct(spy_ret)}. "
            f"{vs_spy['note']}"
        )
        vs_class = pnl_class(alpha)

    cr_nav_sub = f"Cash {fmt_money(cr['cash'])}"
    if cr.get("status") == "cash_only" and not cr["holdings"]:
        cr_nav_sub = "Cash sleeve (no positions yet)"

    book = {
        "generated_at": data["as_of"],
        "as_of": data["as_of"],
        "as_of_display": data["as_of_display"],
        "equity": {
            "cash": eq["cash"],
            "starting_capital": eq["starting_capital"],
            "spy_last_close": eq.get("bench_last_close"),
            "peak_nav": eq.get("peak_nav"),
            "positions": [
                {
                    "ticker": h["ticker"],
                    "shares": h["shares"],
                    "avg_cost": h["avg_cost"],
                    "cost_basis": h["cost_basis"],
                    "sector": h.get("sector"),
                    "last_price": h["last_price"],
                }
                for h in eq["holdings"]
            ],
        },
        "crypto": {
            "cash": cr["cash"],
            "starting_capital": cr["starting_capital"],
            "btc_last_close": cr.get("bench_last_close"),
            "peak_nav": cr.get("peak_nav"),
            "positions": [
                {
                    "ticker": h["ticker"],
                    "shares": h["shares"],
                    "avg_cost": h["avg_cost"],
                    "cost_basis": h["cost_basis"],
                    "sector": h.get("sector"),
                    "last_price": h["last_price"],
                }
                for h in cr["holdings"]
            ],
        },
    }
    book_json = json.dumps(book, separators=(",", ":"))
    pnl_json = json.dumps(pnl_hist, separators=(",", ":"))
    sparse_note = ""
    counts = (pnl_hist or {}).get("counts") or {}
    series = (pnl_hist or {}).get("series") or {}
    min_pts = min(
        (counts.get("household") or len(series.get("household") or [])),
        (counts.get("equity") or len(series.get("equity") or []) or 0) or 0,
        (counts.get("crypto") or len(series.get("crypto") or []) or 0) or 0,
    ) if pnl_hist else 0
    # Prefer explicit note; also show if any series has < 2 points
    note_text = (pnl_hist or {}).get("note")
    hh_n = len(series.get("household") or [])
    eq_n = len(series.get("equity") or [])
    cr_n = len(series.get("crypto") or [])
    if note_text or hh_n < 2 or eq_n < 2 or cr_n < 2:
        note_text = note_text or "History will fill in as daily marks run."
        sparse_note = (
            f'<p class="blurb" id="pnl-history-note">{note_text}</p>'
        )
    else:
        sparse_note = '<p class="blurb" id="pnl-history-note" hidden></p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paper Portfolio</title>
<style>
  :root {{
    --bg: #0f1419;
    --panel: #1a2332;
    --panel-border: #2a3548;
    --text: #e7ecf3;
    --muted: #9aa8bc;
    --accent: #5b9fd4;
    --pos: #3ecf8e;
    --neg: #f07178;
    --flat: #c5cdd8;
    --card-shadow: 0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px rgba(0,0,0,0.35);
    --font: "Segoe UI", system-ui, -apple-system, sans-serif;
    --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 24px 20px 48px;
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    line-height: 1.45;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  header {{ margin-bottom: 16px; }}
  h1 {{
    margin: 0 0 6px;
    font-size: 1.75rem;
    font-weight: 650;
    letter-spacing: -0.02em;
  }}
  .asof {{ color: var(--muted); font-size: 0.95rem; }}
  .status-bar {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 14px;
    margin-bottom: 22px;
    padding: 10px 14px;
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 10px;
    box-shadow: var(--card-shadow);
  }}
  #live-status {{ flex: 1 1 240px; color: var(--muted); font-size: 0.9rem; }}
  #live-status.live {{ color: var(--pos); }}
  #live-status.mark {{ color: var(--muted); }}
  #live-status.partial {{ color: var(--accent); }}
  #btn-refresh {{
    appearance: none;
    border: 1px solid var(--panel-border);
    background: #243044;
    color: var(--text);
    border-radius: 8px;
    padding: 7px 12px;
    font: inherit;
    font-size: 0.85rem;
    cursor: pointer;
  }}
  #btn-refresh:hover {{ border-color: var(--accent); }}
  #btn-refresh:disabled {{ opacity: 0.55; cursor: wait; }}
  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: var(--card-shadow);
  }}
  .card .label {{
    color: var(--muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 6px;
  }}
  .card .value {{
    font-size: 1.35rem;
    font-weight: 650;
    font-variant-numeric: tabular-nums;
  }}
  .card .sub {{
    margin-top: 4px;
    font-size: 0.8rem;
    color: var(--muted);
  }}
  .pos {{ color: var(--pos); }}
  .neg {{ color: var(--neg); }}
  .flat {{ color: var(--flat); }}
  section {{
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    padding: 18px 20px;
    margin-bottom: 18px;
    box-shadow: var(--card-shadow);
  }}
  section h2 {{
    margin: 0 0 12px;
    font-size: 1.05rem;
    font-weight: 600;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
    font-variant-numeric: tabular-nums;
  }}
  th, td {{
    text-align: left;
    padding: 8px 10px;
    border-bottom: 1px solid var(--panel-border);
  }}
  th {{
    color: var(--muted);
    font-weight: 550;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  td.num, th.num {{ text-align: right; }}
  td.ticker {{ font-family: var(--mono); font-weight: 600; }}
  .muted {{ color: var(--muted); }}
  .blurb {{ color: var(--muted); font-size: 0.9rem; margin: 0 0 10px; }}
  ul.caps {{
    margin: 0;
    padding-left: 1.2rem;
    color: var(--text);
  }}
  ul.caps li {{ margin: 4px 0; }}
  footer {{
    margin-top: 8px;
    color: var(--muted);
    font-size: 0.82rem;
  }}
  footer p {{ margin: 4px 0; }}
  .arch-img {{ width: 100%; height: auto; border-radius: 8px; border: 1px solid var(--panel-border); background: #0f1419; display: block; }}
  .arch-svg-wrap {{ width: 100%; overflow-x: auto; }}
  .arch-svg-wrap svg {{ width: 100%; height: auto; display: block; border-radius: 8px; border: 1px solid var(--panel-border); }}
  .pnl-toolbar {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 16px;
    margin: 0 0 12px;
  }}
  .pnl-legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px 18px;
    font-size: 0.85rem;
    color: var(--muted);
  }}
  .pnl-legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
  .pnl-swatch {{
    width: 12px; height: 3px; border-radius: 1px; display: inline-block;
  }}
  .pnl-swatch.hh {{ background: var(--accent); }}
  .pnl-swatch.eq {{ background: var(--pos); }}
  .pnl-swatch.cr {{ background: #e6b450; }}
  .pnl-toggle {{
    appearance: none;
    border: 1px solid var(--panel-border);
    background: #243044;
    color: var(--text);
    border-radius: 8px;
    padding: 5px 10px;
    font: inherit;
    font-size: 0.8rem;
    cursor: pointer;
  }}
  .pnl-toggle[aria-pressed="true"] {{
    border-color: var(--accent);
    color: var(--accent);
  }}
  #pnl-chart-wrap {{
    width: 100%;
    overflow-x: auto;
  }}
  #pnl-chart {{
    width: 100%;
    height: 280px;
    display: block;
  }}
  #pnl-chart .grid-line {{ stroke: #2a3548; stroke-width: 1; }}
  #pnl-chart .axis {{ stroke: #3a4a63; stroke-width: 1; }}
  #pnl-chart .axis-label {{ fill: var(--muted); font-size: 11px; font-family: var(--font); }}
  #pnl-chart .zero-line {{ stroke: #4a5a73; stroke-width: 1; stroke-dasharray: 4 3; }}
  #pnl-chart .line-hh {{ fill: none; stroke: #5b9fd4; stroke-width: 2.2; }}
  #pnl-chart .line-eq {{ fill: none; stroke: #3ecf8e; stroke-width: 1.8; }}
  #pnl-chart .line-cr {{ fill: none; stroke: #e6b450; stroke-width: 1.8; }}
  #pnl-chart .dot {{ stroke: #0f1419; stroke-width: 1; }}
  #pnl-chart .dot-hh {{ fill: #5b9fd4; }}
  #pnl-chart .dot-eq {{ fill: #3ecf8e; }}
  #pnl-chart .dot-cr {{ fill: #e6b450; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Paper Portfolio</h1>
    <div class="asof" id="mark-asof">Mark snapshot: {data['as_of_display']} (America/New_York)</div>
  </header>

  <div class="status-bar">
    <div id="live-status" class="mark">Showing last mark &hellip; loading live prices</div>
    <button type="button" id="btn-refresh">Refresh prices</button>
  </div>

  <div class="cards">
    <div class="card">
      <div class="label">Household NAV</div>
      <div class="value" id="hh-nav">{fmt_money(hh['nav'])}</div>
      <div class="sub">Equity + crypto</div>
    </div>
    <div class="card">
      <div class="label">Equity NAV</div>
      <div class="value" id="eq-nav">{fmt_money(eq['nav'])}</div>
      <div class="sub" id="eq-cash-sub">Cash {fmt_money(eq['cash'])}</div>
    </div>
    <div class="card">
      <div class="label">Crypto NAV</div>
      <div class="value" id="cr-nav">{fmt_money(cr['nav'])}</div>
      <div class="sub" id="cr-cash-sub">{cr_nav_sub}</div>
    </div>
    <div class="card">
      <div class="label">Equity P&amp;L</div>
      <div class="value {pnl_class(eq['total_pnl'])}" id="eq-pnl">{fmt_money(eq['total_pnl'])}</div>
      <div class="sub {pnl_class(eq['total_pnl_pct'])}" id="eq-pnl-pct">{fmt_pct(eq['total_pnl_pct'])} vs start</div>
    </div>
    <div class="card">
      <div class="label">Crypto P&amp;L</div>
      <div class="value {pnl_class(cr['total_pnl'])}" id="cr-pnl">{fmt_money(cr['total_pnl'])}</div>
      <div class="sub {pnl_class(cr['total_pnl_pct'])}" id="cr-pnl-pct">{fmt_pct(cr['total_pnl_pct'])} vs start</div>
    </div>
    <div class="card">
      <div class="label">Household P&amp;L</div>
      <div class="value {pnl_class(hh['total_pnl'])}" id="hh-pnl">{fmt_money(hh['total_pnl'])}</div>
      <div class="sub {pnl_class(hh['total_pnl_pct'])}" id="hh-pnl-pct">{fmt_pct(hh['total_pnl_pct'])} vs combined start</div>
    </div>
  </div>

  <section id="pnl-over-time">
    <h2>P&amp;L over time</h2>
    {sparse_note}
    <div class="pnl-toolbar">
      <div class="pnl-legend" aria-label="Series legend">
        <span><i class="pnl-swatch hh" aria-hidden="true"></i>Household</span>
        <span><i class="pnl-swatch eq" aria-hidden="true"></i>Equity</span>
        <span><i class="pnl-swatch cr" aria-hidden="true"></i>Crypto</span>
      </div>
      <div>
        <button type="button" class="pnl-toggle" id="pnl-metric-pnl" aria-pressed="true">P&amp;L $</button>
        <button type="button" class="pnl-toggle" id="pnl-metric-nav" aria-pressed="false">NAV $</button>
      </div>
    </div>
    <div id="pnl-chart-wrap">
      <svg id="pnl-chart" viewBox="0 0 1000 280" role="img" aria-label="P and L over time">{render_pnl_svg(pnl_hist)}</svg>
    </div>
  </section>

  <section>
    <h2>Equity holdings</h2>
    <p class="blurb" id="eq-prices-note">{eq_prices_note}</p>
    <table>
      <thead>
        <tr>
          <th>Ticker</th>
          <th class="num">Shares</th>
          <th class="num">Avg cost</th>
          <th class="num">Last price</th>
          <th class="num">Market value</th>
          <th class="num">Weight</th>
          <th class="num">Unrealized P&amp;L</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="eq-tbody">
        {eq_rows}
      </tbody>
    </table>
    <p class="blurb" style="margin-top:12px" id="eq-footer">
      Equity cash weight: <strong id="eq-cash-wt">{fmt_pct_plain(eq['cash_weight_pct'])}</strong>
      (<span id="eq-cash-amt">{fmt_money(eq['cash'])}</span>). Benchmark SPY last: <span id="eq-bench">{fmt_money(eq.get('bench_last_close'))}</span>.
      vs SPY: <span class="{vs_class}" id="eq-vs-spy">{vs_spy_display}</span>.
    </p>
  </section>

  <section>
    <h2>Crypto holdings</h2>
    <p class="blurb" id="cr-prices-note">{cr_prices_note}</p>
    <table>
      <thead>
        <tr>
          <th>Ticker</th>
          <th class="num">Qty</th>
          <th class="num">Avg cost</th>
          <th class="num">Last price</th>
          <th class="num">Market value</th>
          <th class="num">Weight</th>
          <th class="num">Unrealized P&amp;L</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="cr-tbody">
        {cr_rows}
      </tbody>
    </table>
    <p class="blurb" style="margin-top:12px" id="cr-footer">
      Crypto cash weight: <strong id="cr-cash-wt">{fmt_pct_plain(cr['cash_weight_pct'])}</strong>
      (<span id="cr-cash-amt">{fmt_money(cr['cash'])}</span>). Benchmark BTC-USD last: <span id="cr-bench">{fmt_money(cr.get('bench_last_close'))}</span>.
      Sleeve is separate from equity; not mixed into equity momentum rank.
    </p>
  </section>

  <section>
    <h2>Caps reminder</h2>
    <p class="blurb">Initiation caps from each sleeve config. Dashboard does not change them.</p>
    <ul class="caps">
      <li><strong>Equity:</strong> max {eq_caps['max_single_name_pct_display']} NAV per name;
          max {eq_caps['max_sector_etf_sleeve_pct_display']} per sector sleeve;
          min {eq_caps['min_cash_pct_display']} cash</li>
      <li><strong>Crypto:</strong> max {cr_caps['max_single_name_pct_display']} NAV per name;
          min {cr_caps['min_cash_pct_display']} cash (max {cr_caps['max_invested_pct_display']} invested)</li>
    </ul>
  </section>

{architecture_section()}  <section>
    <h2>Versus SPY (equity sleeve)</h2>
    <p class="blurb">{vs_spy_detail}</p>
  </section>

  <footer>
    <p>Simulated paper books only. This is not a real brokerage or exchange account.</p>
    <p>Crypto quotes in-browser via CoinGecko when available. Equity may stay on last mark if live quotes are blocked. Weekday rebuilds refresh the embedded snapshot.</p>
  </footer>
</div>
<script type="application/json" id="book-data">{book_json}</script>
<script type="application/json" id="pnl-history">{pnl_json}</script>
<script>
(function () {{
  "use strict";

  var CG_IDS = {{
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink"
  }};

  var REFRESH_MS = 60000;
  var bookEl = document.getElementById("book-data");
  if (!bookEl) return;
  var book = JSON.parse(bookEl.textContent);
  var statusEl = document.getElementById("live-status");
  var btn = document.getElementById("btn-refresh");
  var inflight = false;

  function money(v) {{
    if (v == null || !isFinite(v)) return "n/a";
    var sign = v < 0 ? "-" : "";
    return sign + "$" + Math.abs(v).toLocaleString(undefined, {{
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }});
  }}

  function pctSigned(v) {{
    if (v == null || !isFinite(v)) return "n/a";
    var sign = v > 0 ? "+" : "";
    return sign + v.toFixed(2) + "%";
  }}

  function pctPlain(v) {{
    if (v == null || !isFinite(v)) return "n/a";
    return v.toFixed(2) + "%";
  }}

  function pnlClass(v) {{
    if (v == null || Math.abs(v) < 1e-9) return "flat";
    return v > 0 ? "pos" : "neg";
  }}

  function setText(id, text) {{
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }}

  function setPnl(id, value) {{
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = typeof value === "string" ? value : money(value);
    el.classList.remove("pos", "neg", "flat");
    var num = typeof value === "number" ? value : null;
    if (num != null) el.classList.add(pnlClass(num));
  }}

  function formatWhen(d) {{
    try {{
      return d.toLocaleString("en-US", {{
        timeZone: "America/New_York",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
      }}) + " ET";
    }} catch (e) {{
      return d.toISOString();
    }}
  }}

  function setStatus(mode, msg) {{
    if (!statusEl) return;
    statusEl.className = mode;
    statusEl.textContent = msg;
  }}

  async function fetchCryptoPrices(tickers) {{
    var ids = [];
    var map = {{}};
    tickers.forEach(function (t) {{
      var id = CG_IDS[t];
      if (id) {{
        ids.push(id);
        map[id] = t;
      }}
    }});
    if (!ids.length) return {{ prices: {{}}, ok: true }};
    var url =
      "https://api.coingecko.com/api/v3/simple/price?ids=" +
      encodeURIComponent(ids.join(",")) +
      "&vs_currencies=usd";
    var res = await fetch(url, {{ cache: "no-store" }});
    if (!res.ok) throw new Error("CoinGecko HTTP " + res.status);
    var data = await res.json();
    var prices = {{}};
    Object.keys(data).forEach(function (id) {{
      var t = map[id];
      if (t && data[id] && typeof data[id].usd === "number") {{
        prices[t] = data[id].usd;
      }}
    }});
    var missing = tickers.filter(function (t) {{ return CG_IDS[t] && prices[t] == null; }});
    return {{ prices: prices, ok: missing.length === 0, missing: missing }};
  }}

  async function fetchEquityPrice(ticker) {{
    // Best-effort public Yahoo chart endpoint. Often blocked by CORS in browsers;
    // failures fall back to embedded mark prices.
    var url =
      "https://query1.finance.yahoo.com/v8/finance/chart/" +
      encodeURIComponent(ticker) +
      "?interval=1m&range=1d";
    var res = await fetch(url, {{
      cache: "no-store",
      mode: "cors",
      credentials: "omit"
    }});
    if (!res.ok) throw new Error("yahoo " + res.status);
    var data = await res.json();
    var meta = data && data.chart && data.chart.result && data.chart.result[0] && data.chart.result[0].meta;
    if (!meta) throw new Error("yahoo empty");
    var px = meta.regularMarketPrice;
    if (typeof px !== "number" || !isFinite(px)) throw new Error("yahoo no price");
    return px;
  }}

  async function fetchEquityPrices(tickers) {{
    var prices = {{}};
    var okCount = 0;
    if (!tickers.length) return {{ prices: prices, ok: true, any: false }};
    var results = await Promise.allSettled(
      tickers.map(function (t) {{
        return fetchEquityPrice(t).then(function (px) {{
          return {{ t: t, px: px }};
        }});
      }})
    );
    results.forEach(function (r) {{
      if (r.status === "fulfilled") {{
        prices[r.value.t] = r.value.px;
        okCount += 1;
      }}
    }});
    return {{
      prices: prices,
      ok: okCount === tickers.length,
      any: okCount > 0
    }};
  }}

  function recomputeSleeve(sleeve, livePrices, liveOk) {{
    var cash = Number(sleeve.cash) || 0;
    var starting = Number(sleeve.starting_capital) || 0;
    var holdingsValue = 0;
    var rows = [];
    (sleeve.positions || []).forEach(function (p) {{
      var shares = Number(p.shares) || 0;
      var cost = Number(p.cost_basis);
      if (!isFinite(cost)) {{
        cost = shares * (Number(p.avg_cost) || 0);
      }}
      var markPx = Number(p.last_price) || 0;
      var live = livePrices[p.ticker];
      var src = "mark";
      var px = markPx;
      if (typeof live === "number" && isFinite(live)) {{
        px = live;
        src = "live";
      }} else if (!liveOk) {{
        src = "mark";
      }}
      var mv = shares * px;
      holdingsValue += mv;
      var upnl = mv - cost;
      var upnlPct = cost ? (upnl / cost) * 100 : 0;
      rows.push({{
        ticker: p.ticker,
        shares: shares,
        avg_cost: Number(p.avg_cost) || 0,
        cost_basis: cost,
        last_price: px,
        market_value: mv,
        unrealized_pnl: upnl,
        unrealized_pnl_pct: upnlPct,
        src: src
      }});
    }});
    var nav = cash + holdingsValue;
    var totalPnl = nav - starting;
    if (Math.abs(totalPnl) < 0.005) totalPnl = 0;
    var totalPnlPct = starting ? (totalPnl / starting) * 100 : 0;
    if (Math.abs(totalPnlPct) < 1e-9) totalPnlPct = 0;
    var cashWt = nav ? (cash / nav) * 100 : 100;
    rows.forEach(function (r) {{
      r.weight_pct = nav ? (r.market_value / nav) * 100 : 0;
    }});
    return {{
      nav: nav,
      cash: cash,
      cash_weight_pct: cashWt,
      starting_capital: starting,
      total_pnl: totalPnl,
      total_pnl_pct: totalPnlPct,
      rows: rows
    }};
  }}

  function updateTable(tbodyId, rows) {{
    var tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    rows.forEach(function (r) {{
      var tr = tbody.querySelector('tr[data-ticker="' + r.ticker + '"]');
      if (!tr) return;
      var price = tr.querySelector('[data-field="price"]');
      var mv = tr.querySelector('[data-field="mv"]');
      var wt = tr.querySelector('[data-field="weight"]');
      var upnl = tr.querySelector('[data-field="upnl"]');
      var src = tr.querySelector('[data-field="src"]');
      if (price) price.textContent = money(r.last_price);
      if (mv) mv.textContent = money(r.market_value);
      if (wt) wt.textContent = pctPlain(r.weight_pct);
      if (upnl) {{
        upnl.textContent = money(r.unrealized_pnl) + " (" + pctSigned(r.unrealized_pnl_pct) + ")";
        upnl.classList.remove("pos", "neg", "flat");
        upnl.classList.add(pnlClass(r.unrealized_pnl));
      }}
      if (src) src.textContent = r.src;
    }});
  }}

  function applyDom(eq, cr, hh, meta) {{
    setText("hh-nav", money(hh.nav));
    setText("eq-nav", money(eq.nav));
    setText("cr-nav", money(cr.nav));
    setPnl("eq-pnl", eq.total_pnl);
    setPnl("cr-pnl", cr.total_pnl);
    setPnl("hh-pnl", hh.total_pnl);

    var eqPct = document.getElementById("eq-pnl-pct");
    if (eqPct) {{
      eqPct.textContent = pctSigned(eq.total_pnl_pct) + " vs start";
      eqPct.classList.remove("pos", "neg", "flat");
      eqPct.classList.add(pnlClass(eq.total_pnl_pct));
    }}
    var crPct = document.getElementById("cr-pnl-pct");
    if (crPct) {{
      crPct.textContent = pctSigned(cr.total_pnl_pct) + " vs start";
      crPct.classList.remove("pos", "neg", "flat");
      crPct.classList.add(pnlClass(cr.total_pnl_pct));
    }}
    var hhPct = document.getElementById("hh-pnl-pct");
    if (hhPct) {{
      hhPct.textContent = pctSigned(hh.total_pnl_pct) + " vs combined start";
      hhPct.classList.remove("pos", "neg", "flat");
      hhPct.classList.add(pnlClass(hh.total_pnl_pct));
    }}

    setText("eq-cash-wt", pctPlain(eq.cash_weight_pct));
    setText("eq-cash-amt", money(eq.cash));
    setText("cr-cash-wt", pctPlain(cr.cash_weight_pct));
    setText("cr-cash-amt", money(cr.cash));
    setText("eq-cash-sub", "Cash " + money(eq.cash));
    setText("cr-cash-sub", "Cash " + money(cr.cash));

    if (meta.spy != null) setText("eq-bench", money(meta.spy));
    if (meta.btc != null) setText("cr-bench", money(meta.btc));

    updateTable("eq-tbody", eq.rows);
    updateTable("cr-tbody", cr.rows);
  }}

  async function refresh() {{
    if (inflight) return;
    inflight = true;
    if (btn) btn.disabled = true;

    var eqTickers = (book.equity.positions || []).map(function (p) {{ return p.ticker; }});
    var crTickers = (book.crypto.positions || []).map(function (p) {{ return p.ticker; }});
    // Also try to refresh benchmarks
    var eqAll = eqTickers.slice();
    if (eqAll.indexOf("SPY") < 0) eqAll.push("SPY");
    var crAll = crTickers.slice();
    if (crAll.indexOf("BTC-USD") < 0) crAll.push("BTC-USD");

    var cryptoLive = {{ prices: {{}}, ok: false }};
    var equityLive = {{ prices: {{}}, ok: false, any: false }};
    var cryptoErr = null;
    var equityErr = null;

    try {{
      cryptoLive = await fetchCryptoPrices(crAll);
    }} catch (e) {{
      cryptoErr = e;
      cryptoLive = {{ prices: {{}}, ok: false }};
    }}
    try {{
      equityLive = await fetchEquityPrices(eqAll);
    }} catch (e) {{
      equityErr = e;
      equityLive = {{ prices: {{}}, ok: false, any: false }};
    }}

    var eq = recomputeSleeve(book.equity, equityLive.prices, equityLive.any);
    var cr = recomputeSleeve(book.crypto, cryptoLive.prices, cryptoLive.ok);

    var spy = equityLive.prices["SPY"];
    if (typeof spy !== "number") spy = book.equity.spy_last_close;
    var btc = cryptoLive.prices["BTC-USD"];
    if (typeof btc !== "number") btc = book.crypto.btc_last_close;

    var hhStart =
      (Number(book.equity.starting_capital) || 0) +
      (Number(book.crypto.starting_capital) || 0);
    var hhNav = eq.nav + cr.nav;
    var hhPnl = hhNav - hhStart;
    if (Math.abs(hhPnl) < 0.005) hhPnl = 0;
    var hhPnlPct = hhStart ? (hhPnl / hhStart) * 100 : 0;
    if (Math.abs(hhPnlPct) < 1e-9) hhPnlPct = 0;

    applyDom(
      eq,
      cr,
      {{ nav: hhNav, total_pnl: hhPnl, total_pnl_pct: hhPnlPct }},
      {{ spy: spy, btc: btc }}
    );

    var when = formatWhen(new Date());
    var cryptoOk = !cryptoErr && (crTickers.length === 0 || Object.keys(cryptoLive.prices).length > 0);
    var equityOk = equityLive.any;

    if (cryptoOk && equityOk) {{
      setStatus("live", "Live prices as of " + when + " (crypto + equity)");
    }} else if (cryptoOk && !equityOk) {{
      setStatus(
        "partial",
        "Live prices as of " +
          when +
          " (crypto live; equity on last mark). Equity live quotes unavailable in-browser."
      );
    }} else if (!cryptoOk && equityOk) {{
      setStatus(
        "partial",
        "Live prices as of " +
          when +
          " (equity live; crypto on last mark)."
      );
    }} else {{
      setStatus(
        "mark",
        "Showing last mark as of " +
          (book.as_of_display || book.as_of) +
          ". Live quote fetch failed; retry with Refresh prices."
      );
    }}

    var eqNote = document.getElementById("eq-prices-note");
    if (eqNote) {{
      eqNote.textContent = equityOk
        ? "Equity prices refreshed in-browser (best-effort public quote)."
        : "Equity showing embedded mark prices (live browser quotes blocked or unavailable).";
    }}
    var crNote = document.getElementById("cr-prices-note");
    if (crNote) {{
      crNote.textContent = cryptoOk
        ? "Crypto prices refreshed via CoinGecko."
        : "Crypto showing embedded mark prices (CoinGecko fetch failed).";
    }}

    inflight = false;
    if (btn) btn.disabled = false;
  }}

  if (btn) btn.addEventListener("click", function () {{ refresh(); }});
  refresh();
  setInterval(refresh, REFRESH_MS);
}})();
</script>
<script>
(function () {{
  "use strict";
  // Historical marks chart. Reads #pnl-history only; live price refresh must not touch this.
  var histEl = document.getElementById("pnl-history");
  var svg = document.getElementById("pnl-chart");
  if (!histEl || !svg) return;

  var hist;
  try {{
    hist = JSON.parse(histEl.textContent);
  }} catch (e) {{
    return;
  }}

  var metric = (hist && hist.default_metric) || "pnl";
  var btnPnl = document.getElementById("pnl-metric-pnl");
  var btnNav = document.getElementById("pnl-metric-nav");

  function parseTs(ts) {{
    var d = new Date(ts);
    return isNaN(d.getTime()) ? null : d;
  }}

  function fmtAxisMoney(v) {{
    var abs = Math.abs(v);
    var sign = v < 0 ? "-" : "";
    if (abs >= 1000000) return sign + "$" + (abs / 1000000).toFixed(1) + "M";
    if (abs >= 1000) return sign + "$" + (abs / 1000).toFixed(abs >= 10000 ? 0 : 1) + "k";
    return sign + "$" + abs.toFixed(0);
  }}

  function fmtEt(d) {{
    try {{
      return d.toLocaleString("en-US", {{
        timeZone: "America/New_York",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
      }});
    }} catch (e) {{
      return d.toISOString();
    }}
  }}

  function seriesPoints(name) {{
    var raw = (hist.series && hist.series[name]) || [];
    var out = [];
    raw.forEach(function (p) {{
      var d = parseTs(p.ts);
      if (!d) return;
      var y = metric === "nav" ? Number(p.nav) : Number(p.pnl);
      if (!isFinite(y)) return;
      out.push({{ t: d.getTime(), d: d, y: y, ts: p.ts }});
    }});
    out.sort(function (a, b) {{ return a.t - b.t; }});
    return out;
  }}

  function niceTicks(minV, maxV, count) {{
    if (!isFinite(minV) || !isFinite(maxV)) return [0];
    if (minV === maxV) {{
      var pad = Math.max(1, Math.abs(minV) * 0.05);
      minV -= pad;
      maxV += pad;
    }}
    var span = maxV - minV;
    var step = span / Math.max(1, count);
    var mag = Math.pow(10, Math.floor(Math.log(Math.abs(step) || 1) / Math.LN10));
    var norm = step / mag;
    var nice;
    if (norm < 1.5) nice = 1;
    else if (norm < 3) nice = 2;
    else if (norm < 7) nice = 5;
    else nice = 10;
    step = nice * mag;
    var start = Math.floor(minV / step) * step;
    var ticks = [];
    for (var v = start; v <= maxV + step * 0.5; v += step) {{
      ticks.push(v);
      if (ticks.length > 12) break;
    }}
    return ticks;
  }}

  function render() {{
    var hh = seriesPoints("household");
    var eq = seriesPoints("equity");
    var cr = seriesPoints("crypto");
    var all = hh.concat(eq).concat(cr);

    var W = 1000, H = 280;
    var pad = {{ l: 64, r: 16, t: 16, b: 40 }};
    var iw = W - pad.l - pad.r;
    var ih = H - pad.t - pad.b;

    if (!all.length) {{
      svg.innerHTML =
        '<text x="500" y="140" text-anchor="middle" class="axis-label">No history yet. History will fill in as daily marks run.</text>';
      return;
    }}

    var tMin = all[0].t, tMax = all[0].t;
    var yMin = all[0].y, yMax = all[0].y;
    all.forEach(function (p) {{
      if (p.t < tMin) tMin = p.t;
      if (p.t > tMax) tMax = p.t;
      if (p.y < yMin) yMin = p.y;
      if (p.y > yMax) yMax = p.y;
    }});
    if (tMax === tMin) tMax = tMin + 1;
    if (metric === "pnl") {{
      yMin = Math.min(yMin, 0);
      yMax = Math.max(yMax, 0);
    }}
    var yPad = (yMax - yMin) * 0.08 || 1;
    yMin -= yPad;
    yMax += yPad;

    function xScale(t) {{
      return pad.l + ((t - tMin) / (tMax - tMin)) * iw;
    }}
    function yScale(y) {{
      return pad.t + ((yMax - y) / (yMax - yMin)) * ih;
    }}

    function pathFor(pts) {{
      if (!pts.length) return "";
      return pts
        .map(function (p, i) {{
          return (i === 0 ? "M" : "L") + xScale(p.t).toFixed(2) + " " + yScale(p.y).toFixed(2);
        }})
        .join(" ");
    }}

    var yTicks = niceTicks(yMin, yMax, 5);
    var parts = [];

    yTicks.forEach(function (v) {{
      var y = yScale(v);
      parts.push(
        '<line class="grid-line" x1="' +
          pad.l +
          '" y1="' +
          y.toFixed(2) +
          '" x2="' +
          (W - pad.r) +
          '" y2="' +
          y.toFixed(2) +
          '" />'
      );
      parts.push(
        '<text class="axis-label" x="' +
          (pad.l - 8) +
          '" y="' +
          (y + 4).toFixed(2) +
          '" text-anchor="end">' +
          fmtAxisMoney(v) +
          "</text>"
      );
    }});

    if (metric === "pnl" && yMin < 0 && yMax > 0) {{
      var zy = yScale(0);
      parts.push(
        '<line class="zero-line" x1="' +
          pad.l +
          '" y1="' +
          zy.toFixed(2) +
          '" x2="' +
          (W - pad.r) +
          '" y2="' +
          zy.toFixed(2) +
          '" />'
      );
    }}

    parts.push(
      '<line class="axis" x1="' +
        pad.l +
        '" y1="' +
        pad.t +
        '" x2="' +
        pad.l +
        '" y2="' +
        (H - pad.b) +
        '" />'
    );
    parts.push(
      '<line class="axis" x1="' +
        pad.l +
        '" y1="' +
        (H - pad.b) +
        '" x2="' +
        (W - pad.r) +
        '" y2="' +
        (H - pad.b) +
        '" />'
    );

    // X labels: first, mid, last
    var xLabels = [];
    if (hh.length) xLabels = hh;
    else if (eq.length) xLabels = eq;
    else xLabels = cr;
    var labelIdx = [0];
    if (xLabels.length > 1) labelIdx.push(Math.floor((xLabels.length - 1) / 2));
    if (xLabels.length > 1) labelIdx.push(xLabels.length - 1);
    var seen = {{}};
    labelIdx.forEach(function (i) {{
      if (seen[i]) return;
      seen[i] = true;
      var p = xLabels[i];
      parts.push(
        '<text class="axis-label" x="' +
          xScale(p.t).toFixed(2) +
          '" y="' +
          (H - 12) +
          '" text-anchor="middle">' +
          fmtEt(p.d) +
          " ET</text>"
      );
    }});

    function drawSeries(pts, lineCls, dotCls) {{
      if (!pts.length) return;
      parts.push('<path class="' + lineCls + '" d="' + pathFor(pts) + '" />');
      pts.forEach(function (p) {{
        parts.push(
          '<circle class="dot ' +
            dotCls +
            '" cx="' +
            xScale(p.t).toFixed(2) +
            '" cy="' +
            yScale(p.y).toFixed(2) +
            '" r="3"><title>' +
            fmtEt(p.d) +
            " ET: " +
            fmtAxisMoney(p.y) +
            "</title></circle>"
        );
      }});
    }}

    drawSeries(eq, "line-eq", "dot-eq");
    drawSeries(cr, "line-cr", "dot-cr");
    drawSeries(hh, "line-hh", "dot-hh");

    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.innerHTML = parts.join("");
  }}

  function setMetric(m) {{
    metric = m;
    if (btnPnl) btnPnl.setAttribute("aria-pressed", m === "pnl" ? "true" : "false");
    if (btnNav) btnNav.setAttribute("aria-pressed", m === "nav" ? "true" : "false");
    render();
  }}

  if (btnPnl) btnPnl.addEventListener("click", function () {{ setMetric("pnl"); }});
  if (btnNav) btnNav.addEventListener("click", function () {{ setMetric("nav"); }});
  render();
}})();
</script>
</body>
</html>
"""



def caps_from_rules(rules: dict, *, has_sector: bool = True) -> dict:
    caps = rules.get("position_caps", {})
    out = {
        "max_single_name_pct": caps.get("max_single_name_pct", 0.15),
        "max_invested_pct": caps.get("max_invested_pct", 0.80),
        "min_cash_pct": caps.get("min_cash_pct", 0.20),
        "max_single_name_pct_display": f"{caps.get('max_single_name_pct', 0.15) * 100:.0f}%",
        "max_invested_pct_display": f"{caps.get('max_invested_pct', 0.80) * 100:.0f}%",
        "min_cash_pct_display": f"{caps.get('min_cash_pct', 0.20) * 100:.0f}%",
    }
    if has_sector:
        out["max_sector_etf_sleeve_pct"] = caps.get("max_sector_etf_sleeve_pct", 0.40)
        out["max_sector_etf_sleeve_pct_display"] = (
            f"{caps.get('max_sector_etf_sleeve_pct', 0.40) * 100:.0f}%"
        )
    return out


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ)
    as_of = now.isoformat(timespec="seconds")
    today = now.date()

    eq_pf = load_json(EQUITY_PORTFOLIO)
    eq_rules = load_json(EQUITY_RULES)
    eq_uni = load_json(EQUITY_UNIVERSE)
    eq_bench = eq_uni.get("benchmark", "SPY")

    equity = mark_sleeve(
        eq_pf,
        EQUITY_PORTFOLIO,
        EQUITY_LEDGER,
        eq_bench,
        "spy_last_close",
        100000.0,
        as_of,
        price_decimals=4,
    )
    equity["caps"] = caps_from_rules(eq_rules, has_sector=True)
    eq_start = portfolio_start_date(eq_pf, EQUITY_LEDGER)
    equity["vs_benchmark"] = bench_return_since(
        eq_bench, eq_start, today, equity["bench_last_close"]
    )
    if equity["vs_benchmark"].get("same_day"):
        equity["vs_benchmark"]["return_pct"] = 0.0
    equity["start_date"] = eq_start.isoformat() if eq_start else None

    crypto_present = CRYPTO_PORTFOLIO.exists()
    if crypto_present:
        cr_pf = load_json(CRYPTO_PORTFOLIO)
        cr_rules = load_json(CRYPTO_RULES)
        cr_uni = load_json(CRYPTO_UNIVERSE)
        cr_bench = cr_uni.get("benchmark", "BTC-USD")
        crypto = mark_sleeve(
            cr_pf,
            CRYPTO_PORTFOLIO,
            CRYPTO_LEDGER,
            cr_bench,
            "btc_last_close",
            25000.0,
            as_of,
            price_decimals=6,
        )
        crypto["caps"] = caps_from_rules(cr_rules, has_sector=False)
        cr_start = portfolio_start_date(cr_pf, CRYPTO_LEDGER)
        crypto["vs_benchmark"] = bench_return_since(
            cr_bench, cr_start, today, crypto["bench_last_close"]
        )
        if crypto["vs_benchmark"].get("same_day"):
            crypto["vs_benchmark"]["return_pct"] = 0.0
        crypto["start_date"] = cr_start.isoformat() if cr_start else None
        crypto["status"] = (
            "booked" if crypto.get("holdings") else "cash_only"
        )
    else:
        crypto = {
            "nav": 0.0,
            "cash": 0.0,
            "invested": 0.0,
            "invested_pct": 0.0,
            "cash_weight_pct": 100.0,
            "starting_capital": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "holdings": [],
            "prices_refreshed": False,
            "failed_tickers": [],
            "bench_last_close": None,
            "caps": caps_from_rules(
                {"position_caps": {"max_single_name_pct": 0.25, "max_invested_pct": 0.80, "min_cash_pct": 0.20}},
                has_sector=False,
            ),
            "vs_benchmark": {"return_pct": 0.0, "note": "Crypto sleeve not present."},
            "status": "missing",
        }

    hh_nav = round(equity["nav"] + crypto["nav"], 2)
    hh_start = round(equity["starting_capital"] + crypto["starting_capital"], 2)
    hh_pnl = round(hh_nav - hh_start, 2)
    if abs(hh_pnl) < 0.005:
        hh_pnl = 0.0
    hh_pnl_pct = (hh_pnl / hh_start * 100.0) if hh_start else 0.0
    if abs(hh_pnl_pct) < 1e-9:
        hh_pnl_pct = 0.0

    pnl_history = build_pnl_history(
        EQUITY_LEDGER,
        CRYPTO_LEDGER,
        EQUITY_PORTFOLIO,
        CRYPTO_PORTFOLIO,
        equity_start=float(equity.get("starting_capital", 100000.0)),
        crypto_start=float(crypto.get("starting_capital", 25000.0)),
    )

    data = {
        "as_of": as_of,
        "as_of_display": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "currency": "USD",
        "household": {
            "nav": hh_nav,
            "starting_capital": hh_start,
            "total_pnl": round(hh_pnl, 2),
            "total_pnl_pct": round(hh_pnl_pct, 4),
        },
        "equity": equity,
        "crypto": crypto,
        "pnl_history": pnl_history,
    }

    # Backward-compatible top-level keys (equity-centric) for any old consumers
    data["nav"] = equity["nav"]
    data["cash"] = equity["cash"]
    data["total_pnl"] = equity["total_pnl"]
    data["holdings"] = equity["holdings"]

    save_json(DATA_OUT, data)
    save_json(PNL_HISTORY_OUT, pnl_history)
    HTML_OUT.write_text(build_html(data), encoding="utf-8")

    print(
        f"equity nav={equity['nav']:.2f} pnl={equity['total_pnl']:.2f} "
        f"failed={equity['failed_tickers']}"
    )
    print(
        f"crypto nav={crypto['nav']:.2f} pnl={crypto['total_pnl']:.2f} "
        f"failed={crypto.get('failed_tickers', [])}"
    )
    print(f"household nav={hh_nav:.2f} pnl={hh_pnl:.2f}")
    counts = pnl_history.get("counts") or {}
    print(
        f"pnl_history points household={counts.get('household')} "
        f"equity={counts.get('equity')} crypto={counts.get('crypto')}"
    )
    print(str(HTML_OUT.resolve()))
    print(str(PNL_HISTORY_OUT.resolve()))


if __name__ == "__main__":
    main()

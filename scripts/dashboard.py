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
TZ = ZoneInfo("America/New_York")
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


def holdings_table_rows(holdings: list[dict], empty_msg: str) -> str:
    rows = []
    for h in holdings:
        upnl = h["unrealized_pnl"]
        qty = h["shares"]
        qty_s = f"{qty:g}" if qty == int(qty) else f"{qty:.6f}".rstrip("0").rstrip(".")
        rows.append(
            "<tr>"
            f"<td class=\"ticker\">{h['ticker']}</td>"
            f"<td class=\"num\">{qty_s}</td>"
            f"<td class=\"num\">{fmt_money(h['avg_cost'])}</td>"
            f"<td class=\"num\">{fmt_money(h['last_price'])}</td>"
            f"<td class=\"num\">{fmt_money(h['market_value'])}</td>"
            f"<td class=\"num\">{fmt_pct_plain(h['weight_pct'])}</td>"
            f"<td class=\"num {pnl_class(upnl)}\">{fmt_money(upnl)} "
            f"({fmt_pct(h['unrealized_pnl_pct'])})</td>"
            f"<td class=\"muted\">{'stale' if h.get('stale') else ''}</td>"
            "</tr>"
        )
    if not rows:
        rows.append(f'<tr><td colspan="8" class="muted">{empty_msg}</td></tr>')
    return "".join(rows)


def architecture_section() -> str:
    """Embed architecture diagram (PNG preferred, SVG fallback)."""
    png_path = REPORTS / "architecture.png"
    svg_path = REPORTS / "architecture.svg"
    blurb = (
        "How Paper runs the simulated book: chat approval, locked rules, local ledger, "
        "weekly mark, yfinance prices, reports, then GitHub Pages. Crypto is a separate "
        "sleeve under sleeves/crypto/, scaffolded and cash-only until Jordan approves. "
        "It is never mixed into the equity momentum rank."
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


def build_html(data: dict) -> str:
    eq = data["equity"]
    cr = data["crypto"]
    hh = data["household"]

    eq_rows = holdings_table_rows(
        eq["holdings"], "No open equity positions. Equity book cash only."
    )
    cr_rows = holdings_table_rows(
        cr["holdings"],
        "No open crypto positions. Crypto sleeve is scaffolded, cash-only until approved.",
    )

    eq_prices_note = (
        "Last equity prices refreshed via yfinance for this run."
        if eq["prices_refreshed"]
        else "Equity price refresh incomplete; showing last booked prices where needed."
    )
    if eq["failed_tickers"]:
        eq_prices_note += f" Failed: {', '.join(eq['failed_tickers'])}."

    cr_prices_note = (
        "Crypto sleeve is cash-only; BTC-USD benchmark priced for reference."
        if not cr["holdings"]
        else (
            "Last crypto prices refreshed via yfinance for this run."
            if cr["prices_refreshed"]
            else "Crypto price refresh incomplete; showing last booked prices where needed."
        )
    )
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
  header {{ margin-bottom: 28px; }}
  h1 {{
    margin: 0 0 6px;
    font-size: 1.75rem;
    font-weight: 650;
    letter-spacing: -0.02em;
  }}
  .asof {{ color: var(--muted); font-size: 0.95rem; }}
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
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Paper Portfolio</h1>
    <div class="asof">As of {data['as_of_display']} (America/New_York)</div>
  </header>

  <div class="cards">
    <div class="card">
      <div class="label">Household NAV</div>
      <div class="value">{fmt_money(hh['nav'])}</div>
      <div class="sub">Equity + crypto</div>
    </div>
    <div class="card">
      <div class="label">Equity NAV</div>
      <div class="value">{fmt_money(eq['nav'])}</div>
      <div class="sub">Cash {fmt_money(eq['cash'])}</div>
    </div>
    <div class="card">
      <div class="label">Crypto NAV</div>
      <div class="value">{fmt_money(cr['nav'])}</div>
      <div class="sub">Cash-only until approved</div>
    </div>
    <div class="card">
      <div class="label">Equity P&amp;L</div>
      <div class="value {pnl_class(eq['total_pnl'])}">{fmt_money(eq['total_pnl'])}</div>
      <div class="sub {pnl_class(eq['total_pnl_pct'])}">{fmt_pct(eq['total_pnl_pct'])} vs start</div>
    </div>
    <div class="card">
      <div class="label">Crypto P&amp;L</div>
      <div class="value {pnl_class(cr['total_pnl'])}">{fmt_money(cr['total_pnl'])}</div>
      <div class="sub {pnl_class(cr['total_pnl_pct'])}">{fmt_pct(cr['total_pnl_pct'])} vs start</div>
    </div>
    <div class="card">
      <div class="label">Household P&amp;L</div>
      <div class="value {pnl_class(hh['total_pnl'])}">{fmt_money(hh['total_pnl'])}</div>
      <div class="sub {pnl_class(hh['total_pnl_pct'])}">{fmt_pct(hh['total_pnl_pct'])} vs combined start</div>
    </div>
  </div>

  <section>
    <h2>Equity holdings</h2>
    <p class="blurb">{eq_prices_note}</p>
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
      <tbody>
        {eq_rows}
      </tbody>
    </table>
    <p class="blurb" style="margin-top:12px">
      Equity cash weight: <strong>{fmt_pct_plain(eq['cash_weight_pct'])}</strong>
      ({fmt_money(eq['cash'])}). Benchmark SPY last: {fmt_money(eq.get('bench_last_close'))}.
      vs SPY: <span class="{vs_class}">{vs_spy_display}</span>.
    </p>
  </section>

  <section>
    <h2>Crypto holdings</h2>
    <p class="blurb">{cr_prices_note}</p>
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
      <tbody>
        {cr_rows}
      </tbody>
    </table>
    <p class="blurb" style="margin-top:12px">
      Crypto cash weight: <strong>{fmt_pct_plain(cr['cash_weight_pct'])}</strong>
      ({fmt_money(cr['cash'])}). Benchmark BTC-USD last: {fmt_money(cr.get('bench_last_close'))}.
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
    <p>Monday 9am ET weekly mark: equity scripts + crypto scripts + combined dashboard.</p>
  </footer>
</div>
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
        crypto["status"] = "scaffolded_cash_only"
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
    }

    # Backward-compatible top-level keys (equity-centric) for any old consumers
    data["nav"] = equity["nav"]
    data["cash"] = equity["cash"]
    data["total_pnl"] = equity["total_pnl"]
    data["holdings"] = equity["holdings"]

    save_json(DATA_OUT, data)
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
    print(str(HTML_OUT.resolve()))


if __name__ == "__main__":
    main()

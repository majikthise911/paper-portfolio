#!/usr/bin/env python3
"""Build a self-contained HTML dashboard for the paper portfolio."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "state" / "portfolio.json"
LEDGER = ROOT / "state" / "ledger.jsonl"
RULES = ROOT / "config" / "rules.json"
UNIVERSE = ROOT / "config" / "universe.json"
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


def portfolio_start_date(pf: dict) -> date | None:
    """Best-effort start date for since-start return comparisons."""
    dates: list[date] = []
    if LEDGER.exists():
        try:
            for line in LEDGER.read_text().splitlines():
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


def spy_return_since(start: date | None, today: date, spy_last: float | None) -> dict:
    """Portfolio vs SPY note inputs. Same calendar day => 0% SPY return."""
    out = {
        "spy_return_pct": 0.0,
        "same_day": True,
        "spy_start_close": None,
        "spy_end_close": spy_last,
        "note": (
            "Versus SPY compares portfolio total return since start to SPY total "
            "return over the same window. Start date is today, so both returns "
            "are treated as 0.0% for this same-day view."
        ),
    }
    if start is None or start >= today:
        return out

    out["same_day"] = False
    try:
        hist = yf.Ticker("SPY").history(
            start=start.isoformat(),
            end=(today.fromordinal(today.toordinal() + 1)).isoformat(),
            auto_adjust=True,
        )
        if hist is None or hist.empty or len(hist) < 1:
            out["note"] = (
                "Versus SPY could not be computed because SPY history was "
                "unavailable for the start window."
            )
            out["spy_return_pct"] = None
            return out
        start_px = float(hist["Close"].iloc[0])
        end_px = float(hist["Close"].iloc[-1]) if spy_last is None else float(spy_last)
        out["spy_start_close"] = round(start_px, 4)
        out["spy_end_close"] = round(end_px, 4)
        ret = ((end_px / start_px) - 1.0) * 100.0 if start_px else 0.0
        out["spy_return_pct"] = round(ret, 4)
        out["note"] = (
            "Versus SPY is portfolio total return since start minus SPY total "
            "return since the portfolio start date (rough, price-only)."
        )
    except Exception as e:
        print(f"WARN: SPY history failed: {e}", file=sys.stderr)
        out["spy_return_pct"] = None
        out["note"] = (
            "Versus SPY could not be computed because SPY history fetch failed."
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



def architecture_section() -> str:
    """Embed architecture diagram (PNG preferred, SVG fallback)."""
    png_path = REPORTS / "architecture.png"
    svg_path = REPORTS / "architecture.svg"
    blurb = (
        "How Paper runs the simulated book: chat approval, locked rules, local ledger, "
        "weekly mark, yfinance prices, reports, then GitHub Pages. Crypto is shown as an "
        "optional separate sleeve, not mixed into the equity book yet."
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
    caps = data["caps"]
    holdings_rows = []
    for h in data["holdings"]:
        upnl = h["unrealized_pnl"]
        holdings_rows.append(
            "<tr>"
            f"<td class=\"ticker\">{h['ticker']}</td>"
            f"<td class=\"num\">{h['shares']:g}</td>"
            f"<td class=\"num\">{fmt_money(h['avg_cost'])}</td>"
            f"<td class=\"num\">{fmt_money(h['last_price'])}</td>"
            f"<td class=\"num\">{fmt_money(h['market_value'])}</td>"
            f"<td class=\"num\">{fmt_pct_plain(h['weight_pct'])}</td>"
            f"<td class=\"num {pnl_class(upnl)}\">{fmt_money(upnl)} "
            f"({fmt_pct(h['unrealized_pnl_pct'])})</td>"
            f"<td class=\"muted\">{'stale' if h.get('stale') else ''}</td>"
            "</tr>"
        )
    if not holdings_rows:
        holdings_rows.append(
            '<tr><td colspan="8" class="muted">No open positions. Book is all cash.</td></tr>'
        )

    total_pnl = data["total_pnl"]
    total_pnl_pct = data["total_pnl_pct"]
    vs_spy = data["vs_spy"]
    port_ret = data["total_pnl_pct"]
    spy_ret = vs_spy.get("spy_return_pct")
    if spy_ret is None:
        vs_spy_display = "n/a"
        vs_spy_detail = vs_spy["note"]
        vs_class = "flat"
    else:
        alpha = port_ret - spy_ret
        vs_spy_display = f"{alpha:+.2f} pp"
        vs_spy_detail = (
            f"Portfolio {fmt_pct(port_ret)} since start vs SPY {fmt_pct(spy_ret)}. "
            f"{vs_spy['note']}"
        )
        vs_class = pnl_class(alpha)

    prices_note = (
        "Last prices refreshed via yfinance for this run."
        if data["prices_refreshed"]
        else "Price refresh did not succeed for all names; showing last booked prices where needed."
    )
    if data["failed_tickers"]:
        prices_note += f" Failed: {', '.join(data['failed_tickers'])}."

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
      <div class="label">NAV</div>
      <div class="value">{fmt_money(data['nav'])}</div>
      <div class="sub">Net asset value</div>
    </div>
    <div class="card">
      <div class="label">Cash</div>
      <div class="value">{fmt_money(data['cash'])}</div>
      <div class="sub">{fmt_pct_plain(data['cash_weight_pct'])} of NAV</div>
    </div>
    <div class="card">
      <div class="label">Invested</div>
      <div class="value">{fmt_money(data['invested'])}</div>
      <div class="sub">{fmt_pct_plain(data['invested_pct'])} of NAV</div>
    </div>
    <div class="card">
      <div class="label">Total P&amp;L</div>
      <div class="value {pnl_class(total_pnl)}">{fmt_money(total_pnl)}</div>
      <div class="sub {pnl_class(total_pnl_pct)}">{fmt_pct(total_pnl_pct)} vs starting capital</div>
    </div>
    <div class="card">
      <div class="label">Drawdown</div>
      <div class="value {pnl_class(data['drawdown_pct'] if data['drawdown_pct'] else 0)}">{fmt_pct_plain(data['drawdown_pct'])}</div>
      <div class="sub">Versus peak NAV {fmt_money(data['peak_nav'])}</div>
    </div>
    <div class="card">
      <div class="label">vs SPY</div>
      <div class="value {vs_class}">{vs_spy_display}</div>
      <div class="sub">Portfolio return minus SPY return since start</div>
    </div>
  </div>

  <section>
    <h2>Holdings</h2>
    <p class="blurb">{prices_note}</p>
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
        {''.join(holdings_rows)}
      </tbody>
    </table>
    <p class="blurb" style="margin-top:12px">
      Cash weight: <strong>{fmt_pct_plain(data['cash_weight_pct'])}</strong>
      ({fmt_money(data['cash'])}).
      Unrealized P&amp;L is market value minus cost basis for open lots.
    </p>
  </section>

  <section>
    <h2>Caps reminder</h2>
    <p class="blurb">These initiation caps come from config/rules.json and are not changed by this dashboard.</p>
    <ul class="caps">
      <li>Max {caps['max_single_name_pct_display']} NAV per single name</li>
      <li>Max {caps['max_sector_etf_sleeve_pct_display']} in any single sector or theme ETF sleeve</li>
      <li>Min {caps['min_cash_pct_display']} cash (max {caps['max_invested_pct_display']} invested)</li>
    </ul>
  </section>

{architecture_section()}  <section>
    <h2>Versus SPY</h2>
    <p class="blurb">{vs_spy_detail}</p>
  </section>

  <footer>
    <p>Simulated paper book only. This is not a real brokerage account.</p>
    <p>Monday 9am ET weekly mark.</p>
  </footer>
</div>
</body>
</html>
"""


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    pf = load_json(PORTFOLIO)
    rules = load_json(RULES)
    uni = load_json(UNIVERSE)
    benchmark = uni.get("benchmark", "SPY")
    now = datetime.now(TZ)
    as_of = now.isoformat(timespec="seconds")
    today = now.date()

    prev_nav = float(pf.get("nav", 0))
    cash = float(pf.get("cash", 0))
    starting = float(pf.get("starting_capital", 100000.0))
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
            pos["last_price"] = round(px, 4)

        mv = shares * px
        holdings_value += mv
        pos["market_value"] = round(mv, 2)

        cost_basis = float(pos.get("cost_basis") or (shares * float(pos.get("avg_cost") or 0)))
        avg_cost = float(pos.get("avg_cost") or (cost_basis / shares if shares else 0))
        upnl = mv - cost_basis
        upnl_pct = (upnl / cost_basis * 100.0) if cost_basis else 0.0

        holdings.append(
            {
                "ticker": ticker,
                "shares": shares,
                "avg_cost": round(avg_cost, 4),
                "cost_basis": round(cost_basis, 2),
                "last_price": round(px, 4),
                "market_value": round(mv, 2),
                "unrealized_pnl": round(upnl, 2),
                "unrealized_pnl_pct": round(upnl_pct, 4),
                "sector": pos.get("sector"),
                "stale": stale,
            }
        )

    spy_px = last_close(benchmark)
    if spy_px is None:
        failed.append(benchmark)
        spy_px = pf.get("spy_last_close")
        if spy_px is not None:
            spy_px = float(spy_px)

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

    start_d = portfolio_start_date(pf)
    vs_spy = spy_return_since(start_d, today, spy_px)
    if vs_spy.get("spy_return_pct") is not None and not vs_spy.get("same_day"):
        # already computed
        pass
    elif vs_spy.get("same_day"):
        vs_spy["spy_return_pct"] = 0.0

    prices_refreshed = prices_attempted > 0 and prices_ok == prices_attempted and benchmark not in failed
    # Allow partial success to still update what we got
    any_price_update = prices_ok > 0 or (spy_px is not None and benchmark not in failed)

    caps = rules.get("position_caps", {})
    data = {
        "as_of": as_of,
        "as_of_display": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "currency": pf.get("currency", "USD"),
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
        "spy_last_close": round(spy_px, 4) if spy_px is not None else None,
        "vs_spy": vs_spy,
        "start_date": start_d.isoformat() if start_d else None,
        "holdings": holdings,
        "caps": {
            "max_single_name_pct": caps.get("max_single_name_pct", 0.15),
            "max_sector_etf_sleeve_pct": caps.get("max_sector_etf_sleeve_pct", 0.40),
            "max_invested_pct": caps.get("max_invested_pct", 0.80),
            "min_cash_pct": caps.get("min_cash_pct", 0.20),
            "max_single_name_pct_display": f"{caps.get('max_single_name_pct', 0.15) * 100:.0f}%",
            "max_sector_etf_sleeve_pct_display": f"{caps.get('max_sector_etf_sleeve_pct', 0.40) * 100:.0f}%",
            "max_invested_pct_display": f"{caps.get('max_invested_pct', 0.80) * 100:.0f}%",
            "min_cash_pct_display": f"{caps.get('min_cash_pct', 0.20) * 100:.0f}%",
        },
        "prices_refreshed": bool(prices_refreshed),
        "prices_ok": prices_ok,
        "prices_attempted": prices_attempted,
        "failed_tickers": failed,
        "notes": pf.get("notes"),
    }

    # Light mark: update portfolio if we got any fresh prices
    if any_price_update:
        pf["as_of"] = as_of
        pf["cash"] = round(cash, 2)
        pf["positions"] = positions
        pf["nav"] = round(nav, 2)
        pf["peak_nav"] = round(peak, 2)
        if spy_px is not None:
            pf["spy_last_close"] = round(spy_px, 4)
        pf["total_pnl"] = round(total_pnl, 2)
        pf["total_pnl_pct"] = round(total_pnl_pct, 4)
        pf["drawdown_pct"] = round(drawdown_pct, 4)
        save_json(PORTFOLIO, pf)

        if abs(nav - prev_nav) >= NAV_MATERIAL_USD:
            ledger_entry = {
                "ts": as_of,
                "type": "mark",
                "cash": round(cash, 2),
                "nav": round(nav, 2),
                "holdings_value": round(holdings_value, 2),
                "spy_last_close": pf.get("spy_last_close"),
                "failed_tickers": failed,
                "source": "dashboard",
            }
            with open(LEDGER, "a") as f:
                f.write(json.dumps(ledger_entry) + "\n")
            print(f"ledger mark appended (NAV {prev_nav:.2f} -> {nav:.2f})")
        else:
            print(f"NAV unchanged materially ({nav:.2f}); no ledger mark")
    else:
        print("No prices refreshed; portfolio.json left unchanged", file=sys.stderr)

    save_json(DATA_OUT, data)
    HTML_OUT.write_text(build_html(data), encoding="utf-8")

    print(f"prices_refreshed={data['prices_refreshed']} ok={prices_ok}/{prices_attempted} failed={failed}")
    print(f"nav={nav:.2f} cash={cash:.2f} invested={invested:.2f} total_pnl={total_pnl:.2f} ({total_pnl_pct:.4f}%)")
    print(str(HTML_OUT.resolve()))


if __name__ == "__main__":
    main()

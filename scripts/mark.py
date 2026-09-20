#!/usr/bin/env python3
"""Mark-to-market paper portfolio vs SPY. Does not trade."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "state" / "portfolio.json"
LEDGER = ROOT / "state" / "ledger.jsonl"
UNIVERSE = ROOT / "config" / "universe.json"
REPORTS = ROOT / "reports"
TZ = ZoneInfo("America/New_York")


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
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"WARN: failed to price {ticker}: {e}", file=sys.stderr)
        return None


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    pf = load_json(PORTFOLIO)
    uni = load_json(UNIVERSE)
    benchmark = uni.get("benchmark", "SPY")
    now = datetime.now(TZ)
    as_of = now.isoformat(timespec="seconds")

    failed = []
    positions = pf.get("positions") or {}
    holdings_value = 0.0
    marked = {}

    for ticker, pos in positions.items():
        shares = float(pos.get("shares", 0))
        if shares == 0:
            continue
        px = last_close(ticker)
        if px is None:
            failed.append(ticker)
            # keep last known if present
            px = float(pos.get("last_price") or 0)
            marked[ticker] = {
                "shares": shares,
                "last_price": px,
                "market_value": shares * px,
                "stale": True,
            }
        else:
            mv = shares * px
            holdings_value += mv
            marked[ticker] = {
                "shares": shares,
                "last_price": round(px, 4),
                "market_value": round(mv, 2),
                "stale": False,
            }
            pos["last_price"] = round(px, 4)
            pos["market_value"] = round(mv, 2)

    cash = float(pf.get("cash", 0))
    nav = cash + holdings_value
    starting = float(pf.get("starting_capital", 100000.0))
    total_pnl = nav - starting
    total_pnl_pct = (total_pnl / starting) * 100.0 if starting else 0.0

    spy_px = last_close(benchmark)
    if spy_px is None:
        failed.append(benchmark)

    peak = float(pf.get("peak_nav", starting))
    peak = max(peak, nav)
    drawdown_pct = ((nav / peak) - 1.0) * 100.0 if peak else 0.0

    pf["as_of"] = as_of
    pf["cash"] = round(cash, 2)
    pf["positions"] = positions
    pf["nav"] = round(nav, 2)
    pf["peak_nav"] = round(peak, 2)
    pf["spy_last_close"] = round(spy_px, 4) if spy_px is not None else None
    pf["total_pnl"] = round(total_pnl, 2)
    pf["total_pnl_pct"] = round(total_pnl_pct, 4)
    pf["drawdown_pct"] = round(drawdown_pct, 4)
    save_json(PORTFOLIO, pf)

    day = now.strftime("%Y-%m-%d")
    ledger_entry = {
        "ts": as_of,
        "type": "mark",
        "cash": round(cash, 2),
        "nav": round(nav, 2),
        "holdings_value": round(holdings_value, 2),
        "spy_last_close": pf["spy_last_close"],
        "failed_tickers": failed,
    }
    with open(LEDGER, "a") as f:
        f.write(json.dumps(ledger_entry) + "\n")

    invest_pct = (holdings_value / nav * 100.0) if nav else 0.0
    report_path = REPORTS / f"mark_{day}.md"
    lines = [
        f"# Mark report {day}",
        "",
        f"As of: {as_of} (America/New_York).",
        "",
        "## Book",
        "",
        f"- Cash: ${cash:,.2f}",
        f"- Holdings market value: ${holdings_value:,.2f}",
        f"- NAV (net asset value): ${nav:,.2f}",
        f"- Invested: {invest_pct:.1f}% of NAV",
        f"- Total P&L versus starting capital ${starting:,.2f}: ${total_pnl:,.2f} ({total_pnl_pct:.2f}%)",
        f"- Drawdown from peak NAV: {drawdown_pct:.2f}%",
        "",
        "## Versus SPY",
        "",
    ]
    if spy_px is not None:
        lines.append(
            f"SPY last close: ${spy_px:,.2f}. With 0% invested, portfolio return is cash (0%). "
            "Versus SPY is informational only until holdings are approved and funded."
        )
    else:
        lines.append("SPY last close could not be fetched this run.")
    lines.extend(["", "## Positions", ""])
    if not marked:
        lines.append("No positions. Book is all cash.")
    else:
        lines.append("| Ticker | Shares | Last price | Market value | Stale |")
        lines.append("|--------|--------|------------|--------------|-------|")
        for t, m in sorted(marked.items()):
            lines.append(
                f"| {t} | {m['shares']} | ${m['last_price']:,.4f} | ${m['market_value']:,.2f} | {m['stale']} |"
            )
    if failed:
        lines.extend(["", "## Failed to price", "", ", ".join(failed)])
    lines.append("")
    report_path.write_text("\n".join(lines))

    print(f"as_of={as_of}")
    print(f"cash={cash:.2f} holdings={holdings_value:.2f} nav={nav:.2f}")
    print(f"spy_last_close={pf['spy_last_close']}")
    print(f"failed={failed}")
    print(f"wrote {report_path}")
    print(f"updated {PORTFOLIO}")


if __name__ == "__main__":
    main()

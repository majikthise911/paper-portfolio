#!/usr/bin/env python3
"""Propose crypto sleeve allocation from screen. Does NOT write positions."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
SLEEVE = ROOT / "sleeves" / "crypto"
PORTFOLIO = SLEEVE / "state" / "portfolio.json"
RULES = SLEEVE / "config" / "rules.json"
UNIVERSE = SLEEVE / "config" / "universe.json"
SCREEN = SLEEVE / "reports" / "screen_latest.json"
REPORTS = SLEEVE / "reports"
TZ = ZoneInfo("America/New_York")


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def last_close(ticker: str):
    try:
        hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"WARN: price fail {ticker}: {e}", file=sys.stderr)
        return None


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    if not SCREEN.exists():
        print("Run scripts/crypto_screen.py first.", file=sys.stderr)
        sys.exit(1)

    pf = load_json(PORTFOLIO)
    rules = load_json(RULES)
    uni = load_json(UNIVERSE)
    screen = load_json(SCREEN)

    nav = float(pf.get("nav") or pf.get("cash") or 25000.0)
    cash = float(pf.get("cash", nav))
    caps = rules["position_caps"]
    max_name = float(caps["max_single_name_pct"])
    max_invested = float(caps["max_invested_pct"])
    min_cash = float(caps["min_cash_pct"])

    rankings = [r for r in screen["rankings"] if r.get("secondary_ok", True)]
    if not rankings:
        rankings = screen["rankings"]

    # With 80% invested and 25% max name => at least ceil(0.80/0.25)=4 names
    min_names = max(3, int((max_invested / max_name) + 0.999))
    candidates = rankings[:8]

    selected = []
    for r in candidates:
        if len(selected) >= min_names and len(selected) >= 4:
            break
        t = r["ticker"]
        sector = r.get("sector") or uni.get("sector_map", {}).get(t, "unknown")
        score = max(float(r["ret_63d"]), 0.0) + 0.01
        selected.append(
            {
                "ticker": t,
                "sector": sector,
                "ret_63d": float(r["ret_63d"]),
                "raw_score": score,
            }
        )

    if not selected:
        # If all returns negative, still take top by rank with floor scores
        for r in rankings[:min_names]:
            t = r["ticker"]
            sector = r.get("sector") or uni.get("sector_map", {}).get(t, "unknown")
            selected.append(
                {
                    "ticker": t,
                    "sector": sector,
                    "ret_63d": float(r["ret_63d"]),
                    "raw_score": 0.01,
                }
            )

    if not selected:
        print("No candidates to allocate.")
        sys.exit(1)

    total_score = sum(s["raw_score"] for s in selected)
    for s in selected:
        s["weight_invested"] = s["raw_score"] / total_score

    weights = {s["ticker"]: s["weight_invested"] * max_invested for s in selected}
    sectors = {s["ticker"]: s["sector"] for s in selected}
    rets = {s["ticker"]: s["ret_63d"] for s in selected}

    for _ in range(20):
        overflow = 0.0
        for t in list(weights):
            if weights[t] > max_name:
                overflow += weights[t] - max_name
                weights[t] = max_name
        if overflow <= 1e-9:
            break
        room = {t: max(0.0, max_name - w) for t, w in weights.items()}
        room_total = sum(room.values())
        if room_total <= 1e-12:
            break
        for t in weights:
            weights[t] += overflow * (room[t] / room_total)

    invested_w = sum(weights.values())
    if invested_w > max_invested:
        scale = max_invested / invested_w
        weights = {t: w * scale for t, w in weights.items()}
        invested_w = sum(weights.values())

    cash_w = 1.0 - invested_w
    if cash_w < min_cash - 1e-9:
        scale = (1.0 - min_cash) / invested_w if invested_w else 0
        weights = {t: w * scale for t, w in weights.items()}
        invested_w = sum(weights.values())
        cash_w = 1.0 - invested_w

    # Fractional qty for crypto (BTC etc.); round to 6 decimals
    trades = []
    failed_price = []
    dollars_used = 0.0
    for t, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        if w <= 0:
            continue
        px = last_close(t)
        if px is None or px <= 0:
            failed_price.append(t)
            continue
        target_dollars = nav * w
        qty = round(target_dollars / px, 6)
        if qty <= 0:
            continue
        est = qty * px
        actual_w = est / nav
        dollars_used += est
        trades.append(
            {
                "ticker": t,
                "side": "BUY",
                "shares": qty,
                "est_price": round(px, 6),
                "est_dollars": round(est, 2),
                "weight": round(actual_w, 6),
                "target_weight": round(w, 6),
                "sector": sectors[t],
                "ret_63d": rets[t],
            }
        )

    actual_invested = dollars_used
    proposed_cash = nav - actual_invested

    now = datetime.now(TZ)
    day = now.strftime("%Y-%m-%d")
    proposal = {
        "as_of": now.isoformat(timespec="seconds"),
        "sleeve": "crypto",
        "mode": "propose",
        "executed": False,
        "nav": nav,
        "proposed_trades": trades,
        "proposed_cash": round(proposed_cash, 2),
        "proposed_invested": round(actual_invested, 2),
        "proposed_cash_pct": round(proposed_cash / nav, 6) if nav else None,
        "failed_to_price": failed_price,
        "notes": (
            "Proposal only. Do not write into sleeves/crypto/state/portfolio.json "
            "positions until Jordan approves seed capital and this allocation."
        ),
    }

    prop_path = REPORTS / f"proposal_{day}.json"
    with open(prop_path, "w") as f:
        json.dump(proposal, f, indent=2)
        f.write("\n")

    pending_path = REPORTS / "proposal_pending.md"
    lines = [
        f"# Crypto proposal pending {day}",
        "",
        "This is a proposal only. Nothing has been bought. Crypto holdings stay empty until Jordan approves.",
        "",
        f"As of: {proposal['as_of']} (America/New_York).",
        f"Current crypto book: all cash ${cash:,.2f}. Sleeve NAV (net asset value) ${nav:,.2f}.",
        "",
        "## Method",
        "",
        "Signal: momentum / relative strength, meaning recent total return ranked versus the rest of the crypto universe. "
        "Primary window is about 63 trading days (roughly 3 months). "
        "Names with a deeply negative 12-month return are deprioritized when data allows.",
        "",
        "Weights are strength-weighted among top screened names, then clipped to caps: "
        "max 25% per name, max 80% invested (at least 20% cash). Fractional quantities allowed.",
        "",
        "Benchmark for this sleeve is BTC-USD (not SPY). Equity momentum rank is untouched.",
        "",
        "## Top momentum names (screen)",
        "",
        "| Rank | Ticker | 63d return | 252d return | Secondary OK |",
        "|------|--------|------------|-------------|--------------|",
    ]
    for r in screen["rankings"][:10]:
        r252 = r.get("ret_252d")
        r252s = "n/a" if r252 is None else f"{100 * r252:+.2f}%"
        lines.append(
            f"| {r['rank']} | {r['ticker']} | {100 * r['ret_63d']:+.2f}% | "
            f"{r252s} | {r.get('secondary_ok', True)} |"
        )
    lines.extend(
        [
            "",
            "## Proposed buys (not booked)",
            "",
            "| Ticker | Qty | Est. price | Est. dollars | Weight | 63d return | Category |",
            "|--------|-----|------------|--------------|--------|------------|----------|",
        ]
    )
    for tr in trades:
        lines.append(
            f"| {tr['ticker']} | {tr['shares']} | ${tr['est_price']:,.4f} | "
            f"${tr['est_dollars']:,.2f} | {100 * tr['weight']:.2f}% | "
            f"{100 * tr['ret_63d']:+.2f}% | {tr['sector']} |"
        )
    lines.extend(
        [
            "",
            "## Cash and invested after proposal (if approved)",
            "",
            f"- Proposed invested: ${actual_invested:,.2f} ({100 * actual_invested / nav:.2f}% of NAV)",
            f"- Proposed cash remaining: ${proposed_cash:,.2f} ({100 * proposed_cash / nav:.2f}% of NAV)",
            "",
        ]
    )
    if failed_price:
        lines.extend(["## Failed to price (skipped)", "", ", ".join(failed_price), ""])
    lines.extend(
        [
            "## Approval ask for Jordan",
            "",
            "1. Confirm $25,000 virtual seed capital for the crypto sleeve.",
            "2. Confirm spot universe: BTC-USD, ETH-USD, SOL-USD, AVAX-USD, LINK-USD (ETF proxies off).",
            "3. Reply yes (and any edits) to authorize writing these buys into "
            "`sleeves/crypto/state/portfolio.json`. Until then the crypto book remains $25,000 cash with no positions.",
            "",
        ]
    )
    pending_path.write_text("\n".join(lines))

    # Also keep a dated init-style note
    md_path = REPORTS / f"init_{day}.md"
    md_path.write_text("\n".join(lines))

    print(f"proposed_trades={len(trades)}")
    for tr in trades:
        print(
            f"  BUY {tr['shares']} {tr['ticker']} @ ~{tr['est_price']:.4f} "
            f"= ${tr['est_dollars']:.2f} ({100 * tr['weight']:.2f}%)"
        )
    print(f"proposed_invested=${actual_invested:.2f} proposed_cash=${proposed_cash:.2f}")
    print(f"failed_to_price={failed_price}")
    print(f"wrote {prop_path}")
    print(f"wrote {pending_path}")
    print("DID NOT update crypto portfolio positions (awaiting Jordan approval).")


if __name__ == "__main__":
    main()

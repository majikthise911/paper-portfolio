#!/usr/bin/env python3
"""Propose initial allocation from screen. Does NOT write positions."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "state" / "portfolio.json"
RULES = ROOT / "config" / "rules.json"
UNIVERSE = ROOT / "config" / "universe.json"
SCREEN = ROOT / "reports" / "screen_latest.json"
REPORTS = ROOT / "reports"
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
        print("Run scripts/screen.py first.", file=sys.stderr)
        sys.exit(1)

    pf = load_json(PORTFOLIO)
    rules = load_json(RULES)
    uni = load_json(UNIVERSE)
    screen = load_json(SCREEN)

    nav = float(pf.get("nav") or pf.get("cash") or 100000.0)
    cash = float(pf.get("cash", nav))
    caps = rules["position_caps"]
    max_name = float(caps["max_single_name_pct"])
    max_sector = float(caps["max_sector_etf_sleeve_pct"])
    max_invested = float(caps["max_invested_pct"])
    min_cash = float(caps["min_cash_pct"])

    target_invest = nav * max_invested
    # Prefer names that pass secondary filter; take top until we fill under caps
    rankings = [r for r in screen["rankings"] if r.get("secondary_ok", True)]
    if not rankings:
        rankings = screen["rankings"]

    # Strength-weighted among selected names, but start by taking top N that fit
    # Cap selection size so equal-ish weights stay under 15%
    # With 80% invested and 15% max name => at least ceil(0.80/0.15)=6 names
    min_names = max(6, int((max_invested / max_name) + 0.999))
    candidates = rankings[:12]  # look at top 12, pick until caps bind

    selected = []
    sector_w = {}
    failed_price = []

    for r in candidates:
        if len(selected) >= min_names and sum(s["raw_score"] for s in selected) > 0:
            # stop once we have enough names if adding more would dilute under util
            if len(selected) >= 8:
                break
        t = r["ticker"]
        # Keep SPY eligible but do not force cash into SPY
        sector = r.get("sector") or uni.get("sector_map", {}).get(t, "unknown")
        score = max(float(r["ret_63d"]), 0.0) + 0.01  # slight floor for equalish
        # provisional equal weight budget check later; first collect
        selected.append(
            {
                "ticker": t,
                "sector": sector,
                "ret_63d": float(r["ret_63d"]),
                "raw_score": score,
            }
        )

    if not selected:
        print("No candidates to allocate.")
        sys.exit(1)

    # Strength weights, then clip to caps and renormalize within invested sleeve
    total_score = sum(s["raw_score"] for s in selected)
    for s in selected:
        s["weight_invested"] = s["raw_score"] / total_score

    # Iterate to enforce name and sector caps on portfolio weights (of NAV)
    weights = {s["ticker"]: s["weight_invested"] * max_invested for s in selected}
    sectors = {s["ticker"]: s["sector"] for s in selected}
    rets = {s["ticker"]: s["ret_63d"] for s in selected}

    for _ in range(20):
        # clip names
        overflow = 0.0
        active = [t for t, w in weights.items() if w > 0]
        for t in list(weights):
            if weights[t] > max_name:
                overflow += weights[t] - max_name
                weights[t] = max_name
        # clip sectors
        sector_sum = {}
        for t, w in weights.items():
            sector_sum[sectors[t]] = sector_sum.get(sectors[t], 0.0) + w
        for sec, sw in sector_sum.items():
            if sw > max_sector:
                scale = max_sector / sw
                for t in weights:
                    if sectors[t] == sec:
                        new_w = weights[t] * scale
                        overflow += weights[t] - new_w
                        weights[t] = new_w
        if overflow <= 1e-9:
            break
        # redistribute overflow to names under name cap and sector room
        room = {}
        for t, w in weights.items():
            name_room = max_name - w
            sec = sectors[t]
            cur_sec = sum(weights[x] for x in weights if sectors[x] == sec)
            sec_room = max_sector - cur_sec
            room[t] = max(0.0, min(name_room, sec_room))
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
        # shrink all to free cash
        scale = (1.0 - min_cash) / invested_w if invested_w else 0
        weights = {t: w * scale for t, w in weights.items()}
        invested_w = sum(weights.values())
        cash_w = 1.0 - invested_w

    # Price and share counts (whole shares)
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
        shares = int(target_dollars // px)
        if shares <= 0:
            continue
        est = shares * px
        actual_w = est / nav
        dollars_used += est
        trades.append(
            {
                "ticker": t,
                "side": "BUY",
                "shares": shares,
                "est_price": round(px, 4),
                "est_dollars": round(est, 2),
                "weight": round(actual_w, 6),
                "target_weight": round(w, 6),
                "sector": sectors[t],
                "ret_63d": rets[t],
            }
        )

    actual_invested = dollars_used
    actual_cash = cash - actual_invested  # proposal assumes funding from current cash
    # If portfolio already all cash, cash after = nav - invested
    proposed_cash = nav - actual_invested

    now = datetime.now(TZ)
    day = now.strftime("%Y-%m-%d")
    proposal = {
        "as_of": now.isoformat(timespec="seconds"),
        "mode": "propose",
        "executed": False,
        "nav": nav,
        "proposed_trades": trades,
        "proposed_cash": round(proposed_cash, 2),
        "proposed_invested": round(actual_invested, 2),
        "proposed_cash_pct": round(proposed_cash / nav, 6) if nav else None,
        "failed_to_price": failed_price,
        "notes": "Proposal only. Do not write into portfolio.json positions until Jordan approves.",
    }

    prop_path = REPORTS / f"proposal_{day}.json"
    with open(prop_path, "w") as f:
        json.dump(proposal, f, indent=2)
        f.write("\n")

    md_path = REPORTS / f"init_{day}.md"
    lines = [
        f"# Proposed initial allocation {day}",
        "",
        "This is a proposal only. Nothing has been bought. Holdings stay empty until Jordan approves.",
        "",
        f"As of: {proposal['as_of']} (America/New_York).",
        f"Current book: all cash ${cash:,.2f}. NAV (net asset value) ${nav:,.2f}.",
        "",
        "## Method",
        "",
        "Signal: momentum / relative strength, meaning recent total return ranked versus the rest of the universe. "
        "Primary window is about 63 trading days (roughly 3 months). "
        "Names with a deeply negative 12-month return are deprioritized when data allows.",
        "",
        "Weights are strength-weighted among top screened names, then clipped to caps: "
        "max 15% per name, max 40% per sector sleeve, max 80% invested (at least 20% cash).",
        "",
        "## Proposed buys",
        "",
        "| Ticker | Shares | Est. price | Est. dollars | Weight | 63d return | Sector |",
        "|--------|--------|------------|--------------|--------|------------|--------|",
    ]
    for tr in trades:
        lines.append(
            f"| {tr['ticker']} | {tr['shares']} | ${tr['est_price']:,.2f} | "
            f"${tr['est_dollars']:,.2f} | {100*tr['weight']:.2f}% | "
            f"{100*tr['ret_63d']:+.2f}% | {tr['sector']} |"
        )
    lines.extend(
        [
            "",
            "## Cash and invested after proposal (if approved)",
            "",
            f"- Proposed invested: ${actual_invested:,.2f} ({100*actual_invested/nav:.2f}% of NAV)",
            f"- Proposed cash remaining: ${proposed_cash:,.2f} ({100*proposed_cash/nav:.2f}% of NAV)",
            "",
        ]
    )
    if failed_price:
        lines.extend(["## Failed to price (skipped)", "", ", ".join(failed_price), ""])
    lines.extend(
        [
            "## Next step",
            "",
            "Jordan: reply yes (and any edits) to authorize writing these buys into `state/portfolio.json`. "
            "Until then the book remains $100,000 cash with no positions.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines))

    print(f"proposed_trades={len(trades)}")
    for tr in trades:
        print(
            f"  BUY {tr['shares']} {tr['ticker']} @ ~{tr['est_price']:.2f} "
            f"= ${tr['est_dollars']:.2f} ({100*tr['weight']:.2f}%)"
        )
    print(f"proposed_invested=${actual_invested:.2f} proposed_cash=${proposed_cash:.2f}")
    print(f"failed_to_price={failed_price}")
    print(f"wrote {prop_path}")
    print(f"wrote {md_path}")
    print("DID NOT update portfolio positions (awaiting Jordan approval).")


if __name__ == "__main__":
    main()

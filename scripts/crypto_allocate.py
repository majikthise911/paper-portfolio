#!/usr/bin/env python3
"""Propose the momentum crypto rebalance under rule v2. Does NOT write positions.

Rule v2 (2026-10-12, btc_core_plus_momentum_top2):
  - BTC-USD core at btc_core_pct of NAV (50%).
  - Top satellite_top_n (2) names from satellite_pool by 63d return
    (252d secondary filter applied) at satellite_weight_pct (15%) each.
  - Everything else in cash (20% floor, min_cash_pct).

Output is a delta list (sells first, then buys) sized at live prices against
the current book. Bands avoid churn: BTC is only trimmed/topped up when it is
more than core_band_pct off target, a kept satellite only when it is more than
satellite_band_pct off target. New and exiting names always trade. Buys are
scaled down if they would push cash under the floor.

Previous version (pre 2026-10-19) proposed the old strength-weighted top-5
book and ignored the BTC core. Replaced 2026-10-19.
"""
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
BTC = "BTC-USD"


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def live_price(ticker: str):
    """Latest 1m close, falling back to the last daily close."""
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="1d", interval="1m")
        if h is not None and not h.empty:
            return float(h["Close"].dropna().iloc[-1])
        h = t.history(period="5d", auto_adjust=True)
        if h is not None and not h.empty:
            return float(h["Close"].dropna().iloc[-1])
    except Exception as e:  # pragma: no cover
        print(f"WARN: price fail {ticker}: {e}", file=sys.stderr)
    return None


def plan(pf: dict, rules: dict, screen: dict, prices: dict) -> dict:
    caps = rules["position_caps"]
    core_w = float(caps.get("btc_core_pct", 0.5))
    sat_n = int(caps.get("satellite_top_n", 2))
    sat_w = float(caps.get("satellite_weight_pct", 0.15))
    min_cash = float(caps["min_cash_pct"])
    pool = list(caps.get("satellite_pool") or [])
    core_band = float(caps.get("core_band_pct", 0.01))
    sat_band = float(caps.get("satellite_band_pct", 0.02))
    min_trade = float(caps.get("min_trade_usd", 100.0))

    positions = pf.get("positions") or {}
    cash = float(pf.get("cash") or 0.0)
    shares = {t: float(p.get("shares") or 0) for t, p in positions.items()}
    hv = sum(shares[t] * prices[t] for t in shares if prices.get(t))
    nav = cash + hv

    ranked = [r for r in screen["rankings"] if r["ticker"] in pool and r.get("secondary_ok", True)]
    ranked.sort(key=lambda r: float(r["ret_63d"]), reverse=True)
    sats = [r["ticker"] for r in ranked[:sat_n]]

    targets = {BTC: core_w}
    for t in sats:
        targets[t] = sat_w
    if sum(targets.values()) > 1.0 - min_cash + 1e-9:
        raise SystemExit("targets exceed max invested; check rules")

    sells, buys, holds = [], [], []
    for t in sorted(set(shares) | set(targets)):
        px = prices.get(t)
        if not px:
            continue
        cur_usd = shares.get(t, 0.0) * px
        cur_w = cur_usd / nav if nav else 0.0
        tgt_w = targets.get(t, 0.0)
        band = core_band if t == BTC else sat_band
        if tgt_w == 0.0:
            if shares.get(t, 0) > 0:
                sells.append({"ticker": t, "side": "SELL", "shares": round(shares[t], 6), "reason": "not_in_target"})
            continue
        if shares.get(t, 0) > 0 and abs(cur_w - tgt_w) <= band:
            holds.append({"ticker": t, "weight": round(cur_w, 6), "target": tgt_w, "reason": "within_band"})
            continue
        delta_usd = tgt_w * nav - cur_usd
        if abs(delta_usd) < min_trade:
            holds.append({"ticker": t, "weight": round(cur_w, 6), "target": tgt_w, "reason": "below_min_trade"})
            continue
        qty = round(abs(delta_usd) / px, 6)
        if delta_usd < 0:
            qty = min(qty, round(shares[t], 6))
            sells.append({"ticker": t, "side": "SELL", "shares": qty, "reason": "trim_to_target"})
        else:
            buys.append({"ticker": t, "side": "BUY", "shares": qty, "reason": "new_or_topup"})

    # Cash after sells, then scale buys to keep the floor.
    cash_after = cash + sum(s["shares"] * prices[s["ticker"]] for s in sells)
    buy_usd = sum(b["shares"] * prices[b["ticker"]] for b in buys)
    room = max(0.0, cash_after - min_cash * nav)
    scaled = False
    if buy_usd > room + 1e-6 and buy_usd > 0:
        k = room / buy_usd
        for b in buys:
            b["shares"] = round(b["shares"] * k * 0.9999, 6)
        scaled = True
    trades = []
    for tr in sells + buys:
        px = prices[tr["ticker"]]
        tr["price"] = round(px, 6)
        tr["dollars"] = round(tr["shares"] * px, 2)
        trades.append(tr)
    cash_final = cash_after - sum(b["dollars"] for b in buys)
    return {
        "nav": round(nav, 2),
        "cash_before": round(cash, 2),
        "targets": targets,
        "satellites": sats,
        "satellite_ranks": {r["ticker"]: round(float(r["ret_63d"]), 6) for r in ranked},
        "trades": trades,
        "holds": holds,
        "buys_scaled_to_cash_floor": scaled,
        "cash_after": round(cash_final, 2),
        "cash_after_pct": round(cash_final / nav, 6) if nav else None,
    }


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    if not SCREEN.exists():
        print("Run scripts/crypto_screen.py first.", file=sys.stderr)
        sys.exit(1)
    pf = load_json(PORTFOLIO)
    rules = load_json(RULES)
    screen = load_json(SCREEN)
    tickers = set((pf.get("positions") or {}).keys()) | {BTC} | set(rules["position_caps"].get("satellite_pool") or [])
    prices, failed = {}, []
    for t in sorted(tickers):
        px = live_price(t)
        if px and px > 0:
            prices[t] = px
        else:
            failed.append(t)
    if BTC in failed or any(t in failed for t in (pf.get("positions") or {})):
        print(f"Price failure on held/core names {failed}; not proposing.", file=sys.stderr)
        sys.exit(2)

    p = plan(pf, rules, screen, prices)
    now = datetime.now(TZ)
    day = now.strftime("%Y-%m-%d")
    proposal = {
        "as_of": now.isoformat(timespec="seconds"),
        "sleeve": "crypto",
        "rule": f"{rules.get('strategy_name')} v{rules.get('rule_version')}",
        "mode": "propose",
        "executed": False,
        **p,
        "failed_to_price": failed,
        "notes": "Proposal only. Book under the 2026-10-05 standing order at live prices.",
    }
    prop_path = REPORTS / f"proposal_{day}.json"
    prop_path.write_text(json.dumps(proposal, indent=2) + "\n")

    lines = [
        f"# Crypto v2 proposal {day}",
        "",
        f"As of {proposal['as_of']} (America/New_York). Proposal only, nothing booked.",
        "",
        f"Rule: BTC core {100*p['targets'][BTC]:.0f}%, top {len(p['satellites'])} alts at "
        f"{100*float(rules['position_caps'].get('satellite_weight_pct', 0.15)):.0f}% each, rest cash "
        f"(floor {100*float(rules['position_caps']['min_cash_pct']):.0f}%).",
        "",
        "Satellite 63d ranks: " + ", ".join(f"{t} {100*v:+.2f}%" for t, v in p["satellite_ranks"].items()),
        f"Selected: {', '.join(p['satellites'])}",
        "",
        f"NAV ${p['nav']:,.2f}, cash before ${p['cash_before']:,.2f}.",
        "",
        "| Side | Ticker | Qty | Price | Dollars | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for t in p["trades"]:
        lines.append(f"| {t['side']} | {t['ticker']} | {t['shares']} | ${t['price']:,.4f} | ${t['dollars']:,.2f} | {t['reason']} |")
    if not p["trades"]:
        lines.append("| none | | | | | |")
    for h in p["holds"]:
        lines.append(f"- Hold {h['ticker']} at {100*h['weight']:.2f}% (target {100*h['target']:.0f}%, {h['reason']})")
    lines.append("")
    lines.append(f"Cash after ${p['cash_after']:,.2f} ({100*(p['cash_after_pct'] or 0):.2f}%)."
                 + (" Buys scaled to hold the cash floor." if p["buys_scaled_to_cash_floor"] else ""))
    (REPORTS / "proposal_pending.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"wrote {prop_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Active crypto 15m EMA trend scanner — proposals only (executed: false)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ACTIVE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ema_scan_lib import (  # noqa: E402
    allocate_longs,
    evaluate_ticker,
    load_json,
    now_et,
    write_proposal,
)


def main() -> int:
    universe = load_json(ACTIVE / "crypto/config/universe.json")
    rules = load_json(ACTIVE / "crypto/config/rules.json")
    portfolio = load_json(ACTIVE / "crypto/state/portfolio.json")

    tickers = list(universe.get("spot", []))
    sector_map = universe.get("sector_map", {})
    caps = rules["position_caps"]
    nav = float(portfolio.get("nav") or portfolio.get("cash") or 25000.0)

    ts = now_et()
    date_str = ts.strftime("%Y-%m-%d")

    results = []
    failures = []
    for t in tickers:
        r = evaluate_ticker(
            t,
            ema_fast=8,
            ema_slow=21,
            atr_period=14,
            stop_atr_mult=2.0,
            period="5d",
        )
        results.append(r)
        if not r["ok"]:
            failures.append({"ticker": t, "error": r["error"]})

    proposed = allocate_longs(
        results,
        nav=nav,
        max_positions=int(caps["max_concurrent_positions"]),
        max_name_pct=float(caps["max_single_name_pct"]),
        min_cash_pct=float(caps["min_cash_pct"]),
        sector_map=sector_map,
    )

    signals_now = [r for r in results if r.get("ok") and r.get("signal")]
    signals_now_sorted = sorted(
        signals_now,
        key=lambda x: x.get("strength") or 0.0,
        reverse=True,
    )

    invested = sum(t["est_dollars"] for t in proposed)
    cash_after = nav - invested

    payload = {
        "as_of": ts.isoformat(),
        "mode": "propose",
        "executed": False,
        "strategy": "crypto_15m_ema_trend",
        "sleeve": "active_crypto",
        "nav": nav,
        "session": "24/7",
        "params": {
            "EMA_fast": 8,
            "EMA_slow": 21,
            "ATR_period": 14,
            "stop_atr_mult": 2.0,
        },
        "caps": {
            "max_single_name_pct": caps["max_single_name_pct"],
            "min_cash_pct": caps["min_cash_pct"],
            "max_concurrent_positions": caps["max_concurrent_positions"],
        },
        "universe_scanned": tickers,
        "data_failures": failures,
        "signals_detected": [
            {
                "ticker": s["ticker"],
                "close": s["close"],
                "ema_fast": s["ema_fast"],
                "ema_slow": s["ema_slow"],
                "atr": s["atr"],
                "strength": s["strength"],
                "bullish_cross": s["bullish_cross"],
                "last_bar": s["last_bar"],
            }
            for s in signals_now_sorted
        ],
        "proposed_trades": proposed,
        "summary": {
            "n_ok": sum(1 for r in results if r["ok"]),
            "n_fail": len(failures),
            "n_signals": len(signals_now),
            "n_proposed_buys": len(proposed),
            "est_invested": round(invested, 2),
            "est_cash_after": round(cash_after, 2),
            "est_cash_pct": round(cash_after / nav, 6) if nav else None,
        },
        "governance": {
            "executed": False,
            "requires_jordan_yes_before_fills": True,
            "do_not_book_until_trade_batch_yes": True,
            "hold_reason": None,
        },
        "notes": (
            "First paper signal pass after strategy lock. "
            "Stop noted at 2×ATR. Books remain all-cash until Jordan yes on this proposal batch. "
            "Never writes into sleeves/crypto/ momentum book."
        ),
    }

    lines = [
        f"# Active crypto proposal {date_str}",
        "",
        f"- **Strategy:** crypto_15m_ema_trend (Locked)",
        f"- **As of:** {ts.isoformat()}",
        f"- **Session:** 24/7",
        f"- **NAV:** ${nav:,.2f} (all cash until fill yes)",
        f"- **executed:** false",
        f"- **Stop:** 2×ATR14",
        "",
        "## Data quality",
        "",
        f"- Scanned {len(tickers)} names; {payload['summary']['n_ok']} OK; "
        f"{payload['summary']['n_fail']} failures.",
    ]
    if failures:
        lines.append("- Failures: " + ", ".join(f"{f['ticker']} ({f['error']})" for f in failures))
    lines += [
        "",
        "## Signals (fast>slow and close>slow)",
        "",
    ]
    if not signals_now_sorted:
        lines.append("- None.")
    else:
        for s in signals_now_sorted:
            cross = " cross" if s.get("bullish_cross") else ""
            lines.append(
                f"- {s['ticker']}: close={s['close']}, EMA8={s['ema_fast']}, "
                f"EMA21={s['ema_slow']}, ATR={s['atr']}, strength={s['strength']}{cross}"
            )

    lines += ["", "## Proposed buys", ""]
    if not proposed:
        lines.append("- None (no qualifying signals or zero-share after sizing).")
    else:
        for t in proposed:
            lines.append(
                f"- BUY {t['shares']} {t['ticker']} @ ~{t['est_price']} "
                f"(~${t['est_dollars']:,.2f}, target wt {t['target_weight']:.1%}, "
                f"stop ~{t['stop_price']} = 2×ATR)"
            )
        lines += [
            "",
            f"- Est. invested: ${invested:,.2f}",
            f"- Est. cash after: ${cash_after:,.2f} ({cash_after/nav:.1%})",
        ]

    lines += [
        "",
        "## Ask for Jordan",
        "",
        "Yes/no to book these active crypto paper buys into "
        "`sleeves/active/crypto/state/portfolio.json`, or hold cash until next scan.",
        "",
    ]

    jp, mp = write_proposal(
        out_dir=ACTIVE / "crypto/reports",
        date_str=date_str,
        payload=payload,
        md_body="\n".join(lines) + "\n",
    )
    print(json.dumps({"json": str(jp), "md": str(mp), "summary": payload["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

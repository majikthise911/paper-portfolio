#!/usr/bin/env python3
"""Active 15m EMA paper day-trader: scan bars, apply locked rules, book fills.

Books into sleeves/active/{equity,crypto}/state only. Never touches momentum
books. Never places real broker orders.

Under Jordan standing order 2026-10-05, Paper auto-books paper fills when
signals fire (no per-batch yes). Caps, cash floors, and max_new_trades_per_day
still apply.

Rule v3 (2026-10-06):
  - Exits (trend break / ATR stop) are never capped and never count toward
    max_new_trades_per_day. Only BUY entries count. Equity exits still need RTH.
  - Buys under position_caps.min_order_usd (default $1,000) are skipped as
    dust; a skipped buy uses no cap slot and no position slot.

Rule v4 (2026-10-06):
  - Open positions with market value below min_order_usd are dust. Dust does
    not count toward max_concurrent_positions, and when
    position_caps.liquidate_dust_positions is true it is sold as an uncapped
    exit (reason exit_dust_below_min_order; equity only during RTH).

Usage:
  python sleeves/active/scripts/run_active.py
  python sleeves/active/scripts/run_active.py --dry-run
  python sleeves/active/scripts/run_active.py --sleeve equity
  python sleeves/active/scripts/run_active.py --sleeve crypto
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ACTIVE = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ema_scan_lib import (  # noqa: E402
    append_ledger,
    count_entries_today,
    count_fills_today,
    evaluate_ticker,
    is_rth,
    last_price,
    load_json,
    now_et,
    save_json,
    size_shares,
    write_proposal,
)

DEFAULT_MAX_NEW_TRADES = {"active_equity": 8, "active_crypto": 6}
DEFAULT_MIN_ORDER_USD = 1000.0


def _sector(universe: dict, ticker: str) -> str | None:
    return (universe.get("sector_map") or {}).get(ticker)


def _mark_positions(portfolio: dict, evals: dict[str, dict]) -> float:
    """Update last_price/market_value from evals; return holdings value."""
    hv = 0.0
    positions = portfolio.get("positions") or {}
    for t, pos in list(positions.items()):
        shares = float(pos.get("shares") or 0)
        if shares == 0:
            continue
        ev = evals.get(t) or {}
        px = None
        if ev.get("ok") and ev.get("close"):
            px = float(ev["close"])
        if px is None:
            px = last_price(t)
        if px is None:
            try:
                px = float(pos.get("last_price") or 0)
            except (TypeError, ValueError):
                px = 0.0
        pos["last_price"] = round(px, 6)
        mv = round(shares * px, 2)
        pos["market_value"] = mv
        cost = float(pos.get("cost_basis") or (shares * float(pos.get("avg_cost") or 0)))
        pos["unrealized_pnl"] = round(mv - cost, 2)
        hv += mv
    portfolio["positions"] = positions
    return hv


def _recompute_nav(portfolio: dict, holdings_value: float) -> None:
    cash = float(portfolio.get("cash") or 0)
    nav = round(cash + holdings_value, 2)
    starting = float(portfolio.get("starting_capital") or nav)
    peak = max(float(portfolio.get("peak_nav") or starting), nav)
    portfolio["cash"] = round(cash, 2)
    portfolio["nav"] = nav
    portfolio["peak_nav"] = round(peak, 2)
    portfolio["total_pnl"] = round(nav - starting, 2)
    portfolio["total_pnl_pct"] = round(
        ((nav - starting) / starting * 100.0) if starting else 0.0, 4
    )
    portfolio["drawdown_pct"] = round(((nav / peak) - 1.0) * 100.0 if peak else 0.0, 4)
    for t, pos in (portfolio.get("positions") or {}).items():
        mv = float(pos.get("market_value") or 0)
        pos["weight"] = round(mv / nav, 6) if nav else 0.0


def _exit_reasons(pos: dict, ev: dict) -> list[str]:
    """Exit on ATR stop, bearish cross, or broken trend (fast<=slow or close<=slow).

    Broken-trend covers bars we missed while the sleeve was frozen or offline.
    """
    reasons = []
    if not ev.get("ok"):
        return reasons
    if ev.get("bearish_cross"):
        reasons.append("ema_bearish_cross")
    # Trend no longer long: exit even if the exact cross bar was missed.
    if not ev.get("signal"):
        reasons.append("ema_trend_broken")
    stop = pos.get("stop_price")
    close = ev.get("close")
    if stop is not None and close is not None:
        try:
            if float(close) <= float(stop):
                reasons.append("atr_stop")
        except (TypeError, ValueError):
            pass
    # Dedupe while keeping order
    seen = set()
    out = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _fill_price(ticker: str, ev: dict | None) -> float | None:
    if ev and ev.get("ok") and ev.get("close"):
        return float(ev["close"])
    return last_price(ticker)


def run_sleeve(
    *,
    sleeve_key: str,
    book_dir: Path,
    strategy_id: str,
    tickers: list[str],
    universe: dict,
    rules: dict,
    stop_atr_mult: float,
    fractional: bool,
    require_rth_for_entries: bool,
    dry_run: bool,
) -> dict[str, Any]:
    portfolio_path = book_dir / "state" / "portfolio.json"
    ledger_path = book_dir / "state" / "ledger.jsonl"
    reports_dir = book_dir / "reports"

    portfolio = load_json(portfolio_path)
    caps = rules["position_caps"]
    max_name = float(caps["max_single_name_pct"])
    min_cash = float(caps["min_cash_pct"])
    max_pos = int(caps["max_concurrent_positions"])
    tech_tickers = list(caps.get("tech_megacap_tickers") or [])
    max_tech = caps.get("max_tech_megacap_sleeve_pct")
    max_tech = float(max_tech) if max_tech is not None else None
    max_new = int(
        caps.get("max_new_trades_per_day")
        or DEFAULT_MAX_NEW_TRADES.get(sleeve_key, 8)
    )
    min_order_raw = caps.get("min_order_usd")
    min_order_usd = float(
        DEFAULT_MIN_ORDER_USD if min_order_raw is None else min_order_raw
    )
    liquidate_dust = bool(caps.get("liquidate_dust_positions", False))

    ts = now_et()
    date_str = ts.strftime("%Y-%m-%d")
    rth = is_rth(ts)
    fills_today = count_fills_today(ledger_path, date_str)
    # Only entries count toward the daily cap (exits are uncapped risk control).
    entries_today = count_entries_today(ledger_path, date_str)
    remaining_budget = max(0, max_new - entries_today)

    # Evaluate universe
    evals: dict[str, dict] = {}
    failures = []
    for t in tickers:
        ev = evaluate_ticker(
            t,
            ema_fast=8,
            ema_slow=21,
            atr_period=14,
            stop_atr_mult=stop_atr_mult,
            period="5d",
        )
        evals[t] = ev
        if not ev.get("ok"):
            failures.append({"ticker": t, "error": ev.get("error")})

    holdings_value = _mark_positions(portfolio, evals)
    _recompute_nav(portfolio, holdings_value)
    nav = float(portfolio["nav"])
    cash = float(portfolio["cash"])
    positions = dict(portfolio.get("positions") or {})

    planned: list[dict[str, Any]] = []
    notes: list[str] = []

    def _is_dust(p: dict) -> bool:
        if min_order_usd <= 0:
            return False
        try:
            mv = float(p.get("shares") or 0) * float(p.get("last_price") or 0)
        except (TypeError, ValueError):
            return False
        return 0 < mv < min_order_usd

    # --- Exits first (never capped; do not consume remaining_budget) ---
    for ticker, pos in list(positions.items()):
        ev = evals.get(ticker) or {}
        reasons = _exit_reasons(pos, ev)
        if liquidate_dust and _is_dust(pos):
            reasons.append("exit_dust_below_min_order")
            notes.append(f"exit_dust_below_min_order:{ticker}")
        if not reasons:
            continue
        # Equity exits only during RTH (can't fill US equity off-hours in paper
        # either; crypto exits anytime).
        if require_rth_for_entries and not rth:
            notes.append(f"exit_deferred_outside_rth:{ticker}:{','.join(reasons)}")
            continue
        shares = float(pos.get("shares") or 0)
        if shares <= 0:
            continue
        px = _fill_price(ticker, ev)
        if px is None or px <= 0:
            notes.append(f"exit_skip_no_price:{ticker}")
            continue
        dollars = round(shares * px, 2)
        planned.append(
            {
                "ticker": ticker,
                "side": "SELL",
                "shares": shares,
                "price": round(px, 6),
                "dollars": dollars,
                "sector": pos.get("sector") or _sector(universe, ticker),
                "reason": "+".join(reasons),
                "signal": "ema_trend_exit",
                "stop_price": pos.get("stop_price"),
                "ema_fast": ev.get("ema_fast"),
                "ema_slow": ev.get("ema_slow"),
                "last_bar": ev.get("last_bar"),
                "cap_exempt": True,
            }
        )

    # Apply exits to a working copy for sizing entries
    work_positions = {k: dict(v) for k, v in positions.items()}
    work_cash = cash
    exited_this_run: set[str] = set()
    for tr in planned:
        if tr["side"] != "SELL":
            continue
        tk = tr["ticker"]
        pos = work_positions.get(tk)
        if not pos:
            continue
        shares = float(pos.get("shares") or 0)
        avg = float(pos.get("avg_cost") or 0)
        cost = float(pos.get("cost_basis") or shares * avg)
        proceeds = tr["dollars"]
        realized = round(proceeds - cost, 2)
        tr["realized_pnl"] = realized
        work_cash = round(work_cash + proceeds, 2)
        del work_positions[tk]
        exited_this_run.add(tk)

    work_nav = work_cash + sum(
        float(p.get("shares") or 0) * float(p.get("last_price") or 0)
        for p in work_positions.values()
    )

    # --- Entries ---
    can_enter = (not require_rth_for_entries) or rth
    if not can_enter:
        notes.append("outside_RTH_no_new_entries")
    elif remaining_budget <= 0:
        notes.append("daily_trade_cap_reached_no_entries")
    else:
        held = set(work_positions.keys())
        # Dust positions do not count toward max_concurrent_positions.
        dust_held = {k for k, p in work_positions.items() if _is_dust(p)}
        if dust_held:
            notes.append(
                "dust_not_counted_toward_max_positions:" + ",".join(sorted(dust_held))
            )
        open_slots = max(0, max_pos - len(held - dust_held))
        # Rank bullish signals not already held. Prefer fresh crosses, then state.
        # Do not re-buy a name we exited in this same scan (avoid stop-out churn).
        candidates = []
        for tk, ev in evals.items():
            if not ev.get("ok") or tk in held or tk in exited_this_run:
                continue
            if not ev.get("signal"):
                continue
            # Entry: bullish cross OR bullish state (fill open trend slots)
            cross = bool(ev.get("bullish_cross"))
            strength = float(ev.get("strength") or 0.0)
            candidates.append((1 if cross else 0, strength, tk, ev))
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)

        for cross_flag, strength, ticker, ev in candidates:
            if open_slots <= 0 or remaining_budget <= 0:
                break
            px = _fill_price(ticker, ev)
            if px is None or px <= 0:
                notes.append(f"entry_skip_no_price:{ticker}")
                continue

            # Room under cash floor and name cap
            max_invested = work_nav * (1.0 - min_cash)
            invested_now = work_nav - work_cash
            room_invest = max(0.0, max_invested - invested_now)
            name_cap_dollars = work_nav * max_name
            # Equal-ish slice among remaining open slots, but not above name cap
            target = min(name_cap_dollars, room_invest, work_cash - work_nav * min_cash + room_invest)
            # Simpler: size to min(max_name * nav, available cash above floor)
            cash_above_floor = max(0.0, work_cash - work_nav * min_cash)
            dollars_budget = min(name_cap_dollars, cash_above_floor, room_invest)
            if dollars_budget < px and not fractional:
                notes.append(f"entry_skip_too_small:{ticker}")
                continue
            if dollars_budget <= 0:
                notes.append("entry_stop_cash_floor")
                break
            if dollars_budget < min_order_usd:
                notes.append(
                    f"entry_skip_below_min_order:{ticker}:"
                    f"budget_${dollars_budget:,.2f}<min_${min_order_usd:,.0f}"
                )
                continue

            # Tech mega-cap sleeve cap
            if max_tech is not None and ticker in tech_tickers:
                tech_mv = sum(
                    float(p.get("shares") or 0) * float(p.get("last_price") or 0)
                    for tt, p in work_positions.items()
                    if tt in tech_tickers
                )
                tech_room = max(0.0, work_nav * max_tech - tech_mv)
                dollars_budget = min(dollars_budget, tech_room)
                if dollars_budget <= 0:
                    notes.append(f"entry_skip_tech_cap:{ticker}")
                    continue

            shares = size_shares(dollars_budget, px, fractional=fractional)
            if shares <= 0:
                notes.append(f"entry_skip_zero_shares:{ticker}")
                continue
            dollars = round(shares * px, 2)
            if dollars <= 0:
                continue
            if work_cash - dollars < work_nav * min_cash - 0.01:
                # Re-size to cash floor
                allowed = max(0.0, work_cash - work_nav * min_cash)
                shares = size_shares(allowed, px, fractional=fractional)
                dollars = round(shares * px, 2)
                if shares <= 0 or dollars <= 0:
                    notes.append("entry_stop_cash_floor")
                    break

            # Dust filter: skip buys under min_order_usd. No cap or slot used.
            if dollars < min_order_usd:
                notes.append(
                    f"entry_skip_below_min_order:{ticker}:"
                    f"${dollars:,.2f}<min_${min_order_usd:,.0f}"
                )
                continue

            stop_px = ev.get("stop_price")
            if stop_px is None and ev.get("atr") is not None:
                stop_px = round(px - float(ev["atr"]) * stop_atr_mult, 6)

            planned.append(
                {
                    "ticker": ticker,
                    "side": "BUY",
                    "shares": shares,
                    "price": round(px, 6),
                    "dollars": dollars,
                    "sector": _sector(universe, ticker),
                    "reason": "ema_bullish_cross" if cross_flag else "ema_trend_long",
                    "signal": "ema_trend_long",
                    "stop_price": stop_px,
                    "ema_fast": ev.get("ema_fast"),
                    "ema_slow": ev.get("ema_slow"),
                    "strength": ev.get("strength"),
                    "bullish_cross": bool(ev.get("bullish_cross")),
                    "last_bar": ev.get("last_bar"),
                }
            )
            # Update working book
            work_cash = round(work_cash - dollars, 2)
            work_positions[ticker] = {
                "shares": shares,
                "avg_cost": px,
                "cost_basis": dollars,
                "last_price": px,
                "market_value": dollars,
                "sector": _sector(universe, ticker),
                "stop_price": stop_px,
            }
            work_nav = work_cash + sum(
                float(p.get("shares") or 0) * float(p.get("last_price") or 0)
                for p in work_positions.values()
            )
            open_slots -= 1
            remaining_budget -= 1

    # Build payload / report
    payload = {
        "as_of": ts.isoformat(),
        "mode": "dry_run" if dry_run else "auto_book",
        "executed": False,
        "strategy": strategy_id,
        "sleeve": sleeve_key,
        "nav_before": nav,
        "cash_before": cash,
        "session": "US_RTH" if rth else "outside_RTH",
        "in_rth": rth,
        "fills_today_before": fills_today,
        "entries_today_before": entries_today,
        "max_new_trades_per_day": max_new,
        "cap_counts": "entries_only (exits exempt)",
        "min_order_usd": min_order_usd,
        "remaining_budget_after_plan": remaining_budget,
        "data_failures": failures,
        "signals_detected": [
            {
                "ticker": e["ticker"],
                "close": e.get("close"),
                "ema_fast": e.get("ema_fast"),
                "ema_slow": e.get("ema_slow"),
                "strength": e.get("strength"),
                "bullish_cross": e.get("bullish_cross"),
                "bearish_cross": e.get("bearish_cross"),
                "last_bar": e.get("last_bar"),
            }
            for e in sorted(
                [v for v in evals.values() if v.get("ok") and v.get("signal")],
                key=lambda x: x.get("strength") or 0.0,
                reverse=True,
            )
        ],
        "planned_trades": planned,
        "notes": notes,
        "governance": {
            "paper_only": True,
            "auto_book_under_standing_order": True,
            "standing_order": "2026-10-05 chat: Paper decides and books; Jordan may override",
            "never_place_real_trades": True,
        },
    }

    if dry_run or not planned:
        payload["executed"] = False
        payload["summary"] = {
            "n_planned": len(planned),
            "n_buys": sum(1 for t in planned if t["side"] == "BUY"),
            "n_sells": sum(1 for t in planned if t["side"] == "SELL"),
            "booked": False,
        }
        tag = "dryrun" if dry_run else "scan"
        jp, mp = write_proposal(
            out_dir=reports_dir,
            date_str=f"{date_str}_{tag}",
            payload=payload,
            md_body=_md_report(payload, booked=False),
        )
        payload["report_json"] = str(jp)
        payload["report_md"] = str(mp)
        return payload

    # --- Book fills ---
    booked_fills = []
    for tr in planned:
        ticker = tr["ticker"]
        side = tr["side"]
        shares = float(tr["shares"])
        px = float(tr["price"])
        dollars = round(shares * px, 2)
        if side == "SELL":
            pos = positions.get(ticker)
            if not pos:
                continue
            avg = float(pos.get("avg_cost") or 0)
            cost = float(pos.get("cost_basis") or shares * avg)
            cash = round(cash + dollars, 2)
            realized = round(dollars - cost, 2)
            del positions[ticker]
            booked_fills.append(
                {
                    "ticker": ticker,
                    "side": "SELL",
                    "shares": shares if fractional else int(shares),
                    "price": round(px, 6),
                    "dollars": dollars,
                    "sector": tr.get("sector"),
                    "realized_pnl": realized,
                    "reason": tr.get("reason"),
                    "fill_source": "yfinance_15m_close",
                }
            )
        else:  # BUY
            if cash < dollars:
                continue
            cash = round(cash - dollars, 2)
            stop_px = tr.get("stop_price")
            positions[ticker] = {
                "shares": shares if fractional else int(shares),
                "avg_cost": round(px, 6),
                "cost_basis": dollars,
                "last_price": round(px, 6),
                "market_value": dollars,
                "sector": tr.get("sector"),
                "opened_at": ts.isoformat(),
                "unrealized_pnl": 0.0,
                "stop_price": stop_px,
            }
            booked_fills.append(
                {
                    "ticker": ticker,
                    "side": "BUY",
                    "shares": shares if fractional else int(shares),
                    "price": round(px, 6),
                    "dollars": dollars,
                    "sector": tr.get("sector"),
                    "reason": tr.get("reason"),
                    "stop_price": stop_px,
                    "fill_source": "yfinance_15m_close",
                }
            )

    portfolio["cash"] = round(cash, 2)
    portfolio["positions"] = positions
    portfolio["as_of"] = ts.isoformat()
    portfolio["last_trade_batch"] = f"active_auto_{date_str}_{ts.strftime('%H%M%S')}"
    # Re-mark NAV
    hv = 0.0
    for t, pos in positions.items():
        shares = float(pos.get("shares") or 0)
        px = float(pos.get("last_price") or 0)
        mv = round(shares * px, 2)
        pos["market_value"] = mv
        hv += mv
    _recompute_nav(portfolio, hv)
    buy_n = sum(1 for f in booked_fills if f["side"] == "BUY")
    sell_n = sum(1 for f in booked_fills if f["side"] == "SELL")
    portfolio["notes"] = (
        f"Active auto-book {ts.isoformat()}: {buy_n} BUY / {sell_n} SELL under "
        f"standing order. Strategy {strategy_id}. Paper only."
    )
    save_json(portfolio_path, portfolio)

    batch_id = portfolio["last_trade_batch"]
    ledger_entry = {
        "ts": ts.isoformat(),
        "type": "trade_batch",
        "sleeve": sleeve_key,
        "approval": (
            "Jordan standing order 2026-10-05: Paper decides and books paper fills; "
            "Jordan may override. Active live daily EMA wired 2026-10-05."
        ),
        "source": f"run_active.py/{strategy_id}",
        "last_trade_batch": batch_id,
        "fills": booked_fills,
        "cash_after": portfolio["cash"],
        "nav_after": portfolio["nav"],
        "invested": round(hv, 2),
        "note": (
            f"Auto paper fills ({strategy_id}): "
            + "; ".join(
                f"{f['side']} {f['shares']} {f['ticker']} @ {f['price']}"
                for f in booked_fills
            )
        ),
    }
    append_ledger(ledger_path, ledger_entry)

    payload["executed"] = True
    payload["booked_fills"] = booked_fills
    payload["nav_after"] = portfolio["nav"]
    payload["cash_after"] = portfolio["cash"]
    payload["summary"] = {
        "n_planned": len(planned),
        "n_buys": buy_n,
        "n_sells": sell_n,
        "booked": True,
        "cash_after": portfolio["cash"],
        "nav_after": portfolio["nav"],
    }
    jp, mp = write_proposal(
        out_dir=reports_dir,
        date_str=f"{date_str}_booked",
        payload=payload,
        md_body=_md_report(payload, booked=True),
    )
    # Also write a booked_*.md for humans
    booked_md = reports_dir / f"booked_{date_str}.md"
    booked_md.write_text(_md_report(payload, booked=True))
    payload["report_json"] = str(jp)
    payload["report_md"] = str(mp)
    payload["booked_md"] = str(booked_md)
    return payload


def _md_report(payload: dict, *, booked: bool) -> str:
    lines = [
        f"# Active {payload['sleeve']} {'booked' if booked else 'scan'} {payload['as_of'][:10]}",
        "",
        f"- **Strategy:** {payload['strategy']}",
        f"- **As of:** {payload['as_of']}",
        f"- **Mode:** {payload['mode']}",
        f"- **executed:** {str(booked).lower()}",
        f"- **Session:** {payload.get('session')}",
        f"- **Entries today before:** {payload.get('entries_today_before')} / "
        f"cap {payload.get('max_new_trades_per_day')} "
        f"(exits exempt; all fills today: {payload.get('fills_today_before')})",
        f"- **Min order:** ${float(payload.get('min_order_usd') or 0):,.0f}",
        "",
        "## Planned / booked trades",
        "",
    ]
    trades = payload.get("booked_fills") or payload.get("planned_trades") or []
    if not trades:
        lines.append("- None.")
    else:
        for t in trades:
            lines.append(
                f"- {t['side']} {t['shares']} {t['ticker']} @ {t['price']} "
                f"(~${t['dollars']:,.2f}; {t.get('reason') or t.get('signal')})"
            )
    if payload.get("notes"):
        lines += ["", "## Notes", ""]
        for n in payload["notes"]:
            lines.append(f"- {n}")
    lines += [
        "",
        "## Governance",
        "",
        "- Paper only. No real broker orders.",
        "- Auto-book under Jordan standing order 2026-10-05 (Jordan may override).",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--sleeve",
        choices=["equity", "crypto", "both"],
        default="both",
        help="Which active sleeve to run (default both)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and plan only; do not write portfolio/ledger",
    )
    args = ap.parse_args()

    results = {}
    if args.sleeve in ("equity", "both"):
        uni = load_json(ACTIVE / "equity/config/universe.json")
        rules = load_json(ACTIVE / "equity/config/rules.json")
        tickers = list(uni.get("etfs", [])) + list(uni.get("mega_caps", []))
        results["active_equity"] = run_sleeve(
            sleeve_key="active_equity",
            book_dir=ACTIVE / "equity",
            strategy_id="equity_15m_ema_trend",
            tickers=tickers,
            universe=uni,
            rules=rules,
            stop_atr_mult=1.5,
            fractional=False,
            require_rth_for_entries=True,
            dry_run=args.dry_run,
        )
    if args.sleeve in ("crypto", "both"):
        uni = load_json(ACTIVE / "crypto/config/universe.json")
        rules = load_json(ACTIVE / "crypto/config/rules.json")
        tickers = list(uni.get("spot", []))
        results["active_crypto"] = run_sleeve(
            sleeve_key="active_crypto",
            book_dir=ACTIVE / "crypto",
            strategy_id="crypto_15m_ema_trend",
            tickers=tickers,
            universe=uni,
            rules=rules,
            stop_atr_mult=2.0,
            fractional=True,
            require_rth_for_entries=False,
            dry_run=args.dry_run,
        )

    summary = {
        k: {
            "executed": v.get("executed"),
            "summary": v.get("summary"),
            "n_planned": len(v.get("planned_trades") or []),
            "notes": v.get("notes"),
        }
        for k, v in results.items()
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

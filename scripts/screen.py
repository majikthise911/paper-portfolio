#!/usr/bin/env python3
"""Momentum / relative strength screen over universe. Prints top 10 and bottom 5."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "config" / "universe.json"
RULES = ROOT / "config" / "rules.json"
REPORTS = ROOT / "reports"
OUT_JSON = REPORTS / "screen_latest.json"


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def universe_tickers(uni: dict) -> list[str]:
    tickers = list(uni.get("etfs", [])) + list(uni.get("mega_caps", []))
    # preserve order, unique
    seen = set()
    out = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def compute_returns(hist: pd.DataFrame, days: int):
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    closes = hist["Close"].dropna()
    if len(closes) < days + 1:
        return None
    start = float(closes.iloc[-(days + 1)])
    end = float(closes.iloc[-1])
    if start <= 0:
        return None
    return (end / start) - 1.0


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    uni = load_json(UNIVERSE)
    rules = load_json(RULES)
    tickers = universe_tickers(uni)
    primary_d = int(rules["signal"]["primary_trading_days"])
    secondary_d = int(rules["signal"]["secondary_trading_days"])
    secondary_min = float(rules["signal"].get("secondary_min_return", -0.20))

    failed = []
    rows = []

    print(f"Downloading ~2y history for {len(tickers)} tickers...")
    # batch download
    try:
        data = yf.download(
            tickers,
            period="2y",
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
    except Exception as e:
        print(f"ERROR: batch download failed: {e}", file=sys.stderr)
        data = None

    for t in tickers:
        try:
            if data is None:
                raise RuntimeError("no batch data")
            if isinstance(data.columns, pd.MultiIndex):
                if t not in data.columns.get_level_values(0):
                    raise KeyError(t)
                hist = data[t].dropna(how="all")
            else:
                # single ticker edge case
                hist = data.dropna(how="all")
            r63 = compute_returns(hist, primary_d)
            r252 = compute_returns(hist, secondary_d)
            if r63 is None:
                # try individual fetch as fallback
                h2 = yf.Ticker(t).history(period="2y", auto_adjust=True)
                r63 = compute_returns(h2, primary_d)
                r252 = compute_returns(h2, secondary_d)
            if r63 is None:
                failed.append(t)
                continue
            secondary_ok = True if r252 is None else (r252 >= secondary_min)
            rows.append(
                {
                    "ticker": t,
                    "ret_63d": r63,
                    "ret_252d": r252,
                    "secondary_ok": secondary_ok,
                    "sector": uni.get("sector_map", {}).get(t, "unknown"),
                }
            )
        except Exception as e:
            print(f"WARN: skip {t}: {e}", file=sys.stderr)
            failed.append(t)

    if not rows:
        print("No screenable tickers.")
        sys.exit(1)

    df = pd.DataFrame(rows)
    df = df.sort_values("ret_63d", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    top10 = df.head(10)
    bottom5 = df.tail(5)

    print("\n=== Top 10 by 63d total return ===")
    for _, r in top10.iterrows():
        r252s = "n/a" if pd.isna(r["ret_252d"]) or r["ret_252d"] is None else f"{100*r['ret_252d']:.2f}%"
        print(
            f"{int(r['rank']):2d}. {r['ticker']:6s}  63d={100*r['ret_63d']:+.2f}%  "
            f"252d={r252s}  secondary_ok={r['secondary_ok']}  sector={r['sector']}"
        )

    print("\n=== Bottom 5 by 63d total return ===")
    for _, r in bottom5.iterrows():
        r252s = "n/a" if pd.isna(r["ret_252d"]) or r["ret_252d"] is None else f"{100*r['ret_252d']:.2f}%"
        print(
            f"{int(r['rank']):2d}. {r['ticker']:6s}  63d={100*r['ret_63d']:+.2f}%  "
            f"252d={r252s}  sector={r['sector']}"
        )

    if failed:
        print("\nFailed / skipped:", ", ".join(failed))

    out = {
        "primary_days": primary_d,
        "secondary_days": secondary_d,
        "secondary_min_return": secondary_min,
        "rankings": [
            {
                "rank": int(r["rank"]),
                "ticker": r["ticker"],
                "ret_63d": float(r["ret_63d"]),
                "ret_252d": None if r["ret_252d"] is None or (isinstance(r["ret_252d"], float) and np.isnan(r["ret_252d"])) else float(r["ret_252d"]),
                "secondary_ok": bool(r["secondary_ok"]),
                "sector": r["sector"],
            }
            for _, r in df.iterrows()
        ],
        "failed_tickers": failed,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(f"\nwrote {OUT_JSON}")


if __name__ == "__main__":
    main()

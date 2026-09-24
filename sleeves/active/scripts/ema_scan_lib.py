"""Shared helpers for active 15m EMA trend paper scanners (pure Python + yfinance)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(tz=ET)


def is_rth(ts: datetime | None = None) -> bool:
    ts = ts or now_et()
    if ts.weekday() >= 5:
        return False
    minutes = ts.hour * 60 + ts.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def fetch_15m(ticker: str, period: str = "5d") -> tuple[pd.DataFrame | None, str | None]:
    """Fetch 15m OHLCV. Returns (df, error)."""
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period, interval="15m", auto_adjust=True)
        if df is None or df.empty:
            return None, "empty_history"
        # Normalize columns
        need = {"Open", "High", "Low", "Close"}
        if not need.issubset(set(df.columns)):
            return None, f"missing_ohlc_cols:{list(df.columns)}"
        df = df.sort_index()
        if len(df) < 25:
            return None, f"too_few_bars:{len(df)}"
        return df, None
    except Exception as e:  # noqa: BLE001
        return None, f"exception:{type(e).__name__}:{e}"


def evaluate_ticker(
    ticker: str,
    *,
    ema_fast: int = 8,
    ema_slow: int = 21,
    atr_period: int = 14,
    stop_atr_mult: float = 1.5,
    period: str = "5d",
) -> dict[str, Any]:
    df, err = fetch_15m(ticker, period=period)
    if err or df is None:
        return {
            "ticker": ticker,
            "ok": False,
            "error": err or "unknown",
            "signal": False,
        }

    close = df["Close"].astype(float)
    fast = ema(close, ema_fast)
    slow = ema(close, ema_slow)
    atr_s = atr(df, atr_period)

    i = -1
    c = float(close.iloc[i])
    f = float(fast.iloc[i])
    s = float(slow.iloc[i])
    a = float(atr_s.iloc[i]) if not np.isnan(atr_s.iloc[i]) else None

    # Prior bar for cross detection
    f_prev = float(fast.iloc[i - 1])
    s_prev = float(slow.iloc[i - 1])

    bullish_state = f > s and c > s
    bullish_cross = f_prev <= s_prev and f > s and c > s
    # "trend long signal NOW" per brief: fast>slow and close>slow
    signal = bullish_state

    # Strength: distance of fast above slow in ATR units (for ranking)
    strength = None
    if a and a > 0:
        strength = (f - s) / a
    else:
        strength = (f - s) / c if c else 0.0

    bar_ts = df.index[i]
    if getattr(bar_ts, "tzinfo", None) is None:
        bar_ts_et = bar_ts.replace(tzinfo=ET) if hasattr(bar_ts, "replace") else str(bar_ts)
    else:
        bar_ts_et = bar_ts.astimezone(ET)

    return {
        "ticker": ticker,
        "ok": True,
        "error": None,
        "signal": bool(signal),
        "bullish_cross": bool(bullish_cross),
        "close": round(c, 6),
        "ema_fast": round(f, 6),
        "ema_slow": round(s, 6),
        "atr": None if a is None or np.isnan(a) else round(float(a), 6),
        "stop_distance": None
        if a is None or np.isnan(a)
        else round(float(a) * stop_atr_mult, 6),
        "stop_price": None
        if a is None or np.isnan(a)
        else round(c - float(a) * stop_atr_mult, 6),
        "strength": None if strength is None else round(float(strength), 6),
        "bars": int(len(df)),
        "last_bar": str(bar_ts_et),
    }


def allocate_longs(
    signals: list[dict[str, Any]],
    *,
    nav: float,
    max_positions: int,
    max_name_pct: float,
    min_cash_pct: float,
    tech_megacap_tickers: list[str] | None = None,
    max_tech_megacap_pct: float | None = None,
    sector_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Equal-ish target weights among top signals, respecting caps. Empty book assumed."""
    ranked = sorted(
        [s for s in signals if s.get("ok") and s.get("signal")],
        key=lambda x: (x.get("strength") is not None, x.get("strength") or 0.0),
        reverse=True,
    )[:max_positions]

    if not ranked:
        return []

    max_invested = 1.0 - min_cash_pct
    n = len(ranked)
    raw = min(max_name_pct, max_invested / n)

    weights = {s["ticker"]: raw for s in ranked}

    # Tech mega-cap sleeve scale-down if needed
    if tech_megacap_tickers and max_tech_megacap_pct is not None:
        tech = [t for t in weights if t in tech_megacap_tickers]
        tech_sum = sum(weights[t] for t in tech)
        if tech_sum > max_tech_megacap_pct and tech_sum > 0:
            scale = max_tech_megacap_pct / tech_sum
            for t in tech:
                weights[t] *= scale

    trades = []
    for s in ranked:
        t = s["ticker"]
        tw = weights[t]
        dollars = nav * tw
        px = s["close"]
        shares = int(dollars // px) if px and px > 0 else 0
        est = round(shares * px, 2) if shares else 0.0
        actual_w = est / nav if nav else 0.0
        trades.append(
            {
                "ticker": t,
                "side": "BUY",
                "shares": shares,
                "est_price": px,
                "est_dollars": est,
                "weight": round(actual_w, 6),
                "target_weight": round(tw, 6),
                "sector": (sector_map or {}).get(t),
                "signal": "ema_trend_long",
                "ema_fast": s["ema_fast"],
                "ema_slow": s["ema_slow"],
                "atr": s["atr"],
                "stop_price": s["stop_price"],
                "stop_distance": s["stop_distance"],
                "strength": s["strength"],
                "bullish_cross": s["bullish_cross"],
                "last_bar": s["last_bar"],
            }
        )
    return trades


def write_proposal(
    *,
    out_dir: Path,
    date_str: str,
    payload: dict[str, Any],
    md_body: str,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / f"proposal_{date_str}.json"
    mp = out_dir / f"proposal_{date_str}.md"
    jp.write_text(json.dumps(payload, indent=2) + "\n")
    mp.write_text(md_body)
    return jp, mp

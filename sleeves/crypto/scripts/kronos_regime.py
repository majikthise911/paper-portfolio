#!/usr/bin/env python3
"""Kronos regime filter (shadow only, never trades).

Runs open-source Kronos-small (NeoQuasar/Kronos-small + Kronos-Tokenizer-base)
on daily OHLCV for each crypto coin and draws N independent sampled paths
(default 100) for the next H days (default 10). Classifies each coin:

  trending: >= 65% of paths agree with the median path's direction AND
            |median H-day return| / IQR of H-day returns >= 0.5 (tight spread)
  choppy:   otherwise (scattered paths)

Shadow rule (crypto v2 + Kronos filter): an alt keeps its 15% slot only if its
regime is trending AND the median path is up; otherwise that slot goes to BTC.

Run with the Kronos venv:
  "/Volumes/Marvin SSD/Projects/kronos/.venv/bin/python" sleeves/crypto/scripts/kronos_regime.py
Writes a JSON row to --out (default: the Kronos folder's regime_log/, outside the
paper repo so cron runs never dirty the tree). The Monday pass copies the log.
"""
import argparse, json, sys, warnings
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
warnings.filterwarnings("ignore")
KRONOS = Path("/Volumes/Marvin SSD/Projects/kronos")
sys.path.insert(0, str(KRONOS))
import numpy as np, pandas as pd, torch, yfinance as yf
from model import Kronos, KronosTokenizer, KronosPredictor
from model.kronos import calc_time_stamps

COINS = ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD"]

def paths_for(pred, df, n, h, lookback):
    df = df.tail(lookback)
    cols = ["open", "high", "low", "close", "volume", "amount"]
    x = df[cols].values.astype(np.float32)
    mu, sd = x.mean(0), x.std(0)
    xn = np.clip((x - mu) / (sd + 1e-5), -5, 5)
    xts = pd.Series(df.index)
    yts = pd.Series(pd.date_range(df.index[-1] + pd.Timedelta(days=1), periods=h, freq="D"))
    xs = calc_time_stamps(xts).values.astype(np.float32)
    ys = calc_time_stamps(yts).values.astype(np.float32)
    X = np.repeat(xn[None], n, 0); XS = np.repeat(xs[None], n, 0); YS = np.repeat(ys[None], n, 0)
    out = pred.generate(X, XS, YS, h, 1.0, 0, 0.9, 1, False)  # (n, h, 6), sample_count=1 per row
    close = out[:, :, 3] * (sd[3] + 1e-5) + mu[3]
    return close, float(df["close"].iloc[-1])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=100)
    ap.add_argument("--horizon", type=int, default=10)
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--out", default=str(KRONOS / "regime_log"))
    a = ap.parse_args()
    torch.manual_seed(20261102)
    tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    mdl = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    pred = KronosPredictor(mdl, tok, device="cpu", max_context=512)
    ts = datetime.now(ZoneInfo("America/New_York"))
    res = {}
    for c in COINS:
        h = yf.download(c, period="2y", interval="1d", auto_adjust=True, progress=False)
        if isinstance(h.columns, pd.MultiIndex):
            h.columns = h.columns.get_level_values(0)
        df = h.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
        close, last = paths_for(pred, df, a.paths, a.horizon, a.lookback)
        r = close[:, -1] / last - 1
        med = float(np.median(r)); iqr = float(np.percentile(r, 75) - np.percentile(r, 25))
        agree = float(np.mean(np.sign(r) == np.sign(med))) if med != 0 else 0.5
        snr = abs(med) / iqr if iqr > 0 else 0.0
        regime = "trending" if (agree >= 0.65 and snr >= 0.5) else "choppy"
        res[c] = dict(last_close=round(last, 4), median_ret=round(med, 4), iqr=round(iqr, 4),
                      p10=round(float(np.percentile(r, 10)), 4), p90=round(float(np.percentile(r, 90)), 4),
                      agree=round(agree, 3), snr=round(snr, 3), regime=regime,
                      up=bool(med > 0))
        print(c, res[c], flush=True)
    row = dict(ts=ts.isoformat(), model="NeoQuasar/Kronos-small", paths=a.paths, horizon_days=a.horizon,
               lookback_days=a.lookback, coins=res)
    od = Path(a.out); od.mkdir(parents=True, exist_ok=True)
    (od / f"{ts.date().isoformat()}.json").write_text(json.dumps(row, indent=1))
    print("wrote", od / f"{ts.date().isoformat()}.json")

if __name__ == "__main__":
    main()

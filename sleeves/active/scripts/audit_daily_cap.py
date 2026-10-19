#!/usr/bin/env python3
"""Audit Active ledgers: BUY entries per ET day vs max_new_trades_per_day.

Exits (SELL) are exempt from the cap by design (rule v3, 2026-10-06), so a day
can show more total fills than the cap without breaking it. Exit code 1 if any
day has more entries than the cap.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
bad = False
for book in ("equity", "crypto"):
    rules = json.loads((ROOT / book / "config" / "rules.json").read_text())
    cap = int(rules["position_caps"].get("max_new_trades_per_day") or 0)
    led = ROOT / book / "state" / "ledger.jsonl"
    days: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for line in led.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("type") != "trade_batch":
            continue
        for f in e.get("fills") or []:
            days[str(e["ts"])[:10]][str(f.get("side") or "BUY").upper()] += 1
    print(f"{book} (cap {cap} entries/day; exits exempt)")
    for d in sorted(days):
        b, s_ = days[d]["BUY"], days[d]["SELL"]
        flag = "  OVER CAP" if cap and b > cap else ""
        bad = bad or bool(flag)
        print(f"  {d}: entries {b}, exits {s_}, total {b + s_}{flag}")
sys.exit(1 if bad else 0)

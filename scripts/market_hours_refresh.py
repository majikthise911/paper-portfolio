#!/usr/bin/env python3
"""Market-hours refresh pipeline for paper portfolio.

1. Run active sleeves. Equity rule v8 (2026-10-20): daily EMA10/30, evaluated
   only at the 3:23 PM ET run; other runs mark only. Crypto rule v7: 15m off.
2. Rebuild the combined dashboard (marks all four sleeves + publishes HTML).

Intended for weekday market-hours routines about every 15-30 minutes during
US RTH (09:30-16:00 ET). Safe to call more often; active sleeve enforces a
per-day trade cap. Crypto active trades also run here (24/7 signals), so
calling this overnight is fine for crypto but equity will only exit/enter in RTH.

Usage (Marvin or box mirror):
  cd /Volumes/Marvin\\ SSD/Projects/paper-portfolio   # or box path
  source .venv/bin/activate
  python scripts/market_hours_refresh.py

Flags:
  --skip-active     only rebuild dashboard
  --active-dry-run  scan active without booking
  --skip-dashboard  only run active
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_RUN = ROOT / "sleeves" / "active" / "scripts" / "run_active.py"
DASHBOARD = ROOT / "scripts" / "dashboard.py"


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return int(proc.returncode)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-active", action="store_true")
    ap.add_argument("--active-dry-run", action="store_true")
    ap.add_argument("--skip-dashboard", action="store_true")
    args = ap.parse_args()

    py = sys.executable
    rc = 0
    if not args.skip_active:
        cmd = [py, str(ACTIVE_RUN)]
        if args.active_dry_run:
            cmd.append("--dry-run")
        rc = _run(cmd) or rc
    if not args.skip_dashboard:
        rc = _run([py, str(DASHBOARD)]) or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

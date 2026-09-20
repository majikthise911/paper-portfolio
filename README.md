# Paper Portfolio (Jordan / agent Paper)

Simulated long-only US portfolio. No real brokerage. No live orders.

## Layout

- `config/rules.json` - strategy rules (do not change without Jordan approval)
- `config/universe.json` - liquid US ETFs + mega-caps; SPY is benchmark
- `state/portfolio.json` - cash, positions, NAV, as-of
- `state/ledger.jsonl` - append-only trade/mark log
- `reports/` - mark reports and allocation proposals
- `scripts/` - mark.py, screen.py, allocate.py

## Ops

```bash
cd /home/box/agent-data/paper-portfolio
source .venv/bin/activate
python scripts/mark.py
python scripts/screen.py
python scripts/allocate.py          # propose only; does not execute
```

## Governance

- Propose strategy tweaks only. Never change rules without Jordan approval.
- Never place real trades. Proposals stay in `reports/` until Jordan approves.
- Do not write approved proposals into `portfolio.json` positions until Jordan says so.
- 30% APY is an aspiration metric only, never an auto-rewire stop.

## Caps (initiation)

- Max 15% NAV per single name
- Max 40% in any single sector/theme ETF sleeve
- Max 80% invested (min 20% cash) unless Jordan approves a change

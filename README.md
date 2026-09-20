# Paper Portfolio (Jordan / agent Paper)

Simulated long-only US portfolio. No real brokerage. No live orders.

## Layout

- `config/rules.json` - strategy rules (do not change without Jordan approval)
- `config/universe.json` - liquid US ETFs + mega-caps; SPY is benchmark
- `state/portfolio.json` - cash, positions, NAV, as-of
- `state/ledger.jsonl` - append-only trade/mark log
- `reports/` - mark reports, allocation proposals, and dashboard
- `scripts/` - mark.py, screen.py, allocate.py, dashboard.py, crypto_*.py
- `sleeves/crypto/` - separate crypto paper sleeve (cash-only until Jordan approves)

## Ops

```bash
cd /home/box/agent-data/paper-portfolio
source .venv/bin/activate
python scripts/mark.py
python scripts/screen.py
python scripts/allocate.py          # propose only; does not execute
python scripts/crypto_mark.py
python scripts/crypto_screen.py
python scripts/crypto_allocate.py   # propose only; does not book positions
python scripts/dashboard.py         # combined equity + crypto household HTML
```

## Dashboard

Regenerate the HTML snapshot:

```bash
cd /home/box/agent-data/paper-portfolio && source .venv/bin/activate && python scripts/dashboard.py
```

Open the report in a browser (works offline via `file://`):

- Box path: `/home/box/agent-data/paper-portfolio/reports/dashboard.html`
- Marvin path: `/Volumes/Marvin SSD/Projects/paper-portfolio/reports/dashboard.html`

Also written: `reports/dashboard_data.json` (same snapshot the HTML uses).

## Governance

- Propose strategy tweaks only. Never change rules without Jordan approval.
- Never place real trades. Proposals stay in `reports/` until Jordan approves.
- Do not write approved proposals into `portfolio.json` positions until Jordan says so.
- 30% APY is an aspiration metric only, never an auto-rewire stop.

## Caps (initiation)

- Max 15% NAV per single name
- Max 40% in any single sector/theme ETF sleeve
- Max 80% invested (min 20% cash) unless Jordan approves a change

## Live dashboard (GitHub Pages)

Bookmark: https://majikthise911.github.io/paper-portfolio/

After regenerating locally, publish with:

```bash
cp reports/dashboard.html /path/to/paper-portfolio-gh/docs/index.html
# then commit and push to majikthise911/paper-portfolio main
```

Or from the box mirror after `python scripts/dashboard.py`, copy `reports/dashboard.html` to the GitHub clone's `docs/index.html` and push.

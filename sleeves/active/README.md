# Active 15m paper sleeve — how to run (when ready)

Parallel paper experiment under `sleeves/active/`. Does not touch momentum equity (repo root) or momentum crypto (`sleeves/crypto/`).

## Status (2026-09-24)

- Starter strategies locked: `equity_15m_ema_trend` / `crypto_15m_ema_trend`.
- Paper fills booked: active equity META/XLP/XLV; active crypto LINK-USD.
- Public dashboard: same Pages site as momentum shows Active (15m EMA) cards + holdings.
- Freqtrade: **not installed**. Optional later in an isolated venv under `sleeves/active/.venv` only.

## Layout

```
sleeves/active/
  PLAN.md
  README.md
  equity/config|state|reports
  crypto/config|state|reports
  strategies/
```

## Capital

| Sleeve | Starting cash | State file |
|--------|---------------|------------|
| Active equity | $100,000 | `equity/state/portfolio.json` |
| Active crypto | $25,000 | `crypto/state/portfolio.json` |

## Proposed starter strategies

| Book | Name | Spec |
|------|------|------|
| Equity | `equity_15m_ema_trend` | `strategies/equity_15m_ema_trend.md` |
| Crypto | `crypto_15m_ema_trend` | `strategies/crypto_15m_ema_trend.md` |

## When ready to run (after strategy yes)

1. Confirm Jordan approved the starter strategy names and any micro-rule tweaks.
2. Prefer an isolated venv under `sleeves/active/.venv` if installing Freqtrade or other runners. Do not pip-install into the parent paper-portfolio `.venv` without an explicit plan.
3. Fetch 15m bars (equity RTH; crypto 24/7), propose only, then book paper fills into this sleeve's `state/` only after Jordan yes on the proposal.
4. Mark and compare same-window vs momentum household (see PLAN.md).

## Do not

- Book fills into root `state/` or `sleeves/crypto/state/`.
- Mix active ranks into weekly momentum screens.
- Claim Freqtrade dry-run is live until it actually is.

## Commands (placeholders)

```bash
cd /home/box/agent-data/paper-portfolio
# Parent momentum scripts unchanged:
#   source .venv/bin/activate && python scripts/mark.py
# Active sleeve runners: TBD after strategy yes and isolated install.
```

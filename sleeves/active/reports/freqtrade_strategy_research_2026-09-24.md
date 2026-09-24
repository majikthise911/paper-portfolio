# Freqtrade strategy research — briefing for Jordan (Paper)

**Date:** Thu Sep 24, 2026 (ET)  
**Setup under review:** `$125k` paper split — `$100k` US equities + `$25k` crypto; locked starters `equity_15m_ema_trend` / `crypto_15m_ema_trend` (15m EMA 8/21, long-only).  
**Question:** Swap before first fills, or keep EMA?

---

## Verdict (first)

**Keep both EMA baselines for first paper fills. Do not swap crypto or equity starters to NFI / MultiMA / Strategy001 / Ichimoku before fills.**

Community evidence does **not** identify a stronger, honestly forward-tested alternative that fits this long-only 15m dual-sleeve paper v1. Published “winners” are mostly crypto-5m, hyperopt-shaped, or educational — with weak or missing out-of-sample / live proof. Closest honest paper data for an EMA-cross idea class is mixed and small-sample; complex Freqtrade favorites are a poor fit and often author-disclaimed for live use.

**Recommended next step:** Keep EMA on both sleeves → first fills → after ~30–60 days (or ≥30 closed trades per sleeve), optional **A–B paper** on crypto only (EMA vs SampleStrategy-style RSI/BB mean-reversion or EMA+BTC informative filter). Equity: no evidence-based swap candidate.

---

## Evidence bullets

### Official / primary (Freqtrade)

- Strategy repo README: strategies are **educational**, “not ready to use”; results depend on pairs/TF/timerange; always backtest then **dry-run**. Sample table is a **20-day** window (2018-01-10→01-30) — not serious OOS.  
  https://github.com/freqtrade/freqtrade-strategies  
  https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/main/README.md
- Docs: dry-run is the real forward test; backtests ≠ live; run **lookahead-analysis** + **recursive-analysis** before dry/live.  
  https://www.freqtrade.io/en/stable/strategy-customization/  
  https://www.freqtrade.io/en/stable/lookahead-analysis/  
  https://www.freqtrade.io/en/stable/backtesting/
- Hyperopt: no built-in train/validation split; maintainers tell users to hyperopt one timerange then **backtest a different (unseen) timerange** — classic overfit risk.  
  https://github.com/freqtrade/freqtrade/issues/8866  
  https://www.freqtrade.io/en/stable/hyperopt/
- Live vs backtest: maintainer (xmatthias) documents fill delay, pricing/timeout, slippage as structural gaps — dry often worse than backtest, not better.  
  https://github.com/freqtrade/freqtrade/issues/8518

### Popular named strategies (crypto-centric)

| Candidate | Idea (1 line) | Typical TF | Pros (reported) | Cons / honesty | Links | Conf. | Fit long-only paper v1 |
|-----------|---------------|------------|-----------------|----------------|-------|-------|-------------------------|
| **EMA 8/21 (OUR baseline)** | Fast/slow EMA cross trend follow | 15m (ours); peers use daily–15m | Simple, auditable, matches paper goal; closest honest paper narrative exists for 9/21 class | Whipsaw in chop; low WR needs R:R; small samples; regime-dependent | Closest paper: https://www.reddit.com/r/algotrading/comments/1u2g8ye/59_days_of_paper_trading_a_921_ema_crossover/ (snapshot: https://reddit.sentinel-team.org/posts/1u2g8ye/snapshots/2026-06-12T06%3A58%3A19.661124Z) | **Med** for “sane starter”; **Low** for “proven edge” | **Best fit** for both sleeves |
| **Strategy001** | EMA20/50/100 + Heikin-Ashi cross | 5m in repo examples | Official example; readable | Tiny 2018 backtest (55 trades, ~0.05% avg); educational only | https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/Strategy001.py | **Low** | Poor — different logic/TF; no OOS/live proof |
| **SampleStrategy (RSI/BB/TEMA)** | RSI cross + BB/TEMA guards (mean-rev lean) | 5m template | Official template; good A–B challenger later | Not claimed profitable; TF mismatch vs our 15m | https://www.freqtrade.io/en/stable/strategy-customization/ https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/templates/sample_strategy.py | **Low–Med** as learning baseline | Crypto A–B later only — not pre-fill swap |
| **NostalgiaForInfinity (NFI X6/X7)** | Large multi-condition crypto system, strict entries, often futures-oriented configs | **5m** | Huge community (3k+ stars); active updates; dry-run docs | Sparse trades; user issues (days with no fills; live vs backtest pain); not designed for US equities 15m; complexity/overfit risk | https://github.com/iterativv/NostalgiaForInfinity https://iterativv.github.io/NostalgiaForInfinity/ https://github.com/iterativv/NostalgiaForInfinity/issues/541 https://github.com/iterativv/NostalgiaForInfinity/issues/1069 | **Low** for *our* setup | **Do not swap** for paper v1 |
| **MultiMA_TSL / Cenderawasih** | Multi-MA + PMAX/RSI-style filters (SMAOffset lineage) | Often 5m crypto | Once popular learning strat | **Author (2025-11-22): “not to be used for live trading… learning only”** | https://github.com/stash86/MultiMA_TSL https://raw.githubusercontent.com/stash86/MultiMA_TSL/main/README.md | **Low** (author disclaimer) | **Do not swap** |
| **Informative pairs (BTC HTF filter)** | Gate entries with higher-TF / BTC RSI or trend | Main TF + 1h/1d | Docs-endorsed pattern; can reduce bad chop entries | Not a full strategy; needs own OOS; more moving parts | https://www.freqtrade.io/en/stable/strategy-customization/ (informative / @informative) | **Med** as *enhancement* later | Optional crypto A–B add-on, not replacement |
| **Ichimoku / BB-only / pure RSI MR** | Classic TA packs | Mixed | Familiar names in forums | No credible Freqtrade OOS/live leaderboard found; Ichimoku chikou lookahead footguns discussed | e.g. https://github.com/freqtrade/technical/issues/93 | **Low** | Not for pre-fill swap |

### Closest honest forward/paper signal (not Freqtrade, but same idea class)

- r/algotrading (Jun 2026 snapshot): **59 days paper**, **9/21 EMA** + ATR stops + RVOL filter: **20 trades / 14 closed**, **33.3% WR**, avg win ~$999 / avg loss ~$316, **+$1,470** closed — **carried by ARM + AMD**; author admits without those two the book is net negative. Commenters: sample too small; bull-regime bias; crossovers die in chop.  
  → Supports **keeping** a simple EMA trend starter for learning/measurement, **not** claiming it is “best.”

### Crypto spot vs US equities 15m

- **Crypto:** Freqtrade’s natural home. Almost all popular strategies (NFI, MultiMA, Strategy00x) assume **crypto, often 5m**, dynamic volume pairlists. Even there, **no reproducible “best live strategy”** — docs and maintainers stress dry-run and OOS.
- **US equities 15m:** Scarce honest Freqtrade results. Alpaca/stock forks exist, but **no comparative paper/live leaderboard** tying named Freqtrade strategies to equity 15m. Swapping equity to a crypto-born complex strat would be **speculative, not evidence-based**.

**Overfit flags to treat as red:** pretty backtests only; hyperopt on full history; 2–4 week backtest windows; “100% winrate” claims; strategies that fail lookahead/recursive checks; author “learning only” disclaimers.

---

## Observation / Logic (keep vs switch)

**Observation:** Forums and official sources repeatedly show that (1) complex hyperopted crypto strategies look great in-sample and disappoint dry/live, (2) authors of MultiMA explicitly ban live use, (3) NFI is a moving 5m crypto target with sparse signals and user fill/performance complaints, (4) Strategy001’s published numbers are a toy window, (5) the only nearby *honest paper* story for EMA-cross is small-sample and outlier-driven — still the same idea family as our lock.

**Logic:** Before first fills, the job of paper v1 is a **measurable, explainable baseline**, not max backtest profit. Swapping to NFI/MultiMA would change TF, complexity, pairlist assumptions, and invalidate the locked comparison — without evidence they beat EMA 8/21 on *our* 15m long-only equity+crypto paper. Therefore **keep EMA on both sleeves**; gather real forward fills; only then A–B crypto challengers.

---

## Explicit recommendation

| Sleeve | Action before first fills |
|--------|---------------------------|
| Crypto `$25k` | **Keep** `crypto_15m_ema_trend` (EMA 8/21) |
| Equities `$100k` | **Keep** `equity_15m_ema_trend` (EMA 8/21) |
| Later (after fills + sample) | Optional **A–B paper** crypto: EMA vs SampleStrategy-style RSI/BB **or** EMA + informative BTC/1h filter. Equity: still no swap candidate from this research. |

**Do not:** install/live-trade NFI or MultiMA as the locked starters for this paper split.

---

## Sources (cite list)

1. https://github.com/freqtrade/freqtrade-strategies  
2. https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/main/README.md  
3. https://www.freqtrade.io/en/stable/strategy-customization/  
4. https://www.freqtrade.io/en/stable/lookahead-analysis/  
5. https://www.freqtrade.io/en/stable/backtesting/  
6. https://www.freqtrade.io/en/stable/hyperopt/  
7. https://github.com/freqtrade/freqtrade/issues/8866  
8. https://github.com/freqtrade/freqtrade/issues/8518  
9. https://github.com/iterativv/NostalgiaForInfinity  
10. https://iterativv.github.io/NostalgiaForInfinity/  
11. https://github.com/iterativv/NostalgiaForInfinity/issues/541  
12. https://github.com/iterativv/NostalgiaForInfinity/issues/1069  
13. https://github.com/stash86/MultiMA_TSL  
14. https://raw.githubusercontent.com/stash86/MultiMA_TSL/main/README.md  
15. https://www.reddit.com/r/algotrading/comments/1u2g8ye/59_days_of_paper_trading_a_921_ema_crossover/  
16. https://reddit.sentinel-team.org/posts/1u2g8ye/snapshots/2026-06-12T06%3A58%3A19.661124Z  

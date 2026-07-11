# KOL Track Record Lab — Do Taiwan's Finance Influencers Actually Beat the Market?

**Live site:** https://henrylin1009.github.io/kol-track-record/

A rule-based backtesting and statistical-inference engine that evaluates **7,947 stock
calls** made by **14 Taiwanese finance influencers (KOLs)** on YouTube, and asks one
honest question of each: *once you correct for multiple testing, does any of them have
demonstrable skill?*

**Punchline:** raw backtests make several KOLs look like winners. After a
**Romano–Wolf stepwise multiple-testing correction** (family-wise error control across
all analysts × horizons), **0 of 14 survive.** Their apparent edge is a
false-discovery artifact of a bull market plus momentum-chasing.

---

## Why this project

Finance influencers broadcast thousands of "buy this" calls but are never held to a
rigorous, look-ahead-free scorecard. The hard part isn't plotting an equity curve — it's
doing the statistics *honestly*: a per-call benchmark, no survivorship or look-ahead bias,
and a multiple-comparisons correction so that testing 14 people doesn't manufacture a
"genius" by chance.

## What it does

- **Extracts** buy/sell decisions and price predictions from 4,500+ YouTube transcripts
  using LLM tool-calling (`extract_decisions.py`, `extract_predictions.py`).
- **Backtests** every call in calendar time with a single unified rule
  (`build_calendar_multi.py`): open-of-next-session entry (no look-ahead), mark-to-market
  to a frozen backtest end date, 0.6% transaction cost on the strategy leg.
- **Benchmarks per call, not per person** (`resolve_target.py`, `verdict_rules.py`):
  a stock/sector pick is judged against its market index (TAIEX / SPY); a call *on* an
  asset itself (SPY, GLD, BTC…) is judged against buy-and-hold of that same asset —
  i.e. "did you beat the index?" vs. "did you at least get the direction right?"
- **Corrects for multiple testing** (`rw_core.py`): Romano–Wolf stepdown over the full
  family of analyst × horizon hypotheses under a shared "no skill" null.
- **Serves** a fully self-contained static site (`generate_site.py`) and a
  natural-language Q&A agent over the call database (`ask_combined.py`, `server.py`).

## Key numbers

| | |
|---|---|
| Analysts evaluated | 14 |
| Stock calls backtested | 7,947 |
| YouTube transcripts indexed | ~4,500 |
| Raw "significant" analysts | several |
| **Survive Romano–Wolf correction** | **0** |

## Statistical method

- **No look-ahead:** entry is the first tradable session *after* a call; the entire price
  history is truncated to a frozen `BACKTEST_END` so no run can peek at future prices.
- **Per-call benchmark routing:** the benchmark is chosen from the call's *target*, not
  the speaker — a rule (`benchmark_for`) maps each call to the right null.
- **Family-wise error control:** Romano–Wolf resampling accounts for correlation across
  hypotheses, unlike naive Bonferroni; this is what collapses the raw significance.
- **Regression-locked baselines** (`baseline_lock.json`, `regression_test.py`): headline
  numbers are pinned so any pipeline change that moves them fails a regression test.
- **Single source of truth:** every number on the site is computed from
  `calendar_multi.json` at build time — no hand-maintained figures.

## Tech stack

Python · pandas / numpy · yfinance · LLM tool-calling (DeepSeek / Claude) for extraction
and Q&A · FastAPI (`server.py`) for the local Q&A backend · a static HTML site generator
(`generate_site.py`) deployed to GitHub Pages.

## Repository layout

```
build_calendar_multi.py   # the backtesting engine (calendar-time, per-call benchmark)
resolve_target.py         # maps each call to its target + benchmark
verdict_rules.py          # significance / verdict thresholds
rw_core.py                # Romano–Wolf multiple-testing correction
extract_decisions.py      # LLM extraction of buy/sell calls from transcripts
extract_predictions.py    # LLM extraction of price predictions
add_analyst.py            # one-command onboarding of a new analyst end-to-end
generate_site.py          # builds the self-contained index.html
ask_combined.py, server.py# natural-language Q&A agent + local API
manage.py                 # admin/deploy CLI (rebuild, recalc, publish)
calendar_multi.json       # single source of truth: all backtest results
METHODOLOGY.md            # full methodology write-up
ARCHITECTURE.md           # system architecture
```

## Reproducing locally

```bash
pip install -r requirements.txt
cp .env.example .env      # add your own API keys
python build_calendar_multi.py   # rebuild results (needs local price/transcript caches)
python generate_site.py          # regenerate the static site
```

> Note: raw data (price caches `*.pkl`, transcript DBs `*.db`, `data_cache/`) is **not**
> committed — it's large and partly personal-API-sourced. The committed
> `calendar_multi.json` lets you inspect the final results without rebuilding.

---

*Built by Henry Lin — Statistics & Economics, McGill University.*

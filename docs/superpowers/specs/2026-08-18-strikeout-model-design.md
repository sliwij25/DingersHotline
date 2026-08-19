# Strikeout Prop Model — Design Spec

*Date: 2026-08-18*

## What This Is

A second prediction pipeline, sibling to Homer (the existing HR model), that ranks
starting pitchers for MLB strikeout props (`pitcher_strikeouts` over/under market).
Same deterministic-scoring + LightGBM-blend philosophy as Homer, run in the same
daily job, published as its own page on the site.

## Why a Sibling Module, Not a Merge

Homer's data-gather + scoring is already a large, working, live pipeline. Strikeouts
need a mostly-disjoint signal set (pitcher whiff rates, workload, opposing-lineup
whiff tendencies) and a disjoint odds market. Building this as `agents/k_predictor.py`
with its own `Ace` class:

- Keeps a bug in the new model from ever touching the working HR pipeline.
- Lets the two models have independently-tuned scoring formulas and independently
  retrained ML models with their own AUC trajectories.
- Still reuses the boring, already-correct plumbing: lineup fetch, EV/Kelly math,
  the Pinnacle-benchmark odds pattern, and (new, but symmetric) the
  `leaderboard/pitch-arsenal-stats` per-pitch-type endpoint already integrated for
  Homer's batter-vs-pitch-type splits.

## Data & Signals

Statcast pitcher leaderboard call gets new columns (alongside the existing
HR-related ones): `k_percent`, `whiff_percent`, `csw_percent`, `swinging_strike_percent`.

| Group | Signal | Source | Notes |
|---|---|---|---|
| Core K ability | K%, Whiff%, CSW% | Savant `leaderboard/custom` (pitcher) | season-level |
| Recent form | K's over last 3 starts | MLB Stats API gamelog (`strikeOuts`) | same pattern as pitcher HR/9 |
| Pitch-type whiff | Whiff% on fastball / breaking / offspeed | Savant `leaderboard/pitch-arsenal-stats` (type=pitcher) | reuses the endpoint built for Homer's batter splits |
| Matchup | Opposing confirmed batters' whiff% vs pitcher's dominant pitch mix | Savant `leaderboard/pitch-arsenal-stats` (type=batter) weighted by pitcher's pitch mix % | per-batter, not team aggregate — sharper signal |
| Workload | IP/start, pitches/start (last 3–5 starts) | MLB Stats API gamelog | gates the ceiling on total K's; a high-K/9 pitcher who only goes 4.2 IP is a bad prop |
| Rest | Days since last start | MLB Stats API schedule | short-rest penalty |
| Odds/EV | `pitcher_strikeouts` market, Pinnacle benchmark, EV on $10, Kelly | The Odds API | reused `_compute_ev`/`_compute_kelly` from `predictor.py` |

**Deliberately excluded:** park factor, weather. Those drive HR outcomes via
batted-ball carry; they have no meaningful causal link to swing-and-miss outcomes.
Carrying them over from the HR model would be a borrowed-but-wrong signal.

**Deferred:** umpire strike-zone tendency. Real research supports it, but there's no
verified reliable source yet for today's plate umpire assignment + historical zone
data. Revisit in a future iteration if a good source turns up.

**Starter confirmation:** unlike HR's roster-fallback (−2 penalty for unconfirmed
batters), an unconfirmed starting pitcher is *excluded* entirely rather than
penalized — starters are typically announced a day or more ahead, so there's no
meaningful "early roster fallback" case the way there is for batting lineups.

## Scoring

`_score_pitcher()` in `agents/k_predictor.py`, threshold-bonus style matching
Homer's `_score_player()`. Exact point thresholds to be tuned via the correlation
report from `optimize_weights_k.py --report` once enough labeled data exists —
initial thresholds seeded from published K-prop research, same approach Homer's
original thresholds took.

## ML Blend

Same architecture as Homer: `_ml_score()` blended in via
`ml_weight = min(0.70, max(0.0, (AUC − 0.50) × 2.5))`, backed by a LightGBM model.
New `ml/optimize_weights_k.py`, saving `ml_weights_k.json` + `lgbm_model_k.txt`.
Cold start: correlation-report-only mode until ~2 weeks of labeled data accumulate,
same message pattern as the existing optimizer's `--min` gate.

## Storage

New `pick_factors_k` table in `data/bets.db` (own schema — the signal set above,
plus `bet_date, player, algo_version, confidence, score, rank, ev_10, kelly_size,
value_edge, pinnacle_odds, homered`-equivalent outcome column named `over_hit`
[1 if actual K's > the line, else 0]). No personal bet tracking table — consistent
with the existing standing rule that personal bets aren't logged by Claude anymore;
the site shows **hypothetical model P&L only** ($10 on every top-N K pick), same
framing as the HR dashboard.

`save_pick_factors_k()` lives in `agents/bet_tracker.py` alongside the existing
`save_pick_factors()` — it's another table in the same DB, not a different concern,
so a new file isn't warranted.

## Daily Pipeline Integration

`scripts/daily_picks.py` runs Homer's full pipeline today. Add a second step after
it: `Ace().get_picks_json()`, writing today's K picks alongside HR picks, auto-commit
+ push covers both (already scoped broadly enough via the auto-push hook's file
patterns — `picks/*.txt`/`.html` will need a K-specific filename convention, e.g.
`picks/k_picks_YYYY-MM-DD.txt`, to keep them from colliding with HR's `picks_*`
files).

Labeling: extend `ml/fetch_actual_results.py` (or a sibling
`fetch_actual_k_results.py`) to pull actual strikeout totals from MLB boxscores
after games end, same fuzzy-match-by-name pattern as HR's `update_pick_factors()`.

## Pick Count

Top 10 daily K picks (not top 20, and not the top-15 count used for HR's
Telegram/site delivery). A given day has roughly 12-15 starting pitchers total
league-wide with confirmed starts and odds — a 20-pick pool doesn't meaningfully
exist for this market, and ranking deep into low-confidence names would just add
noise. `Ace.get_picks_json()` returns the top 10 by score.

## Site

New standalone page `docs/strikeouts.html`, linked in nav alongside
pick-of-the-day/leaderboard. Same card-based visual style as the HR pick pages.
Shows: ranked pitcher K picks, confidence tiers, hypothetical model P&L (K-specific,
not commingled with HR P&L — two separate fictitious $10-per-pick portfolios).

## Bootstrap / Cold Start

No historical strikeout training data exists yet. Two options for getting the model
off the ground, to be decided at implementation time:
1. Build a historical dataset the same way `ml/build_historical_dataset.py` did for
   HR (pull real game-day starters + actual K outcomes from MLB Stats API for prior
   seasons) — gets the model trainable on day one instead of waiting ~2 weeks.
2. Just start live and wait for the correlation-report-only period like Homer's
   original bootstrap.

Recommendation: option 1, since the historical-rebuild pattern already exists and
worked well for HR (see `notes/ALGORITHM.md`'s 2026-07-06 entry) — reduces cold
start from weeks to a single backfill run.

## Out of Scope (this iteration)

- Umpire tendency signal (deferred, no reliable source yet).
- Batter strikeout props (pitcher props only, per requirements).
- Any change to the existing HR pipeline, tables, or site pages.

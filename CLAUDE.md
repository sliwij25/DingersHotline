# DingersHotline — Claude Project Instructions

This file gives Claude context about the DingersHotline project so future sessions
can pick up without re-deriving the architecture.

---

## Project Purpose

A home run betting tracker and AI prediction system used for wagering on MLB
HR props on ProphetX and Novig. Bets are $10 singles. The goal is to find
value picks using live data and track performance over time.

---

## Architecture at a Glance

```
daily_picks.py              ← Run every morning in Spyder (or with --use-cache for testing)
record_results.py           ← Run after games end (~11pm ET) to log win/loss + see model post-mortem
fetch_actual_results.py     ← Auto-labels pick_factors with MLB HR results (called by daily_picks.py)
build_historical_dataset.py ← Bootstrap 2015–present training data (188k rows, run once)
optimize_weights.py         ← Train logistic regression → ml_weights.json (auto-called by daily_picks.py)
cache_data.py               ← Save today's data for offline testing
test_homer_prompt.py        ← Test pick logic without re-fetching data
DingersHotline.ipynb           ← Log bets, P&L charts, backtesting
ml_weights.json             ← Auto-generated ML model weights
agents/
  base.py               ← Shared Claude client (claude-3.5-sonnet via Claude Code) + run_agent() loop
  predictor.py          ← Homer: fetches all data, builds per-game player cards, ranks picks (Python scorer, no LLM)
  bet_tracker.py        ← BetTrackerAgent: SQLite reads/writes, P&L summaries, save_pick_factors()
  overseer.py           ← OverseerAgent: orchestrates Homer + BetTrackerAgent
  backtester.py         ← Scores historical bets, finds winning factors
data/bets.db            ← SQLite database (singles + pick_factors ML training table)
cache/historical/       ← Cached Statcast + HR event CSVs for 2015–2025 (never re-fetched)
api/.env                ← API keys (never commit)
```

---

## Key Design Decisions

### Gather-then-analyze (Homer)
Homer does **NOT** use Claude for ranking. Instead:
1. Python calls all data tools directly (Statcast, lineups, odds, BallparkPal, etc.)
2. Aggregates everything into a deterministic scoring function
3. Returns ranked picks using `_score_player()` in `predictor.py` (pure Python, no LLM)

This was necessary to avoid LLM hallucinations when context is large (~100k tokens).
The system is **100% reproducible** and **fully auditable** — you can see exactly why each player is ranked.

### Claude API (via Claude Code)
All agent calls now use Claude 3.5 Sonnet via the Claude Code interface.
No local Ollama setup needed. Trade-off: Claude API costs money, so use the cache-and-iterate system
to avoid re-fetching data during development. See COST_OPTIMIZATION.md for details.

### BallparkPal session auth
`_get_bpp_session()` in predictor.py logs in via POST to Login.php and
caches the session for 1 hour. Falls back to FanGraphs + OpenWeatherMap
if credentials are missing or login fails.

### ML Score Blend
`_score_player()` in predictor.py ends with an ML blend:
```python
ml = Homer._ml_score(sig)
if ml is not None:
    auc = weights.get("cv_auc_mean", 0.5)
    ml_weight = min(0.7, max(0.0, (auc - 0.5) * 2.5))
    score = (1.0 - ml_weight) * score + ml_weight * ml
```
- `ml_weight` = 0 at AUC=0.50 (pure heuristic), 0.70 max at AUC≥0.78
- `Homer._ml_weights` and `Homer._ml_weights_loaded` are class-level caches
- After auto-retraining, `Homer._ml_weights_loaded = False` forces reload on next pick run

---

## ML Pipeline (Self-Improving Model)

All maintenance runs automatically inside `_auto_maintain()` at the top of `daily_picks.py`.
No manual script runs are needed by the user.

### Three auto-maintenance steps (run every morning before picks):

**Step 1 — Label yesterday's results** (`fetch_actual_results.py`)
- `fetch_homers_for_date(date)` → MLB Stats API schedule + boxscores → `{player: hr_count}`
- `update_pick_factors(date, homers)` → fuzzy match (SequenceMatcher ≥0.85) → sets `homered=1` or `0`

**Step 2 — Refresh 2026 training data** (`build_historical_dataset.py`)
- `fetch_statcast_season(CURRENT_YEAR)` → Savant leaderboard CSV → `{name: signals}`
- `fetch_hr_events_season(CURRENT_YEAR)` → Savant HR events CSV → `{date: [names]}`
- `write_season_to_db(year, statcast, hr_events)` → `INSERT OR IGNORE` → never overwrites live picks
- 2015–2025 are cached in `cache/historical/`; only 2026 is re-fetched each morning

**Step 3 — Retrain ML weights if due** (`optimize_weights.py`)
- Retrain conditions: first time (≥100 rows) OR (7+ days old AND 200+ new rows) OR 2000+ new rows
- `load_training_data()` → loads `pick_factors WHERE homered IS NOT NULL`, imputes NaN with median
- `train_and_save(X, y)` → LogisticRegression(C=0.5, class_weight="balanced") + StandardScaler
- Cross-val AUC reported; weights saved to `ml_weights.json`
- `Homer._ml_weights_loaded = False` invalidates cache so new model loads immediately

### Training data design (eliminates selection bias)
- `daily_picks.py` saves signal snapshots for **top 20 ranked players** (not just placed bets)
- The model sees who didn't homer as well as who did — critical for unbiased logistic regression
- `save_pick_factors(date, player, signals, confidence, algo_version, score, rank)` in `bet_tracker.py`

### pick_factors schema (expanded)
New columns added for ML training:
`score, rank, homered, xiso, xslg, xhr_rate, fb_pct, launch_angle, ev_avg, sweet_spot_pct, bpp_hr_pct, park_hr_factor, lineup_confirmed`

Migration is handled by `_MIGRATION_COLUMNS` in `bet_tracker.py` — safe `ALTER TABLE ADD COLUMN IF NOT EXISTS` loop.

### 19 ML features (FEATURES list in optimize_weights.py)
Grouped by predictive research source:
- **Contact quality**: barrel_rate (r=0.70), ev_avg (r=0.57), hard_hit_pct (r=0.66), sweet_spot_pct (r=0.42), xiso, xslg, xhr_rate
- **Batted ball**: fb_pct (fly ball% — strong HR correlation), launch_angle (r=0.42), hr_fb_ratio
- **Context**: bpp_hr_pct, park_hr_factor, ev_10, value_edge, recent_form_14d, pitcher_hr_per_9, is_home, platoon, h2h_hr

### New scoring rules added to _score_player() (predictive r values from research)
- `xslg`: only scores if `xiso` is None (avoids double-counting), thresholds: ≥0.600=+4, ≥0.500=+3, ≥0.420=+2, ≥0.360=+1, <0.280=-1
- `xhr_rate`: ≥6%=+4, ≥4.5%=+3, ≥3%=+2, ≥2%=+1, <1.5%=-1
- `fb_pct`: ≥45%=+3, ≥38%=+2, ≥30%=+1, <20%=-2 (RotoGrinders research)
- `launch_angle`: ≥25°=+2, ≥20°=+1, ≥12°=0, <12°=-1 (NOTE: high angles are POSITIVE per r=+0.43)
- `ev_avg`: ≥93=+3, ≥91=+2, ≥89=+1, <87.5=-1, <86=-2
- `sweet_spot_pct`: ≥42%=+2, ≥37%=+1, <28%=-1
- HR/FB sustainability: `if hr_fb_ratio > 20 and fb_pct < 25: score -= 2`

---

## Homer's Data Pipeline (_gather_data)

Steps run sequentially, results merged into one context passed to the model:

1. `fetch_confirmed_lineups()` — MLB Stats API (with `hydrate=lineups(person),probablePitcher(person)` for IDs + handedness)
2. `check_lineup_availability()` — cross-checks pending bets vs lineups
3. Full Statcast batter leaderboard (CSV, all batters in one request)
4. Full Statcast pitcher leaderboard (CSV, all pitchers in one request)
5. `fetch_recent_hr_form()` — HR leaders last 14 days from Savant
6. `fetch_pitcher_matchups()` + `fetch_park_factors()` — BallparkPal
   `fetch_odds_comparison()` — all sportsbooks, consensus line, EV, Kelly, value flags
7. `_fetch_pitcher_recent_form()` — last 3 starts HR/9 per starting pitcher (MLB Stats API game log)
8. `_fetch_home_away_splits_batch()` — home/away splits for all confirmed batters (batch MLB API call)
9. `_build_game_cards()` — per-batter card cross-referencing all data sources; returns `(text, player_signals)`
10. `_add_roster_fallback()` — for teams without confirmed lineups, fetch full roster and add unconfirmed batters to candidate pool (marked `lineup_confirmed: False`)

After step 9, `_gather_data()` merges odds signals (EV, Kelly, value_edge, Pinnacle) into `player_signals`.
After step 10, roster fallback batters are added with `-2 scoring penalty` to rank below confirmed batters.

---

## Roster-Based Fallback (added session 4)

When lineups aren't confirmed yet (typically early in the day before 11am ET):
- `_add_roster_fallback()` fetches full team rosters from MLB API
- Adds unconfirmed batters to candidate pool with `lineup_confirmed: False` marker
- `_score_player()` applies **−2 penalty** for unconfirmed players (so confirmed batters rank higher)
- Picks with unconfirmed batters are labeled `[ROSTER FALLBACK]` in the output

This allows picks to run even before official batting orders are posted (typically 2–4 hours before first pitch).
Strategy: confirmed lineup picks rank first; roster fallback picks are backups if you need early recommendations.

---

## Six Mathematical Enhancements (added session 3)

All implemented as pure Python helpers — no extra LLM calls.

### 1. Expected Value (EV)
`_compute_ev(pinnacle_prob, best_odds_int, stake=10.0)` in `predictor.py`
- Uses Pinnacle implied probability as the "true" probability (sharpest market)
- `EV = pinnacle_prob × profit − (1 − pinnacle_prob) × stake`
- Positive = bet is profitable long-run; negative = paying too much vig
- `fetch_odds_comparison()` returns `ev_10` field per player

### 2. Platoon Advantage
`_platoon_edge(bat_side, pitcher_throws)` in `predictor.py`
- `PLATOON+` when batter faces opposite-hand pitcher (L vs R or R vs L) — historic HR advantage
- Switch hitters (`S`) always `PLATOON+`
- `platoon-` = same-hand matchup (disadvantage)
- Derived from lineup hydration: `batSide.code` and `pitchHand.code` from MLB Stats API

### 3. Pitcher Recent Form
`_fetch_pitcher_recent_form(pitcher_id, n_starts=3)` in `predictor.py`
- Hits MLB Stats API: `/api/v1/people/{id}/stats?stats=gameLog&group=pitching`
- Filters to starts only (≥3 IP), returns HR/9 and total HR over last 3 starts
- High HR/9 = pitcher is currently vulnerable regardless of season stats

### 4. Kelly Criterion
`_compute_kelly(pinnacle_prob, best_odds_int, bankroll=200.0, max_fraction=0.15)` in `predictor.py`
- `f* = (b × p − q) / b` where b = decimal_odds − 1, p = pinnacle_prob, q = 1 − p
- Capped at 15% of bankroll ($30 max on $200 bankroll)
- Returns 0.0 for negative-EV situations
- `fetch_odds_comparison()` returns `kelly_size` field per player

### 5. Head-to-Head Career Stats
`_fetch_head_to_head(batter_id, pitcher_id)` in `predictor.py`
- MLB Stats API: `/api/v1/people/{batter_id}/stats?stats=vsPlayer&opposingPlayerId={pitcher_id}`
- Only returns data if ≥5 AB (meaningful sample)
- Only called for top 4 batters per team to limit API calls (~120 calls max per run)

### 6. Home/Away Splits
`_fetch_home_away_splits_batch(player_ids)` in `predictor.py`
- MLB Stats API: `/api/v1/stats?stats=splits&sitCodes=h,a&playerIds=...` (batch, one call)
- Returns HR, PA, slugging, OPS for each batter at home vs away
- Game cards show splits for the correct venue type (home/away based on lineup side)

---

## Odds Comparison (fetch_odds_comparison)

Fetches HR props (over 0.5 only — standard HR prop) from all
available sportsbooks via regions `us,eu` and computes:
- **Pinnacle line** — sharpest benchmark, no retail markup (EU region)
- **Best available line** per player + which book offers it
- **Consensus implied probability** — average across all books, vig stripped
- **value_edge** = consensus_prob − best_odds_implied_prob (positive = value)
- **VALUE flag** when edge >= 3 percentage points
- **ev_10** — expected value on $10 bet (Pinnacle prob as true probability)
- **kelly_size** — Kelly Criterion optimal stake ($200 bankroll, 15% cap)

Key implementation notes:
- Player names are in the `description` field, NOT `name` ("Over"/"Under")
- Filter `point == 0.5` to exclude 2+ HR / 3+ HR parlays from BetRivers
- Pinnacle key is `pinnacle` in the `eu` region
- Novig and ProphetX are NOT on The Odds API — output prompts user to compare manually
- odds_check.py (standalone utility) shows all books per player + EV/Kelly columns

---

## Algorithm Performance Tracking

`pick_factors` table in `data/bets.db` stores a signal snapshot for every pick.
Saved automatically by `daily_picks.py` after Homer's `get_picks_json()`.

Key functions in `bet_tracker.py`:
- `save_pick_factors(bet_date, player, signals, confidence, algo_version)` — stores snapshot
- `factor_performance_report()` — joins pick_factors with singles, shows which signals predict wins

`player_signals` dict (keyed by player name) is built by `_build_game_cards()` in `_gather_data()`
and enriched with odds data. Passed from `get_picks_json()` → attached to each pick → saved to DB.

Tracking fields per pick:
`platoon, barrel_rate, hard_hit_pct, hr_fb_ratio, recent_form_14d, pitcher_hr_per_9,
h2h_hr, h2h_ab, is_home, venue_slugging, ev_10, kelly_size, value_edge, pinnacle_odds,
confidence, algo_version`

When the algorithm changes significantly, bump `algo_version` in `daily_picks.py` so the
`factor_performance_report()` can compare before/after win rates.

---

## Database

SQLite at `data/bets.db` with two tables:

**`singles`** — one row per bet:
| Column           | Type    | Notes                              |
|------------------|---------|------------------------------------|
| id               | INTEGER | PK autoincrement                   |
| bet_date         | TEXT    | YYYY-MM-DD                         |
| platform         | TEXT    | 'prophetx' or 'novig'              |
| player           | TEXT    | Full player name                   |
| game             | TEXT    | e.g. "LAA @ NYY 7:05 PM"          |
| wager            | REAL    | Always $10.0                       |
| odds             | TEXT    | e.g. "+275"                        |
| potential_payout | REAL    | Platform's displayed payout        |
| result           | TEXT    | 'win', 'loss', or NULL (pending)   |
| payout           | REAL    | Total return for wins (wager+profit)|
| notes            | TEXT    | Optional                           |

**`pick_factors`** — signal snapshot per pick (auto-created by `save_pick_factors()`):
| Column             | Type    | Notes                                      |
|--------------------|---------|--------------------------------------------|
| bet_date           | TEXT    | YYYY-MM-DD                                 |
| player             | TEXT    | Full player name                           |
| algo_version       | TEXT    | e.g. "3.0" — bump when algo changes        |
| confidence         | TEXT    | HIGH / MEDIUM / LOW                        |
| ev_10              | REAL    | Expected value on $10 bet                  |
| kelly_size         | REAL    | Kelly optimal stake ($200 bankroll)        |
| value_edge         | REAL    | Consensus − best_book implied prob (pp)    |
| pinnacle_odds      | TEXT    | e.g. "+245"                                |
| platoon            | TEXT    | PLATOON+ or platoon-                       |
| barrel_rate        | REAL    | Season barrel%                             |
| hard_hit_pct       | REAL    | Season hard hit%                           |
| hr_fb_ratio        | REAL    | Season HR/FB ratio                         |
| recent_form_14d    | INTEGER | HRs hit in last 14 days                    |
| pitcher_hr_per_9   | REAL    | Pitcher HR/9 over last 3 starts            |
| h2h_hr             | INTEGER | Career HR vs this pitcher                  |
| h2h_ab             | INTEGER | Career AB vs this pitcher                  |
| is_home            | INTEGER | 1=home, 0=away                             |
| venue_slugging     | TEXT    | SLG at today's venue type                  |
| lineup_confirmed   | INTEGER | 1=confirmed, 0=roster fallback             |

To record a result directly via sqlite3:
```bash
sqlite3 data/bets.db "UPDATE singles SET result='loss' WHERE bet_date='YYYY-MM-DD' AND player LIKE '%Name%' AND result IS NULL;"
```

---

## API Keys (stored in api/.env)

| Variable               | Service               |
|------------------------|-----------------------|
| ODDS_API_KEY             | the-odds-api.com        |
| BALLPARKPAL_EMAIL        | ballparkpal.com         |
| BALLPARKPAL_PASSWORD     | ballparkpal.com         |
| OPENWEATHER_API_KEY      | openweathermap.org      |

Free-tier limits: Odds API = 500 req/month, OpenWeatherMap = 1000/day.
Daily script uses ~12–15 Odds API requests (one per game).

---

## GitHub

- **Repo:** `https://github.com/sliwij25/DingersHotline` (private, user: sliwij25)
- **Auto-commit:** `daily_picks.py` commits + pushes after every run — ml_weights.json, code changes, etc.
- **Routine trigger ID:** `trig_01HWF4ucuuE1fofLn6M2GcgD` (claude.ai/code/routines)
- **Dispatch command:** `Run ~/AIProjects/DingersHotline/run-picks.sh and show me today's top HR picks and model stats`
- **launchd job:** `com.homerunbets.daily` — fires at 11am daily, output to `logs/daily_picks.log`
- **Mac wake schedule:** `sudo pmset repeat wakeorpoweron MTWRFSU 10:55:00`

---

## Pick Grading System

See **[GRADING.md](GRADING.md)** for the full star rating definitions, AUC ceiling thresholds, and rank bands.

Stars combine two signals: rank within today's top 20 pool + model accuracy ceiling (AUC).
Current max: ★★★★☆ (AUC 0.634). Reaches ★★★★★ when AUC ≥ 0.65.

---

## Common Tasks

### Record a result
```python
# In notebook Section 3, or directly via bet_tracker:
set_result('2026-04-15', 'Aaron Judge', 'win', payout=37.50)
set_result('2026-04-15', 'Yordan Alvarez', 'loss')
```

### Daily workflow (token-efficient)
```bash
# Morning — get picks + log bets interactively (prompts you after picks show)
python daily_picks.py

# Iterate on scoring logic WITHOUT re-fetching any data
python test_homer_prompt.py                      # re-run picks from cache
python test_homer_prompt.py --debug Aaron Judge  # why is Judge scoring low?
python test_homer_prompt.py --pipeline           # are BPP/park/weather signals populated?

# Bet management (no Homer loaded — fast)
python bets.py                           # pending bets + P&L summary
python bets.py log                       # log new bets interactively
python bets.py history                   # full history
python bets.py history --player Judge    # filter by player
python bets.py stats --player Judge      # win rate + ROI

# Night — record results + model post-mortem
python record_results.py
```

### Run backtesting
```python
from agents import backtest_report
backtest_report()
```

### Check algorithm performance (which signals predict wins)
```python
from agents import factor_performance_report
import json
print(factor_performance_report())
```

---

## Platforms

- **ProphetX** — standard sportsbook, American odds
- **Novig** — no-vig exchange, typically tighter lines
- Both accept $10 HR single bets

---

## Things to Know

- **Statcast CSV BOM**: Baseball Savant CSV starts with a UTF-8 BOM (`\ufeff`) that corrupts
  the `last_name, first_name` column header. `_fetch_full_statcast()` strips it with
  `resp.text.lstrip('\ufeff')` before parsing. Without this fix, `batter_stats = {}` and
  all Statcast signals (barrel, hh, xiso) are MISSING for every player.
- Statcast data is unreliable in April (small sample sizes, <50 PA).
  Barrel rate and hard hit% become meaningful from late April onwards.
- BallparkPal provides matchup grades (0–10) and park-adjusted HR%.
  These are the most predictive signals when Statcast samples are thin.
- **Park factor venue matching**: BPP Park-Factors.php game strings use "Away @ Home" format.
  `_gather_data()` stores park factors under both team parts AND their known stadium names
  (via `_TEAM_VENUE` lookup dict). Player `venue` from MLB API is a full stadium name.
- Odds API `batter_home_runs` market may return 422 for some events
  (no props listed yet) — this is expected and handled with a `continue`.
- The `fetch_odds_comparison()` function caps at 12 games to stay within
  the 500 req/month free tier (12 events × ~25 days = ~300 requests).

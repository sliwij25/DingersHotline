# Home Run Bets

A home run betting tracker and AI prediction system for ProphetX and Novig.

---

## What This Does

- **Tracks** every HR bet you place (player, odds, wager, result, payout)
- **Predicts** the best HR picks each day using live data from multiple sources
- **Analyzes** your betting history to identify which factors predict wins
- **Stores** everything in a local SQLite database — no cloud, no subscriptions (except BallparkPal)

---

## Project Structure

```
HomeRunBets/
├── daily_picks.py              ← Run this every morning (--use-cache for testing)
├── test_homer_prompt.py        ← Test pick logic without re-fetching data
├── record_results.py           ← Record tonight's game results + model post-mortem
├── fetch_actual_results.py     ← Auto-labels pick_factors with MLB HR results (ML training)
├── build_historical_dataset.py ← Bootstrap 2015–present historical data (188k rows)
├── optimize_weights.py         ← Train logistic regression on labeled picks → ml_weights.json
├── cache_data.py               ← Save today's data for offline testing
├── HomeRunBets.ipynb           ← Notebook for logging bets, recording results, P&L charts
├── requirements.txt            ← Python dependencies
├── ml_weights.json             ← Auto-generated ML model (created after enough training data)
├── data/
│   └── bets.db                 ← SQLite database (all your bets + ML training data)
├── cache/
│   └── historical/             ← Cached Statcast/HR data for 2015–2025 (never re-fetched)
├── api/
│   ├── .env                    ← Your API keys (never share this file)
│   └── .env.example            ← Template showing what keys are needed
└── agents/
    ├── __init__.py
    ├── base.py                 ← Shared Claude client + agentic loop
    ├── predictor.py            ← Homer: fetches all data, builds per-game player cards, ranks picks
    ├── bet_tracker.py          ← Bet Tracker: DB reads/writes, P&L
    ├── overseer.py             ← Overseer: orchestrates both agents
    └── backtester.py           ← Scores historical bets, finds winning factors
```

---

## First-Time Setup

### 1. Install Python dependencies
Open Terminal in the HomeRunBets folder and run:
```
pip install -r requirements.txt
pip install scikit-learn scipy   # required for ML weight training
```

### 2. Fill in your API keys
Open `api/.env` and add your credentials:
```
ODDS_API_KEY=         ← from the-odds-api.com (free tier: 500 req/month)
BALLPARKPAL_EMAIL=    ← your BallparkPal login email ($10/month or $60/season)
BALLPARKPAL_PASSWORD= ← your BallparkPal password
OPENWEATHER_API_KEY=  ← from openweathermap.org (free tier: 1000 calls/day)
```

---

## Daily Workflow

### Morning — Get Today's Picks

**Step 1:** Open Spyder from Anaconda Navigator.

**Step 2:** Open and run `daily_picks.py` (press F5).

- Best time to run: **after 11am** when MLB posts confirmed lineups
- The script takes ~30–60 seconds to fetch all data
- Output includes ranked picks + ready-to-fill bet slips for ProphetX and Novig
- **Early morning runs** (before lineups post): Picks marked `[ROSTER FALLBACK]` are from full team rosters, ranked lower than confirmed-lineup picks. These are backups if you need recommendations before lineups are official.

**What runs automatically every morning (zero manual steps):**
1. Labels yesterday's pick results from MLB API (ML training data)
2. Refreshes 2026 Statcast data in the training database
3. Retrains ML weights if 7+ days old AND 200+ new rows have accumulated (or 2000+ new rows any time)
4. Saves signal snapshots for the top 20 ranked players (unbiased training data — not just placed bets)

### Place Your Bets
Open ProphetX or Novig, find the HR prop for each recommended player, and note:
- The **odds** (e.g. `+340`)
- The **potential payout** shown on the platform

### Log Your Bets (Jupyter Notebook)
Open `HomeRunBets.ipynb` in Spyder or Jupyter. In **Section 2 (Log Today's Bets)**, fill in and run `log_singles()`:

```python
log_singles('2026-04-15', 'prophetx', [
    {'player': 'Aaron Judge',  'game': 'LAA @ NYY 7:05 PM', 'odds': '+275', 'potential_payout': 27.50},
    {'player': 'Yordan Alvarez','game': 'COL @ HOU 8:10 PM', 'odds': '+260', 'potential_payout': 26.00},
], wager=10.0)
```

---

### Evening — Record Results

Once games are final, open the notebook and go to **Section 3 (Record Results)**.

For a **win**, pass the total return (wager + profit):
```python
# Aaron Judge hit a homer — +275 on $10 = $37.50 total return
set_result('2026-04-15', 'Aaron Judge', 'win', payout=37.50)
```

For a **loss**:
```python
set_result('2026-04-15', 'Yordan Alvarez', 'loss')
```

---

### View P&L

Run **Section 5 (P&L Dashboard)** in the notebook:
```python
pnl_summary()
```

This prints your record, total wagered, net P&L, ROI, and displays a bar + cumulative chart.

---

## Agents

All data fetching is done locally using Python (no API bottlenecks). Ranking uses Claude API. For cost optimization during development, see [COST_OPTIMIZATION.md](COST_OPTIMIZATION.md).

### Homer (Predictor)
`agents/predictor.py`

Fetches live data from all sources, builds a per-game card for every confirmed batter, and ranks today's best HR picks.

**Data sources Homer uses:**
| Source | What it provides |
|---|---|
| BallparkPal | Matchup grade (0–10), park-adjusted HR%, pitcher vs batter history |
| BallparkPal | Park HR factor, wind speed/direction, temperature, humidity |
| Baseball Savant (Statcast) | Barrel rate, hard hit %, HR/FB ratio, fly ball%, exit velocity, xISO, xSLG, xHR%, sweet spot% |
| MLB Stats API | Confirmed lineups, batting position, player IDs, bat/pitch handedness |
| MLB Stats API | Pitcher game log — HR/9 allowed over last 3 starts |
| MLB Stats API | Head-to-head career stats — batter vs today's specific pitcher |
| MLB Stats API | Home/away splits — HR, PA, slugging at each venue type |
| Baseball Savant | Recent HR form — HRs hit in the last 14 days |
| The Odds API | Best available odds + consensus line + EV + Kelly across all sportsbooks |
| Local DB | Our own win/loss record per player |
| ml_weights.json | Logistic regression model trained on 188k+ labeled historical at-bats |

**Pick criteria (in priority order):**
1. Lineup confirmed — skip any unconfirmed player
2. Our historical record — players we've cashed on before get an edge
3. Odds tier — favorites (<+250) are hitting at 75% in our data early in the season
4. Recent HR form (last 14 days) — hot streaks
5. Statcast power profile — barrel rate >10%, hard hit% >45%
6. BallparkPal matchup grade ≥7/10
7. Pitcher vulnerability — high HR/FB allowed + high FB%
8. Park HR factor >1.0
9. Weather — wind OUT 10+ mph is a strong positive; wind IN penalises heavily
10. Market signal — odds shortening = sharp money
11. **Platoon advantage** — batter facing opposite-hand pitcher (PLATOON+) hits more HRs historically
12. **Pitcher recent form** — pitcher HR/9 over last 3 starts; high = currently vulnerable
13. **Head-to-head** — career HR and OPS vs today's specific pitcher (min 5 AB)
14. **Home/away splits** — slugging and HR rate at today's venue type
15. **Expected value (EV)** — `Pinnacle_prob × profit − (1−Pinnacle_prob) × stake`; positive EV = profitable long-run
16. **Kelly Criterion** — optimal bet sizing based on EV; $200 bankroll, capped at 15%

### Bet Tracker
`agents/bet_tracker.py`

Handles all database operations — P&L summaries, pending bets, result recording, per-player stats, and algorithm performance tracking. Ask it anything in plain English:

```python
from agents import BetTrackerAgent
tracker = BetTrackerAgent()
print(tracker.run("Show me my full P&L summary with win rate and ROI."))
print(tracker.run("Who are my best performing players?"))
print(tracker.run("Show all pending bets."))
```

Or call the tracking functions directly:

```python
from agents import factor_performance_report
print(factor_performance_report())
```

### Overseer
`agents/overseer.py`

Coordinates Homer and the Bet Tracker for a full daily briefing:

```python
from agents import OverseerAgent
overseer = OverseerAgent()
print(overseer.run("Run the full daily workflow."))
```

---

## Odds Comparison & Value Finder

`daily_picks.py` includes an **ODDS COMPARISON** section that runs automatically after picks are generated. Also available standalone via `odds_check.py`.

For every player with HR props listed, it:
1. Fetches lines from **all available sportsbooks** (DraftKings, FanDuel, BetMGM, Caesars, etc.)
2. Computes the **consensus implied probability** — the market's true estimate, with the vig stripped out
3. Finds the **best available odds** and which book offers them
4. Calculates a **value edge** (in percentage points): `consensus_prob − best_odds_implied_prob`
5. Computes **Expected Value (EV)** on a $10 bet using Pinnacle's implied probability as the true probability
6. Computes **Kelly Criterion** optimal stake for a $200 bankroll

**How to use it:**
- **Pinnacle** is the sharpest sportsbook — no retail markup, used by professional bettors worldwide. Their line is the closest thing to a true market price.
- **EV > 0** means the bet is profitable long-term given the Pinnacle probability. Negative EV means you're paying too much vig.
- **Kelly size** = mathematically optimal stake. High Kelly = high conviction. Cap: $30 (15% of $200 bankroll).
- `VALUE` flag = one book's implied probability is 3+ percentage points lower than the market consensus
- If your Novig/ProphetX odds beat the Pinnacle column, you have real edge.

> **Note:** Novig and ProphetX are not available on The Odds API. Compare your platform to the Pinnacle column manually.

**Example output:**
```
Player                     Pinnacle    Best Odds   Best Book    Consensus%  Edge      EV($10)  Kelly    Flag
Shohei Ohtani              +245        +450        BetRivers    23.6%       +5.4pp    +$2.15   $8.20    VALUE
Cal Raleigh                +332        +575        BetRivers    19.0%       +4.2pp    +$3.80   $12.40   VALUE
Gary Sanchez               +440        +440        Pinnacle     18.5%       +0.0pp    -$0.50   $0.00
```

---

## Machine Learning Pipeline

Homer uses a self-improving ML model that trains on every pick it makes. The pipeline runs automatically — no manual steps required.

### How it works

1. **Daily picks → training data**: Every morning, `daily_picks.py` saves signal snapshots for the top 20 ranked players (not just bets placed — all 20 ranked candidates). This eliminates selection bias so the model learns from misses as well as hits.

2. **Result labeling**: The next morning, `daily_picks.py` auto-fetches yesterday's MLB boxscores and labels each pick with `homered=1` or `homered=0`. This creates supervised training data.

3. **Historical bootstrapping**: `build_historical_dataset.py` loaded 188,000+ labeled examples from 2015–2026 (2 API calls per season, cached). This gives the model a strong head start.

4. **Auto-retraining**: Once enough labeled data accumulates, `ml_weights.json` is created automatically. The model retrains when:
   - First time: 100+ labeled rows
   - Ongoing: 7+ days since last training AND 200+ new labeled rows
   - Force: 2,000+ new labeled rows regardless of age

5. **ML blend**: Homer's final score blends the heuristic score with the ML probability:
   - `final = (1 - ml_weight) × heuristic + ml_weight × ml_prob`
   - `ml_weight` scales from 0 (AUC=0.50) to 0.70 max (AUC≥0.78)
   - As the model improves, it gets more influence over rankings

### Signals used for training (19 features)
| Feature | Predictive r | Notes |
|---|---|---|
| barrel_rate | r=0.70 | Strongest single HR predictor |
| ev_avg | r=0.57 | Average exit velocity |
| hard_hit_pct | r=0.66 | Exit velocity ≥ 100 mph in air |
| sweet_spot_pct | r=0.42 | 8–32° launch angle rate |
| xISO | — | Expected isolated power |
| xSLG | — | Expected slugging (proxy for xHR% early season) |
| xHR% | — | Expected HR rate (populates ~June) |
| fb_pct | — | Fly ball rate — strong HR correlation |
| launch_angle | r=0.42 | Average launch angle |
| hr_fb_ratio | — | HR/FB — volatile early, meaningful mid-season |
| bpp_hr_pct | — | BallparkPal park-adjusted HR% |
| park_hr_factor | — | Park HR multiplier (1.00 = league average) |
| value_edge | — | Odds value vs consensus |
| recent_form_14d | — | HRs in last 14 days |
| pitcher_hr_per_9 | — | Pitcher vulnerability last 3 starts |
| platoon | — | Opposite-hand matchup advantage |
| h2h_hr | — | Career HRs vs today's pitcher |

### Running the ML optimizer manually
```bash
python optimize_weights.py           # train and save weights
python optimize_weights.py --report  # report only, don't save
```

---

## Algorithm Performance Tracking

Every time `daily_picks.py` runs, it automatically saves a signal snapshot for each pick to the `pick_factors` table in `data/bets.db`. Once results are recorded, you can run:

```python
from agents import factor_performance_report
import json
print(factor_performance_report())
```

This shows **which signals actually predict wins** across your settled bets:

| Signal condition | Bets | Wins | Win% |
|---|---|---|---|
| EV > 0 (profitable at Pinnacle) | 24 | 8 | 33.3% |
| EV ≤ 0 | 10 | 2 | 20.0% |
| PLATOON+ (opp-hand matchup) | 18 | 7 | 38.9% |
| platoon- (same-hand matchup) | 16 | 3 | 18.8% |
| VALUE flag (3+ pp edge) | 12 | 5 | 41.7% |
| Confidence: HIGH | 8 | 4 | 50.0% |
| 2+ HR last 14 days (hot streak) | 14 | 6 | 42.9% |
| h2h_hr ≥ 1 (hit HR off this pitcher) | 7 | 4 | 57.1% |

The report also breaks down win rate by **algo_version** — when we update the algorithm, the version tag increments so you can compare before/after.

---

## Backtesting

Run **Section 7 (Backtesting)** in the notebook to score all settled bets against the prediction criteria and see which factors are actually predicting wins.

Or run directly:
```python
from agents import backtest_report
backtest_report()
```

**Scoring factors (0–3 pts each, max 15):**
| Factor | 0 pts | 1 pt | 2 pts | 3 pts |
|---|---|---|---|---|
| Barrel rate | <5% | 5–10% | 10–15% | >15% |
| Hard hit % | <40% | 40–45% | 45–50% | >50% |
| HR/FB ratio | <10% | 10–15% | 15–20% | >20% |
| Recent form (14d HRs) | 0 | 1 | 2 | 3+ |
| Odds tier | +450+ | +350–449 | +250–349 | <+250 |

> **Note:** Statcast scores are unreliable in April (small sample sizes). They become the strongest signal from late April onwards when players have 50+ PA.

---

## Bet Sizing

| Bet type | Platform | Wager |
|---|---|---|
| Single HR prop | ProphetX | $10 |
| Single HR prop | Novig | $10 |

---

## API Keys Reference

| Key | Where to get it | Cost |
|---|---|---|
| `BALLPARKPAL_EMAIL` / `PASSWORD` | ballparkpal.com | $10/month or $60/season |
| `ODDS_API_KEY` | the-odds-api.com | Free (500 req/month) |
| `OPENWEATHER_API_KEY` | openweathermap.org | Free (1000 calls/day) |

---

## Data Tools Reference

### `fetch_actual_results.py`
Labels yesterday's pick results from the MLB API. Runs automatically every morning inside `daily_picks.py`. Can also be run manually:
```bash
python fetch_actual_results.py              # label today
python fetch_actual_results.py 2026-04-14  # label a specific past date
python fetch_actual_results.py --show      # show results without saving
```

### `build_historical_dataset.py`
Bootstrap the ML training database with 2015–present historical data (188k rows). Only needs to run once; yearly caches are stored in `cache/historical/`.
```bash
python build_historical_dataset.py           # all seasons 2015–present
python build_historical_dataset.py --refresh # current season only (fast update)
python build_historical_dataset.py --stats   # show row counts per year
```

### `optimize_weights.py`
Train logistic regression on labeled pick data. Runs automatically inside `daily_picks.py` when retraining is due. Can also be run manually:
```bash
python optimize_weights.py           # train and save ml_weights.json
python optimize_weights.py --report  # report only, don't save weights
```

### `test_homer_prompt.py`
Iterate on scoring logic without making any API calls:
```bash
python test_homer_prompt.py                      # top 8 picks from latest cache
python test_homer_prompt.py --debug Aaron Judge  # explain why a player scored low/high
python test_homer_prompt.py --pipeline           # data pipeline health (% signals populated)
python test_homer_prompt.py --top 20             # show top 20 picks
```

---

## GitHub & Automation

### Repository
`https://github.com/sliwij25/HomeRunBets` (private)

### Auto-commit
Every morning when `daily_picks.py` runs it automatically commits and pushes changes to GitHub — updated ML weights, any code edits, etc. No manual git steps required.

### Running picks without touching your laptop

**Automated (11am daily):**
A macOS launchd job runs `daily_picks.py` every day at 11am. Output goes to `logs/daily_picks.log`.

To ensure the Mac wakes from sleep in time:
```bash
sudo pmset repeat wakeorpoweron MTWRFSU 10:55:00
```

**On demand via Claude Dispatch:**
Open the Claude mobile app → Dispatch tab → send:
> Run `~/AIProjects/HomeRunBets/run-picks.sh` and show me today's top HR picks and model stats

**On demand via remote trigger:**
The routine `trig_01HWF4ucuuE1fofLn6M2GcgD` is set up at claude.ai/code/routines.
Fire it from anywhere with:
```bash
curl -X POST https://api.claude.ai/v1/code/triggers/trig_01HWF4ucuuE1fofLn6M2GcgD/fire \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json"
```
Save this as an iPhone Shortcut for one-tap access.

**On demand in Claude Code:**
Just say "run daily picks" and Claude will execute it directly in the session.

### Re-cloning on a new machine
```bash
git clone https://github.com/sliwij25/HomeRunBets.git
cd HomeRunBets
pip install -r requirements.txt
pip install scikit-learn scipy
cp api/.env.example api/.env   # then fill in your API keys
python build_historical_dataset.py  # rebuild historical training data
```

---

## Troubleshooting

**"Cache file not found"** (when using `--use-cache`)
You tried to use cached data but haven't run a fresh fetch yet.
Run `python daily_picks.py` first (without `--use-cache`) to create the cache.

**BallparkPal returns no data**
Check that `BALLPARKPAL_EMAIL` and `BALLPARKPAL_PASSWORD` are correctly set in `api/.env`. Credentials are case-sensitive.

**Lineups show no batting orders**
Run after 11am. MLB posts lineups 2–4 hours before first pitch. Running before that returns games with no batting orders.

**Picks look inconsistent**
If lineups aren't confirmed yet, you won't have picks. Wait until 11am–noon when MLB posts batting orders and re-run.

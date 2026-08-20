# Dingers Hotline — Algorithm & Scoring Guide

*Last updated: 2026-08-20*

---

## What This Is

Dingers Hotline is an MLB home run prop prediction system. Each morning it pulls live data from multiple sources, scores every batter in confirmed lineups, and ranks the top 20 HR candidates for the day. The goal is to find value picks for $10 HR singles on ProphetX and Novig.

---

## How It Works (Big Picture)

The system is **100% deterministic Python** — no AI or language model is involved in ranking picks. Every score is computed from a formula, so you can always trace exactly why a player ranked where they did.

1. Pull confirmed lineups from MLB API
2. Fetch Statcast metrics, park factors, weather, matchup grades, and odds
3. Score every confirmed batter using a weighted formula
4. Blend in a machine learning model (LightGBM gradient-boosted trees trained on historical results)
5. Rank and bucket players into confidence tiers
6. Publish to the site

---

## Data Sources

| Source | What It Provides |
|--------|-----------------|
| MLB Stats API | Confirmed lineups, pitcher handedness, home/away splits, head-to-head career stats, pitcher recent form |
| Baseball Savant (Statcast) | Season barrel rate, hard hit %, exit velocity, xISO, xSLG, xHR rate, sweet spot %, fly ball %, launch angle |
| BallparkPal | Matchup grades (0–10), park-adjusted HR probability, park HR factor |
| The Odds API | HR prop lines across all sportsbooks, Pinnacle (sharpest market), best available line, implied probability |
| OpenWeatherMap | Temperature and wind at game time (wind out = boost) |

---

## Scoring Formula

Each player gets a raw **score** built from individual signal bonuses and penalties. Higher score = better HR candidate.

### Contact Quality (Statcast)
*Note: Statcast metrics are down-weighted early in the season (< 40 PA) due to small sample size.*

| Signal | Thresholds | Points |
|--------|-----------|--------|
| **Barrel Rate** | ≥15% / ≥10% / ≥5% / <5% | +3 / +2 / +1 / −1 |
| **Hard Hit %** | ≥50% / ≥45% / ≥40% / <35% | +3 / +2 / +1 / −1 |
| **xISO** (expected isolated power) | ≥.250 / ≥.200 / ≥.160 / ≥.120 / <.080 | +4 / +3 / +2 / +1 / −1 |
| **xSLG** (expected slugging) | ≥.600 / ≥.500 / ≥.420 / ≥.360 / <.280 | +4 / +3 / +2 / +1 / −1 |
| **xHR Rate** (expected HR%) | ≥6% / ≥4.5% / ≥3% / ≥2% / <1.5% | +4 / +3 / +2 / +1 / −1 |
| **Exit Velocity Avg** | ≥93 / ≥91 / ≥89 mph / <87.5 / <86 | +3 / +2 / +1 / −1 / −2 |
| **Sweet Spot %** | ≥42% / ≥37% / <28% | +2 / +1 / −1 |

*xSLG only scores if xISO is unavailable (avoids double-counting).*

### Batted Ball Profile

| Signal | Thresholds | Points |
|--------|-----------|--------|
| **Fly Ball %** | ≥45% / ≥38% / ≥30% / <20% | +3 / +2 / +1 / −2 |
| **Launch Angle** | ≥25° / ≥20° / ≥12° / <12° | +2 / +1 / 0 / −1 |
| **HR/FB Sustainability** | HR/FB ratio >20% but fly ball% <25% | −2 (unsustainable pace) |

### Matchup & Context

| Signal | Thresholds | Points |
|--------|-----------|--------|
| **BallparkPal HR%** | ≥23% / ≥21% / ≥19% / ≥16% / ≥12% / <10% | +8 / +6 / +4 / +2 / +1 / −2 |
| **BallparkPal Rank** | Top 5 / Top 15 | +3 / +1 |
| **Park HR Factor** | ≥1.15 / ≥1.05 / <0.90 / <0.80 | +2 / +1 / −1 / −2 |
| **Platoon Advantage** | Batter faces opposite-hand pitcher | +2 |
| **Platoon Disadvantage** | Batter faces same-hand pitcher | −1 |
| **Recent Form (14 days)** | ≥3 HR / 2 HR / 1 HR / 0 HR | +3 / +2 / +1 / −1 |
| **Pitcher HR/9 (last 3 starts)** | ≥2.0 / ≥1.5 / ≥1.0 / <0.5 | +3 / +2 / +1 / −2 |
| **Head-to-Head Career HR** | ≥2 HR / 1 HR vs this pitcher | +2 / +1 |
| **Home/Away Splits** | Strong SLG at today's venue type | up to +2 |
| **Temperature** | ≥85°F / ≥75°F / <40°F | +1 / 0 / −1 |
| **Wind** | ≥15 mph out / ≥8 mph out / into batter | +3 / +1 / −2 |

### Odds / Value

| Signal | Thresholds | Points |
|--------|-----------|--------|
| **Expected Value (EV on $10)** | >$3 / >$1 / >$0 / >−$1 / ≤−$1 | +5 / +3 / +1 / −1 / −3 |
| **Value Edge** | Consensus prob − best book implied prob ≥3pp | VALUE flag |

### Lineup Status Penalties

| Status | Points |
|--------|--------|
| Lineup not yet confirmed (roster fallback) | −2 |
| Player status "waiting" | −1 |
| Player status "unknown" | −3 |

---

## Strikeout Model (Ace)

Parallel to Homer (HR batter model), Ace predicts **starting pitcher strikeout props** — Over/Under on the K line. Same philosophy: deterministic Python scoring, no LLM, fully auditable.

### Pitcher Quality Score

`_score_pitcher()` evaluates starting pitchers on strikeout rate, whiff rate, fastball/breaking/offspeed whiff splits, K per 9 innings, opposing lineup's strikeout susceptibility, recent workload, and rest. Score ranges 0–∞; higher = more explosive K potential. **Purpose: eligibility floor only.** The score does not determine ranking or confidence — that role belongs solely to the gap between projected and market K totals.

| Signal | Thresholds | Points |
|--------|-----------|--------|
| **K Rate** | ≥30% / ≥27% / ≥24% / ≥21% / <18% | +4 / +3 / +2 / +1 / −1 |
| **Whiff %** | ≥32% / ≥28% / ≥25% / <20% | +3 / +2 / +1 / −1 |
| **CSW %** | ≥33% / ≥30% / <26% | +2 / +1 / −1 |
| **Swinging Strike %** | ≥14% / ≥12% / <9% | +2 / +1 / −1 |
| **K per 9 (blended)** | ≥11 / ≥9.5 / ≥8 / ≥6.5 / <5 | +4 / +3 / +2 / +1 / −1 |
| **Pitcher whiff splits** (FB/BR/OS) | ≥35% / <20% | +1 / −0.5 |
| **Opp lineup whiff vs pitch mix** | ≥27% / ≥24% / ≥21% / <17% | +3 / +2 / +1 / −1 |
| **Avg IP last 3 starts** | ≥6.0 / ≥5.5 / <4.5 | +2 / +1 / −2 |
| **Avg pitches last 3** | ≥95 / <80 | +1 / −1 |
| **Rest (days between starts)** | 5–7 / 4 or 8–10 / ≤3 or >10 | 0 / ±0.5 / −1 to −2 |
| **EV (K prop)** | >$3 / >$1 / >$0 / >−$1 / ≤−$1 | +5 / +3 / +1 / −1 / −3 |

### Direction and Confidence

After computing `_score_pitcher()`, only pitchers scoring **≥ 2.0 pass the eligibility gate.** For eligible pitchers, `_pick_direction()` projects the K total and compares it to the market line:

**Projection Formula (`_project_k`):**
```
projected_K = k_per_9_blended × (avg_ip_last_3 / 9) × combined_factor

combined_factor = avg(
  opp_team_k_pct / LEAGUE_AVG_K_PCT,
  opp_lineup_whiff_vs_mix / LEAGUE_AVG_WHIFF
)
```
- `LEAGUE_AVG_K_PCT = 0.225` (MLB strikeout rate baseline)
- `LEAGUE_AVG_WHIFF = 28.0` (MLB whiff rate baseline)

**Gap-Based Confidence:**
```
gap = projected_K − market_line

if |gap| < 0.25:     skip (no actionable edge)
if |gap| >= 1.5:     confidence = HIGH
if |gap| >= 0.75:    confidence = MEDIUM
if |gap| >= 0.25:    confidence = LOW
```

Direction is **OVER** if `gap > 0` (projected K > line), **UNDER** if `gap < 0`.

### Ranking and Display

Pitchers are ranked by **absolute gap descending** (largest edge first). Confidence tier applies only to display — it does not affect ranking order. **Crucially: EV and odds signals contribute to the eligibility-floor score (via `_score_pitcher()`) but play no role in ranking order, direction, or confidence tier.** The recommendation is purely gap-driven: does the pitcher's projected K total exceed or fall short of today's line, and by how much?

---

## ML Score Blend

After the raw score is computed, it's blended with a **LightGBM model** trained on historical pick results.

```
ml_weight = min(0.70, max(0.0, (AUC − 0.50) × 2.5))
final_score = (1 − ml_weight) × raw_score + ml_weight × ml_score
```

- At **AUC = 0.50** (random): ml_weight = 0% — pure heuristic scoring
- At **AUC = 0.612** (current): ml_weight = **28%** — model has meaningful influence
- At **AUC ≥ 0.78**: ml_weight caps at **70%**

### Current Model Status
- **AUC: 0.612** (retrained 2026-07-06 after the historical dataset rebuild — see below)
- **Training data:** 314,000+ rows, one row per (game, actual lineup batter) for 2015–2026
- **Retrains automatically** each morning when ≥200 new labeled rows accumulate

### 2026-07-06 historical dataset rebuild
The historical training set used to be a cross-product of "every power hitter in the
season pool" × "every sampled date," regardless of whether the player's team even played
that day — so `park_hr_factor`, `is_home`, and `pitcher_hr_per_9` were always `None` for
historical rows despite being real features. It was rebuilt in `ml/build_historical_dataset.py`
to pull actual game-day lineups + starting pitchers from the MLB Stats API schedule
endpoint (one call per game-day) and season-level pitcher HR/9, so every historical row
now reflects a real game the batter actually played in, with real park/pitcher/home-away
context. `pitcher_hr_per_9` is now the single most important feature by LightGBM gain.

Headline AUC dropped from ~0.72 (last live-committed value) to 0.612 after the rebuild.
This is not read as a regression: the old cross-product dataset repeated each player's
*identical* static season-aggregate feature vector across every sampled date (~60+ times),
and 5-fold CV used `shuffle=True` — so duplicate copies of the same player's feature
vector routinely landed in both the train and validation folds, letting the model
memorize a player's fingerprint → average outcome rate rather than learning anything
that generalizes to a specific day. The new dataset breaks that duplication (features
now vary game-to-game via park/pitcher/home-away context), so 0.612 is a more honest
day-level number, not a worse model.

### ML Features (26 total)
Barrel rate, exit velocity avg, hard hit %, sweet spot %, xISO, xSLG, fly ball %, launch angle, HR/FB ratio, blast rate, BallparkPal matchup grade (0-10), park HR factor, EV on $10, value edge, recent form (14d), pitcher HR/9, pitcher HR vs batter's hand, pitcher barrel %, is home, platoon, head-to-head HR, career park HR, pitcher career HR/9 vs hand, pitcher FB/breaking/offspeed mix (3), batter xSLG vs fastball/breaking/offspeed (3)

See `ml/optimize_weights.py`'s `FEATURES` list for the authoritative, current set.

### 2026-08-18 dead feature pipeline fix
Audited the full `FEATURES` list against real population rates in `pick_factors` and found ~20 of 30 features were >99% null — the model could only ever learn from the ~10 that were actually populated. Root causes, by bucket:
- **Genuine bugs (fixed):** `pitcher_fb_pct`/`pitcher_breaking_pct`/`pitcher_offspeed_pct` were computed correctly in `predictor.py` but never included in `save_pick_factors()`'s INSERT columns — computed, then thrown away. The platoon signal was gated behind `status == "confirmed"` even though the pitcher's handedness (the only input it actually needs) is resolved regardless of batter lineup-confirmation status. `_fetch_batter_pitch_splits()` requested the Savant `leaderboard/custom` endpoint without `csv=true`, got an HTML page back, and `resp.json()` failed inside a bare `except` that silently returned `{}` every time — worse, even after fixing the request format, the column names it was requesting (`xslg_fastball` etc.) don't exist on that endpoint at all; the real data lives on a separate `leaderboard/pitch-arsenal-stats` endpoint keyed by individual pitch type (FF/SL/CH/...), which now gets PA-weighted and bucketed into fastball/breaking/offspeed client-side.
- **Dead upstream field (removed):** `xhr_rate` and `bpp_hr_pct` are both 0% populated because the underlying Savant/BallparkPal fields they read from don't exist in the scraped data. `xhr_rate` was dropped from `FEATURES` entirely; `bpp_hr_pct` was replaced with `bpp_vs_grade` — a real, already-fetched BallparkPal 0–10 matchup grade that was never wired into the ML feature set.
- **By-design sparsity (left alone):** `h2h_hr`, `ev_10`/`value_edge`, `recent_form_14d`, career splits — these are legitimately sparse (small-sample gates, 12-games/day odds cap) rather than broken.

Added `tests/test_ml_features.py::test_all_features_have_a_save_pick_factors_write_path` — a regression check that greps `save_pick_factors()`'s source for `signals.get("<col>")` for every column in `FEATURES`, so a feature that's computed but never persisted can't silently reoccur. `algo_version` bumped to `4.2`. Success criteria here is the fields populating correctly going forward, not an immediate AUC jump — the retrain threshold needs ~2 weeks of newly-labeled rows with these fields non-null before it can move the needle.

---

## Star Rating / Confidence Tiers

Stars are assigned based on **rank within today's pool** combined with the **model's AUC ceiling**.

| Tier | Stars | Label | Current Rank Range |
|------|-------|-------|--------------------|
| Strong Plays | ★★★★★ | Top picks, max confidence | Unlocks when AUC ≥ 0.65 |
| Strong Plays | ★★★★☆ | Top picks | Ranks 1–5 (approx) |
| Solid Looks | ★★★☆☆ | Good value | Mid-ranks |
| Worth Watching | ★★☆☆☆ | Viable plays | Lower-mid |
| Speculative | ★☆☆☆☆ | Long shots | Bottom of pool |

*Bucket sizes fluctuate daily — there is no fixed quota per tier. It depends on how tightly players cluster in score.*

Current max is ★★★★☆ because AUC = 0.634 (just below the 0.65 threshold for 5 stars).

---

## Historical Hit Rate by Rank (all-time)

The system tracks HR hit rate by rank bucket across all labeled picks since launch.
This updates automatically as results come in each night.

---

## Model P&L Tracking

The site tracks a **fictitious $10-per-pick model portfolio** — as if $10 was bet on every top-20 pick every day, regardless of actual bets placed.

- **Wins** count only when the odds at game time are known
- **Losses** always count as −$10
- Tracks cumulative P&L, daily P&L, and ROI

*Current performance (Apr 16–19, 2026): **+$227.00 / +28.4% ROI** over 4 days.*

---

## Daily Workflow

| Time | Action |
|------|--------|
| 11am ET | System auto-runs: labels yesterday's results, refreshes 2026 training data, retrains ML if due, fetches today's picks |
| Morning | Review picks on dingershotline.com, log bets on ProphetX/Novig |
| ~11pm ET | Run record_results to capture outcomes and update model P&L |

---

## Key Design Decisions

**Why no AI in the ranking?** Early versions used Claude to rank picks from a large context, but LLM outputs aren't reproducible and hallucinations were a risk. The current system produces identical output for identical inputs — every score is fully auditable.

**Why top 20 and not just top 5?** The ML model needs to see players who *didn't* homer as well as those who did. Saving signal snapshots for all 20 daily picks (not just placed bets) eliminates selection bias in the training data.

**Why Pinnacle for EV?** Pinnacle has the sharpest lines and lowest vig in the market. Using their implied probability as the "true probability" gives the most honest EV calculation.

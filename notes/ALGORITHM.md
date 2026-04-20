# Dingers Hotline — Algorithm & Scoring Guide

*Last updated: 2026-04-19*

---

## What This Is

Dingers Hotline is an MLB home run prop prediction system. Each morning it pulls live data from multiple sources, scores every batter in confirmed lineups, and ranks the top 20 HR candidates for the day. The goal is to find value picks for $10 HR singles on ProphetX and Novig.

---

## How It Works (Big Picture)

The system is **100% deterministic Python** — no AI or language model is involved in ranking picks. Every score is computed from a formula, so you can always trace exactly why a player ranked where they did.

1. Pull confirmed lineups from MLB API
2. Fetch Statcast metrics, park factors, weather, matchup grades, and odds
3. Score every confirmed batter using a weighted formula
4. Blend in a machine learning model (logistic regression trained on historical results)
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

## ML Score Blend

After the raw score is computed, it's blended with a **logistic regression model** trained on historical pick results.

```
ml_weight = min(0.70, max(0.0, (AUC − 0.50) × 2.5))
final_score = (1 − ml_weight) × raw_score + ml_weight × ml_score
```

- At **AUC = 0.50** (random): ml_weight = 0% — pure heuristic scoring
- At **AUC = 0.634** (current): ml_weight = **33%** — model has meaningful influence
- At **AUC ≥ 0.78**: ml_weight caps at **70%**

### Current Model Status
- **AUC: 0.634** (trained on 4 days of live results + 2015–2025 historical data)
- **Training data:** 188,000+ rows of Statcast + HR event data
- **Retrains automatically** each morning when ≥200 new labeled rows accumulate

### ML Features (19 total)
Barrel rate, exit velocity avg, hard hit %, sweet spot %, xISO, xSLG, xHR rate, fly ball %, launch angle, HR/FB ratio, BallparkPal HR%, park HR factor, EV on $10, value edge, recent form (14d), pitcher HR/9, is home, platoon, head-to-head HR

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

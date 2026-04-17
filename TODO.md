# DingersHotline — Roadmap & To-Dos

Items are tracked here as features, fixes, and improvements. Priorities: 🔴 High · 🟡 Medium · 🟢 Low

---

## In Progress

| Priority | Item | Notes |
|----------|------|-------|
| 🟡 | **Model P&L tracker on dingershotline.com** | Separate tab/view showing hypothetical $10/pick daily + cumulative P&L for all top-20 model picks. Backend done (`model_pnl_report()`). Needs front-end. |

---

## Backlog

### Features

| Priority | Item | Notes |
|----------|------|-------|
| 🔴 | **Public-facing model P&L page** | Show the world how the model performs — daily win/loss + running total, separate from actual bets. Good marketing. |
| 🔴 | **launchd failure alerting** | If the 11am daily job silently fails, there's no notification. Add a failure hook that sends an alert (Telegram or email) so you don't miss a day. |
| 🟡 | **Model performance dashboard** | Surface `model_pnl_report()` + `model_performance_report()` output visually on the site (ROI, hit rate by confidence tier, rank bucket analysis). |
| 🟡 | **Confidence calibration report** | Are HIGH picks actually hitting at a higher rate than MEDIUM? Generate a monthly breakdown to validate the tier thresholds and tune them if not. |
| 🟡 | **ProphetX vs Novig line comparison** | Track which platform historically offers better value per player — could shift where bets are placed over time. |
| 🟡 | **Player trending alert** | Flag players who've ranked in the top 10 three or more consecutive days — strong signal worth highlighting before picks. |
| 🟡 | **Bankroll tracker** | Kelly Criterion assumes a fixed $200 bankroll. If your actual bankroll changes, sizing is wrong. Make it configurable or auto-tracked. |
| 🟡 | **Odds API usage tracker** | You're on a 500 req/month free tier with no warning when approaching the limit. Add a daily usage counter and alert at ~400. |
| 🟡 | **Pitch-type batter matchup scoring** | Factor in how the batter performs against the pitcher's primary pitch type. E.g. pitcher throws 65% fastballs, batter has elite FB xSLG = meaningful edge. Statcast pitch mix + batter pitch-type splits both available via Baseball Savant. New signal in `_score_player()` + new `pick_factors` column. |
| 🟡 | **Career pitcher handedness splits** | Current model only uses last 3 starts HR/9. Add career HR/9 vs LHB and vs RHB as a separate signal. Example: Dollander has a 2.05 career HR/9 vs lefties — massive edge for any LHB in that matchup that the model currently misses. MLB Stats API has career platoon splits per pitcher. |
| 🟡 | **Season-to-date tier boosting for elite hitters** | Top-tier hitters having standout seasons (e.g. Yordan Alvarez leading the league in HR/xSLG) should get a boost beyond raw Statcast signals. Consider a leaderboard bonus: top 10 in HR or xSLG league-wide gets +2 to score. Prevents the model from undervaluing proven studs with moderate day-to-day signals. |
| 🟡 | **Expected HRs vs actual HRs (luck metric)** | Calculate each player's expected HR total from Statcast signals (xHR = PA × xHR_rate, or use Savant's `xba`/`xslg` to derive expected HR pace). Compare to actual HRs hit → `luck = actual - expected`. Positive luck = overperforming (regression risk); negative = underperforming (bounce-back candidate). Feed `luck` as a signed signal into `_score_player()` — negative luck players get a boost, positive luck players get penalized. Store in `pick_factors` for ML training. |
| 🟢 | **Early-season Statcast weighting** | April data is noisy (<50 PA). Automatically down-weight barrel/xiso and up-weight BallparkPal signals when a player has thin samples. |
| 🟢 | **Pick history page** | Public archive of past daily top-20 picks with outcomes — builds credibility over time. |
| 🟢 | **"Pick of the day" highlight** | Surface the single highest-confidence pick prominently on the site — good for casual visitors and social sharing. |
| 🟢 | **Historical performance charts** | Win rate over time, ROI by month, hit rate by confidence tier — visual story of model improvement. |
| 🟢 | **Parlay suggester** | Identify two high-correlation top picks for a same-game or cross-game parlay recommendation. |

### Fixes & Technical Debt

| Priority | Item | Notes |
|----------|------|-------|
| 🔴 | **Pitchers appearing in pick pool** ⚡ TOP PRIORITY | Andrés Muñoz, Anthony Kay, Fernando Cruz, Cam Schlittler and others confirmed in pick pool on 4/16. Filter candidates by primary position (SP/RP) from MLB roster API before scoring — simple position check, high impact. |
| 🟡 | **Duplicate pick_factors rows** | `pick_factors` table has no UNIQUE constraint on existing DB rows (schema has it, but old table predates it). Re-running `daily_picks.py` on same day creates duplicates. Fix: `CREATE UNIQUE INDEX IF NOT EXISTS`. |
| 🟡 | **Odds signals not always populating** | `pinnacle_odds`, `ev_10`, `best_odds` are NULL for some days — odds API may return no props for certain games. Add logging to surface when this happens. |
| 🟢 | **Aaron Judge missing from 4/15 pick_factors** | One-off gap — Judge wasn't saved despite being a bet that day. Investigate if the save loop silently threw on certain players. |

---

## Completed

| Item | Date | Notes |
|------|------|-------|
| `best_odds` stored in `pick_factors` | 2026-04-16 | Now saves best available line per player for model P&L tracking. |
| `model_pnl_report()` function | 2026-04-16 | Hypothetical $10/pick P&L tracker, fully separate from actual bets. |
| `score` and `rank` saving to DB | 2026-04-16 | Was NULL for 4/15 (old code), fixed in v3.0 — working from 4/16 onward. |
| ML self-improving pipeline | 2026-04-12 | Auto-labels results, refreshes 2026 data, retrains weights each morning. |
| Roster fallback for early picks | — | Unconfirmed batters added with −2 penalty when lineups not yet posted. |
| Six mathematical enhancements | — | EV, Kelly, platoon edge, pitcher form, H2H, home/away splits. |

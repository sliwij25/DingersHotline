# DingersHotline — Roadmap & To-Dos

Items are tracked here as features, fixes, and improvements. Priorities: 🔴 High · 🟡 Medium · 🟢 Low

---

## In Progress

| Priority | Item | Notes |
|----------|------|-------|
| 🟡 | **Model P&L tracker on dingershotline.com** | Separate tab/view showing hypothetical $10/pick daily + cumulative P&L for all top-20 model picks. Backend done (`model_pnl_report()`). Needs front-end. UI: calendar view showing daily P&L for each day of the current month + monthly total; prev/next month navigation to browse historical months. |

---

## Backlog

### Features

| Priority | Item | Notes |
|----------|------|-------|
| 🔴 | **Public-facing model P&L page** | Show the world how the model performs — daily win/loss + running total, separate from actual bets. Good marketing. |
| 🔴 | **launchd failure alerting** | If the 11am daily job silently fails, there's no notification. Add a failure hook that sends an alert (Telegram or email) so you don't miss a day. |
| 🟡 | **Model performance dashboard** | Surface `model_pnl_report()` + `model_performance_report()` output visually on the site (ROI, hit rate by confidence tier, rank bucket analysis). |
| 🟡 | **Confidence calibration report** | Are HIGH picks actually hitting at a higher rate than MEDIUM? Generate a monthly breakdown to validate the tier thresholds and tune them if not. |
| 🟡 | **Tier performance tracking** | Track hit rate per confidence tier (HIGH / MEDIUM / LOW) in `pick_factors`. Surface as "Strong Plays: 15% HR rate (n=42)" — available via `bets.py stats` and optionally on the site dashboard. Query: `SELECT confidence, COUNT(*) as n, SUM(homered) as hits, ROUND(100.0*SUM(homered)/COUNT(*),1) as hit_pct FROM pick_factors WHERE homered IS NOT NULL GROUP BY confidence ORDER BY hit_pct DESC`. |
| 🟡 | **ProphetX vs Novig line comparison** | Track which platform historically offers better value per player — could shift where bets are placed over time. |
| 🟡 | **Player trending alert** | Flag players who've ranked in the top 10 three or more consecutive days — strong signal worth highlighting before picks. |
| 🟡 | **Bankroll tracker** | Kelly Criterion assumes a fixed $200 bankroll. If your actual bankroll changes, sizing is wrong. Make it configurable or auto-tracked. |
| 🟡 | **Odds API usage tracker** | You're on a 500 req/month free tier with no warning when approaching the limit. Add a daily usage counter and alert at ~400. |
| 🟡 | **Pitch-type batter matchup scoring** | Factor in how the batter performs against the pitcher's primary pitch type. E.g. pitcher throws 65% fastballs, batter has elite FB xSLG = meaningful edge. Statcast pitch mix + batter pitch-type splits both available via Baseball Savant. New signal in `_score_player()` + new `pick_factors` column. |
| 🟡 | **Pull tendency × ballpark wall depth matching** | If a pull-side field wall is short and the batter is a strong pull hitter, that's an independent HR edge. E.g. right-handed pull hitter at Yankee Stadium (short LF porch). **Data sources:** Statcast `pull_percent` from the batter leaderboard CSV (already fetched daily); directional HR counts available via Savant spray chart API. Stadium wall depths need a hand-built lookup dict (similar to `_DOME_STADIUMS`). Score boost when pull% aligns with the short side. |
| 🟡 | **Pitch-mix × batter pitch-type preference** | Extend pitch-type matchup: if the pitcher is fastball-heavy (>60% usage) and the batter has elite xSLG or HR rate on fastballs, apply a boost. Conversely, pitcher throws heavy breaking balls and batter struggles against off-speed → penalty. **Data sources:** Pitcher pitch mix from Statcast pitcher leaderboard CSV (already fetched); batter pitch-type splits (xSLG/HR by pitch type) available via Savant pitch-type leaderboard — separate CSV endpoint, not yet fetched. |
| 🟡 | **Career pitcher handedness splits** | Current model only uses last 3 starts HR/9. Add career HR/9 vs LHB and vs RHB as a separate signal. Example: Dollander has a 2.05 career HR/9 vs lefties — massive edge for any LHB in that matchup that the model currently misses. MLB Stats API has career platoon splits per pitcher. |
| 🟡 | **Season-to-date tier boosting for elite hitters** | Top-tier hitters having standout seasons (e.g. Yordan Alvarez leading the league in HR/xSLG) should get a boost beyond raw Statcast signals. Consider a leaderboard bonus: top 10 in HR or xSLG league-wide gets +2 to score. Prevents the model from undervaluing proven studs with moderate day-to-day signals. |
| 🟡 | **Expected HRs vs actual HRs (luck metric)** | Calculate each player's expected HR total from Statcast signals (xHR = PA × xHR_rate, or use Savant's `xba`/`xslg` to derive expected HR pace). Compare to actual HRs hit → `luck = actual - expected`. Positive luck = overperforming (regression risk); negative = underperforming (bounce-back candidate). Feed `luck` as a signed signal into `_score_player()` — negative luck players get a boost, positive luck players get penalized. Store in `pick_factors` for ML training. |
| 🟡 | **Integrate Blast into HR model** | Statcast bat-tracking metric: a swing is a "Blast" when `(percent_squared_up × 100) + bat_speed ≥ 164`. Only ~7% of swings qualify; extremely high correlation with HR/power outcomes. Available on Baseball Savant bat-tracking leaderboard (2023–present). Add `blast_rate` as a new signal in `_score_player()` and `pick_factors`. Source: [MLB Glossary — Blasts](https://www.mlb.com/glossary/statcast/bat-tracking-blasts) |
| 🟢 | **Early-season Statcast weighting** | April data is noisy (<50 PA). Automatically down-weight barrel/xiso and up-weight BallparkPal signals when a player has thin samples. |
| 🟢 | **Pick history page** | Public archive of past daily top-20 picks with outcomes — builds credibility over time. |
| 🟢 | **"Pick of the day" highlight** | Surface the single highest-confidence pick prominently on the site — good for casual visitors and social sharing. |
| 🟢 | **Historical performance charts** | Win rate over time, ROI by month, hit rate by confidence tier — visual story of model improvement. |
| 🟡 | **"UPDATED" label in Telegram when picks re-sent same day** | When `daily_picks.py` runs more than once on the same date, the Telegram notification caption should include the word "UPDATED" so subscribers know to refresh. Detect by checking if a picks file or pick_factors rows already exist for today before sending. |
| 🟢 | **Parlay suggester** | Identify two high-correlation top picks for a same-game or cross-game parlay recommendation. |
| 🟢 | **Player card deep-dive** | Clicking a player card on the site opens an expanded view with full signal breakdown — Statcast splits, platoon edge, park factors, odds across all books, H2H history, recent form chart. |

### Fixes & Technical Debt

| Priority | Item | Notes |
|----------|------|-------|
| 🔴 | **Fix wind direction / weather signal** | Our wind data differs from BallparkPal's wind patterns — BPP is trusted as the more accurate source. Mismatched wind signals could be negatively influencing model scoring. Audit what wind data we fetch (OpenWeatherMap direction/speed) vs what BPP shows, identify the discrepancy (bearing convention, stadium orientation, or API accuracy), and align our wind scoring to match BPP or simply defer to BPP's wind grade entirely. |
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
| Pitcher filtering from pick pool | 2026-04-18 | Position check (type/abbreviation/code) in both confirmed lineup and roster fallback paths. |
| Blast rate integration | 2026-04-18 | Bat-tracking leaderboard fetched in parallel, scored in `_score_player()`, saved to `pick_factors`, added to ML features. |
| Duplicate pick_factors rows fix | 2026-04-19 | `UNIQUE(bet_date, player)` constraint + `CREATE UNIQUE INDEX` both present on table. |
| Odds signals logging | 2026-04-19 | Added `[ODDS]` log lines for missing ev_10, missing pinnacle, unmatched players, and zero-match warnings. |

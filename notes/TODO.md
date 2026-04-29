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
| 🟡 | **Model performance dashboard** | Surface `model_pnl_report()` + `model_performance_report()` output visually on the site (ROI, hit rate by confidence tier, rank bucket analysis). |
| 🟡 | **Confidence calibration report** | Are HIGH picks actually hitting at a higher rate than MEDIUM? Generate a monthly breakdown to validate the tier thresholds and tune them if not. |
| 🟡 | **ProphetX vs Novig line comparison** | Track which platform historically offers better value per player — could shift where bets are placed over time. |
| 🟡 | **Bankroll tracker** | Kelly Criterion assumes a fixed $200 bankroll. If your actual bankroll changes, sizing is wrong. Make it configurable or auto-tracked. |
| 🟡 | **Odds API usage tracker** | You're on a 500 req/month free tier with no warning when approaching the limit. Add a daily usage counter and alert at ~400. |
| 🟡 | **Pull tendency × ballpark wall depth matching** | If a pull-side field wall is short and the batter is a strong pull hitter, that's an independent HR edge. E.g. right-handed pull hitter at Yankee Stadium (short LF porch). **Data sources:** Statcast `pull_percent` from the batter leaderboard CSV (already fetched daily); directional HR counts available via Savant spray chart API. Stadium wall depths need a hand-built lookup dict (similar to `_DOME_STADIUMS`). Score boost when pull% aligns with the short side. |
| 🟡 | **Pitch-type scoring Phase 2 — batter splits** | Phase 1 (pitcher mix) done. Phase 2: fetch batter xSLG/HR rate vs fastball/breaking/offspeed from Savant pitch-type leaderboard (separate CSV endpoint). Match batter's weakness/strength to pitcher's dominant pitch for a batter-specific boost/penalty. New signal in `_score_player()` + new `pick_factors` columns. Spec: `docs/superpowers/specs/2026-04-19-pitch-type-scoring-design.md`. |
| 🟡 | **Career pitcher handedness splits** | Current model only uses last 3 starts HR/9. Add career HR/9 vs LHB and vs RHB as a separate signal. Example: Dollander has a 2.05 career HR/9 vs lefties — massive edge for any LHB in that matchup that the model currently misses. MLB Stats API has career platoon splits per pitcher. |
| 🟡 | **Season-to-date tier boosting for elite hitters** | Top-tier hitters having standout seasons (e.g. Yordan Alvarez leading the league in HR/xSLG) should get a boost beyond raw Statcast signals. Consider a leaderboard bonus: top 10 in HR or xSLG league-wide gets +2 to score. Prevents the model from undervaluing proven studs with moderate day-to-day signals. |
| 🟡 | **Integrate Blast into HR model** | Statcast bat-tracking metric: a swing is a "Blast" when `(percent_squared_up × 100) + bat_speed ≥ 164`. Only ~7% of swings qualify; extremely high correlation with HR/power outcomes. Available on Baseball Savant bat-tracking leaderboard (2023–present). Add `blast_rate` as a new signal in `_score_player()` and `pick_factors`. Source: [MLB Glossary — Blasts](https://www.mlb.com/glossary/statcast/bat-tracking-blasts) |
| 🟢 | **Welcome DM to new Telegram subscribers** | When a new user joins the Dingers Hotline Telegram channel, send them a personalized welcome message introducing the model and how to use the picks. |
| 🟢 | **Pick history page** | Public archive of past daily top-20 picks with outcomes — builds credibility over time. |
| 🟢 | **"Pick of the day" highlight** | Surface the single highest-confidence pick prominently on the site — good for casual visitors and social sharing. |
| 🟢 | **Historical performance charts** | Win rate over time, ROI by month, hit rate by confidence tier — visual story of model improvement. |
| 🟢 | **Parlay suggester** | Identify two high-correlation top picks for a same-game or cross-game parlay recommendation. |
| 🟢 | **Player card deep-dive** | Clicking a player card on the site opens an expanded view with full signal breakdown — Statcast splits, platoon edge, park factors, odds across all books, H2H history, recent form chart. |
| 🟢 | **Season HR leaderboard on site** | Show a ranked top-20 hitters by season HR total — informational context for visitors, not tied to picks. |
| 🟡 | **Full pipeline automation** | Four parts: (1) launchd triggers daily picks each morning without any Claude session; (2) site auto-refreshes picks throughout the day as lineups confirm — if Ohtani is scratched he falls off the top 20 in real time; (3) players whose games have already started are locked into the top 20 so they don't skew results by disappearing mid-day; (4) after games end, results + P&L are calculated automatically with no manual step. |

### Planned (Not Yet Implemented)

| Priority | Item | Notes |
|----------|------|-------|
| 🟡 | **5-star rating unlock (AUC ≥ 0.65)** | When AUC crosses 0.65, expand percentile cutpoints to 5 tiers. In `Homer._load_score_percentiles()`, the `max_stars=5` branch already defines cutpoints `[(92, 5), (78, 4), (62, 3), (45, 2)]` — verify those thresholds make sense against the score distribution at that time, then update GRADING.md star meanings to reflect the new ★★★★★ tier. Also update the tier performance section headers in `daily_picks.py` which currently show raw HR-rate data per tier. Do NOT implement early — the model needs to earn it. |

---

### Fixes & Technical Debt

| Priority | Item | Notes |
|----------|------|-------|

---



## Completed

| Item | Date | Notes |
|------|------|-------|
| Early-season Statcast weighting | 2026-04-29 | PA tiers ≥50/30/15/<15 → pa_scale 1.0/0.6/0.25/0.0; bpp_boost 1.0/1.3/1.5/1.6 amplifies BPP matchup grade to compensate when Statcast is down-weighted. |
| Double-header handling | 2026-04-29 | Composite key {name}\|\|{game_pk} in player_signals; G1/G2 labels in output; name-only odds/blast index; UNIQUE(bet_date, player, game_pk) in pick_factors with auto-rebuild migration; 12 tests. |
| `best_odds` stored in `pick_factors` | 2026-04-16 | Now saves best available line per player for model P&L tracking. |
| `model_pnl_report()` function | 2026-04-16 | Hypothetical $10/pick P&L tracker, fully separate from actual bets. |
| `score` and `rank` saving to DB | 2026-04-16 | Was NULL for 4/15 (old code), fixed in v3.0 — working from 4/16 onward. |
| ML self-improving pipeline | 2026-04-12 | Auto-labels results, refreshes 2026 data, retrains weights each morning. |
| Roster fallback for early picks | — | Unconfirmed batters added with −2 penalty when lineups not yet posted. |
| Six mathematical enhancements | — | EV, Kelly, platoon edge, pitcher form, H2H, home/away splits. |
| Pitcher filtering from pick pool | 2026-04-18 | Position check (type/abbreviation/code) in both confirmed lineup and roster fallback paths. |
| Pitcher barrel rate allowed | 2026-04-22 | Strips park/luck from pitcher vulnerability — stronger HR predictor than HR/9. Scored in `_score_player()`, saved to `pick_factors`, in ML features. |
| Blast rate integration | 2026-04-18 | Bat-tracking leaderboard fetched in parallel, scored in `_score_player()`, saved to `pick_factors`, added to ML features. |
| Duplicate pick_factors rows fix | 2026-04-19 | `UNIQUE(bet_date, player)` constraint + `CREATE UNIQUE INDEX` both present on table. |
| Odds signals logging | 2026-04-19 | Added `[ODDS]` log lines for missing ev_10, missing pinnacle, unmatched players, and zero-match warnings. |
| "UPDATED" label in Telegram on re-runs | 2026-04-20 | Caption prefixed with `🔄 UPDATED —` when `pick_factors` already has rows for today. |
| Pitch-type scoring Phase 1 — pitcher mix | 2026-04-23 | Directional scoring based on pitcher's FB/breaking/offspeed usage. +1/+2 FB-heavy, -1/-2 breaking-heavy, -1 offspeed-heavy. 75–86% coverage. 9 tests. |
| Player trending alert | 2026-04-24 | TRENDING section in terminal output — flags players in top 10 for 3+ consecutive days with streak length and rank history. |
| Expected HRs vs actual (luck metric) | 2026-04-24 | `hr_luck = actual_HR - PA × (xhr_rate/100)`. Scored in `_score_player()`: ≤-4 = +2.0, ≤-2 = +1.0, ≥+2 = -1.0, etc. Saved to `pick_factors`, in ML features. |
| Aaron Judge missing 4/15 pick_factors | 2026-04-24 | Non-issue — 4/15 predates v3.0 live tracking. Old code saved 40 NULL-rank rows. Judge appears correctly every day from 4/16 onward. |
| Odds as lineup confirmation proxy + remove early-game bias | 2026-04-24 | If player has HR prop odds, no status penalty (books don't post props for scratched players). Removes systematic disadvantage for late-game players. Also fixed: `picks_{TODAY}.txt` now written on every run so lock source and DB always reflect the most recent run. |
| Track record by star rating | 2026-04-20 | P&L chip per tier in section headers; green/red badge next to HR rate badge. |
| Fix wind + add altitude/humidity/pressure/carry | 2026-04-20 | Removed blind mph penalty; BPP weather_hr_factor as primary wind signal; carry_ft scored; 4 new pick_factors columns. |
| Tier performance tracking (HIGH/MEDIUM/LOW) | 2026-04-20 | Already in model_performance_report() CONFIDENCE CALIBRATION section, printed daily. |
| launchd failure alerting | 2026-04-20 | run-picks.sh sends personal Telegram DM on non-zero exit with last 10 lines of error log. Plist updated to call run-picks.sh. |

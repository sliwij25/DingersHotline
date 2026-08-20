# DingersHotline — Roadmap & To-Dos

Items are tracked here as features, fixes, and improvements. Priorities: 🔴 High · 🟡 Medium · 🟢 Low

---

## Backlog

### Features

| Priority | Item | Notes |
|----------|------|-------|
| 🟡 | **Model performance dashboard** | Surface `model_pnl_report()` + `model_performance_report()` output visually on the site (ROI, hit rate by confidence tier, rank bucket analysis). |
| 🟢 | **Welcome DM to new Telegram subscribers** | When a new user joins the Dingers Hotline Telegram channel, send them a personalized welcome message introducing the model and how to use the picks. |
| 🟢 | **Historical performance charts** | Win rate over time, ROI by month, hit rate by confidence tier — visual story of model improvement. |
| 🟢 | **Parlay suggester** | Identify two high-correlation top picks for a same-game or cross-game parlay recommendation. |
| 🟡 | **Full pipeline automation** | Four parts: (1) launchd triggers daily picks each morning without any Claude session; (2) site auto-refreshes picks throughout the day as lineups confirm — if Ohtani is scratched he falls off the top 20 in real time; (3) players whose games have already started are locked into the top 20 so they don't skew results by disappearing mid-day; (4) after games end, results + P&L are calculated automatically with no manual step. |
| 🟡 | **Team HR picks page** | Page where you select a team and see their top 3–5 HR picks for the day (exact count TBD, 3–5 is the comfortable range). Goes deeper than the top-15 — more signal detail per player, team-specific context. Useful for fans betting on a specific game rather than the full slate. |

### Planned (Not Yet Implemented)

| Priority | Item | Notes |
|----------|------|-------|

---

### Fixes & Technical Debt

| Priority | Item | Notes |
|----------|------|-------|

---



## Completed

| Item | Date | Notes |
|------|------|-------|
| Pull% standalone scoring + park-context bonus | 2026-04-29 | `pull_pct` scored independently (+2 ≥52%, +1 ≥44%, -1 <32%) in addition to existing pull×short-porch park context bonus. |
| Max exit velocity scoring | 2026-04-29 | `ev_max` (max_hit_speed from Savant) added to batter CSV fetch and scored in `_score_player()`: +3 ≥115mph, +2 ≥112, +1 ≥109, -1 <104. Peak power ceiling independent of average EV. |
| Derived HR/FB rate | 2026-04-29 | When Savant `hr_flyballs_rate_batter` is empty (early season), compute from season_hr ÷ (pa × fb_pct/100). Makes HR/FB sustainability check functional all season. |
| Launch angle penalty steepened | 2026-04-29 | <10° now -4 (was -1), 10–14° now -2 (was -1), 15° neutral. Prevents ground-ball hitters with elite barrel/hard-hit from ranking too high. |
| Minimum PA gate | 2026-04-29 | Players with known PA < 50 excluded from top-20 pool entirely. Prevents tiny-sample Statcast inflation from obscure/newly-called-up players. |
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
| Season HR leaderboard on site | 2026-04-30 | `docs/leaderboard.html` — ranked top-20 hitters by season HR with Statcast metrics, color-coded cells, auto-generated by `tools/generate_html.py`. |
| Pick of the Day page | 2026-04-30 | `docs/pick-of-the-day.html` — standalone page for top model pick with full signal breakdown, EV strip, score breakdown, contact quality, pitcher analysis, park context, historical splits, odds table. |
| Player card deep-dive page | 2026-04-30 | `docs/player-card.html` — standalone deep-dive for any player: hero header, recent form calendar, all signal sections, odds table, career park HR, pitch-type splits. |
| Pitch-type scoring Phase 2 — batter splits | 2026-04-30 | `batter_xslg_vs_fastball/breaking/offspeed` fetched from Savant leaderboard; scored only when pitcher has a dominant pitch (≥50%) — elite batter vs dominant pitch ±1/+2; in ML features + pick_factors. 19 tests. |
| Career pitcher handedness splits (`pitcher_career_hr_vs_hand`) | 2026-04-30 | Explicit ML feature alongside existing `pitcher_hr_vs_hand`; `_fetch_pitcher_career_splits_batch()` batch function; ≥1.5→+2, ≥1.0→+1, ≤0.25→-1. In ML features + pick_factors. |
| Pull tendency Phase 2 — HR spray profiles | 2026-06-09 | _fetch_hr_spray_profiles_batch() fetches actual HR direction (hc_x/hc_y) from Savant. Scoring now uses hr_pull_pct + hr_oppo_pct for park alignment — catches oppo-field HR hitters like Judge at short-porch parks. Falls back to pull_pct when <8 HRs. |
| Confidence calibration report | 2026-06-09 | Monthly breakdown added to model_performance_report() — shows HIGH/MEDIUM/LOW hit rates per month with small-sample warnings. |
| Wire Pick of Day + Player Card to generator | 2026-06-09 | Both pages live at dingershotline.com, fed by real daily pick data via player-data.json. |
| 5-star rating unlock | 2026-06-09 | AUC hit 0.701 (≥0.65 threshold). 5 tiers across top-15: #1–3=★★★★★, #4–6=★★★★☆, #7–9=★★★☆☆, #10–12=★★☆☆☆, #13–15=★☆☆☆☆. |
| Public-facing model P&L page | 2026-06-09 | Live at dingershotline.com/hit-rate — daily win/loss + cumulative P&L, calendar view, month navigation. |
| Season-to-date elite hitter boost (HR + xSLG top-10) | 2026-04-30 | Extended to boost players who are top-10 in xSLG in addition to HR. `_compute_elite_boost_thresholds()` extracted as testable static method. |

# Pitch-Type Batter Matchup Scoring — Design Spec

**Date:** 2026-04-19  
**Scope:** Phase 1 — pitcher pitch mix directional scoring  
**Status:** Approved, ready for implementation

---

## Overview

Add a directional scoring signal based on the starting pitcher's pitch arsenal. Fastball-heavy pitchers favor HR outcomes; breaking-ball and offspeed-heavy pitchers suppress them. All three pitch-type buckets score independently.

This is Phase 1 of pitch-type matchup scoring. Phase 2 (batter pitch-type splits — how a specific batter hits fastballs vs breaking balls) is a separate future spec.

---

## Data Layer

**File:** `agents/predictor.py` — `_fetch_pitchers()`

Extend the existing pitcher Statcast leaderboard selections string to include pitch mix percentages:

```python
"hr_flyball_rate,fb_percent,xfip,hard_hit_percent,barrel_batted_rate,"
"n_ff_formatted,n_si_formatted,n_fc_formatted,"   # fastball family
"n_sl_formatted,n_cu_formatted,n_sw_formatted,"   # breaking family
"n_ch_formatted,n_fs_formatted"                   # offspeed family
```

**No new HTTP call or cache file.** Piggybacks on the existing `statcast_pitcher_YYYY-MM-DD.csv` that is already fetched and cached daily.

### Pitch Bucket Derivation

Computed in `_build_game_cards()` after pitcher stats lookup:

| Bucket | Fields summed |
|--------|--------------|
| `pitcher_fb_pct` | `n_ff_formatted` + `n_si_formatted` + `n_fc_formatted` |
| `pitcher_breaking_pct` | `n_sl_formatted` + `n_cu_formatted` + `n_sw_formatted` |
| `pitcher_offspeed_pct` | `n_ch_formatted` + `n_fs_formatted` |

Values are percentages (0–100). Stored in `player_signals` per batter, keyed to the batter's starting pitcher.

---

## Scoring Logic

**File:** `agents/predictor.py` — `_score_player()`

New block inserted after the existing pitcher HR/9 section:

```python
# Pitcher pitch mix (directional — fastball favors HR, breaking/offspeed suppresses)
fb_pct       = sig.get("pitcher_fb_pct")
breaking_pct = sig.get("pitcher_breaking_pct")
offspeed_pct = sig.get("pitcher_offspeed_pct")

if fb_pct is not None:
    if fb_pct >= 60:   score += 2
    elif fb_pct >= 50: score += 1

if breaking_pct is not None:
    if breaking_pct >= 35: score -= 2
    elif breaking_pct >= 25: score -= 1

if offspeed_pct is not None:
    if offspeed_pct >= 20: score -= 1
```

### Score Range

| Scenario | Delta |
|----------|-------|
| Heavy fastball pitcher (FB% ≥60) | +2 |
| Fastball-leaning pitcher (FB% ≥50) | +1 |
| Breaking-ball dominant (Breaking% ≥35) | −2 |
| Breaking-ball leaning (Breaking% ≥25) | −1 |
| Heavy offspeed (Offspeed% ≥20) | −1 |
| Typical mixed arsenal (~45/30/15) | 0 |
| Worst case (breaking-dominant + heavy offspeed) | −3 |

A neutral/mixed arsenal scores 0 — no distortion for average pitchers.

---

## Storage & ML

**File:** `agents/bet_tracker.py` — `_MIGRATION_COLUMNS`

Three new columns added via the existing safe migration pattern:

```python
("pitcher_fb_pct",       "REAL"),
("pitcher_breaking_pct", "REAL"),
("pitcher_offspeed_pct", "REAL"),
```

`ALTER TABLE ADD COLUMN IF NOT EXISTS` runs automatically on next startup — no manual migration needed.

**File:** `ml/optimize_weights.py` — `FEATURES` list

All three columns added as ML features so logistic regression can learn better weights once labeled data accumulates.

---

## What Is NOT In Scope (Phase 1)

- Batter pitch-type splits (xSLG/HR rate vs fastball, breaking, offspeed) — Phase 2
- Pitch-mix × batter preference matching (e.g. fastball-crusher facing FB-heavy pitcher) — Phase 2
- Count-specific pitch usage (what does the pitcher throw 0-2 vs 3-1) — future

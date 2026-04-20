# Doubleheader Support Design

**Date:** 2026-04-20  
**Status:** Approved

---

## Problem

`player_signals` is keyed by bare player name. When a team plays two games on the same day (doubleheader), `_build_game_cards` processes Game 1 then Game 2. The second game's signal dict overwrites the first for every shared player — silently discarding the first game's pitcher, platoon edge, park factor, and EV context. The player is scored once, against the wrong game's data.

---

## Decision

Surface both games as independent picks, labeled `[DH G1]` / `[DH G2]`. Each game is a separate betting opportunity with its own pitcher, odds, and EV. The user decides whether to bet one or both.

---

## Architecture

### 1. Composite key for `player_signals`

Replace `player_signals[batter_name]` with `player_signals[f"{batter_name}||{game_pk}"]` throughout `_build_game_cards`.

Each signal dict gains two new fields:

| Field | Type | Description |
|-------|------|-------------|
| `game_pk` | `int` | MLB API game ID |
| `game_label` | `str \| None` | `"G1"` / `"G2"` for doubleheaders, `None` for normal games |

**G1/G2 assignment:** Before the main game loop in `_build_game_cards`, build a per-team game index:

```python
from collections import defaultdict
team_game_order: dict[str, list[str]] = defaultdict(list)
for game in games:
    gtime = game.get("game_time", "")
    gpk   = str(game.get("game_pk", ""))
    for side in ("away", "home"):
        team = game.get(side, {}).get("team", "")
        team_game_order[team].append((gtime, gpk))

# Sort each team's games by start time, assign G1/G2
team_game_label: dict[tuple[str, str], str | None] = {}
for team, entries in team_game_order.items():
    entries.sort()
    is_dh = len(entries) > 1
    for i, (_, gpk) in enumerate(entries):
        team_game_label[(team, gpk)] = f"G{i+1}" if is_dh else None
```

### 2. `_rank_picks_python`

No structural changes. Iterating `player_signals.items()` now yields two entries for doubleheader players naturally. Both compete in the ranked output.

**Output label:** When `game_label` is set, append it to the pick display:

```
#1  Aaron Judge  [DH G1]  PLATOON+  barrel=18.2% ...
#3  Aaron Judge  [DH G2]  platoon-  barrel=18.2% ...
```

### 3. Odds merging — name-only index

The current `normed_signals = {_norm(k): k for k in player_signals}` normalizes the full composite key, breaking fuzzy matching. Replace with a name-only index that maps to a list of composite keys (handles doubleheader players appearing twice):

```python
name_to_keys: dict[str, list[str]] = defaultdict(list)
for ck in player_signals:
    name_part = ck.split("||")[0]
    name_to_keys[_norm(name_part)].append(ck)
```

**3-tier matching hierarchy:**

1. **Exact normalized** — `_norm(pname) in name_to_keys`
2. **Token intersection** — every space-separated token in `_norm(pname)` appears in the candidate key (handles accent variants without false positives from shared last names like "Jose Ramirez" vs "Harold Ramirez")
3. **SequenceMatcher ≥ 0.90** (tightened from 0.85) — fallback only; prints a warning so false matches surface in logs

On match, write odds into **all** composite keys for that player (both DH games get the same odds object — or, if the odds API returns two separate events, each game's odds are matched to the correct composite key by cross-referencing game time).

Same fix applied to the blast rate merging block.

### 4. `pick_factors` table — schema migration

Add column via the existing `_MIGRATION_COLUMNS` mechanism in `bet_tracker.py`:

```python
("game_pk", "TEXT DEFAULT NULL"),
```

`save_pick_factors` gains a `game_pk: str | None = None` parameter. The unique constraint becomes `(bet_date, player, game_pk)` so both DH games get their own row.

### 5. `_add_roster_fallback`

This function also writes into `player_signals` by bare name. Update to use composite key `f"{player_name}||{game_pk}"`, passing `game_pk` from its caller context.

---

## What Does NOT Change

- `fetch_confirmed_lineups` — already returns `game_pk` per game; no changes needed
- `fetch_odds_comparison` — unchanged; odds merging is handled in the signal merge step
- `_score_player` — operates on a single signal dict; composite keying is transparent to it
- Star rating, confidence thresholds, ML blend — unchanged

---

## Error Handling

- If `game_pk` is missing from a game entry (shouldn't happen but possible): fall back to bare name key and log a warning — existing behavior preserved
- If a player appears in a doubleheader but only one game has confirmed lineups: confirmed game ranks normally, roster-fallback game takes the −2 penalty as usual

---

## Success Criteria

- On a non-doubleheader day: output identical to current behavior
- On a doubleheader day: players in both games appear twice in ranked output, labeled `[DH G1]` / `[DH G2]` with correct pitcher/venue/platoon for each game
- No false positive odds matches from shared last names
- Both DH games saved as separate rows in `pick_factors`

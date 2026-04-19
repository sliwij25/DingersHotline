# Pitch-Type Pitcher Mix Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a directional scoring signal based on pitcher pitch-type mix — fastball-heavy pitchers boost HR scores, breaking-ball and offspeed-heavy pitchers penalize them.

**Architecture:** Extend the existing pitcher Statcast CSV fetch with 8 pitch-usage columns, derive three bucket values (fb_pct, breaking_pct, offspeed_pct) per pitcher in `_build_game_cards()`, score them in `_score_player()`, persist them via `_MIGRATION_COLUMNS`, and add them to the ML feature list.

**Tech Stack:** Python, SQLite, Baseball Savant CSV leaderboard, pytest

---

### Task 1: Fetch pitch mix data

**Files:**
- Modify: `agents/predictor.py:1888-1892` (`_fetch_pitchers()`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_pitch_mix.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.predictor import Homer

def test_fetch_pitchers_includes_pitch_mix():
    """Pitcher CSV should include at least one pitch-mix field for a known pitcher."""
    homer = Homer()
    stats = homer._fetch_full_statcast(
        "pitcher",
        "hr_flyball_rate,fb_percent,xfip,hard_hit_percent,barrel_batted_rate,"
        "n_ff_formatted,n_si_formatted,n_fc_formatted,"
        "n_sl_formatted,n_cu_formatted,n_sw_formatted,"
        "n_ch_formatted,n_fs_formatted"
    )
    assert stats, "Pitcher stats dict should not be empty"
    # At least one pitcher should have a non-empty n_ff_formatted value
    pitchers_with_ff = [
        name for name, row in stats.items()
        if row.get("n_ff_formatted") not in (None, "")
    ]
    assert len(pitchers_with_ff) > 0, "Expected at least one pitcher with 4-seam fastball data"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/joesliwinski/AIProjects/DingersHotline
python -m pytest tests/test_pitch_mix.py::test_fetch_pitchers_includes_pitch_mix -v
```

Expected: FAIL — `n_ff_formatted` column missing because `_fetch_pitchers()` doesn't request it yet.

- [ ] **Step 3: Extend `_fetch_pitchers()` selections**

In `agents/predictor.py`, find the `_fetch_pitchers()` inner function (around line 1888) and update the selections string:

```python
def _fetch_pitchers():
    return self._fetch_full_statcast(
        "pitcher",
        "hr_flyball_rate,fb_percent,xfip,hard_hit_percent,barrel_batted_rate,"
        "n_ff_formatted,n_si_formatted,n_fc_formatted,"
        "n_sl_formatted,n_cu_formatted,n_sw_formatted,"
        "n_ch_formatted,n_fs_formatted"
    )
```

- [ ] **Step 4: Delete today's pitcher cache so the new columns are fetched**

```bash
rm -f /Users/joesliwinski/AIProjects/DingersHotline/cache/statcast_pitcher_$(date +%Y-%m-%d).csv
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/test_pitch_mix.py::test_fetch_pitchers_includes_pitch_mix -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agents/predictor.py tests/test_pitch_mix.py
git commit -m "feat: extend pitcher statcast fetch with pitch-mix columns (n_ff, n_sl, n_ch, etc.)"
```

---

### Task 2: Compute pitch buckets in `_build_game_cards()`

**Files:**
- Modify: `agents/predictor.py:1709-1714` (pitcher stats block in `_build_game_cards()`)
- Modify: `agents/predictor.py:1821` (player_signals dict in `_build_game_cards()`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pitch_mix.py`:

```python
from agents.predictor import _safe_float

def test_pitch_bucket_derivation():
    """Pitch bucket sums should correctly aggregate pitch-family percentages."""
    sp_data = {
        "n_ff_formatted": "50.0",
        "n_si_formatted": "10.0",
        "n_fc_formatted": "5.0",
        "n_sl_formatted": "20.0",
        "n_cu_formatted": "8.0",
        "n_sw_formatted": "0.0",
        "n_ch_formatted": "7.0",
        "n_fs_formatted": "0.0",
    }

    def _bucket(fields):
        return round(sum(
            (_safe_float(sp_data.get(f)) or 0.0) for f in fields
        ), 1)

    fb_pct       = _bucket(["n_ff_formatted", "n_si_formatted", "n_fc_formatted"])
    breaking_pct = _bucket(["n_sl_formatted", "n_cu_formatted", "n_sw_formatted"])
    offspeed_pct = _bucket(["n_ch_formatted", "n_fs_formatted"])

    assert fb_pct == 65.0
    assert breaking_pct == 28.0
    assert offspeed_pct == 7.0
```

- [ ] **Step 2: Run test to verify it passes immediately**

```bash
python -m pytest tests/test_pitch_mix.py::test_pitch_bucket_derivation -v
```

Expected: PASS — this validates our bucket math before wiring it into `_build_game_cards()`.

- [ ] **Step 3: Add pitch bucket computation after pitcher stats lookup (line ~1714)**

In `agents/predictor.py`, find the pitcher stats block in `_build_game_cards()` (around line 1709) and add bucket computation after the existing `p_xfip` line:

```python
                # Statcast pitcher season stats
                sp_key  = sp.lower()
                sp_data = _find_best_name_match(sp, pitcher_stats)
                p_hr_fb  = sp_data.get("hr_flyball_rate") or "—"
                p_fb_pct = sp_data.get("fb_percent") or "—"
                p_xfip   = sp_data.get("xfip") or "—"

                # Pitch-type mix buckets
                def _pct(field):
                    return _safe_float(sp_data.get(field)) or 0.0
                sp_fb_pct       = round(_pct("n_ff_formatted") + _pct("n_si_formatted") + _pct("n_fc_formatted"), 1)
                sp_breaking_pct = round(_pct("n_sl_formatted") + _pct("n_cu_formatted") + _pct("n_sw_formatted"), 1)
                sp_offspeed_pct = round(_pct("n_ch_formatted") + _pct("n_fs_formatted"), 1)
                # Use None when pitcher has no pitch data at all (early season / missing)
                sp_fb_pct       = sp_fb_pct if sp_fb_pct > 0 else None
                sp_breaking_pct = sp_breaking_pct if sp_breaking_pct > 0 else None
                sp_offspeed_pct = sp_offspeed_pct if sp_offspeed_pct > 0 else None
```

- [ ] **Step 4: Store pitch buckets in player_signals dict (line ~1821)**

In the `player_signals[batter_name] = { ... }` dict (around line 1821), add three entries after `"pitcher_hr_per_9"`:

```python
                            "pitcher_hr_per_9":    round(pf["hr_per_9"], 2) if pf else None,
                            "pitcher_fb_pct":      sp_fb_pct,
                            "pitcher_breaking_pct": sp_breaking_pct,
                            "pitcher_offspeed_pct": sp_offspeed_pct,
```

- [ ] **Step 5: Write integration test**

Add to `tests/test_pitch_mix.py`:

```python
def test_player_signals_include_pitch_buckets():
    """player_signals should contain pitcher_fb_pct keys after _build_game_cards()."""
    import json
    from unittest.mock import patch

    homer = Homer()

    fake_lineups = json.dumps({
        "status": "success",
        "games": [{
            "home": {
                "team": "New York Yankees",
                "lineup_confirmed": True,
                "pitcher": "Gerrit Cole",
                "pitcher_id": 543037,
                "pitcher_throws": "R",
                "players": [{"id": 592450, "fullName": "Aaron Judge", "batSide": {"code": "R"}}],
            },
            "away": {
                "team": "Boston Red Sox",
                "lineup_confirmed": False,
                "pitcher": "TBD",
                "pitcher_id": None,
                "pitcher_throws": "R",
                "players": [],
            },
            "venue": "Yankee Stadium",
            "time": "7:05 PM",
        }]
    })

    fake_pitcher_stats = {
        "cole, gerrit": {
            "hr_flyball_rate": "8.5", "fb_percent": "52.0",
            "xfip": "3.20", "hard_hit_percent": "38.0",
            "barrel_batted_rate": "6.0",
            "n_ff_formatted": "55.0", "n_si_formatted": "0.0", "n_fc_formatted": "5.0",
            "n_sl_formatted": "22.0", "n_cu_formatted": "10.0", "n_sw_formatted": "0.0",
            "n_ch_formatted": "8.0", "n_fs_formatted": "0.0",
        }
    }

    _, signals = homer._build_game_cards(
        fake_lineups,
        batter_stats={},
        pitcher_stats=fake_pitcher_stats,
        our_history=[],
        recent_form=[],
        pitcher_form={},
        home_away={},
    )

    assert "Aaron Judge" in signals
    judge = signals["Aaron Judge"]
    assert "pitcher_fb_pct" in judge, "pitcher_fb_pct should be in player_signals"
    assert judge["pitcher_fb_pct"] == 60.0   # 55 + 0 + 5
    assert judge["pitcher_breaking_pct"] == 32.0  # 22 + 10 + 0
    assert judge["pitcher_offspeed_pct"] == 8.0   # 8 + 0
```

- [ ] **Step 6: Run all pitch_mix tests**

```bash
python -m pytest tests/test_pitch_mix.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 7: Commit**

```bash
git add agents/predictor.py tests/test_pitch_mix.py
git commit -m "feat: compute pitcher pitch-mix buckets (fb/breaking/offspeed) in _build_game_cards()"
```

---

### Task 3: Add scoring logic in `_score_player()`

**Files:**
- Modify: `agents/predictor.py:2563` (after pitcher HR/9 block in `_score_player()`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pitch_mix.py`:

```python
def test_score_player_pitch_mix_bonus():
    """Heavy fastball pitcher should add +2 to score."""
    sig = {
        "status": "confirmed",
        "pitcher_fb_pct": 65.0,
        "pitcher_breaking_pct": 20.0,
        "pitcher_offspeed_pct": 10.0,
    }
    score = Homer._score_player(sig)
    assert score >= 2, f"Expected score >= 2 for heavy FB pitcher, got {score}"

def test_score_player_pitch_mix_penalty():
    """Breaking-ball dominant pitcher should subtract from score."""
    sig = {
        "status": "confirmed",
        "pitcher_fb_pct": 30.0,
        "pitcher_breaking_pct": 40.0,
        "pitcher_offspeed_pct": 25.0,
    }
    score = Homer._score_player(sig)
    assert score <= -3, f"Expected score <= -3 for breaking+offspeed heavy pitcher, got {score}"

def test_score_player_pitch_mix_neutral():
    """Typical mixed arsenal should not change score from None baseline."""
    sig_with_mix = {
        "status": "confirmed",
        "pitcher_fb_pct": 45.0,
        "pitcher_breaking_pct": 30.0,
        "pitcher_offspeed_pct": 15.0,
    }
    sig_no_mix = {"status": "confirmed"}
    score_with = Homer._score_player(sig_with_mix)
    score_without = Homer._score_player(sig_no_mix)
    assert score_with == score_without, "Mixed arsenal should not change score vs no data"

def test_score_player_pitch_mix_none():
    """Missing pitch data should not affect score."""
    sig = {
        "status": "confirmed",
        "pitcher_fb_pct": None,
        "pitcher_breaking_pct": None,
        "pitcher_offspeed_pct": None,
    }
    score = Homer._score_player(sig)
    assert score == 0.0  # no signals = base score (confirmed, no other data)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pitch_mix.py::test_score_player_pitch_mix_bonus tests/test_pitch_mix.py::test_score_player_pitch_mix_penalty tests/test_pitch_mix.py::test_score_player_pitch_mix_neutral tests/test_pitch_mix.py::test_score_player_pitch_mix_none -v
```

Expected: FAIL — pitch mix block not yet in `_score_player()`

- [ ] **Step 3: Add scoring block to `_score_player()` after pitcher HR/9 section (line ~2563)**

In `agents/predictor.py`, find the pitcher HR/9 block (ends around line 2563) and insert immediately after:

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

- [ ] **Step 4: Run all scoring tests**

```bash
python -m pytest tests/test_pitch_mix.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/predictor.py tests/test_pitch_mix.py
git commit -m "feat: add pitcher pitch-mix directional scoring to _score_player()"
```

---

### Task 4: Persist to DB and add ML features

**Files:**
- Modify: `agents/bet_tracker.py:150` (`_MIGRATION_COLUMNS`)
- Modify: `ml/optimize_weights.py:59` (`FEATURES` list)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pitch_mix.py`:

```python
import sqlite3, tempfile, os

def test_migration_columns_include_pitch_mix():
    """pick_factors table should gain pitch-mix columns after migration."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from agents.bet_tracker import _ensure_pick_factors_table, _MIGRATION_COLUMNS

    col_names = [col for col, _ in _MIGRATION_COLUMNS]
    assert "pitcher_fb_pct" in col_names
    assert "pitcher_breaking_pct" in col_names
    assert "pitcher_offspeed_pct" in col_names

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        _ensure_pick_factors_table(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(pick_factors)").fetchall()}
        conn.close()
        assert "pitcher_fb_pct" in cols
        assert "pitcher_breaking_pct" in cols
        assert "pitcher_offspeed_pct" in cols
    finally:
        os.unlink(db_path)

def test_ml_features_include_pitch_mix():
    """FEATURES list in optimize_weights.py should include the three pitch-mix columns."""
    from ml.optimize_weights import FEATURES
    feature_names = [name for name, _ in FEATURES]
    assert "pitcher_fb_pct" in feature_names
    assert "pitcher_breaking_pct" in feature_names
    assert "pitcher_offspeed_pct" in feature_names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pitch_mix.py::test_migration_columns_include_pitch_mix tests/test_pitch_mix.py::test_ml_features_include_pitch_mix -v
```

Expected: FAIL — columns not yet added

- [ ] **Step 3: Add migration columns to `bet_tracker.py`**

In `agents/bet_tracker.py`, find `_MIGRATION_COLUMNS` (line 135) and add three entries after `("blast_rate", "REAL")`:

```python
    ("blast_rate",           "REAL"),
    ("pitcher_fb_pct",       "REAL"),
    ("pitcher_breaking_pct", "REAL"),
    ("pitcher_offspeed_pct", "REAL"),
```

- [ ] **Step 4: Add ML features to `optimize_weights.py`**

In `ml/optimize_weights.py`, find the `FEATURES` list (line 35) and add three entries after `("h2h_hr", None)`:

```python
    ("h2h_hr",           None),
    ("pitcher_fb_pct",       None),
    ("pitcher_breaking_pct", None),
    ("pitcher_offspeed_pct", None),
]
```

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/test_pitch_mix.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add agents/bet_tracker.py ml/optimize_weights.py tests/test_pitch_mix.py
git commit -m "feat: persist pitcher pitch-mix to pick_factors DB and add to ML features"
```

---

### Task 5: Smoke test end-to-end with cached data

**Files:**
- Run: `tools/test_homer_prompt.py`

- [ ] **Step 1: Run picks from cache and check pitch-mix signals appear**

```bash
cd /Users/joesliwinski/AIProjects/DingersHotline
python tools/test_homer_prompt.py --pipeline 2>&1 | grep -i "pitch\|fb_pct\|breaking\|offspeed" | head -20
```

Expected: output shows pitch-mix data populating for at least some pitchers.

- [ ] **Step 2: Spot-check a specific player's signals**

```bash
python tools/test_homer_prompt.py --debug "Aaron Judge" 2>&1 | grep -i "pitch\|fb\|breaking\|offspeed" | head -10
```

Expected: `pitcher_fb_pct`, `pitcher_breaking_pct`, `pitcher_offspeed_pct` visible in Judge's signal dump.

- [ ] **Step 3: Confirm [ODDS] log still clean**

```bash
python tools/test_homer_prompt.py 2>&1 | grep "\[ODDS\]"
```

Expected: lines show matched player count with no unexpected warnings.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: pitch-type pitcher mix scoring — complete (Phase 1)"
```

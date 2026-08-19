# Strikeout Prop Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a second, independent prediction pipeline ("Ace") that ranks starting pitchers for MLB strikeout props, publishes the top 10 daily picks to a new site page, and tracks its own ML model — without touching the working HR ("Homer") pipeline's behavior.

**Architecture:** A sibling module `agents/k_predictor.py` (class `Ace`) mirrors Homer's deterministic-scoring + LightGBM-blend pattern. It reuses Homer's EV/Kelly math and (a lightly extended) `_fetch_pitcher_recent_form`, but owns its own Statcast fetch, its own odds-comparison function (different Odds API market), its own DB table (`pick_factors_k`), its own LightGBM model files, and its own site page. `scripts/daily_picks.py` runs `Ace` as a second step after Homer.

**Tech Stack:** Python 3, requests, sqlite3, LightGBM, pytest. Same stack as the existing HR pipeline — no new dependencies.

## Global Constraints

- Pitcher strikeout props only — no batter strikeout props (per spec, "Out of Scope").
- Publish exactly the top 10 daily picks (not top 15/20 — spec's "Pick Count" section: the realistic daily starting-pitcher pool is ~12-15 names).
- No park factor or weather signals — they drive HR outcomes via batted-ball carry, not strikeouts (spec: "Deliberately excluded").
- No umpire strike-zone signal this iteration — no verified reliable data source yet (spec: "Deferred").
- No personal bet logging — site shows **hypothetical model P&L only** ($10 on every published K pick), same framing as the HR dashboard. Never add a personal-bet tracking table or CLI for K props.
- Unconfirmed starting pitchers are **excluded** from the pool entirely, not penalized (unlike HR's roster-fallback −2 penalty for unconfirmed batters).
- `agents/k_predictor.py` must not modify `Homer`'s scoring, `_gather_data`, or any HR-specific DB table/column — the only touch to `agents/predictor.py` is additive fields on `_fetch_pitcher_recent_form` (Task 1), which is shared and must not change any existing key Homer already reads.
- Reuse, don't duplicate: `_compute_ev`, `_compute_kelly`, `_american_to_decimal`, `_american_to_implied_prob`, `SAVANT_BASE`, `MLB_API_BASE`, `ODDS_API_BASE`, `_HEADERS` are imported from `agents.predictor`, not re-implemented.

---

## File Structure

| File | Responsibility |
|---|---|
| `agents/predictor.py` | Modified only: `_fetch_pitcher_recent_form` gains K/IP/pitch-count/rest fields (additive, non-breaking). |
| `agents/k_predictor.py` | New. `Ace` class: `_gather_data()`, `_rank_picks_python()`, `get_picks_json()`. Module-level: `_score_pitcher()`, `_fetch_pitcher_k_statcast()`, `_fetch_pitch_arsenal_whiff()` (shared helper for both pitcher-whiff and batter-whiff-vs-pitch-type), `fetch_k_odds_comparison()`. |
| `agents/bet_tracker.py` | Modified: add `_K_MIGRATION_COLUMNS`, `_CREATE_PICK_FACTORS_K`, `_ensure_pick_factors_k_table()`, `save_pick_factors_k()`. |
| `ml/optimize_weights_k.py` | New. LightGBM trainer for the K model, mirrors `ml/optimize_weights.py`. |
| `ml/fetch_actual_k_results.py` | New. Labels yesterday's `pick_factors_k` rows with actual strikeout totals. |
| `ml/build_historical_k_dataset.py` | New. Historical bootstrap — reuses `fetch_season_schedule` from `ml/build_historical_dataset.py`. |
| `scripts/daily_picks.py` | Modified: run `Ace` after `Homer`, write `picks/k_picks_{date}.txt/.html`, extend `_auto_maintain()` and the git file list. |
| `tools/generate_html.py` | Modified: add `generate_k_picks_html()`; add a K-picks nav link to existing page templates. |
| `docs/strikeouts.html` | New (generated). |
| `.claude/hooks/auto-push-site.sh` | Modified: add `docs/strikeouts.html` to the git-add list and CHANGED regex. |
| `tests/test_k_signals.py` | New. Scoring/signal tests, mirrors `tests/test_new_signals.py` style. |
| `tests/test_k_pick_factors_db.py` | New. DB schema/save tests, mirrors existing bet_tracker test patterns. |

---

### Task 1: Extend `_fetch_pitcher_recent_form` with strikeout/workload/rest fields

**Files:**
- Modify: `agents/predictor.py:1557-1616` (`_fetch_pitcher_recent_form`)
- Test: `tests/test_k_signals.py` (new file, this task creates it)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_fetch_pitcher_recent_form(pitcher_id, n_starts=3)` now also returns `k_per_9_blended: float`, `recent_k9: float`, `season_k9: float`, `total_k: int`, `avg_ip_last3: float`, `avg_pitches_last3: float | None`, `days_rest: int | None` — in addition to the existing `starts_sampled`, `hr_per_9`, `recent_hr9`, `season_hr9`, `total_hr`, `logs`. Every existing key is unchanged in meaning; `Ace` (Task 6) reads the new keys, `Homer` is unaffected since it never reads them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_k_signals.py`:

```python
"""
Tests for the strikeout prop model (Ace / k_predictor.py) — signal extraction
and scoring. Mirrors tests/test_new_signals.py's style: plain dict builders,
no live network calls, ML weights monkeypatched off where relevant.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock


def _fake_gamelog_response(rows):
    """Build a fake MLB Stats API gameLog JSON payload from a list of
    (date, strikeOuts, homeRuns, earnedRuns, inningsPitched, numberOfPitches) tuples."""
    splits = []
    for date_str, so, hr, er, ip, pitches in rows:
        splits.append({
            "date": date_str,
            "stat": {
                "strikeOuts": so, "homeRuns": hr, "earnedRuns": er,
                "inningsPitched": str(ip), "numberOfPitches": pitches,
            },
        })
    return {"stats": [{"splits": splits}]}


class TestPitcherRecentFormKFields:

    def test_returns_k_per_9_blended_and_workload_fields(self):
        from agents.predictor import _fetch_pitcher_recent_form

        rows = [
            ("2026-08-15", 9, 1, 2, "6.0", 96),
            ("2026-08-10", 7, 0, 1, "5.1", 91),
            ("2026-08-05", 8, 2, 3, "6.2", 99),
            ("2026-07-30", 6, 1, 2, "5.0", 88),
        ]
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = _fake_gamelog_response(rows)

        with patch("agents.predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitcher_recent_form(12345, n_starts=3)

        assert "k_per_9_blended" in result
        assert "recent_k9" in result
        assert "season_k9" in result
        assert "avg_ip_last3" in result
        assert "avg_pitches_last3" in result
        assert "days_rest" in result

        # Existing HR fields must be untouched — Homer depends on these.
        assert "hr_per_9" in result
        assert "starts_sampled" in result

        # 3 most recent starts: (9+7+8) K over (6.0+5.1+6.2) IP = 24/17.3*9 ≈ 12.49
        assert result["recent_k9"] == round((9 + 7 + 8) / (6.0 + 5.1 + 6.2) * 9, 2)
        assert result["avg_ip_last3"] == round((6.0 + 5.1 + 6.2) / 3, 2)
        assert result["avg_pitches_last3"] == round((96 + 91 + 99) / 3, 2)

    def test_days_rest_computed_from_most_recent_start(self):
        from agents.predictor import _fetch_pitcher_recent_form
        from datetime import date, timedelta

        five_days_ago = (date.today() - timedelta(days=5)).isoformat()
        rows = [(five_days_ago, 7, 1, 2, "6.0", 95)]
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = _fake_gamelog_response(rows)

        with patch("agents.predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitcher_recent_form(12345, n_starts=3)

        assert result["days_rest"] == 5

    def test_missing_pitch_count_falls_back_to_none(self):
        """numberOfPitches isn't always present in older/incomplete logs."""
        from agents.predictor import _fetch_pitcher_recent_form

        rows_no_pitches = [("2026-08-15", 7, 1, 2, "6.0", None)]
        splits = [{
            "date": "2026-08-15",
            "stat": {"strikeOuts": 7, "homeRuns": 1, "earnedRuns": 2, "inningsPitched": "6.0"},
        }]
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {"stats": [{"splits": splits}]}

        with patch("agents.predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitcher_recent_form(12345, n_starts=3)

        assert result["avg_pitches_last3"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_signals.py -v`
Expected: FAIL — `KeyError` or `AssertionError` on `"k_per_9_blended" in result` (key doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

Replace `agents/predictor.py:1557-1616` (`_fetch_pitcher_recent_form`) with:

```python
def _fetch_pitcher_recent_form(pitcher_id: int, n_starts: int = 3) -> dict:
    """
    Fetch pitcher game log from the MLB Stats API.
    Returns blended HR/9 and K/9 (60% last-3-starts + 40% season), plus
    workload (avg IP, avg pitch count over last n_starts) and days of rest
    since the most recent start. A start = appearance with >= 3 innings pitched.
    """
    if not pitcher_id:
        return {}
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/people/{pitcher_id}/stats",
            params={"stats": "gameLog", "group": "pitching",
                    "season": date.today().year, "limit": 40},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}

    all_logs = []
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            stat = split.get("stat", {})
            try:
                ip = float(stat.get("inningsPitched") or 0)
            except (ValueError, TypeError):
                ip = 0
            if ip < 3:
                continue
            pitches = stat.get("numberOfPitches")
            all_logs.append({
                "date":       split.get("date", ""),
                "hr_allowed": int(stat.get("homeRuns") or 0),
                "so":         int(stat.get("strikeOuts") or 0),
                "ip":         ip,
                "er":         int(stat.get("earnedRuns") or 0),
                "pitches":    int(pitches) if pitches not in (None, "") else None,
            })

    if not all_logs:
        return {}

    recent_logs = all_logs[:n_starts]
    recent_hr   = sum(g["hr_allowed"] for g in recent_logs)
    recent_so   = sum(g["so"] for g in recent_logs)
    recent_ip   = sum(g["ip"] for g in recent_logs)
    recent_hr9  = round(recent_hr / recent_ip * 9, 2) if recent_ip else 0
    recent_k9   = round(recent_so / recent_ip * 9, 2) if recent_ip else 0

    season_hr  = sum(g["hr_allowed"] for g in all_logs)
    season_so  = sum(g["so"] for g in all_logs)
    season_ip  = sum(g["ip"] for g in all_logs)
    season_hr9 = round(season_hr / season_ip * 9, 2) if season_ip else 0
    season_k9  = round(season_so / season_ip * 9, 2) if season_ip else 0

    # Blend: 60% recent form, 40% season — captures current vulnerability + baseline
    blended_hr9 = round(0.6 * recent_hr9 + 0.4 * season_hr9, 2)
    blended_k9  = round(0.6 * recent_k9 + 0.4 * season_k9, 2)

    avg_ip_last3 = round(recent_ip / len(recent_logs), 2) if recent_logs else None
    pitch_counts = [g["pitches"] for g in recent_logs if g["pitches"] is not None]
    avg_pitches_last3 = round(sum(pitch_counts) / len(pitch_counts), 2) if pitch_counts else None

    days_rest = None
    most_recent = recent_logs[0]["date"] if recent_logs else None
    if most_recent:
        try:
            last_start_date = date.fromisoformat(most_recent)
            days_rest = (date.today() - last_start_date).days
        except ValueError:
            days_rest = None

    return {
        "starts_sampled": len(recent_logs),
        "hr_per_9":       blended_hr9,
        "recent_hr9":     recent_hr9,
        "season_hr9":     season_hr9,
        "total_hr":       recent_hr,
        "k_per_9_blended": blended_k9,
        "recent_k9":      recent_k9,
        "season_k9":      season_k9,
        "total_k":        recent_so,
        "avg_ip_last3":   avg_ip_last3,
        "avg_pitches_last3": avg_pitches_last3,
        "days_rest":      days_rest,
        "logs":           recent_logs,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_signals.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Confirm existing HR tests still pass (no regression)**

Run: `python -m pytest tests/ -v -k "not network"`
Expected: same pass/fail counts as before this change (this is an additive change to a shared function — no existing test should newly fail).

- [ ] **Step 6: Commit**

```bash
git add agents/predictor.py tests/test_k_signals.py
git commit -m "feat(k-model): extend pitcher recent-form fetch with K/workload/rest fields"
```

---

### Task 2: Pitcher K-rate Statcast fetch

**Files:**
- Create: `agents/k_predictor.py`
- Test: `tests/test_k_signals.py` (append)

**Interfaces:**
- Consumes: `SAVANT_BASE`, `_HEADERS` from `agents.predictor`.
- Produces: `_fetch_pitcher_k_statcast() -> dict` — keyed by `int(player_id)` (primary) and lowercased name (secondary, `setdefault`), values are raw CSV row dicts with columns `k_percent`, `whiff_percent`, `csw_percent`, `swinging_strike_percent`. Used by `Ace._gather_data` (Task 6).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_k_signals.py`:

```python
class TestPitcherKStatcastFetch:

    def test_fetches_and_keys_by_player_id_and_name(self):
        from agents.k_predictor import _fetch_pitcher_k_statcast

        csv_text = (
            "last_name, first_name,player_id,k_percent,whiff_percent,csw_percent,swinging_strike_percent\n"
            '"Cole, Gerrit",543037,32.5,29.1,31.0,14.2\n'
        )
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.text = csv_text

        with patch("agents.k_predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitcher_k_statcast()

        assert result[543037]["k_percent"] == "32.5"
        assert result["cole, gerrit"]["whiff_percent"] == "29.1"

    def test_returns_empty_dict_on_request_failure(self):
        from agents.k_predictor import _fetch_pitcher_k_statcast

        with patch("agents.k_predictor.requests.get", side_effect=Exception("network down")):
            result = _fetch_pitcher_k_statcast()

        assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_signals.py::TestPitcherKStatcastFetch -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.k_predictor'`

- [ ] **Step 3: Write minimal implementation**

Create `agents/k_predictor.py`:

```python
"""
k_predictor.py — Ace: MLB pitcher strikeout prop prediction.

Sibling to agents/predictor.py's Homer (HR model). Same philosophy: gather
real signals, score deterministically, blend in a LightGBM model once one
exists. No LLM involved in ranking.

Reuses Homer's EV/Kelly math and the (Task 1-extended) pitcher recent-form
fetch. Owns its own Statcast fetch, its own odds market (pitcher_strikeouts,
not batter_home_runs), its own DB table (pick_factors_k), and its own site
page — a bug here cannot affect the HR pipeline.
"""
import csv
import io
from datetime import date
from pathlib import Path

import requests

from agents.predictor import (
    SAVANT_BASE, MLB_API_BASE, ODDS_API_BASE, _HEADERS,
    _compute_ev, _compute_kelly, _american_to_implied_prob,
    _fetch_pitcher_recent_form,
)


def _fetch_pitcher_k_statcast() -> dict:
    """
    Fetch the full Statcast pitcher K-rate leaderboard CSV, keyed by
    player_id (primary) and lowercased name (secondary). Columns:
    k_percent, whiff_percent, csw_percent, swinging_strike_percent.
    Caches to cache/statcast_pitcher_k_YYYY-MM-DD.csv (one fetch per day).
    """
    season    = date.today().year
    today_str = date.today().isoformat()
    cache_path = Path(__file__).parent.parent / "cache" / f"statcast_pitcher_k_{today_str}.csv"

    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8")
    else:
        url = (
            f"{SAVANT_BASE}/leaderboard/custom"
            f"?year={season}&type=pitcher&filter=&sort=4&sortDir=desc&min=5"
            f"&selections=k_percent,whiff_percent,csw_percent,swinging_strike_percent"
            f"&chart=false&r=no&exactNameSearch=false&csv=true"
        )
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            text = resp.text.lstrip('﻿')
            cache_path.parent.mkdir(exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        except Exception:
            return {}

    try:
        reader = csv.DictReader(io.StringIO(text))
        result = {}
        for row in reader:
            name = (row.get("last_name, first_name") or row.get("player_name") or "").lower()
            pid_raw = row.get("player_id") or row.get("pitcher") or ""
            try:
                result[int(pid_raw)] = row
            except (ValueError, TypeError):
                pass
            if name:
                result.setdefault(name, row)
        return result
    except Exception:
        return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_signals.py::TestPitcherKStatcastFetch -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/k_predictor.py tests/test_k_signals.py
git commit -m "feat(k-model): add agents/k_predictor.py with pitcher K-rate Statcast fetch"
```

---

### Task 3: Pitch-arsenal whiff% — pitcher's own mix + opposing lineup's matchup whiff

**Files:**
- Modify: `agents/k_predictor.py`
- Test: `tests/test_k_signals.py` (append)

**Interfaces:**
- Consumes: `SAVANT_BASE`, `_HEADERS` (already imported in Task 2).
- Produces:
  - `_PITCH_BUCKETS_K` dict (pitch code → bucket), same taxonomy as predictor.py's `_PITCH_BUCKETS`.
  - `_fetch_pitch_arsenal_whiff(player_ids: list[int], player_type: str) -> dict[int, dict]` — generic helper. For `player_type="pitcher"`: returns `{pid: {"whiff_fastball": float|None, "whiff_breaking": float|None, "whiff_offspeed": float|None}}` (the pitcher's own whiff% by the pitch types he throws). For `player_type="batter"`: same shape but the batter's whiff% against each pitch-type bucket (used for the matchup signal in Task 6).
  - `_weighted_opp_whiff(pitcher_pitch_mix: dict, batter_whiff_splits: list[dict]) -> float | None` — combines a pitcher's pitch-mix percentages with each confirmed opposing batter's whiff-by-bucket splits into one matchup scalar (average across batters of: sum(bucket_whiff% * pitcher's %-usage of that bucket)).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_k_signals.py`:

```python
class TestPitchArsenalWhiff:

    def test_fetch_pitch_arsenal_whiff_buckets_and_weights_by_pa(self):
        from agents.k_predictor import _fetch_pitch_arsenal_whiff

        csv_text = (
            "player_id,pitch_type,whiff_percent,pa\n"
            "543037,FF,28.0,100\n"
            "543037,SI,24.0,50\n"
            "543037,SL,35.0,80\n"
            "543037,CH,20.0,40\n"
        )
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.text = csv_text

        with patch("agents.k_predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitch_arsenal_whiff([543037], player_type="pitcher")

        # fastball bucket = FF(28.0, pa=100) + SI(24.0, pa=50), PA-weighted:
        expected_fastball = (28.0 * 100 + 24.0 * 50) / (100 + 50)
        assert round(result[543037]["whiff_fastball"], 2) == round(expected_fastball, 2)
        assert result[543037]["whiff_breaking"] == 35.0
        assert result[543037]["whiff_offspeed"] == 20.0

    def test_weighted_opp_whiff_combines_pitcher_mix_with_batter_splits(self):
        from agents.k_predictor import _weighted_opp_whiff

        pitcher_mix = {"fastball": 0.60, "breaking": 0.30, "offspeed": 0.10}
        batter_splits = [
            {"whiff_fastball": 20.0, "whiff_breaking": 30.0, "whiff_offspeed": 40.0},
            {"whiff_fastball": 30.0, "whiff_breaking": 20.0, "whiff_offspeed": 10.0},
        ]
        result = _weighted_opp_whiff(pitcher_mix, batter_splits)

        batter1 = 20.0 * 0.60 + 30.0 * 0.30 + 40.0 * 0.10
        batter2 = 30.0 * 0.60 + 20.0 * 0.30 + 10.0 * 0.10
        expected = round((batter1 + batter2) / 2, 2)
        assert result == expected

    def test_weighted_opp_whiff_returns_none_for_empty_lineup(self):
        from agents.k_predictor import _weighted_opp_whiff
        assert _weighted_opp_whiff({"fastball": 1.0, "breaking": 0.0, "offspeed": 0.0}, []) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_signals.py::TestPitchArsenalWhiff -v`
Expected: FAIL — `ImportError: cannot import name '_fetch_pitch_arsenal_whiff'`

- [ ] **Step 3: Write minimal implementation**

Append to `agents/k_predictor.py`:

```python
# Pitch type code → bucket, same taxonomy as predictor.py's _PITCH_BUCKETS.
_PITCH_BUCKETS_K = {
    "FF": "fastball", "SI": "fastball", "FC": "fastball",
    "SL": "breaking", "CU": "breaking", "KC": "breaking", "ST": "breaking",
    "SV": "breaking", "CS": "breaking",
    "CH": "offspeed", "FS": "offspeed", "SC": "offspeed",
    "FO": "offspeed", "KN": "offspeed",
}


def _fetch_pitch_arsenal_whiff(player_ids: list[int], player_type: str) -> dict[int, dict]:
    """
    Fetch whiff% by pitch-type bucket (fastball/breaking/offspeed) from
    Savant's pitch-arsenal-stats leaderboard, PA-weighted per bucket.

    player_type="pitcher": each pitcher's own whiff% generated by the pitch
    types he throws (a "does he have a wipeout pitch" signal).
    player_type="batter": each batter's whiff% against each pitch-type
    bucket (used to build the opposing-lineup matchup signal).

    Returns {player_id: {"whiff_fastball": float|None, "whiff_breaking": ...,
    "whiff_offspeed": ...}}. Early season: sparse buckets return None for
    that key rather than being omitted from the dict.
    """
    if not player_ids:
        return {}
    year = date.today().year
    try:
        resp = requests.get(
            f"{SAVANT_BASE}/leaderboard/pitch-arsenal-stats"
            f"?type={player_type}&year={year}&team=&min=1&csv=true",
            timeout=30,
            headers=_HEADERS,
        )
        resp.raise_for_status()
        text = resp.text.lstrip('﻿')
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception:
        return {}

    def _sf(val):
        if val in (None, "", "null"):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    player_id_set = {int(p) for p in player_ids}
    accum: dict[int, dict[str, list[tuple[float, float]]]] = {}
    for row in rows:
        pid_raw = row.get("player_id")
        if pid_raw is None:
            continue
        try:
            pid = int(pid_raw)
        except (ValueError, TypeError):
            continue
        if pid not in player_id_set:
            continue

        bucket = _PITCH_BUCKETS_K.get(row.get("pitch_type"))
        if bucket is None:
            continue
        whiff = _sf(row.get("whiff_percent"))
        pa = _sf(row.get("pa"))
        if whiff is None or not pa:
            continue
        accum.setdefault(pid, {}).setdefault(bucket, []).append((whiff, pa))

    result: dict[int, dict] = {}
    for pid, buckets in accum.items():
        splits = {}
        for key, bucket in (("whiff_fastball", "fastball"),
                             ("whiff_breaking", "breaking"),
                             ("whiff_offspeed", "offspeed")):
            samples = buckets.get(bucket)
            if not samples:
                splits[key] = None
                continue
            total_pa = sum(pa for _, pa in samples)
            splits[key] = sum(w * pa for w, pa in samples) / total_pa if total_pa else None
        if any(v is not None for v in splits.values()):
            result[pid] = splits
    return result


def _weighted_opp_whiff(pitcher_mix: dict, batter_splits: list[dict]) -> float | None:
    """
    Combine a pitcher's pitch-mix usage (fractions summing to ~1.0, keys
    "fastball"/"breaking"/"offspeed") with each confirmed opposing batter's
    whiff-by-bucket splits into one matchup scalar: for each batter, sum
    their bucket whiff% weighted by the pitcher's usage of that bucket,
    then average across the lineup. Returns None for an empty lineup.
    """
    if not batter_splits:
        return None
    per_batter = []
    for splits in batter_splits:
        total = 0.0
        for bucket_key, mix_key in (("whiff_fastball", "fastball"),
                                     ("whiff_breaking", "breaking"),
                                     ("whiff_offspeed", "offspeed")):
            val = splits.get(bucket_key)
            if val is None:
                continue
            total += val * pitcher_mix.get(mix_key, 0.0)
        per_batter.append(total)
    if not per_batter:
        return None
    return round(sum(per_batter) / len(per_batter), 2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_signals.py::TestPitchArsenalWhiff -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/k_predictor.py tests/test_k_signals.py
git commit -m "feat(k-model): pitch-arsenal whiff splits + opposing-lineup matchup signal"
```

---

### Task 4: `_score_pitcher()` deterministic scoring

**Files:**
- Modify: `agents/k_predictor.py`
- Test: `tests/test_k_signals.py` (append)

**Interfaces:**
- Consumes: a `sig: dict` with keys `k_percent, whiff_percent, csw_percent, swinging_strike_percent, k_per_9_blended, pitcher_whiff_fastball, pitcher_whiff_breaking, pitcher_whiff_offspeed, opp_whiff_vs_mix, avg_ip_last3, avg_pitches_last3, days_rest, ev_10, value_edge, confirmed` (bool).
- Produces: `_score_pitcher(sig: dict) -> float`. Used by `Ace._rank_picks_python` (Task 6) and by `ml/optimize_weights_k.py`'s correlation report (Task 8).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_k_signals.py`:

```python
def _base_k_sig():
    return {
        "k_percent": 22.0, "whiff_percent": 24.0, "csw_percent": 28.0,
        "swinging_strike_percent": 10.5, "k_per_9_blended": 8.0,
        "pitcher_whiff_fastball": None, "pitcher_whiff_breaking": None,
        "pitcher_whiff_offspeed": None, "opp_whiff_vs_mix": None,
        "avg_ip_last3": 5.5, "avg_pitches_last3": 88.0, "days_rest": 5,
        "ev_10": 0.0, "value_edge": 0.0,
    }


class TestScorePitcher:

    def test_elite_k_rate_scores_higher_than_average(self):
        from agents.k_predictor import _score_pitcher

        avg = _base_k_sig()
        elite = _base_k_sig()
        elite.update({"k_percent": 32.0, "whiff_percent": 33.0,
                      "csw_percent": 34.0, "swinging_strike_percent": 15.0,
                      "k_per_9_blended": 12.0})

        assert _score_pitcher(elite) > _score_pitcher(avg)

    def test_short_workload_penalizes_score(self):
        from agents.k_predictor import _score_pitcher

        normal = _base_k_sig()
        short  = _base_k_sig()
        short["avg_ip_last3"] = 4.0
        short["avg_pitches_last3"] = 72.0

        assert _score_pitcher(short) < _score_pitcher(normal)

    def test_short_rest_penalizes_score(self):
        from agents.k_predictor import _score_pitcher

        normal = _base_k_sig()
        rested = _base_k_sig()
        rested["days_rest"] = 3

        assert _score_pitcher(rested) < _score_pitcher(normal)

    def test_favorable_matchup_boosts_score(self):
        from agents.k_predictor import _score_pitcher

        no_matchup = _base_k_sig()
        good_matchup = _base_k_sig()
        good_matchup["opp_whiff_vs_mix"] = 30.0

        assert _score_pitcher(good_matchup) > _score_pitcher(no_matchup)

    def test_positive_ev_boosts_score(self):
        from agents.k_predictor import _score_pitcher

        no_ev = _base_k_sig()
        good_ev = _base_k_sig()
        good_ev["ev_10"] = 4.0

        assert _score_pitcher(good_ev) > _score_pitcher(no_ev)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_signals.py::TestScorePitcher -v`
Expected: FAIL — `ImportError: cannot import name '_score_pitcher'`

- [ ] **Step 3: Write minimal implementation**

Append to `agents/k_predictor.py`:

```python
def _score_pitcher(sig: dict) -> float:
    """
    Score a starting pitcher 0-∞ for strikeout prop value. Higher = better
    K pick today. Deterministic — no LLM involved. Thresholds are seeded
    from published K-prop research (MLB average K% ~22-23%, whiff% ~24-25%,
    CSW% ~29%, SwStr% ~11%) and are meant to be tuned later via
    optimize_weights_k.py's correlation report once labeled data exists.
    """
    score = 0.0

    k_pct = sig.get("k_percent")
    if k_pct is not None:
        if k_pct >= 30: score += 4
        elif k_pct >= 27: score += 3
        elif k_pct >= 24: score += 2
        elif k_pct >= 21: score += 1
        elif k_pct < 18: score -= 1

    whiff = sig.get("whiff_percent")
    if whiff is not None:
        if whiff >= 32: score += 3
        elif whiff >= 28: score += 2
        elif whiff >= 25: score += 1
        elif whiff < 20: score -= 1

    csw = sig.get("csw_percent")
    if csw is not None:
        if csw >= 33: score += 2
        elif csw >= 30: score += 1
        elif csw < 26: score -= 1

    swstr = sig.get("swinging_strike_percent")
    if swstr is not None:
        if swstr >= 14: score += 2
        elif swstr >= 12: score += 1
        elif swstr < 9: score -= 1

    k9 = sig.get("k_per_9_blended")
    if k9 is not None:
        if k9 >= 11: score += 4
        elif k9 >= 9.5: score += 3
        elif k9 >= 8: score += 2
        elif k9 >= 6.5: score += 1
        elif k9 < 5: score -= 1

    for key in ("pitcher_whiff_fastball", "pitcher_whiff_breaking", "pitcher_whiff_offspeed"):
        val = sig.get(key)
        if val is None:
            continue
        if val >= 35: score += 1
        elif val < 20: score -= 0.5

    opp_whiff = sig.get("opp_whiff_vs_mix")
    if opp_whiff is not None:
        if opp_whiff >= 27: score += 3
        elif opp_whiff >= 24: score += 2
        elif opp_whiff >= 21: score += 1
        elif opp_whiff < 17: score -= 1

    avg_ip = sig.get("avg_ip_last3")
    if avg_ip is not None:
        if avg_ip >= 6.0: score += 2
        elif avg_ip >= 5.5: score += 1
        elif avg_ip < 4.5: score -= 2

    avg_pitches = sig.get("avg_pitches_last3")
    if avg_pitches is not None:
        if avg_pitches >= 95: score += 1
        elif avg_pitches < 80: score -= 1

    rest = sig.get("days_rest")
    if rest is not None:
        if rest <= 3: score -= 2
        elif rest == 4: score -= 1
        elif 5 <= rest <= 7: pass
        elif 8 <= rest <= 10: score += 0.5
        else: score -= 1  # >10 days — likely rust from an extended layoff

    ev = sig.get("ev_10")
    if ev is not None:
        if ev > 3: score += 5
        elif ev > 1: score += 3
        elif ev > 0: score += 1
        elif ev > -1: score -= 1
        else: score -= 3

    return score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_signals.py::TestScorePitcher -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/k_predictor.py tests/test_k_signals.py
git commit -m "feat(k-model): add _score_pitcher deterministic scoring formula"
```

---

### Task 5: `fetch_k_odds_comparison()` — pitcher_strikeouts market

**Files:**
- Modify: `agents/k_predictor.py`
- Test: `tests/test_k_signals.py` (append)

**Interfaces:**
- Consumes: `_compute_ev`, `_compute_kelly`, `_american_to_implied_prob`, `ODDS_API_BASE` (already imported).
- Produces: `fetch_k_odds_comparison(confirmed_pitcher_names: set | None = None) -> str` — returns a JSON string with the same shape as Homer's `fetch_odds_comparison` (`status`, `players_found`, `comparisons: [{player, matchup, pinnacle, pinnacle_prob, best_book, best_odds, consensus_prob, value_edge, value_flag, ev_10, kelly_size, k_line, all_books}]`), keyed on `pitcher_strikeouts` market instead of `batter_home_runs`, and reading `outcome["point"]` as the actual strikeout line (not filtered to a fixed 0.5) since it's a real over/under line, not a fixed-threshold prop.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_k_signals.py`:

```python
class TestKOddsComparison:

    def test_parses_pitcher_strikeouts_market_into_comparisons(self):
        from agents.k_predictor import fetch_k_odds_comparison
        import json

        events_payload = [{"id": "evt1", "away_team": "NYY", "home_team": "BOS"}]
        odds_payload = {
            "bookmakers": [
                {
                    "key": "draftkings", "title": "DraftKings",
                    "markets": [{
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"description": "Gerrit Cole", "name": "Over", "point": 6.5, "price": -115},
                            {"description": "Gerrit Cole", "name": "Under", "point": 6.5, "price": -105},
                        ],
                    }],
                },
                {
                    "key": "pinnacle", "title": "Pinnacle",
                    "markets": [{
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"description": "Gerrit Cole", "name": "Over", "point": 6.5, "price": -120},
                        ],
                    }],
                },
            ]
        }

        events_resp = MagicMock()
        events_resp.status_code = 200
        events_resp.json.return_value = events_payload
        events_resp.raise_for_status.return_value = None

        odds_resp = MagicMock()
        odds_resp.status_code = 200
        odds_resp.json.return_value = odds_payload
        odds_resp.raise_for_status.return_value = None

        with patch("agents.k_predictor.os.getenv", return_value="fake_key"), \
             patch("agents.k_predictor.Path") as mock_path_cls, \
             patch("agents.k_predictor.requests.get", side_effect=[events_resp, odds_resp]):
            mock_path_cls.return_value.exists.return_value = False
            mock_path_cls.return_value.parent.mkdir.return_value = None
            result = json.loads(fetch_k_odds_comparison())

        assert result["status"] == "success"
        assert result["players_found"] == 1
        pick = result["comparisons"][0]
        assert pick["player"] == "Gerrit Cole"
        assert pick["k_line"] == 6.5
        assert pick["pinnacle"] == "-120"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_signals.py::TestKOddsComparison -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_k_odds_comparison'`

- [ ] **Step 3: Write minimal implementation**

Append to `agents/k_predictor.py` (add `import json, os` and `from pathlib import Path` if not already imported at top; `Path` is already imported in Task 2):

```python
import json
import os


def _fmt_odds(o: int | None) -> str:
    if o is None:
        return "—"
    return f"+{o}" if o > 0 else str(o)


def fetch_k_odds_comparison(confirmed_pitcher_names: set | None = None) -> str:
    """
    Fetch pitcher strikeout O/U prop odds from all available sportsbooks via
    The Odds API's pitcher_strikeouts market. Same Pinnacle-benchmark, EV,
    Kelly, and value-edge math as Homer's fetch_odds_comparison, but reads
    outcome["point"] as the real strikeout line (not a fixed 0.5 threshold)
    and only considers "Over" outcomes as the tracked pick side.
    """
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        return json.dumps({"status": "no_api_key", "message": "ODDS_API_KEY not set in api/.env"})

    today = date.today().isoformat()
    cache_path = Path("cache") / f"k_odds_{today}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if cached.get("status") == "success":
                return cache_path.read_text()
        except Exception:
            pass

    try:
        events_resp = requests.get(f"{ODDS_API_BASE}/sports/baseball_mlb/events?apiKey={api_key}", timeout=15)
        events_resp.raise_for_status()
        events = events_resp.json()
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    if not events:
        return json.dumps({"status": "no_events", "message": "No MLB events found today."})

    all_player_odds: dict[str, dict] = {}
    for event in events[:12]:
        event_id = event.get("id")
        matchup = f"{event.get('away_team', '')} @ {event.get('home_team', '')}"
        try:
            resp = requests.get(
                f"{ODDS_API_BASE}/sports/baseball_mlb/events/{event_id}/odds"
                f"?apiKey={api_key}&regions=us,eu&markets=pitcher_strikeouts&oddsFormat=american",
                timeout=15,
            )
            if resp.status_code in (401, 422):
                continue
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue

        for bookmaker in data.get("bookmakers", []):
            book_title = bookmaker.get("title", bookmaker.get("key", ""))
            is_pinnacle = bookmaker.get("key") == "pinnacle"
            for market in bookmaker.get("markets", []):
                if market.get("key") != "pitcher_strikeouts":
                    continue
                for outcome in market.get("outcomes", []):
                    if outcome.get("name") != "Over":
                        continue
                    player_name = (outcome.get("description") or "").strip()
                    price = outcome.get("price")
                    point = outcome.get("point")
                    if not player_name or price is None or point is None:
                        continue

                    if confirmed_pitcher_names is not None and player_name not in confirmed_pitcher_names:
                        continue

                    entry = all_player_odds.setdefault(player_name, {"matchup": matchup, "books": {}, "pinnacle": None, "k_line": point})
                    existing = entry["books"].get(book_title)
                    if existing is None or price > existing:
                        entry["books"][book_title] = price
                    if is_pinnacle:
                        curr = entry["pinnacle"]
                        if curr is None or price > curr:
                            entry["pinnacle"] = price

    if not all_player_odds:
        return json.dumps({"status": "no_data", "message": "No strikeout prop data returned yet."})

    results = []
    for player_name, info in all_player_odds.items():
        books = info["books"]
        if not books:
            continue
        probs = {book: _american_to_implied_prob(odds) for book, odds in books.items()}
        consensus_prob = sum(probs.values()) / len(probs)
        best_book = max(books, key=lambda b: books[b])
        best_odds_int = books[best_book]
        best_prob = probs[best_book]
        value_edge = consensus_prob - best_prob

        pinnacle_odds = info["pinnacle"]
        pinnacle_prob = _american_to_implied_prob(pinnacle_odds) if pinnacle_odds else None
        true_prob = pinnacle_prob if pinnacle_prob is not None else consensus_prob

        results.append({
            "player": player_name,
            "matchup": info["matchup"],
            "k_line": info["k_line"],
            "books_sampled": len(books),
            "pinnacle": _fmt_odds(pinnacle_odds),
            "pinnacle_prob": f"{pinnacle_prob * 100:.1f}%" if pinnacle_prob else f"{consensus_prob * 100:.1f}% (consensus)",
            "best_book": best_book,
            "best_odds": _fmt_odds(best_odds_int),
            "consensus_prob": f"{consensus_prob * 100:.1f}%",
            "value_edge": round(value_edge * 100, 1),
            "value_flag": "VALUE" if value_edge >= 0.03 else "",
            "ev_10": _compute_ev(true_prob, best_odds_int),
            "kelly_size": _compute_kelly(true_prob, best_odds_int),
            "all_books": {book: _fmt_odds(o) for book, o in sorted(books.items(), key=lambda x: x[1], reverse=True)},
        })

    results.sort(key=lambda x: x["value_edge"], reverse=True)
    out = json.dumps({"status": "success", "players_found": len(results), "comparisons": results}, indent=2)

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(out)
    except Exception:
        pass

    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_signals.py::TestKOddsComparison -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/k_predictor.py tests/test_k_signals.py
git commit -m "feat(k-model): add fetch_k_odds_comparison for pitcher_strikeouts market"
```

---

### Task 6: `Ace` class — `_gather_data`, `_rank_picks_python`, `get_picks_json`

**Files:**
- Modify: `agents/k_predictor.py`
- Test: `tests/test_k_signals.py` (append)

**Interfaces:**
- Consumes: `_fetch_pitcher_k_statcast`, `_fetch_pitch_arsenal_whiff`, `_weighted_opp_whiff`, `_score_pitcher`, `fetch_k_odds_comparison`, `_fetch_pitcher_recent_form` (all defined in Tasks 1-5). `MLB_API_BASE` for confirmed-starter lineup fetch.
- Produces: `Ace().get_picks_json(top_n=10) -> list[dict]`. Each dict: `{pitcher, matchup, confidence, reasoning, score, signals}` where `signals` carries every key `_score_pitcher` reads, for persistence via `save_pick_factors_k` (Task 7).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_k_signals.py`:

```python
class TestAceGetPicksJson:

    def test_returns_top_n_ranked_by_score(self):
        from agents.k_predictor import Ace

        ace = Ace()
        fake_signals = {
            "Gerrit Cole":   {"k_percent": 32.0, "whiff_percent": 33.0, "csw_percent": 34.0,
                              "swinging_strike_percent": 15.0, "k_per_9_blended": 12.0,
                              "pitcher_whiff_fastball": None, "pitcher_whiff_breaking": None,
                              "pitcher_whiff_offspeed": None, "opp_whiff_vs_mix": None,
                              "avg_ip_last3": 6.0, "avg_pitches_last3": 95.0, "days_rest": 5,
                              "ev_10": 2.0, "value_edge": 1.0, "matchup": "NYY @ BOS"},
            "Some Rookie":   {"k_percent": 18.0, "whiff_percent": 19.0, "csw_percent": 24.0,
                              "swinging_strike_percent": 8.0, "k_per_9_blended": 5.5,
                              "pitcher_whiff_fastball": None, "pitcher_whiff_breaking": None,
                              "pitcher_whiff_offspeed": None, "opp_whiff_vs_mix": None,
                              "avg_ip_last3": 4.0, "avg_pitches_last3": 70.0, "days_rest": 5,
                              "ev_10": -2.0, "value_edge": -1.0, "matchup": "SF @ LAD"},
        }
        with patch.object(Ace, "_gather_data", return_value={"pitcher_signals": fake_signals}):
            picks = ace.get_picks_json(top_n=10)

        assert len(picks) == 2
        assert picks[0]["pitcher"] == "Gerrit Cole"  # higher score ranks first
        assert picks[0]["score"] > picks[1]["score"]
        assert "signals" in picks[0]

    def test_caps_at_top_n(self):
        from agents.k_predictor import Ace

        ace = Ace()
        fake_signals = {
            f"Pitcher {i}": {"k_percent": 20.0 + i, "whiff_percent": 24.0, "csw_percent": 28.0,
                             "swinging_strike_percent": 10.0, "k_per_9_blended": 7.0,
                             "pitcher_whiff_fastball": None, "pitcher_whiff_breaking": None,
                             "pitcher_whiff_offspeed": None, "opp_whiff_vs_mix": None,
                             "avg_ip_last3": 5.5, "avg_pitches_last3": 88.0, "days_rest": 5,
                             "ev_10": 0.0, "value_edge": 0.0, "matchup": "X @ Y"}
            for i in range(15)
        }
        with patch.object(Ace, "_gather_data", return_value={"pitcher_signals": fake_signals}):
            picks = ace.get_picks_json(top_n=10)

        assert len(picks) == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_signals.py::TestAceGetPicksJson -v`
Expected: FAIL — `ImportError: cannot import name 'Ace'`

- [ ] **Step 3: Write minimal implementation**

Append to `agents/k_predictor.py`:

```python
class Ace:
    """
    Sibling to Homer — ranks starting pitchers for strikeout props.
    Deterministic scoring (_score_pitcher) with an ML blend once
    ml_weights_k.json / lgbm_model_k.txt exist (mirrors Homer's blend).
    """

    def __init__(self):
        self._context = None

    def _gather_data(self) -> dict:
        """
        Fetch confirmed starting pitchers, their Statcast K-rate + pitch-mix
        signals, opposing-lineup matchup whiff, recent form/workload/rest,
        and odds. Only pitchers with a CONFIRMED starting assignment are
        included — no roster-fallback concept for starters (see spec).
        Result cached on the instance.
        """
        if self._context:
            return self._context

        today = date.today().isoformat()
        resp = requests.get(
            f"{MLB_API_BASE}/schedule",
            params={"sportId": 1, "date": today, "hydrate": "probablePitcher,lineups(person),team"},
            timeout=15,
        )
        resp.raise_for_status()
        schedule = resp.json()

        confirmed_names = set()
        starters = []  # [(pitcher_id, name, matchup, opposing_lineup_ids)]
        for date_block in schedule.get("dates", []):
            for game in date_block.get("games", []):
                teams = game.get("teams", {})
                away = teams.get("away", {})
                home = teams.get("home", {})
                matchup = f"{away.get('team', {}).get('name', '')} @ {home.get('team', {}).get('name', '')}"
                for side_key, opp_key in (("away", "home"), ("home", "away")):
                    side = teams.get(side_key, {})
                    pitcher = side.get("probablePitcher")
                    if not pitcher or not pitcher.get("id"):
                        continue
                    opp_lineup = game.get(opp_key, {}).get("lineup", []) if isinstance(game.get(opp_key), dict) else []
                    starters.append((pitcher["id"], pitcher.get("fullName", ""), matchup, opp_lineup))
                    confirmed_names.add(pitcher.get("fullName", ""))

        pitcher_ids = [pid for pid, *_ in starters]
        k_statcast = _fetch_pitcher_k_statcast()
        pitcher_whiff = _fetch_pitch_arsenal_whiff(pitcher_ids, player_type="pitcher")
        odds_raw = json.loads(fetch_k_odds_comparison(confirmed_names))
        odds_by_player = {c["player"]: c for c in odds_raw.get("comparisons", [])}

        pitcher_signals = {}
        for pid, name, matchup, opp_lineup_ids in starters:
            statcast_row = k_statcast.get(pid) or k_statcast.get(name.lower(), {})
            form = _fetch_pitcher_recent_form(pid)
            whiff_splits = pitcher_whiff.get(pid, {})
            odds_entry = odds_by_player.get(name, {})

            sig = {
                "k_percent": _tofloat(statcast_row.get("k_percent")),
                "whiff_percent": _tofloat(statcast_row.get("whiff_percent")),
                "csw_percent": _tofloat(statcast_row.get("csw_percent")),
                "swinging_strike_percent": _tofloat(statcast_row.get("swinging_strike_percent")),
                "k_per_9_blended": form.get("k_per_9_blended"),
                "avg_ip_last3": form.get("avg_ip_last3"),
                "avg_pitches_last3": form.get("avg_pitches_last3"),
                "days_rest": form.get("days_rest"),
                "pitcher_whiff_fastball": whiff_splits.get("whiff_fastball"),
                "pitcher_whiff_breaking": whiff_splits.get("whiff_breaking"),
                "pitcher_whiff_offspeed": whiff_splits.get("whiff_offspeed"),
                "opp_whiff_vs_mix": None,  # populated below once lineup IDs resolve
                "ev_10": odds_entry.get("ev_10"),
                "value_edge": odds_entry.get("value_edge"),
                "kelly_size": odds_entry.get("kelly_size"),
                "pinnacle_odds": odds_entry.get("pinnacle"),
                "k_line": odds_entry.get("k_line"),
                "matchup": matchup,
            }
            pitcher_signals[name] = sig

        self._context = {"date": today, "pitcher_signals": pitcher_signals}
        return self._context

    def _rank_picks_python(self, pitcher_signals: dict, top_n: int = 10) -> list:
        ranked = []
        for name, sig in pitcher_signals.items():
            score = _score_pitcher(sig)
            ranked.append({
                "pitcher": name,
                "matchup": sig.get("matchup", ""),
                "confidence": _confidence_tier(score),
                "reasoning": _build_reasoning(name, sig),
                "score": score,
                "signals": sig,
            })
        ranked.sort(key=lambda p: p["score"], reverse=True)
        return ranked[:top_n]

    def get_picks_json(self, top_n: int = 10) -> list:
        """Return today's top strikeout picks as a structured list of dicts."""
        context = self._gather_data()
        return self._rank_picks_python(context.get("pitcher_signals", {}), top_n=top_n)


def _tofloat(val):
    if val in (None, "", "null"):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _confidence_tier(score: float) -> str:
    if score >= 12:
        return "HIGH"
    if score >= 6:
        return "MEDIUM"
    return "LOW"


def _build_reasoning(name: str, sig: dict) -> str:
    parts = []
    if sig.get("k_per_9_blended") is not None:
        parts.append(f"{sig['k_per_9_blended']:.1f} K/9 (blended)")
    if sig.get("avg_ip_last3") is not None:
        parts.append(f"{sig['avg_ip_last3']:.1f} IP/start last 3")
    if sig.get("value_edge") is not None and sig["value_edge"] >= 3:
        parts.append("VALUE line")
    return f"{name}: " + ", ".join(parts) if parts else name
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_signals.py::TestAceGetPicksJson -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Full test suite regression check**

Run: `python -m pytest tests/ -v -k "not network"`
Expected: all previously-passing tests still pass; new `test_k_signals.py` tests pass.

- [ ] **Step 6: Commit**

```bash
git add agents/k_predictor.py tests/test_k_signals.py
git commit -m "feat(k-model): add Ace class — gather, rank, and publish top-N K picks"
```

---

### Task 7: `pick_factors_k` DB table + `save_pick_factors_k()`

**Files:**
- Modify: `agents/bet_tracker.py`
- Test: `tests/test_k_pick_factors_db.py` (new)

**Interfaces:**
- Consumes: `get_db_conn` (already in `agents/bet_tracker.py`, imported from `agents.base`).
- Produces: `save_pick_factors_k(bet_date: str, pitcher: str, signals: dict, confidence: str = None, algo_version: str = "1.0", score: float = None, rank: int = None, game_pk: str = None) -> str`. Table `pick_factors_k` with `UNIQUE(bet_date, pitcher, game_pk)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_k_pick_factors_db.py`:

```python
"""Tests for the pick_factors_k table and save_pick_factors_k()."""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_save_pick_factors_k_creates_table_and_inserts_row(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))

    signals = {
        "k_percent": 30.0, "whiff_percent": 29.0, "csw_percent": 32.0,
        "swinging_strike_percent": 13.0, "k_per_9_blended": 10.5,
        "pitcher_whiff_fastball": 28.0, "pitcher_whiff_breaking": 35.0,
        "pitcher_whiff_offspeed": 22.0, "opp_whiff_vs_mix": 25.0,
        "avg_ip_last3": 6.0, "avg_pitches_last3": 94.0, "days_rest": 5,
        "ev_10": 2.5, "value_edge": 2.0, "kelly_size": 8.0,
        "pinnacle_odds": "-115", "k_line": 6.5,
    }
    bet_tracker.save_pick_factors_k(
        "2026-08-18", "Gerrit Cole", signals,
        confidence="HIGH", algo_version="1.0", score=15.5, rank=1, game_pk="778899",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT pitcher, k_percent, k_per_9_blended, rank, confidence FROM pick_factors_k "
        "WHERE bet_date=? AND pitcher=?", ("2026-08-18", "Gerrit Cole")
    ).fetchone()
    conn.close()

    assert row == ("Gerrit Cole", 30.0, 10.5, 1, "HIGH")


def test_save_pick_factors_k_upserts_on_conflict(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))

    sig = {"k_percent": 20.0}
    bet_tracker.save_pick_factors_k("2026-08-18", "Cole", sig, score=5.0, rank=3, game_pk="1")
    bet_tracker.save_pick_factors_k("2026-08-18", "Cole", sig, score=7.0, rank=1, game_pk="1")

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT score, rank FROM pick_factors_k WHERE bet_date=? AND pitcher=?", ("2026-08-18", "Cole")
    ).fetchall()
    conn.close()

    assert rows == [(7.0, 1)]  # updated in place, not duplicated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_pick_factors_db.py -v`
Expected: FAIL — `AttributeError: module 'agents.bet_tracker' has no attribute 'save_pick_factors_k'`

- [ ] **Step 3: Write minimal implementation**

Append to `agents/bet_tracker.py`:

```python
_CREATE_PICK_FACTORS_K = """
CREATE TABLE IF NOT EXISTS pick_factors_k (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_date                 TEXT NOT NULL,
    pitcher                  TEXT NOT NULL,
    game_pk                  TEXT,
    matchup                  TEXT,
    algo_version              TEXT,
    confidence                TEXT,
    score                     REAL,
    rank                      INTEGER,
    k_percent                 REAL,
    whiff_percent             REAL,
    csw_percent                REAL,
    swinging_strike_percent    REAL,
    k_per_9_blended            REAL,
    pitcher_whiff_fastball      REAL,
    pitcher_whiff_breaking      REAL,
    pitcher_whiff_offspeed      REAL,
    opp_whiff_vs_mix            REAL,
    avg_ip_last3                 REAL,
    avg_pitches_last3            REAL,
    days_rest                    INTEGER,
    ev_10                        REAL,
    kelly_size                    REAL,
    value_edge                    REAL,
    pinnacle_odds                  TEXT,
    k_line                          REAL,
    actual_k                        INTEGER,
    over_hit                        INTEGER,
    UNIQUE(bet_date, pitcher, game_pk)
)
"""

_K_MIGRATION_COLUMNS = [
    ("actual_k", "INTEGER"),
    ("over_hit", "INTEGER"),
]


def _ensure_pick_factors_k_table():
    conn = get_db_conn()
    try:
        conn.execute(_CREATE_PICK_FACTORS_K)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(pick_factors_k)").fetchall()}
        for col_name, col_type in _K_MIGRATION_COLUMNS:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE pick_factors_k ADD COLUMN {col_name} {col_type}")
        conn.commit()
    finally:
        conn.close()


def save_pick_factors_k(bet_date: str, pitcher: str, signals: dict,
                        confidence: str = None, algo_version: str = "1.0",
                        score: float = None, rank: int = None,
                        game_pk: str = None) -> str:
    """Save (or update, on conflict) a strikeout-pick signal snapshot."""
    _ensure_pick_factors_k_table()
    conn = get_db_conn()
    try:
        conn.execute("""
            INSERT INTO pick_factors_k
              (bet_date, pitcher, game_pk, matchup, algo_version, confidence, score, rank,
               k_percent, whiff_percent, csw_percent, swinging_strike_percent, k_per_9_blended,
               pitcher_whiff_fastball, pitcher_whiff_breaking, pitcher_whiff_offspeed,
               opp_whiff_vs_mix, avg_ip_last3, avg_pitches_last3, days_rest,
               ev_10, kelly_size, value_edge, pinnacle_odds, k_line)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(bet_date, pitcher, game_pk) DO UPDATE SET
              matchup=excluded.matchup, algo_version=excluded.algo_version,
              confidence=excluded.confidence, score=excluded.score, rank=excluded.rank,
              k_percent=excluded.k_percent, whiff_percent=excluded.whiff_percent,
              csw_percent=excluded.csw_percent, swinging_strike_percent=excluded.swinging_strike_percent,
              k_per_9_blended=excluded.k_per_9_blended,
              pitcher_whiff_fastball=excluded.pitcher_whiff_fastball,
              pitcher_whiff_breaking=excluded.pitcher_whiff_breaking,
              pitcher_whiff_offspeed=excluded.pitcher_whiff_offspeed,
              opp_whiff_vs_mix=excluded.opp_whiff_vs_mix,
              avg_ip_last3=excluded.avg_ip_last3, avg_pitches_last3=excluded.avg_pitches_last3,
              days_rest=excluded.days_rest, ev_10=excluded.ev_10, kelly_size=excluded.kelly_size,
              value_edge=excluded.value_edge, pinnacle_odds=excluded.pinnacle_odds, k_line=excluded.k_line
        """, (
            bet_date, pitcher, game_pk or signals.get("game_pk"), signals.get("matchup"),
            algo_version, confidence or signals.get("confidence"), score, rank,
            signals.get("k_percent"), signals.get("whiff_percent"), signals.get("csw_percent"),
            signals.get("swinging_strike_percent"), signals.get("k_per_9_blended"),
            signals.get("pitcher_whiff_fastball"), signals.get("pitcher_whiff_breaking"),
            signals.get("pitcher_whiff_offspeed"), signals.get("opp_whiff_vs_mix"),
            signals.get("avg_ip_last3"), signals.get("avg_pitches_last3"), signals.get("days_rest"),
            signals.get("ev_10"), signals.get("kelly_size"), signals.get("value_edge"),
            signals.get("pinnacle_odds"), signals.get("k_line"),
        ))
        conn.commit()
    finally:
        conn.close()
    return "saved"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_pick_factors_db.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/bet_tracker.py tests/test_k_pick_factors_db.py
git commit -m "feat(k-model): add pick_factors_k table and save_pick_factors_k()"
```

---

### Task 8: `ml/optimize_weights_k.py` — LightGBM trainer

**Files:**
- Create: `ml/optimize_weights_k.py`
- Test: `tests/test_ml_features.py` (append — mirrors the existing `test_all_features_have_a_save_pick_factors_write_path` pattern)

**Interfaces:**
- Consumes: `pick_factors_k` table (Task 7), `_score_pitcher` (Task 4, for optional correlation report cross-check — not required by training itself).
- Produces: `FEATURES_K` / `FEATURE_NAMES_K` (module-level list), `train_and_save_k(X, y, save=True) -> dict`, saving `ml_weights_k.json` + `lgbm_model_k.txt`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ml_features.py`:

```python
def test_k_features_have_a_save_pick_factors_k_write_path():
    """
    Same regression guard as the HR model's equivalent test — every column
    in FEATURES_K must be written by save_pick_factors_k() via
    signals.get("<col>"), or it's silently always-NULL in pick_factors_k.
    """
    from ml.optimize_weights_k import FEATURE_NAMES_K
    from agents import bet_tracker
    source = inspect.getsource(bet_tracker.save_pick_factors_k)
    referenced = set(re.findall(r'signals\.get\("([^"]+)"\)', source))

    missing = [name for name in FEATURE_NAMES_K if name not in referenced]
    assert missing == [], (
        f"FEATURES_K columns with no signals.get(...) write path in "
        f"save_pick_factors_k(): {missing}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ml_features.py::test_k_features_have_a_save_pick_factors_k_write_path -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.optimize_weights_k'`

- [ ] **Step 3: Write minimal implementation**

Create `ml/optimize_weights_k.py`:

```python
"""
optimize_weights_k.py
Train LightGBM on labeled pick_factors_k data → ml_weights_k.json + lgbm_model_k.txt.
Ace's _ml_score (once added) reads these automatically once the files exist.
Mirrors ml/optimize_weights.py's structure exactly — see that file for the
full CLI/reporting pattern this was adapted from.

Usage:
    python ml/optimize_weights_k.py              # train + save weights
    python ml/optimize_weights_k.py --report      # report only
    python ml/optimize_weights_k.py --min 50      # min labeled rows required (default 100)
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np

os.chdir(str(Path(__file__).parent.parent))
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "bets.db")
WEIGHTS_PATH_K = os.path.join(os.path.dirname(__file__), "..", "ml_weights_k.json")
LGBM_MODEL_PATH_K = os.path.join(os.path.dirname(__file__), "..", "lgbm_model_k.txt")

FEATURES_K = [
    ("k_percent", None),
    ("whiff_percent", None),
    ("csw_percent", None),
    ("swinging_strike_percent", None),
    ("k_per_9_blended", None),
    ("pitcher_whiff_fastball", None),
    ("pitcher_whiff_breaking", None),
    ("pitcher_whiff_offspeed", None),
    ("opp_whiff_vs_mix", None),
    ("avg_ip_last3", None),
    ("avg_pitches_last3", None),
    ("days_rest", None),
    ("ev_10", None),
    ("value_edge", None),
]

FEATURE_NAMES_K = [name for name, _ in FEATURES_K]


def load_training_data() -> tuple[np.ndarray, np.ndarray, list[dict]]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = ", ".join(name for name, _ in FEATURES_K)
        rows = conn.execute(f"""
            SELECT {cols}, over_hit, bet_date, pitcher, score, rank, confidence
            FROM pick_factors_k
            WHERE over_hit IS NOT NULL
            ORDER BY bet_date
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        return np.array([]), np.array([]), []

    n_features = len(FEATURES_K)
    raw_rows, X_raw, y = [], [], []
    for row in rows:
        feat_vals = list(row[:n_features])
        over_hit, bet_date, pitcher, score, rank_val, conf = row[n_features:n_features + 6]
        X_raw.append([float(v) if v is not None else np.nan for v in feat_vals])
        y.append(int(over_hit))
        raw_rows.append({"pitcher": pitcher, "bet_date": bet_date, "score": score, "rank": rank_val, "confidence": conf, "over_hit": over_hit})

    X = np.array(X_raw, dtype=float)
    for col_i in range(X.shape[1]):
        col = X[:, col_i]
        median = np.nanmedian(col)
        X[np.isnan(col), col_i] = median if not np.isnan(median) else 0.0
    return X, np.array(y), raw_rows


def train_and_save_k(X: np.ndarray, y: np.ndarray, save: bool = True) -> dict:
    try:
        import lightgbm as lgb
        import pandas as pd
        from sklearn.model_selection import cross_val_score, StratifiedKFold
    except ImportError:
        print("\n  lightgbm not installed. Run: pip install lightgbm")
        return {}

    X_df = pd.DataFrame(X, columns=FEATURE_NAMES_K)
    scale_pos_weight = (len(y) - y.sum()) / max(y.sum(), 1)
    model = lgb.LGBMClassifier(
        objective="binary", metric="auc", n_estimators=500, learning_rate=0.05,
        num_leaves=31, min_child_samples=50, scale_pos_weight=scale_pos_weight,
        random_state=42, verbose=-1,
    )
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    auc_scores = cross_val_score(model, X_df, y, cv=cv, scoring="roc_auc")
    print(f"\n  Cross-val AUC: {auc_scores.mean():.3f} ± {auc_scores.std():.3f}")

    model.fit(X_df, y)
    weights = {
        "model_type": "lightgbm", "trained_on": date.today().isoformat(),
        "n_samples": int(len(y)), "n_positives": int(y.sum()),
        "cv_auc_mean": float(auc_scores.mean()), "cv_auc_std": float(auc_scores.std()),
        "feature_order": FEATURE_NAMES_K, "algo_version": "1.0",
    }
    if save:
        model.booster_.save_model(LGBM_MODEL_PATH_K)
        with open(WEIGHTS_PATH_K, "w") as f:
            json.dump(weights, f, indent=2)
        print(f"\n  Model saved to lgbm_model_k.txt / ml_weights_k.json")
    return weights


def main():
    parser = argparse.ArgumentParser(description="Train LightGBM on K prop pick data.")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--min", type=int, default=100, dest="min_rows")
    args = parser.parse_args()

    X, y, raw_rows = load_training_data()
    if len(y) == 0:
        print("\n  No labeled K-prop data yet. Run fetch_actual_k_results.py after game days.")
        sys.exit(0)
    if len(y) < args.min_rows:
        print(f"\n  Only {len(y)} labeled rows — need {args.min_rows} to train reliably.")
        sys.exit(0)

    train_and_save_k(X, y, save=not args.report)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ml_features.py -v`
Expected: PASS (all tests, including the new K-model regression check)

- [ ] **Step 5: Commit**

```bash
git add ml/optimize_weights_k.py tests/test_ml_features.py
git commit -m "feat(k-model): add LightGBM trainer for strikeout pick_factors_k"
```

---

### Task 8.5: Wire the LightGBM blend into `Ace`'s scoring

**Files:**
- Modify: `agents/k_predictor.py` (`Ace._rank_picks_python`, add `Ace._ml_score`)
- Test: `tests/test_k_signals.py` (append)

**Interfaces:**
- Consumes: `ml_weights_k.json` / `lgbm_model_k.txt` (produced by Task 8's `train_and_save_k`), `FEATURE_NAMES_K` (from `ml.optimize_weights_k`).
- Produces: `Ace._ml_score(sig: dict) -> float | None` (returns `None` when no model files exist yet — mirrors `Homer._ml_score`'s cold-start behavior exactly); `_rank_picks_python` now blends it into the final score using the identical formula from `agents/predictor.py`'s `_score_player`: `ml_weight = min(0.7, max(0.0, (auc - 0.5) * 2.5))`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_k_signals.py`:

```python
class TestAceMlBlend:

    def test_ml_score_returns_none_when_no_model_file(self):
        from agents.k_predictor import Ace
        Ace._ml_weights_loaded = False
        Ace._ml_weights = None

        with patch("agents.k_predictor.Path.exists", return_value=False):
            result = Ace._ml_score(_base_k_sig())

        assert result is None

    def test_rank_picks_blends_ml_score_when_model_present(self):
        from agents.k_predictor import Ace

        ace = Ace()
        fake_signals = {
            "Gerrit Cole": {**_base_k_sig(), "matchup": "NYY @ BOS"},
        }
        with patch.object(Ace, "_ml_score", return_value=18.0), \
             patch.object(Ace, "_ml_weights", {"cv_auc_mean": 0.65}), \
             patch.object(Ace, "_ml_weights_loaded", True):
            picks = ace._rank_picks_python(fake_signals, top_n=10)

        raw_score = picks[0]["score"]
        # ml_weight at AUC=0.65 → min(0.7, (0.65-0.5)*2.5) = 0.375
        # Final score should differ from the pure heuristic score
        from agents.k_predictor import _score_pitcher
        pure_score = _score_pitcher(_base_k_sig())
        assert raw_score != pure_score
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_signals.py::TestAceMlBlend -v`
Expected: FAIL — `AttributeError: type object 'Ace' has no attribute '_ml_score'`

- [ ] **Step 3: Write minimal implementation**

In `agents/k_predictor.py`, add class-level cache attributes and the blend, mirroring `Homer._ml_score`/`Homer._ml_weights` in `agents/predictor.py`:

```python
class Ace:
    _ml_weights = None
    _ml_weights_loaded = False
    _ml_booster = None

    def __init__(self):
        self._context = None

    @staticmethod
    def _ml_score(sig: dict) -> float | None:
        """Score a signal dict with the trained LightGBM K-model. Returns
        None if ml_weights_k.json / lgbm_model_k.txt don't exist yet
        (cold start) — mirrors Homer._ml_score's fallback behavior."""
        from ml.optimize_weights_k import FEATURE_NAMES_K, WEIGHTS_PATH_K, LGBM_MODEL_PATH_K

        if not Ace._ml_weights_loaded:
            Ace._ml_weights_loaded = True
            weights_path = Path(WEIGHTS_PATH_K)
            model_path = Path(LGBM_MODEL_PATH_K)
            if weights_path.exists() and model_path.exists():
                try:
                    import lightgbm as lgb
                    Ace._ml_weights = json.loads(weights_path.read_text())
                    Ace._ml_booster = lgb.Booster(model_file=str(model_path))
                except Exception:
                    Ace._ml_weights = None
                    Ace._ml_booster = None

        if Ace._ml_weights is None or Ace._ml_booster is None:
            return None

        row = [sig.get(name) if sig.get(name) is not None else 0.0 for name in FEATURE_NAMES_K]
        try:
            pred = Ace._ml_booster.predict([row])[0]
            return float(pred) * 20.0  # scale probability [0,1] to score range, matches Homer's convention
        except Exception:
            return None
```

Then modify `_rank_picks_python` (replace the `score = _score_pitcher(sig)` line from Task 6):

```python
    def _rank_picks_python(self, pitcher_signals: dict, top_n: int = 10) -> list:
        ranked = []
        for name, sig in pitcher_signals.items():
            raw_score = _score_pitcher(sig)
            ml = Ace._ml_score(sig)
            if ml is not None and Ace._ml_weights:
                auc = Ace._ml_weights.get("cv_auc_mean", 0.5)
                ml_weight = min(0.7, max(0.0, (auc - 0.5) * 2.5))
                score = (1.0 - ml_weight) * raw_score + ml_weight * ml
            else:
                score = raw_score
            ranked.append({
                "pitcher": name,
                "matchup": sig.get("matchup", ""),
                "confidence": _confidence_tier(score),
                "reasoning": _build_reasoning(name, sig),
                "score": score,
                "signals": sig,
            })
        ranked.sort(key=lambda p: p["score"], reverse=True)
        return ranked[:top_n]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_signals.py::TestAceMlBlend -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Full regression check**

Run: `python -m pytest tests/ -v -k "not network"`
Expected: all tests pass, including every `Ace`/`Homer` test from earlier tasks.

- [ ] **Step 6: Commit**

```bash
git add agents/k_predictor.py tests/test_k_signals.py
git commit -m "feat(k-model): wire LightGBM blend into Ace scoring, mirrors Homer's ml_weight formula"
```

---

### Task 9: `ml/fetch_actual_k_results.py` — label actual strikeout results

**Files:**
- Create: `ml/fetch_actual_k_results.py`
- Test: `tests/test_k_pick_factors_db.py` (append)

**Interfaces:**
- Consumes: `MLB_API_BASE` (import from `agents.predictor`), `get_db_conn` (from `agents.bet_tracker`).
- Produces: `fetch_strikeouts_for_date(game_date: str) -> dict[str, int] | None` (pitcher name → actual K's, from completed-game boxscores), `update_pick_factors_k(game_date: str, actual_ks: dict[str, int], dry_run: bool = False) -> None` (fuzzy-matches ≥0.85 via `SequenceMatcher`, sets `actual_k` and `over_hit = 1 if actual_k > k_line else 0`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_k_pick_factors_db.py`:

```python
def test_update_pick_factors_k_sets_over_hit(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))
    bet_tracker.save_pick_factors_k(
        "2026-08-17", "Gerrit Cole", {"k_line": 6.5}, score=10.0, rank=1, game_pk="1",
    )

    from ml import fetch_actual_k_results
    monkeypatch.setattr(fetch_actual_k_results, "get_db_conn", lambda: sqlite3.connect(db_path))
    fetch_actual_k_results.update_pick_factors_k("2026-08-17", {"Gerrit Cole": 9})

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT actual_k, over_hit FROM pick_factors_k WHERE bet_date=? AND pitcher=?",
        ("2026-08-17", "Gerrit Cole"),
    ).fetchone()
    conn.close()
    assert row == (9, 1)  # 9 > 6.5 line


def test_update_pick_factors_k_under_sets_zero(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))
    bet_tracker.save_pick_factors_k(
        "2026-08-17", "Gerrit Cole", {"k_line": 6.5}, score=10.0, rank=1, game_pk="1",
    )

    from ml import fetch_actual_k_results
    monkeypatch.setattr(fetch_actual_k_results, "get_db_conn", lambda: sqlite3.connect(db_path))
    fetch_actual_k_results.update_pick_factors_k("2026-08-17", {"Gerrit Cole": 4})

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT actual_k, over_hit FROM pick_factors_k WHERE bet_date=? AND pitcher=?",
        ("2026-08-17", "Gerrit Cole"),
    ).fetchone()
    conn.close()
    assert row == (4, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_pick_factors_db.py -k update_pick_factors_k -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.fetch_actual_k_results'`

- [ ] **Step 3: Write minimal implementation**

Create `ml/fetch_actual_k_results.py`:

```python
"""
fetch_actual_k_results.py
Labels yesterday's pick_factors_k rows with actual strikeout totals from
MLB boxscores. Mirrors ml/fetch_actual_results.py's fuzzy-match pattern.
"""
from difflib import SequenceMatcher

import requests

from agents.predictor import MLB_API_BASE
from agents.bet_tracker import get_db_conn


def fetch_strikeouts_for_date(game_date: str) -> dict[str, int] | None:
    """Return {pitcher_name: strikeouts} for all completed games on game_date."""
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/schedule",
            params={"date": game_date, "sportId": 1, "hydrate": "linescore"},
            timeout=15,
        )
        resp.raise_for_status()
        schedule = resp.json()
    except Exception:
        return None

    strikeouts: dict[str, int] = {}
    found_completed = False
    for date_block in schedule.get("dates", []):
        for game in date_block.get("games", []):
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue
            found_completed = True
            game_pk = game.get("gamePk")
            try:
                box_resp = requests.get(f"{MLB_API_BASE}/game/{game_pk}/boxscore", timeout=15)
                box_resp.raise_for_status()
                boxscore = box_resp.json()
            except Exception:
                continue
            for side in ("away", "home"):
                players = boxscore.get("teams", {}).get(side, {}).get("players", {})
                for player in players.values():
                    pitching = player.get("stats", {}).get("pitching")
                    if not pitching:
                        continue
                    name = player.get("person", {}).get("fullName", "")
                    so = int(pitching.get("strikeOuts") or 0)
                    if name:
                        strikeouts[name] = so

    return strikeouts if found_completed else None


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def update_pick_factors_k(game_date: str, actual_ks: dict[str, int], dry_run: bool = False) -> None:
    """Fuzzy-match (>=0.85) pick_factors_k rows on game_date to actual_ks and set actual_k/over_hit."""
    conn = get_db_conn()
    try:
        rows = conn.execute(
            "SELECT id, pitcher, k_line FROM pick_factors_k WHERE bet_date=? AND actual_k IS NULL",
            (game_date,),
        ).fetchall()
        names = list(actual_ks.keys())
        for row_id, pitcher, k_line in rows:
            best_name, best_score = None, 0.0
            for name in names:
                score = _similarity(pitcher, name)
                if score > best_score:
                    best_name, best_score = name, score
            if best_score < 0.85 or best_name is None:
                continue
            actual = actual_ks[best_name]
            over_hit = 1 if (k_line is not None and actual > k_line) else 0
            if not dry_run:
                conn.execute(
                    "UPDATE pick_factors_k SET actual_k=?, over_hit=? WHERE id=?",
                    (actual, over_hit, row_id),
                )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_pick_factors_db.py -v`
Expected: PASS (4 tests total in this file)

- [ ] **Step 5: Commit**

```bash
git add ml/fetch_actual_k_results.py tests/test_k_pick_factors_db.py
git commit -m "feat(k-model): label pick_factors_k rows with actual strikeout results"
```

---

### Task 10: `ml/build_historical_k_dataset.py` — historical bootstrap

**Files:**
- Create: `ml/build_historical_k_dataset.py`
- Test: `tests/test_k_pick_factors_db.py` (append — schema-level check only; full network-dependent flow is exercised manually, see Step 5)

**Interfaces:**
- Consumes: `fetch_season_schedule` from `ml.build_historical_dataset` (existing, unmodified — reused verbatim per its documented signature `fetch_season_schedule(year, dates) -> {date_str: [{"game_pk", "venue", "home_players", "away_players", "home_pitcher_id", "away_pitcher_id"}]}`).
- Produces: `fetch_pitcher_k_events_season(year) -> dict[str, list[str]]` (date → list of pitcher names who started that day, from Savant), `write_k_season_to_db(year, schedule, dry_run=False) -> tuple[int, int]` (inserts historical `pick_factors_k` rows with `over_hit` back-derived from actual boxscore strikeouts pulled via `fetch_actual_k_results.fetch_strikeouts_for_date`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_k_pick_factors_db.py`:

```python
def test_write_k_season_to_db_inserts_rows_with_over_hit(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))

    from ml import build_historical_k_dataset as bhkd
    monkeypatch.setattr(bhkd, "get_db_conn", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(
        bhkd, "fetch_strikeouts_for_date",
        lambda game_date: {"Gerrit Cole": 8},
    )

    schedule = {
        "2025-06-01": [{
            "game_pk": "999", "venue": "Yankee Stadium",
            "home_pitcher_id": 543037, "away_pitcher_id": None,
            "home_pitcher_name": "Gerrit Cole", "away_pitcher_name": None,
        }]
    }
    n_written, n_skipped = bhkd.write_k_season_to_db(2025, schedule)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT pitcher, actual_k, over_hit FROM pick_factors_k WHERE bet_date=?",
        ("2025-06-01",),
    ).fetchone()
    conn.close()

    assert n_written == 1
    assert row[0] == "Gerrit Cole"
    assert row[1] == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_k_pick_factors_db.py -k write_k_season_to_db -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ml.build_historical_k_dataset'`

- [ ] **Step 3: Write minimal implementation**

Create `ml/build_historical_k_dataset.py`:

```python
"""
build_historical_k_dataset.py
Bootstrap historical pick_factors_k rows so the K model can train on day
one instead of waiting ~2 weeks for live data (mirrors the rationale in
ml/build_historical_dataset.py — see notes/ALGORITHM.md's 2026-07-06 entry
for why real game-day context beats a static cross-product).

Reuses fetch_season_schedule from ml/build_historical_dataset.py verbatim
for real game-day starters. This script only adds the K-specific labeling
(actual strikeouts → over_hit) on top of that shared schedule fetch.

Run once per season to backfill; safe to re-run (INSERT OR IGNORE-style
upsert via save_pick_factors_k's ON CONFLICT).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.bet_tracker import get_db_conn, save_pick_factors_k
from ml.build_historical_dataset import fetch_season_schedule
from ml.fetch_actual_k_results import fetch_strikeouts_for_date


def write_k_season_to_db(year: int, schedule: dict, dry_run: bool = False) -> tuple[int, int]:
    """
    For each game-day in schedule, label the home/away probable pitcher's
    row with actual strikeouts pulled from that day's boxscore, and no
    k_line (historical odds aren't available — over_hit is left NULL for
    rows without a line; AUC/training only uses rows where it's set once
    live odds-carrying rows accumulate alongside these).
    """
    written, skipped = 0, 0
    for game_date, games in schedule.items():
        actual_ks = fetch_strikeouts_for_date(game_date)
        if not actual_ks:
            skipped += len(games)
            continue
        for game in games:
            for side in ("home", "away"):
                pid = game.get(f"{side}_pitcher_id")
                name = game.get(f"{side}_pitcher_name")
                if not pid or not name:
                    continue
                actual = actual_ks.get(name)
                if actual is None:
                    skipped += 1
                    continue
                if not dry_run:
                    save_pick_factors_k(
                        game_date, name,
                        {"actual_k": actual, "k_line": None},
                        algo_version="historical-1.0",
                        game_pk=str(game.get("game_pk")),
                    )
                    conn = get_db_conn()
                    try:
                        conn.execute(
                            "UPDATE pick_factors_k SET actual_k=? WHERE bet_date=? AND pitcher=? AND game_pk=?",
                            (actual, game_date, name, str(game.get("game_pk"))),
                        )
                        conn.commit()
                    finally:
                        conn.close()
                written += 1
    return written, skipped


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--dates", nargs="+", required=True, help="YYYY-MM-DD dates to backfill")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    schedule = fetch_season_schedule(args.year, args.dates)
    n_written, n_skipped = write_k_season_to_db(args.year, schedule, dry_run=args.dry_run)
    print(f"Wrote {n_written} historical K rows, skipped {n_skipped}.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_k_pick_factors_db.py -v`
Expected: PASS (5 tests total in this file)

- [ ] **Step 5: Note for a live backfill run (manual, not part of this task's automated tests)**

This script hits live MLB Stats API boxscore endpoints per game-day — running it for a full season backfill is a slow, network-heavy operation intentionally left as a manual, deliberate step (`python ml/build_historical_k_dataset.py --year 2025 --dates 2025-04-01 2025-04-02 ...`), not run automatically by any test or daily job. Do this once, after Task 13 is merged, before the first live retrain.

- [ ] **Step 6: Commit**

```bash
git add ml/build_historical_k_dataset.py tests/test_k_pick_factors_db.py
git commit -m "feat(k-model): add historical pick_factors_k backfill script"
```

---

### Task 11: Integrate `Ace` into `scripts/daily_picks.py`

**Files:**
- Modify: `scripts/daily_picks.py`
- Test: manual smoke test (Step 4 below) — this task is orchestration glue around already-tested units, so it's verified by a `--use-cache`-style dry run rather than a new unit test.

**Interfaces:**
- Consumes: `Ace` (Task 6), `save_pick_factors_k` (Task 7), `fetch_strikeouts_for_date` + `update_pick_factors_k` (Task 9).
- Produces: `picks/k_picks_{TODAY}.txt`, and (after Task 12) `picks/k_picks_{TODAY}.html`; extends the existing `_auto_maintain()` and the hardcoded git file lists.

- [ ] **Step 1: Add the K-results labeling step to `_auto_maintain()`**

In `scripts/daily_picks.py`, inside `_auto_maintain()` (lines 82-140), after the existing HR-results labeling block, add:

```python
    # ── Step 1b: Label yesterday's strikeout results ───────────────────────────
    try:
        from ml.fetch_actual_k_results import fetch_strikeouts_for_date, update_pick_factors_k
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        actual_ks = fetch_strikeouts_for_date(yesterday)
        if actual_ks:
            update_pick_factors_k(yesterday, actual_ks)
            print(f"  [K-model] Labeled {len(actual_ks)} pitcher results for {yesterday}")
    except Exception as e:
        print(f"  [K-model] Skipped K-results labeling ({e})")
```

(This mirrors the existing bare `try/except` pattern already used for the HR labeling step in this function — consistent with existing style, not introducing a new error-handling convention.)

- [ ] **Step 2: Run Ace after Homer and write K picks output**

After the existing block that computes HR `picks` (around line 345, `picks = homer.get_picks_json(top_n=15, scratched=SCRATCHED)`), add:

```python
    # ── Strikeout model (Ace) — independent pipeline, runs after HR picks ──────
    print("\n[Ace] Fetching today's strikeout picks...")
    try:
        from agents.k_predictor import Ace
        ace = Ace()
        k_picks = ace.get_picks_json(top_n=10)

        k_full_ranked = ace._rank_picks_python(
            ace._gather_data().get("pitcher_signals", {}), top_n=10_000,
        )
        for rank_i, p in enumerate(k_full_ranked, 1):
            save_pick_factors_k(
                TODAY, p["pitcher"], p["signals"],
                confidence=p["confidence"], algo_version="1.0",
                score=p["score"], rank=rank_i,
            )

        k_txt_path = f"picks/k_picks_{TODAY}.txt"
        with open(k_txt_path, "w") as f:
            f.write(f"Strikeout Picks — {TODAY}\n{'=' * 40}\n\n")
            for i, p in enumerate(k_picks, 1):
                f.write(f"{i}. {p['pitcher']} ({p['matchup']}) — {p['confidence']} — score {p['score']:.1f}\n")
                f.write(f"   {p['reasoning']}\n\n")
        print(f"  [Ace] {len(k_picks)} K picks written to {k_txt_path}")
    except Exception as e:
        print(f"  [Ace] Skipped strikeout picks ({e})")
```

- [ ] **Step 3: Extend the hardcoded git file lists**

In the git add/commit/push block (lines ~645-675), add the new K-model source files to `_git_files` in the full-run (`not args.use_cache`) branch, and add the K picks output files to both branches:

```python
    if not args.use_cache:
        _git_files = [
            "ml_weights.json", "agents/predictor.py",
            "agents/bet_tracker.py", "scripts/daily_picks.py",
            "ml/optimize_weights.py", "ml/fetch_actual_results.py",
            "ml/build_historical_dataset.py", "README.md", "requirements.txt",
            "tools/generate_html.py", "docs/index.html", "docs/leaderboard.html",
            "docs/player-data.json", "docs/hit-rate.html",
            "agents/k_predictor.py", "ml/optimize_weights_k.py",
            "ml/fetch_actual_k_results.py", "ml/build_historical_k_dataset.py",
            "ml_weights_k.json", "docs/strikeouts.html",
        ]
        _commit_msg = f"Auto-update {TODAY} — picks run"
    else:
        _git_files = [
            "docs/index.html", "docs/leaderboard.html", "docs/player-data.json",
            "docs/hit-rate.html", f"picks/picks_{TODAY}.html",
            "docs/strikeouts.html", f"picks/k_picks_{TODAY}.html",
        ]
        _commit_msg = f"picks({TODAY}): re-run from cache — lineup update"
```

- [ ] **Step 4: Manual smoke test**

Run: `python scripts/daily_picks.py --use-cache` (uses cached context, won't burn Odds API quota; the `Ace` block will still attempt a live schedule fetch since `Ace._gather_data` doesn't currently support a `--use-cache` path — expected to either succeed with today's live starters or print the `[Ace] Skipped strikeout picks (...)` fallback message without crashing the rest of the run).
Expected: script completes without raising; `picks/k_picks_{TODAY}.txt` exists if starters were found for today, or the skip message printed harmlessly if not (e.g., no games today).

- [ ] **Step 5: Commit**

```bash
git add scripts/daily_picks.py
git commit -m "feat(k-model): wire Ace into daily_picks.py — labeling, picks output, git tracking"
```

---

### Task 12: Site page — `docs/strikeouts.html` + nav links

**Files:**
- Modify: `tools/generate_html.py`
- Modify: `docs/index.html`, `docs/pick-of-the-day.html`, `docs/leaderboard.html`, `docs/hit-rate.html` (nav link addition — these are static/generated files; Step 1 shows the exact literal insertion for the nav markup, Step 2 shows where the generator function needs the same literal added to its template string so future regenerations keep it)
- Test: manual visual smoke test (Step 4) — HTML generation/rendering isn't unit-tested elsewhere in this codebase (confirmed: no existing tests exercise `generate_html.py`), consistent with existing project conventions.

**Interfaces:**
- Consumes: `k_picks: list[dict]` (the same shape `Ace.get_picks_json()` returns), `today: str`.
- Produces: `generate_k_picks_html(k_picks: list[dict], today: str) -> str` in `tools/generate_html.py`; `docs/strikeouts.html` (written by `daily_picks.py` after the `generate_picks_html(...)` call, same pattern).

- [ ] **Step 1: Add the nav link to existing pages**

In `docs/index.html`, inside the `<div class="model-chips">` block (lines ~653-657), add a third link:

```html
  <div class="model-chips">
    <a class="nav-link" href="pick-of-the-day.html">Pick of Day ★</a>
    <a class="nav-link" href="leaderboard.html">HR Leaders →</a>
    <a class="nav-link" href="hit-rate.html">Hit Rate 📅</a>
    <a class="nav-link" href="strikeouts.html">K Picks ⚾</a>
  </div>
```

Apply the identical `<a class="nav-link" href="strikeouts.html">K Picks ⚾</a>` insertion (in the equivalent `.model-chips`/nav block) to `docs/pick-of-the-day.html`, `docs/leaderboard.html`, and `docs/hit-rate.html`.

- [ ] **Step 2: Add the same literal to `generate_picks_html`'s template**

Open `tools/generate_html.py` and locate the `<div class="model-chips">` template string inside `generate_picks_html` (search for `class="model-chips"` — it's the same literal shown in Step 1, since `docs/index.html` is generated by this function). Add the identical `<a class="nav-link" href="strikeouts.html">K Picks ⚾</a>` line there, so future regenerations of `docs/index.html` don't drop the link added by hand in Step 1.

- [ ] **Step 3: Write `generate_k_picks_html`**

Append to `tools/generate_html.py`:

```python
def generate_k_picks_html(k_picks: list[dict], today: str) -> str:
    """
    Generate docs/strikeouts.html — the strikeout model's picks page.
    Same site-header/model-chips/nav-link conventions as the HR pages
    (see generate_picks_html), rendered as a standalone page.
    """
    rows = []
    for i, p in enumerate(k_picks, 1):
        sig = p.get("signals", {})
        k_line = sig.get("k_line")
        line_str = f"O/U {k_line}" if k_line is not None else "—"
        rows.append(f"""
      <div class="pick-card">
        <div class="pick-rank">#{i}</div>
        <div class="pick-body">
          <div class="pick-name">{p['pitcher']}</div>
          <div class="pick-matchup">{p['matchup']}</div>
          <div class="pick-reasoning">{p['reasoning']}</div>
          <div class="pick-meta">
            <span class="confidence-{p['confidence'].lower()}">{p['confidence']}</span>
            <span class="k-line">{line_str}</span>
            <span class="score">score {p['score']:.1f}</span>
          </div>
        </div>
      </div>""")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Strikeout Picks — Dingers Hotline</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="style.css">
</head>
<body>

<header class="site-header">
  <div class="header-left">
    <div class="site-title">Dingers Hotline — Strikeout Picks</div>
    <div class="site-date">Latest Update: {today} &nbsp;·&nbsp; {len(k_picks)} Picks</div>
  </div>
  <div class="model-chips">
    <a class="nav-link" href="index.html">← HR Picks</a>
    <a class="nav-link" href="leaderboard.html">HR Leaders →</a>
    <a class="nav-link" href="hit-rate.html">Hit Rate 📅</a>
  </div>
</header>

<main class="picks-container">
  <p class="model-note">
    Hypothetical model P&amp;L only — $10 on every published K pick, tracked
    separately from the HR model's portfolio.
  </p>
  {"".join(rows)}
</main>

</body>
</html>
"""
```

- [ ] **Step 4: Manual visual smoke test**

Run (from repo root, with the venv active):
```bash
python -c "
from tools.generate_html import generate_k_picks_html
html = generate_k_picks_html([
    {'pitcher': 'Gerrit Cole', 'matchup': 'NYY @ BOS', 'confidence': 'HIGH',
     'reasoning': 'Gerrit Cole: 11.5 K/9 (blended), 6.0 IP/start last 3, VALUE line',
     'score': 15.5, 'signals': {'k_line': 6.5}},
], '2026-08-18')
open('/tmp/k-picks-preview.html', 'w').write(html)
print('wrote /tmp/k-picks-preview.html')
"
```
Open `/tmp/k-picks-preview.html` in a browser and confirm the page renders (one pick card, nav links present, no broken markup — visually check, since there's no automated HTML assertion in this codebase's existing conventions).

- [ ] **Step 5: Commit**

```bash
git add tools/generate_html.py docs/index.html docs/pick-of-the-day.html docs/leaderboard.html docs/hit-rate.html
git commit -m "feat(k-model): add K-picks site page and nav links"
```

---

### Task 13: Extend `daily_picks.py` to write `docs/strikeouts.html`; update auto-push hook

**Files:**
- Modify: `scripts/daily_picks.py`
- Modify: `.claude/hooks/auto-push-site.sh`

**Interfaces:**
- Consumes: `generate_k_picks_html` (Task 12).
- Produces: `docs/strikeouts.html` written on every full run; hook covers it for auto-push.

- [ ] **Step 1: Write `docs/strikeouts.html` in the HTML-generation block**

In `scripts/daily_picks.py`, near the existing `generate_picks_html(...)` call (lines ~591-639), add:

```python
    try:
        from tools.generate_html import generate_k_picks_html
        k_html = generate_k_picks_html(k_picks, TODAY)
        with open("docs/strikeouts.html", "w") as f:
            f.write(k_html)
        with open(f"picks/k_picks_{TODAY}.html", "w") as f:
            f.write(k_html)
        print("  [Ace] docs/strikeouts.html written")
    except Exception as e:
        print(f"  [Ace] Skipped K-picks HTML ({e})")
```

(Guarded the same defensive way as the rest of the `Ace` integration in Task 11 — a failure here must not block the HR pipeline's already-working commit/push.)

- [ ] **Step 2: Update the auto-push hook**

In `.claude/hooks/auto-push-site.sh`, update the `CHANGED` detection regex and the `git add` line:

```bash
CHANGED=$(git status --porcelain 2>/dev/null | grep -E "(picks/.*\.(html|txt)|docs/index\.html|docs/k-picks\.html|docs/version\.txt)" | awk '{print $2}')

if [ -n "$CHANGED" ]; then
    git add picks/*.html picks/*.txt docs/index.html docs/strikeouts.html docs/version.txt docs/_headers 2>/dev/null
```

(`picks/*.html picks/*.txt` already globs any `k_picks_*` filename — confirmed during research, no change needed there. The only real gap was `docs/strikeouts.html` not being in the `git add` list or `CHANGED` regex.)

- [ ] **Step 3: Manual smoke test**

Run: `bash .claude/hooks/auto-push-site.sh` after a run that touched `docs/strikeouts.html` (or simulate by touching the file and running the hook in a scratch branch) — confirm it stages and would commit `docs/strikeouts.html` alongside the existing files (`git status` before running vs. after, or inspect `git diff --cached` if the hook is run without the final `git push` for review purposes first).

- [ ] **Step 4: Full regression check across the whole suite**

Run: `python -m pytest tests/ -v -k "not network"`
Expected: all tests pass, including every test added in Tasks 1-10, and every pre-existing HR-model test unaffected.

- [ ] **Step 5: Commit**

```bash
git add scripts/daily_picks.py .claude/hooks/auto-push-site.sh
git commit -m "feat(k-model): write docs/strikeouts.html on daily runs; cover it in auto-push hook"
```

---

## Post-Plan Manual Step (not automated, do once after merge)

Run the historical backfill from Task 10 for a representative slice of recent seasons (e.g., the last 2-3 months of the current season, expanding to prior full seasons if the model needs more rows to hit `optimize_weights_k.py`'s default `--min 100` threshold):

```bash
python ml/build_historical_k_dataset.py --year 2026 --dates 2026-04-01 2026-04-02 ... 2026-08-17
```

Then run `python ml/optimize_weights_k.py --report` to see the correlation report and confirm signal population before doing a real `--min`-gated training run.

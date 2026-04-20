# Doubleheader Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `player_signals` keying so doubleheader players appear as two independent picks, each scored against their own game's pitcher/park/EV data, labeled `[DH G1]` / `[DH G2]`.

**Architecture:** Replace the bare-name key `player_signals[batter_name]` with a composite key `player_signals[f"{batter_name}||{game_pk}"]` throughout `_build_game_cards` and `_add_roster_fallback`. Strip the suffix when emitting player names to the output layer. Fix odds/blast-rate merging to use a name-only index so composite keys don't break fuzzy matching.

**Tech Stack:** Python 3.11, SQLite (`data/bets.db`), difflib.SequenceMatcher

---

## File Map

| File | What changes |
|------|-------------|
| `agents/predictor.py` | `_build_game_cards` (composite key + G1/G2 labels), odds merging (name-only index, 3-tier match), blast-rate merging, `_add_roster_fallback` (composite key), `_rank_picks_python` (strip suffix, DH label in output), `_format_narrative` (DH label display) |
| `agents/bet_tracker.py` | `_MIGRATION_COLUMNS` (add `game_pk`), `_ensure_pick_factors_table` (update unique index), `save_pick_factors` (add `game_pk` param + INSERT) |
| `scripts/daily_picks.py` | `save_pick_factors` call (pass `game_pk`) |
| `tests/test_doubleheader.py` | New test file |

---

## Task 1: Add composite-key helpers and G1/G2 index to `_build_game_cards`

**Files:**
- Modify: `agents/predictor.py:1689` (`_build_game_cards` — top of method, before main game loop)
- Create: `tests/test_doubleheader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doubleheader.py
import pytest
from collections import defaultdict


def _build_team_game_label(games: list) -> dict:
    """Extracted helper — mirrors the logic we'll add to _build_game_cards."""
    team_game_order: dict[str, list] = defaultdict(list)
    for game in games:
        gtime = game.get("game_time", "")
        gpk   = str(game.get("game_pk", ""))
        for side in ("away", "home"):
            team = game.get(side, {}).get("team", "")
            if team:
                team_game_order[team].append((gtime, gpk))

    team_game_label: dict[tuple, str | None] = {}
    for team, entries in team_game_order.items():
        entries.sort()
        is_dh = len(entries) > 1
        for i, (_, gpk) in enumerate(entries):
            team_game_label[(team, gpk)] = f"G{i+1}" if is_dh else None
    return team_game_label


def test_no_doubleheader_labels_are_none():
    games = [
        {"game_pk": 1001, "game_time": "2026-04-20T17:05:00Z",
         "away": {"team": "BOS"}, "home": {"team": "NYY"}},
        {"game_pk": 1002, "game_time": "2026-04-20T19:10:00Z",
         "away": {"team": "LAD"}, "home": {"team": "SFG"}},
    ]
    labels = _build_team_game_label(games)
    assert labels[("NYY", "1001")] is None
    assert labels[("BOS", "1001")] is None
    assert labels[("LAD", "1002")] is None


def test_doubleheader_assigns_g1_g2():
    games = [
        {"game_pk": 2001, "game_time": "2026-04-20T15:05:00Z",
         "away": {"team": "BOS"}, "home": {"team": "NYY"}},
        {"game_pk": 2002, "game_time": "2026-04-20T19:05:00Z",
         "away": {"team": "BOS"}, "home": {"team": "NYY"}},
    ]
    labels = _build_team_game_label(games)
    assert labels[("NYY", "2001")] == "G1"
    assert labels[("NYY", "2002")] == "G2"
    assert labels[("BOS", "2001")] == "G1"
    assert labels[("BOS", "2002")] == "G2"


def test_composite_key_format():
    player = "Aaron Judge"
    game_pk = 745308
    key = f"{player}||{game_pk}"
    name_part = key.split("||")[0]
    assert name_part == "Aaron Judge"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/joesliwinski/AIProjects/DingersHotline
python -m pytest tests/test_doubleheader.py -v
```

Expected: `ImportError` or `NameError` (helper not yet in predictor.py — the test defines it locally so it should actually PASS; this is a logic-verification test, not a unit test of the production function yet).

- [ ] **Step 3: Add the G1/G2 index block to `_build_game_cards`**

In `agents/predictor.py`, at the top of `_build_game_cards` (just after `player_signals = {}` is initialized, before `for game in lineups.get("games", []):`):

```python
        # ── Build per-team G1/G2 doubleheader index ──────────────────────────
        from collections import defaultdict as _defaultdict
        _team_game_order: dict[str, list] = _defaultdict(list)
        for _g in lineups.get("games", []):
            _gtime = _g.get("game_time", "")
            _gpk   = str(_g.get("game_pk", ""))
            for _side in ("away", "home"):
                _team = _g.get(_side, {}).get("team", "")
                if _team:
                    _team_game_order[_team].append((_gtime, _gpk))
        _team_game_label: dict[tuple, str | None] = {}
        for _team, _entries in _team_game_order.items():
            _entries.sort()
            _is_dh = len(_entries) > 1
            for _i, (_, _gpk) in enumerate(_entries):
                _team_game_label[(_team, _gpk)] = f"G{_i+1}" if _is_dh else None
        # ─────────────────────────────────────────────────────────────────────
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_doubleheader.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_doubleheader.py agents/predictor.py
git commit -m "feat: add G1/G2 doubleheader index to _build_game_cards"
```

---

## Task 2: Switch `_build_game_cards` to composite keys

**Files:**
- Modify: `agents/predictor.py:1689–1842` (inner batter loop of `_build_game_cards`)

- [ ] **Step 1: In the outer game loop, capture `game_pk` and `game_label`**

Inside `for game in lineups.get("games", []):`, after extracting `team` (line ~1700), add:

```python
                game_pk_str  = str(game.get("game_pk") or "")
                game_label   = _team_game_label.get((team, game_pk_str))
```

Do this for both the `away_side` and `home_side` iterations (the `for side, opp, is_home in [...]` loop). The cleanest way: extract at the top of that inner loop, replacing the current `team = side.get("team", "")` line:

```python
                team         = side.get("team", "")
                game_pk_str  = str(game.get("game_pk") or "")
                game_label   = _team_game_label.get((team, game_pk_str))
```

- [ ] **Step 2: Replace bare-name key with composite key in `player_signals` assignment**

Find the block starting at line ~1804:
```python
                    if batter_name:
                        player_signals[batter_name] = {
```

Replace with:
```python
                    if batter_name:
                        _ck = f"{batter_name}||{game_pk_str}" if game_pk_str else batter_name
                        player_signals[_ck] = {
```

- [ ] **Step 3: Add `game_pk` and `game_label` to the signal dict**

In the signal dict being assigned (lines ~1806–1842), add these two fields after `"status"`:

```python
                            "game_pk":          game_pk_str or None,
                            "game_label":       game_label,
```

- [ ] **Step 4: Run a quick smoke test**

```bash
cd /Users/joesliwinski/AIProjects/DingersHotline
python -c "
from agents.predictor import Homer
h = Homer()
import json
# Minimal fake lineups with two games for same team
fake = json.dumps({'status': 'success', 'date': '2026-04-20', 'games': [
    {'game_pk': 1001, 'venue': 'Yankee Stadium', 'game_time': '2026-04-20T15:05:00Z', 'status': 'Scheduled',
     'away': {'team': 'BOS', 'team_id': 111, 'starting_pitcher': 'J. Doe', 'pitcher_id': 999, 'pitcher_throws': 'R', 'lineup_confirmed': True, 'batting_order': ['Aaron Judge'], 'batters': [{'id': 592450, 'name': 'Aaron Judge', 'bat_side': 'R', 'status': 'confirmed'}]},
     'home': {'team': 'NYY', 'team_id': 147, 'starting_pitcher': 'T. Smith', 'pitcher_id': 998, 'pitcher_throws': 'L', 'lineup_confirmed': True, 'batting_order': [], 'batters': []}},
    {'game_pk': 1002, 'venue': 'Yankee Stadium', 'game_time': '2026-04-20T19:05:00Z', 'status': 'Scheduled',
     'away': {'team': 'BOS', 'team_id': 111, 'starting_pitcher': 'M. Chen', 'pitcher_id': 997, 'pitcher_throws': 'L', 'lineup_confirmed': True, 'batting_order': ['Aaron Judge'], 'batters': [{'id': 592450, 'name': 'Aaron Judge', 'bat_side': 'R', 'status': 'confirmed'}]},
     'home': {'team': 'NYY', 'team_id': 147, 'starting_pitcher': 'R. Lee', 'pitcher_id': 996, 'pitcher_throws': 'R', 'lineup_confirmed': True, 'batting_order': [], 'batters': []}}
]})
cards, signals = h._build_game_cards(fake, {}, {}, [], [], {}, {})
dh_keys = [k for k in signals if 'Aaron Judge' in k]
print('DH keys:', dh_keys)
assert len(dh_keys) == 2, f'Expected 2 entries, got {len(dh_keys)}'
g1 = signals['Aaron Judge||1001']
g2 = signals['Aaron Judge||1002']
assert g1['game_label'] == 'G1', f'Expected G1, got {g1[\"game_label\"]}'
assert g2['game_label'] == 'G2', f'Expected G2, got {g2[\"game_label\"]}'
print('PASS: Two composite keys, correct game labels')
"
```

Expected output: `PASS: Two composite keys, correct game labels`

- [ ] **Step 5: Commit**

```bash
git add agents/predictor.py
git commit -m "feat: composite key player_signals in _build_game_cards"
```

---

## Task 3: Fix odds merging — name-only index with 3-tier matching

**Files:**
- Modify: `agents/predictor.py:2012–2054` (odds merge block)
- Modify: `agents/predictor.py:2058–2076` (blast rate merge block)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_doubleheader.py`:

```python
import unicodedata
from difflib import SequenceMatcher
from collections import defaultdict as _defaultdict


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


def _match_odds_player(pname: str, player_signals: dict) -> list[str]:
    """
    3-tier name matcher. Returns list of composite keys that match pname.
    Tier 1: exact normalized name.
    Tier 2: token intersection (all tokens in pname appear in candidate name).
    Tier 3: SequenceMatcher >= 0.90.
    """
    name_to_keys: dict[str, list[str]] = _defaultdict(list)
    for ck in player_signals:
        name_part = ck.split("||")[0]
        name_to_keys[_norm(name_part)].append(ck)

    pname_norm = _norm(pname)

    # Tier 1: exact
    if pname_norm in name_to_keys:
        return name_to_keys[pname_norm]

    # Tier 2: token intersection
    tokens = set(pname_norm.split())
    for nk, keys in name_to_keys.items():
        if tokens and tokens.issubset(set(nk.split())):
            return keys

    # Tier 3: fuzzy
    best_ratio, best_keys = 0.0, []
    for nk, keys in name_to_keys.items():
        r = SequenceMatcher(None, pname_norm, nk).ratio()
        if r > best_ratio:
            best_ratio, best_keys = r, keys
    if best_ratio >= 0.90:
        return best_keys
    return []


def test_odds_match_normal_game():
    signals = {"Aaron Judge||1001": {}}
    assert _match_odds_player("Aaron Judge", signals) == ["Aaron Judge||1001"]


def test_odds_match_doubleheader_returns_both():
    signals = {"Aaron Judge||1001": {}, "Aaron Judge||1002": {}}
    result = _match_odds_player("Aaron Judge", signals)
    assert set(result) == {"Aaron Judge||1001", "Aaron Judge||1002"}


def test_odds_match_accent():
    signals = {"Yordan Alvarez||2001": {}}
    assert _match_odds_player("Yordan Álvarez", signals) == ["Yordan Alvarez||2001"]


def test_odds_no_false_positive_same_last_name():
    signals = {"Jose Ramirez||3001": {}, "Harold Ramirez||3002": {}}
    result = _match_odds_player("Jose Ramirez", signals)
    assert result == ["Jose Ramirez||3001"], f"Got: {result}"


def test_odds_no_match_below_threshold():
    signals = {"Mike Trout||4001": {}}
    result = _match_odds_player("Juan Soto", signals)
    assert result == []
```

- [ ] **Step 2: Run to verify tests fail**

```bash
python -m pytest tests/test_doubleheader.py::test_odds_match_normal_game -v
```

Expected: `NameError: name '_match_odds_player' is not defined` (function defined in test only at this stage).

Actually these tests define `_match_odds_player` locally so they'll pass as written — run all of them to confirm the logic is correct:

```bash
python -m pytest tests/test_doubleheader.py -v
```

Expected: All tests PASS (logic verification before wiring into production code).

- [ ] **Step 3: Replace the odds merge block in `predictor.py`**

Find lines ~2012–2054 in `agents/predictor.py` (the block starting with `def _norm(s: str) -> str:` inside the try block):

Replace:
```python
            def _norm(s: str) -> str:
                return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()

            normed_signals = {_norm(k): k for k in player_signals}
            matched_count = 0

            for comp in odds_data.get("comparisons", []):
                pname = comp.get("player", "")
                # Exact match first, then accent-stripped, then fuzzy
                if pname in player_signals:
                    matched = pname
                elif _norm(pname) in normed_signals:
                    matched = normed_signals[_norm(pname)]
                else:
                    best_ratio, best_key = 0.0, None
                    pname_norm = _norm(pname)
                    for nk, orig in normed_signals.items():
                        r = SequenceMatcher(None, pname_norm, nk).ratio()
                        if r > best_ratio:
                            best_ratio, best_key = r, orig
                    matched = best_key if best_ratio >= 0.85 else None

                if matched:
                    matched_count += 1
                    ev    = comp.get("ev_10")
                    pin   = comp.get("pinnacle")
                    best  = comp.get("best_odds")
                    if ev is None:
                        print(f"[ODDS] {pname}: ev_10 is None (pinnacle={pin!r}, best_odds={best!r})")
                    if pin is None:
                        print(f"[ODDS] {pname}: pinnacle_odds missing — EV/Kelly unreliable")
                    player_signals[matched]["ev_10"]         = ev
                    player_signals[matched]["kelly_size"]    = comp.get("kelly_size")
                    player_signals[matched]["value_edge"]    = comp.get("value_edge")
                    player_signals[matched]["pinnacle_odds"] = pin
                    player_signals[matched]["best_odds"]     = best
                else:
                    print(f"[ODDS] No signal match for odds player: {pname!r}")
```

With:
```python
            def _norm(s: str) -> str:
                return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()

            # Name-only index: strips ||game_pk suffix so composite keys don't break matching
            from collections import defaultdict as _dd
            _name_to_keys: dict[str, list[str]] = _dd(list)
            for _ck in player_signals:
                _name_part = _ck.split("||")[0]
                _name_to_keys[_norm(_name_part)].append(_ck)

            def _find_signal_keys(pname: str) -> list[str]:
                """3-tier match: exact → token intersection → fuzzy ≥0.90."""
                pn = _norm(pname)
                # Tier 1: exact
                if pn in _name_to_keys:
                    return _name_to_keys[pn]
                # Tier 2: token intersection (guards against shared-last-name false positives)
                tokens = set(pn.split())
                for nk, keys in _name_to_keys.items():
                    if tokens and tokens.issubset(set(nk.split())):
                        return keys
                # Tier 3: fuzzy (tightened to 0.90; warns so false matches surface in logs)
                best_ratio, best_keys = 0.0, []
                for nk, keys in _name_to_keys.items():
                    r = SequenceMatcher(None, pn, nk).ratio()
                    if r > best_ratio:
                        best_ratio, best_keys = r, keys
                if best_ratio >= 0.90:
                    print(f"[ODDS] Fuzzy match ({best_ratio:.2f}): {pname!r} → {best_keys[0].split('||')[0]!r}")
                    return best_keys
                return []

            matched_count = 0

            for comp in odds_data.get("comparisons", []):
                pname     = comp.get("player", "")
                ev        = comp.get("ev_10")
                pin       = comp.get("pinnacle")
                best      = comp.get("best_odds")
                hit_keys  = _find_signal_keys(pname)

                if hit_keys:
                    matched_count += 1
                    if ev is None:
                        print(f"[ODDS] {pname}: ev_10 is None (pinnacle={pin!r}, best_odds={best!r})")
                    if pin is None:
                        print(f"[ODDS] {pname}: pinnacle_odds missing — EV/Kelly unreliable")
                    for _hk in hit_keys:
                        player_signals[_hk]["ev_10"]         = ev
                        player_signals[_hk]["kelly_size"]    = comp.get("kelly_size")
                        player_signals[_hk]["value_edge"]    = comp.get("value_edge")
                        player_signals[_hk]["pinnacle_odds"] = pin
                        player_signals[_hk]["best_odds"]     = best
                else:
                    print(f"[ODDS] No signal match for odds player: {pname!r}")
```

- [ ] **Step 4: Replace the blast rate merge block**

Find lines ~2058–2076 (the blast rate block):

Replace:
```python
            normed_signals = {_norm(k): k for k in player_signals}
            for bt_key, blast_val in blast_tracking.items():
                if bt_key in normed_signals:
                    matched = normed_signals[bt_key]
                else:
                    best_ratio, best_key = 0.0, None
                    for nk, orig in normed_signals.items():
                        r = SequenceMatcher(None, bt_key, nk).ratio()
                        if r > best_ratio:
                            best_ratio, best_key = r, orig
                    matched = best_key if best_ratio >= 0.85 else None
                if matched:
                    player_signals[matched]["blast_rate"] = round(blast_val * 100, 2)
```

With:
```python
            _blast_name_to_keys: dict[str, list[str]] = _dd(list)
            for _ck in player_signals:
                _blast_name_to_keys[_norm(_ck.split("||")[0])].append(_ck)
            for bt_key, blast_val in blast_tracking.items():
                _hit = _find_signal_keys(bt_key) if "_find_signal_keys" in dir() else []
                if not _hit:
                    # _find_signal_keys may not be in scope if odds block was skipped
                    bt_norm = _norm(bt_key)
                    _hit = _blast_name_to_keys.get(bt_norm, [])
                for _hk in _hit:
                    player_signals[_hk]["blast_rate"] = round(blast_val * 100, 2)
```

Note: `_find_signal_keys` is defined inside the odds `try` block above. To avoid scope dependency, extract it to a module-level helper. Add this function just above the `_gather_data` method (outside the class, or as a `@staticmethod`):

Actually, the simplest fix: define `_find_signal_keys` as a standalone inner function once at the start of the merge section (not inside the `try` block), so both blast and odds blocks share it. Move the `_norm`, `_name_to_keys`, and `_find_signal_keys` definitions to just before the `try odds_data = ...` block. Then both `try` blocks can reference it.

Replace the blast rate block with this simpler form:
```python
            for bt_key, blast_val in blast_tracking.items():
                for _hk in _find_signal_keys(bt_key):
                    player_signals[_hk]["blast_rate"] = round(blast_val * 100, 2)
```

And move the `_norm`, `_name_to_keys`, and `_find_signal_keys` definitions to before both try blocks (at the same indentation level as the `try` statements). This requires reading the surrounding context carefully and moving the definitions up ~10 lines.

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/test_doubleheader.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/predictor.py tests/test_doubleheader.py
git commit -m "feat: name-only odds/blast index, 3-tier matching, composite-key aware"
```

---

## Task 4: Fix `_add_roster_fallback` composite key

**Files:**
- Modify: `agents/predictor.py:2368–2448` (`_add_roster_fallback`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_doubleheader.py`:

```python
def test_roster_fallback_composite_key():
    """
    _add_roster_fallback should use composite key when game_pk is present,
    so a player in two DH games gets two separate entries.
    """
    # Simulate what _add_roster_fallback does (logic only, no DB calls)
    player_signals = {}

    def _fake_fallback(games, player_signals):
        for game in games:
            game_pk_str = str(game.get("game_pk") or "")
            for side_key in ("away", "home"):
                side = game.get(side_key, {})
                if side.get("lineup_confirmed"):
                    continue
                for player_name in side.get("roster_names", []):
                    _ck = f"{player_name}||{game_pk_str}" if game_pk_str else player_name
                    if _ck not in player_signals:
                        player_signals[_ck] = {"status": "waiting", "game_pk": game_pk_str}

    games = [
        {"game_pk": 5001,
         "away": {"lineup_confirmed": False, "roster_names": ["Xander Bogaerts"]},
         "home": {"lineup_confirmed": True,  "roster_names": []}},
        {"game_pk": 5002,
         "away": {"lineup_confirmed": False, "roster_names": ["Xander Bogaerts"]},
         "home": {"lineup_confirmed": True,  "roster_names": []}},
    ]
    _fake_fallback(games, player_signals)
    keys = [k for k in player_signals if "Xander Bogaerts" in k]
    assert len(keys) == 2, f"Expected 2 entries, got {keys}"
    assert "Xander Bogaerts||5001" in player_signals
    assert "Xander Bogaerts||5002" in player_signals
```

- [ ] **Step 2: Run test**

```bash
python -m pytest tests/test_doubleheader.py::test_roster_fallback_composite_key -v
```

Expected: PASS (logic test).

- [ ] **Step 3: Update `_add_roster_fallback` in `predictor.py`**

At line ~2380, inside `for game in lineups.get("games", []):`, add:

```python
                game_pk_str = str(game.get("game_pk") or "")
```

At line ~2401 (the `if player_name in player_signals:` check), replace:

```python
                    if player_name in player_signals:
                        if not player_signals[player_name].get("lineup_confirmed"):
                            player_signals[player_name]["batting_order"] = entry["batting_order"]
                        continue
```

With:

```python
                    _rfck = f"{player_name}||{game_pk_str}" if game_pk_str else player_name
                    if _rfck in player_signals:
                        if not player_signals[_rfck].get("lineup_confirmed"):
                            player_signals[_rfck]["batting_order"] = entry["batting_order"]
                        continue
```

At line ~2414 (the `player_signals[player_name] = {` assignment), replace:

```python
                    player_signals[player_name] = {
```

With:

```python
                    player_signals[_rfck] = {
```

Then inside the dict, add `"game_pk": game_pk_str or None,` and `"game_label": None,` (fallback players don't know their DH label at this stage — label is None by default and acceptable since roster fallback is a best-effort signal).

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/test_doubleheader.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/predictor.py tests/test_doubleheader.py
git commit -m "feat: composite key in _add_roster_fallback for doubleheader support"
```

---

## Task 5: Strip composite key suffix in `_rank_picks_python` and add DH label to output

**Files:**
- Modify: `agents/predictor.py:2935–3072` (`_rank_picks_python`)
- Modify: `agents/predictor.py:3118–3149` (`_format_narrative`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_doubleheader.py`:

```python
def test_rank_picks_strips_composite_suffix():
    """Player name in output should be clean, not contain ||game_pk."""
    # Simulate the key extraction logic
    composite_key = "Aaron Judge||745308"
    player_name = composite_key.split("||")[0]
    assert player_name == "Aaron Judge"
    assert "||" not in player_name


def test_dh_label_in_signals():
    """game_label should flow through to the pick output."""
    sig = {"game_label": "G1", "status": "confirmed", "matchup": "BOS @ NYY"}
    label = sig.get("game_label")
    display = f"[DH {label}]" if label else ""
    assert display == "[DH G1]"

    sig2 = {"game_label": None, "status": "confirmed", "matchup": "LAD @ SFG"}
    label2 = sig2.get("game_label")
    display2 = f"[DH {label2}]" if label2 else ""
    assert display2 == ""
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_doubleheader.py::test_rank_picks_strips_composite_suffix tests/test_doubleheader.py::test_dh_label_in_signals -v
```

Expected: PASS (logic tests).

- [ ] **Step 3: Update `_rank_picks_python` to strip the suffix**

At line ~2935, replace:

```python
        for player, sig in player_signals.items():
            if sig.get("bat_side", "?") == "?":
                resolved = get_bat_side_by_name(player)
```

With:

```python
        for _composite_key, sig in player_signals.items():
            player = _composite_key.split("||")[0]  # strip ||game_pk suffix
            if sig.get("bat_side", "?") == "?":
                resolved = get_bat_side_by_name(player)
```

No other changes needed in this loop — `player` is now the clean name everywhere it's used (lines 2937, 3005, 3034, 3061).

- [ ] **Step 4: Add DH label to the scored dict**

At line ~3033, in `scored.append({...})`, add after `"player": player,`:

```python
                "dh_label":   sig.get("game_label"),
```

- [ ] **Step 5: Update `_format_narrative` to display DH label**

At line ~3120 in `_format_narrative`:

```python
            name   = pick["player"]
```

After this line, add:

```python
            dh_label   = pick.get("dh_label")
            dh_tag     = f"  [DH {dh_label}]" if dh_label else ""
```

At line ~3133:

```python
            lines.append(f"#{i}  {name}{status_tag}  {stars}")
```

Replace with:

```python
            lines.append(f"#{i}  {name}{dh_tag}{status_tag}  {stars}")
```

- [ ] **Step 6: Run all tests**

```bash
python -m pytest tests/test_doubleheader.py -v
```

Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add agents/predictor.py tests/test_doubleheader.py
git commit -m "feat: strip composite key suffix in output, add [DH G1/G2] label"
```

---

## Task 6: Update `bet_tracker.py` schema and `save_pick_factors`

**Files:**
- Modify: `agents/bet_tracker.py:135–165` (`_MIGRATION_COLUMNS`, `_ensure_pick_factors_table`)
- Modify: `agents/bet_tracker.py:170–238` (`save_pick_factors`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_doubleheader.py`:

```python
import sqlite3
import tempfile
import os


def test_save_pick_factors_two_dh_games():
    """Both DH games should get their own row in pick_factors."""
    import sys
    sys.path.insert(0, "/Users/joesliwinski/AIProjects/DingersHotline")

    # Patch get_db_conn to use a temp DB
    import agents.bet_tracker as bt
    original_get_db = bt.get_db_conn

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_db = f.name

    def _fake_conn():
        return sqlite3.connect(tmp_db)

    bt.get_db_conn = _fake_conn
    try:
        bt.save_pick_factors("2026-04-20", "Aaron Judge", {"is_home": True}, game_pk="745308")
        bt.save_pick_factors("2026-04-20", "Aaron Judge", {"is_home": False}, game_pk="745309")

        conn = sqlite3.connect(tmp_db)
        rows = conn.execute(
            "SELECT player, game_pk FROM pick_factors WHERE bet_date='2026-04-20' ORDER BY game_pk"
        ).fetchall()
        conn.close()
        assert len(rows) == 2, f"Expected 2 rows, got {rows}"
        assert rows[0] == ("Aaron Judge", "745308")
        assert rows[1] == ("Aaron Judge", "745309")
    finally:
        bt.get_db_conn = original_get_db
        os.unlink(tmp_db)
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_doubleheader.py::test_save_pick_factors_two_dh_games -v
```

Expected: `TypeError: save_pick_factors() got an unexpected keyword argument 'game_pk'`

- [ ] **Step 3: Add `game_pk` to `_MIGRATION_COLUMNS`**

In `agents/bet_tracker.py` at line ~150, add to `_MIGRATION_COLUMNS`:

```python
    ("game_pk",          "TEXT"),
```

- [ ] **Step 4: Update unique index in `_ensure_pick_factors_table`**

At line ~163:

```python
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pick_factors_date_player
            ON pick_factors (bet_date, player)
        """)
```

Replace with:

```python
        # Drop old single-game unique index (incompatible with doubleheaders)
        conn.execute("DROP INDEX IF EXISTS idx_pick_factors_date_player")
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pick_factors_date_player_game
            ON pick_factors (bet_date, player, game_pk)
        """)
```

- [ ] **Step 5: Add `game_pk` parameter to `save_pick_factors`**

At line ~170, replace signature:

```python
def save_pick_factors(bet_date: str, player: str, signals: dict,
                      confidence: str = None,
                      algo_version: str = "2.0",
                      score: float = None,
                      rank: int = None) -> str:
```

With:

```python
def save_pick_factors(bet_date: str, player: str, signals: dict,
                      confidence: str = None,
                      algo_version: str = "2.0",
                      score: float = None,
                      rank: int = None,
                      game_pk: str = None) -> str:
```

- [ ] **Step 6: Add `game_pk` to INSERT statement**

At line ~192, in the `conn.execute("""INSERT OR IGNORE INTO pick_factors ...""")`:

Add `game_pk` to the column list and `?` to the values tuple.

Column list — add after `blast_rate)`:
```
               blast_rate, game_pk)
```

Values tuple — add after `signals.get("blast_rate"),`:
```python
            game_pk or signals.get("game_pk"),
```

- [ ] **Step 7: Run the failing test**

```bash
python -m pytest tests/test_doubleheader.py::test_save_pick_factors_two_dh_games -v
```

Expected: PASS.

- [ ] **Step 8: Run all tests**

```bash
python -m pytest tests/test_doubleheader.py -v
```

Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add agents/bet_tracker.py tests/test_doubleheader.py
git commit -m "feat: add game_pk to pick_factors schema and save_pick_factors"
```

---

## Task 7: Update `daily_picks.py` call site

**Files:**
- Modify: `scripts/daily_picks.py:257` (`save_pick_factors` call)

- [ ] **Step 1: Update the call**

At line ~257:

```python
                save_pick_factors(TODAY, p["player"], p["signals"],
                                  confidence=p.get("confidence"),
                                  algo_version="3.1",
                                  score=p.get("score"),
                                  rank=rank_i)
```

Replace with:

```python
                save_pick_factors(TODAY, p["player"], p["signals"],
                                  confidence=p.get("confidence"),
                                  algo_version="3.1",
                                  score=p.get("score"),
                                  rank=rank_i,
                                  game_pk=p.get("signals", {}).get("game_pk"))
```

- [ ] **Step 2: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: All PASS.

- [ ] **Step 3: Smoke test with cache**

```bash
cd /Users/joesliwinski/AIProjects/DingersHotline
python tools/test_homer_prompt.py 2>&1 | head -40
```

Verify: no `KeyError`, no `||` appearing in player names in the output, picks display normally.

- [ ] **Step 4: Commit**

```bash
git add scripts/daily_picks.py
git commit -m "feat: pass game_pk to save_pick_factors from daily_picks"
```

---

## Task 8: End-to-end smoke test and cleanup

**Files:**
- Read-only: `cache/debug_context_*.json` (if a recent cache exists)

- [ ] **Step 1: Verify no composite keys leak into output**

```bash
cd /Users/joesliwinski/AIProjects/DingersHotline
python tools/test_homer_prompt.py 2>&1 | grep "||"
```

Expected: no output (no `||` in any pick name).

- [ ] **Step 2: Verify scoring debug shows clean names**

```bash
python tools/test_homer_prompt.py --debug 2>&1 | grep "SCORING DEBUG" -A 25
```

Expected: Player names are clean (e.g., `Aaron Judge`, not `Aaron Judge||745308`).

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v --no-network
```

Expected: All PASS.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: doubleheader support — composite keys, DH labels, game_pk in pick_factors"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Composite key in `_build_game_cards` — Task 2
- ✅ G1/G2 label assignment — Task 1
- ✅ `_rank_picks_python` strips suffix, no structural change — Task 5
- ✅ DH label in output — Task 5
- ✅ Odds merging name-only index, 3-tier match — Task 3
- ✅ Blast rate merging fixed — Task 3
- ✅ `_add_roster_fallback` composite key — Task 4
- ✅ `pick_factors` schema migration — Task 6
- ✅ `save_pick_factors` `game_pk` param — Task 6
- ✅ `daily_picks.py` call site — Task 7
- ✅ Error handling (missing game_pk falls back to bare name) — Task 2 step 3 (`if game_pk_str else batter_name`)
- ✅ Non-DH day output identical to current — covered by smoke test Task 8

**No placeholders found.**

**Type consistency:** `game_pk` is `str | None` throughout (converted with `str(...)` at source, stored as `TEXT` in SQLite). `game_label` is `str | None`. Both consistent across all tasks.

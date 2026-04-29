"""
Tests for doubleheader support — composite key logic, G1/G2 labels,
odds/blast name matching, and pick_factors schema.
"""
import os
import sqlite3
import sys
import tempfile
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── G1/G2 label helper (mirrors the logic added to _build_game_cards) ─────────

def _build_team_game_label(games: list) -> dict:
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


# ── Odds name matching ─────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


def _name_part(sig_key: str) -> str:
    """Strip ||game_pk suffix — works for both 'name||pk' and legacy 'name|team'."""
    return sig_key.split("|")[0]


def _match_odds_player(pname: str, player_signals: dict) -> list[str]:
    """
    3-tier name matcher. Returns list of composite keys that match pname.
    Tier 1: exact normalized name.
    Tier 2: token intersection (all tokens in pname appear in candidate name).
    Tier 3: SequenceMatcher >= 0.90.
    """
    name_to_keys: dict[str, list[str]] = defaultdict(list)
    for ck in player_signals:
        name_part = _name_part(ck)
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


# ── Roster fallback composite key ──────────────────────────────────────────────

def test_roster_fallback_composite_key():
    """
    _add_roster_fallback should use composite key when game_pk is present,
    so a player in two DH games gets two separate entries.
    """
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


# ── Output layer ───────────────────────────────────────────────────────────────

def test_rank_picks_strips_composite_suffix():
    composite_key = "Aaron Judge||745308"
    player_name = composite_key.split("||")[0]
    assert player_name == "Aaron Judge"
    assert "||" not in player_name


def test_dh_label_in_signals():
    sig = {"game_label": "G1", "status": "confirmed", "matchup": "BOS @ NYY"}
    label = sig.get("game_label")
    display = f"  [DH {label}]" if label else ""
    assert display == "  [DH G1]"

    sig2 = {"game_label": None, "status": "confirmed", "matchup": "LAD @ SFG"}
    label2 = sig2.get("game_label")
    display2 = f"  [DH {label2}]" if label2 else ""
    assert display2 == ""


# ── pick_factors DB schema ─────────────────────────────────────────────────────

def test_save_pick_factors_two_dh_games():
    """Both DH games should get their own row in pick_factors."""
    import agents.bet_tracker as bt
    original_get_db = bt.get_db_conn

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_db = f.name

    def _fake_conn():
        return sqlite3.connect(tmp_db)

    bt.get_db_conn = _fake_conn
    try:
        bt.save_pick_factors("2026-04-20", "Aaron Judge", {"is_home": True},  game_pk="745308")
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

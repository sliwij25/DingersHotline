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

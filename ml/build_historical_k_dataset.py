"""
build_historical_k_dataset.py
Bootstrap historical pick_factors_k rows so the K model can train on day
one instead of waiting ~2 weeks for live data (mirrors the rationale in
ml/build_historical_dataset.py — see notes/ALGORITHM.md's 2026-07-06 entry
for why real game-day context beats a static cross-product).

Reuses fetch_season_schedule from ml/build_historical_dataset.py verbatim
for real game-day starters. This script only adds the K-specific labeling
(actual strikeouts → over_hit) on top of that shared schedule fetch.

Note: fetch_season_schedule's game dicts only carry home_pitcher_id /
away_pitcher_id (no pitcher name field), so pitcher full names are
resolved separately via the MLB People API (with an in-process cache,
since the same starter often appears across multiple games in a
backfill window).

Run once per season to backfill; safe to re-run (upsert via
save_pick_factors_k's ON CONFLICT).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from agents.bet_tracker import get_db_conn, save_pick_factors_k
from agents.predictor import MLB_API_BASE
from ml.build_historical_dataset import fetch_season_schedule
from ml.fetch_actual_k_results import fetch_strikeouts_for_date

_PITCHER_NAME_CACHE: dict[int, str] = {}


def _pitcher_name(pid: int) -> str | None:
    """Resolve a pitcher's full name from their MLB person ID, with caching."""
    if pid in _PITCHER_NAME_CACHE:
        return _PITCHER_NAME_CACHE[pid]
    try:
        resp = requests.get(f"{MLB_API_BASE}/people/{pid}", timeout=15)
        resp.raise_for_status()
        people = resp.json().get("people", [])
        name = people[0].get("fullName") if people else None
    except Exception:
        name = None
    _PITCHER_NAME_CACHE[pid] = name
    return name


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
                if not pid:
                    continue
                name = _pitcher_name(pid)
                if not name:
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

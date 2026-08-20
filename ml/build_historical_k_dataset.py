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
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from agents.bet_tracker import get_db_conn, save_pick_factors_k
from agents.predictor import MLB_API_BASE
from ml.build_historical_dataset import (
    fetch_season_schedule, _load_cache, _save_cache, _sf, CURRENT_YEAR,
)
from ml.fetch_actual_k_results import fetch_strikeouts_for_date

SAVANT_BASE = "https://baseballsavant.mlb.com"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

_PITCHER_NAME_CACHE: dict[int, str] = {}


def fetch_k_statcast_season(year: int) -> dict:
    """
    Fetch season-level pitcher K-rate Statcast leaderboard for historical
    backfill (mirrors agents/k_predictor.py's _fetch_pitcher_k_statcast,
    year-parameterized). Returns rows keyed by player_id (int) and
    lowercased 'last, first' name → {k_percent, whiff_percent,
    csw_percent, swinging_strike_percent}. Cached for past seasons via the
    same cache/historical/ helpers fetch_statcast_season uses.
    """
    cache_key = f"statcast_k_{year}.json"
    if year < CURRENT_YEAR:
        cached = _load_cache(cache_key)
        if cached:
            return cached

    url = (
        f"{SAVANT_BASE}/leaderboard/custom"
        f"?year={year}&type=pitcher&filter=&sort=4&sortDir=desc&min=5"
        f"&selections=k_percent,whiff_percent,csw_percent,swinging_strike_percent"
        f"&chart=false&r=no&exactNameSearch=false&csv=true"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text.lstrip("﻿")
        reader = csv.DictReader(io.StringIO(text))
        result = {}
        for row in reader:
            name = (row.get("last_name, first_name") or "").strip().lower()
            pid_raw = row.get("player_id") or ""
            entry = {
                "k_percent": _sf(row.get("k_percent")),
                "whiff_percent": _sf(row.get("whiff_percent")),
                "csw_percent": _sf(row.get("csw_percent")),
                "swinging_strike_percent": _sf(row.get("swinging_strike_percent")),
            }
            try:
                result[int(pid_raw)] = entry
            except (ValueError, TypeError):
                pass
            if name:
                result.setdefault(name, entry)
    except Exception:
        return {}

    if year < CURRENT_YEAR and result:
        _save_cache(cache_key, result)
    return result


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
    Label each historical start with actual strikeouts, real season-level
    Statcast K signals, and a synthetic k_line: that pitcher's own
    trailing average of ACTUAL K's from earlier starts already processed
    in this backfill run, rounded to the nearest 0.5. No real historical
    odds line exists, so this proxy stands in for one — a pitcher's first
    start in the window has no prior data and is written with k_line/
    over_hit left NULL (excluded from training, same as before, but only
    for that one row). algo_version "historical-1.0" distinguishes these
    from live-line rows.
    """
    k_statcast = fetch_k_statcast_season(year)
    sorted_dates = sorted(schedule.keys())
    running_ks: dict[str, list[int]] = {}
    written, skipped = 0, 0

    for game_date in sorted_dates:
        games = schedule[game_date]
        actual_ks = fetch_strikeouts_for_date(game_date)
        if not actual_ks:
            skipped += len(games)
            continue

        day_results = []  # (name, actual) folded into running_ks after this date's rows are written
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
                day_results.append((name, actual))

                prior = running_ks.get(name)
                k_line = round(sum(prior) / len(prior) * 2) / 2 if prior else None
                over_hit = (1 if actual > k_line else 0) if k_line is not None else None
                statcast_row = k_statcast.get(pid) or k_statcast.get(name.lower(), {})

                if not dry_run:
                    save_pick_factors_k(
                        game_date, name,
                        {
                            "actual_k": actual,
                            "k_line": k_line,
                            "k_percent": statcast_row.get("k_percent"),
                            "whiff_percent": statcast_row.get("whiff_percent"),
                            "csw_percent": statcast_row.get("csw_percent"),
                            "swinging_strike_percent": statcast_row.get("swinging_strike_percent"),
                        },
                        algo_version="historical-1.0",
                        game_pk=str(game.get("game_pk")),
                    )
                    conn = get_db_conn()
                    try:
                        conn.execute(
                            "UPDATE pick_factors_k SET actual_k=?, over_hit=? "
                            "WHERE bet_date=? AND pitcher=? AND game_pk=?",
                            (actual, over_hit, game_date, name, str(game.get("game_pk"))),
                        )
                        conn.commit()
                    finally:
                        conn.close()
                written += 1

        for name, actual in day_results:
            running_ks.setdefault(name, []).append(actual)

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

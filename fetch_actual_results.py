"""
fetch_actual_results.py
Run after games end (~11pm ET) to auto-fetch who homered from the MLB API
and update pick_factors.homered for every player Homer scored that day.

This is the data labeling step for ML training. It does NOT touch your bets
in the singles table — it only labels pick_factors rows with 1 (homered) or 0.

Usage:
    python fetch_actual_results.py              # label today
    python fetch_actual_results.py 2026-04-14   # label a specific past date
    python fetch_actual_results.py --show       # show today's results without saving
"""

import argparse
import os
import sqlite3
import sys
from datetime import date
from difflib import SequenceMatcher

import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bets.db")


def fetch_homers_for_date(game_date: str) -> dict[str, int] | None:
    """
    Query MLB Stats API for all players who hit HRs on game_date.
    Returns:
      {full_player_name: hr_count}  — all players with ≥1 HR (may be empty dict)
      None                          — no completed games found (off day or all pending)
    Only includes completed games.
    """
    print(f"Fetching MLB results for {game_date}...")

    resp = requests.get(f"{MLB_API_BASE}/schedule", params={
        "date": game_date,
        "sportId": 1,
        "hydrate": "linescore",
    }, timeout=20)
    resp.raise_for_status()
    schedule = resp.json()

    homers: dict[str, int] = {}
    games_checked = 0
    games_pending = 0

    for date_entry in schedule.get("dates", []):
        for game in date_entry.get("games", []):
            state = game.get("status", {}).get("abstractGameState", "")
            if state not in ("Final", "Game Over"):
                games_pending += 1
                continue

            game_pk = game["gamePk"]
            games_checked += 1

            try:
                box_resp = requests.get(
                    f"{MLB_API_BASE}/game/{game_pk}/boxscore", timeout=20
                )
                box_resp.raise_for_status()
                boxscore = box_resp.json()
            except Exception as e:
                print(f"  Warning: could not fetch boxscore for game {game_pk}: {e}")
                continue

            for side in ("home", "away"):
                players = boxscore.get("teams", {}).get(side, {}).get("players", {})
                for pid, pdata in players.items():
                    name = pdata.get("person", {}).get("fullName", "")
                    hr = pdata.get("stats", {}).get("batting", {}).get("homeRuns", 0)
                    if name and hr:
                        homers[name] = homers.get(name, 0) + hr

    print(f"  Games completed: {games_checked} | Games pending: {games_pending}")
    # Return None when no games were completed (off day or all still in progress)
    if games_checked == 0:
        return None
    return homers


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _best_match(player: str, homer_names: list[str]) -> tuple[str | None, float]:
    """Return (best_matching_name, similarity_score) from the homer set."""
    if not homer_names:
        return None, 0.0
    scored = [(n, _similarity(player, n)) for n in homer_names]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0]


def update_pick_factors(game_date: str, homers: dict[str, int],
                        dry_run: bool = False) -> None:
    """
    For every row in pick_factors on game_date:
      - homered=1 if player name matches a homer (exact or fuzzy ≥0.85)
      - homered=0 otherwise (player was in Homer's ranked list but didn't homer)
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT id, player FROM pick_factors WHERE bet_date=?",
            (game_date,)
        ).fetchall()

        if not rows:
            print(f"  No pick_factors rows found for {game_date}.")
            print("  Run daily_picks.py first to generate today's picks.")
            return

        homer_names = list(homers.keys())
        results: list[tuple[str, int, str]] = []  # (player, homered, matched_name)

        for row_id, player in rows:
            # Exact match first
            if player in homers:
                results.append((player, 1, player))
                if not dry_run:
                    conn.execute("UPDATE pick_factors SET homered=1 WHERE id=?", (row_id,))
                continue

            # Fuzzy match
            match_name, sim = _best_match(player, homer_names)
            if match_name and sim >= 0.85:
                results.append((player, 1, match_name))
                if not dry_run:
                    conn.execute("UPDATE pick_factors SET homered=1 WHERE id=?", (row_id,))
            else:
                results.append((player, 0, ""))
                if not dry_run:
                    conn.execute("UPDATE pick_factors SET homered=0 WHERE id=?", (row_id,))

        if not dry_run:
            conn.commit()

        # Print summary
        hr_players  = [(p, m) for p, h, m in results if h == 1]
        no_hr       = [p for p, h, m in results if h == 0]
        hit_rate    = len(hr_players) / len(results) * 100 if results else 0

        print(f"\n  {'[DRY RUN] ' if dry_run else ''}Results for {game_date}")
        print(f"  Total players scored by Homer: {len(results)}")
        print(f"  Homered: {len(hr_players)} ({hit_rate:.1f}%)")
        print(f"  Did not homer: {len(no_hr)}")

        if hr_players:
            print(f"\n  Players who homered:")
            for player, matched in hr_players:
                note = f" (matched: {matched})" if matched != player else ""
                print(f"    ✓ {player}{note}")

        # Show MLB homers not captured in pick_factors (players Homer didn't rank)
        ranked_names = {p for p, _, _ in results}
        untracked = [n for n in homer_names if not any(
            _similarity(n, r) >= 0.85 for r in ranked_names
        )]
        if untracked:
            print(f"\n  MLB homers NOT in Homer's ranked list ({len(untracked)}):")
            for n in sorted(untracked):
                print(f"    — {n}")

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Label pick_factors with actual HR outcomes.")
    parser.add_argument("date", nargs="?", default=date.today().isoformat(),
                        help="Date to label (YYYY-MM-DD, default: today)")
    parser.add_argument("--show", action="store_true",
                        help="Dry run — show results without saving to DB")
    args = parser.parse_args()

    homers = fetch_homers_for_date(args.date)

    if homers is None:
        print(f"\n  No completed games found for {args.date}.")
        print("  Games may still be in progress — re-run after 11pm ET.")
        return

    if not homers:
        print(f"\n  No home runs recorded for {args.date} (games completed).")
        print("  Labeling all picked players as homered=0.")
    else:
        print(f"\n  MLB home runs today ({len(homers)} players):")
        for name, count in sorted(homers.items()):
            plural = "s" if count > 1 else ""
            print(f"    {name}: {count} HR{plural}")

    update_pick_factors(args.date, homers, dry_run=args.show)

    if not args.show:
        print(f"\n  pick_factors.homered updated for {args.date}.")
        print("  Run optimize_weights.py weekly to retrain the model.")


if __name__ == "__main__":
    main()

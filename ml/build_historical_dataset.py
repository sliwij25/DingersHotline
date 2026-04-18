"""
build_historical_dataset.py

Bootstraps the ML training dataset with labeled historical examples (2015–present).

Efficiency design:
  - 2 API calls per season: Statcast leaderboard CSV + HR events CSV
  - Seasons 2015–(current-1) are cached to cache/historical/ and never re-fetched
  - Current season (2026) is always re-fetched since stats update daily
  - Writes ~150–250k labeled rows to pick_factors for ML training
  - Uses INSERT OR IGNORE so live picks are never overwritten

How labeling works:
  - Power hitter pool = all batters with barrel% ≥ 5 and ≥ 100 PA in that season
  - For each game date: pool members who homered → homered=1, others → homered=0
  - Season-level Statcast signals are used (no BPP, odds, or pitcher data)

Usage:
    python build_historical_dataset.py                # all seasons 2015–present
    python build_historical_dataset.py --year 2023    # one specific season
    python build_historical_dataset.py --refresh      # current season only (fast update)
    python build_historical_dataset.py --stats        # show DB row counts, no fetching
    python build_historical_dataset.py --dry-run      # show what would be written, no DB writes
"""

import argparse
import csv
import io
import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

os.chdir(str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Constants ──────────────────────────────────────────────────────────────────

SAVANT_BASE  = "https://baseballsavant.mlb.com"
DB_PATH      = Path("data/bets.db")
CACHE_DIR    = Path("cache/historical")
CURRENT_YEAR = date.today().year
START_YEAR   = 2015

# Minimum requirements to be in the power hitter candidate pool.
# Only these players get scored as "could have hit a HR today".
MIN_PA            = 100    # minimum plate appearances in the season
MIN_BARREL_RATE   = 5.0   # minimum barrel% — filters out pure contact hitters

# Sample every Nth game date to control DB size while keeping enough variance.
# 1 = all dates (~180/season), 3 = every 3rd (~60/season), 5 = every 5th (~36/season)
DATE_SAMPLE_EVERY = 3

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / name


def _load_cache(name: str) -> dict | None:
    p = _cache_path(name)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def _save_cache(name: str, data: dict) -> None:
    with open(_cache_path(name), "w") as f:
        json.dump(data, f, separators=(",", ":"))  # compact JSON, no indentation


# ── Statcast leaderboard fetch ─────────────────────────────────────────────────

def fetch_statcast_season(year: int) -> dict[str, dict]:
    """
    Fetch full Statcast batter leaderboard for a season.
    Returns {normalized_name: {barrel_rate, ev_avg, xiso, ...}}.
    Cached for all seasons except the current year.
    """
    cache_key = f"statcast_{year}.json"
    if year < CURRENT_YEAR:
        cached = _load_cache(cache_key)
        if cached:
            return cached

    print(f"  Fetching Statcast leaderboard {year}...", end=" ", flush=True)
    # Current season uses a lower PA threshold — players only have ~15-25 PA in April
    pa_threshold = MIN_PA if year < CURRENT_YEAR else 15
    url = (
        f"{SAVANT_BASE}/leaderboard/custom"
        f"?year={year}&type=batter&filter=&sort=4&sortDir=desc&min={pa_threshold}"
        f"&selections=barrel_batted_rate,hard_hit_percent,hr_flyballs_rate_batter,"
        f"exit_velocity_avg,sweet_spot_percent,xiso,xslg,xhrs,"
        f"flyballs_percent,launch_angle_avg,pa"
        f"&chart=false&r=no&exactNameSearch=false&csv=true"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        text = resp.text.lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(text))
        result = {}
        for row in reader:
            name = (row.get("last_name, first_name") or "").strip().lower()
            if not name:
                continue
            try:
                barrel = float(row.get("barrel_batted_rate") or 0)
                pa     = int(row.get("pa") or 0)
            except (ValueError, TypeError):
                continue
            if pa < pa_threshold or barrel < MIN_BARREL_RATE:
                continue  # skip contact hitters — not HR candidates
            result[name] = {
                "barrel_rate":      _sf(row.get("barrel_batted_rate")),
                "hard_hit_pct":     _sf(row.get("hard_hit_percent")),
                "hr_fb_ratio":      _sf(row.get("hr_flyballs_rate_batter")),
                "ev_avg":           _sf(row.get("exit_velocity_avg")),
                "sweet_spot_pct":   _sf(row.get("sweet_spot_percent")),
                "xiso":             _sf(row.get("xiso")),
                "xslg":             _sf(row.get("xslg")),
                "xhr_rate":         _sf(row.get("xhrs")),
                "fb_pct":           _sf(row.get("flyballs_percent")),
                "launch_angle":     _sf(row.get("launch_angle_avg")),
            }
        print(f"{len(result)} power hitters")
    except Exception as e:
        print(f"ERROR: {e}")
        return {}

    if year < CURRENT_YEAR and result:
        _save_cache(cache_key, result)
    return result


# ── HR events fetch ────────────────────────────────────────────────────────────

def fetch_hr_events_season(year: int) -> dict[str, list[str]]:
    """
    Fetch all home run events for a season from Statcast search.
    Returns {date_str: [normalized_player_name, ...]} for every game date.
    Cached for all seasons except the current year.
    """
    cache_key = f"hr_events_{year}.json"
    if year < CURRENT_YEAR:
        cached = _load_cache(cache_key)
        if cached:
            return cached

    print(f"  Fetching HR events {year}...", end=" ", flush=True)
    url = (
        f"{SAVANT_BASE}/statcast_search/csv"
        f"?all=true&hfAB=home_run%7C&hfGT=R%7C&hfSea={year}%7C"
        f"&player_type=batter&type=details&csv=true"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=60)
        text = resp.text.lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(text))
        result: dict[str, list[str]] = {}
        for row in reader:
            game_date = (row.get("game_date") or "").strip()
            player    = (row.get("player_name") or "").strip().lower()
            if game_date and player:
                result.setdefault(game_date, [])
                if player not in result[game_date]:
                    result[game_date].append(player)
        total_hrs = sum(len(v) for v in result.values())
        print(f"{len(result)} game dates, {total_hrs} HR events")
    except Exception as e:
        print(f"ERROR: {e}")
        return {}

    if year < CURRENT_YEAR and result:
        _save_cache(cache_key, result)
    return result


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    # Ensure all new columns exist (runs migration if needed)
    from agents.bet_tracker import _ensure_pick_factors_table
    _ensure_pick_factors_table(conn)
    return conn


def _db_row_counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN homered=1 THEN 1 ELSE 0 END) as positives,
            SUM(CASE WHEN homered=0 THEN 1 ELSE 0 END) as negatives,
            SUM(CASE WHEN homered IS NULL THEN 1 ELSE 0 END) as unlabeled,
            COUNT(DISTINCT bet_date) as dates,
            MIN(bet_date) as earliest,
            MAX(bet_date) as latest
        FROM pick_factors
    """).fetchone()
    keys = ("total", "positives", "negatives", "unlabeled", "dates", "earliest", "latest")
    return dict(zip(keys, rows))


# ── Write labeled rows ─────────────────────────────────────────────────────────

def write_season_to_db(
    year: int,
    batter_stats: dict[str, dict],
    hr_events: dict[str, list[str]],
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    For each sampled game date in hr_events, write:
      - homered=1 for power hitters who hit a HR
      - homered=0 for power hitters who didn't

    Returns (rows_written, rows_skipped_conflict).
    """
    if not batter_stats or not hr_events:
        return 0, 0

    all_pool = set(batter_stats.keys())  # power hitter candidate pool
    algo_ver = f"hist_{year}"

    # Sample game dates evenly across the season
    sorted_dates = sorted(hr_events.keys())
    sampled_dates = sorted_dates[::DATE_SAMPLE_EVERY]

    if dry_run:
        est_pos = sum(
            len([n for n in hr_events[d] if n in all_pool])
            for d in sampled_dates
        )
        est_neg = len(sampled_dates) * len(all_pool) - est_pos
        print(f"    [DRY RUN] {year}: {len(sampled_dates)} dates → "
              f"~{est_pos} positives, ~{est_neg} negatives")
        return est_pos + est_neg, 0

    conn = _get_conn()
    written = skipped = 0

    try:
        for batch_start in range(0, len(sampled_dates), 20):
            batch = sampled_dates[batch_start:batch_start + 20]
            rows_to_insert = []

            for game_date in batch:
                homers_today = set(hr_events.get(game_date, []))
                for player_key, signals in batter_stats.items():
                    homered = 1 if player_key in homers_today else 0
                    rows_to_insert.append((
                        game_date,
                        player_key,          # stored as "last, first" normalized
                        algo_ver,
                        None,                # confidence (not applicable for historical)
                        None,                # score (no Homer ranking for historical)
                        None,                # rank
                        homered,
                        signals.get("barrel_rate"),
                        signals.get("hard_hit_pct"),
                        signals.get("hr_fb_ratio"),
                        signals.get("xiso"),
                        signals.get("xslg"),
                        signals.get("xhr_rate"),
                        signals.get("fb_pct"),
                        signals.get("launch_angle"),
                        signals.get("ev_avg"),
                        signals.get("sweet_spot_pct"),
                        None,  # bpp_hr_pct — not available historically
                        None,  # park_hr_factor — not available historically
                        None,  # ev_10 / kelly_size / value_edge / pinnacle_odds
                        None,
                        None,
                        None,
                        None,  # platoon
                        None,  # recent_form_14d
                        None,  # pitcher_hr_per_9
                        None,  # h2h_hr
                        None,  # h2h_ab
                        None,  # is_home
                        1,     # lineup_confirmed (season-level data = assume confirmed)
                        None,  # venue_slugging
                    ))

            # Bulk insert — INSERT OR IGNORE so live picks are never overwritten
            conn.executemany("""
                INSERT OR IGNORE INTO pick_factors
                  (bet_date, player, algo_version, confidence, score, rank, homered,
                   barrel_rate, hard_hit_pct, hr_fb_ratio, xiso, xslg, xhr_rate,
                   fb_pct, launch_angle, ev_avg, sweet_spot_pct,
                   bpp_hr_pct, park_hr_factor,
                   ev_10, kelly_size, value_edge, pinnacle_odds, platoon,
                   recent_form_14d, pitcher_hr_per_9,
                   h2h_hr, h2h_ab, is_home, lineup_confirmed, venue_slugging)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows_to_insert)
            conn.commit()
            written  += conn.execute("SELECT changes()").fetchone()[0]

        # Count total written (INSERT OR IGNORE doesn't count skipped rows in changes())
        written = conn.execute(
            "SELECT COUNT(*) FROM pick_factors WHERE algo_version=?", (algo_ver,)
        ).fetchone()[0]

    finally:
        conn.close()

    return written, skipped


# ── Utility ────────────────────────────────────────────────────────────────────

def _sf(val) -> float | None:
    """Safe float conversion — returns None on failure."""
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return None


def show_stats() -> None:
    """Print current pick_factors DB stats."""
    conn = _get_conn()
    try:
        counts = _db_row_counts(conn)
        print(f"\n  pick_factors table:")
        print(f"  Total rows:     {counts['total']:,}")
        print(f"  Homered=1:      {counts['positives']:,}")
        print(f"  Homered=0:      {counts['negatives']:,}")
        print(f"  Unlabeled:      {counts['unlabeled']:,}")
        print(f"  Unique dates:   {counts['dates']:,}")
        print(f"  Date range:     {counts['earliest']} → {counts['latest']}")

        print(f"\n  Rows by algo_version:")
        rows = conn.execute("""
            SELECT algo_version,
                   COUNT(*) as n,
                   SUM(CASE WHEN homered=1 THEN 1 ELSE 0 END) as pos,
                   MIN(bet_date), MAX(bet_date)
            FROM pick_factors
            GROUP BY algo_version
            ORDER BY algo_version
        """).fetchall()
        print(f"  {'Version':<16} {'Rows':>8}  {'HRs':>6}  {'Date range'}")
        print("  " + "-" * 55)
        for ver, n, pos, mn, mx in rows:
            hr_rate = pos / n * 100 if n else 0
            print(f"  {ver:<16} {n:>8,}  {pos:>5} ({hr_rate:.1f}%)  {mn} → {mx}")
    finally:
        conn.close()


# ── Main ───────────────────────────────────────────────────────────────────────

def process_year(year: int, dry_run: bool = False) -> None:
    print(f"\n── {year} {'(current — always re-fetched)' if year == CURRENT_YEAR else '(cached if available)'} ──")
    t0 = time.time()

    batter_stats = fetch_statcast_season(year)
    hr_events    = fetch_hr_events_season(year)

    if not batter_stats or not hr_events:
        print(f"  Skipping {year} — no data returned.")
        return

    written, _ = write_season_to_db(year, batter_stats, hr_events, dry_run=dry_run)
    elapsed = time.time() - t0
    if not dry_run:
        positive_rate = sum(
            len([n for n in hr_events.get(d, []) if n in batter_stats])
            for d in sorted(hr_events.keys())[::DATE_SAMPLE_EVERY]
        )
        total_sampled = len(sorted(hr_events.keys())[::DATE_SAMPLE_EVERY]) * len(batter_stats)
        rate = positive_rate / total_sampled * 100 if total_sampled else 0
        print(f"  Wrote {written:,} rows  |  HR rate in pool: {rate:.1f}%  |  {elapsed:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build historical HR training dataset.")
    parser.add_argument("--year",         type=int,          help="Process a single year")
    parser.add_argument("--refresh",      action="store_true", help="Current season only")
    parser.add_argument("--stats",        action="store_true", help="Show DB stats and exit")
    parser.add_argument("--dry-run",      action="store_true", help="Show what would be written")
    parser.add_argument("--start",        type=int, default=START_YEAR, help=f"Start year (default {START_YEAR})")
    args = parser.parse_args()

    print("=" * 60)
    print("  HISTORICAL HR DATASET BUILDER")
    print("=" * 60)

    if args.stats:
        show_stats()
        return

    years = (
        [args.year]            if args.year    else
        [CURRENT_YEAR]         if args.refresh else
        list(range(args.start, CURRENT_YEAR + 1))
    )

    print(f"\n  Seasons to process: {years}")
    print(f"  Power hitter pool: barrel% ≥ {MIN_BARREL_RATE}, PA ≥ {MIN_PA}")
    print(f"  Date sampling: every {DATE_SAMPLE_EVERY}rd game day per season")
    print(f"  Cache: cache/historical/  (2015–{CURRENT_YEAR-1} only)")
    if args.dry_run:
        print("  [DRY RUN] — no DB writes")

    t_total = time.time()
    for year in years:
        process_year(year, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print(f"  Done in {time.time() - t_total:.1f}s")
    if not args.dry_run:
        show_stats()
        print(f"\n  Next step: python optimize_weights.py")
    print("=" * 60)


if __name__ == "__main__":
    main()

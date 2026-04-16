"""
test_homer_prompt.py
Load cached Homer context and test pick logic WITHOUT re-fetching data.

Usage:
    python test_homer_prompt.py                         # top 8 picks from latest cache
    python test_homer_prompt.py --debug Aaron Judge     # explain why a player scored low/high
    python test_homer_prompt.py --pipeline              # show data pipeline health (% signals populated)
    python test_homer_prompt.py debug_context_2026-04-15.json  # specific cache file

This is the primary iteration tool — change scoring logic in predictor.py, then
re-run this to see the effect without making any API calls.
"""

import json
import sys
import os
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "api", ".env"))

from agents import Homer
from agents.predictor import Homer as HomerClass


def find_latest_cache() -> Path | None:
    caches = sorted(Path(__file__).parent.glob("debug_context_*.json"), reverse=True)
    return caches[0] if caches else None


def load_context(cache_file: str | None = None) -> dict:
    path = Path(cache_file) if cache_file else find_latest_cache()
    if not path or not path.exists():
        print("No cache file found. Run: python daily_picks.py  (once, to create cache)")
        sys.exit(1)
    print(f"Cache: {path.name}\n")
    with open(path) as f:
        return json.load(f)


def cmd_picks(context: dict, top_n: int = 8):
    """Show top N picks using current scoring logic."""
    homer = Homer()
    homer._context = context
    player_signals = context.get("player_signals", {})
    print(f"Scoring {len(player_signals)} players...\n")
    ranked = homer._rank_picks_python(player_signals, top_n=top_n)
    today  = context.get("date", date.today().isoformat())
    print(homer._format_narrative(ranked, today, context.get("availability", "{}")))


def cmd_debug_player(context: dict, name: str):
    """Show every signal for a named player and explain their score."""
    from agents.predictor import Homer as H
    homer = H()
    homer._context = context
    player_signals = context.get("player_signals", {})

    # Fuzzy match
    name_lower = name.lower()
    matches = [(p, s) for p, s in player_signals.items() if name_lower in p.lower()]

    if not matches:
        print(f"No player found matching '{name}'.")
        print("Available players (sample):", list(player_signals.keys())[:10])
        return

    for player, sig in matches:
        score = homer._score_player(sig)
        print(f"\n{'='*60}")
        print(f"  {player}  —  score={score}")
        print(f"{'='*60}")

        # Signal table
        signal_keys = [
            ("status",           "Lineup status"),
            ("matchup",          "Matchup"),
            ("venue",            "Venue"),
            ("bpp_hr_pct",       "BPP HR prob (%)"),
            ("bpp_proj_rank",    "BPP rank"),
            ("park_hr_factor",   "Park HR factor"),
            ("temp_f",           "Temperature (°F)"),
            ("wind_mph",         "Wind (mph)"),
            ("xiso",             "xISO"),
            ("xslg",             "xSLG (exp. slugging)"),
            ("xhr_rate",         "xHR% (exp. HR rate)"),
            ("barrel_rate",      "Barrel rate (%)"),
            ("hard_hit_pct",     "Hard hit (%)"),
            ("ev_avg",           "Exit velo avg (mph)"),
            ("sweet_spot_pct",   "Sweet spot (%)"),
            ("hr_fb_ratio",      "HR/FB ratio (%)"),
            ("fb_pct",           "Fly ball rate (%)"),
            ("launch_angle",     "Avg launch angle (°)"),
            ("platoon",          "Platoon"),
            ("recent_form_14d",  "HRs last 14 days"),
            ("pitcher_hr_per_9", "Pitcher HR/9 (L3)"),
            ("h2h_hr",           "H2H HR vs pitcher"),
            ("h2h_ab",           "H2H AB vs pitcher"),
            ("ev_10",            "Expected value ($10)"),
            ("value_edge",       "Value edge (pp)"),
            ("pinnacle_odds",    "Pinnacle odds"),
            ("venue_slugging",   "Venue SLG"),
        ]

        for key, label in signal_keys:
            val = sig.get(key)
            populated = "✓" if val is not None else "✗ MISSING"
            print(f"  {label:<28} {str(val):<15} {populated}")

        # Score contribution breakdown
        pa = sig.get("pa")
        if pa is not None and pa < 40:
            pa_scale = 0.5 if pa >= 20 else 0.0
            print(f"\n  ⚠ PA={pa} — Statcast metrics scaled to {pa_scale:.0%} weight (need 40+ for full credit)")
        print(f"\n  Score breakdown:")
        status = sig.get("status", "unknown")
        if status == "waiting":  print(f"    status=waiting         -1.0")
        if status == "unknown":  print(f"    status=unknown         -3.0")

        ev = sig.get("ev_10")
        if ev is not None:
            pts = 5 if ev>3 else 3 if ev>1 else 1 if ev>0 else -1 if ev>-1 else -3
            print(f"    ev_10={ev:.2f}              {pts:+.1f}")

        bpp = sig.get("bpp_hr_pct")
        if bpp is not None:
            pts = 8 if bpp>=23 else 6 if bpp>=21 else 4 if bpp>=19 else 2 if bpp>=16 else 1 if bpp>=12 else -2 if bpp<10 else 0
            print(f"    bpp_hr_pct={bpp:.1f}%         {pts:+.1f}")

        rank = sig.get("bpp_proj_rank")
        if rank is not None:
            pts = 3 if rank<=5 else 1 if rank<=15 else 0
            print(f"    bpp_proj_rank=#{rank}         {pts:+.1f}")

        xiso = sig.get("xiso")
        if xiso is not None:
            pts = 4 if xiso>=0.250 else 3 if xiso>=0.200 else 2 if xiso>=0.160 else 1 if xiso>=0.120 else -1 if xiso<0.080 else 0
            print(f"    xiso={xiso:.3f}              {pts:+.1f}")

        barrel = sig.get("barrel_rate")
        if barrel is not None:
            pts = 3 if barrel>=15 else 2 if barrel>=10 else 1 if barrel>=5 else -1
            print(f"    barrel_rate={barrel:.1f}%       {pts:+.1f}")

        print(f"\n  TOTAL: {score}")


def cmd_pipeline(context: dict):
    """Show what % of players have each signal populated — diagnose data issues."""
    player_signals = context.get("player_signals", {})
    total = len(player_signals)
    if total == 0:
        print("No player_signals in cache.")
        return

    print(f"Data pipeline health — {total} players in cache\n")
    print(f"  {'Signal':<28} {'Populated':>10}  {'Missing':>10}  {'Coverage'}")
    print("  " + "-" * 65)

    keys = [
        "bpp_hr_pct", "bpp_proj_rank", "park_hr_factor", "temp_f", "wind_mph",
        "xiso", "xslg", "xhr_rate", "barrel_rate", "hard_hit_pct", "ev_avg",
        "sweet_spot_pct", "hr_fb_ratio", "fb_pct", "launch_angle",
        "pitcher_hr_per_9", "h2h_hr", "ev_10", "value_edge", "pinnacle_odds",
        "recent_form_14d", "platoon", "venue_slugging",
    ]

    for key in keys:
        populated = sum(1 for s in player_signals.values() if s.get(key) is not None)
        missing   = total - populated
        pct       = populated / total * 100
        bar       = "█" * int(pct / 5)
        flag      = "  ← CHECK" if pct < 20 else ""
        print(f"  {key:<28} {populated:>10}  {missing:>10}  {pct:5.1f}%  {bar}{flag}")

    print(f"\n  Cache date: {context.get('date', 'unknown')}")
    print(f"  Cache file: {(find_latest_cache() or Path()).name}")


def main():
    parser = argparse.ArgumentParser(description="Test Homer picks from cache.")
    parser.add_argument("cache_file",  nargs="?",        help="Path to debug_context JSON (optional)")
    parser.add_argument("--debug",     nargs="+",        help="Show all signals for a player (e.g. --debug Aaron Judge)")
    parser.add_argument("--pipeline",  action="store_true", help="Show data pipeline health")
    parser.add_argument("--top",       type=int, default=8, help="Number of picks to show (default 8)")
    args = parser.parse_args()

    context = load_context(args.cache_file)

    if args.debug:
        cmd_debug_player(context, " ".join(args.debug))
    elif args.pipeline:
        cmd_pipeline(context)
    else:
        cmd_picks(context, top_n=args.top)


if __name__ == "__main__":
    main()

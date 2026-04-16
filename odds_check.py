"""
odds_check.py
Run this anytime in Spyder to see today's HR prop lines across all books.
No Ollama required — just fetches and displays the odds comparison.

Best time to run: after 11am ET when most books have posted player props.
"""

import json
import os
import sys
from datetime import date

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "api", ".env"))

from agents.predictor import fetch_odds_comparison

TODAY = date.today().isoformat()

print("=" * 70)
print(f"  ODDS COMPARISON — {TODAY}")
print("=" * 70)
print("  Pinnacle = sharpest line. Beat Pinnacle on Novig/ProphetX = value.\n")

raw  = fetch_odds_comparison()
data = json.loads(raw)

if data.get("status") != "success":
    print(f"  {data.get('message', 'No data returned.')}")
    sys.exit(0)

comparisons = data.get("comparisons", [])
if not comparisons:
    print("  No HR prop odds posted yet. Try again after 11am ET.")
    sys.exit(0)

# ── Summary table ─────────────────────────────────────────────────────────────
print(f"  {'Player':<26} {'Pinnacle':<11} {'Best Odds':<11} "
      f"{'Best Book':<18} {'Consensus%':<11} {'Edge':<9} {'EV($10)':<9} {'Kelly':<8} {'Flag'}")
print("  " + "-" * 115)

for c in comparisons:
    flag     = "VALUE" if c.get("value_flag") == "VALUE" else ""
    edge     = c.get("value_edge", 0)
    edge_str = f"+{edge:.1f}pp" if edge >= 0 else f"{edge:.1f}pp"

    ev = c.get("ev_10")
    ev_str = f"${ev:+.2f}" if ev is not None else "—"

    kelly = c.get("kelly_size")
    kelly_str = f"${kelly:.2f}" if kelly is not None else "—"

    print(f"  {c['player']:<26} {c['pinnacle']:<11} {c['best_odds']:<11} "
          f"{c['best_book']:<18} {c['consensus_prob']:<11} {edge_str:<9} "
          f"{ev_str:<9} {kelly_str:<8} {flag}")

# ── Per-player book breakdown ─────────────────────────────────────────────────
print("\n\n" + "=" * 70)
print("  ALL BOOKS — odds by player")
print("=" * 70)

for c in comparisons:
    flag = "  *** VALUE ***" if c.get("value_flag") == "VALUE" else ""
    print(f"\n  {c['player']}  ({c['matchup']}){flag}")
    for book, odds in c["all_books"].items():
        best_mark = "  <- BEST"       if book == c["best_book"] else ""
        pin_mark  = "  <- SHARP LINE" if "Pinnacle" in book     else ""
        print(f"    {book:<24} {odds}{best_mark}{pin_mark}")
    print(f"    {'Consensus':<24} {c['consensus_prob']}  (edge {'+' if c['value_edge'] >= 0 else ''}{c['value_edge']:.1f}pp)")

print("\n" + "=" * 70)
value_count = sum(1 for c in comparisons if c.get("value_flag") == "VALUE")
print(f"  {len(comparisons)} players  |  {value_count} VALUE flags")
print("=" * 70)

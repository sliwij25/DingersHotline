"""
cache_odds.py
Run at ~2-4pm after books post HR props for today's games.

What it does:
  1. Fetches best available odds for every player from the Odds API
  2. Stores best_odds + pinnacle_odds in pick_factors for today's top-20 picks
  3. Re-renders the site with odds displayed on each player card
  4. Pushes to GitHub

Usage:
  python cache_odds.py              # today's date
  python cache_odds.py 2026-04-16   # specific date (backfill)
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "api", ".env"))

from agents.predictor import fetch_odds_comparison, Homer
from agents.bet_tracker import backfill_pick_odds, model_pnl_report
from generate_html import generate_picks_html

target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

print("=" * 60)
print(f"  CACHE ODDS — {target_date}")
print("=" * 60)

# ── 1. Fetch current odds ──────────────────────────────────────────────────────

print("\n  Fetching odds from The Odds API...")
try:
    raw = fetch_odds_comparison()
    data = json.loads(raw)
except Exception as e:
    print(f"  ERROR: Could not fetch odds — {e}")
    sys.exit(1)

if data.get("status") != "success":
    print(f"  No odds available yet: {data.get('message', 'unknown')}")
    print("  Books typically post HR props 2-4 hours before first pitch.")
    sys.exit(0)

comparisons = data.get("comparisons", [])
if not comparisons:
    print("  No HR prop data returned yet. Try again closer to game time.")
    sys.exit(0)

print(f"  Got odds for {len(comparisons)} players.")

# ── 2. Store in pick_factors ───────────────────────────────────────────────────

n_updated = backfill_pick_odds(target_date, comparisons)
print(f"  Stored odds for {n_updated} pick(s) in pick_factors.")

# Report any picks that still have no odds (user can manually supply)
from agents.base import get_db_conn
conn = get_db_conn()
missing = conn.execute(
    "SELECT player, rank FROM pick_factors "
    "WHERE bet_date=? AND rank IS NOT NULL AND best_odds IS NULL "
    "ORDER BY rank",
    (target_date,)
).fetchall()
conn.close()

if missing:
    print(f"\n  ⚠  {len(missing)} pick(s) have NO odds — not found on any book:")
    for player, rank in missing:
        print(f"     #{rank}  {player}")
    print("\n  You can supply odds manually:")
    print(f"  sqlite3 data/bets.db \"UPDATE pick_factors SET best_odds='+350' WHERE bet_date='{target_date}' AND player='Player Name';\"")

# ── 3. Merge odds into player_signals for HTML rendering ──────────────────────

# Build a name→odds lookup from the comparisons
odds_lookup = {}
for c in comparisons:
    odds_lookup[c["player"]] = {
        "best_odds":  c.get("best_odds"),
        "pinnacle_odds": c.get("pinnacle"),
        "best_book":  c.get("best_book"),
        "ev_10":      c.get("ev_10"),
        "kelly_size": c.get("kelly_size"),
        "value_edge": c.get("value_edge"),
    }

# Load today's cached context
ctx_path = Path(f"debug_context_{target_date}.json")
if not ctx_path.exists():
    print(f"\n  No cached context found for {target_date} — cannot re-render HTML.")
    print("  (context is saved when daily_picks.py runs)")
    sys.exit(0)

with open(ctx_path) as f:
    ctx = json.load(f)

homer = Homer.__new__(Homer)
homer._context = ctx
player_signals = ctx.get("player_signals", {})

# Inject odds into player_signals
from difflib import SequenceMatcher
injected = 0
for odds_name, odds_data in odds_lookup.items():
    matched = odds_name if odds_name in player_signals else None
    if not matched:
        best_r, best_n = 0.0, None
        for pname in player_signals:
            r = SequenceMatcher(None, odds_name.lower(), pname.lower()).ratio()
            if r > best_r:
                best_r, best_n = r, pname
        if best_r >= 0.82:
            matched = best_n
    if matched:
        player_signals[matched].update(odds_data)
        injected += 1

print(f"  Injected odds into {injected} player signal(s) for HTML rendering.")

all_ranked = homer._rank_picks_python(player_signals, top_n=20)

# ── 4. Rebuild HTML ────────────────────────────────────────────────────────────

import sqlite3 as sq, json as js, datetime as dt

_wp = Path("ml_weights.json")
_auc, _ml_influence = 0.0, 0.0
if _wp.exists():
    with open(_wp) as wf:
        wj = js.load(wf)
    _auc = wj.get("cv_auc_mean", 0.0)
    _ml_influence = min(0.7, max(0.0, (_auc - 0.5) * 2.5))

_model_yesterday_pnl, _model_cumulative_pnl = None, None
try:
    _pnl_js      = js.loads(model_pnl_report())
    _pnl_summary = _pnl_js.get("model_pnl_summary", {})
    _pnl_daily   = _pnl_js.get("daily", [])
    if _pnl_summary.get("days_tracked", 0) > 0:
        _cum_str = _pnl_summary.get("cumulative_pnl", "$0.00")
        _model_cumulative_pnl = float(_cum_str.replace("$", "").replace("+", ""))
    if _pnl_daily:
        _day_str = _pnl_daily[-1].get("day_pnl", "$0.00")
        _model_yesterday_pnl = float(_day_str.replace("$", "").replace("+", ""))
except Exception:
    pass

timestamp = dt.datetime.now().strftime("%Y-%m-%d %I:%M %p")
html = generate_picks_html(
    all_ranked,
    today=timestamp,
    auc=_auc,
    ml_influence=_ml_influence,
    model_yesterday_pnl=_model_yesterday_pnl,
    model_cumulative_pnl=_model_cumulative_pnl,
)

Path(f"picks/picks_{target_date}.html").write_text(html, encoding="utf-8")
Path("docs/index.html").write_text(html, encoding="utf-8")
print(f"\n  HTML updated with odds on cards.")

# ── 5. Push to GitHub ─────────────────────────────────────────────────────────

import subprocess
result = subprocess.run(
    ["git", "add", "docs/index.html", f"picks/picks_{target_date}.html"],
    capture_output=True, text=True
)
result2 = subprocess.run(
    ["git", "commit", "-m", f"Cache odds + refresh site — {target_date}"],
    capture_output=True, text=True
)
result3 = subprocess.run(["git", "push"], capture_output=True, text=True)

if result3.returncode == 0:
    print("  Site pushed to GitHub Pages.")
else:
    print(f"  Push failed: {result3.stderr.strip()}")

print("\n" + "=" * 60)
print(f"  Done. Odds cached for {target_date}.")
print(f"  Tonight, record_results.py will use these to calculate P&L.")
print("=" * 60)

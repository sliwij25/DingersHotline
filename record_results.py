"""
record_results.py
Run this after games finish (typically 11pm ET) to record today's bet outcomes.

Usage:
  python record_results.py              # record results for today
  python record_results.py 2026-04-14   # record results for a specific date
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "api", ".env"))

from agents.bet_tracker import get_pending_bets, record_result, factor_performance_report, backfill_pick_odds, model_pnl_report
from agents.base import get_db_conn

# ── Determine date ─────────────────────────────────────────────────────────────

if len(sys.argv) > 1:
    target_date = sys.argv[1]
else:
    target_date = date.today().isoformat()

print("=" * 60)
print(f"  RECORD RESULTS — {target_date}")
print("=" * 60)

# ── Backfill today's pick odds (odds guaranteed live by game time) ─────────────

try:
    from agents.predictor import fetch_odds_comparison
    raw_odds = fetch_odds_comparison()
    odds_data = json.loads(raw_odds)
    comparisons = odds_data.get("comparisons", []) if odds_data.get("status") == "success" else []
    if comparisons:
        n_updated = backfill_pick_odds(target_date, comparisons)
        print(f"  [Odds] Backfilled odds for {n_updated} pick(s) in pick_factors")
    else:
        print("  [Odds] No odds data available — model P&L will be incomplete for today")
except Exception as e:
    print(f"  [Odds] Could not backfill odds: {e}")

# ── Fetch pending bets ─────────────────────────────────────────────────────────

raw = get_pending_bets(bet_date=target_date)
try:
    data = json.loads(raw)
    pending = data.get("bets", [])
except Exception:
    pending = []

if not pending:
    print(f"\n  No pending bets found for {target_date}.")
    print("  Either all bets are already recorded, or none were logged that day.")
    sys.exit(0)

print(f"\n  {len(pending)} pending bet(s) for {target_date}:\n")
for b in pending:
    print(f"    {b['player']:<26} {b['odds']:<8}  potential: ${b['to_win']:.2f}")

# ── Interactive result entry ───────────────────────────────────────────────────

print()
results_recorded = []

for b in pending:
    player   = b["player"]
    odds_str = b["odds"]
    payout   = float(b.get("to_win") or 0)

    while True:
        try:
            raw_input = input(f"  {player} ({odds_str})  — w(in) / l(oss) / s(kip): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Interrupted — saving progress.")
            break

        if raw_input in ("w", "win"):
            record_result(target_date, player, "win", payout=payout)
            print(f"    ✓ WIN  +${payout - 10:.2f} profit")
            results_recorded.append(("win", player, payout))
            break
        elif raw_input in ("l", "loss"):
            record_result(target_date, player, "loss")
            print(f"    ✗ LOSS  -$10.00")
            results_recorded.append(("loss", player, 0))
            break
        elif raw_input in ("s", "skip", ""):
            print(f"    — skipped")
            break
        else:
            print("    Enter w, l, or s")

# ── Summary ────────────────────────────────────────────────────────────────────

if results_recorded:
    wins   = [r for r in results_recorded if r[0] == "win"]
    losses = [r for r in results_recorded if r[0] == "loss"]
    profit = sum(r[2] - 10 for r in wins) - (len(losses) * 10)

    print("\n" + "=" * 60)
    print(f"  SESSION RESULTS — {target_date}")
    print("=" * 60)
    print(f"  {len(wins)}W / {len(losses)}L  |  Net: ${profit:+.2f}")
    for r in results_recorded:
        if r[0] == "win":
            print(f"  ✓ {r[1]}  +${r[2]-10:.2f}")
        else:
            print(f"  ✗ {r[1]}  -$10.00")

# ── Post-mortem: compare today's results to model signals ─────────────────────

print("\n" + "=" * 60)
print("  MODEL POST-MORTEM")
print("=" * 60)

conn = get_db_conn()
try:
    rows = conn.execute("""
        SELECT
            s.player, s.result, s.odds,
            pf.confidence, pf.ev_10, pf.value_edge, pf.platoon,
            pf.barrel_rate, pf.hard_hit_pct, pf.pitcher_hr_per_9,
            pf.h2h_hr, pf.recent_form_14d, pf.algo_version
        FROM singles s
        LEFT JOIN pick_factors pf
          ON pf.bet_date = s.bet_date
         AND (s.player LIKE '%' || pf.player || '%'
              OR pf.player LIKE '%' || s.player || '%')
        WHERE s.bet_date = ? AND s.result IS NOT NULL
        ORDER BY s.result DESC, s.player
    """, (target_date,)).fetchall()
finally:
    conn.close()

if rows:
    for row in rows:
        (player, result, odds, conf, ev, ve, platoon,
         barrel, hh, p_hr9, h2h_hr, form, algo) = row

        icon   = "✓" if result == "win" else "✗"
        label  = "WIN" if result == "win" else "LOSS"
        conf_s = f"[{conf}]" if conf else "[?]"

        print(f"\n  {icon} {player}  {label}  {odds or ''}  {conf_s}")

        signals = []
        if ev   is not None: signals.append(f"EV ${ev:+.2f}")
        if ve   is not None and ve >= 3: signals.append(f"VALUE +{ve:.1f}pp")
        if platoon == "PLATOON+": signals.append("PLATOON+")
        if barrel is not None:    signals.append(f"barrel {barrel:.1f}%")
        if hh    is not None:     signals.append(f"hh {hh:.1f}%")
        if p_hr9 is not None:     signals.append(f"pitcher L3 {p_hr9:.1f}HR/9")
        if h2h_hr is not None and h2h_hr >= 1: signals.append(f"h2h {h2h_hr}HR")
        if form  is not None and form >= 1:     signals.append(f"{form}HR last 14d")

        if signals:
            print(f"     Signals fired: {' | '.join(signals)}")
        elif algo:
            print(f"     (no pick_factors snapshot — bet not in model's top 8)")
        else:
            print(f"     (no signal data)")
else:
    print(f"\n  No settled bets with results for {target_date}.")

# ── Overall signal performance (if enough history) ────────────────────────────

conn2 = get_db_conn()
try:
    total_settled = conn2.execute(
        "SELECT COUNT(*) FROM singles WHERE result IS NOT NULL"
    ).fetchone()[0]
finally:
    conn2.close()

if total_settled >= 10:
    print("\n" + "=" * 60)
    print("  SIGNAL ACCURACY (all-time)")
    print("=" * 60)
    try:
        report = json.loads(factor_performance_report())
        overall = report.get("overall_win_pct", "?")
        total   = report.get("total_tracked", 0)
        print(f"  Overall: {overall} win rate across {total} tracked picks\n")

        breakdown = report.get("signal_breakdown", {})
        # Show only sections with >= 3 bets, sorted by win rate descending
        rows_out = []
        for key, sec in breakdown.items():
            if isinstance(sec, dict) and sec.get("bets", 0) >= 3:
                pct = float(sec["win_pct"].replace("%", ""))
                rows_out.append((pct, sec["label"], sec["bets"], sec["wins"], sec["win_pct"]))
        rows_out.sort(reverse=True)

        for pct, label, bets, wins, win_pct in rows_out:
            bar = "█" * int(pct / 5)
            print(f"  {label:<40} {win_pct:>6}  ({wins}/{bets})  {bar}")
    except Exception as e:
        print(f"  Could not generate signal report: {e}")
else:
    remaining = 10 - total_settled
    print(f"\n  Signal accuracy report unlocks after {remaining} more settled bet(s).")

# ── Fictitious model P&L (all top-20 picks, $10 each) ─────────────────────────

try:
    pnl_data = json.loads(model_pnl_report())
    summary = pnl_data.get("model_pnl_summary", {})
    if summary and summary.get("days_tracked", 0) > 0:
        print("\n" + "=" * 60)
        print("  MODEL P&L  (fictitious — $10 on every top-20 pick)")
        print("=" * 60)
        print(f"  Days tracked:   {summary['days_tracked']}")
        print(f"  Total picks:    {summary['total_picks_with_odds']}  ({summary['win_pct']} hit rate)")
        print(f"  Total wagered:  {summary['total_wagered']}")
        print(f"  Cumulative P&L: {summary['cumulative_pnl']}")
        print(f"  ROI:            {summary['roi']}")
        daily = pnl_data.get("daily", [])
        if daily:
            print(f"\n  {'Date':<12} {'Picks':>6} {'Wins':>5} {'Day P&L':>10} {'Cumulative':>12}")
            print("  " + "-" * 48)
            for d in daily[-10:]:
                print(f"  {d['date']:<12} {d['picks_with_odds']:>6} {d['wins']:>5} "
                      f"{d['day_pnl']:>10} {d['cumulative_pnl']:>12}")
except Exception as e:
    print(f"\n  [Model P&L unavailable: {e}]")

print("\n" + "=" * 60)

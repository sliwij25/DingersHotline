"""
bets.py — lightweight bet management CLI. No Homer, no API calls, just the DB.

Usage:
    python bets.py                          # pending bets + P&L summary
    python bets.py log                      # interactively log new bets
    python bets.py results                  # record today's results (alias for record_results.py)
    python bets.py history                  # full bet history
    python bets.py history --player Judge   # filter by player
    python bets.py stats --player Judge     # win rate / ROI for one player
"""

import json
import sys
import os
import argparse
from datetime import date

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "api", ".env"))

from agents.bet_tracker import (
    get_pending_bets, get_pnl_summary, get_bet_history,
    get_player_stats, log_singles, record_result,
)

TODAY = date.today().isoformat()


def cmd_summary():
    """Pending bets + overall P&L."""
    # Pending
    raw = get_pending_bets()
    try:
        pending = json.loads(raw).get("bets", [])
    except Exception:
        pending = []

    if pending:
        print(f"\nPENDING BETS ({len(pending)})\n")
        for b in pending:
            print(f"  {b['bet_date']}  {b['player']:<26} {b['odds']:<8}  ${b['to_win']:.2f} to win")
    else:
        print("\nNo pending bets.")

    # P&L
    raw = get_pnl_summary()
    try:
        pnl = json.loads(raw)
        print(f"\nP&L SUMMARY\n")
        print(f"  Total bets:    {pnl.get('total_bets', 0)}")
        print(f"  Wins / Losses: {pnl.get('wins', 0)} / {pnl.get('losses', 0)}")
        print(f"  Net P&L:       {pnl.get('net_pnl', '$0.00')}")
        print(f"  ROI:           {pnl.get('roi', 'N/A')}")
    except Exception:
        print(raw)


def cmd_log():
    """Interactively log one or more bets."""
    print(f"\nLOG BETS — {TODAY}")
    print("Enter bets one at a time. Leave player blank to finish.\n")

    bets = []
    while True:
        player = input("  Player name (or Enter to finish): ").strip()
        if not player:
            break
        game    = input(f"  Game (e.g. LAA @ NYY): ").strip()
        odds    = input(f"  Odds (e.g. +220): ").strip()
        raw_pay = input(f"  Potential payout ($): ").strip()
        try:
            payout = float(raw_pay)
        except ValueError:
            payout = 0.0
        bets.append({"player": player, "game": game, "odds": odds, "potential_payout": payout})
        print(f"  Added: {player}\n")

    if not bets:
        print("No bets entered.")
        return

    platform_raw = input("Platform (prophetx/novig) [prophetx]: ").strip().lower()
    platform = platform_raw if platform_raw in ("prophetx", "novig") else "prophetx"

    result = log_singles(TODAY, platform, bets, wager=10.0)
    print(f"\n✓ {result}")


def cmd_results(target_date: str):
    """Record results for a given date (delegates to record_results.py logic inline)."""
    raw = get_pending_bets(bet_date=target_date)
    try:
        pending = json.loads(raw).get("bets", [])
    except Exception:
        pending = []

    if not pending:
        print(f"\nNo pending bets for {target_date}.")
        return

    print(f"\nRECORD RESULTS — {target_date}\n")
    for b in pending:
        print(f"  {b['player']:<26} {b['odds']}")

    print()
    for b in pending:
        player = b["player"]
        payout = float(b.get("to_win") or 0)
        while True:
            try:
                r = input(f"  {player} — w(in) / l(oss) / s(kip): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nStopped.")
                return
            if r in ("w", "win"):
                record_result(target_date, player, "win", payout=payout)
                print(f"    ✓ WIN  +${payout-10:.2f}")
                break
            elif r in ("l", "loss"):
                record_result(target_date, player, "loss")
                print(f"    ✗ LOSS  -$10.00")
                break
            elif r in ("s", "skip", ""):
                print("    — skipped")
                break


def cmd_history(player_filter: str | None):
    raw = get_bet_history(player=player_filter)
    try:
        data = json.loads(raw)
        bets = data.get("bets", [])
    except Exception:
        print(raw)
        return

    if not bets:
        print("No bet history found.")
        return

    print(f"\nBET HISTORY ({len(bets)} bets)\n")
    print(f"  {'Date':<12} {'Player':<26} {'Odds':<8} {'Result':<8} {'P&L'}")
    print("  " + "-" * 70)
    for b in bets:
        result = b.get("result") or "pending"
        if result == "win":
            pnl = f"+${float(b.get('to_win',0)) - 10:.2f}"
        elif result == "loss":
            pnl = "-$10.00"
        else:
            pnl = "—"
        print(f"  {b['bet_date']:<12} {b['player']:<26} {b['odds']:<8} {result:<8} {pnl}")


def cmd_stats(player: str):
    raw = get_player_stats(player)
    try:
        data = json.loads(raw)
    except Exception:
        print(raw)
        return

    if data.get("status") == "not_found":
        print(f"No bets found for '{player}'.")
        return

    print(f"\nSTATS — {data.get('player', player)}\n")
    print(f"  Bets:        {data.get('total_bets', 0)}")
    print(f"  Wins:        {data.get('wins', 0)}")
    print(f"  Win rate:    {data.get('win_rate', 'N/A')}")
    print(f"  Total wagered: ${data.get('total_wagered', 0):.2f}")
    print(f"  Net P&L:     {data.get('net_pnl', '$0.00')}")
    print(f"  ROI:         {data.get('roi', 'N/A')}")


def main():
    parser = argparse.ArgumentParser(description="Bet management CLI")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("log",     help="Log new bets interactively")
    sub.add_parser("results", help="Record today's results").add_argument(
        "--date", default=TODAY, help="Date to record (YYYY-MM-DD)")

    hist = sub.add_parser("history", help="Show bet history")
    hist.add_argument("--player", default=None, help="Filter by player name")

    stats = sub.add_parser("stats", help="Player win rate / ROI")
    stats.add_argument("--player", required=True)

    args = parser.parse_args()

    if args.cmd == "log":
        cmd_log()
    elif args.cmd == "results":
        cmd_results(args.date)
    elif args.cmd == "history":
        cmd_history(args.player)
    elif args.cmd == "stats":
        cmd_stats(args.player)
    else:
        cmd_summary()


if __name__ == "__main__":
    main()

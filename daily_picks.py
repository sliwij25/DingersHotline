"""
daily_picks.py
Run this every morning in Spyder to get today's HR picks and bet slips.

COST OPTIMIZATION:
  For testing/development, use --use-cache flag to skip data fetching:
    python daily_picks.py --use-cache
  
  This loads cached context from the latest debug_context_YYYY-MM-DD.json,
  avoiding ~100 API calls per run (Odds API, MLB API, Statcast, etc.).

Usage:
  python daily_picks.py              # fetch all data fresh
  python daily_picks.py --use-cache  # reuse cached data from today
"""

import json
import os
import sys
import argparse
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

# ── Setup ──────────────────────────────────────────────────────────────────────

# Make sure we're in the right directory so agent imports work
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load API keys from api/.env
load_dotenv(os.path.join(os.path.dirname(__file__), "api", ".env"))

TODAY = date.today().isoformat()

# Parse command-line args
parser = argparse.ArgumentParser()
parser.add_argument("--use-cache", action="store_true",
                    help="Load cached context instead of fetching fresh data")
args = parser.parse_args()

print("=" * 60)
print(f"  HOME RUN PICKS — {TODAY}")
if args.use_cache:
    print("  (using cached data — development mode)")
print("=" * 60)

# ── Import Homer ───────────────────────────────────────────────────────────────

from agents import Homer
from agents.predictor import fetch_odds_comparison
from agents.bet_tracker import save_pick_factors, model_performance_report

# ── Auto-maintenance (runs every morning before picks) ─────────────────────────
# Labels yesterday's pick_factors with actual HR results, refreshes 2026 training
# data, and retrains ML weights when due. Zero manual steps required.

def _auto_maintain():
    import sqlite3 as _sqlite3
    from datetime import date as _date, timedelta

    yesterday = (_date.today() - timedelta(days=1)).isoformat()

    # 1. Label yesterday's MLB results ─────────────────────────────────────────
    print("  [Auto] Labeling yesterday's HR results...", end=" ", flush=True)
    try:
        from fetch_actual_results import fetch_homers_for_date, update_pick_factors
        import io as _io, sys as _sys
        _old, _sys.stdout = _sys.stdout, _io.StringIO()
        try:
            homers = fetch_homers_for_date(yesterday)
            # homers=None → off day / all games pending (skip labeling)
            # homers={} → games completed, nobody homered (still label everyone as 0)
            if homers is not None:
                update_pick_factors(yesterday, homers, dry_run=False)
        finally:
            _sys.stdout = _old
        if homers is None:
            print("no completed games")
        else:
            print(f"{len(homers)} players homered")
    except Exception as e:
        print(f"skipped ({e})")

    # 2. Refresh 2026 training data ────────────────────────────────────────────
    print("  [Auto] Refreshing 2026 Statcast + HR data...", end=" ", flush=True)
    try:
        from build_historical_dataset import (
            fetch_statcast_season, fetch_hr_events_season,
            write_season_to_db, CURRENT_YEAR
        )
        import io as _io, sys as _sys
        _old, _sys.stdout = _sys.stdout, _io.StringIO()
        try:
            bs   = fetch_statcast_season(CURRENT_YEAR)
            hrev = fetch_hr_events_season(CURRENT_YEAR)
            n, _ = write_season_to_db(CURRENT_YEAR, bs, hrev)
        finally:
            _sys.stdout = _old
        print(f"{n:,} rows in DB" if bs else "no data yet (early season?)")
    except Exception as e:
        print(f"skipped ({e})")

    # 3. Retrain ML weights if due ─────────────────────────────────────────────
    weights_path = Path(__file__).parent / "ml_weights.json"
    retrain, retrain_reason = False, ""

    try:
        conn = _sqlite3.connect(Path(__file__).parent / "data" / "bets.db")
        labeled_n = conn.execute(
            "SELECT COUNT(*) FROM pick_factors WHERE homered IS NOT NULL"
        ).fetchone()[0]
        conn.close()
    except Exception:
        labeled_n = 0

    if not weights_path.exists() and labeled_n >= 100:
        retrain, retrain_reason = True, "first-time training"
    elif weights_path.exists():
        try:
            with open(weights_path) as f:
                w = json.load(f)
            days_since = (_date.today() - _date.fromisoformat(w.get("trained_on", "2000-01-01"))).days
            new_rows   = labeled_n - w.get("n_samples", 0)
            if days_since >= 7 and new_rows >= 200:
                retrain, retrain_reason = True, f"{days_since}d old, {new_rows:,} new rows"
            elif new_rows >= 2000:
                retrain, retrain_reason = True, f"{new_rows:,} new labeled rows"
        except Exception:
            pass

    if retrain:
        print(f"  [Auto] Retraining ML weights ({retrain_reason})...", end=" ", flush=True)
        try:
            from optimize_weights import load_training_data, train_and_save
            import io as _io, sys as _sys
            _old, _sys.stdout = _sys.stdout, _io.StringIO()
            try:
                X, y, _ = load_training_data()
                weights  = train_and_save(X, y, save=True)
            finally:
                _sys.stdout = _old
            auc = weights.get("cv_auc_mean", 0) if weights else 0
            print(f"done  AUC={auc:.3f}")
            # Invalidate Homer's cached weights so new model loads immediately
            Homer._ml_weights_loaded = False
            Homer._ml_weights        = None
        except ImportError:
            print("skipped — run: pip install scikit-learn scipy")
        except Exception as e:
            print(f"skipped ({e})")
    elif weights_path.exists():
        try:
            with open(weights_path) as f:
                w = json.load(f)
            print(f"  [Auto] ML weights up to date  "
                  f"(trained {w.get('trained_on','?')}, AUC={w.get('cv_auc_mean',0):.3f})")
        except Exception:
            pass

    print()

if not args.use_cache:
    _auto_maintain()

# ── Get picks (narrative) ──────────────────────────────────────────────────────

if args.use_cache:
    # Load cached context
    cache_file = sorted(Path(__file__).parent.glob(f"debug_context_{TODAY}.json"), reverse=True)
    if not cache_file:
        print("ERROR: No cache file found for today.")
        print(f"Run without --use-cache first, or run cache_data.py manually.")
        sys.exit(1)
    
    print(f"Loading cached context from {cache_file[0].name}...\n")
    homer = Homer()
    with open(cache_file[0]) as f:
        homer._context = json.load(f)
else:
    print("Fetching picks — this takes about 30–60 seconds...\n")
    homer = Homer()

narrative = homer.run(
    f"Today is {TODAY}. Give me the top 20 HR picks for today with confidence tiers. "
    "Evaluate ALL batters in the confirmed lineups using BallparkPal matchup grades, "
    "park factors, Statcast barrel rate, hard hit %, recent HR form, and our historical record. "
    "For each pick include: player, matchup, batting position, key stats, and reasoning."
)

# Auto-save cache on fresh run (not needed when using --use-cache)
if not args.use_cache:
    cache_file = Path(__file__).parent / f"debug_context_{TODAY}.json"
    try:
        with open(cache_file, "w") as f:
            json.dump(homer._context, f)
        print(f"\n  [Cached context to {cache_file.name} for testing]")
    except Exception as e:
        pass  # silent fail, not critical


print("\n" + "=" * 60)
print("  TODAY'S PICKS")
print("=" * 60)
print(narrative)

# ── Export clean .txt file (shareable picks list) ──────────────────────────────
if not args.use_cache:
    try:
        txt_path = Path(__file__).parent / "picks" / f"picks_{TODAY}.txt"
        with open(txt_path, "w", encoding="utf-8") as _f:
            _f.write(f"HomeRunBets — {TODAY}\n")
            _f.write("=" * 62 + "\n\n")
            _f.write(narrative)
            _f.write("\n")
        print(f"\n  [Export] Picks saved to {txt_path.name}")
    except Exception as e:
        print(f"  [Export] Could not save .txt: {e}")

# ── Generate bet slips ─────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("  BET SLIPS — fill in odds + potential_payout from your platform")
print("=" * 60)

picks = homer.get_picks_json(top_n=20)

if not picks:
    print("\nCould not generate structured bet slip.")
    print("Use the picks above to manually fill in log_singles().\n")
else:
    # Save ALL ranked players (not just top 8) for unbiased ML training data.
    # The model needs to see who didn't homer just as much as who did.
    player_signals = homer._context.get("player_signals", {})
    all_ranked = homer._rank_picks_python(player_signals, top_n=20, verbose=True)
    saved = 0
    for rank_i, p in enumerate(all_ranked, 1):
        if p.get("signals"):
            try:
                save_pick_factors(TODAY, p["player"], p["signals"],
                                  confidence=p.get("confidence"),
                                  algo_version="3.0",
                                  score=p.get("score"),
                                  rank=rank_i)
                saved += 1
            except Exception:
                pass
    print(f"\n  [ML Training] Saved signal snapshots for {saved} players (top 20 ranked)")

    for platform in ["prophetx", "novig"]:
        print(f"\n# ── {platform.upper()} ──────────────────────────────────────")
        print(f"log_singles('{TODAY}', '{platform}', [")
        for p in picks:
            print(f"    # {p.get('stars','')} {p.get('reasoning','')}")
            print(f"    {{'player': '{p.get('player','')}', "
                  f"'game': '{p.get('matchup','')}', "
                  f"'odds': '___', 'potential_payout': 0.00}},")
        print("], wager=10.0)")

# ── Odds comparison / value finder ────────────────────────────────────────────

print("\n" + "=" * 60)
print("  ODDS COMPARISON — sharp lines + value finder")
print("=" * 60)
print("  Pinnacle = sharpest benchmark (no US retail markup).")
print("  Compare your Novig / ProphetX odds to Pinnacle and Best Odds.")
print("  If your platform beats Best Odds -> you have extra edge.\n")

try:
    raw_cmp = fetch_odds_comparison()
    cmp_data = json.loads(raw_cmp)

    if cmp_data.get("status") == "success":
        comparisons = cmp_data.get("comparisons", [])
        if comparisons:
            # Main comparison table
            print(f"  {'Player':<26} {'Pinnacle':<11} {'Best Odds':<11} "
                  f"{'Best Book':<18} {'Consensus%':<12} {'Edge':<8} {'Flag'}")
            print("  " + "-" * 96)
            for c in comparisons[:25]:
                flag     = "VALUE" if c.get("value_flag") == "VALUE" else ""
                edge     = c.get("value_edge", 0)
                edge_str = f"+{edge:.1f}pp" if edge >= 0 else f"{edge:.1f}pp"
                print(f"  {c['player']:<26} {c['pinnacle']:<11} {c['best_odds']:<11} "
                      f"{c['best_book']:<18} {c['consensus_prob']:<12} "
                      f"{edge_str:<8} {flag}")
            print()

            # Detailed breakdown for VALUE picks
            value_picks = [c for c in comparisons if c.get("value_flag") == "VALUE"]
            if value_picks:
                print("  ── VALUE picks — full book breakdown ──────────────────")
                for vp in value_picks[:8]:
                    print(f"\n  {vp['player']}  ({vp['matchup']})")
                    for book, odds in vp["all_books"].items():
                        marker    = " <- BEST"       if book == vp["best_book"] else ""
                        pin_mark  = " <- SHARP LINE" if "Pinnacle" in book      else ""
                        print(f"    {book:<22} {odds}{marker}{pin_mark}")
                    print(f"  >> Novig / ProphetX: check app — beat Pinnacle {vp['pinnacle']} = value")
            else:
                print("  No VALUE flags today — lines are tight across books.")
                print("  Compare your Novig/ProphetX to the Pinnacle column above.")
        else:
            print("  No prop odds data yet — books post HR props ~2-4h before first pitch.")
            print("  Re-run after 11am for full odds comparison.")
    else:
        print(f"  {cmp_data.get('message', 'Could not fetch odds comparison.')}")
except Exception as e:
    print(f"  Odds comparison unavailable: {e}")

print("\n" + "=" * 60)
print("  To log bets: python bets.py log")
print("  To record results tonight: python record_results.py")
print("=" * 60)

# ── Model performance dashboard ────────────────────────────────────────────────

print()
try:
    print(model_performance_report())
except Exception as e:
    print(f"  [Model dashboard unavailable: {e}]")

# ── Auto-commit + push to GitHub ───────────────────────────────────────────────

if not args.use_cache:
    try:
        import subprocess as _sp
        _repo = os.path.dirname(os.path.abspath(__file__))
        _sp.run(["/usr/bin/git", "-C", _repo, "add",
                 "ml_weights.json", "agents/predictor.py",
                 "agents/bet_tracker.py", "daily_picks.py",
                 "optimize_weights.py", "fetch_actual_results.py",
                 "build_historical_dataset.py", "README.md", "requirements.txt"],
                capture_output=True)
        _result = _sp.run(
            ["/usr/bin/git", "-C", _repo, "commit", "-m",
             f"Auto-update {TODAY} — picks run, ML weights refreshed"],
            capture_output=True, text=True
        )
        if "nothing to commit" in _result.stdout:
            print("  [GitHub] No changes to commit.")
        else:
            _sp.run(["/usr/bin/git", "-C", _repo, "push"], capture_output=True)
            print("  [GitHub] Changes pushed to github.com/sliwij25/HomeRunBets")
    except Exception as e:
        print(f"  [GitHub] Push skipped: {e}")

# ── Notifications (Telegram primary, iMessage fallback) ────────────────────────

if not args.use_cache:
    import subprocess as _nsp, requests as _req
    _top = picks[:3] if picks else []
    _top3_lines = "\n".join(
        f"  #{i+1} {p.get('stars','')} {p.get('player','?')}  — {p.get('reasoning','')}"
        for i, p in enumerate(_top)
    ) if _top else "  no picks yet"
    _caption = f"HomeRunBets {TODAY}\n\nTop 3:\n{_top3_lines}\n\nFull 20 picks in the file."

    # 1. Telegram (primary) — send .txt file with top-3 caption
    _tg_sent = False
    try:
        _tg_token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
        if not _tg_token:
            _env_path = os.path.join(os.path.expanduser("~"), ".claude", "channels", "telegram", ".env")
            if os.path.exists(_env_path):
                with open(_env_path) as _f:
                    for _line in _f:
                        if _line.startswith("TELEGRAM_BOT_TOKEN="):
                            _tg_token = _line.strip().split("=", 1)[1]
        if _tg_token:
            _tg_chat = "-1003940624182"  # Dingers Hotline group
            _txt_path = Path(__file__).parent / "picks" / f"picks_{TODAY}.txt"
            if _txt_path.exists():
                # Send as document so recipient can tap to open full list
                with open(_txt_path, "rb") as _tf:
                    _resp = _req.post(
                        f"https://api.telegram.org/bot{_tg_token}/sendDocument",
                        data={"chat_id": _tg_chat, "caption": _caption},
                        files={"document": (_txt_path.name, _tf, "text/plain")},
                        timeout=20,
                    )
                if _resp.status_code == 200:
                    _tg_sent = True
                    print("  [Telegram] Picks file sent.")
                else:
                    raise RuntimeError(_resp.text[:200])
            else:
                # No .txt yet — fall back to plain text message
                _resp = _req.post(
                    f"https://api.telegram.org/bot{_tg_token}/sendMessage",
                    data={"chat_id": _tg_chat, "text": _caption},
                    timeout=10,
                )
                if _resp.status_code == 200:
                    _tg_sent = True
                    print("  [Telegram] Notification sent (no file).")
    except Exception as _e:
        print(f"  [Telegram] Skipped: {_e}")

    # 2. iMessage (fallback — only if Telegram failed)
    if not _tg_sent:
        try:
            _imsg = _caption.replace("\n", " ")
            _script = (
                f'tell application "Messages"\n'
                f'  set s to 1st service whose service type is iMessage\n'
                f'  send "{_imsg}" to buddy "+14148811460" of s\n'
                f'end tell'
            )
            _nsp.run(["osascript", "-e", _script], capture_output=True, timeout=30)
            print("  [iMessage] Notification sent (Telegram fallback).")
        except Exception as _e:
            print(f"  [iMessage] Skipped: {_e}")

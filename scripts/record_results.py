"""
record_results.py
Run nightly at 2am ET (after west coast games finish) to label HR results and retrain ML weights.
Scheduled via launchd (com.homerunbets.nightly). Retrain runs every Monday to align with new series.

Usage:
    python scripts/record_results.py
    python scripts/record_results.py --date 2026-04-21   # label a specific past date
    python scripts/record_results.py --dry-run           # preview labels without saving
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.chdir(str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "ml"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "api", ".env"))

parser = argparse.ArgumentParser()
parser.add_argument("--date", default=(date.today() - timedelta(days=1)).isoformat(),
                    help="Date to label results for (YYYY-MM-DD, default: yesterday)")
parser.add_argument("--dry-run", action="store_true",
                    help="Preview labels without writing to DB or retraining")
args = parser.parse_args()

TARGET_DATE = args.date

print("=" * 60)
print(f"  RECORD RESULTS — {TARGET_DATE}")
if args.dry_run:
    print("  (dry run — no changes will be saved)")
print("=" * 60)

# ── 1. Label today's HR results ────────────────────────────────────────────────

print(f"\n  [Step 1] Labeling HR results for {TARGET_DATE}...", end=" ", flush=True)
homers = None
try:
    from fetch_actual_results import fetch_homers_for_date, update_pick_factors
    homers, homer_teams, active_players = fetch_homers_for_date(TARGET_DATE)
    if homers is None:
        print("no completed games yet — try again after games finish")
    else:
        if not args.dry_run:
            update_pick_factors(TARGET_DATE, homers, homer_teams, active_players, dry_run=False)
        print(f"{len(homers)} players homered")
        if homers:
            for name, count in sorted(homers.items()):
                print(f"    {name}: {count} HR")
except Exception as e:
    print(f"failed ({e})")
    sys.exit(1)

if homers is None:
    print("\n  Games not complete — rerun after final outs.")
    sys.exit(0)

# ── 2. Backfill odds (best available book + manual override) ──────────────────

print(f"\n  [Step 2] Backfilling odds for {TARGET_DATE}...")
if not args.dry_run:
    try:
        from agents.predictor import fetch_odds_comparison
        from agents.bet_tracker import backfill_pick_odds
        import json as _json
        raw_cmp = fetch_odds_comparison()
        cmp_data = _json.loads(raw_cmp)
        if cmp_data.get("status") == "success":
            comparisons = cmp_data.get("comparisons", [])
            if comparisons:
                saved_odds = backfill_pick_odds(TARGET_DATE, comparisons)
                print(f"  [Odds] Saved best_odds for {saved_odds} picks from Odds API")
            else:
                print("  [Odds] No props data returned from Odds API")
        else:
            print(f"  [Odds] {cmp_data.get('message', 'Odds API unavailable')}")
    except Exception as e:
        print(f"  [Odds] Backfill failed ({e})")

# Manual override prompt for any still-missing odds
if sys.stdin.isatty() and not args.dry_run:
    try:
        import sqlite3 as _sq2
        _db2 = _sq2.connect(str(Path(__file__).parent.parent / "data" / "bets.db"))
        _missing = _db2.execute(
            "SELECT player, rank FROM pick_factors WHERE bet_date=? AND best_odds IS NULL AND rank IS NOT NULL ORDER BY rank",
            (TARGET_DATE,)
        ).fetchall()
        if _missing:
            print(f"\n  {len(_missing)} picks still missing odds — enter manually (or press Enter to skip):")
            for _mp, _mr in _missing:
                _inp = input(f"    #{_mr} {_mp} best odds (e.g. +350): ").strip()
                if _inp:
                    _db2.execute(
                        "UPDATE pick_factors SET best_odds=? WHERE bet_date=? AND player=?",
                        (_inp, TARGET_DATE, _mp)
                    )
            _db2.commit()
        else:
            print("  [Odds] All picks have odds recorded.")
        _db2.close()
    except Exception as e:
        print(f"  [Odds] Manual prompt failed ({e})")

# ── 3. Retrain ML weights if due ───────────────────────────────────────────────

import sqlite3
weights_path = Path(__file__).parent.parent / "ml_weights.json"
retrain, retrain_reason = False, ""

try:
    conn = sqlite3.connect(str(Path(__file__).parent.parent / "data" / "bets.db"))
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
        days_since = (date.today() - date.fromisoformat(w.get("trained_on", "2000-01-01"))).days
        new_rows   = labeled_n - w.get("n_samples", 0)
        is_monday  = date.today().weekday() == 0  # 0 = Monday
        if is_monday and new_rows >= 50:
            retrain, retrain_reason = True, f"Monday retrain ({new_rows:,} new rows since {w.get('trained_on','?')})"
        elif new_rows >= 2000:
            retrain, retrain_reason = True, f"emergency retrain — {new_rows:,} new labeled rows"
        else:
            print(f"\n  [Step 3] ML weights up to date "
                  f"(trained {w.get('trained_on','?')}, AUC={w.get('cv_auc_mean',0):.3f}, "
                  f"v{w.get('algo_version','?')}, {new_rows} new rows since last train)")
    except Exception:
        pass

if retrain:
    print(f"\n  [Step 3] Retraining ML weights ({retrain_reason})...", end=" ", flush=True)
    if args.dry_run:
        print("skipped (dry run)")
    else:
        try:
            from optimize_weights import load_training_data, train_and_save
            import io as _io
            _old, sys.stdout = sys.stdout, _io.StringIO()
            try:
                X, y, _ = load_training_data()
                weights  = train_and_save(X, y, save=True)
            finally:
                sys.stdout = _old

            auc = weights.get("cv_auc_mean", 0) if weights else 0

            # Bump algo_version: read current, increment minor (e.g. "3.1" → "3.2")
            current_ver = weights.get("algo_version", None)
            if current_ver is None:
                # Try reading from the file we just wrote (before we add algo_version)
                try:
                    with open(weights_path) as _f:
                        _existing = json.load(_f)
                    current_ver = _existing.get("algo_version", "3.1")
                except Exception:
                    current_ver = "3.1"
            try:
                major, minor = current_ver.split(".")
                new_ver = f"{major}.{int(minor) + 1}"
            except Exception:
                new_ver = current_ver + ".1"

            # Write algo_version into ml_weights.json
            with open(weights_path) as _f:
                saved_weights = json.load(_f)
            saved_weights["algo_version"] = new_ver
            with open(weights_path, "w") as _f:
                json.dump(saved_weights, _f, indent=2)

            print(f"done  AUC={auc:.3f}  algo_version bumped to {new_ver}")

            # Invalidate Homer's class-level cache so next pick run uses new model
            try:
                from agents.predictor import Homer
                Homer._ml_weights_loaded = False
                Homer._ml_weights        = None
            except Exception:
                pass

        except ImportError:
            print("skipped — run: pip install scikit-learn scipy")
        except Exception as e:
            print(f"failed ({e})")

# ── 3. Commit + push ───────────────────────────────────────────────────────────

if not args.dry_run:
    try:
        from agents.base import git_commit_and_push
        _files = ["ml_weights.json"]
        _msg   = f"results({TARGET_DATE}): labeled HR outcomes" + (" + retrained ML" if retrain else "")
        _status = git_commit_and_push(_files, _msg)
        if _status == "nothing_to_commit":
            print("\n  [GitHub] No changes to commit.")
        elif _status == "pushed":
            print(f"\n  [GitHub] Pushed: {_msg}")
        else:
            print(f"\n  [GitHub] FAILED — {_status}")
    except Exception as e:
        print(f"\n  [GitHub] Push skipped: {e}")

# ── 4. Schedule tomorrow night's wake ─────────────────────────────────────────
# pmset repeat requires sudo; pmset schedule (one-time) does not.
# Re-schedule each night so the nightly job can always wake the Mac.

if not args.dry_run:
    try:
        from datetime import datetime, timezone, timedelta
        from zoneinfo import ZoneInfo
        import subprocess as _sp2
        tomorrow_2am = (datetime.now(ZoneInfo("America/New_York"))
                        .replace(hour=1, minute=55, second=0, microsecond=0)
                        + timedelta(days=1))
        pmset_fmt = tomorrow_2am.strftime("%m/%d/%y %H:%M:%S")
        r = _sp2.run(["pmset", "schedule", "wake", pmset_fmt],
                     capture_output=True, text=True)
        if r.returncode == 0:
            print(f"  [Wake] Scheduled next run: {pmset_fmt} ET")
        else:
            print(f"  [Wake] pmset failed: {r.stderr.strip()}")
    except Exception as e:
        print(f"  [Wake] Schedule skipped ({e})")

print("\n  Done.\n")

"""
optimize_weights.py
Train the HR model on labeled live pick_factors rows → save ml_weights.json.
Homer's _score_player() reads it automatically and blends it with the heuristic.

Model (v5, Sept 2026 off-season rebuild): L2-regularised logistic regression on
median-imputed features + missing-value indicators, trained on LIVE rows only.
Historical backfill rows (algo_version 'hist_*') are excluded: they use season-final
Statcast / pitcher HR/9, i.e. look-ahead leakage, and carry NULLs for 21 of 29
features. Walk-forward testing on the Aug–Sep 2026 full slates showed the old
LightGBM-on-everything recipe ranked worse than the heuristic alone (per-day
AUC 0.589 vs 0.614); this recipe + 50/50 heuristic blend scored 0.623 and lifted
top-20 hit rate from 17.1% to 19.5%. See notes/ALGORITHM.md and tools/model_lab.py.

Run weekly (or after every ~50 new labeled days accumulate).

Usage:
    python optimize_weights.py              # train + save weights
    python optimize_weights.py --report     # report only, don't save weights
    python optimize_weights.py --min 50     # require at least N labeled rows (default 100)

Output:
    ml_weights.json          — coefficients, imputation/scaling constants, blend constants
    (stdout)                 — coefficients, calibration, rank-vs-hit-rate
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np

os.chdir(str(Path(__file__).parent.parent))
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "bets.db")
WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "..", "ml_weights.json")

ALGO_VERSION   = "5.0"   # model generation; record_results.py bumps the minor on each retrain
LOGIT_C        = 0.02    # strong L2 — walk-forward best of {0.005, 0.02, 0.2}
BLEND_WEIGHT   = 0.5     # share of final score from ML (walk-forward: 0.2–0.8 all beat prod; 0.5 best)
WF_TEST_DAYS   = 42      # walk-forward evaluation window (most recent full-slate days)
WF_STEP_DAYS   = 7       # refit cadence inside the walk-forward evaluation

# Model features.
# Each entry: (column_name, transform)
# transform: None = use raw value, "platoon" = PLATOON+→1 / platoon-→-1 / else→0
# Correlated contact-quality features are kept: strong L2 (LOGIT_C) keeps their
# coefficients small and stable instead of sign-flipping.
FEATURES = [
    # Contact quality
    ("barrel_rate",      None),    # r=0.70 predictive for HR%
    ("ev_avg",           None),    # r=0.57 predictive — avg exit velocity
    ("hard_hit_pct",     None),    # r=0.66 descriptive — EV 100+ mph
    ("sweet_spot_pct",   None),    # r=0.42 predictive — 8-32° launch angle%
    ("xiso",             None),    # expected ISO — power composite
    ("xslg",             None),    # expected slugging
    # Batted ball profile
    ("fb_pct",           None),    # fly ball rate — per RotoGrinders: strong HR correlation
    ("launch_angle",     None),    # avg launch angle — r=0.42 predictive
    ("hr_fb_ratio",      None),    # HR/FB — volatile early, meaningful mid-season
    # Bat tracking
    ("blast_rate",       None),    # % of swings qualifying as a Blast — high HR correlation
    # Context
    ("bpp_vs_grade",     None),    # BallparkPal 0-10 matchup grade (bpp_hr_pct is unobtainable, see predictor.py)
    ("park_hr_factor",   None),
    ("ev_10",            None),
    ("value_edge",       None),
    ("recent_form_14d",  None),
    ("pitcher_hr_per_9",   None),
    ("pitcher_hr_vs_hand", None),
    ("pitcher_barrel_pct", None),
    ("is_home",            None),
    ("platoon",          "platoon"),
    ("h2h_hr",           None),
    ("career_park_hr",   None),    # career HR count at today's specific venue
    ("pitcher_career_hr_vs_hand", None),  # career HR/9 vs batter's handedness (explicit ML feature)
    # Pitcher pitch mix
    ("pitcher_fb_pct",       None),
    ("pitcher_breaking_pct", None),
    ("pitcher_offspeed_pct", None),
    # Batter split vs pitcher's dominant pitch type
    ("batter_xslg_vs_fastball",  None),
    ("batter_xslg_vs_breaking",  None),
    ("batter_xslg_vs_offspeed",  None),
]

FEATURE_NAMES = [name for name, _ in FEATURES]


def load_training_data() -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """
    Load LIVE pick_factors rows where homered IS NOT NULL (historical 'hist_*'
    backfill rows are excluded — see module docstring for why).
    Returns (X, y, raw_rows). Missing values stay NaN; train_and_save() median-imputes
    them and adds a missing-indicator column so "value unknown" can carry its own weight.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT *
            FROM pick_factors
            WHERE homered IS NOT NULL
              AND algo_version NOT LIKE 'hist%'
            ORDER BY bet_date
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        return np.array([]), np.array([]), []

    raw_rows = []
    X_raw = []
    y = []

    for row in rows:
        signals  = dict(row)
        homered  = signals.pop("homered")
        bet_date = signals["bet_date"]
        player   = signals["player"]
        score    = signals["score"]
        rank_val = signals["rank"]
        conf     = signals["confidence"]

        # Transform features
        transformed = []
        for col, transform in FEATURES:
            val = signals.get(col)
            if transform == "platoon":
                if val == "PLATOON+":
                    transformed.append(1.0)
                elif val == "platoon-":
                    transformed.append(-1.0)
                else:
                    transformed.append(0.0)
            else:
                transformed.append(float(val) if val is not None else np.nan)

        X_raw.append(transformed)
        y.append(int(homered))
        raw_rows.append({
            "player": player, "bet_date": bet_date,
            "score": score, "rank": rank_val,
            "confidence": conf, "homered": homered,
            "signals": signals,
        })

    X = np.array(X_raw, dtype=float)

    return X, np.array(y), raw_rows


def point_biserial_correlation(X: np.ndarray, y: np.ndarray) -> list[tuple[str, float]]:
    """Compute correlation between each feature and the binary outcome.
    NaN rows are dropped per-column (many features are only populated for the
    live-season slice of the data) rather than imputed, so this reflects the
    real relationship on the rows that actually have the signal."""
    from scipy import stats
    results = []
    for i, name in enumerate(FEATURE_NAMES):
        col = X[:, i]
        mask = ~np.isnan(col)
        col, col_y = col[mask], y[mask]
        if len(col) < 10 or col.std() < 1e-9:
            results.append((name, 0.0))
            continue
        r, p = stats.pointbiserialr(col, col_y)
        results.append((name, r))
    return sorted(results, key=lambda x: abs(x[1]), reverse=True)


def rank_hit_rate_analysis(raw_rows: list[dict]) -> None:
    """Show HR hit rate by Homer score rank bucket."""
    buckets = {
        "Top 5":    [r for r in raw_rows if r["rank"] and r["rank"] <= 5],
        "6–10":     [r for r in raw_rows if r["rank"] and 6 <= r["rank"] <= 10],
        "11–20":    [r for r in raw_rows if r["rank"] and 11 <= r["rank"] <= 20],
        "21–40":    [r for r in raw_rows if r["rank"] and 21 <= r["rank"] <= 40],
        "41+":      [r for r in raw_rows if r["rank"] and r["rank"] > 40],
        "No rank":  [r for r in raw_rows if not r["rank"]],
    }
    print("\n  Rank bucket → HR hit rate (this is the key metric):")
    print(f"  {'Bucket':<12} {'Players':>8} {'Homered':>8} {'Hit Rate':>10}")
    print("  " + "-" * 42)
    for label, group in buckets.items():
        if not group:
            continue
        hr_count = sum(r["homered"] for r in group)
        rate = hr_count / len(group) * 100
        bar = "█" * int(rate / 2)
        print(f"  {label:<12} {len(group):>8} {hr_count:>8} {rate:>9.1f}%  {bar}")

    overall_rate = sum(r["homered"] for r in raw_rows) / len(raw_rows) * 100
    print(f"\n  Overall HR rate: {overall_rate:.1f}%  (MLB base rate: ~15%)")
    print("  If Top 5 hit rate >> 41+ hit rate, Homer's ranking is working.")


def confidence_calibration(raw_rows: list[dict]) -> None:
    """Show actual HR rate by confidence tier."""
    tiers = {"HIGH": [], "MEDIUM": [], "LOW": [], None: []}
    for r in raw_rows:
        tier = r.get("confidence")
        if tier not in tiers:
            tier = None
        tiers[tier].append(r["homered"])

    print("\n  Confidence tier calibration:")
    print(f"  {'Tier':<10} {'Count':>6} {'HR Rate':>8}")
    print("  " + "-" * 28)
    for tier in ("HIGH", "MEDIUM", "LOW", None):
        vals = tiers[tier]
        if not vals:
            continue
        rate = sum(vals) / len(vals) * 100
        label = tier or "unknown"
        print(f"  {label:<10} {len(vals):>6} {rate:>7.1f}%")
    print("  (HIGH should have the highest hit rate — if not, tiers need recalibration)")


def _design(X: np.ndarray, medians: np.ndarray, ind_idx: list[int]) -> np.ndarray:
    """Median-impute X and append a 0/1 missing indicator for each column in ind_idx.
    Mirrors Homer._ml_score() exactly — change both together."""
    miss = np.isnan(X)
    Xi = np.where(miss, medians, X)
    return np.hstack([Xi, miss[:, ind_idx].astype(float)])


def _fit_logit(X: np.ndarray, y: np.ndarray) -> dict:
    """Fit imputation + scaler + L2 logistic regression; return an exportable model dict."""
    from sklearn.linear_model import LogisticRegression

    with np.errstate(all="ignore"):
        medians = np.nanmedian(X, axis=0)
    medians = np.where(np.isnan(medians), 0.0, medians)
    ind_idx = [i for i in range(X.shape[1]) if np.isnan(X[:, i]).any()]
    D = _design(X, medians, ind_idx)
    mean = D.mean(axis=0)
    scale = D.std(axis=0)
    scale[scale < 1e-9] = 1.0
    lr = LogisticRegression(C=LOGIT_C, max_iter=5000)
    lr.fit((D - mean) / scale, y)
    return {
        "medians": medians.tolist(),
        "indicator_features": [FEATURE_NAMES[i] for i in ind_idx],
        "scaler_mean": mean.tolist(),
        "scaler_scale": scale.tolist(),
        "coef": lr.coef_[0].tolist(),
        "intercept": float(lr.intercept_[0]),
    }


def predict_log_odds(model: dict, X: np.ndarray) -> np.ndarray:
    ind_idx = [FEATURE_NAMES.index(f) for f in model["indicator_features"]]
    D = _design(X, np.array(model["medians"]), ind_idx)
    Z = (D - np.array(model["scaler_mean"])) / np.array(model["scaler_scale"])
    return Z @ np.array(model["coef"]) + model["intercept"]


def _full_slate_mask(dates: np.ndarray, min_rows: int = 100) -> np.ndarray:
    """Days where the whole candidate pool was saved (Aug 2026+), not just the top 20."""
    uniq, counts = np.unique(dates, return_counts=True)
    full = set(uniq[counts >= min_rows])
    return np.array([d in full for d in dates])


def _heuristic_scores(raw_rows: list[dict], mask: np.ndarray) -> np.ndarray:
    """Re-score rows with Homer's heuristic only (ML disabled) to get its scale for blending."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.predictor import Homer

    saved = Homer.__dict__["_ml_score"]
    Homer._ml_score = classmethod(lambda cls, sig: None)
    try:
        out = []
        for r, m in zip(raw_rows, mask):
            if not m:
                continue
            sig = dict(r["signals"])
            sig["status"] = "confirmed" if sig.get("lineup_confirmed") == 1 else "waiting"
            sig.setdefault("season_hr", 10)  # not persisted; keep the pitcher-matchup gate open
            out.append(Homer._score_player(sig))
    finally:
        Homer._ml_score = saved
    return np.array(out, dtype=float)


def walk_forward_auc(X: np.ndarray, y: np.ndarray, dates: np.ndarray) -> tuple[float, float, int]:
    """Honest out-of-time AUC: refit every WF_STEP_DAYS on strictly-earlier data and
    score each of the last WF_TEST_DAYS full-slate days. Returns (mean, std, n_days)."""
    from sklearn.metrics import roc_auc_score

    full_days = sorted(set(dates[_full_slate_mask(dates)]))[-WF_TEST_DAYS:]
    aucs = []
    for i in range(0, len(full_days), WF_STEP_DAYS):
        chunk = full_days[i:i + WF_STEP_DAYS]
        train = dates < chunk[0]
        if y[train].sum() < 50:
            continue
        model = _fit_logit(X[train], y[train])
        for d in chunk:
            m = dates == d
            if len(set(y[m])) == 2:
                aucs.append(roc_auc_score(y[m], predict_log_odds(model, X[m])))
    if not aucs:
        return 0.5, 0.0, 0
    return float(np.mean(aucs)), float(np.std(aucs)), len(aucs)


def train_and_save(X: np.ndarray, y: np.ndarray, save: bool = True,
                   raw_rows: list[dict] | None = None) -> dict:
    """
    Train the logistic HR model and save ml_weights.json.
    raw_rows (from load_training_data) enables the walk-forward AUC and the
    heuristic-scale blend constants; without them, AUC falls back to 0.5 and
    Homer uses the heuristic alone.
    Returns the weights dict.
    """
    try:
        import sklearn  # noqa: F401
    except ImportError:
        print("\n  scikit-learn not installed. Run: pip install scikit-learn")
        return {}

    dates = np.array([r["bet_date"] for r in raw_rows]) if raw_rows else None

    if dates is not None:
        auc_mean, auc_std, n_days = walk_forward_auc(X, y, dates)
        print(f"\n  Walk-forward AUC (per day, last {n_days} full slates): {auc_mean:.3f} ± {auc_std:.3f}")
    else:
        auc_mean, auc_std, n_days = 0.5, 0.0, 0
        print("\n  No dates supplied — skipping walk-forward AUC.")
    print("  (0.5 = random; ~0.62 is near the practical ceiling for single-game HR props)")

    model = _fit_logit(X, y)

    # Blend constants: map ML log-odds onto the heuristic's scale via z-scores,
    # both measured on the full-slate days (the population Homer actually ranks).
    blend = {}
    if raw_rows:
        mask = _full_slate_mask(dates)
        if mask.sum() >= 1000:
            lo = predict_log_odds(model, X[mask])
            heur = _heuristic_scores(raw_rows, mask)
            blend = {
                "blend_weight": BLEND_WEIGHT,
                "ml_logodds_mean": float(lo.mean()), "ml_logodds_std": float(lo.std()),
                "heur_mean": float(heur.mean()), "heur_std": float(heur.std()),
            }
    if not blend:
        print("  Not enough full-slate rows for blend constants — Homer will use the heuristic alone.")

    n_feat = len(FEATURE_NAMES)
    coeffs = dict(zip(FEATURE_NAMES, model["coef"][:n_feat]))
    print("\n  Standardised coefficients (log-odds per 1 SD):")
    for feat, c in sorted(coeffs.items(), key=lambda x: abs(x[1]), reverse=True):
        print(f"  {feat:<26} {c:>+7.3f}  {'█' * int(abs(c) * 60)}")

    weights = {
        "model_type":    "logistic_v2",
        "trained_on":    date.today().isoformat(),
        "n_samples":     int(len(y)),
        "n_positives":   int(y.sum()),
        "cv_auc_mean":   auc_mean,
        "cv_auc_std":    auc_std,
        "cv_method":     f"walk-forward per-day AUC, {n_days} days",
        "feature_order": FEATURE_NAMES,
        "coefficients":  coeffs,
        "model":         model,
        **blend,
        "algo_version":  ALGO_VERSION,
    }

    if save:
        with open(WEIGHTS_PATH, "w") as f:
            json.dump(weights, f, indent=2)
        print("\n  Model saved to ml_weights.json")
        print("  Homer will use these weights automatically on next run.")

    return weights


def main():
    parser = argparse.ArgumentParser(description="Train logistic regression on HR pick data.")
    parser.add_argument("--report", action="store_true",
                        help="Show report only — do not save weights")
    parser.add_argument("--min", type=int, default=100, dest="min_rows",
                        help="Minimum labeled rows required to train (default: 100)")
    args = parser.parse_args()

    print("=" * 60)
    print("  HOMER ML WEIGHT OPTIMIZER")
    print("=" * 60)

    X, y, raw_rows = load_training_data()

    if len(y) == 0:
        print("\n  No labeled data yet.")
        print("  Run fetch_actual_results.py after each game day to label picks.")
        print("  Come back after ~2 weeks of data.")
        sys.exit(0)

    n_pos = int(y.sum())
    n_neg = int(len(y) - n_pos)
    base_rate = n_pos / len(y) * 100

    print(f"\n  Labeled examples: {len(y)}")
    print(f"  Homered (positive): {n_pos} ({base_rate:.1f}%)")
    print(f"  Did not homer:      {n_neg}")

    # ── Correlation analysis (always run, no sklearn needed) ──────────────────
    print("\n" + "=" * 60)
    print("  SIGNAL CORRELATIONS  (point-biserial r vs homered)")
    print("=" * 60)
    try:
        correlations = point_biserial_correlation(X, y)
        print(f"  {'Feature':<22} {'r':>8}  Interpretation")
        print("  " + "-" * 58)
        for feat, r in correlations:
            if abs(r) >= 0.10:
                strength = "strong"
            elif abs(r) >= 0.05:
                strength = "moderate"
            else:
                strength = "weak"
            direction = "+" if r >= 0 else "-"
            bar = "█" * int(abs(r) * 40)
            print(f"  {feat:<22} {r:>+8.3f}  {strength} {direction}  {bar}")
    except ImportError:
        print("  (scipy not installed — skipping correlation. pip install scipy)")

    # ── Rank bucket analysis ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RANK → HIT RATE ANALYSIS")
    print("=" * 60)
    rank_hit_rate_analysis(raw_rows)

    # ── Confidence calibration ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  CONFIDENCE TIER CALIBRATION")
    print("=" * 60)
    confidence_calibration(raw_rows)

    # ── Logistic regression ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  LOGISTIC REGRESSION")
    print("=" * 60)

    if len(y) < args.min_rows:
        print(f"\n  Only {len(y)} labeled rows — need {args.min_rows} to train reliably.")
        print(f"  Keep running daily_picks.py + fetch_actual_results.py.")
        est_days = (args.min_rows - len(y)) // 25
        print(f"  Estimated {est_days} more game days needed.")
        print("\n  Showing correlations above as a guide in the meantime.")
        sys.exit(0)

    train_and_save(X, y, save=not args.report, raw_rows=raw_rows)

    print("\n" + "=" * 60)
    print("  NEXT STEPS")
    print("=" * 60)
    if args.report:
        print("  (--report mode: weights NOT saved)")
        print("  Re-run without --report to save weights to ml_weights.json")
    else:
        print("  1. ml_weights.json saved — Homer uses it automatically")
        print("  2. Re-run daily_picks.py to see ML-adjusted picks")
        print("  3. Run this script again weekly as more data accumulates")
        print("  4. Watch cv_auc_mean — it should rise over time")


if __name__ == "__main__":
    main()

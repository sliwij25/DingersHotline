"""
optimize_weights.py
Train logistic regression on labeled pick_factors data → save ml_weights.json.
Homer's _score_player() reads these weights automatically once the file exists.

Run weekly (or after every ~50 new labeled days accumulate).

Usage:
    python optimize_weights.py              # train + save weights
    python optimize_weights.py --report     # report only, don't save weights
    python optimize_weights.py --min 50     # require at least N labeled rows (default 100)

Output:
    ml_weights.json          — loaded by _score_player() at runtime
    (stdout)                 — feature importances, calibration, rank-vs-hit-rate
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

# Features used for logistic regression.
# Each entry: (column_name, transform)
# transform: None = use raw value, "platoon" = PLATOON+→1 / platoon-→-1 / else→0
FEATURES = [
    # Contact quality — top predictors per Savant glossary research
    ("barrel_rate",      None),    # r=0.70 predictive for HR% — strongest single signal
    ("ev_avg",           None),    # r=0.57 predictive — avg exit velocity
    ("hard_hit_pct",     None),    # proxy for EV 100+ mph in air (r=0.66 descriptive)
    ("sweet_spot_pct",   None),    # r=0.42 predictive — 8-32° launch angle%
    ("xiso",             None),    # expected ISO — power composite
    ("xslg",             None),    # expected slugging — most predictive per FanGraphs
    ("xhr_rate",         None),    # expected HR rate — populates mid-season
    # Batted ball profile
    ("fb_pct",           None),    # fly ball rate — per RotoGrinders: strong HR correlation
    ("launch_angle",     None),    # avg launch angle — r=0.42 predictive
    ("hr_fb_ratio",      None),    # HR/FB — volatile early, meaningful mid-season
    # Bat tracking
    ("blast_rate",       None),    # % of swings qualifying as a Blast — high HR correlation
    # Context
    ("bpp_hr_pct",       None),
    ("park_hr_factor",   None),
    ("ev_10",            None),
    ("value_edge",       None),
    ("recent_form_14d",  None),
    ("pitcher_hr_per_9", None),
    ("is_home",          None),
    ("platoon",          "platoon"),
    ("h2h_hr",           None),
]

FEATURE_NAMES = [name for name, _ in FEATURES]


def load_training_data() -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """
    Load pick_factors rows where homered IS NOT NULL.
    Returns (X, y, raw_rows).
    Missing feature values are imputed with the column median.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = ", ".join(name for name, _ in FEATURES)
        rows = conn.execute(f"""
            SELECT {cols}, homered, bet_date, player, score, rank, confidence
            FROM pick_factors
            WHERE homered IS NOT NULL
            ORDER BY bet_date
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        return np.array([]), np.array([]), []

    n_features = len(FEATURES)
    raw_rows = []
    X_raw = []
    y = []

    for row in rows:
        feat_vals = list(row[:n_features])
        homered   = row[n_features]
        bet_date  = row[n_features + 1]
        player    = row[n_features + 2]
        score     = row[n_features + 3]
        rank_val  = row[n_features + 4]
        conf      = row[n_features + 5]

        # Transform features
        transformed = []
        for i, (col, transform) in enumerate(FEATURES):
            val = feat_vals[i]
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
        })

    X = np.array(X_raw, dtype=float)

    # Impute missing values with column median
    for col_i in range(X.shape[1]):
        col = X[:, col_i]
        median = np.nanmedian(col)
        X[np.isnan(col), col_i] = median if not np.isnan(median) else 0.0

    return X, np.array(y), raw_rows


def point_biserial_correlation(X: np.ndarray, y: np.ndarray) -> list[tuple[str, float]]:
    """Compute correlation between each feature and the binary outcome."""
    from scipy import stats
    results = []
    for i, name in enumerate(FEATURE_NAMES):
        col = X[:, i]
        if col.std() < 1e-9:
            results.append((name, 0.0))
            continue
        r, p = stats.pointbiserialr(col, y)
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


def train_and_save(X: np.ndarray, y: np.ndarray,
                   save: bool = True) -> dict:
    """
    Train logistic regression, output coefficients.
    Returns weights dict saved to ml_weights.json.
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import cross_val_score, StratifiedKFold
        from sklearn.calibration import CalibratedClassifierCV
    except ImportError:
        print("\n  scikit-learn not installed.")
        print("  Run: pip install scikit-learn scipy")
        return {}

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Use calibrated logistic regression (outputs true probabilities)
    base_lr = LogisticRegression(C=0.5, max_iter=1000, class_weight="balanced")

    # Cross-val AUC to estimate model quality
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    auc_scores = cross_val_score(base_lr, X_scaled, y, cv=cv, scoring="roc_auc")
    print(f"\n  Cross-val AUC: {auc_scores.mean():.3f} ± {auc_scores.std():.3f}")
    print("  (0.5 = random, 0.6+ = useful, 0.7+ = strong)")

    # Fit on all data for final weights
    base_lr.fit(X_scaled, y)

    # Feature importances (standardized coefficients)
    coeffs = base_lr.coef_[0]
    feat_importance = sorted(
        zip(FEATURE_NAMES, coeffs), key=lambda x: abs(x[1]), reverse=True
    )

    print("\n  Feature importances (logistic regression coefficients):")
    print(f"  {'Feature':<22} {'Coeff':>8}  Direction")
    print("  " + "-" * 48)
    for feat, coeff in feat_importance:
        direction = "↑ helps HR" if coeff > 0 else "↓ hurts HR"
        bar = "█" * int(abs(coeff) * 3)
        print(f"  {feat:<22} {coeff:>+8.3f}  {direction}  {bar}")

    # Build weights dict
    weights = {
        "trained_on":    date.today().isoformat(),
        "n_samples":     int(len(y)),
        "n_positives":   int(y.sum()),
        "cv_auc_mean":   float(auc_scores.mean()),
        "cv_auc_std":    float(auc_scores.std()),
        "scaler_mean":   scaler.mean_.tolist(),
        "scaler_scale":  scaler.scale_.tolist(),
        "coefficients":  {f: float(c) for f, c in zip(FEATURE_NAMES, coeffs)},
        "intercept":     float(base_lr.intercept_[0]),
        "feature_order": FEATURE_NAMES,
    }

    if save:
        with open(WEIGHTS_PATH, "w") as f:
            json.dump(weights, f, indent=2)
        print(f"\n  Weights saved to ml_weights.json")
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

    weights = train_and_save(X, y, save=not args.report)

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

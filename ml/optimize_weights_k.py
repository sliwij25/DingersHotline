"""
optimize_weights_k.py
Train LightGBM on labeled pick_factors_k data → ml_weights_k.json + lgbm_model_k.txt.
Ace's _ml_score (once added) reads these automatically once the files exist.
Mirrors ml/optimize_weights.py's structure exactly — see that file for the
full CLI/reporting pattern this was adapted from.

Usage:
    python ml/optimize_weights_k.py              # train + save weights
    python ml/optimize_weights_k.py --report      # report only
    python ml/optimize_weights_k.py --min 50      # min labeled rows required (default 100)
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
WEIGHTS_PATH_K = os.path.join(os.path.dirname(__file__), "..", "ml_weights_k.json")
LGBM_MODEL_PATH_K = os.path.join(os.path.dirname(__file__), "..", "lgbm_model_k.txt")

FEATURES_K = [
    ("k_percent", None),
    ("whiff_percent", None),
    ("csw_percent", None),
    ("swinging_strike_percent", None),
    ("k_per_9_blended", None),
    ("pitcher_whiff_fastball", None),
    ("pitcher_whiff_breaking", None),
    ("pitcher_whiff_offspeed", None),
    ("opp_whiff_vs_mix", None),
    ("avg_ip_last3", None),
    ("avg_pitches_last3", None),
    ("days_rest", None),
    ("ev_10", None),
    ("value_edge", None),
]

FEATURE_NAMES_K = [name for name, _ in FEATURES_K]


def load_training_data() -> tuple[np.ndarray, np.ndarray, list[dict]]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = ", ".join(name for name, _ in FEATURES_K)
        rows = conn.execute(f"""
            SELECT {cols}, over_hit, bet_date, pitcher, score, rank, confidence
            FROM pick_factors_k
            WHERE over_hit IS NOT NULL
            ORDER BY bet_date
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        return np.array([]), np.array([]), []

    n_features = len(FEATURES_K)
    raw_rows, X_raw, y = [], [], []
    for row in rows:
        feat_vals = list(row[:n_features])
        over_hit, bet_date, pitcher, score, rank_val, conf = row[n_features:n_features + 6]
        X_raw.append([float(v) if v is not None else np.nan for v in feat_vals])
        y.append(int(over_hit))
        raw_rows.append({"pitcher": pitcher, "bet_date": bet_date, "score": score, "rank": rank_val, "confidence": conf, "over_hit": over_hit})

    X = np.array(X_raw, dtype=float)
    for col_i in range(X.shape[1]):
        col = X[:, col_i]
        median = np.nanmedian(col)
        X[np.isnan(col), col_i] = median if not np.isnan(median) else 0.0
    return X, np.array(y), raw_rows


def train_and_save_k(X: np.ndarray, y: np.ndarray, save: bool = True) -> dict:
    try:
        import lightgbm as lgb
        import pandas as pd
        from sklearn.model_selection import cross_val_score, StratifiedKFold
    except ImportError:
        print("\n  lightgbm not installed. Run: pip install lightgbm")
        return {}

    X_df = pd.DataFrame(X, columns=FEATURE_NAMES_K)
    scale_pos_weight = (len(y) - y.sum()) / max(y.sum(), 1)
    model = lgb.LGBMClassifier(
        objective="binary", metric="auc", n_estimators=500, learning_rate=0.05,
        num_leaves=31, min_child_samples=50, scale_pos_weight=scale_pos_weight,
        random_state=42, verbose=-1,
    )
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    auc_scores = cross_val_score(model, X_df, y, cv=cv, scoring="roc_auc")
    print(f"\n  Cross-val AUC: {auc_scores.mean():.3f} ± {auc_scores.std():.3f}")

    model.fit(X_df, y)
    weights = {
        "model_type": "lightgbm", "trained_on": date.today().isoformat(),
        "n_samples": int(len(y)), "n_positives": int(y.sum()),
        "cv_auc_mean": float(auc_scores.mean()), "cv_auc_std": float(auc_scores.std()),
        "feature_order": FEATURE_NAMES_K, "algo_version": "1.0",
    }
    if save:
        model.booster_.save_model(LGBM_MODEL_PATH_K)
        with open(WEIGHTS_PATH_K, "w") as f:
            json.dump(weights, f, indent=2)
        print(f"\n  Model saved to lgbm_model_k.txt / ml_weights_k.json")
    return weights


def main():
    parser = argparse.ArgumentParser(description="Train LightGBM on K prop pick data.")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--min", type=int, default=100, dest="min_rows")
    args = parser.parse_args()

    X, y, raw_rows = load_training_data()
    if len(y) == 0:
        print("\n  No labeled K-prop data yet. Run fetch_actual_k_results.py after game days.")
        sys.exit(0)
    if len(y) < args.min_rows:
        print(f"\n  Only {len(y)} labeled rows — need {args.min_rows} to train reliably.")
        sys.exit(0)

    train_and_save_k(X, y, save=not args.report)


if __name__ == "__main__":
    main()

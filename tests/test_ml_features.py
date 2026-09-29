"""
Tests for ML feature set and model type.

History:
  - xslg/hard_hit_pct/sweet_spot_pct were removed to fix logistic regression multicollinearity.
  - After switching to LightGBM, all features are restored — trees handle correlated
    features correctly without sign-flipping.
  - v5 (Sept 2026): back to logistic regression (model_type=logistic_v2), live rows only,
    strong L2 keeps correlated features stable. Walk-forward validated; see ALGORITHM.md.
"""
import inspect
import json
import os
import re
import sys
import pathlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ml.optimize_weights import FEATURE_NAMES

ROOT = pathlib.Path(__file__).parent.parent
WEIGHTS_PATH = ROOT / "ml_weights.json"

# Features that were problematic under logistic regression but valid under LightGBM
RESTORED_FEATURES = {"barrel_rate", "hard_hit_pct", "sweet_spot_pct", "xslg"}


def test_restored_features_back_in_training_set():
    """All contact-quality features stay in the model (strong L2 handles collinearity)."""
    missing = RESTORED_FEATURES - set(FEATURE_NAMES)
    assert missing == set(), (
        f"These features should be restored under LightGBM: {missing}"
    )


def test_xiso_still_present():
    """xiso must remain — it's the strongest single predictor (r=0.123)."""
    assert "xiso" in FEATURE_NAMES


def test_model_type_is_logistic_v2():
    """ml_weights.json must declare model_type=logistic_v2 with blend constants."""
    assert WEIGHTS_PATH.exists(), "ml_weights.json not found"
    with open(WEIGHTS_PATH) as f:
        weights = json.load(f)
    assert weights.get("model_type") == "logistic_v2", (
        f"Expected model_type='logistic_v2', got {weights.get('model_type')!r}"
    )
    for key in ("model", "blend_weight", "heur_mean", "heur_std",
                "ml_logodds_mean", "ml_logodds_std"):
        assert key in weights, f"ml_weights.json missing {key!r}"


def test_ml_score_matches_trainer():
    """Homer._ml_score must reproduce optimize_weights.predict_log_odds exactly."""
    import numpy as np
    from ml.optimize_weights import predict_log_odds
    from agents.predictor import Homer
    Homer._ml_weights_loaded = False
    Homer._ml_weights = None
    with open(WEIGHTS_PATH) as f:
        w = json.load(f)
    sig = {"xiso": 0.250, "barrel_rate": 12.0, "hard_hit_pct": 48.0, "platoon": "PLATOON+",
           "is_home": 1, "park_hr_factor": 105}  # everything else missing → imputed
    x = np.array([[{"PLATOON+": 1.0}.get(sig.get(f), sig.get(f)) if sig.get(f) is not None
                   else np.nan for f in FEATURE_NAMES]], dtype=float)
    lo = predict_log_odds(w["model"], x)[0]
    expected = w["heur_mean"] + w["heur_std"] * (lo - w["ml_logodds_mean"]) / w["ml_logodds_std"]
    assert abs(Homer._ml_score(sig) - expected) < 0.01


def test_all_features_have_a_save_pick_factors_write_path():
    """
    Every column in FEATURES must be written by save_pick_factors() via
    signals.get("<col>") — otherwise the model trains on a column that's
    computed in-memory (predictor.py) but never persisted, so it's 100%
    null in the DB and silently useless (the exact bug class that caused
    pitcher_fb_pct/breaking_pct/offspeed_pct/bpp_vs_grade to be dead).
    """
    from agents import bet_tracker
    source = inspect.getsource(bet_tracker.save_pick_factors)
    referenced = set(re.findall(r'signals\.get\("([^"]+)"\)', source))

    missing = [name for name in FEATURE_NAMES if name not in referenced]
    assert missing == [], (
        f"FEATURES columns with no signals.get(...) write path in "
        f"save_pick_factors(): {missing} — these will always be NULL in pick_factors"
    )


def test_ml_score_returns_numeric():
    """Homer._ml_score must return a float (not None) when the model is present."""
    from agents.predictor import Homer
    Homer._ml_weights_loaded = False
    Homer._ml_weights = None

    sig = {
        "xiso": 0.250, "barrel_rate": 8.5, "ev_avg": 90.1, "hard_hit_pct": 42.0,
        "sweet_spot_pct": 35.0, "fb_pct": 38.0, "launch_angle": 18.0,
        "hr_fb_ratio": 14.0, "blast_rate": 5.0, "park_hr_factor": 1.05,
        "ev_10": 0.50, "value_edge": 2.0, "recent_form_14d": 1,
        "pitcher_hr_per_9": 1.5, "pitcher_hr_vs_hand": 1.2,
        "pitcher_barrel_pct": 7.0, "is_home": 1, "platoon": "PLATOON+",
        "h2h_hr": 1,
    }
    result = Homer._ml_score(sig)
    assert result is not None, "_ml_score returned None — model not loading"
    assert isinstance(result, float), f"Expected float, got {type(result)}"
    assert -50.0 <= result <= 60.0, f"Score {result} outside the heuristic's scale"


def test_k_features_have_a_save_pick_factors_k_write_path():
    """
    Same regression guard as the HR model's equivalent test — every column
    in FEATURES_K must be written by save_pick_factors_k() via
    signals.get("<col>"), or it's silently always-NULL in pick_factors_k.
    """
    from ml.optimize_weights_k import FEATURE_NAMES_K
    from agents import bet_tracker
    source = inspect.getsource(bet_tracker.save_pick_factors_k)
    referenced = set(re.findall(r'signals\.get\("([^"]+)"\)', source))

    missing = [name for name in FEATURE_NAMES_K if name not in referenced]
    assert missing == [], (
        f"FEATURES_K columns with no signals.get(...) write path in "
        f"save_pick_factors_k(): {missing}"
    )

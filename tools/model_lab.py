"""
model_lab.py — walk-forward evaluation of HR model variants on live 2026 slates.

Every live pick_factors row is a full-slate candidate (~350/day), so we can measure
how well each variant *ranks* a day's slate — the thing that actually matters.

Usage: python tools/model_lab.py
"""
import os, sqlite3, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "ml"))
from optimize_weights import FEATURE_NAMES  # noqa: E402

def american_to_prob(o):
    try: o = float(str(o).replace("+", ""))
    except (TypeError, ValueError): return np.nan
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)

def american_profit(o, stake=10.0):
    try: o = float(str(o).replace("+", ""))
    except (TypeError, ValueError): return np.nan
    return stake * (o / 100 if o > 0 else 100 / -o)

def load():
    df = pd.read_sql("select * from pick_factors where homered is not null",
                     sqlite3.connect(ROOT / "data" / "bets.db"))
    df["live"] = ~df.algo_version.str.startswith("hist")
    df["platoon"] = df.platoon.map({"PLATOON+": 1.0, "platoon-": -1.0})
    df["pin_prob"] = df.pinnacle_odds.map(american_to_prob)
    df["month"] = df.bet_date.str[:7]
    return df

def day_metrics(d, col):
    """Per-day ranking quality of column `col` (higher = more likely HR)."""
    from sklearn.metrics import roc_auc_score
    out = []
    for day, g in d.groupby("bet_date"):
        g = g.dropna(subset=[col])
        if g.homered.nunique() < 2 or len(g) < 40: continue
        g = g.sort_values(col, ascending=False)
        top = g.head(20)
        prof = [american_profit(o) if h else -10.0
                for o, h in zip(top.best_odds.fillna(top.pinnacle_odds), top.homered)]
        prof = [p if not (isinstance(p, float) and np.isnan(p)) else 35.0 for p in prof]  # +350 fallback
        out.append(dict(auc=roc_auc_score(g.homered, g[col]),
                        top10=g.head(10).homered.mean(), top20=top.homered.mean(),
                        pnl20=sum(prof), base=g.homered.mean()))
    m = pd.DataFrame(out)
    return m.mean().round(4).to_dict() | {"days": len(m), "pnl20_total": round(m.pnl20.sum(), 1)}

# ── walk-forward experiments ──────────────────────────────────────────────
CORE = ["barrel_rate", "ev_avg", "hard_hit_pct", "sweet_spot_pct", "xiso", "xslg",
        "fb_pct", "launch_angle", "pitcher_hr_per_9", "is_home", "park_hr_factor"]

def lgbm(params=None):
    import lightgbm as lgb
    p = dict(n_estimators=500, learning_rate=0.05, num_leaves=31, min_child_samples=50,
             random_state=42, verbose=-1)
    p.update(params or {})
    return lgb.LGBMClassifier(**p)

def walk_forward(df, fit_predict, start="2026-08-10", step_days=7):
    """Refit weekly; predict each following week of live full-slate days."""
    L = df[df.live]
    days = sorted(d for d in L.bet_date.unique() if d >= start)
    preds = []
    for i in range(0, len(days), step_days):
        chunk = days[i:i + step_days]
        train = df[df.bet_date < chunk[0]]
        test = L[L.bet_date.isin(chunk)].copy()
        test["pred"] = fit_predict(train, test)
        preds.append(test)
    return pd.concat(preds)

def run(name, df, fp, **kw):
    out = walk_forward(df, fp, **kw)
    print(f"{name:<34}", day_metrics(out, "pred"))
    return out

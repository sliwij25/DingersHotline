"""
k_predictor.py — Ace: MLB pitcher strikeout prop prediction.

Sibling to agents/predictor.py's Homer (HR model). Same philosophy: gather
real signals, score deterministically, blend in a LightGBM model once one
exists. No LLM involved in ranking.

Reuses Homer's EV/Kelly math and the (Task 1-extended) pitcher recent-form
fetch. Owns its own Statcast fetch, its own odds market (pitcher_strikeouts,
not batter_home_runs), its own DB table (pick_factors_k), and its own site
page — a bug here cannot affect the HR pipeline.
"""
import csv
import io
from datetime import date
from pathlib import Path

import requests

from agents.predictor import (
    SAVANT_BASE, MLB_API_BASE, ODDS_API_BASE, _HEADERS,
    _compute_ev, _compute_kelly, _american_to_implied_prob,
    _fetch_pitcher_recent_form,
)


def _fetch_pitcher_k_statcast() -> dict:
    """
    Fetch the full Statcast pitcher K-rate leaderboard CSV, keyed by
    player_id (primary) and lowercased name (secondary). Columns:
    k_percent, whiff_percent, csw_percent, swinging_strike_percent.
    Caches to cache/statcast_pitcher_k_YYYY-MM-DD.csv (one fetch per day).
    """
    season    = date.today().year
    today_str = date.today().isoformat()
    cache_path = Path(__file__).parent.parent / "cache" / f"statcast_pitcher_k_{today_str}.csv"

    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8")
    else:
        url = (
            f"{SAVANT_BASE}/leaderboard/custom"
            f"?year={season}&type=pitcher&filter=&sort=4&sortDir=desc&min=5"
            f"&selections=k_percent,whiff_percent,csw_percent,swinging_strike_percent"
            f"&chart=false&r=no&exactNameSearch=false&csv=true"
        )
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            text = resp.text.lstrip('﻿')
            cache_path.parent.mkdir(exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        except Exception:
            return {}

    try:
        reader = csv.DictReader(io.StringIO(text))
        result = {}
        for row in reader:
            name = (row.get("last_name, first_name") or row.get("player_name") or "").lower()
            pid_raw = row.get("player_id") or row.get("pitcher") or ""
            try:
                result[int(pid_raw)] = row
            except (ValueError, TypeError):
                pass
            if name:
                result.setdefault(name, row)
        return result
    except Exception:
        return {}

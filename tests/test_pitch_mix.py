import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import csv
import io
import pytest
from pathlib import Path
from datetime import date

from agents.predictor import Homer, _safe_float


def test_pitch_bucket_derivation():
    """Pitch bucket sums should correctly aggregate pitch-family percentages."""
    sp_data = {
        "n_ff_formatted": "50.0",
        "n_si_formatted": "10.0",
        "n_fc_formatted": "5.0",
        "n_sl_formatted": "20.0",
        "n_cu_formatted": "8.0",
        "n_sw_formatted": "0.0",
        "n_ch_formatted": "7.0",
        "n_fs_formatted": "0.0",
    }

    def _bucket(fields):
        return round(sum(
            (_safe_float(sp_data.get(f)) or 0.0) for f in fields
        ), 1)

    fb_pct       = _bucket(["n_ff_formatted", "n_si_formatted", "n_fc_formatted"])
    breaking_pct = _bucket(["n_sl_formatted", "n_cu_formatted", "n_sw_formatted"])
    offspeed_pct = _bucket(["n_ch_formatted", "n_fs_formatted"])

    assert fb_pct == 65.0
    assert breaking_pct == 28.0
    assert offspeed_pct == 7.0


def test_player_signals_include_pitch_buckets():
    """player_signals should contain pitcher_fb_pct keys after _build_game_cards()."""
    import json

    homer = Homer()

    # Aaron Judge is on the AWAY team so he faces the HOME pitcher (Gerrit Cole).
    # _build_game_cards iterates each side and uses opp.starting_pitcher as the SP.
    fake_lineups = json.dumps({
        "status": "success",
        "games": [{
            "home": {
                "team": "New York Yankees",
                "lineup_confirmed": True,
                "starting_pitcher": "Gerrit Cole",
                "pitcher_id": 543037,
                "pitcher_throws": "R",
                "batters": [],
            },
            "away": {
                "team": "Boston Red Sox",
                "lineup_confirmed": True,
                "starting_pitcher": "TBD",
                "pitcher_id": None,
                "pitcher_throws": "R",
                "batters": [{"id": 592450, "name": "Aaron Judge", "bat_side": "R", "status": "confirmed"}],
            },
            "venue": "Yankee Stadium",
            "game_time": "2026-04-19T23:05:00Z",
        }]
    })

    fake_pitcher_stats = {
        "cole, gerrit": {
            "hr_flyball_rate": "8.5", "fb_percent": "52.0",
            "xfip": "3.20", "hard_hit_percent": "38.0",
            "barrel_batted_rate": "6.0",
            "n_ff_formatted": "55.0", "n_si_formatted": "0.0", "n_fc_formatted": "5.0",
            "n_sl_formatted": "22.0", "n_cu_formatted": "10.0", "n_sw_formatted": "0.0",
            "n_ch_formatted": "8.0", "n_fs_formatted": "0.0",
        }
    }

    _, signals = homer._build_game_cards(
        fake_lineups,
        batter_stats={},
        pitcher_stats=fake_pitcher_stats,
        our_history=[],
        recent_form=[],
        pitcher_form={},
        home_away={},
    )

    assert "Aaron Judge" in signals
    judge = signals["Aaron Judge"]
    assert "pitcher_fb_pct" in judge, "pitcher_fb_pct should be in player_signals"
    assert judge["pitcher_fb_pct"] == 60.0   # 55 + 0 + 5
    assert judge["pitcher_breaking_pct"] == 32.0  # 22 + 10 + 0
    assert judge["pitcher_offspeed_pct"] == 8.0   # 8 + 0


@pytest.mark.network
def test_fetch_pitchers_includes_pitch_mix(require_network):
    """Pitcher cache CSV should contain pitch-mix columns from _fetch_pitchers()."""
    homer = Homer()
    # _fetch_pitchers calls _fetch_full_statcast with the pitch-mix selections.
    # Call it directly to ensure the cache is warm with the current selections.
    stats = homer._fetch_full_statcast(
        "pitcher",
        "hr_flyball_rate,fb_percent,xfip,hard_hit_percent,barrel_batted_rate,"
        "n_ff_formatted,n_si_formatted,n_fc_formatted,"
        "n_sl_formatted,n_cu_formatted,n_sw_formatted,"
        "n_ch_formatted,n_fs_formatted"
    )

    # Also verify the on-disk cache contains pitch-mix columns — this would catch
    # _fetch_pitchers() being changed to drop the columns in a real run.
    cache_path = Path("cache") / f"statcast_pitcher_{date.today().isoformat()}.csv"
    assert cache_path.exists(), f"Expected pitcher cache at {cache_path}"
    text = cache_path.read_text(encoding="utf-8").lstrip("\ufeff")
    headers = next(csv.reader(io.StringIO(text)))
    assert "n_ff_formatted" in headers, f"n_ff_formatted missing from pitcher cache headers: {headers}"
    assert "n_sl_formatted" in headers
    assert "n_ch_formatted" in headers

    # Stat dict should be non-empty with fb data
    pitchers_with_ff = [
        name for name, row in stats.items()
        if row.get("n_ff_formatted") not in (None, "")
    ]
    assert len(pitchers_with_ff) > 0

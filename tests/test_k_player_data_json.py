import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_k_player_data_json

def _sample_pick(pitcher="Test Pitcher", score=12.0, rank=1):
    return {
        "pitcher": pitcher,
        "matchup": "NYY @ BOS",
        "direction": "OVER",
        "confidence": "HIGH",
        "score": score,
        "projected_k": 7.2,
        "gap": 1.7,
        "reasoning": "Elite K% vs a whiff-prone lineup.",
        "signals": {
            "venue": "Fenway Park",
            "game_time": "2026-08-22T23:05:00Z",
            "pitcher_throws": "R",
            "k_line": 5.5,
            "k_percent": 28.4,
            "whiff_percent": 31.2,
            "csw_percent": 30.1,
            "swinging_strike_percent": 13.5,
            "k_per_9_blended": 10.1,
            "avg_ip_last3": 6.0,
            "avg_pitches_last3": 92.0,
            "days_rest": 5,
            "pitcher_whiff_fastball": 22.0,
            "pitcher_whiff_breaking": 38.0,
            "pitcher_whiff_offspeed": 30.0,
            "opp_whiff_vs_mix": 27.5,
            "opp_team_k_pct": 24.0,
            "ev_10": 3.5,
            "value_edge": 4.2,
            "kelly_size": 12.0,
            "pinnacle_odds": "-115",
        },
    }

class TestGenerateKPlayerDataJson:
    def test_entry_shape_and_slug(self):
        picks = [_sample_pick()]
        out = json.loads(generate_k_player_data_json(picks, "2026-08-22"))

        assert out["date"] == "2026-08-22"
        entry = out["players"][0]
        assert entry["slug"] == "test-pitcher"
        assert entry["pitcher"] == "Test Pitcher"
        assert entry["rank"] == 1
        assert entry["direction"] == "OVER"
        assert entry["projected_k"] == 7.2
        assert entry["gap"] == 1.7
        assert entry["game_time_et"] == "7:05 PM ET"
        assert entry["signals"]["venue"] == "Fenway Park"
        assert entry["signals"]["pitcher_throws"] == "R"
        assert entry["signals"]["k_line"] == 5.5
        assert "ev_10" not in entry["signals"]
        assert "value_edge" not in entry["signals"]
        assert "kelly_size" not in entry["signals"]

    def test_rank_follows_input_order(self):
        picks = [_sample_pick("First", score=15.0), _sample_pick("Second", score=10.0)]
        out = json.loads(generate_k_player_data_json(picks, "2026-08-22"))
        ranks = {e["pitcher"]: e["rank"] for e in out["players"]}
        assert ranks == {"First": 1, "Second": 2}

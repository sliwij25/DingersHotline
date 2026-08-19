"""
Tests for the strikeout prop model (Ace / k_predictor.py) — signal extraction
and scoring. Mirrors tests/test_new_signals.py's style: plain dict builders,
no live network calls, ML weights monkeypatched off where relevant.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock


def _fake_gamelog_response(rows):
    """Build a fake MLB Stats API gameLog JSON payload from a list of
    (date, strikeOuts, homeRuns, earnedRuns, inningsPitched, numberOfPitches) tuples."""
    splits = []
    for date_str, so, hr, er, ip, pitches in rows:
        splits.append({
            "date": date_str,
            "stat": {
                "strikeOuts": so, "homeRuns": hr, "earnedRuns": er,
                "inningsPitched": str(ip), "numberOfPitches": pitches,
            },
        })
    return {"stats": [{"splits": splits}]}


class TestPitcherRecentFormKFields:

    def test_returns_k_per_9_blended_and_workload_fields(self):
        from agents.predictor import _fetch_pitcher_recent_form

        rows = [
            ("2026-08-15", 9, 1, 2, "6.0", 96),
            ("2026-08-10", 7, 0, 1, "5.1", 91),
            ("2026-08-05", 8, 2, 3, "6.2", 99),
            ("2026-07-30", 6, 1, 2, "5.0", 88),
        ]
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = _fake_gamelog_response(rows)

        with patch("agents.predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitcher_recent_form(12345, n_starts=3)

        assert "k_per_9_blended" in result
        assert "recent_k9" in result
        assert "season_k9" in result
        assert "avg_ip_last3" in result
        assert "avg_pitches_last3" in result
        assert "days_rest" in result

        # Existing HR fields must be untouched — Homer depends on these.
        assert "hr_per_9" in result
        assert "starts_sampled" in result

        # 3 most recent starts: (9+7+8) K over (6.0+5.1+6.2) IP = 24/17.3*9 ≈ 12.49
        assert result["recent_k9"] == round((9 + 7 + 8) / (6.0 + 5.1 + 6.2) * 9, 2)
        assert result["avg_ip_last3"] == round((6.0 + 5.1 + 6.2) / 3, 2)
        assert result["avg_pitches_last3"] == round((96 + 91 + 99) / 3, 2)

    def test_days_rest_computed_from_most_recent_start(self):
        from agents.predictor import _fetch_pitcher_recent_form
        from datetime import date, timedelta

        five_days_ago = (date.today() - timedelta(days=5)).isoformat()
        rows = [(five_days_ago, 7, 1, 2, "6.0", 95)]
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = _fake_gamelog_response(rows)

        with patch("agents.predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitcher_recent_form(12345, n_starts=3)

        assert result["days_rest"] == 5

    def test_missing_pitch_count_falls_back_to_none(self):
        """numberOfPitches isn't always present in older/incomplete logs."""
        from agents.predictor import _fetch_pitcher_recent_form

        rows_no_pitches = [("2026-08-15", 7, 1, 2, "6.0", None)]
        splits = [{
            "date": "2026-08-15",
            "stat": {"strikeOuts": 7, "homeRuns": 1, "earnedRuns": 2, "inningsPitched": "6.0"},
        }]
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {"stats": [{"splits": splits}]}

        with patch("agents.predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitcher_recent_form(12345, n_starts=3)

        assert result["avg_pitches_last3"] is None

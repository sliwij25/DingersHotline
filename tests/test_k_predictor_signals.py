import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.k_predictor import Ace


def _mock_schedule_response(pitcher_id=100, pitcher_name="Test Pitcher"):
    return {
        "dates": [{
            "games": [{
                "gameDate": "2026-08-22T23:05:00Z",
                "venue": {"name": "Test Park"},
                "teams": {
                    "away": {"team": {"id": 1, "abbreviation": "AWY", "name": "Away Team"}},
                    "home": {"team": {"id": 2, "abbreviation": "HME", "name": "Home Team"},
                             "probablePitcher": {"id": pitcher_id, "fullName": pitcher_name}},
                },
                "lineups": {"homePlayers": [], "awayPlayers": []},
            }]
        }]
    }


def _mock_people_response(pitcher_id=100, hand="R"):
    return {"people": [{"id": pitcher_id, "pitchHand": {"code": hand}}]}


class TestPitcherSignalGap:
    def test_sig_dict_includes_venue_game_time_pitcher_throws(self):
        ace = Ace()
        schedule_resp = MagicMock()
        schedule_resp.json.return_value = _mock_schedule_response()
        people_resp = MagicMock()
        people_resp.json.return_value = _mock_people_response()

        def fake_get(url, params=None, timeout=None):
            if url.endswith("/schedule"):
                return schedule_resp
            if url.endswith("/people"):
                return people_resp
            resp = MagicMock()
            resp.json.return_value = {}
            return resp

        with patch("agents.k_predictor.requests.get", side_effect=fake_get):
            with patch("agents.k_predictor._fetch_pitcher_k_statcast", return_value={}), \
                 patch("agents.k_predictor._fetch_pitch_arsenal_whiff", return_value={}), \
                 patch("agents.k_predictor._fetch_pitcher_pitch_mix", return_value={}), \
                 patch("agents.k_predictor._fetch_pitcher_recent_form", return_value={}), \
                 patch("agents.k_predictor._fetch_team_k_pct", return_value=None), \
                 patch("agents.k_predictor._weighted_opp_whiff", return_value=None), \
                 patch("agents.k_predictor.fetch_k_odds_comparison", return_value='{"comparisons": []}'):
                data = ace._gather_data()

        sig = data["pitcher_signals"]["Test Pitcher"]
        assert sig["venue"] == "Test Park"
        assert sig["game_time"] == "2026-08-22T23:05:00Z"
        assert sig["pitcher_throws"] == "R"

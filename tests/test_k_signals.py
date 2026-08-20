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


class TestPitcherKStatcastFetch:

    def test_fetches_and_keys_by_player_id_and_name(self):
        from agents.k_predictor import _fetch_pitcher_k_statcast

        csv_text = (
            '"last_name, first_name",player_id,k_percent,whiff_percent,csw_percent,swinging_strike_percent\n'
            '"Cole, Gerrit",543037,32.5,29.1,31.0,14.2\n'
        )
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.text = csv_text

        with patch("agents.k_predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitcher_k_statcast()

        assert result[543037]["k_percent"] == "32.5"
        assert result["cole, gerrit"]["whiff_percent"] == "29.1"

    def test_returns_empty_dict_on_request_failure(self):
        from agents.k_predictor import _fetch_pitcher_k_statcast

        with patch("agents.k_predictor.requests.get", side_effect=Exception("network down")):
            result = _fetch_pitcher_k_statcast()

        assert result == {}


class TestPitchArsenalWhiff:

    def test_fetch_pitch_arsenal_whiff_buckets_and_weights_by_pa(self):
        from agents.k_predictor import _fetch_pitch_arsenal_whiff

        csv_text = (
            "player_id,pitch_type,whiff_percent,pa\n"
            "543037,FF,28.0,100\n"
            "543037,SI,24.0,50\n"
            "543037,SL,35.0,80\n"
            "543037,CH,20.0,40\n"
        )
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.text = csv_text

        with patch("agents.k_predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitch_arsenal_whiff([543037], player_type="pitcher")

        # fastball bucket = FF(28.0, pa=100) + SI(24.0, pa=50), PA-weighted:
        expected_fastball = (28.0 * 100 + 24.0 * 50) / (100 + 50)
        assert round(result[543037]["whiff_fastball"], 2) == round(expected_fastball, 2)
        assert result[543037]["whiff_breaking"] == 35.0
        assert result[543037]["whiff_offspeed"] == 20.0

    def test_weighted_opp_whiff_combines_pitcher_mix_with_batter_splits(self):
        from agents.k_predictor import _weighted_opp_whiff

        pitcher_mix = {"fastball": 0.60, "breaking": 0.30, "offspeed": 0.10}
        batter_splits = [
            {"whiff_fastball": 20.0, "whiff_breaking": 30.0, "whiff_offspeed": 40.0},
            {"whiff_fastball": 30.0, "whiff_breaking": 20.0, "whiff_offspeed": 10.0},
        ]
        result = _weighted_opp_whiff(pitcher_mix, batter_splits)

        batter1 = 20.0 * 0.60 + 30.0 * 0.30 + 40.0 * 0.10
        batter2 = 30.0 * 0.60 + 20.0 * 0.30 + 10.0 * 0.10
        expected = round((batter1 + batter2) / 2, 2)
        assert result == expected

    def test_weighted_opp_whiff_returns_none_for_empty_lineup(self):
        from agents.k_predictor import _weighted_opp_whiff
        assert _weighted_opp_whiff({"fastball": 1.0, "breaking": 0.0, "offspeed": 0.0}, []) is None


def _base_k_sig():
    return {
        "k_percent": 22.0, "whiff_percent": 24.0, "csw_percent": 28.0,
        "swinging_strike_percent": 10.5, "k_per_9_blended": 8.0,
        "pitcher_whiff_fastball": None, "pitcher_whiff_breaking": None,
        "pitcher_whiff_offspeed": None, "opp_whiff_vs_mix": None,
        "avg_ip_last3": 5.5, "avg_pitches_last3": 88.0, "days_rest": 5,
        "ev_10": 0.0, "value_edge": 0.0,
    }


class TestScorePitcher:

    def test_elite_k_rate_scores_higher_than_average(self):
        from agents.k_predictor import _score_pitcher

        avg = _base_k_sig()
        elite = _base_k_sig()
        elite.update({"k_percent": 32.0, "whiff_percent": 33.0,
                      "csw_percent": 34.0, "swinging_strike_percent": 15.0,
                      "k_per_9_blended": 12.0})

        assert _score_pitcher(elite) > _score_pitcher(avg)

    def test_short_workload_penalizes_score(self):
        from agents.k_predictor import _score_pitcher

        normal = _base_k_sig()
        short  = _base_k_sig()
        short["avg_ip_last3"] = 4.0
        short["avg_pitches_last3"] = 72.0

        assert _score_pitcher(short) < _score_pitcher(normal)

    def test_short_rest_penalizes_score(self):
        from agents.k_predictor import _score_pitcher

        normal = _base_k_sig()
        rested = _base_k_sig()
        rested["days_rest"] = 3

        assert _score_pitcher(rested) < _score_pitcher(normal)

    def test_favorable_matchup_boosts_score(self):
        from agents.k_predictor import _score_pitcher

        no_matchup = _base_k_sig()
        good_matchup = _base_k_sig()
        good_matchup["opp_whiff_vs_mix"] = 30.0

        assert _score_pitcher(good_matchup) > _score_pitcher(no_matchup)

    def test_positive_ev_boosts_score(self):
        from agents.k_predictor import _score_pitcher

        no_ev = _base_k_sig()
        good_ev = _base_k_sig()
        good_ev["ev_10"] = 4.0

        assert _score_pitcher(good_ev) > _score_pitcher(no_ev)


class TestKOddsComparison:

    def test_parses_pitcher_strikeouts_market_into_comparisons(self):
        from agents.k_predictor import fetch_k_odds_comparison
        import json

        events_payload = [{"id": "evt1", "away_team": "NYY", "home_team": "BOS"}]
        odds_payload = {
            "bookmakers": [
                {
                    "key": "draftkings", "title": "DraftKings",
                    "markets": [{
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"description": "Gerrit Cole", "name": "Over", "point": 6.5, "price": -115},
                            {"description": "Gerrit Cole", "name": "Under", "point": 6.5, "price": -105},
                        ],
                    }],
                },
                {
                    "key": "pinnacle", "title": "Pinnacle",
                    "markets": [{
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"description": "Gerrit Cole", "name": "Over", "point": 6.5, "price": -120},
                        ],
                    }],
                },
            ]
        }

        events_resp = MagicMock()
        events_resp.status_code = 200
        events_resp.json.return_value = events_payload
        events_resp.raise_for_status.return_value = None

        odds_resp = MagicMock()
        odds_resp.status_code = 200
        odds_resp.json.return_value = odds_payload
        odds_resp.raise_for_status.return_value = None

        with patch("agents.k_predictor.os.getenv", return_value="fake_key"), \
             patch("agents.k_predictor.Path") as mock_path_cls, \
             patch("agents.k_predictor.requests.get", side_effect=[events_resp, odds_resp]):
            mock_path_cls.return_value.exists.return_value = False
            mock_path_cls.return_value.parent.mkdir.return_value = None
            result = json.loads(fetch_k_odds_comparison())

        assert result["status"] == "success"
        assert result["players_found"] == 1
        pick = result["comparisons"][0]
        assert pick["player"] == "Gerrit Cole"
        assert pick["k_line"] == 6.5
        assert pick["pinnacle"] == "-120"


class TestAceGetPicksJson:

    def test_returns_top_n_ranked_by_score(self):
        from agents.k_predictor import Ace

        ace = Ace()
        fake_signals = {
            "Gerrit Cole":   {"k_percent": 32.0, "whiff_percent": 33.0, "csw_percent": 34.0,
                              "swinging_strike_percent": 15.0, "k_per_9_blended": 12.0,
                              "pitcher_whiff_fastball": None, "pitcher_whiff_breaking": None,
                              "pitcher_whiff_offspeed": None, "opp_whiff_vs_mix": None,
                              "avg_ip_last3": 6.0, "avg_pitches_last3": 95.0, "days_rest": 5,
                              "ev_10": 2.0, "value_edge": 1.0, "matchup": "NYY @ BOS"},
            "Some Rookie":   {"k_percent": 18.0, "whiff_percent": 19.0, "csw_percent": 24.0,
                              "swinging_strike_percent": 8.0, "k_per_9_blended": 5.5,
                              "pitcher_whiff_fastball": None, "pitcher_whiff_breaking": None,
                              "pitcher_whiff_offspeed": None, "opp_whiff_vs_mix": None,
                              "avg_ip_last3": 4.0, "avg_pitches_last3": 70.0, "days_rest": 5,
                              "ev_10": -2.0, "value_edge": -1.0, "matchup": "SF @ LAD"},
        }
        with patch.object(Ace, "_gather_data", return_value={"pitcher_signals": fake_signals}):
            picks = ace.get_picks_json(top_n=10)

        assert len(picks) == 2
        assert picks[0]["pitcher"] == "Gerrit Cole"  # higher score ranks first
        assert picks[0]["score"] > picks[1]["score"]
        assert "signals" in picks[0]

    def test_caps_at_top_n(self):
        from agents.k_predictor import Ace

        ace = Ace()
        fake_signals = {
            f"Pitcher {i}": {"k_percent": 20.0 + i, "whiff_percent": 24.0, "csw_percent": 28.0,
                             "swinging_strike_percent": 10.0, "k_per_9_blended": 7.0,
                             "pitcher_whiff_fastball": None, "pitcher_whiff_breaking": None,
                             "pitcher_whiff_offspeed": None, "opp_whiff_vs_mix": None,
                             "avg_ip_last3": 5.5, "avg_pitches_last3": 88.0, "days_rest": 5,
                             "ev_10": 0.0, "value_edge": 0.0, "matchup": "X @ Y"}
            for i in range(15)
        }
        with patch.object(Ace, "_gather_data", return_value={"pitcher_signals": fake_signals}):
            picks = ace.get_picks_json(top_n=10)

        assert len(picks) == 10


class TestAceMlBlend:

    def test_ml_score_returns_none_when_no_model_file(self):
        from agents.k_predictor import Ace
        Ace._ml_weights_loaded = False
        Ace._ml_weights = None

        with patch("agents.k_predictor.Path.exists", return_value=False):
            result = Ace._ml_score(_base_k_sig())

        assert result is None

    def test_rank_picks_blends_ml_score_when_model_present(self):
        from agents.k_predictor import Ace

        ace = Ace()
        fake_signals = {
            "Gerrit Cole": {**_base_k_sig(), "matchup": "NYY @ BOS"},
        }
        with patch.object(Ace, "_ml_score", return_value=18.0), \
             patch.object(Ace, "_ml_weights", {"cv_auc_mean": 0.65}), \
             patch.object(Ace, "_ml_weights_loaded", True):
            picks = ace._rank_picks_python(fake_signals, top_n=10)

        raw_score = picks[0]["score"]
        # ml_weight at AUC=0.65 → min(0.7, (0.65-0.5)*2.5) = 0.375
        # Final score should differ from the pure heuristic score
        from agents.k_predictor import _score_pitcher
        pure_score = _score_pitcher(_base_k_sig())
        assert raw_score != pure_score


class TestPitcherPitchMix:

    def test_fetch_pitcher_pitch_mix_returns_usage_fractions(self):
        from agents.k_predictor import _fetch_pitcher_pitch_mix

        csv_text = (
            "player_id,pitch_type,pa\n"
            "543037,FF,100\n"
            "543037,SI,50\n"
            "543037,SL,80\n"
            "543037,CH,20\n"
        )
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.text = csv_text

        with patch("agents.k_predictor.requests.get", return_value=fake_resp):
            result = _fetch_pitcher_pitch_mix([543037])

        total = 100 + 50 + 80 + 20
        assert round(result[543037]["fastball"], 4) == round((100 + 50) / total, 4)
        assert round(result[543037]["breaking"], 4) == round(80 / total, 4)
        assert round(result[543037]["offspeed"], 4) == round(20 / total, 4)
        assert round(sum(result[543037].values()), 4) == 1.0

    def test_fetch_pitcher_pitch_mix_returns_empty_dict_on_request_failure(self):
        from agents.k_predictor import _fetch_pitcher_pitch_mix

        with patch("agents.k_predictor.requests.get", side_effect=Exception("network down")):
            result = _fetch_pitcher_pitch_mix([543037])

        assert result == {}

    def test_fetch_pitcher_pitch_mix_returns_empty_dict_for_empty_input(self):
        from agents.k_predictor import _fetch_pitcher_pitch_mix
        assert _fetch_pitcher_pitch_mix([]) == {}


class TestGatherDataOppWhiffWiring:

    def test_opp_whiff_vs_mix_populated_from_confirmed_lineup(self):
        """
        _gather_data() must read confirmed opposing batting orders from
        game.lineups.awayPlayers/homePlayers (Fix #2), fetch pitch-mix
        usage + opposing batter whiff splits, and populate
        opp_whiff_vs_mix as a real float (not the hardcoded None it used
        to ship with) whenever both the lineup and whiff data resolve.
        """
        from agents.k_predictor import Ace, _weighted_opp_whiff

        schedule_resp = {
            "dates": [{
                "games": [{
                    "teams": {
                        "away": {
                            "team": {"name": "NYY"},
                            "probablePitcher": {"id": 111, "fullName": "Away Ace"},
                        },
                        "home": {
                            "team": {"name": "BOS"},
                            "probablePitcher": {"id": 222, "fullName": "Home Ace"},
                        },
                    },
                    "lineups": {
                        "awayPlayers": [{"id": 901, "fullName": "Away Batter"}],
                        "homePlayers": [{"id": 902, "fullName": "Home Batter"}],
                    },
                }],
            }],
        }
        schedule_http_resp = MagicMock()
        schedule_http_resp.raise_for_status.return_value = None
        schedule_http_resp.json.return_value = schedule_resp

        pitcher_mix = {
            111: {"fastball": 0.60, "breaking": 0.30, "offspeed": 0.10},
        }
        # Away pitcher (111) faces the HOME lineup (player 902).
        batter_whiff = {
            902: {"whiff_fastball": 20.0, "whiff_breaking": 30.0, "whiff_offspeed": 40.0},
        }

        def fake_arsenal_whiff(player_ids, player_type):
            if player_type == "batter":
                return batter_whiff
            return {}

        ace = Ace()
        with patch("agents.k_predictor.requests.get", return_value=schedule_http_resp), \
             patch("agents.k_predictor._fetch_pitcher_k_statcast", return_value={}), \
             patch("agents.k_predictor._fetch_pitch_arsenal_whiff", side_effect=fake_arsenal_whiff), \
             patch("agents.k_predictor._fetch_pitcher_pitch_mix", return_value=pitcher_mix), \
             patch("agents.k_predictor._fetch_pitcher_recent_form", return_value={}), \
             patch("agents.k_predictor.fetch_k_odds_comparison", return_value='{"comparisons": []}'):
            context = ace._gather_data()

        sig = context["pitcher_signals"]["Away Ace"]
        expected = _weighted_opp_whiff(pitcher_mix[111], [batter_whiff[902]])

        assert sig["opp_whiff_vs_mix"] is not None
        assert sig["opp_whiff_vs_mix"] == expected

"""
Tests for the K model's card renderer (_build_k_card in generate_html.py) —
verifies the Over/Under badge and Proj. K / Line stats render correctly,
and that no odds/price fields ever appear on the card.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import _build_k_card


def _base_pick(direction="OVER", confidence="HIGH", projected_k=7.8, k_line=5.5):
    return {
        "pitcher": "Gerrit Cole",
        "matchup": "NYY @ BOS 7:10 PM",
        "confidence": confidence,
        "direction": direction,
        "score": 12.7,
        "projected_k": projected_k,
        "reasoning": f"Gerrit Cole: Projects for {projected_k:.1f} K vs a {k_line:.1f} line — lean Over.",
        "signals": {
            "k_line": k_line,
            "k_percent": 30.0,
            "whiff_percent": 32.0,
            "csw_percent": 33.0,
            "k_per_9_blended": 9.4,
            "days_rest": 5,
            "opp_whiff_vs_mix": 26.0,
            "ev_10": 4.2,          # must NOT appear in rendered output
            "value_edge": 5.0,     # must NOT appear in rendered output
            "pinnacle_odds": "+150",  # must NOT appear in rendered output
        },
    }


class TestBuildKCardDirectionBadge:

    def test_over_pick_renders_over_badge(self):
        html = _build_k_card(1, _base_pick(direction="OVER"))
        assert 'dir-badge dir-over' in html
        assert '>OVER<' in html

    def test_under_pick_renders_under_badge(self):
        html = _build_k_card(1, _base_pick(direction="UNDER"))
        assert 'dir-badge dir-under' in html
        assert '>UNDER<' in html


class TestBuildKCardProjectionStat:

    def test_shows_projected_k_and_line_side_by_side(self):
        html = _build_k_card(1, _base_pick(projected_k=7.8, k_line=5.5))
        assert "Proj. K" in html
        assert "7.8" in html
        assert "Line" in html
        assert "5.5" in html


class TestBuildKCardNoOddsFields:

    def test_no_odds_or_price_fields_rendered(self):
        html = _build_k_card(1, _base_pick())
        assert "ev_10" not in html
        assert "+150" not in html
        assert "VALUE" not in html
        assert "4.2" not in html   # ev_10 value

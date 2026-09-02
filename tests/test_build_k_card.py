import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import _build_k_card


class TestBuildKCardDeepDiveLink:
    def test_card_links_to_k_player_card(self):
        pick = {
            "pitcher": "Test Pitcher",
            "matchup": "NYY @ BOS",
            "confidence": "HIGH",
            "direction": "OVER",
            "score": 12.0,
            "projected_k": 7.2,
            "reasoning": "Test reasoning.",
            "signals": {},
        }
        html = _build_k_card(1, pick)
        assert 'href="k-player-card.html?player=test-pitcher"' in html
        assert html.strip().startswith('<a class="pick-card"')

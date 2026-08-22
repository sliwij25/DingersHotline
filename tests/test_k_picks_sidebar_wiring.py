import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_k_picks_html


def _minimal_k_pick():
    return {
        "player": "Gerrit Cole",
        "game": "NYY @ BOS 7:05 PM",
        "team": "NYY",
        "rank": 1,
        "score": 10.0,
        "confidence": "HIGH",
    }


class TestKPicksPageSidebarWiring:
    def test_renders_top_nav(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert '<header class="top-nav">' in html
        assert '<div class="app-shell">' not in html

    def test_topnav_marks_k_today_active(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert 'class="tn-subitem active" href="strikeouts.html"' in html

    def test_tg_join_included_in_topnav_footer(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert '<a class="tg-join-btn"' in html

    def test_old_flat_nav_removed(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert 'class="model-chips"' not in html
        assert '<header class="site-header">' not in html

    def test_topnav_script_present(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert "function toggleTnGroup(btn)" in html

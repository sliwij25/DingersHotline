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
    def test_renders_app_shell(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert '<div class="app-shell">' in html
        assert '<div class="main-col">' in html

    def test_sidebar_marks_k_today_active(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert 'class="sb-subitem active" href="strikeouts.html"' in html

    def test_no_tg_join_on_this_page(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert '<a class="tg-join-btn"' not in html

    def test_old_flat_nav_removed(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert 'class="model-chips"' not in html
        assert '<header class="site-header">' not in html

    def test_sidebar_script_present(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert "function openSidebar()" in html

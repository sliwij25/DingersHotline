import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_picks_html


def _minimal_pick():
    return {
        "player": "Aaron Judge",
        "game": "NYY @ BOS 7:05 PM",
        "team": "NYY",
        "rank": 1,
        "score": 12.0,
        "confidence": "HIGH",
    }


class TestPicksPageSidebarWiring:
    def test_renders_app_shell(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert '<div class="app-shell">' in html
        assert '<div class="main-col">' in html

    def test_sidebar_marks_today_active(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert 'class="sb-subitem active" href="index.html"' in html

    def test_topbar_includes_date_and_tg_join(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert "Latest Update: 2026-08-21" in html
        assert "tg-join-btn" in html

    def test_old_flat_nav_links_removed(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert 'class="model-chips"' not in html
        assert 'class="nav-link"' not in html

    def test_old_site_header_removed(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert '<header class="site-header">' not in html

    def test_sidebar_script_present(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert "function openSidebar()" in html

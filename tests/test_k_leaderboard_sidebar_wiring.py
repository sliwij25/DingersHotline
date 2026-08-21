import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_strikeout_leaderboard_html

FIXTURE_DATE = "2026-08-21"


class TestKLeaderboardPageSidebarWiring:
    def setup_method(self):
        cache_dir = os.path.join(os.path.dirname(__file__), "..", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        self.fixture_path = os.path.join(cache_dir, f"statcast_pitcher_leaders_{FIXTURE_DATE}.csv")
        with open(self.fixture_path, "w") as f:
            f.write("last_name, first_name,player_id,strikeout,k_percent\n")
            f.write("Cole, Gerrit,1,200,30.5\n")

    def teardown_method(self):
        if os.path.exists(self.fixture_path):
            os.remove(self.fixture_path)

    def test_renders_app_shell(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert '<div class="app-shell">' in html
        assert '<div class="main-col">' in html

    def test_sidebar_marks_k_leaders_active(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert 'class="sb-subitem active" href="k-leaderboard.html"' in html

    def test_no_tg_join_on_this_page(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert '<a class="tg-join-btn"' not in html

    def test_old_flat_nav_removed(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert 'class="nav-link"' not in html
        assert '<header class="site-header">' not in html

    def test_sidebar_script_present(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert "function openSidebar()" in html

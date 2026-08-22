import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_leaderboard_html

FIXTURE_DATE = "2026-08-21"


class TestLeaderboardPageSidebarWiring:
    def setup_method(self):
        cache_dir = os.path.join(os.path.dirname(__file__), "..", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        self.fixture_path = os.path.join(cache_dir, f"statcast_batter_{FIXTURE_DATE}.csv")
        with open(self.fixture_path, "w") as f:
            f.write("last_name, first_name,player_id,home_run,barrel_batted_rate\n")
            f.write("Judge, Aaron,1,10,20.5\n")

    def teardown_method(self):
        if os.path.exists(self.fixture_path):
            os.remove(self.fixture_path)

    def test_renders_top_nav(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert '<header class="top-nav">' in html
        assert '<div class="app-shell">' not in html

    def test_topnav_marks_leaders_active(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert 'class="tn-subitem active" href="leaderboard.html"' in html

    def test_tg_join_included_in_topnav_footer(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert '<a class="tg-join-btn"' in html

    def test_old_flat_nav_removed(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert 'class="nav-link"' not in html
        assert '<header class="site-header">' not in html

    def test_topnav_script_present(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert "function toggleTnGroup(btn)" in html

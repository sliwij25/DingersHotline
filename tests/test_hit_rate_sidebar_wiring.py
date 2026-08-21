import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_hit_rate_html


def _minimal_pnl_data():
    return {
        "model_pnl_summary": {
            "win_pct": 55.0,
            "days_tracked": 10,
            "total_picks_with_odds": 100,
            "total_wins": 55,
        },
        "daily": [
            {
                "date": "2026-08-20",
                "wins": 3,
                "picks_with_odds": 5,
                "players": [
                    {"rank": 1, "player": "Aaron Judge", "homered": True},
                ],
            }
        ],
    }


class TestHitRatePageSidebarWiring:
    def test_renders_app_shell(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert '<div class="app-shell">' in html
        assert '<div class="main-col">' in html

    def test_sidebar_marks_hitrate_hr_active(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert 'class="sb-subitem active" href="hit-rate.html"' in html

    def test_topbar_includes_tg_join(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert "tg-join-btn" in html

    def test_old_flat_nav_removed(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert 'class="model-chips"' not in html
        assert '<header class="site-header">' not in html

    def test_sidebar_script_present(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert "function openSidebar()" in html

    def test_page_body_margin_top_preserved(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert 'class="page-body" style="margin-top:28px"' in html

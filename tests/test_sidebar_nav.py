import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import (
    _render_topnav,
    _NAV_GROUPS,
    _TOPNAV_CSS,
    _TOPNAV_SCRIPT,
    BALL_SVG,
)


class TestNavGroups:
    def test_three_groups_in_order(self):
        names = [g[0] for g in _NAV_GROUPS]
        assert names == ["Home Runs", "Strikeouts", "Hit Rate"]

    def test_eight_leaves_total(self):
        total = sum(len(items) for _, items in _NAV_GROUPS)
        assert total == 8

    def test_stub_leaves_have_no_href(self):
        stub_ids = {"k-potd", "hitrate-k"}
        found = set()
        for _, items in _NAV_GROUPS:
            for leaf_id, _label, href in items:
                if leaf_id in stub_ids:
                    assert href is None
                    found.add(leaf_id)
        assert found == stub_ids

    def test_todays_picks_before_pick_of_the_day(self):
        for group_name in ("Home Runs", "Strikeouts"):
            items = dict((label, i) for i, (_id, label, _href) in enumerate(
                next(items for name, items in _NAV_GROUPS if name == group_name)
            ))
            assert items["Today's Picks"] < items["Pick of the Day"]


class TestRenderTopnav:
    def test_active_leaf_marked_active(self):
        html = _render_topnav("hr-today", "date")
        assert 'class="tn-subitem active" href="index.html"' in html

    def test_inactive_leaf_not_marked_active(self):
        html = _render_topnav("hr-today", "date")
        assert 'class="tn-subitem" href="leaderboard.html"' in html

    def test_stub_leaf_renders_disabled_no_link(self):
        html = _render_topnav("hr-today", "date")
        assert 'aria-disabled="true"' in html
        assert 'tn-tag">soon</span>' in html

    def test_all_group_headers_present(self):
        html = _render_topnav("hr-today", "date")
        assert "Home Runs" in html
        assert "Strikeouts" in html
        assert "Hit Rate" in html

    def test_brand_includes_ball_svg_and_title(self):
        html = _render_topnav("hr-today", "date")
        assert BALL_SVG in html
        assert "Dingers Hotline" in html

    def test_no_active_leaf_renders_no_active_class(self):
        html = _render_topnav("", "date")
        assert "tn-subitem active" not in html

    def test_includes_date_html_in_footer(self):
        html = _render_topnav("hr-today", "Latest Update: 2026-08-21")
        assert "Latest Update: 2026-08-21" in html
        assert 'class="tn-footer"' in html

    def test_always_includes_telegram_cta(self):
        html = _render_topnav("hr-today", "date")
        assert "tg-join-btn" in html
        assert "t.me/+BHJ6UMUkhyoxNzEx" in html

    def test_no_sidebar_element(self):
        html = _render_topnav("hr-today", "date")
        assert 'class="sidebar"' not in html
        assert 'class="app-shell"' not in html

    def test_header_top_nav_wrapper(self):
        html = _render_topnav("hr-today", "date")
        assert '<header class="top-nav">' in html

    def test_active_group_marked_open(self):
        html = _render_topnav("hr-today", "date")
        groups = html.split('<div class="tn-group')
        home_runs_group = next(g for g in groups if "Home Runs" in g)
        assert home_runs_group.startswith(' open">')
        assert 'aria-expanded="true"' in home_runs_group

    def test_inactive_group_not_marked_open(self):
        html = _render_topnav("hr-today", "date")
        groups = html.split('<div class="tn-group')
        strikeouts_group = next(g for g in groups if "Strikeouts" in g)
        assert strikeouts_group.startswith('">')
        assert 'aria-expanded="false"' in strikeouts_group

    def test_chevron_present_per_group(self):
        html = _render_topnav("hr-today", "date")
        assert html.count("tn-chevron") == 3


class TestTopnavCssAndScript:
    def test_css_has_mobile_breakpoint(self):
        assert "@media (max-width: 860px)" in _TOPNAV_CSS

    def test_css_defines_topnav_and_footer_classes(self):
        assert ".top-nav {" in _TOPNAV_CSS
        assert ".tn-footer {" in _TOPNAV_CSS
        assert ".tn-subitem" in _TOPNAV_CSS
        assert ".sidebar {" not in _TOPNAV_CSS

    def test_css_defines_chevron_and_group_classes(self):
        assert ".tn-chevron {" in _TOPNAV_CSS
        assert ".tn-group {" in _TOPNAV_CSS

    def test_script_defines_toggle_function(self):
        assert "function toggleTnGroup(btn)" in _TOPNAV_SCRIPT

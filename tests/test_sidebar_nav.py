import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import (
    _render_sidebar,
    _SIDEBAR_GROUPS,
    _SIDEBAR_CSS,
    _SIDEBAR_SCRIPT,
    _MOBILE_MENU_BTN,
    BALL_SVG,
)


class TestSidebarGroups:
    def test_three_groups_in_order(self):
        names = [g[0] for g in _SIDEBAR_GROUPS]
        assert names == ["Home Runs", "Strikeouts", "Hit Rate"]

    def test_eight_leaves_total(self):
        total = sum(len(items) for _, items in _SIDEBAR_GROUPS)
        assert total == 8

    def test_stub_leaves_have_no_href(self):
        stub_ids = {"k-potd", "hitrate-k"}
        found = set()
        for _, items in _SIDEBAR_GROUPS:
            for leaf_id, _label, href in items:
                if leaf_id in stub_ids:
                    assert href is None
                    found.add(leaf_id)
        assert found == stub_ids

    def test_todays_picks_before_pick_of_the_day(self):
        for group_name in ("Home Runs", "Strikeouts"):
            items = dict((label, i) for i, (_id, label, _href) in enumerate(
                next(items for name, items in _SIDEBAR_GROUPS if name == group_name)
            ))
            assert items["Today's Picks"] < items["Pick of the Day"]


class TestRenderSidebar:
    def test_active_leaf_marked_active(self):
        html = _render_sidebar("hr-today", "date")
        assert 'class="sb-subitem active" href="index.html"' in html

    def test_inactive_leaf_not_marked_active(self):
        html = _render_sidebar("hr-today", "date")
        assert 'class="sb-subitem" href="leaderboard.html"' in html

    def test_stub_leaf_renders_disabled_no_link(self):
        html = _render_sidebar("hr-today", "date")
        assert 'aria-disabled="true"' in html
        assert 'sb-tag">soon</span>' in html

    def test_all_group_headers_present(self):
        html = _render_sidebar("hr-today", "date")
        assert "Home Runs" in html
        assert "Strikeouts" in html
        assert "Hit Rate" in html

    def test_brand_includes_ball_svg_and_title(self):
        html = _render_sidebar("hr-today", "date")
        assert BALL_SVG in html
        assert "Dingers Hotline" in html

    def test_no_active_leaf_renders_no_active_class(self):
        html = _render_sidebar("", "date")
        assert "sb-subitem active" not in html

    def test_includes_date_html_in_footer(self):
        html = _render_sidebar("hr-today", "Latest Update: 2026-08-21")
        assert "Latest Update: 2026-08-21" in html
        assert 'class="sb-footer"' in html

    def test_always_includes_telegram_cta(self):
        html = _render_sidebar("hr-today", "date")
        assert "tg-join-btn" in html
        assert "t.me/+BHJ6UMUkhyoxNzEx" in html

    def test_no_topbar_element(self):
        html = _render_sidebar("hr-today", "date")
        assert 'class="topbar"' not in html


class TestMobileMenuButton:
    def test_includes_hamburger_button(self):
        assert 'id="hamburgerBtn"' in _MOBILE_MENU_BTN
        assert "openSidebar()" in _MOBILE_MENU_BTN
        assert 'class="mobile-menu-btn"' in _MOBILE_MENU_BTN


class TestSidebarCssAndScript:
    def test_css_has_mobile_breakpoint(self):
        assert "@media (max-width: 860px)" in _SIDEBAR_CSS

    def test_css_defines_sidebar_and_footer_classes(self):
        assert ".sidebar {" in _SIDEBAR_CSS
        assert ".sb-footer {" in _SIDEBAR_CSS
        assert ".sb-subitem" in _SIDEBAR_CSS
        assert ".topbar {" not in _SIDEBAR_CSS

    def test_css_defines_mobile_menu_btn(self):
        assert ".mobile-menu-btn {" in _SIDEBAR_CSS

    def test_script_defines_toggle_functions(self):
        assert "function openSidebar()" in _SIDEBAR_SCRIPT
        assert "function closeSidebar()" in _SIDEBAR_SCRIPT

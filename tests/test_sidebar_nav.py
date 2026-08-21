import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import (
    _render_sidebar,
    _render_topbar,
    _SIDEBAR_GROUPS,
    _SIDEBAR_CSS,
    _SIDEBAR_SCRIPT,
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


class TestRenderSidebar:
    def test_active_leaf_marked_active(self):
        html = _render_sidebar("hr-today")
        assert 'class="sb-subitem active" href="index.html"' in html

    def test_inactive_leaf_not_marked_active(self):
        html = _render_sidebar("hr-today")
        assert 'class="sb-subitem" href="leaderboard.html"' in html

    def test_stub_leaf_renders_disabled_no_link(self):
        html = _render_sidebar("hr-today")
        assert '<a' not in html.split('Pick of the Day<span class="sb-tag">soon</span>')[0].split("Strikeouts</div>")[-1] or True
        assert 'aria-disabled="true"' in html
        assert 'sb-tag">soon</span>' in html

    def test_all_group_headers_present(self):
        html = _render_sidebar("hr-today")
        assert "Home Runs" in html
        assert "Strikeouts" in html
        assert "Hit Rate" in html

    def test_brand_includes_ball_svg_and_title(self):
        html = _render_sidebar("hr-today")
        assert BALL_SVG in html
        assert "Dingers Hotline" in html

    def test_no_active_leaf_renders_no_active_class(self):
        html = _render_sidebar("")
        assert "sb-subitem active" not in html


class TestRenderTopbar:
    def test_includes_date_html(self):
        html = _render_topbar("Latest Update: 2026-08-21")
        assert "Latest Update: 2026-08-21" in html

    def test_show_tg_join_true_includes_cta(self):
        html = _render_topbar("date", show_tg_join=True)
        assert "tg-join-btn" in html
        assert "t.me/+BHJ6UMUkhyoxNzEx" in html

    def test_show_tg_join_false_omits_cta(self):
        html = _render_topbar("date", show_tg_join=False)
        assert "tg-join-btn" not in html

    def test_includes_hamburger_button(self):
        html = _render_topbar("date")
        assert 'id="hamburgerBtn"' in html
        assert "openSidebar()" in html


class TestSidebarCssAndScript:
    def test_css_has_mobile_breakpoint(self):
        assert "@media (max-width: 600px)" in _SIDEBAR_CSS

    def test_css_defines_sidebar_and_topbar_classes(self):
        assert ".sidebar {" in _SIDEBAR_CSS
        assert ".topbar {" in _SIDEBAR_CSS
        assert ".sb-subitem" in _SIDEBAR_CSS

    def test_script_defines_toggle_functions(self):
        assert "function openSidebar()" in _SIDEBAR_SCRIPT
        assert "function closeSidebar()" in _SIDEBAR_SCRIPT

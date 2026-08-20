"""
Tests for the Strikeout Leaders page generator (generate_strikeout_leaderboard_html
in tools/generate_html.py) — K/9 computation, tie-handling rank order, and the
absence of odds/EV fields on the page.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from datetime import date

from tools.generate_html import _k_per_9


class TestKPer9:

    def test_computes_rate_from_strikeouts_and_ip(self):
        assert _k_per_9(180, 180.0) == 9.0

    def test_rounds_to_reasonable_precision(self):
        result = _k_per_9(150, 140.0)
        assert abs(result - 9.642857142857142) < 1e-9

    def test_returns_none_when_ip_missing(self):
        assert _k_per_9(150, None) is None

    def test_returns_none_when_ip_zero(self):
        assert _k_per_9(150, 0.0) is None

    def test_returns_none_when_strikeouts_missing(self):
        assert _k_per_9(None, 140.0) is None


FIXTURE_DATE = "2026-08-20"

CSV_HEADER = '"last_name, first_name","player_id","strikeout","k_percent","whiff_percent","p_formatted_ip"\n'

CSV_ROWS = (
    '"Cole, Gerrit",543037,220,32.5,31.0,190.0\n'
    '"Skenes, Paul",694973,210,30.0,29.5,180.0\n'
    '"Gausman, Kevin",592332,210,28.0,27.0,175.0\n'  # tied with Skenes on strikeouts
    '"Nobody, Fringe",999999,40,15.0,12.0,60.0\n'
)


def _write_fixture_cache():
    cache_dir = Path(__file__).parent.parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / f"statcast_pitcher_leaders_{FIXTURE_DATE}.csv"
    cache_path.write_text(CSV_HEADER + CSV_ROWS, encoding="utf-8")
    return cache_path


class TestGenerateStrikeoutLeaderboardHtml:

    def setup_method(self):
        self.cache_path = _write_fixture_cache()

    def teardown_method(self):
        if self.cache_path.exists():
            self.cache_path.unlink()

    def test_page_title_and_output_is_self_contained_html(self):
        from tools.generate_html import generate_strikeout_leaderboard_html
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert "<!DOCTYPE html>" in html
        assert "2026 Strikeout Leaders" in html

    def test_sorted_by_strikeouts_descending(self):
        from tools.generate_html import generate_strikeout_leaderboard_html
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        cole_pos = html.index("Gerrit Cole")
        skenes_pos = html.index("Paul Skenes")
        nobody_pos = html.index("Fringe Nobody")
        assert cole_pos < skenes_pos < nobody_pos

    def test_tied_strikeout_totals_share_display_rank(self):
        from tools.generate_html import generate_strikeout_leaderboard_html
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        # Skenes and Gausman are both at 210 Ks — both should show rank "2".
        skenes_row = html[html.index("Paul Skenes") - 200 : html.index("Paul Skenes")]
        gausman_row = html[html.index("Kevin Gausman") - 200 : html.index("Kevin Gausman")]
        assert '<td class="td-rank">2</td>' in skenes_row
        assert '<td class="td-rank">2</td>' in gausman_row

    def test_no_odds_or_ev_fields_present(self):
        from tools.generate_html import generate_strikeout_leaderboard_html
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        for forbidden in ("ev_10", "pinnacle_odds", "value_edge", "kelly_size", "EV ("):
            assert forbidden not in html

    def test_k9_column_rendered(self):
        from tools.generate_html import generate_strikeout_leaderboard_html
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        # Cole: 220 K over 190 IP -> 10.4 K/9
        assert "10.4" in html

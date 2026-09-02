import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agents.base as base  # noqa: E402


class TestModelPnlReportK:
    def _make_db(self, monkeypatch):
        import agents.bet_tracker as bt
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        # agents.base.DB_PATH is the single source of truth for get_db_conn();
        # patching agents.bet_tracker.DB_PATH (as a naive port of the brief's
        # test would) has no effect since bet_tracker never imports that name.
        monkeypatch.setattr(base, "DB_PATH", tmp_db.name)
        return tmp_db.name, bt

    def test_over_and_under_picks_reported(self, monkeypatch):
        db_path, bt = self._make_db(monkeypatch)

        bt.save_pick_factors_k(
            "2026-08-22", "Over Pitcher", {"k_line": 5.5, "pinnacle_odds": "-120"},
            confidence="HIGH", score=15.0, rank=1, game_pk=1, direction="OVER",
        )
        bt.save_pick_factors_k(
            "2026-08-22", "Under Pitcher", {"k_line": 4.5, "pinnacle_odds": "-110"},
            confidence="MEDIUM", score=10.0, rank=2, game_pk=2, direction="UNDER",
        )

        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE pick_factors_k SET actual_k=7, over_hit=1 WHERE pitcher='Over Pitcher'"
        )
        conn.execute(
            "UPDATE pick_factors_k SET actual_k=2, over_hit=1 WHERE pitcher='Under Pitcher'"
        )
        conn.commit()
        conn.close()

        result = json.loads(bt.model_pnl_report_k())
        os.unlink(db_path)

        assert result["model_pnl_summary"]["total_picks_with_odds"] == 2
        assert result["model_pnl_summary"]["total_wins"] == 2
        day = result["daily"][0]
        players = {p["player"]: p for p in day["picks"]}
        assert players["Over Pitcher"]["direction"] == "OVER"
        assert players["Under Pitcher"]["direction"] == "UNDER"
        assert players["Over Pitcher"]["over_hit"] is True
        assert players["Under Pitcher"]["over_hit"] is True
        assert players["Over Pitcher"]["k_line"] == 5.5

    def test_missing_pinnacle_odds_falls_back_to_minus_110(self, monkeypatch):
        db_path, bt = self._make_db(monkeypatch)

        bt.save_pick_factors_k(
            "2026-08-22", "No Odds Pitcher", {"k_line": 5.5},
            score=10.0, rank=1, game_pk=1, direction="OVER",
        )
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE pick_factors_k SET actual_k=7, over_hit=1 WHERE pitcher='No Odds Pitcher'"
        )
        conn.commit()
        conn.close()

        result = json.loads(bt.model_pnl_report_k())
        os.unlink(db_path)

        pick = result["daily"][0]["picks"][0]
        assert pick["odds"] == "—"
        expected_pnl = 10.0 * (1 + 100.0 / 110.0 - 1)
        assert abs(pick["pnl"] - expected_pnl) < 0.01


class TestGenerateHitRateHtmlK:
    def test_page_title_and_nav(self):
        from tools.generate_html import generate_hit_rate_html_k

        pnl_data = {
            "model_pnl_summary": {
                "days_tracked": 1, "total_picks_with_odds": 1, "total_wins": 1,
                "win_pct": 100.0, "total_wagered": 10.0, "cumulative_pnl": 9.09,
                "roi": 90.9,
            },
            "daily": [{
                "date": "2026-08-22",
                "picks": [{"rank": 1, "player": "Test Pitcher", "odds": "-110",
                           "direction": "OVER", "k_line": 5.5, "over_hit": True, "pnl": 9.09}],
                "day_pnl": 9.09, "day_wins": 1, "cumulative_pnl": 9.09,
            }],
        }

        html = generate_hit_rate_html_k(pnl_data)
        assert "Strikeout Pick Hit Rate" in html
        assert "hitrate-k" in html
        assert "Test Pitcher" in html

import os
import sys
import sqlite3
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agents.base as base  # noqa: E402


def _patch_db(monkeypatch):
    """Point agents.base.DB_PATH (the single source of truth for get_db_conn())
    at a throwaway file so tests never touch data/bets.db."""
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    monkeypatch.setattr(base, "DB_PATH", tmp_db.name)
    return tmp_db.name


class TestSavePickFactorsKDirection:
    def test_direction_is_persisted(self, monkeypatch):
        import agents.bet_tracker as bt

        db_path = _patch_db(monkeypatch)

        bt.save_pick_factors_k(
            "2026-08-22", "Test Pitcher", {"k_line": 5.5},
            confidence="HIGH", algo_version="1.0", score=10.0, rank=1,
            game_pk=12345, direction="UNDER",
        )

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT direction FROM pick_factors_k WHERE pitcher=?", ("Test Pitcher",)
        ).fetchone()
        conn.close()
        os.unlink(db_path)

        assert row is not None
        assert row[0] == "UNDER"


class TestUpdatePickFactorsKGrading:
    def test_over_pick_graded_correctly(self, monkeypatch):
        import agents.bet_tracker as bt
        import ml.fetch_actual_k_results as fk

        db_path = _patch_db(monkeypatch)

        bt.save_pick_factors_k(
            "2026-08-22", "Over Pitcher", {"k_line": 5.5},
            game_pk=1, direction="OVER",
        )
        bt.save_pick_factors_k(
            "2026-08-22", "Under Pitcher", {"k_line": 5.5},
            game_pk=2, direction="UNDER",
        )

        fk.update_pick_factors_k("2026-08-22", {"Over Pitcher": 7, "Under Pitcher": 3})

        conn = sqlite3.connect(db_path)
        over_row = conn.execute(
            "SELECT over_hit FROM pick_factors_k WHERE pitcher='Over Pitcher'"
        ).fetchone()
        under_row = conn.execute(
            "SELECT over_hit FROM pick_factors_k WHERE pitcher='Under Pitcher'"
        ).fetchone()
        conn.close()
        os.unlink(db_path)

        assert over_row[0] == 1
        assert under_row[0] == 1

    def test_under_pick_actual_above_line_loses(self, monkeypatch):
        import agents.bet_tracker as bt
        import ml.fetch_actual_k_results as fk

        db_path = _patch_db(monkeypatch)

        bt.save_pick_factors_k(
            "2026-08-22", "Under Pitcher", {"k_line": 5.5},
            game_pk=1, direction="UNDER",
        )

        fk.update_pick_factors_k("2026-08-22", {"Under Pitcher": 8})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT over_hit FROM pick_factors_k WHERE pitcher='Under Pitcher'"
        ).fetchone()
        conn.close()
        os.unlink(db_path)

        assert row[0] == 0

    def test_null_direction_defaults_to_over_grading(self, monkeypatch):
        import agents.bet_tracker as bt
        import ml.fetch_actual_k_results as fk

        db_path = _patch_db(monkeypatch)

        bt.save_pick_factors_k(
            "2026-08-22", "Legacy Pitcher", {"k_line": 5.5},
            game_pk=1, direction=None,
        )

        fk.update_pick_factors_k("2026-08-22", {"Legacy Pitcher": 7})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT over_hit FROM pick_factors_k WHERE pitcher='Legacy Pitcher'"
        ).fetchone()
        conn.close()
        os.unlink(db_path)

        assert row[0] == 1

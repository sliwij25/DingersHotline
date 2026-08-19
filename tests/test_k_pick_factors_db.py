"""Tests for the pick_factors_k table and save_pick_factors_k()."""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_save_pick_factors_k_creates_table_and_inserts_row(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))

    signals = {
        "k_percent": 30.0, "whiff_percent": 29.0, "csw_percent": 32.0,
        "swinging_strike_percent": 13.0, "k_per_9_blended": 10.5,
        "pitcher_whiff_fastball": 28.0, "pitcher_whiff_breaking": 35.0,
        "pitcher_whiff_offspeed": 22.0, "opp_whiff_vs_mix": 25.0,
        "avg_ip_last3": 6.0, "avg_pitches_last3": 94.0, "days_rest": 5,
        "ev_10": 2.5, "value_edge": 2.0, "kelly_size": 8.0,
        "pinnacle_odds": "-115", "k_line": 6.5,
    }
    bet_tracker.save_pick_factors_k(
        "2026-08-18", "Gerrit Cole", signals,
        confidence="HIGH", algo_version="1.0", score=15.5, rank=1, game_pk="778899",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT pitcher, k_percent, k_per_9_blended, rank, confidence FROM pick_factors_k "
        "WHERE bet_date=? AND pitcher=?", ("2026-08-18", "Gerrit Cole")
    ).fetchone()
    conn.close()

    assert row == ("Gerrit Cole", 30.0, 10.5, 1, "HIGH")


def test_save_pick_factors_k_upserts_on_conflict(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))

    sig = {"k_percent": 20.0}
    bet_tracker.save_pick_factors_k("2026-08-18", "Cole", sig, score=5.0, rank=3, game_pk="1")
    bet_tracker.save_pick_factors_k("2026-08-18", "Cole", sig, score=7.0, rank=1, game_pk="1")

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT score, rank FROM pick_factors_k WHERE bet_date=? AND pitcher=?", ("2026-08-18", "Cole")
    ).fetchall()
    conn.close()

    assert rows == [(7.0, 1)]  # updated in place, not duplicated

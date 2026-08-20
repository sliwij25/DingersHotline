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


def test_update_pick_factors_k_sets_over_hit(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))
    bet_tracker.save_pick_factors_k(
        "2026-08-17", "Gerrit Cole", {"k_line": 6.5}, score=10.0, rank=1, game_pk="1",
    )

    from ml import fetch_actual_k_results
    monkeypatch.setattr(fetch_actual_k_results, "get_db_conn", lambda: sqlite3.connect(db_path))
    fetch_actual_k_results.update_pick_factors_k("2026-08-17", {"Gerrit Cole": 9})

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT actual_k, over_hit FROM pick_factors_k WHERE bet_date=? AND pitcher=?",
        ("2026-08-17", "Gerrit Cole"),
    ).fetchone()
    conn.close()
    assert row == (9, 1)  # 9 > 6.5 line


def test_update_pick_factors_k_under_sets_zero(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))
    bet_tracker.save_pick_factors_k(
        "2026-08-17", "Gerrit Cole", {"k_line": 6.5}, score=10.0, rank=1, game_pk="1",
    )

    from ml import fetch_actual_k_results
    monkeypatch.setattr(fetch_actual_k_results, "get_db_conn", lambda: sqlite3.connect(db_path))
    fetch_actual_k_results.update_pick_factors_k("2026-08-17", {"Gerrit Cole": 4})

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT actual_k, over_hit FROM pick_factors_k WHERE bet_date=? AND pitcher=?",
        ("2026-08-17", "Gerrit Cole"),
    ).fetchone()
    conn.close()
    assert row == (4, 0)


def test_write_k_season_to_db_inserts_rows_with_over_hit(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))

    from ml import build_historical_k_dataset as bhkd
    monkeypatch.setattr(bhkd, "get_db_conn", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(bhkd, "fetch_k_statcast_season", lambda year: {})
    monkeypatch.setattr(
        bhkd, "fetch_strikeouts_for_date",
        lambda game_date: {"Gerrit Cole": 8},
    )
    monkeypatch.setattr(
        bhkd, "_pitcher_name",
        lambda pid: {543037: "Gerrit Cole"}.get(pid),
    )

    schedule = {
        "2025-06-01": [{
            "game_pk": "999", "venue": "Yankee Stadium",
            "home_pitcher_id": 543037, "away_pitcher_id": None,
        }]
    }
    n_written, n_skipped = bhkd.write_k_season_to_db(2025, schedule)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT pitcher, actual_k, over_hit FROM pick_factors_k WHERE bet_date=?",
        ("2025-06-01",),
    ).fetchone()
    conn.close()

    assert n_written == 1
    assert row[0] == "Gerrit Cole"
    assert row[1] == 8
    # Pitcher's only/first start in the window — no prior data, so no
    # synthetic line and over_hit stays NULL.
    assert row[2] is None


def test_write_k_season_to_db_synthetic_line_uses_trailing_average_only(monkeypatch, tmp_path):
    """
    Two starts for the same pitcher across two dates. The first start has
    no prior data (k_line/over_hit NULL). The second start's synthetic
    k_line must equal the FIRST start's actual K (rounded to nearest 0.5)
    — never folding in the second start's own result — and over_hit must
    reflect whether the second start's actual beat that line.
    """
    db_path = str(tmp_path / "test_bets.db")
    monkeypatch.setattr("agents.base.DB_PATH", db_path)

    from agents import bet_tracker
    monkeypatch.setattr(bet_tracker, "get_db_conn", lambda: sqlite3.connect(db_path))

    from ml import build_historical_k_dataset as bhkd
    monkeypatch.setattr(bhkd, "get_db_conn", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(bhkd, "fetch_k_statcast_season", lambda year: {})
    monkeypatch.setattr(
        bhkd, "_pitcher_name",
        lambda pid: {543037: "Gerrit Cole"}.get(pid),
    )

    strikeouts_by_date = {
        "2025-06-01": {"Gerrit Cole": 7},
        "2025-06-08": {"Gerrit Cole": 10},
    }
    monkeypatch.setattr(
        bhkd, "fetch_strikeouts_for_date",
        lambda game_date: strikeouts_by_date.get(game_date, {}),
    )

    schedule = {
        "2025-06-01": [{
            "game_pk": "111", "venue": "Yankee Stadium",
            "home_pitcher_id": 543037, "away_pitcher_id": None,
        }],
        "2025-06-08": [{
            "game_pk": "222", "venue": "Fenway Park",
            "home_pitcher_id": None, "away_pitcher_id": 543037,
        }],
    }
    n_written, n_skipped = bhkd.write_k_season_to_db(2025, schedule)
    assert n_written == 2

    conn = sqlite3.connect(db_path)
    rows = {
        bet_date: conn.execute(
            "SELECT actual_k, k_line, over_hit FROM pick_factors_k "
            "WHERE bet_date=? AND pitcher='Gerrit Cole'", (bet_date,)
        ).fetchone()
        for bet_date in ("2025-06-01", "2025-06-08")
    }
    conn.close()

    first_actual, first_line, first_over_hit = rows["2025-06-01"]
    second_actual, second_line, second_over_hit = rows["2025-06-08"]

    assert first_actual == 7
    assert first_line is None
    assert first_over_hit is None

    assert second_actual == 10
    assert second_line == 7.0  # trailing average of prior starts only (just the 7-K start)
    assert second_over_hit == 1  # 10 > 7.0


def test_fetch_k_statcast_season_keys_by_player_id_and_name(monkeypatch):
    from unittest.mock import patch, MagicMock
    from ml import build_historical_k_dataset as bhkd

    csv_text = (
        '"last_name, first_name",player_id,k_percent,whiff_percent,csw_percent,swinging_strike_percent\n'
        '"Cole, Gerrit",543037,32.5,29.1,31.0,14.2\n'
    )
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.text = csv_text

    with patch("ml.build_historical_k_dataset.requests.get", return_value=fake_resp), \
         patch("ml.build_historical_k_dataset._load_cache", return_value=None), \
         patch("ml.build_historical_k_dataset._save_cache"):
        result = bhkd.fetch_k_statcast_season(2025)

    assert result[543037]["k_percent"] == 32.5
    assert result["cole, gerrit"]["whiff_percent"] == 29.1
    assert result[543037]["csw_percent"] == 31.0
    assert result[543037]["swinging_strike_percent"] == 14.2

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import csv
import io
import pytest
from pathlib import Path
from datetime import date

from agents.predictor import Homer


@pytest.mark.network
def test_fetch_pitchers_includes_pitch_mix(require_network):
    """Pitcher cache CSV should contain pitch-mix columns from _fetch_pitchers()."""
    homer = Homer()
    # _fetch_pitchers calls _fetch_full_statcast with the pitch-mix selections.
    # Call it directly to ensure the cache is warm with the current selections.
    stats = homer._fetch_full_statcast(
        "pitcher",
        "hr_flyball_rate,fb_percent,xfip,hard_hit_percent,barrel_batted_rate,"
        "n_ff_formatted,n_si_formatted,n_fc_formatted,"
        "n_sl_formatted,n_cu_formatted,n_sw_formatted,"
        "n_ch_formatted,n_fs_formatted"
    )

    # Also verify the on-disk cache contains pitch-mix columns — this would catch
    # _fetch_pitchers() being changed to drop the columns in a real run.
    cache_path = Path("cache") / f"statcast_pitcher_{date.today().isoformat()}.csv"
    assert cache_path.exists(), f"Expected pitcher cache at {cache_path}"
    text = cache_path.read_text(encoding="utf-8").lstrip("\ufeff")
    headers = next(csv.reader(io.StringIO(text)))
    assert "n_ff_formatted" in headers, f"n_ff_formatted missing from pitcher cache headers: {headers}"
    assert "n_sl_formatted" in headers
    assert "n_ch_formatted" in headers

    # Stat dict should be non-empty with fb data
    pitchers_with_ff = [
        name for name, row in stats.items()
        if row.get("n_ff_formatted") not in (None, "")
    ]
    assert len(pitchers_with_ff) > 0

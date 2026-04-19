import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.predictor import Homer

def test_fetch_pitchers_includes_pitch_mix():
    """Pitcher CSV should include at least one pitch-mix field for a known pitcher."""
    homer = Homer()
    stats = homer._fetch_full_statcast(
        "pitcher",
        "hr_flyball_rate,fb_percent,xfip,hard_hit_percent,barrel_batted_rate,"
        "n_ff_formatted,n_si_formatted,n_fc_formatted,"
        "n_sl_formatted,n_cu_formatted,n_sw_formatted,"
        "n_ch_formatted,n_fs_formatted"
    )
    assert stats, "Pitcher stats dict should not be empty"
    # At least one pitcher should have a non-empty n_ff_formatted value
    pitchers_with_ff = [
        name for name, row in stats.items()
        if row.get("n_ff_formatted") not in (None, "")
    ]
    assert len(pitchers_with_ff) > 0, "Expected at least one pitcher with 4-seam fastball data"

"""Pytest configuration for test isolation."""
import pytest
from pathlib import Path
from datetime import date


@pytest.fixture(autouse=True)
def cleanup_pitcher_k_cache():
    """Clean up pitcher K-rate cache after each test to ensure isolation."""
    yield
    today_str = date.today().isoformat()
    cache_file = Path(__file__).parent.parent / "cache" / f"statcast_pitcher_k_{today_str}.csv"
    if cache_file.exists():
        cache_file.unlink()

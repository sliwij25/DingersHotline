import pytest
from pathlib import Path
from datetime import date

def pytest_addoption(parser):
    parser.addoption("--no-network", action="store_true", default=False,
                     help="Skip tests that require network access")

def pytest_configure(config):
    config.addinivalue_line("markers", "network: mark test as requiring network access")

@pytest.fixture
def require_network(request):
    if request.config.getoption("--no-network"):
        pytest.skip("Skipped: --no-network flag set")

@pytest.fixture(autouse=True)
def cleanup_pitcher_k_cache():
    """Clean up pitcher K-rate cache after each test to ensure isolation."""
    yield
    today_str = date.today().isoformat()
    cache_file = Path(__file__).parent.parent / "cache" / f"statcast_pitcher_k_{today_str}.csv"
    if cache_file.exists():
        cache_file.unlink()

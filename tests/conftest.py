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

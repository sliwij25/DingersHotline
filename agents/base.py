"""
Shared DB helpers and path constants used by all agents.
"""
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────────────
AGENTS_DIR  = Path(__file__).parent
PROJECT_DIR = AGENTS_DIR.parent
DB_PATH     = str(PROJECT_DIR / "data" / "bets.db")

# Load API keys from api/.env (ODDS_API_KEY etc.)
load_dotenv(PROJECT_DIR / "api" / ".env")


def get_db_conn() -> sqlite3.Connection:
    """Open and return a SQLite connection to the bets database."""
    return sqlite3.connect(DB_PATH)

"""
Shared DB helpers and path constants used by all agents.
"""
import subprocess
import sqlite3
import time
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


def git_commit_and_push(files: list[str], msg: str, retries: int = 2) -> str:
    """
    Stage, commit, and push `files` with commit message `msg`.

    Unlike a bare `subprocess.run(["git", "push"])`, this checks the actual
    exit code of every step and retries the push on transient failure
    (network blip, launchd-session credential hiccup) instead of silently
    logging success regardless of outcome.

    Returns one of: "pushed", "nothing_to_commit", "commit_failed: <stderr>",
    "push_failed: <stderr>".
    """
    repo = str(PROJECT_DIR)
    git = "/usr/bin/git"

    add_result = subprocess.run(
        [git, "-C", repo, "add"] + files, capture_output=True, text=True
    )
    if add_result.returncode != 0:
        return f"commit_failed: git add failed — {add_result.stderr.strip()}"

    commit_result = subprocess.run(
        [git, "-C", repo, "commit", "-m", msg], capture_output=True, text=True
    )
    if "nothing to commit" in commit_result.stdout:
        return "nothing_to_commit"
    if commit_result.returncode != 0:
        return f"commit_failed: {commit_result.stderr.strip() or commit_result.stdout.strip()}"

    last_err = ""
    for attempt in range(1, retries + 1):
        push_result = subprocess.run(
            [git, "-C", repo, "push"], capture_output=True, text=True
        )
        if push_result.returncode == 0:
            return "pushed"
        last_err = push_result.stderr.strip() or push_result.stdout.strip()
        if attempt < retries:
            time.sleep(5)
    return f"push_failed: {last_err}"

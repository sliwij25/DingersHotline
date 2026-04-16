"""
Overseer Agent
Uses local Ollama (llama3.1) — no API key required.

Skills:
  - ask_bet_tracker                : delegate DB / P&L queries to BetTrackerAgent
  - ask_predictor                  : delegate scraping / picks to PredictorAgent
  - validate_predictions_vs_results: compare bets to actual outcomes for a date
  - get_performance_report         : cross-date analysis by odds tier and player
"""
import json
from datetime import date

from .base import get_client, get_db_conn, run_agent

# ── Sub-agent helpers ─────────────────────────────────────────────────────────

def _run_bet_tracker(query: str) -> str:
    from .bet_tracker import BetTrackerAgent
    return BetTrackerAgent().run(query)

def _run_predictor(query: str) -> str:
    from .predictor import Homer
    return Homer().run(query)

# ── Tool definitions ───────────────────────────────────────────────────────────

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_bet_tracker",
            "description": "Delegate a question or task to the Bet Tracker Agent (DB, P&L, results).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language instruction for the Bet Tracker Agent."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_predictor",
            "description": "Delegate a question or task to the Predictor Agent (BallparkPal, daily picks).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language instruction for the Predictor Agent."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_predictions_vs_results",
            "description": "Compare bets placed on a given date against their actual outcomes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD date to validate."},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_performance_report",
            "description": "Generate a comprehensive multi-date performance report broken down by odds tier and player.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# ── Tool implementations ───────────────────────────────────────────────────────

def ask_bet_tracker(query: str) -> str:
    return _run_bet_tracker(query)

def ask_predictor(query: str) -> str:
    return _run_predictor(query)

def validate_predictions_vs_results(date: str) -> str:
    conn = get_db_conn()
    try:
        rows = conn.execute("""
            SELECT player, odds, wager, potential_payout, result, payout, game
            FROM   singles
            WHERE  bet_date = ? AND result IS NOT NULL
            ORDER  BY player
        """, (date,)).fetchall()

        if not rows:
            return f"No settled bets found for {date}."

        wins   = [r for r in rows if r[4] == "win"]
        losses = [r for r in rows if r[4] == "loss"]

        def odds_int(o):
            try:
                return int(str(o).replace("+", ""))
            except Exception:
                return 999

        upsets          = [r for r in wins   if odds_int(r[1]) >= 400]
        surprise_losses = [r for r in losses if odds_int(r[1]) <  250]

        wagered  = sum(r[2] for r in rows)
        returned = sum((r[5] or 0) for r in wins)
        net      = returned - wagered

        return json.dumps({
            "date":            date,
            "total_bets":      len(rows),
            "wins":            len(wins),
            "losses":          len(losses),
            "win_rate":        f"{len(wins) / len(rows) * 100:.1f}%",
            "net_pnl":         f"${net:+.2f}",
            "winners":         [{"player": r[0], "odds": r[1], "payout": r[5]} for r in wins],
            "losers":          [{"player": r[0], "odds": r[1]} for r in losses],
            "upsets":          [r[0] for r in upsets],
            "surprise_losses": [r[0] for r in surprise_losses],
            "flags": {
                "upsets_count":          len(upsets),
                "surprise_losses_count": len(surprise_losses),
            },
        }, indent=2)
    finally:
        conn.close()


def get_performance_report() -> str:
    conn = get_db_conn()
    try:
        tier_rows = conn.execute("""
            SELECT
                CASE
                    WHEN CAST(REPLACE(odds,'+','') AS INTEGER) < 250 THEN 'favorite  (<+250)'
                    WHEN CAST(REPLACE(odds,'+','') AS INTEGER) < 350 THEN 'mid       (+250-+349)'
                    WHEN CAST(REPLACE(odds,'+','') AS INTEGER) < 450 THEN 'long      (+350-+449)'
                    ELSE                                                   'longshot  (+450+)'
                END                                                     AS tier,
                COUNT(*)                                                AS total,
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END)          AS wins,
                SUM(COALESCE(payout,0) - wager)                        AS net_pnl
            FROM singles
            WHERE result IS NOT NULL AND odds IS NOT NULL
            GROUP BY tier
            ORDER BY tier
        """).fetchall()

        best = conn.execute("""
            SELECT player, COUNT(*) AS bets,
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) AS wins,
                   SUM(COALESCE(payout,0) - wager) AS pnl
            FROM   singles
            WHERE  result IS NOT NULL
            GROUP  BY player HAVING bets >= 2
            ORDER  BY pnl DESC LIMIT 5
        """).fetchall()

        worst = conn.execute("""
            SELECT player, COUNT(*) AS bets,
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) AS wins,
                   SUM(COALESCE(payout,0) - wager) AS pnl
            FROM   singles
            WHERE  result IS NOT NULL
            GROUP  BY player HAVING bets >= 2
            ORDER  BY pnl ASC LIMIT 5
        """).fetchall()

        return json.dumps({
            "by_odds_tier": [
                {"tier": r[0].strip(), "bets": r[1], "wins": r[2],
                 "win_rate": f"{r[2]/r[1]*100:.1f}%" if r[1] else "N/A",
                 "net_pnl":  f"${r[3]:+.2f}"}
                for r in tier_rows
            ],
            "best_players": [
                {"player": r[0], "bets": r[1], "wins": r[2], "net_pnl": f"${r[3]:+.2f}"}
                for r in best
            ],
            "worst_players": [
                {"player": r[0], "bets": r[1], "wins": r[2], "net_pnl": f"${r[3]:+.2f}"}
                for r in worst
            ],
        }, indent=2)
    finally:
        conn.close()


# ── Agent ──────────────────────────────────────────────────────────────────────

_SYSTEM = """You are the Overseer Agent for a home run betting system.
You coordinate two specialist sub-agents and deliver high-level analysis.

Sub-agents at your disposal:
  - Bet Tracker  — all database operations: logging, results, P&L
  - Predictor    — BallparkPal scraping, matchup analysis, daily picks

Your responsibilities:
  1. Orchestrate the daily workflow on request
  2. Validate that predictions align with outcomes over time
  3. Surface systematic patterns in the data (odds tiers, specific players, parks)
  4. Flag when the prediction model needs recalibration
  5. Deliver concise, actionable executive summaries

Daily workflow (when asked to run it):
  Step 1 — Ask Predictor for today's picks
  Step 2 — Ask Bet Tracker for pending bets + current P&L
  Step 3 — Validate yesterday's predictions vs results
  Step 4 — Summarise findings; flag red flags or pattern shifts

Always be data-driven. Quantify everything with dollar amounts and percentages."""

_TOOL_FNS = {
    "ask_bet_tracker":                ask_bet_tracker,
    "ask_predictor":                  ask_predictor,
    "validate_predictions_vs_results": validate_predictions_vs_results,
    "get_performance_report":         get_performance_report,
}


class OverseerAgent:
    """Local Ollama orchestrator that coordinates the Bet Tracker and Predictor agents."""

    def __init__(self):
        self.client = get_client()

    def run(self, user_message: str) -> str:
        today = date.today().isoformat()
        msg_with_date = f"Today's date is {today}.\n\n{user_message}"
        return run_agent(
            client    = self.client,
            system    = _SYSTEM,
            user_msg  = msg_with_date,
            tools     = _TOOLS,
            tool_fns  = _TOOL_FNS,
            max_tokens= 8192,
        )

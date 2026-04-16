"""
Bet Tracker Agent
Uses local Ollama (llama3.1) — no API key required.

Skills:
  - get_pnl_summary           : overall P&L across all settled bets
  - get_pending_bets          : bets that still need a result
  - get_bet_history           : filterable history for analysis
  - record_result             : write win/loss + payout to DB
  - get_player_stats          : per-player win rate and ROI
  - save_pick_factors         : store signal snapshot for a pick (algorithm tracking)
  - factor_performance_report : analyze which signals predict wins
"""
import json
from datetime import date
from typing import Optional

from .base import get_client, get_db_conn, run_agent


# ── player_attributes table (permanent player info — handedness, etc.) ────────

_CREATE_PLAYER_ATTRS = """
CREATE TABLE IF NOT EXISTS player_attributes (
    mlb_id     INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    bat_side   TEXT,        -- L / R / S
    throws     TEXT,        -- L / R (pitchers)
    updated_at TEXT    DEFAULT (datetime('now'))
);
"""

def _ensure_player_attrs_table(conn) -> None:
    conn.execute(_CREATE_PLAYER_ATTRS)
    conn.commit()


def upsert_player_attr(mlb_id: int, name: str,
                       bat_side: str = None, throws: str = None) -> None:
    """
    Persist a player's static attributes (handedness, etc.).
    Safe to call every run — only writes when values are non-null and meaningful.
    """
    if not mlb_id or not name:
        return
    conn = get_db_conn()
    try:
        _ensure_player_attrs_table(conn)
        # Only update fields we actually have — don't overwrite good data with None
        fields, vals = ["name", "updated_at"], [name, date.today().isoformat()]
        if bat_side and bat_side != "?":
            fields.append("bat_side"); vals.append(bat_side)
        if throws and throws != "?":
            fields.append("throws"); vals.append(throws)
        set_clause = ", ".join(f"{f} = excluded.{f}" for f in fields)
        conn.execute(f"""
            INSERT INTO player_attributes (mlb_id, {', '.join(fields)})
            VALUES ({mlb_id}, {', '.join('?' for _ in fields)})
            ON CONFLICT(mlb_id) DO UPDATE SET {set_clause}
        """, vals)
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def get_bat_side(mlb_id: int) -> str:
    """Look up a player's bat side from the persistent DB. Returns '?' if unknown."""
    if not mlb_id:
        return "?"
    conn = get_db_conn()
    try:
        _ensure_player_attrs_table(conn)
        row = conn.execute(
            "SELECT bat_side FROM player_attributes WHERE mlb_id = ?", (mlb_id,)
        ).fetchone()
        return row[0] if row and row[0] else "?"
    except Exception:
        return "?"
    finally:
        conn.close()


# ── pick_factors table helpers ─────────────────────────────────────────────────

_CREATE_PICK_FACTORS = """
CREATE TABLE IF NOT EXISTS pick_factors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_date         TEXT    NOT NULL,
    player           TEXT    NOT NULL,
    algo_version     TEXT    DEFAULT '2.0',
    confidence       TEXT,
    score            REAL,
    rank             INTEGER,
    homered          INTEGER,
    ev_10            REAL,
    kelly_size       REAL,
    value_edge       REAL,
    pinnacle_odds    TEXT,
    best_odds        TEXT,
    platoon          TEXT,
    barrel_rate      REAL,
    hard_hit_pct     REAL,
    hr_fb_ratio      REAL,
    xiso             REAL,
    bpp_hr_pct       REAL,
    park_hr_factor   REAL,
    recent_form_14d  INTEGER,
    pitcher_hr_per_9 REAL,
    h2h_hr           INTEGER,
    h2h_ab           INTEGER,
    is_home          INTEGER,
    lineup_confirmed INTEGER,
    venue_slugging   TEXT,
    created_at       TEXT    DEFAULT (datetime('now')),
    UNIQUE(bet_date, player)
);
"""

# Columns added after initial release — migrated safely at runtime
_MIGRATION_COLUMNS = [
    ("score",            "REAL"),
    ("rank",             "INTEGER"),
    ("homered",          "INTEGER"),
    ("xiso",             "REAL"),
    ("xslg",             "REAL"),
    ("xhr_rate",         "REAL"),
    ("fb_pct",           "REAL"),
    ("launch_angle",     "REAL"),
    ("ev_avg",           "REAL"),
    ("sweet_spot_pct",   "REAL"),
    ("bpp_hr_pct",       "REAL"),
    ("park_hr_factor",   "REAL"),
    ("lineup_confirmed", "INTEGER"),
    ("best_odds",        "TEXT"),
]


def _ensure_pick_factors_table(conn) -> None:
    conn.execute(_CREATE_PICK_FACTORS)
    conn.commit()
    # Add new columns to existing tables without breaking old rows
    existing = {row[1] for row in conn.execute("PRAGMA table_info(pick_factors)").fetchall()}
    for col_name, col_type in _MIGRATION_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE pick_factors ADD COLUMN {col_name} {col_type}")
    conn.commit()


def save_pick_factors(bet_date: str, player: str, signals: dict,
                      confidence: str = None,
                      algo_version: str = "2.0",
                      score: float = None,
                      rank: int = None) -> str:
    """
    Persist the algorithmic signal snapshot for one pick.
    Called automatically by daily_picks.py for ALL ranked players (not just bets),
    so we can train the ML model on unbiased outcome data.

    Args:
        bet_date:     YYYY-MM-DD
        player:       Full player name
        signals:      Dict from _rank_picks_python() pick["signals"]
        confidence:   "HIGH" / "MEDIUM" / "LOW"
        algo_version: Tag to track when the algorithm is updated
        score:        Raw Homer score (float)
        rank:         Rank among all players scored that day (1 = best)
    """
    conn = get_db_conn()
    try:
        _ensure_pick_factors_table(conn)
        conn.execute("""
            INSERT OR REPLACE INTO pick_factors
              (bet_date, player, algo_version, confidence, score, rank,
               ev_10, kelly_size, value_edge, pinnacle_odds, best_odds,
               platoon, barrel_rate, hard_hit_pct, hr_fb_ratio,
               xiso, xslg, xhr_rate, fb_pct, launch_angle, ev_avg, sweet_spot_pct,
               bpp_hr_pct, park_hr_factor,
               recent_form_14d, pitcher_hr_per_9,
               h2h_hr, h2h_ab, is_home, lineup_confirmed, venue_slugging)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            bet_date, player, algo_version,
            confidence or signals.get("confidence"),
            score,
            rank,
            signals.get("ev_10"),
            signals.get("kelly_size"),
            signals.get("value_edge"),
            signals.get("pinnacle_odds"),
            signals.get("best_odds"),
            signals.get("platoon"),
            signals.get("barrel_rate"),
            signals.get("hard_hit_pct"),
            signals.get("hr_fb_ratio"),
            signals.get("xiso"),
            signals.get("xslg"),
            signals.get("xhr_rate"),
            signals.get("fb_pct"),
            signals.get("launch_angle"),
            signals.get("ev_avg"),
            signals.get("sweet_spot_pct"),
            signals.get("bpp_hr_pct"),
            signals.get("park_hr_factor"),
            signals.get("recent_form_14d"),
            signals.get("pitcher_hr_per_9"),
            signals.get("h2h_hr"),
            signals.get("h2h_ab"),
            1 if signals.get("is_home") else 0,
            1 if signals.get("lineup_confirmed", True) else 0,
            signals.get("venue_slugging"),
        ))
        conn.commit()
        return f"Saved signals for {player} ({bet_date})"
    finally:
        conn.close()


def model_pnl_report() -> str:
    """
    Hypothetical P&L if $10 was bet on every top-20 pick each day.
    Completely separate from actual bets — tracks model quality in dollar terms.
    Only counts picks where homered IS NOT NULL and best_odds IS NOT NULL.
    """
    conn = get_db_conn()
    try:
        rows = conn.execute("""
            SELECT bet_date, player, rank, best_odds, homered
            FROM pick_factors
            WHERE homered IS NOT NULL
              AND best_odds IS NOT NULL
              AND algo_version NOT LIKE 'hist_%'
            ORDER BY bet_date, rank
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        return json.dumps({"error": "No labeled picks with odds data yet. Run tomorrow after games end."})

    def _to_decimal(odds_str: str) -> float:
        try:
            o = int(odds_str)
            return (o / 100 + 1) if o > 0 else (100 / abs(o) + 1)
        except Exception:
            return None

    days: dict = {}
    for bet_date, player, rank, best_odds, homered in rows:
        dec = _to_decimal(best_odds)
        if dec is None:
            continue
        pnl = round((dec - 1) * 10, 2) if homered else -10.0
        if bet_date not in days:
            days[bet_date] = {"picks": 0, "wins": 0, "pnl": 0.0, "players": []}
        days[bet_date]["picks"] += 1
        days[bet_date]["wins"] += int(homered)
        days[bet_date]["pnl"] = round(days[bet_date]["pnl"] + pnl, 2)
        days[bet_date]["players"].append({
            "rank": rank, "player": player,
            "odds": best_odds, "homered": bool(homered), "pnl": pnl,
        })

    cumulative = 0.0
    daily_rows = []
    for date_str in sorted(days):
        d = days[date_str]
        cumulative = round(cumulative + d["pnl"], 2)
        daily_rows.append({
            "date": date_str,
            "picks_with_odds": d["picks"],
            "wins": d["wins"],
            "day_pnl": f"${d['pnl']:+.2f}",
            "cumulative_pnl": f"${cumulative:+.2f}",
            "players": d["players"],
        })

    total_picks = sum(d["picks"] for d in days.values())
    total_wins  = sum(d["wins"]  for d in days.values())
    return json.dumps({
        "model_pnl_summary": {
            "days_tracked": len(days),
            "total_picks_with_odds": total_picks,
            "total_wins": total_wins,
            "win_pct": f"{total_wins/total_picks*100:.1f}%" if total_picks else "0%",
            "total_wagered": f"${total_picks * 10:.2f}",
            "cumulative_pnl": f"${cumulative:+.2f}",
            "roi": f"{cumulative / (total_picks * 10) * 100:+.1f}%" if total_picks else "0%",
        },
        "daily": daily_rows,
    }, indent=2)


def model_performance_report() -> str:
    """
    Print a plain-text model performance dashboard to stdout.
    Covers pick accuracy, rank bucket hit rates, confidence calibration,
    betting P&L, and ML model status. Called automatically at the end of
    daily_picks.py so it appears in the log every morning.
    """
    import os, json
    from datetime import date, timedelta

    lines = []
    add = lines.append

    add("=" * 60)
    add("  MODEL PERFORMANCE DASHBOARD")
    add("=" * 60)

    conn = get_db_conn()
    try:
        _ensure_pick_factors_table(conn)

        today_str = date.today().isoformat()
        week_ago  = (date.today() - timedelta(days=7)).isoformat()
        month_ago = (date.today() - timedelta(days=30)).isoformat()

        # ── 1. Pick accuracy (pick_factors with labeled outcomes) ─────────────
        total_labeled = conn.execute(
            "SELECT COUNT(*) FROM pick_factors WHERE homered IS NOT NULL"
        ).fetchone()[0]

        # Count how many live picks (with rank) are labeled — separate from historical bulk data
        live_labeled = conn.execute(
            "SELECT COUNT(*) FROM pick_factors WHERE homered IS NOT NULL AND rank IS NOT NULL"
        ).fetchone()[0]

        add(f"\n  PICK ACCURACY  ({live_labeled:,} live labeled picks | {total_labeled:,} total incl. historical)")
        add(f"  {'Bucket':<14} {'Picks':>6} {'HRs':>6} {'Hit Rate':>10}  {'vs base':>8}")
        add("  " + "-" * 50)

        base_rate = 8.1  # historical base rate from dataset

        buckets = [
            ("Top 3",   "rank <= 3"),
            ("Top 5",   "rank <= 5"),
            ("6-10",    "rank BETWEEN 6 AND 10"),
            ("11-20",   "rank BETWEEN 11 AND 20"),
            ("All live","rank IS NOT NULL"),
        ]
        any_rank_data = False
        for label, where in buckets:
            row = conn.execute(
                f"SELECT COUNT(*), SUM(homered) FROM pick_factors "
                f"WHERE homered IS NOT NULL AND {where}"
            ).fetchone()
            n, hits = row[0], (row[1] or 0)
            if n == 0:
                continue
            any_rank_data = True
            rate = hits / n * 100
            vs   = rate - base_rate
            vs_s = f"+{vs:.1f}pp" if vs >= 0 else f"{vs:.1f}pp"
            bar  = "█" * int(rate / 3)
            add(f"  {label:<14} {n:>6} {hits:>6} {rate:>9.1f}%  {vs_s:>8}  {bar}")

        if not any_rank_data:
            add("  (Populates after first game day — run picks daily to build this up)")

        # Last 7 days trend
        row7 = conn.execute(
            "SELECT COUNT(*), SUM(homered) FROM pick_factors "
            "WHERE homered IS NOT NULL AND rank <= 20 AND bet_date >= ?", (week_ago,)
        ).fetchone()
        if row7[0]:
            r7 = (row7[1] or 0) / row7[0] * 100
            add(f"\n  Last 7 days (top 20): {row7[0]} picks, {r7:.1f}% hit rate")

        # ── 2. Confidence tier calibration ────────────────────────────────────
        add(f"\n  CONFIDENCE CALIBRATION")
        add(f"  {'Tier':<10} {'Picks':>6} {'HRs':>6} {'Hit Rate':>10}")
        add("  " + "-" * 36)
        for tier in ("HIGH", "MEDIUM", "LOW"):
            row = conn.execute(
                "SELECT COUNT(*), SUM(homered) FROM pick_factors "
                "WHERE homered IS NOT NULL AND confidence=?", (tier,)
            ).fetchone()
            n, hits = row[0], (row[1] or 0)
            if n == 0:
                continue
            rate = hits / n * 100
            add(f"  {tier:<10} {n:>6} {hits:>6} {rate:>9.1f}%")

        # ── 3. Betting P&L (from singles table) ───────────────────────────────
        try:
            pnl_rows = conn.execute("""
                SELECT
                  COUNT(*)                                   as total,
                  SUM(CASE WHEN result='win'  THEN 1 ELSE 0 END) as wins,
                  SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses,
                  SUM(CASE WHEN result IS NULL THEN 1 ELSE 0 END) as pending,
                  SUM(wager)                                 as wagered,
                  SUM(CASE WHEN result='win' THEN payout - wager
                           WHEN result='loss' THEN -wager
                           ELSE 0 END)                       as net_pnl
                FROM singles
            """).fetchone()

            total_b, wins_b, losses_b, pending_b, wagered, net = pnl_rows
            settled = (wins_b or 0) + (losses_b or 0)
            win_rate = (wins_b or 0) / settled * 100 if settled else 0
            roi      = (net or 0) / (wagered or 1) * 100

            add(f"\n  BETTING P&L")
            add(f"  {'Record:':<18} {wins_b or 0}W - {losses_b or 0}L  ({pending_b or 0} pending)")
            add(f"  {'Win rate:':<18} {win_rate:.1f}%  (MLB base HR rate ~15%)")
            add(f"  {'Total wagered:':<18} ${wagered or 0:.2f}")
            add(f"  {'Net P&L:':<18} ${net or 0:+.2f}")
            add(f"  {'ROI:':<18} {roi:+.1f}%")

            # Last 7 days P&L
            row7p = conn.execute("""
                SELECT COUNT(*),
                  SUM(CASE WHEN result='win' THEN 1 ELSE 0 END),
                  SUM(CASE WHEN result='win' THEN payout - wager
                           WHEN result='loss' THEN -wager ELSE 0 END)
                FROM singles WHERE result IS NOT NULL AND bet_date >= ?
            """, (week_ago,)).fetchone()
            if row7p[0]:
                r7_rate = (row7p[1] or 0) / row7p[0] * 100
                add(f"  {'Last 7 days:':<18} {row7p[0]} bets, {r7_rate:.0f}% win rate, ${row7p[2] or 0:+.2f} P&L")

            # Last 30 days P&L
            row30p = conn.execute("""
                SELECT COUNT(*),
                  SUM(CASE WHEN result='win' THEN 1 ELSE 0 END),
                  SUM(CASE WHEN result='win' THEN payout - wager
                           WHEN result='loss' THEN -wager ELSE 0 END)
                FROM singles WHERE result IS NOT NULL AND bet_date >= ?
            """, (month_ago,)).fetchone()
            if row30p[0]:
                r30_rate = (row30p[1] or 0) / row30p[0] * 100
                add(f"  {'Last 30 days:':<18} {row30p[0]} bets, {r30_rate:.0f}% win rate, ${row30p[2] or 0:+.2f} P&L")

        except Exception as e:
            add(f"\n  BETTING P&L  (unavailable: {e})")

        # ── 4. ML model status ─────────────────────────────────────────────────
        add(f"\n  ML MODEL STATUS")
        weights_path = os.path.join(os.path.dirname(__file__), "..", "ml_weights.json")
        weights_path = os.path.normpath(weights_path)
        if os.path.exists(weights_path):
            try:
                with open(weights_path) as f:
                    w = json.load(f)
                trained_on = w.get("trained_on", "?")
                auc        = w.get("cv_auc_mean", 0)
                n_samples  = w.get("n_samples", 0)
                auc_std    = w.get("cv_auc_std", 0)
                days_since = (date.today() - date.fromisoformat(trained_on)).days if trained_on != "?" else "?"

                auc_grade = "strong" if auc >= 0.70 else "useful" if auc >= 0.60 else "developing"
                ml_weight_pct = min(70, max(0, (auc - 0.5) * 250))

                add(f"  {'Trained:':<20} {trained_on}  ({days_since} days ago)")
                add(f"  {'Training samples:':<20} {n_samples:,}")
                add(f"  {'Cross-val AUC:':<20} {auc:.3f} ± {auc_std:.3f}  [{auc_grade}]")
                add(f"  {'ML influence:':<20} {ml_weight_pct:.0f}% of final score  (grows as AUC improves)")

                # Top 3 features
                coeffs = w.get("coefficients", {})
                top3   = sorted(coeffs.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
                top3_s = "  ".join(f"{f}({c:+.2f})" for f, c in top3)
                add(f"  {'Top features:':<20} {top3_s}")

                # Labeled picks since last training
                new_since = conn.execute(
                    "SELECT COUNT(*) FROM pick_factors WHERE homered IS NOT NULL AND bet_date > ?",
                    (trained_on,)
                ).fetchone()[0]
                next_retrain = max(0, 200 - new_since)
                add(f"  {'New labeled picks:':<20} {new_since} since last training"
                    f"  ({'retrain due!' if next_retrain == 0 else f'{next_retrain} until next retrain'})")

            except Exception as e:
                add(f"  Could not read ml_weights.json: {e}")
        else:
            labeled_n = conn.execute(
                "SELECT COUNT(*) FROM pick_factors WHERE homered IS NOT NULL"
            ).fetchone()[0]
            add(f"  No model yet — {labeled_n}/100 labeled picks collected")
            add(f"  Model trains automatically once 100 picks are labeled.")

    finally:
        conn.close()

    add("\n" + "=" * 60)
    return "\n".join(lines)


def factor_performance_report() -> str:
    """
    Analyze which pick signals correlate with wins across all settled bets
    that have a pick_factors snapshot.

    Joins pick_factors with singles on (bet_date + fuzzy player name) and
    computes win rates broken down by each key signal. Use this to measure
    whether the algorithm is improving and which factors are most predictive.
    """
    conn = get_db_conn()
    try:
        _ensure_pick_factors_table(conn)

        # Join on bet_date + approximate player name
        rows = conn.execute("""
            SELECT
                pf.player, pf.bet_date,
                pf.confidence, pf.ev_10, pf.kelly_size, pf.value_edge,
                pf.platoon, pf.barrel_rate, pf.hard_hit_pct, pf.hr_fb_ratio,
                pf.recent_form_14d, pf.pitcher_hr_per_9,
                pf.h2h_hr, pf.h2h_ab, pf.is_home, pf.algo_version,
                s.result
            FROM pick_factors pf
            LEFT JOIN singles s
              ON s.bet_date = pf.bet_date
             AND (s.player LIKE '%' || pf.player || '%'
                  OR pf.player LIKE '%' || s.player || '%')
            WHERE s.result IS NOT NULL
            ORDER BY pf.bet_date DESC
        """).fetchall()

        if not rows:
            return json.dumps({
                "status": "no_data",
                "message": "No settled bets with signal snapshots yet. "
                           "Signals are saved automatically when you run daily_picks.py."
            }, indent=2)

        cols   = ["player","bet_date","confidence","ev_10","kelly_size","value_edge",
                  "platoon","barrel_rate","hard_hit_pct","hr_fb_ratio",
                  "recent_form_14d","pitcher_hr_per_9","h2h_hr","h2h_ab",
                  "is_home","algo_version","result"]
        bets   = [dict(zip(cols, r)) for r in rows]
        total  = len(bets)
        wins   = [b for b in bets if b["result"] == "win"]
        w_rate = len(wins) / total * 100 if total else 0

        def split_rate(key, condition_fn, label):
            group = [b for b in bets if condition_fn(b.get(key))]
            if not group:
                return None
            gw = sum(1 for b in group if b["result"] == "win")
            return {"label": label, "bets": len(group),
                    "wins": gw, "win_pct": f"{gw/len(group)*100:.1f}%"}

        sections = {}

        # Confidence tier
        for tier in ("HIGH", "MEDIUM", "LOW"):
            g = [b for b in bets if b.get("confidence") == tier]
            if g:
                gw = sum(1 for b in g if b["result"] == "win")
                sections.setdefault("by_confidence", {})[tier] = {
                    "bets": len(g), "wins": gw, "win_pct": f"{gw/len(g)*100:.1f}%"
                }

        # EV
        sections["ev_positive"] = split_rate("ev_10", lambda v: v is not None and v > 0, "ev_10 > 0")
        sections["ev_negative"] = split_rate("ev_10", lambda v: v is not None and v <= 0, "ev_10 <= 0")

        # VALUE flag (value_edge >= 3pp)
        sections["value_flag"]    = split_rate("value_edge", lambda v: v is not None and v >= 3.0, "value_edge >= 3pp")
        sections["no_value_flag"] = split_rate("value_edge", lambda v: v is not None and v < 3.0, "value_edge < 3pp")

        # Platoon
        sections["platoon_plus"]  = split_rate("platoon", lambda v: v == "PLATOON+", "PLATOON+")
        sections["platoon_minus"] = split_rate("platoon", lambda v: v == "platoon-", "platoon-")

        # H2H — has hit HR off this pitcher before
        sections["h2h_has_hr"] = split_rate("h2h_hr", lambda v: v is not None and v >= 1, "h2h_hr >= 1")
        sections["h2h_no_hr"]  = split_rate("h2h_hr", lambda v: v is not None and v == 0, "h2h_hr = 0")

        # Pitcher recent vulnerability (HR/9 last 3 starts)
        sections["pitcher_vulnerable"] = split_rate("pitcher_hr_per_9",
                                                     lambda v: v is not None and v >= 1.0,
                                                     "pitcher HR/9 >= 1.0 (last 3 starts)")

        # Barrel rate
        sections["barrel_elite"] = split_rate("barrel_rate",
                                               lambda v: v is not None and v >= 10.0,
                                               "barrel_rate >= 10%")

        # Home vs away
        sections["home_batter"] = split_rate("is_home", lambda v: v == 1, "batting at home")
        sections["away_batter"] = split_rate("is_home", lambda v: v == 0, "batting away")

        # Recent hot streak
        sections["hot_streak"] = split_rate("recent_form_14d",
                                             lambda v: v is not None and v >= 2,
                                             "2+ HR in last 14 days")

        # Filter out None entries
        sections = {k: v for k, v in sections.items() if v is not None}

        # Version breakdown
        version_stats = {}
        for b in bets:
            v = b.get("algo_version") or "unknown"
            version_stats.setdefault(v, {"bets": 0, "wins": 0})
            version_stats[v]["bets"] += 1
            if b["result"] == "win":
                version_stats[v]["wins"] += 1
        for v, s in version_stats.items():
            s["win_pct"] = f"{s['wins']/s['bets']*100:.1f}%" if s["bets"] else "0%"

        return json.dumps({
            "status":         "success",
            "total_tracked":  total,
            "overall_wins":   len(wins),
            "overall_win_pct": f"{w_rate:.1f}%",
            "by_algo_version": version_stats,
            "signal_breakdown": sections,
            "note": (
                "signal_breakdown shows win rate for each signal condition. "
                "Factors with win_pct well above overall_win_pct are predictive. "
                "Low sample sizes (<5 bets) may not be statistically meaningful."
            ),
        }, indent=2)
    finally:
        conn.close()

# ── Tool definitions (Ollama/OpenAI format) ───────────────────────────────────

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_pnl_summary",
            "description": "Return a full P&L summary across all settled bets, broken down by date.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_bets",
            "description": "Return bets that have no result recorded yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bet_date": {
                        "type": "string",
                        "description": "Optional YYYY-MM-DD filter. Omit for all pending bets.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bet_history",
            "description": "Return historical bets, optionally filtered by date range or player.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "YYYY-MM-DD lower bound."},
                    "end_date":   {"type": "string", "description": "YYYY-MM-DD upper bound."},
                    "player":     {"type": "string", "description": "Partial player name match."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_result",
            "description": "Write the outcome of a settled bet to the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bet_date": {"type": "string", "description": "YYYY-MM-DD date of the bet."},
                    "player":   {"type": "string", "description": "Exact player name as stored."},
                    "result":   {"type": "string", "description": "'win' or 'loss'."},
                    "payout":   {"type": "number",  "description": "Total return for a win. Omit for a loss."},
                },
                "required": ["bet_date", "player", "result"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_stats",
            "description": "Return win rate and ROI for a specific player.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player": {"type": "string", "description": "Partial or full player name."},
                },
                "required": ["player"],
            },
        },
    },
]

# ── Tool implementations ───────────────────────────────────────────────────────

def get_pnl_summary() -> str:
    conn = get_db_conn()
    try:
        rows = conn.execute("""
            SELECT bet_date, player, wager, odds, result, payout
            FROM   singles
            WHERE  result IS NOT NULL
            ORDER  BY bet_date
        """).fetchall()

        if not rows:
            return "No settled bets found."

        wins, total_wagered, total_returned = 0, 0.0, 0.0
        bet_list = []
        for bet_date, player, wager, odds, result, payout in rows:
            payout = payout or 0.0
            pnl = (payout - wager) if result == "win" else -wager
            if result == "win":
                wins += 1
                total_returned += payout
            total_wagered += wager
            bet_list.append({"date": bet_date, "player": player, "odds": odds,
                              "result": result, "pnl": round(pnl, 2)})

        total = len(rows)
        net   = total_returned - total_wagered
        return json.dumps({
            "total_bets":    total,
            "wins":          wins,
            "losses":        total - wins,
            "win_pct":       f"{wins / total * 100:.1f}%",
            "total_wagered": f"${total_wagered:.2f}",
            "net_pnl":       f"${net:+.2f}",
            "roi":           f"{net / total_wagered * 100:+.1f}%" if total_wagered else "N/A",
            "bets":          bet_list,
        }, indent=2)
    finally:
        conn.close()


def get_pending_bets(bet_date: str = None) -> str:
    conn = get_db_conn()
    try:
        if bet_date:
            rows = conn.execute(
                "SELECT id, bet_date, platform, player, game, wager, odds, potential_payout "
                "FROM singles WHERE result IS NULL AND bet_date=? ORDER BY player",
                (bet_date,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, bet_date, platform, player, game, wager, odds, potential_payout "
                "FROM singles WHERE result IS NULL ORDER BY bet_date, player"
            ).fetchall()

        if not rows:
            return "No pending bets found."

        bets = [{"id": r[0], "date": r[1], "platform": r[2], "player": r[3],
                 "game": r[4], "wager": r[5], "odds": r[6], "to_win": r[7]}
                for r in rows]
        return json.dumps({"pending_count": len(bets), "bets": bets}, indent=2)
    finally:
        conn.close()


def get_bet_history(
    start_date: str = None,
    end_date:   str = None,
    player:     str = None,
) -> str:
    conn = get_db_conn()
    try:
        conds, params = [], []
        if start_date:
            conds.append("bet_date >= ?"); params.append(start_date)
        if end_date:
            conds.append("bet_date <= ?"); params.append(end_date)
        if player:
            conds.append("player LIKE ?"); params.append(f"%{player}%")

        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        rows  = conn.execute(
            f"SELECT bet_date, platform, player, game, wager, odds, "
            f"potential_payout, result, payout FROM singles {where} "
            f"ORDER BY bet_date DESC, player",
            params,
        ).fetchall()

        if not rows:
            return "No bets found matching the criteria."

        bets = [{"date": r[0], "platform": r[1], "player": r[2], "game": r[3],
                 "wager": r[4], "odds": r[5], "to_win": r[6],
                 "result": r[7] or "pending", "payout": r[8]}
                for r in rows]
        return json.dumps({"count": len(bets), "bets": bets}, indent=2)
    finally:
        conn.close()


def log_singles(bet_date: str, platform: str, bets: list, wager: float = 10.0) -> str:
    """
    Log multiple single HR bets at once.
    bets: list of dicts with keys: player, game, odds, potential_payout
    """
    rows = [
        (bet_date, platform.lower(), b["player"], b.get("game"),
         wager, b.get("odds"), b.get("potential_payout"))
        for b in bets
    ]
    conn = get_db_conn()
    try:
        conn.executemany(
            """INSERT INTO singles
               (bet_date, platform, player, game, wager, odds, potential_payout)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()
        return f"Logged {len(rows)} bet(s) on {platform} for {bet_date}"
    finally:
        conn.close()


def record_result(bet_date: str, player: str, result: str, payout: float = None) -> str:
    if result not in ("win", "loss"):
        return f"Error: result must be 'win' or 'loss', got '{result}'"

    conn = get_db_conn()
    try:
        cur = conn.execute(
            "UPDATE singles SET result=?, payout=? WHERE bet_date=? AND player=?",
            (result, payout, bet_date, player),
        )
        conn.commit()
        if cur.rowcount == 0:
            return f"No bet found for {player} on {bet_date}."
        tag = f"  payout=${payout:.2f}" if payout else ""
        return f"Recorded: {player} ({bet_date}) → {result}{tag}"
    finally:
        conn.close()


def get_player_stats(player: str) -> str:
    conn = get_db_conn()
    try:
        rows = conn.execute(
            "SELECT player, result, wager, payout FROM singles "
            "WHERE player LIKE ? AND result IS NOT NULL ORDER BY bet_date",
            (f"%{player}%",),
        ).fetchall()

        if not rows:
            return f"No settled bets found for '{player}'."

        wins     = [r for r in rows if r[1] == "win"]
        wagered  = sum(r[2] for r in rows)
        returned = sum((r[3] or 0) for r in wins)
        net      = returned - wagered

        return json.dumps({
            "player":        rows[0][0],
            "total_bets":    len(rows),
            "wins":          len(wins),
            "losses":        len(rows) - len(wins),
            "win_rate":      f"{len(wins) / len(rows) * 100:.1f}%",
            "total_wagered": f"${wagered:.2f}",
            "net_pnl":       f"${net:+.2f}",
            "roi":           f"{net / wagered * 100:+.1f}%",
        }, indent=2)
    finally:
        conn.close()


# ── Agent ─────────────────────────────────────────────────────────────────────

_SYSTEM = """You are the Bet Tracker Agent for a home run betting system.

Responsibilities:
- Query the bets database for history, P&L, and pending results
- Record win/loss outcomes when asked
- Report accurate per-player and overall statistics

Database — singles table columns:
  id, bet_date, platform, player, game, wager, odds,
  potential_payout, result ('win'/'loss'/NULL), payout, notes

Rules:
- payout = total return (wager + profit) for a win
- Always include both dollar amounts and percentages in summaries
- When no date is provided, report on all available data"""

_TOOL_FNS = {
    "get_pnl_summary":   get_pnl_summary,
    "get_pending_bets":  get_pending_bets,
    "get_bet_history":   get_bet_history,
    "record_result":     record_result,
    "get_player_stats":  get_player_stats,
}


class BetTrackerAgent:
    """Local Ollama agent for DB reads, result recording, and P&L reporting."""

    def __init__(self):
        self.client = get_client()

    def run(self, user_message: str) -> str:
        return run_agent(
            client    = self.client,
            system    = _SYSTEM,
            user_msg  = user_message,
            tools     = _TOOLS,
            tool_fns  = _TOOL_FNS,
            max_tokens= 4096,
        )

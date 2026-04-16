"""
Backtester
Scores every settled bet using reconstructed predictive criteria, then
correlates each factor against actual win/loss outcomes.

Scoring factors (all reconstructed from historical data):
  - barrel_rate    : Statcast barrel % for the season of the bet
  - hard_hit_pct   : Statcast hard hit % for the season of the bet
  - hr_fb_ratio    : HR/FB rate for the season of the bet
  - recent_form    : HRs in the 14 days prior to the bet date (Baseball Savant)
  - odds_tier      : categorised from American odds in DB

Each factor is scored 0-3. Composite score = sum (max 15).
Higher score = stronger pre-bet signal.
"""

import csv
import io
import json
from datetime import date, timedelta

import pandas as pd
import requests
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from .base import get_db_conn

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}
SAVANT_BASE = "https://baseballsavant.mlb.com"


# ── Statcast helpers ──────────────────────────────────────────────────────────

def _fetch_savant_season(player: str, season: int) -> dict:
    """Return Statcast season stats for a batter. Returns {} if not found."""
    url = (
        f"{SAVANT_BASE}/leaderboard/custom"
        f"?year={season}&type=batter&filter=&sort=4&sortDir=desc&min=10"
        f"&selections=barrel_batted_rate,hard_hit_percent,hr_flyballs_rate_batter,"
        f"exit_velocity_avg,sweet_spot_percent"
        f"&chart=false&x=barrel_batted_rate&y=barrel_batted_rate"
        f"&r=no&exactNameSearch=false&csv=true"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        reader  = csv.DictReader(io.StringIO(resp.text))
        search  = player.lower()
        matches = [
            r for r in reader
            if search in (r.get("last_name, first_name") or r.get("player_name") or "").lower()
        ]
        return matches[0] if matches else {}
    except Exception:
        return {}


def _fetch_savant_recent_hrs(player: str, end_date: str, days: int = 14) -> int:
    """Return the number of HRs a player hit in the N days before end_date."""
    end   = date.fromisoformat(end_date)
    start = (end - timedelta(days=days)).isoformat()
    season = end.year

    url = (
        f"{SAVANT_BASE}/leaderboard/custom"
        f"?year={season}&type=batter&filter=&sort=4&sortDir=desc&min=1"
        f"&selections=hr"
        f"&chart=false&x=hr&y=hr&r=no&exactNameSearch=false"
        f"&game_date_gt={start}&game_date_lt={end_date}&csv=true"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        reader  = csv.DictReader(io.StringIO(resp.text))
        search  = player.lower()
        matches = [
            r for r in reader
            if search in (r.get("last_name, first_name") or r.get("player_name") or "").lower()
        ]
        return int(matches[0].get("hr") or 0) if matches else 0
    except Exception:
        return 0


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_barrel_rate(val) -> int:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return 0
    if v >= 15:  return 3
    if v >= 10:  return 2
    if v >=  5:  return 1
    return 0


def _score_hard_hit(val) -> int:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return 0
    if v >= 50:  return 3
    if v >= 45:  return 2
    if v >= 40:  return 1
    return 0


def _score_hr_fb(val) -> int:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return 0
    if v >= 20:  return 3
    if v >= 15:  return 2
    if v >= 10:  return 1
    return 0


def _score_recent_form(hrs: int) -> int:
    if hrs >= 3:  return 3
    if hrs >= 2:  return 2
    if hrs >= 1:  return 1
    return 0


def _score_odds(odds_str: str) -> int:
    """Lower odds = more expected = higher score (market confidence)."""
    try:
        v = int(str(odds_str).replace("+", ""))
    except (TypeError, ValueError):
        return 0
    if v < 250:   return 3
    if v < 350:   return 2
    if v < 450:   return 1
    return 0


def _odds_tier(odds_str: str) -> str:
    try:
        v = int(str(odds_str).replace("+", ""))
    except (TypeError, ValueError):
        return "unknown"
    if v < 250:   return "favorite  (<+250)"
    if v < 350:   return "mid       (+250–+349)"
    if v < 450:   return "long      (+350–+449)"
    return "longshot  (+450+)"


# ── Main backtester ───────────────────────────────────────────────────────────

def run_backtest(verbose: bool = True) -> pd.DataFrame:
    """
    Score every settled bet and return a DataFrame with factor scores + outcome.

    Columns:
      bet_date, player, odds, odds_tier, result, win,
      barrel_rate, hard_hit_pct, hr_fb_ratio,
      score_barrel, score_hard_hit, score_hr_fb, score_recent_form, score_odds,
      composite_score
    """
    conn = get_db_conn()
    try:
        rows = conn.execute(
            "SELECT bet_date, player, odds, result FROM singles "
            "WHERE result IS NOT NULL ORDER BY bet_date, player"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No settled bets found.")
        return pd.DataFrame()

    records = []
    total   = len(rows)

    for i, (bet_date, player, odds, result) in enumerate(rows, 1):
        if verbose:
            print(f"  [{i}/{total}] Scoring {player} ({bet_date})...")

        season      = int(bet_date[:4])
        stats       = _fetch_savant_season(player, season)
        recent_hrs  = _fetch_savant_recent_hrs(player, bet_date, days=14)

        barrel_rate = stats.get("barrel_batted_rate")
        hard_hit    = stats.get("hard_hit_percent")
        hr_fb       = stats.get("hr_flyballs_rate_batter")

        s_barrel    = _score_barrel_rate(barrel_rate)
        s_hard_hit  = _score_hard_hit(hard_hit)
        s_hr_fb     = _score_hr_fb(hr_fb)
        s_form      = _score_recent_form(recent_hrs)
        s_odds      = _score_odds(odds)
        composite   = s_barrel + s_hard_hit + s_hr_fb + s_form + s_odds

        records.append({
            "bet_date":          bet_date,
            "player":            player,
            "odds":              odds,
            "odds_tier":         _odds_tier(odds),
            "result":            result,
            "win":               1 if result == "win" else 0,
            "barrel_rate":       barrel_rate,
            "hard_hit_pct":      hard_hit,
            "hr_fb_ratio":       hr_fb,
            "recent_hrs_14d":    recent_hrs,
            "score_barrel":      s_barrel,
            "score_hard_hit":    s_hard_hit,
            "score_hr_fb":       s_hr_fb,
            "score_recent_form": s_form,
            "score_odds":        s_odds,
            "composite_score":   composite,
        })

    return pd.DataFrame(records)


# ── Report + visualisation ────────────────────────────────────────────────────

def backtest_report(df: pd.DataFrame = None) -> None:
    """
    Print a full backtest report and display charts.
    Pass a pre-computed DataFrame or leave None to run from scratch.
    """
    if df is None:
        df = run_backtest()

    if df.empty:
        print("No data to report.")
        return

    wins   = df["win"].sum()
    total  = len(df)
    print("=" * 55)
    print(f"  BACKTEST REPORT  ({df['bet_date'].min()} → {df['bet_date'].max()})")
    print("=" * 55)
    print(f"  Settled bets : {total}")
    print(f"  Win rate     : {wins}/{total}  ({wins/total*100:.1f}%)")
    print()

    # ── Factor correlations ───────────────────────────────────────────────────
    factor_cols = ["score_barrel", "score_hard_hit", "score_hr_fb",
                   "score_recent_form", "score_odds", "composite_score"]
    print("  FACTOR CORRELATION WITH WIN")
    print("  " + "-" * 40)
    for col in factor_cols:
        if df[col].std() == 0:
            print(f"  {col:<22} : N/A (no variance)")
            continue
        corr = df[col].corr(df["win"])
        bar  = "█" * int(abs(corr) * 20)
        sign = "+" if corr >= 0 else "-"
        print(f"  {col:<22} : {sign}{abs(corr):.3f}  {bar}")
    print()

    # ── Win rate by composite score tier ─────────────────────────────────────
    df["score_tier"] = pd.cut(
        df["composite_score"],
        bins=[-1, 4, 7, 10, 15],
        labels=["0–4 (weak)", "5–7 (moderate)", "8–10 (strong)", "11–15 (elite)"],
    )
    tier_summary = (
        df.groupby("score_tier", observed=True)
        .agg(bets=("win", "count"), wins=("win", "sum"))
        .assign(win_rate=lambda x: x["wins"] / x["bets"] * 100)
    )
    print("  WIN RATE BY COMPOSITE SCORE TIER")
    print("  " + "-" * 40)
    for tier, row in tier_summary.iterrows():
        print(f"  {str(tier):<20} : {int(row['wins'])}/{int(row['bets'])}  "
              f"({row['win_rate']:.0f}% win rate)")
    print()

    # ── Win rate by odds tier ─────────────────────────────────────────────────
    odds_summary = (
        df.groupby("odds_tier")
        .agg(bets=("win", "count"), wins=("win", "sum"))
        .assign(win_rate=lambda x: x["wins"] / x["bets"] * 100)
        .sort_values("win_rate", ascending=False)
    )
    print("  WIN RATE BY ODDS TIER")
    print("  " + "-" * 40)
    for tier, row in odds_summary.iterrows():
        print(f"  {tier.strip():<26} : {int(row['wins'])}/{int(row['bets'])}  "
              f"({row['win_rate']:.0f}% win rate)")
    print()

    # ── Player breakdown ──────────────────────────────────────────────────────
    player_summary = (
        df.groupby("player")
        .agg(bets=("win", "count"), wins=("win", "sum"),
             avg_score=("composite_score", "mean"))
        .assign(win_rate=lambda x: x["wins"] / x["bets"] * 100)
        .sort_values("win_rate", ascending=False)
    )
    print("  PLAYER BREAKDOWN")
    print("  " + "-" * 40)
    for player, row in player_summary.iterrows():
        print(f"  {player:<26} : {int(row['wins'])}/{int(row['bets'])}  "
              f"win rate {row['win_rate']:.0f}%  "
              f"avg score {row['avg_score']:.1f}")
    print()
    print("=" * 55)

    # ── Charts ────────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))

    # Chart 1 — composite score distribution by outcome
    wins_scores   = df[df["win"] == 1]["composite_score"]
    losses_scores = df[df["win"] == 0]["composite_score"]
    axes[0].hist(wins_scores,   bins=range(0, 16), alpha=0.6, color="green",
                 label="Win",  density=True)
    axes[0].hist(losses_scores, bins=range(0, 16), alpha=0.6, color="red",
                 label="Loss", density=True)
    axes[0].set_title("Composite Score Distribution")
    axes[0].set_xlabel("Score (0–15)")
    axes[0].set_ylabel("Density")
    axes[0].legend()

    # Chart 2 — factor correlations bar chart
    corrs = [df[c].corr(df["win"]) for c in factor_cols[:-1]]
    labels = ["Barrel", "Hard Hit", "HR/FB", "Form", "Odds"]
    colors = ["green" if c >= 0 else "red" for c in corrs]
    axes[1].bar(labels, corrs, color=colors, alpha=0.7)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("Factor Correlation with Win")
    axes[1].set_ylabel("Pearson r")
    axes[1].set_ylim(-1, 1)

    # Chart 3 — win rate by composite score tier
    tier_summary_plot = tier_summary[tier_summary["bets"] > 0]
    axes[2].bar(
        range(len(tier_summary_plot)),
        tier_summary_plot["win_rate"],
        color="steelblue", alpha=0.7,
    )
    axes[2].axhline(wins / total * 100, color="orange", linestyle="--",
                    linewidth=1.5, label=f"Overall {wins/total*100:.0f}%")
    axes[2].set_xticks(range(len(tier_summary_plot)))
    axes[2].set_xticklabels(tier_summary_plot.index, rotation=15, ha="right",
                             fontsize=8)
    axes[2].set_title("Win Rate by Score Tier")
    axes[2].set_ylabel("Win Rate (%)")
    axes[2].set_ylim(0, 100)
    axes[2].legend()

    plt.suptitle("Backtest Analysis", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.show()

    return df

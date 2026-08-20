"""
k_predictor.py — Ace: MLB pitcher strikeout prop prediction.

Sibling to agents/predictor.py's Homer (HR model). Same philosophy: gather
real signals, score deterministically, blend in a LightGBM model once one
exists. No LLM involved in ranking.

Reuses Homer's EV/Kelly math and the (Task 1-extended) pitcher recent-form
fetch. Owns its own Statcast fetch, its own odds market (pitcher_strikeouts,
not batter_home_runs), its own DB table (pick_factors_k), and its own site
page — a bug here cannot affect the HR pipeline.
"""
import csv
import io
from datetime import date
from pathlib import Path

import requests

from agents.predictor import (
    SAVANT_BASE, MLB_API_BASE, ODDS_API_BASE, _HEADERS,
    _compute_ev, _compute_kelly, _american_to_implied_prob,
    _fetch_pitcher_recent_form,
)

LEAGUE_AVG_K_PCT = 0.225   # approx. MLB league-average K% (batters), tunable
LEAGUE_AVG_WHIFF = 28.0    # approx. league-average whiff% baseline, tunable


def _project_k(sig: dict) -> float | None:
    """
    Project a starting pitcher's strikeout total for today's start:
    base rate (k_per_9_blended) scaled to expected innings (avg_ip_last3),
    adjusted by how strikeout-prone the opposing lineup is relative to
    league average. Returns None if the base rate or expected innings are
    missing (nothing to project from).
    """
    k9 = sig.get("k_per_9_blended")
    ip = sig.get("avg_ip_last3")
    if k9 is None or ip is None:
        return None

    factors = []
    team_k_pct = sig.get("opp_team_k_pct")
    if team_k_pct is not None:
        factors.append(team_k_pct / LEAGUE_AVG_K_PCT)
    opp_whiff = sig.get("opp_whiff_vs_mix")
    if opp_whiff is not None:
        factors.append(opp_whiff / LEAGUE_AVG_WHIFF)

    combined_factor = sum(factors) / len(factors) if factors else 1.0
    return k9 * (ip / 9) * combined_factor


def _pick_direction(sig: dict, score: float) -> dict | None:
    """
    Decide Over/Under direction and confidence for a pitcher, purely from
    the gap between the projected strikeout total and the market line.
    `score` (from _score_pitcher) is used only as a quality/noise floor —
    it does not affect direction, confidence, or ranking order.
    Returns None if the pitcher is ineligible for a pick today.
    """
    if score < 2.0:
        return None

    projected_k = _project_k(sig)
    k_line = sig.get("k_line")
    if projected_k is None or k_line is None:
        return None

    gap = projected_k - k_line
    if abs(gap) < 0.25:
        return None

    direction = "OVER" if gap > 0 else "UNDER"

    abs_gap = abs(gap)
    if abs_gap >= 1.5:
        confidence = "HIGH"
    elif abs_gap >= 0.75:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "direction": direction,
        "confidence": confidence,
        "projected_k": projected_k,
        "gap": gap,
    }


def _fetch_pitcher_k_statcast() -> dict:
    """
    Fetch the full Statcast pitcher K-rate leaderboard CSV, keyed by
    player_id (primary) and lowercased name (secondary). Columns:
    k_percent, whiff_percent, csw_percent, swinging_strike_percent.
    Caches to cache/statcast_pitcher_k_YYYY-MM-DD.csv (one fetch per day).
    """
    season    = date.today().year
    today_str = date.today().isoformat()
    cache_path = Path(__file__).parent.parent / "cache" / f"statcast_pitcher_k_{today_str}.csv"

    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8")
    else:
        url = (
            f"{SAVANT_BASE}/leaderboard/custom"
            f"?year={season}&type=pitcher&filter=&sort=4&sortDir=desc&min=5"
            f"&selections=k_percent,whiff_percent,csw_percent,swinging_strike_percent"
            f"&chart=false&r=no&exactNameSearch=false&csv=true"
        )
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            text = resp.text.lstrip('﻿')
            cache_path.parent.mkdir(exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        except Exception:
            return {}

    try:
        reader = csv.DictReader(io.StringIO(text))
        result = {}
        for row in reader:
            name = (row.get("last_name, first_name") or row.get("player_name") or "").lower()
            pid_raw = row.get("player_id") or row.get("pitcher") or ""
            try:
                result[int(pid_raw)] = row
            except (ValueError, TypeError):
                pass
            if name:
                result.setdefault(name, row)
        return result
    except Exception:
        return {}


def _fetch_team_k_pct(team_id: int) -> float | None:
    """
    Fetch a team's season strikeOuts / plateAppearances from MLB Stats API
    season hitting stats. Returns None on any missing field or request
    failure. No caching here — Ace._gather_data caches per-call-site via
    a local dict since this is only called once per unique opposing team
    per run (~30 calls max on a full slate).
    """
    year = date.today().year
    try:
        resp = requests.get(
            f"{MLB_API_BASE}/teams/{team_id}/stats",
            params={"stats": "season", "group": "hitting", "season": year},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        stat = data["stats"][0]["splits"][0]["stat"]
        strikeouts = stat.get("strikeOuts")
        plate_appearances = stat.get("plateAppearances")
        if not strikeouts or not plate_appearances:
            return None
        return round(strikeouts / plate_appearances, 4)
    except Exception:
        return None


# Pitch type code → bucket, same taxonomy as predictor.py's _PITCH_BUCKETS.
_PITCH_BUCKETS_K = {
    "FF": "fastball", "SI": "fastball", "FC": "fastball",
    "SL": "breaking", "CU": "breaking", "KC": "breaking", "ST": "breaking",
    "SV": "breaking", "CS": "breaking",
    "CH": "offspeed", "FS": "offspeed", "SC": "offspeed",
    "FO": "offspeed", "KN": "offspeed",
}


def _fetch_pitch_arsenal_whiff(player_ids: list[int], player_type: str) -> dict[int, dict]:
    """
    Fetch whiff% by pitch-type bucket (fastball/breaking/offspeed) from
    Savant's pitch-arsenal-stats leaderboard, PA-weighted per bucket.

    player_type="pitcher": each pitcher's own whiff% generated by the pitch
    types he throws (a "does he have a wipeout pitch" signal).
    player_type="batter": each batter's whiff% against each pitch-type
    bucket (used to build the opposing-lineup matchup signal).

    Returns {player_id: {"whiff_fastball": float|None, "whiff_breaking": ...,
    "whiff_offspeed": ...}}. Early season: sparse buckets return None for
    that key rather than being omitted from the dict.
    """
    if not player_ids:
        return {}
    year = date.today().year
    try:
        resp = requests.get(
            f"{SAVANT_BASE}/leaderboard/pitch-arsenal-stats"
            f"?type={player_type}&year={year}&team=&min=1&csv=true",
            timeout=30,
            headers=_HEADERS,
        )
        resp.raise_for_status()
        text = resp.text.lstrip('﻿')
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception:
        return {}

    def _sf(val):
        if val in (None, "", "null"):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    player_id_set = {int(p) for p in player_ids}
    accum: dict[int, dict[str, list[tuple[float, float]]]] = {}
    for row in rows:
        pid_raw = row.get("player_id")
        if pid_raw is None:
            continue
        try:
            pid = int(pid_raw)
        except (ValueError, TypeError):
            continue
        if pid not in player_id_set:
            continue

        bucket = _PITCH_BUCKETS_K.get(row.get("pitch_type"))
        if bucket is None:
            continue
        whiff = _sf(row.get("whiff_percent"))
        pa = _sf(row.get("pa"))
        if whiff is None or not pa:
            continue
        accum.setdefault(pid, {}).setdefault(bucket, []).append((whiff, pa))

    result: dict[int, dict] = {}
    for pid, buckets in accum.items():
        splits = {}
        for key, bucket in (("whiff_fastball", "fastball"),
                             ("whiff_breaking", "breaking"),
                             ("whiff_offspeed", "offspeed")):
            samples = buckets.get(bucket)
            if not samples:
                splits[key] = None
                continue
            total_pa = sum(pa for _, pa in samples)
            splits[key] = sum(w * pa for w, pa in samples) / total_pa if total_pa else None
        if any(v is not None for v in splits.values()):
            result[pid] = splits
    return result


def _fetch_pitcher_pitch_mix(pitcher_ids: list[int]) -> dict[int, dict]:
    """
    Fetch each pitcher's pitch-mix usage fractions (fastball/breaking/
    offspeed, summing to ~1.0) from the same Savant pitch-arsenal-stats
    leaderboard _fetch_pitch_arsenal_whiff reads, using the `pa` column as
    a usage proxy instead of whiff%. Feeds _weighted_opp_whiff's
    `pitcher_mix` argument.

    Returns {player_id: {"fastball": float, "breaking": float, "offspeed": float}}.
    Pitchers with zero total PA across the three buckets are omitted.
    """
    if not pitcher_ids:
        return {}
    year = date.today().year
    try:
        resp = requests.get(
            f"{SAVANT_BASE}/leaderboard/pitch-arsenal-stats"
            f"?type=pitcher&year={year}&team=&min=1&csv=true",
            timeout=30,
            headers=_HEADERS,
        )
        resp.raise_for_status()
        text = resp.text.lstrip('﻿')
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception:
        return {}

    def _sf(val):
        if val in (None, "", "null"):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    pitcher_id_set = {int(p) for p in pitcher_ids}
    accum: dict[int, dict[str, float]] = {}
    for row in rows:
        pid_raw = row.get("player_id")
        if pid_raw is None:
            continue
        try:
            pid = int(pid_raw)
        except (ValueError, TypeError):
            continue
        if pid not in pitcher_id_set:
            continue
        bucket = _PITCH_BUCKETS_K.get(row.get("pitch_type"))
        if bucket is None:
            continue
        pa = _sf(row.get("pa"))
        if not pa:
            continue
        accum.setdefault(pid, {}).setdefault(bucket, 0.0)
        accum[pid][bucket] += pa

    result: dict[int, dict] = {}
    for pid, buckets in accum.items():
        total = sum(buckets.values())
        if not total:
            continue
        result[pid] = {
            "fastball": buckets.get("fastball", 0.0) / total,
            "breaking": buckets.get("breaking", 0.0) / total,
            "offspeed": buckets.get("offspeed", 0.0) / total,
        }
    return result


def _weighted_opp_whiff(pitcher_mix: dict, batter_splits: list[dict]) -> float | None:
    """
    Combine a pitcher's pitch-mix usage (fractions summing to ~1.0, keys
    "fastball"/"breaking"/"offspeed") with each confirmed opposing batter's
    whiff-by-bucket splits into one matchup scalar: for each batter, sum
    their bucket whiff% weighted by the pitcher's usage of that bucket,
    then average across the lineup. Returns None for an empty lineup.
    """
    if not batter_splits:
        return None
    per_batter = []
    for splits in batter_splits:
        total = 0.0
        for bucket_key, mix_key in (("whiff_fastball", "fastball"),
                                     ("whiff_breaking", "breaking"),
                                     ("whiff_offspeed", "offspeed")):
            val = splits.get(bucket_key)
            if val is None:
                continue
            total += val * pitcher_mix.get(mix_key, 0.0)
        per_batter.append(total)
    if not per_batter:
        return None
    return round(sum(per_batter) / len(per_batter), 2)


def _score_pitcher(sig: dict) -> float:
    """
    Score a starting pitcher 0-∞ for strikeout prop value. Higher = better
    K pick today. Deterministic — no LLM involved. Thresholds are seeded
    from published K-prop research (MLB average K% ~22-23%, whiff% ~24-25%,
    CSW% ~29%, SwStr% ~11%) and are meant to be tuned later via
    optimize_weights_k.py's correlation report once labeled data exists.
    """
    score = 0.0

    k_pct = sig.get("k_percent")
    if k_pct is not None:
        if k_pct >= 30: score += 4
        elif k_pct >= 27: score += 3
        elif k_pct >= 24: score += 2
        elif k_pct >= 21: score += 1
        elif k_pct < 18: score -= 1

    whiff = sig.get("whiff_percent")
    if whiff is not None:
        if whiff >= 32: score += 3
        elif whiff >= 28: score += 2
        elif whiff >= 25: score += 1
        elif whiff < 20: score -= 1

    csw = sig.get("csw_percent")
    if csw is not None:
        if csw >= 33: score += 2
        elif csw >= 30: score += 1
        elif csw < 26: score -= 1

    swstr = sig.get("swinging_strike_percent")
    if swstr is not None:
        if swstr >= 14: score += 2
        elif swstr >= 12: score += 1
        elif swstr < 9: score -= 1

    k9 = sig.get("k_per_9_blended")
    if k9 is not None:
        if k9 >= 11: score += 4
        elif k9 >= 9.5: score += 3
        elif k9 >= 8: score += 2
        elif k9 >= 6.5: score += 1
        elif k9 < 5: score -= 1

    for key in ("pitcher_whiff_fastball", "pitcher_whiff_breaking", "pitcher_whiff_offspeed"):
        val = sig.get(key)
        if val is None:
            continue
        if val >= 35: score += 1
        elif val < 20: score -= 0.5

    opp_whiff = sig.get("opp_whiff_vs_mix")
    if opp_whiff is not None:
        if opp_whiff >= 27: score += 3
        elif opp_whiff >= 24: score += 2
        elif opp_whiff >= 21: score += 1
        elif opp_whiff < 17: score -= 1

    avg_ip = sig.get("avg_ip_last3")
    if avg_ip is not None:
        if avg_ip >= 6.0: score += 2
        elif avg_ip >= 5.5: score += 1
        elif avg_ip < 4.5: score -= 2

    avg_pitches = sig.get("avg_pitches_last3")
    if avg_pitches is not None:
        if avg_pitches >= 95: score += 1
        elif avg_pitches < 80: score -= 1

    rest = sig.get("days_rest")
    if rest is not None:
        if rest <= 3: score -= 2
        elif rest == 4: score -= 1
        elif 5 <= rest <= 7: pass
        elif 8 <= rest <= 10: score += 0.5
        else: score -= 1  # >10 days — likely rust from an extended layoff

    ev = sig.get("ev_10")
    if ev is not None:
        if ev > 3: score += 5
        elif ev > 1: score += 3
        elif ev > 0: score += 1
        elif ev > -1: score -= 1
        else: score -= 3

    return score
import json
import os


def _fmt_odds(o: int | None) -> str:
    if o is None:
        return "—"
    return f"+{o}" if o > 0 else str(o)


def fetch_k_odds_comparison(confirmed_pitcher_names: set | None = None) -> str:
    """
    Fetch pitcher strikeout O/U prop odds from all available sportsbooks via
    The Odds API's pitcher_strikeouts market. Same Pinnacle-benchmark, EV,
    Kelly, and value-edge math as Homer's fetch_odds_comparison, but reads
    outcome["point"] as the real strikeout line (not a fixed 0.5 threshold)
    and only considers "Over" outcomes as the tracked pick side.
    """
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        return json.dumps({"status": "no_api_key", "message": "ODDS_API_KEY not set in api/.env"})

    today = date.today().isoformat()
    cache_path = Path("cache") / f"k_odds_{today}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if cached.get("status") == "success":
                return cache_path.read_text()
        except Exception:
            pass

    try:
        events_resp = requests.get(f"{ODDS_API_BASE}/sports/baseball_mlb/events?apiKey={api_key}", timeout=15)
        events_resp.raise_for_status()
        events = events_resp.json()
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    if not events:
        return json.dumps({"status": "no_events", "message": "No MLB events found today."})

    all_player_odds: dict[str, dict] = {}
    for event in events[:12]:
        event_id = event.get("id")
        matchup = f"{event.get('away_team', '')} @ {event.get('home_team', '')}"
        try:
            resp = requests.get(
                f"{ODDS_API_BASE}/sports/baseball_mlb/events/{event_id}/odds"
                f"?apiKey={api_key}&regions=us,eu&markets=pitcher_strikeouts&oddsFormat=american",
                timeout=15,
            )
            if resp.status_code in (401, 422):
                continue
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue

        for bookmaker in data.get("bookmakers", []):
            book_title = bookmaker.get("title", bookmaker.get("key", ""))
            is_pinnacle = bookmaker.get("key") == "pinnacle"
            for market in bookmaker.get("markets", []):
                if market.get("key") != "pitcher_strikeouts":
                    continue
                for outcome in market.get("outcomes", []):
                    if outcome.get("name") != "Over":
                        continue
                    player_name = (outcome.get("description") or "").strip()
                    price = outcome.get("price")
                    point = outcome.get("point")
                    if not player_name or price is None or point is None:
                        continue

                    if confirmed_pitcher_names is not None and player_name not in confirmed_pitcher_names:
                        continue

                    entry = all_player_odds.setdefault(player_name, {"matchup": matchup, "books": {}, "pinnacle": None, "k_line": point})
                    existing = entry["books"].get(book_title)
                    if existing is None or price > existing:
                        entry["books"][book_title] = price
                    if is_pinnacle:
                        curr = entry["pinnacle"]
                        if curr is None or price > curr:
                            entry["pinnacle"] = price

    if not all_player_odds:
        return json.dumps({"status": "no_data", "message": "No strikeout prop data returned yet."})

    results = []
    for player_name, info in all_player_odds.items():
        books = info["books"]
        if not books:
            continue
        probs = {book: _american_to_implied_prob(odds) for book, odds in books.items()}
        consensus_prob = sum(probs.values()) / len(probs)
        best_book = max(books, key=lambda b: books[b])
        best_odds_int = books[best_book]
        best_prob = probs[best_book]
        value_edge = consensus_prob - best_prob

        pinnacle_odds = info["pinnacle"]
        pinnacle_prob = _american_to_implied_prob(pinnacle_odds) if pinnacle_odds else None
        true_prob = pinnacle_prob if pinnacle_prob is not None else consensus_prob

        results.append({
            "player": player_name,
            "matchup": info["matchup"],
            "k_line": info["k_line"],
            "books_sampled": len(books),
            "pinnacle": _fmt_odds(pinnacle_odds),
            "pinnacle_prob": f"{pinnacle_prob * 100:.1f}%" if pinnacle_prob else f"{consensus_prob * 100:.1f}% (consensus)",
            "best_book": best_book,
            "best_odds": _fmt_odds(best_odds_int),
            "consensus_prob": f"{consensus_prob * 100:.1f}%",
            "value_edge": round(value_edge * 100, 1),
            "value_flag": "VALUE" if value_edge >= 0.03 else "",
            "ev_10": _compute_ev(true_prob, best_odds_int),
            "kelly_size": _compute_kelly(true_prob, best_odds_int),
            "all_books": {book: _fmt_odds(o) for book, o in sorted(books.items(), key=lambda x: x[1], reverse=True)},
        })

    results.sort(key=lambda x: x["value_edge"], reverse=True)
    out = json.dumps({"status": "success", "players_found": len(results), "comparisons": results}, indent=2)

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(out)
    except Exception:
        pass

    return out


class Ace:
    """
    Sibling to Homer — ranks starting pitchers for strikeout props.
    Deterministic scoring (_score_pitcher) with an ML blend once
    ml_weights_k.json / lgbm_model_k.txt exist (mirrors Homer's blend).
    """

    _ml_weights = None
    _ml_weights_loaded = False
    _ml_booster = None

    def __init__(self):
        self._context = None

    @staticmethod
    def _ml_score(sig: dict) -> float | None:
        """Score a signal dict with the trained LightGBM K-model. Returns
        None if ml_weights_k.json / lgbm_model_k.txt don't exist yet
        (cold start) — mirrors Homer._ml_score's fallback behavior."""
        from ml.optimize_weights_k import FEATURE_NAMES_K, WEIGHTS_PATH_K, LGBM_MODEL_PATH_K

        if not Ace._ml_weights_loaded:
            Ace._ml_weights_loaded = True
            weights_path = Path(WEIGHTS_PATH_K)
            model_path = Path(LGBM_MODEL_PATH_K)
            if weights_path.exists() and model_path.exists():
                try:
                    import lightgbm as lgb
                    Ace._ml_weights = json.loads(weights_path.read_text())
                    Ace._ml_booster = lgb.Booster(model_file=str(model_path))
                except Exception:
                    Ace._ml_weights = None
                    Ace._ml_booster = None

        if Ace._ml_weights is None or Ace._ml_booster is None:
            return None

        row = [sig.get(name) if sig.get(name) is not None else 0.0 for name in FEATURE_NAMES_K]
        try:
            pred = Ace._ml_booster.predict([row])[0]
            return float(pred) * 20.0  # scale probability [0,1] to score range, matches Homer's convention
        except Exception:
            return None

    def _gather_data(self) -> dict:
        """
        Fetch confirmed starting pitchers, their Statcast K-rate + pitch-mix
        signals, opposing-lineup matchup whiff, recent form/workload/rest,
        and odds. Only pitchers with a CONFIRMED starting assignment are
        included — no roster-fallback concept for starters (see spec).
        Result cached on the instance.
        """
        if self._context:
            return self._context

        today = date.today().isoformat()
        resp = requests.get(
            f"{MLB_API_BASE}/schedule",
            params={"sportId": 1, "date": today, "hydrate": "probablePitcher,lineups(person),team"},
            timeout=15,
        )
        resp.raise_for_status()
        schedule = resp.json()

        confirmed_names = set()
        starters = []  # [(pitcher_id, name, matchup, opposing_lineup_ids, opp_team_id)]
        for date_block in schedule.get("dates", []):
            for game in date_block.get("games", []):
                teams = game.get("teams", {})
                away = teams.get("away", {})
                home = teams.get("home", {})
                lineup_data = game.get("lineups", {})
                matchup = f"{away.get('team', {}).get('name', '')} @ {home.get('team', {}).get('name', '')}"
                for side_key, opp_side_key, opp_lineup_key in (
                    ("away", "home", "homePlayers"),
                    ("home", "away", "awayPlayers"),
                ):
                    side = teams.get(side_key, {})
                    opp_side = teams.get(opp_side_key, {})
                    pitcher = side.get("probablePitcher")
                    if not pitcher or not pitcher.get("id"):
                        continue
                    opp_lineup_ids = [p["id"] for p in lineup_data.get(opp_lineup_key, []) if p.get("id")]
                    opp_team_id = opp_side.get("team", {}).get("id")
                    starters.append((pitcher["id"], pitcher.get("fullName", ""), matchup, opp_lineup_ids, opp_team_id))
                    confirmed_names.add(pitcher.get("fullName", ""))

        pitcher_ids = [pid for pid, *_ in starters]
        opp_batter_ids = sorted({bid for _pid, _name, _matchup, opp_ids, _team_id in starters for bid in opp_ids})
        k_statcast = _fetch_pitcher_k_statcast()
        pitcher_whiff = _fetch_pitch_arsenal_whiff(pitcher_ids, player_type="pitcher")
        pitcher_mix = _fetch_pitcher_pitch_mix(pitcher_ids)
        batter_whiff = _fetch_pitch_arsenal_whiff(opp_batter_ids, player_type="batter")
        odds_raw = json.loads(fetch_k_odds_comparison(confirmed_names))
        odds_by_player = {c["player"]: c for c in odds_raw.get("comparisons", [])}

        team_k_pct_cache: dict[int, float | None] = {}

        pitcher_signals = {}
        for pid, name, matchup, opp_lineup_ids, opp_team_id in starters:
            statcast_row = k_statcast.get(pid) or k_statcast.get(name.lower(), {})
            form = _fetch_pitcher_recent_form(pid)
            whiff_splits = pitcher_whiff.get(pid, {})
            odds_entry = odds_by_player.get(name, {})
            batter_splits = [batter_whiff[bid] for bid in opp_lineup_ids if bid in batter_whiff]
            opp_whiff_vs_mix = _weighted_opp_whiff(pitcher_mix.get(pid, {}), batter_splits)

            opp_team_k_pct = None
            if opp_team_id is not None:
                if opp_team_id not in team_k_pct_cache:
                    team_k_pct_cache[opp_team_id] = _fetch_team_k_pct(opp_team_id)
                opp_team_k_pct = team_k_pct_cache[opp_team_id]

            sig = {
                "k_percent": _tofloat(statcast_row.get("k_percent")),
                "whiff_percent": _tofloat(statcast_row.get("whiff_percent")),
                "csw_percent": _tofloat(statcast_row.get("csw_percent")),
                "swinging_strike_percent": _tofloat(statcast_row.get("swinging_strike_percent")),
                "k_per_9_blended": form.get("k_per_9_blended"),
                "avg_ip_last3": form.get("avg_ip_last3"),
                "avg_pitches_last3": form.get("avg_pitches_last3"),
                "days_rest": form.get("days_rest"),
                "pitcher_whiff_fastball": whiff_splits.get("whiff_fastball"),
                "pitcher_whiff_breaking": whiff_splits.get("whiff_breaking"),
                "pitcher_whiff_offspeed": whiff_splits.get("whiff_offspeed"),
                "opp_whiff_vs_mix": opp_whiff_vs_mix,
                "opp_team_k_pct": opp_team_k_pct,
                "ev_10": odds_entry.get("ev_10"),
                "value_edge": odds_entry.get("value_edge"),
                "kelly_size": odds_entry.get("kelly_size"),
                "pinnacle_odds": odds_entry.get("pinnacle"),
                "k_line": odds_entry.get("k_line"),
                "matchup": matchup,
            }
            pitcher_signals[name] = sig

        self._context = {"date": today, "pitcher_signals": pitcher_signals}
        return self._context

    def _rank_picks_python(self, pitcher_signals: dict, top_n: int = 10) -> list:
        ranked = []
        for name, sig in pitcher_signals.items():
            raw_score = _score_pitcher(sig)
            ml = Ace._ml_score(sig)
            if ml is not None and Ace._ml_weights:
                auc = Ace._ml_weights.get("cv_auc_mean", 0.5)
                ml_weight = min(0.7, max(0.0, (auc - 0.5) * 2.5))
                score = (1.0 - ml_weight) * raw_score + ml_weight * ml
            else:
                score = raw_score

            direction_info = _pick_direction(sig, score)
            if direction_info is None:
                continue

            ranked.append({
                "pitcher": name,
                "matchup": sig.get("matchup", ""),
                "direction": direction_info["direction"],
                "confidence": direction_info["confidence"],
                "projected_k": direction_info["projected_k"],
                "gap": direction_info["gap"],
                "reasoning": _build_reasoning(
                    name, sig, direction_info["direction"], direction_info["projected_k"]
                ),
                "score": score,
                "signals": sig,
            })
        ranked.sort(key=lambda p: abs(p["gap"]), reverse=True)
        return ranked[:top_n]

    def get_picks_json(self, top_n: int = 10) -> list:
        """Return today's top strikeout picks as a structured list of dicts."""
        context = self._gather_data()
        return self._rank_picks_python(context.get("pitcher_signals", {}), top_n=top_n)


def _tofloat(val):
    if val in (None, "", "null"):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _build_reasoning(name: str, sig: dict, direction: str, projected_k: float) -> str:
    k_line = sig.get("k_line")
    lean = "Over" if direction == "OVER" else "Under"
    parts = [f"Projects for {projected_k:.1f} K vs a {k_line:.1f} line — lean {lean}."]
    if sig.get("k_per_9_blended") is not None:
        parts.append(f"{sig['k_per_9_blended']:.1f} K/9 (blended)")
    if sig.get("avg_ip_last3") is not None:
        parts.append(f"{sig['avg_ip_last3']:.1f} IP/start last 3")
    return f"{name}: " + " ".join(parts[:1]) + (", " + ", ".join(parts[1:]) if len(parts) > 1 else "")

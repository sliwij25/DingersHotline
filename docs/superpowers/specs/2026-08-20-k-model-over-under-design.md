# K Model Over/Under Direction — Design Spec

**Date:** 2026-08-20
**Scope:** Sub-project 1 of 4 (Over/Under logic → Strikeout Leaders page →
K hit-rate pipeline+page → site nav reorg). This spec covers only Over/Under.

## Problem

The strikeout (K) model currently only ever recommends betting the Over on
a pitcher's strikeout prop line, regardless of his actual signals relative
to that line. `fetch_k_odds_comparison()` in `agents/k_predictor.py`
explicitly discards all non-"Over" outcomes from the odds API response, and
`_score_pitcher()` produces a single additive quality scalar with no
directional (Over vs. Under) branching — a low score just means "skip this
pitcher," never "bet Under on this pitcher." A strikeout line is a
threshold bet (e.g. "Over/Under 5.5 Ks"), so judging it requires an actual
projected strikeout number to compare against the line — not just a
relative quality score.

## Goal

The model should recommend Over or Under per pitcher based on where a
projected strikeout total falls relative to the market line, with
confidence driven by the size of that gap.

## Non-goals (explicitly out of scope for this spec)

- Odds/price/EV/Kelly display or computation for either side. The user
  does not trust odds extraction reliability yet; confidence is
  projection-only. `ev_10` / `value_edge` / `kelly_size` / `pinnacle_odds`
  are no longer read anywhere in `_rank_picks_python` or the card
  renderer, on either the Over or Under side.
- Any UI beyond the existing merged, tiered `strikeouts.html` page (no
  separate Over/Under sections — see Design below).
- Strikeout Leaders page, K hit-rate tracking/page, and site nav reorg —
  each is its own follow-on spec.

## Design

### 1. New signal: opponent team strikeout rate

Add `_fetch_team_k_pct(team_id: int) -> float | None` to
`agents/k_predictor.py`:

- Calls MLB Stats API: `GET /api/v1/teams/{team_id}/stats?stats=season&group=hitting&season={current_year}`
- Computes `strikeOuts / plateAppearances` from the season hitting totals.
- Returns `None` on any missing field or request failure.
- Cached per team per process run (module-level dict keyed by `team_id`) —
  at most ~30 calls total across a full slate (one per team), not one per
  pitcher.

`_gather_data()`'s schedule-parsing loop currently extracts only
`opp_lineup_ids` (opposing batter IDs) per starter. It must also capture
the opposing team's numeric `id` (already present in the hydrated
`teams.away.team` / `teams.home.team` payload alongside the `name` field
already read) so `_fetch_team_k_pct()` can be called per starter's
opponent.

### 2. Projection formula

New module-level constants in `agents/k_predictor.py`:

```python
LEAGUE_AVG_K_PCT = 0.225   # approx. MLB league-average K% (batters), tunable
LEAGUE_AVG_WHIFF = 28.0    # approx. league-average whiff% baseline, tunable
```

New function `_project_k(sig: dict) -> float | None`:

```python
def _project_k(sig: dict) -> float | None:
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
```

`sig["opp_team_k_pct"]` is a new field populated in `_gather_data()` from
`_fetch_team_k_pct(opp_team_id)`, alongside the existing `opp_whiff_vs_mix`.

### 3. Direction, eligibility, and confidence

New function `_pick_direction(sig: dict, score: float) -> dict | None` in
`agents/k_predictor.py`, called from `_rank_picks_python()` in place of the
current score-only ranking:

- **Quality floor:** pitcher must have `score >= 2.0` (using the existing
  `_score_pitcher()` value) to be eligible at all. This reuses the score
  purely as a noise/bad-matchup filter — it no longer drives ranking or
  confidence.
- **Projection required:** `_project_k(sig)` must return a value, and
  `sig.get("k_line")` must not be `None`. Pitchers missing either are
  excluded (no projection or nothing to compare against).
- **Minimum edge:** `gap = projected_k - k_line`. If `abs(gap) < 0.25`,
  exclude (no meaningful edge in either direction).
- **Direction:** `"OVER"` if `gap > 0` else `"UNDER"`.
- **Confidence tier**, by `abs(gap)`:
  - `HIGH`: `>= 1.5`
  - `MEDIUM`: `>= 0.75`
  - `LOW`: `>= 0.25`
- **Ranking:** eligible pitchers are sorted by `abs(gap)` descending
  (biggest edge first, regardless of direction), then truncated to
  `top_n` — replacing today's sort-by-`score` in `_rank_picks_python()`.

**Starting pitchers only:** already enforced — `_gather_data()` only
builds signals for pitchers with a confirmed `probablePitcher` assignment
from the MLB schedule (no roster-fallback concept for starters, per the
existing class docstring). No change needed; this spec preserves that
constraint.

`_rank_picks_python()` changes: for each pitcher, compute `raw_score` /
`ml`-blended `score` as today (still needed for the quality floor and for
the ML blend's existing cold-start behavior), then call `_pick_direction`.
Skip the pitcher if it returns `None`. Otherwise emit:

```python
{
    "pitcher": name,
    "matchup": sig.get("matchup", ""),
    "direction": direction,          # "OVER" | "UNDER"
    "confidence": tier,              # "HIGH" | "MEDIUM" | "LOW"
    "projected_k": projected_k,
    "gap": gap,
    "reasoning": _build_reasoning(name, sig, direction, projected_k),
    "score": score,
    "signals": sig,
}
```

Final list is sorted by `abs(gap)` descending and sliced to `top_n`.

`_build_reasoning()` gains a `direction: str` and `projected_k: float`
parameter and produces text like:
`"Gerrit Cole: Projects for 7.8 K vs a 5.5 line — lean Over. 9.4 K/9 (blended), 6.1 IP/start last 3."`

`_confidence_tier(score)` (score-based) is no longer called from
`_rank_picks_python()` — confidence now comes from `_pick_direction`'s
gap-based tiering. The function can remain unused/removed; removing it is
preferred (YAGNI) since nothing else calls it.

### 4. Card / UI changes

`tools/generate_html.py`'s `_build_k_card(rank, pick)`:

- Replace the current plain `<span class="tag tag-dim">O/U {k_line}</span>`
  tag with a direction badge in the same visual slot as the existing
  `conf-badge`, next to the player name:
  `<span class="dir-badge dir-over">OVER</span>` (green, reuses
  `tag-green`'s color values) or
  `<span class="dir-badge dir-under">UNDER</span>` (red, reuses
  `tag-red`'s color values). New CSS classes `.dir-badge`, `.dir-over`,
  `.dir-under` added to the page's `<style>` block, styled like the
  existing `.conf-badge` variants.
- Add a new stat card to `stats_row` (alongside K%, Whiff%, CSW%, K/9 L3):
  `Proj. K` showing `projected_k` formatted to 1 decimal, and change the
  existing line display to `Line {k_line}` so the two sit side by side —
  e.g. `Proj. K: 7.8` and `Line: 5.5`.
- No odds/price/EV/book fields are read or rendered (none are today
  either — confirmed by reading the current card renderer — so this is a
  no-op removal, not a UI regression).
- `generate_k_picks_html()`'s tier bucketing (`_K_TIER_LABELS`,
  `_K_TIER_ORDER`) is unchanged — it already buckets by `pick["confidence"]`,
  which will now come from `_pick_direction`'s gap-based tier instead of
  the old score-based tier. One merged, ranked list — Over and Under picks
  mixed together within each confidence tier, exactly as today's Over-only
  picks are.

### 5. Testing

- Unit-test `_project_k()` with representative signal dicts: full data
  (both factors present), missing `opp_team_k_pct`, missing
  `opp_whiff_vs_mix`, missing both (factor defaults to `1.0`), and missing
  `k_per_9_blended`/`avg_ip_last3` (returns `None`).
- Unit-test `_pick_direction()`: gap above/below each tier threshold,
  gap below the `0.25` minimum-edge cutoff (excluded), missing
  `k_line` (excluded), score below the `2.0` floor (excluded).
- Manual verification: run `python scripts/daily_picks.py --use-cache`
  after implementation and inspect `docs/strikeouts.html` for a mix of
  OVER/UNDER badges across the tiers (not always Over), and confirm no
  odds/price text appears on any K card.

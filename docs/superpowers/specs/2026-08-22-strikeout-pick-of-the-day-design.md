# Strikeout Pick of the Day — Design Spec

## Purpose

The site's "Strikeouts" nav group currently has a disabled "Pick of the Day" stub
(`k-potd` leaf, `href=None` in `_NAV_GROUPS`). This spec un-stubs it by building a
full strikeout ("Ace" model) equivalent of the existing HR Pick of the Day /
Player Deep Dive page pair, so the site has matching depth for both prop types.

Two new pages ship together:

1. `docs/strikeout-pick-of-the-day.html` — features today's single top strikeout
   pick with a signal summary. Parallel to `docs/pick-of-the-day.html`.
2. `docs/k-player-card.html` — full per-pitcher signal deep dive, reached by
   clicking any pitcher tile on `docs/strikeouts.html` or the POTD page.
   Parallel to `docs/player-card.html`.

## Data Source

New JSON export: `docs/k-player-data.json`, written by a new function
`generate_k_player_data_json(picks: list[dict], today: str) -> str` in
`tools/generate_html.py`, mirroring `generate_player_data_json` (line 139).

Each entry is keyed by `slug` (via the existing `_player_slug()` helper, reused
as-is — it's name-based, not batter-specific) so both new pages can fetch the
same file: the POTD page takes the top-ranked entry, the deep-dive page looks
up by `?player={slug}` query param, falling back to entry 0 if not found —
same pattern as the HR pages.

Entry shape, drawn from `agents/k_predictor.py`'s pick dict (`_rank_picks_python`,
line ~708) and its `sig` dict (line 682):

```json
{
  "slug": "...",
  "pitcher": "...",
  "rank": 1,
  "score": 0.0,
  "confidence": "HIGH|MEDIUM|LOW",
  "matchup": "...",
  "direction": "OVER|UNDER",
  "projected_k": 0.0,
  "gap": 0.0,
  "game_time_et": "7:05 PM ET",
  "reasoning": "...",
  "signals": {
    "venue": null,
    "pitcher_throws": null,
    "k_line": null,
    "k_percent": null,
    "whiff_percent": null,
    "csw_percent": null,
    "swinging_strike_percent": null,
    "k_per_9_blended": null,
    "avg_ip_last3": null,
    "avg_pitches_last3": null,
    "days_rest": null,
    "pitcher_whiff_fastball": null,
    "pitcher_whiff_breaking": null,
    "pitcher_whiff_offspeed": null,
    "opp_whiff_vs_mix": null,
    "opp_team_k_pct": null,
    "pinnacle_odds": null
  }
}
```

`game_time_et` is computed the same way `generate_player_data_json` computes it
(line 145-153): parse `sig.get("game_time")` as ISO 8601, convert to
`America/New_York` via `zoneinfo`, format as `"%-I:%M %p ET"`. `venue` and
`pitcher_throws` are read straight from the sig dict (see "Pitcher Signal Gap
Fix" below) — same pattern as the HR `signals.venue` / `signals.pitcher_throws`
fields.

**Venue / game time / pitcher throws (now in scope — see "Pitcher Signal Gap
Fix" below):** the K sig dict previously had no `venue`, `game_time`, or
`pitcher_throws` fields, unlike the HR sig dict. These are added as part of
this spec, so the hero banner on both new pages shows the same
venue/game-time line the HR pages show, plus a pitcher-handedness badge.
`ev_10`, `value_edge`, and `kelly_size` exist in the sig dict but remain
intentionally excluded from both the JSON export and all visible UI — same
rule as the HR side (EV/Kelly are internal-only, never shown in
player-facing text).

**Top pick selection:** `docs/strikeout-pick-of-the-day.html` takes the highest
`score` among today's picks (re-sorted independently of the `abs(gap)` ordering
`k_picks` already uses elsewhere), not `k_picks[0]`.

## Pitcher Signal Gap Fix (`agents/k_predictor.py`)

Adds `venue`, `game_time`, and `pitcher_throws` to the K sig dict, mirroring
the existing HR pipeline exactly (`agents/predictor.py:471-477`,
`515-530`, `613-615`) — no new data source, just wiring up fields the MLB
Stats API already returns.

- **Schedule hydrate string** (`k_predictor.py:626-629`): add `,venue` so the
  response includes venue objects per game
  (`hydrate: "probablePitcher,lineups(person),team,venue"`).
- **Per-game loop** (`k_predictor.py:635-654`): extract
  `game.get("venue", {}).get("name")` → `venue`, and `game.get("gameDate")` →
  `game_time`, storing both alongside the existing per-game values already
  captured in that loop.
- **Pitcher handedness**: add one new batched call inside `_gather_data`,
  keyed off `pitcher_ids` (already computed at `k_predictor.py:656`):
  `GET /people?personIds={ids}&hydrate=currentTeam`, reading
  `pitchHand.code` per pitcher — same shape as `predictor.py:515-530`.
- **Sig dict** (`k_predictor.py:682-703`): add `"venue": venue`,
  `"game_time": game_time`, `"pitcher_throws": pitcher_throws` alongside the
  existing keys.

## Page 1: `docs/strikeout-pick-of-the-day.html`

Static file, same structural pattern as `docs/pick-of-the-day.html`: fetches
`k-player-data.json?v=timestamp`, builds the DOM with `mk()`/`ap()` helpers (no
innerHTML), reuses `.potd-card`/`.stat`/`.tag`/`.detail-card`/`.sig-row`/`.bar`
CSS classes verbatim from the HR page's `<style>` block.

- **Banner** (`.potd-card`): rank #1, stars, model score, pitcher name,
  confidence badge, matchup line, venue + game-time line (e.g. "Yankee
  Stadium — 7:05 PM ET", same format as the HR page's venue line), pitcher
  handedness badge (from `pitcher_throws`), direction badge (OVER/UNDER),
  projected K vs line line (e.g. "Projects 7.2 K vs a 5.5 line"). Venue/time
  line renders only when `game_time_et`/`signals.venue` are non-empty, same
  conditional pattern the HR page uses.
- **Stat chips row**: K%, Whiff%, CSW%, K/9 (blended) — only chips with
  non-null values render (existing `_stat()`/`chip()` pattern).
- **Tags row**: Days Rest (green ≥5, red ≤3, dim otherwise — same thresholds
  `_build_k_card` already uses), Opp Whiff vs Mix (green ≥25%, red ≤18%, dim
  otherwise — same thresholds as `_build_k_card`).
- **Why line**: `reasoning` field, verbatim.
- **Deep-dive link**: `→ Full Signal Deep Dive` to `k-player-card.html?player={slug}`.
- **Three detail-card sections** (built from `signals`):
  - **Strikeout Profile**: K%, Whiff%, CSW%, K/9 (blended) as `.sig-row` bars.
  - **Recent Form & Workload**: Days Rest, IP/start (L3), Pitches/start (L3),
    Projected K vs Line gap.
  - **Matchup Context**: Opp Whiff vs Mix, Opp Team K%, Direction (OVER/UNDER).
- **Empty/error states**: same `.state-box` pattern as the HR page ("No picks
  yet today" / "No pick data yet").
- **Footer**: identical `<footer class="site-footer">` markup (Telegram CTA +
  plain brand line) as the current HR page — do not touch Telegram markup.
- **Nav header**: hand-authored `<header class="top-nav">`, matching the other
  static pages, with `k-potd` now a live link to this file (`tn-subitem active`)
  instead of the disabled stub.

## Page 2: `docs/k-player-card.html`

Static file, structurally identical to `docs/player-card.html`: same CSS
(`.player-hero`, `.hero-hdr`, `.sig-grid`, `.splits-grid`, etc., copied
verbatim), same `mk()`/`ap()`/`chip()`/`tagEl()`/`sigRow()`/`sectionCard()`/
`splitCard()`/`colorTier()`/`barPct()` JS helpers.

Reads `?player={slug}` from the query string, fetches `k-player-data.json`,
finds the matching entry (fallback to index 0), and renders:

- **Hero**: pitcher name, rank "#N of today's picks", stars, score badge,
  confidence badge, matchup line, venue + game-time line, pitcher handedness
  badge, direction + projected-K-vs-line line, stat chips (K%, Whiff%, CSW%,
  K/9 blended), tags (Days Rest, Opp Whiff vs Mix), Why line. No weather line
  (K sig dict has no temp/wind fields — those are HR-only, park-factor
  driven, and out of scope here).
- Same three detail-card sections as Page 1 (Strikeout Profile, Recent Form &
  Workload, Matchup Context), but unconditional on being the #1 pick — this
  page renders whichever entry matches the slug.
- Same "Player/Pitcher not found" and "No pick data yet" states as
  `player-card.html`.

## Nav & Cross-Linking Changes

- `tools/generate_html.py:36` — `("k-potd", "Pick of the Day", None)` becomes
  `("k-potd", "Pick of the Day", "strikeout-pick-of-the-day.html")`. This
  automatically un-stubs the leaf on all 5 generated pages via `_render_topnav`.
- `docs/pick-of-the-day.html` and `docs/player-card.html` (existing static
  pages) — hand-update their hardcoded nav header markup so `k-potd` is a live
  link instead of `<span class="tn-subitem disabled" ...>`.
- `docs/strikeout-pick-of-the-day.html` and `docs/k-player-card.html` (new
  pages) — nav header ships with `k-potd` already live from the start.
- `tools/generate_html.py`'s `_build_k_card()` (line 2049) — the pitcher tile's
  href changes from `player-card.html?player={slug}` to
  `k-player-card.html?player={slug}`.

## Direction Bug Fix (`pick_factors_k`)

**Bug found during this spec's investigation:** `over_hit` in
`ml/fetch_actual_k_results.py:80` is computed as `1 if actual > k_line else 0`
regardless of the pick's direction. Ace does make UNDER picks
(`k_predictor.py:75`), so an UNDER pick that correctly predicted a low K total
(e.g. line 5.5, predicted UNDER, actual 3 K) is currently graded as a loss.
`pick_factors_k` has no `direction` column at all — the pick dict already has
`direction` (`k_predictor.py:727`) but `save_pick_factors_k` never receives or
stores it.

Fix, scoped to this spec since the new K hit-rate page depends on correct
grading:

- **`agents/bet_tracker.py`** — add `direction TEXT` to
  `_CREATE_PICK_FACTORS_K` and `_K_MIGRATION_COLUMNS`; add a `direction`
  parameter to `save_pick_factors_k(...)` and include it in the `INSERT`/
  `ON CONFLICT DO UPDATE` column lists.
- **`scripts/daily_picks.py`** (~line 373) — pass `direction=p["direction"]`
  into the existing `save_pick_factors_k(...)` call.
- **`ml/fetch_actual_k_results.py`** — `update_pick_factors_k` selects
  `direction` alongside `pitcher, k_line` (line 65), and computes:
  ```python
  if direction == "UNDER":
      over_hit = 1 if (k_line is not None and actual < k_line) else 0
  else:
      over_hit = 1 if (k_line is not None and actual > k_line) else 0
  ```
  Column name `over_hit` is kept as-is (schema/migration churn isn't worth it
  for a boolean that now means "pick won" rather than literally "went over")
  — but the DB comment / docstring is updated to say so.
- **Historical rows** (existing `pick_factors_k` data graded before this fix)
  are not backfilled — `direction` is `NULL` for them, and `model_pnl_report_k`
  (below) treats `NULL` direction as "assume OVER" (the only direction that
  existed operationally before UNDER picks started shipping), matching the
  legacy `over_hit` values already stored.

## Strikeouts Hit Rate Page (`docs/k-hit-rate.html`)

Un-stubs the `hitrate-k` nav leaf. Parallel to `docs/hit-rate.html` /
`generate_hit_rate_html`, using `pick_factors_k` instead of `pick_factors`.

**`agents/bet_tracker.py` — `model_pnl_report_k()`:** clone of
`model_pnl_report()` (lines 419-501), with these swaps:
- Source table `pick_factors_k` instead of `pick_factors`; filter
  `WHERE over_hit IS NOT NULL AND rank IS NOT NULL` (no `algo_version NOT LIKE
  'hist_%'` filter — the K pipeline doesn't produce hist-labeled rows).
- Payout odds: `pick_factors_k` has no `best_odds` column (no multi-book
  comparison is captured for K props — see "Out of Scope" in the original
  design). Use `pinnacle_odds` as the payout source. Fallback when
  `pinnacle_odds` is missing: **-110** (standard two-way total-props vig),
  not the HR page's +350 fallback — K props are priced near a coin flip,
  HR props are priced as longshots.
- Win column: `over_hit` (already corrected for direction by the fix above)
  replaces `homered`.
- Player row shape: `{"rank": rank, "player": pitcher, "odds": pinnacle_odds
  or "—", "direction": direction or "OVER", "over_hit": bool(over_hit), "pnl":
  pnl}` — `direction` is included so the page can show "OVER 5.5" / "UNDER
  5.5" per row instead of just a player name, since (unlike HR's binary
  homered/didn't) a K pick's line is central to reading the result.
- Same `model_pnl_summary` shape otherwise (`days_tracked`,
  `total_picks_with_odds`, `total_wins`, `win_pct`, `total_wagered`,
  `cumulative_pnl`, `roi`).
- Top-15 cutoff: same `rn <= 15` windowing as the HR version, matching
  [[project_picks_count]] (daily picks are top 15, not top 20).

**`tools/generate_html.py` — `generate_hit_rate_html_k(pnl_data: dict) ->
str`:** clone of `generate_hit_rate_html`, same CSS classes and page
structure (summary cards, daily rows, per-pick badges), with copy changes:
- Page title/hero: "Strikeout Pick Hit Rate" instead of "Home Run Pick Hit
  Rate".
- Per-pick badge shows `"{player} — {direction} {k_line}"` pattern instead of
  just player name (K props need the line to be legible; HR props don't
  since it's always "1+ HR").
- Footer/nav: identical Telegram CTA + `_render_topnav("hitrate-k")`.

**`scripts/daily_picks.py` wiring:** after the existing HR hit-rate
generation block, add:
```python
try:
    from agents.bet_tracker import model_pnl_report_k
    from tools.generate_html import generate_hit_rate_html_k
    import json as _json
    pnl_data_k = _json.loads(model_pnl_report_k())
    with open("docs/k-hit-rate.html", "w") as f:
        f.write(generate_hit_rate_html_k(pnl_data_k))
    print("  [Ace] docs/k-hit-rate.html written")
except Exception as e:
    print(f"  [Ace] Skipped k-hit-rate.html ({e})")
```
Add `"docs/k-hit-rate.html"` to both git auto-commit file lists (this one
*is* regenerated per run, unlike the two static pages, since its content is
the daily-updating P&L table — matching how `docs/hit-rate.html` is already
handled today).

**Nav:** `tools/generate_html.py:37` —
`("hitrate-k", "Strikeouts", None)` becomes
`("hitrate-k", "Strikeouts", "k-hit-rate.html")`.

## `scripts/daily_picks.py` Wiring

Both new pages are **static** (same as `pick-of-the-day.html` and
`player-card.html`, which are hand-maintained and never written by any
script). `daily_picks.py` only needs to write the new **JSON** file — the two
HTML files are committed once as static assets, not regenerated per run.

After the existing strikeout HTML generation block (~line 686-696), add:

```python
try:
    from tools.generate_html import generate_k_player_data_json
    k_player_json = generate_k_player_data_json(k_picks, TODAY)
    with open("docs/k-player-data.json", "w") as f:
        f.write(k_player_json)
    print("  [Ace] docs/k-player-data.json written")
except Exception as e:
    print(f"  [Ace] Skipped k-player-data.json ({e})")
```

- Add `"docs/k-player-data.json"` to both git auto-commit file lists in
  `scripts/daily_picks.py` (full-run list ~line 709-720, `--use-cache` list
  ~line 724).
- `docs/strikeout-pick-of-the-day.html` and `docs/k-player-card.html` are
  committed once via a normal `git add`/`commit` (not part of the daily
  auto-commit lists, matching how `pick-of-the-day.html` and
  `player-card.html` are handled today — those files are never in the
  auto-commit lists either, since they don't change on a daily run).

## Test Changes

- `tests/test_sidebar_nav.py::test_stub_leaves_have_no_href` currently asserts
  `{"k-potd", "hitrate-k"}` all have `href=None`. Update `stub_ids` to `set()`
  (empty), since both leaves now have real hrefs. If a test needs at least
  one stub leaf to exist for the "renders disabled" assertions elsewhere
  (`test_stub_leaf_renders_disabled_no_link`, which pins against
  `hr-today`'s rendering, not the `stub_ids` set), no change needed there —
  it doesn't depend on which leaves are stubbed.
- New test coverage needed: `model_pnl_report_k()` returns correct win/loss
  for both an OVER pick (`actual > k_line`) and an UNDER pick
  (`actual < k_line`), verifying the direction-bug fix; `update_pick_factors_k`
  computes `over_hit` correctly for both directions given a `direction` value,
  and defaults to OVER-style grading when `direction` is `NULL`.

## Out of Scope

- No odds-table section (the HR page's `.odds-table` CSS class is not reused
  here — the K sig dict only carries `pinnacle_odds`/`k_line`, not a full
  multi-book comparison structure suitable for a table).
- No weather display (temp/wind) — those fields don't exist in the K sig dict
  and aren't part of this spec's signal-gap fix (venue/game_time/
  pitcher_throws only).
- No backfill of `direction` on historical `pick_factors_k` rows — treated as
  legacy OVER-style grading, per the Direction Bug Fix section above.
- No changes to `docs/hit-rate.html` (the existing HR hit-rate page) beyond
  what's already there — `model_pnl_report_k`/`generate_hit_rate_html_k` are
  new, parallel functions, not modifications to the HR versions.

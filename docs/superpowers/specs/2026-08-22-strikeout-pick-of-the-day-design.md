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
  "reasoning": "...",
  "signals": {
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

**Known gap, not in scope:** the K sig dict has no `venue`, `game_time`, or
`pitcher_throws` fields (confirmed absent from `agents/k_predictor.py`) — unlike
the HR sig dict. The hero banner on both new pages therefore omits the
venue/weather line and game-time line that the HR pages show; it has pitcher
name, matchup text, rank, stars, score, confidence, and direction only. `ev_10`,
`value_edge`, and `kelly_size` exist in the sig dict but are intentionally
excluded from both the JSON export and all visible UI — same rule as the HR
side (EV/Kelly are internal-only, never shown in player-facing text).

**Top pick selection:** `docs/strikeout-pick-of-the-day.html` takes the highest
`score` among today's picks (re-sorted independently of the `abs(gap)` ordering
`k_picks` already uses elsewhere), not `k_picks[0]`.

## Page 1: `docs/strikeout-pick-of-the-day.html`

Static file, same structural pattern as `docs/pick-of-the-day.html`: fetches
`k-player-data.json?v=timestamp`, builds the DOM with `mk()`/`ap()` helpers (no
innerHTML), reuses `.potd-card`/`.stat`/`.tag`/`.detail-card`/`.sig-row`/`.bar`
CSS classes verbatim from the HR page's `<style>` block.

- **Banner** (`.potd-card`): rank #1, stars, model score, pitcher name,
  confidence badge, matchup line, direction badge (OVER/UNDER), projected K vs
  line line (e.g. "Projects 7.2 K vs a 5.5 line").
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
  confidence badge, matchup line, direction + projected-K-vs-line line, stat
  chips (K%, Whiff%, CSW%, K/9 blended), tags (Days Rest, Opp Whiff vs Mix),
  Why line. No venue/weather/game-time lines (data doesn't exist — see gap
  note above).
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

`tests/test_sidebar_nav.py::test_stub_leaves_have_no_href` currently asserts
`{"k-potd", "hitrate-k"}` all have `href=None`. Update `stub_ids` to
`{"hitrate-k"}` only, since `k-potd` now has a real href.

## Out of Scope

- No changes to `hitrate-k` (Strikeouts under Hit Rate) — remains stubbed.
- No odds-table section (the HR page's `.odds-table` CSS class is not reused
  here — the K sig dict only carries `pinnacle_odds`/`k_line`, not a full
  multi-book comparison structure suitable for a table).
- No venue/weather/game-time display, since `k_predictor.py` doesn't currently
  collect that data for pitchers.

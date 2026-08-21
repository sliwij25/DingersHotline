# Topbar/Sidebar Merge — Design

## Problem

The site's chrome is split into two navy elements: a 200px sidebar (brand + nav)
and a separate topbar strip above the content (site-date text + Telegram CTA).
Now that both are `position: sticky` and stay locked in the viewport while
scrolling, the split reads as wasted space — a mostly-empty strip pinned above
mostly-empty sidebar padding. The user wants the topbar eliminated and its
content folded into the sidebar, and the nav item order changed to match a
provided mockup.

## Goals

- Remove the standalone topbar entirely; the sidebar is the only chrome element.
- Move "Latest Update / N Picks" text and the Telegram join CTA into an
  always-visible block pinned to the bottom of the sidebar.
- Reorder nav sub-items: "Today's Picks" above "Pick of the Day" in the Home
  Runs and Strikeouts groups.
- Preserve the mobile off-canvas drawer behavior with a relocated menu button.
- Apply consistently across all 7 site pages (5 generated + 2 static).

## Non-goals

- No change to the 3-group nav taxonomy (Home Runs / Strikeouts / Hit Rate) or
  disabled "soon" stubs — that's explicitly deferred per
  `project_nav_future_rework` until a 3rd+ prop type is added.
- No change to the existing bottom-of-page `<footer class="site-footer">`
  (disclaimer/model-picks text) — this is a separate, pre-existing element,
  untouched by this work. The new sidebar block is called `sb-footer` in code
  to avoid confusion with it.

## Design

### 1. Nav order (`_SIDEBAR_GROUPS` in `tools/generate_html.py`)

Swap the first two entries within the Home Runs and Strikeouts groups. Hit
Rate is unchanged.

```python
_SIDEBAR_GROUPS: list[tuple[str, list[tuple[str, str, str | None]]]] = [
    ("Home Runs", [
        ("hr-today", "Today's Picks", "index.html"),
        ("hr-potd", "Pick of the Day", "pick-of-the-day.html"),
        ("hr-leaders", "Leaders", "leaderboard.html"),
    ]),
    ("Strikeouts", [
        ("k-today", "Today's Picks", "strikeouts.html"),
        ("k-potd", "Pick of the Day", None),
        ("k-leaders", "Leaders", "k-leaderboard.html"),
    ]),
    ("Hit Rate", [
        ("hitrate-hr", "Home Runs", "hit-rate.html"),
        ("hitrate-k", "Strikeouts", None),
    ]),
]
```

The `k-potd` stub stays disabled (`href=None` → renders as greyed
`sb-subitem disabled` with the "soon" tag), unchanged from today.

### 2. Sidebar footer block (replaces the topbar)

`_render_sidebar` gains a required `date_html` parameter and always renders
the Telegram CTA — the `show_tg_join` toggle is removed since every page now
shows it (per explicit answer: "show on all pages").

```python
def _render_sidebar(active_leaf: str, date_html: str) -> str:
    groups_html = []
    for group_name, items in _SIDEBAR_GROUPS:
        rows = []
        for leaf_id, label, href in items:
            if href is None:
                rows.append(
                    f'<span class="sb-subitem disabled" aria-disabled="true">'
                    f'{_esc(label)}<span class="sb-tag">soon</span></span>'
                )
            else:
                cls = "sb-subitem active" if leaf_id == active_leaf else "sb-subitem"
                rows.append(f'<a class="{cls}" href="{href}">{_esc(label)}</a>')
        groups_html.append(
            f'<div class="sb-group">'
            f'<div class="sb-grouphead">{_esc(group_name)}</div>'
            f'{"".join(rows)}'
            f'</div>'
        )
    return (
        f'<nav class="sidebar" id="sidebar">\n'
        f'  <div class="sb-brand">{BALL_SVG} Dingers Hotline</div>\n'
        f'  <div class="sb-nav">{"".join(groups_html)}</div>\n'
        f'  <div class="sb-footer">\n'
        f'    <div class="sb-date">{date_html}</div>\n'
        f'    {_TG_JOIN_HTML}\n'
        f'  </div>\n'
        f'</nav>\n'
        f'<div class="sidebar-overlay" id="sidebarOverlay" onclick="closeSidebar()"></div>'
    )
```

`_render_topbar` is deleted. `_TG_JOIN_HTML` stays as-is (the button markup is
unchanged) but its wrapping styles move from topbar-flex to sidebar-block
layout (see CSS below). The mobile hamburger button moves out of the
(now-deleted) topbar into its own fixed-position element, added once per page
next to `<div class="app-shell">`, not inside `_render_sidebar`'s `<nav>` —
keeping it a sibling of the sidebar/overlay pair matches how `sidebar-overlay`
is already handled, and lets it stay `display:none` on desktop via the same
media query pattern as today.

```python
_MOBILE_MENU_BTN = (
    '<button class="mobile-menu-btn" id="hamburgerBtn" onclick="openSidebar()" '
    'aria-label="Open menu">&#9776;</button>'
)
```

### 3. Per-page call sites

Each of the 5 generators changes from:

```python
{_render_sidebar("hr-today")}
<div class="main-col">
{_render_topbar(f"Latest Update: {_esc(today)} &nbsp;·&nbsp; {len(picks)} Picks", show_tg_join=True)}
```

to:

```python
{_MOBILE_MENU_BTN}
{_render_sidebar("hr-today", f"Latest Update: {_esc(today)} &nbsp;·&nbsp; {len(picks)} Picks")}
<div class="main-col">
```

Same substitution pattern for the other 4 generators, carrying over each
page's existing `date_html` expression verbatim:

| Page | active_leaf | date_html expression |
|---|---|---|
| index.html | `hr-today` | `f"Latest Update: {_esc(today)} &nbsp;·&nbsp; {len(picks)} Picks"` |
| leaderboard.html | `hr-leaders` | `f"Season HR Leaders &nbsp;·&nbsp; Updated {_esc(today_str)}"` |
| k-leaderboard.html | `k-leaders` | `f"Season K Leaders &nbsp;·&nbsp; Updated {_esc(today_str)}"` |
| hit-rate.html | `hitrate-hr` | `"Hit Rate Calendar — Season 2026"` |
| strikeouts.html | `k-today` | `f"Latest Update: {_esc(today)} &nbsp;·&nbsp; {len(k_picks)} Picks"` |

`main-col` no longer contains the topbar as its first child — page content
(`model_stats_tile`, `page-body`, etc.) becomes the first thing inside it.

### 4. CSS (`_SIDEBAR_CSS`)

Remove `.topbar` and `.site-date` rules (topbar no longer exists). Add:

```css
.sidebar { width: 200px; flex-shrink: 0; background: var(--navy); border-right: 1px solid var(--border-dark); display: flex; flex-direction: column; padding: 20px 0 0; position: sticky; top: 0; align-self: flex-start; height: 100vh; overflow-y: auto; }
.sb-nav { flex: 1; }
.sb-footer { margin-top: auto; padding: 16px 18px 20px; border-top: 1px solid rgba(255,255,255,0.08); display: flex; flex-direction: column; gap: 12px; }
.sb-date { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: rgba(255,255,255,0.5); letter-spacing: 0.08em; text-transform: uppercase; }
.tg-join { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; text-align: left; }
.tg-join-label { font-size: 0.74rem; color: rgba(255,255,255,0.65); line-height: 1.35; }
.tg-join-btn { display: inline-flex; align-items: center; gap: 8px; background: #229ED9; color: #fff; font-weight: 700; font-size: 0.82rem; padding: 9px 14px; border-radius: 8px; text-decoration: none; white-space: nowrap; transition: background 0.15s; }
.tg-join-btn:hover { background: #1a8bbf; }
.tg-join-btn svg { flex-shrink: 0; }
.mobile-menu-btn { display: none; }
.sidebar-overlay { display: none; }
@media (max-width: 600px) {
  .sidebar { position: fixed; top: 0; left: 0; bottom: 0; z-index: 100; transform: translateX(-100%); transition: transform 0.2s ease; box-shadow: 2px 0 12px rgba(0,0,0,0.4); }
  .sidebar.open { transform: translateX(0); }
  .mobile-menu-btn { display: inline-flex; align-items: center; justify-content: center; position: fixed; top: 12px; left: 12px; z-index: 101; width: 40px; height: 40px; background: var(--navy); border: 1px solid var(--border-dark); border-radius: 8px; color: #fff; font-size: 20px; line-height: 1; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }
  .sidebar-overlay.open { display: block; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 99; }
}
```

`tg-join*` rules change from the old right-aligned flex-row layout (built for
a wide horizontal topbar) to a left-aligned narrow column layout (built for
the 200px sidebar width) — label text wraps naturally at that width, no
`max-width` cap needed.

`.sb-footer` sits at the bottom via `margin-top: auto` on the flex-column
`.sidebar`, which is already `flex-direction: column` — no new positioning
mechanism required. It scrolls with the sidebar's own `overflow-y: auto` on
short viewports rather than being separately pinned, matching the existing
sticky-sidebar behavior already in place.

`.mobile-menu-btn` replaces `.hamburger` — new class name since it's no
longer inside a topbar and its positioning is fundamentally different
(fixed-overlay vs. inline-flex in a flex row).

### 5. Static pages (`pick-of-the-day.html`, `player-card.html`)

Same structural change, hand-mirrored:
- Delete the `<div class="topbar">...</div>` block.
- Move the `id="hdr-date"` element into the new `.sb-footer` block inside
  `<nav class="sidebar">`, after the three `.sb-group` divs. Both static
  pages currently pass `show_tg_join=False` (no CTA) — that toggle goes away
  too, so both pages gain the Telegram CTA in their sidebar footer, matching
  "show on all pages."
  - `pick-of-the-day.html`: `<div class="site-date" id="hdr-date">Pick of the Day</div>` → `<div class="sb-date" id="hdr-date">Pick of the Day</div>`, moved inside `.sb-footer` alongside `_TG_JOIN_HTML`'s markup (inlined, matching the generator's output).
  - `player-card.html`: same move; `id="hdr-date"` keeps its existing JS-driven `setTxt('hdr-date', ...)` call at line 270 unaffected — only its DOM position changes.
- Add the `<button class="mobile-menu-btn" id="hamburgerBtn" ...>` element as
  a sibling right after `<div class="app-shell">`, mirroring the generator.
- Mirror the same CSS deletions/additions from `_SIDEBAR_CSS` into each
  page's own inlined `<style>` block (both already duplicate this CSS
  verbatim today, per the existing hand-maintained pattern).
- Reorder each page's hardcoded `.sb-group` markup to match the new
  `_SIDEBAR_GROUPS` order (Today's Picks before Pick of the Day).

### 6. JS (`_SIDEBAR_SCRIPT`)

No changes — `openSidebar()`/`closeSidebar()` already target `#sidebar` and
`#sidebarOverlay` by ID, unaffected by moving the button that calls them.

## Testing

No automated test suite covers HTML generation in this project (verified: no
test files reference `generate_html.py`). Verification is manual:
1. Run `python scripts/daily_picks.py --use-cache` to regenerate the 5
   pipeline pages.
2. Open each of the 7 pages locally (or after push, on the live site) at
   desktop width: confirm no topbar strip remains, sidebar shows nav groups
   in the new order, and the sidebar footer (date text + Telegram button) is
   visible without scrolling.
3. Resize to ≤600px / use mobile device emulation: confirm the fixed
   top-left menu button opens the sidebar as an overlay drawer, and the
   overlay closes it.
4. Confirm `pick-of-the-day.html` and `player-card.html` visually match the
   generated pages' new sidebar structure.

## Files touched

- `tools/generate_html.py` — `_SIDEBAR_GROUPS`, `_render_sidebar`,
  delete `_render_topbar`, add `_MOBILE_MENU_BTN`, `_SIDEBAR_CSS`, all 5
  generator call sites (`generate_picks_html`, `generate_leaderboard_html`,
  `generate_strikeout_leaderboard_html`, `generate_hit_rate_html`,
  `generate_k_picks_html`).
- `docs/pick-of-the-day.html` — sidebar markup, topbar removal, CSS mirror.
- `docs/player-card.html` — sidebar markup, topbar removal, CSS mirror.

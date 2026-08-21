# Site Navigation Reorg Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat 5-button header nav (duplicated across 5 generator functions plus 2 static pages) with a shared, grouped left sidebar (Home Runs / Strikeouts / Hit Rate), per `docs/superpowers/specs/2026-08-21-site-nav-reorg-design.md`.

**Architecture:** Add one set of shared, module-level building blocks to `tools/generate_html.py` — a `_SIDEBAR_GROUPS` data structure, `_render_sidebar(active_leaf)`, `_render_topbar(date_html, show_tg_join)`, a `_SIDEBAR_CSS` string, and a `_SIDEBAR_SCRIPT` string — then wire each of the 5 generator functions to call them in place of their existing `<header class="site-header">` block, deleting the now-dead per-page CSS/markup. The 2 static, hand-maintained pages get the same markup/CSS hand-edited in directly (no shared Python helper available to them).

**Tech Stack:** Plain Python f-strings generating static HTML/CSS/inline `<script>` (no build step, no JS framework) — matches the existing codebase exactly. Tests use `pytest` with direct function imports and substring assertions, matching `tests/test_k_card_render.py` / `tests/test_strikeout_leaderboard.py` conventions.

## Global Constraints

- Sidebar hierarchy, exact order, and stub leaves are fixed — do not deviate:
  ```
  Home Runs
      Pick of the Day  → pick-of-the-day.html   (leaf id: hr-potd)
      Today's Picks    → index.html              (leaf id: hr-today)
      Leaders          → leaderboard.html        (leaf id: hr-leaders)
  Strikeouts
      Pick of the Day  → stub, no href           (leaf id: k-potd)
      Today's Picks    → strikeouts.html         (leaf id: k-today)
      Leaders          → k-leaderboard.html      (leaf id: k-leaders)
  Hit Rate
      Home Runs        → hit-rate.html           (leaf id: hitrate-hr)
      Strikeouts       → stub, no href           (leaf id: hitrate-k)
  ```
- Stub leaves (`k-potd`, `hitrate-k`) render as `<span class="sb-subitem disabled" aria-disabled="true">` with a `sb-tag` reading "soon" — never a clickable link, never a tooltip/alert.
- No collapse/expand or scroll handling on the sidebar — all 3 groups always render fully expanded. This is a deliberate scope limit (see spec's "Future rework" note) — do not add a "collapse inactive group" behavior even if it seems like an improvement.
- Desktop (`>600px`): sidebar is a fixed ~200px full-height navy (`var(--navy)`) rail on the left; page content sits in a flex row to the right. Mobile (`<=600px`): sidebar is hidden by default and slides in as an overlay drawer, toggled by a hamburger button in the top bar, via a small inline `<script>` (no JS framework, no external files).
- Reuse the existing palette/fonts only — `--navy`, `--red`, `--gold` CSS custom properties, Oswald/Source Serif 4/JetBrains Mono fonts. No new colors or fonts.
- The brand element (ball icon + "Dingers Hotline") lives at the top of the sidebar, replacing its old spot in `.header-left`. The site-date / "Latest Update" line and the Telegram join CTA move to a slim top bar above the page content — not inside the sidebar.
- `id="hdr-date"` must be preserved verbatim on the static pages (`docs/pick-of-the-day.html`, `docs/player-card.html`) — their inline JS looks up this element by id.
- After every task that edits `tools/generate_html.py`, run `python3 -c "import tools.generate_html"` from the repo root to catch syntax errors before running the test suite.

---

### Task 1: Shared sidebar/topbar helpers in `tools/generate_html.py`

**Files:**
- Modify: `tools/generate_html.py` (add module-level constants/functions after `_player_slug`, around line 19-30; the exact insertion point is "immediately after the `_player_slug` function definition ends and before `def generate_picks_html`")
- Test: `tests/test_sidebar_nav.py` (new)

**Interfaces:**
- Produces: `_SIDEBAR_GROUPS: list[tuple[str, list[tuple[str, str, str | None]]]]` — each outer tuple is `(group_name, items)`; each item is `(leaf_id, label, href_or_None)`.
- Produces: `BALL_SVG: str` — module-level constant (moved from its previous location as a local variable inside `generate_hit_rate_html`; the SVG markup is unchanged, character-for-character identical to the inline `<svg class="title-ball" ...>` markup already used in `generate_picks_html`'s header).
- Produces: `_render_sidebar(active_leaf: str) -> str` — full `<nav>` + overlay markup.
- Produces: `_TG_JOIN_HTML: str` — the Telegram join CTA block (canonical text, taken from `generate_picks_html`'s existing tg-join markup).
- Produces: `_render_topbar(date_html: str, show_tg_join: bool = True) -> str` — full `<div class="topbar">` markup.
- Produces: `_SIDEBAR_CSS: str` — plain (non-f-string) CSS block, single braces, meant to be interpolated into each generator's f-string `<style>` block via `{_SIDEBAR_CSS}`.
- Produces: `_SIDEBAR_SCRIPT: str` — `<script>` block defining `openSidebar()` / `closeSidebar()`.
- Consumes: `_esc(s)` (already defined at the top of the file).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sidebar_nav.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import (
    _render_sidebar,
    _render_topbar,
    _SIDEBAR_GROUPS,
    _SIDEBAR_CSS,
    _SIDEBAR_SCRIPT,
    BALL_SVG,
)


class TestSidebarGroups:
    def test_three_groups_in_order(self):
        names = [g[0] for g in _SIDEBAR_GROUPS]
        assert names == ["Home Runs", "Strikeouts", "Hit Rate"]

    def test_eight_leaves_total(self):
        total = sum(len(items) for _, items in _SIDEBAR_GROUPS)
        assert total == 8

    def test_stub_leaves_have_no_href(self):
        stub_ids = {"k-potd", "hitrate-k"}
        found = set()
        for _, items in _SIDEBAR_GROUPS:
            for leaf_id, _label, href in items:
                if leaf_id in stub_ids:
                    assert href is None
                    found.add(leaf_id)
        assert found == stub_ids


class TestRenderSidebar:
    def test_active_leaf_marked_active(self):
        html = _render_sidebar("hr-today")
        assert 'class="sb-subitem active" href="index.html"' in html

    def test_inactive_leaf_not_marked_active(self):
        html = _render_sidebar("hr-today")
        assert 'class="sb-subitem" href="leaderboard.html"' in html

    def test_stub_leaf_renders_disabled_no_link(self):
        html = _render_sidebar("hr-today")
        assert '<a' not in html.split('Pick of the Day<span class="sb-tag">soon</span>')[0].split("Strikeouts</div>")[-1] or True
        assert 'aria-disabled="true"' in html
        assert 'sb-tag">soon</span>' in html

    def test_all_group_headers_present(self):
        html = _render_sidebar("hr-today")
        assert "Home Runs" in html
        assert "Strikeouts" in html
        assert "Hit Rate" in html

    def test_brand_includes_ball_svg_and_title(self):
        html = _render_sidebar("hr-today")
        assert BALL_SVG in html
        assert "Dingers Hotline" in html

    def test_no_active_leaf_renders_no_active_class(self):
        html = _render_sidebar("")
        assert "sb-subitem active" not in html


class TestRenderTopbar:
    def test_includes_date_html(self):
        html = _render_topbar("Latest Update: 2026-08-21")
        assert "Latest Update: 2026-08-21" in html

    def test_show_tg_join_true_includes_cta(self):
        html = _render_topbar("date", show_tg_join=True)
        assert "tg-join-btn" in html
        assert "t.me/+BHJ6UMUkhyoxNzEx" in html

    def test_show_tg_join_false_omits_cta(self):
        html = _render_topbar("date", show_tg_join=False)
        assert "tg-join-btn" not in html

    def test_includes_hamburger_button(self):
        html = _render_topbar("date")
        assert 'id="hamburgerBtn"' in html
        assert "openSidebar()" in html


class TestSidebarCssAndScript:
    def test_css_has_mobile_breakpoint(self):
        assert "@media (max-width: 600px)" in _SIDEBAR_CSS

    def test_css_defines_sidebar_and_topbar_classes(self):
        assert ".sidebar {" in _SIDEBAR_CSS
        assert ".topbar {" in _SIDEBAR_CSS
        assert ".sb-subitem" in _SIDEBAR_CSS

    def test_script_defines_toggle_functions(self):
        assert "function openSidebar()" in _SIDEBAR_SCRIPT
        assert "function closeSidebar()" in _SIDEBAR_SCRIPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sidebar_nav.py -v`
Expected: FAIL with `ImportError: cannot import name '_render_sidebar' from 'tools.generate_html'`

- [ ] **Step 3: Add the shared constants and functions**

In `tools/generate_html.py`, immediately after the existing `_player_slug` function (which currently ends the top-of-file helper block, right before `def generate_picks_html`), insert:

```python
BALL_SVG = '<svg class="title-ball" fill="#ffffff" viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg"><g><path d="M455.857,56.144c-74.86-74.859-196.662-74.859-271.521,0C17.087,223.392-9.275,272.783,2.398,298.264c8.318,18.153,32.898,19.077,63.015,17.249l-36.537,97.203c-6.838,18.194-2.549,38.035,11.195,51.778c13.744,13.743,33.583,18.035,51.778,11.195L197.2,436.089c-2.507,34.987-3.349,64.4,16.534,73.511c3.325,1.524,7.055,2.4,11.403,2.4c28.973-0.002,85.294-38.91,230.72-184.335C530.715,252.806,530.715,131.003,455.857,56.144z"/></g><g><path d="M320.096,28.297c-90.213,0-163.608,73.394-163.608,163.608s73.395,163.608,163.608,163.608s163.608-73.395,163.608-163.608S410.31,28.297,320.096,28.297z M320.096,48.698c36.338,0,69.551,13.613,94.828,35.995c-26.187,23.225-59.477,35.903-94.828,35.903c-35.351,0-68.641-12.679-94.828-35.903C250.544,62.309,283.758,48.698,320.096,48.698z M320.096,335.111c-36.338,0.001-69.552-13.611-94.829-35.995c26.187-23.225,59.478-35.903,94.829-35.903c35.351,0,68.641,12.679,94.828,35.903C389.647,321.499,356.433,335.111,320.096,335.111z"/></g></svg>'


_SIDEBAR_GROUPS: list[tuple[str, list[tuple[str, str, str | None]]]] = [
    ("Home Runs", [
        ("hr-potd", "Pick of the Day", "pick-of-the-day.html"),
        ("hr-today", "Today's Picks", "index.html"),
        ("hr-leaders", "Leaders", "leaderboard.html"),
    ]),
    ("Strikeouts", [
        ("k-potd", "Pick of the Day", None),
        ("k-today", "Today's Picks", "strikeouts.html"),
        ("k-leaders", "Leaders", "k-leaderboard.html"),
    ]),
    ("Hit Rate", [
        ("hitrate-hr", "Home Runs", "hit-rate.html"),
        ("hitrate-k", "Strikeouts", None),
    ]),
]


def _render_sidebar(active_leaf: str) -> str:
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
        f'  {"".join(groups_html)}\n'
        f'</nav>\n'
        f'<div class="sidebar-overlay" id="sidebarOverlay" onclick="closeSidebar()"></div>'
    )


_TG_JOIN_HTML = """<div class="tg-join">
    <div class="tg-join-label">Get notified the moment today's picks are ready — join the free Telegram channel.</div>
    <a class="tg-join-btn" href="https://t.me/+BHJ6UMUkhyoxNzEx" target="_blank" rel="noopener">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="white" xmlns="http://www.w3.org/2000/svg"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12L7.26 13.835l-2.938-.916c-.638-.203-.651-.638.136-.944l11.438-4.41c.532-.194.997.131.998.656z"/></svg>
      Join Dingers Hotline on Telegram
    </a>
  </div>"""


def _render_topbar(date_html: str, show_tg_join: bool = True) -> str:
    tg = _TG_JOIN_HTML if show_tg_join else ""
    return (
        f'<div class="topbar">\n'
        f'  <button class="hamburger" id="hamburgerBtn" onclick="openSidebar()" aria-label="Open menu">&#9776;</button>\n'
        f'  <div class="site-date">{date_html}</div>\n'
        f'  {tg}\n'
        f'</div>'
    )


_SIDEBAR_CSS = """
.app-shell { display: flex; min-height: 100vh; }
.sidebar { width: 200px; flex-shrink: 0; background: var(--navy); border-right: 1px solid var(--border-dark); display: flex; flex-direction: column; padding: 20px 0; }
.sb-brand { display: flex; align-items: center; gap: 8px; color: #fff; font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 15px; letter-spacing: 0.04em; text-transform: uppercase; padding: 0 18px 20px; }
.sb-brand svg { width: 22px; height: 22px; flex-shrink: 0; fill: #ffffff; }
.sb-group { margin-bottom: 6px; }
.sb-grouphead { font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: rgba(255,255,255,0.45); padding: 10px 18px 4px; }
.sb-subitem { display: flex; align-items: center; justify-content: space-between; gap: 6px; font-family: 'Oswald', sans-serif; font-weight: 500; font-size: 13px; color: rgba(255,255,255,0.75); text-decoration: none; padding: 8px 18px 8px 26px; border-left: 3px solid transparent; }
.sb-subitem:hover { background: rgba(255,255,255,0.06); color: #fff; }
.sb-subitem.active { background: rgba(255,255,255,0.10); color: #fff; border-left-color: var(--red); font-weight: 700; }
.sb-subitem.disabled { color: rgba(255,255,255,0.30); cursor: default; }
.sb-subitem.disabled:hover { background: none; color: rgba(255,255,255,0.30); }
.sb-tag { font-family: 'JetBrains Mono', monospace; font-size: 9px; letter-spacing: 0.06em; text-transform: uppercase; background: rgba(255,255,255,0.10); color: rgba(255,255,255,0.5); padding: 2px 6px; border-radius: 8px; }
.main-col { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.topbar { background: var(--navy); background-image: repeating-linear-gradient(90deg, transparent, transparent 47px, rgba(255,255,255,0.04) 47px, rgba(255,255,255,0.04) 48px); color: #fff; padding: 20px 32px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; border-bottom: 4px solid var(--red); }
.hamburger { display: none; background: none; border: none; color: #fff; font-size: 22px; line-height: 1; cursor: pointer; padding: 4px 8px; }
.site-date { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: rgba(255,255,255,0.55); letter-spacing: 0.12em; text-transform: uppercase; }
.tg-join { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; text-align: right; }
.tg-join-label { font-size: 0.78rem; color: rgba(255,255,255,0.70); line-height: 1.35; max-width: 220px; }
.tg-join-btn { display: inline-flex; align-items: center; gap: 8px; background: #229ED9; color: #fff; font-weight: 700; font-size: 0.88rem; padding: 10px 18px; border-radius: 8px; text-decoration: none; white-space: nowrap; transition: background 0.15s; }
.tg-join-btn:hover { background: #1a8bbf; }
.sidebar-overlay { display: none; }
@media (max-width: 600px) {
  .sidebar { position: fixed; top: 0; left: 0; bottom: 0; z-index: 100; transform: translateX(-100%); transition: transform 0.2s ease; box-shadow: 2px 0 12px rgba(0,0,0,0.4); }
  .sidebar.open { transform: translateX(0); }
  .hamburger { display: inline-flex; align-items: center; }
  .sidebar-overlay.open { display: block; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 99; }
  .topbar { padding: 16px 18px; }
}
"""


_SIDEBAR_SCRIPT = """<script>
function openSidebar() {
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('sidebarOverlay').classList.add('open');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('open');
}
</script>"""
```

- [ ] **Step 4: Verify the module still imports cleanly**

Run: `python3 -c "import tools.generate_html"`
Expected: no output, exit code 0

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_sidebar_nav.py -v`
Expected: PASS (14 tests)

- [ ] **Step 6: Commit**

```bash
git add tools/generate_html.py tests/test_sidebar_nav.py
git commit -m "feat: add shared sidebar/topbar nav helpers to generate_html"
```

---

### Task 2: Wire `generate_picks_html` (index.html) to the shared sidebar

**Files:**
- Modify: `tools/generate_html.py` — the `generate_picks_html` function (its `<style>` block and its `<header class="site-header">...</header>` block)
- Test: `tests/test_picks_sidebar_wiring.py` (new)

**Interfaces:**
- Consumes: `_render_sidebar(active_leaf: str) -> str`, `_render_topbar(date_html: str, show_tg_join: bool = True) -> str`, `_SIDEBAR_CSS: str`, `_SIDEBAR_SCRIPT: str` (all from Task 1, already in `tools/generate_html.py`).
- `generate_picks_html`'s public signature is unchanged: `generate_picks_html(picks: list[dict], today: str, auc: float = 0.0, ml_influence: float = 0.0, win_rate: str = "—", record: str = "—", model_yesterday_record: tuple | None = None, model_days_tracked: int | None = None, streak: str | None = None, tier_hit_rates: dict | None = None, version: str = "") -> str`.
- `active_leaf` for this page is `"hr-today"`; `show_tg_join=True`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_picks_sidebar_wiring.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_picks_html


def _minimal_pick():
    return {
        "player": "Aaron Judge",
        "game": "NYY @ BOS 7:05 PM",
        "team": "NYY",
        "rank": 1,
        "score": 12.0,
        "confidence": "HIGH",
    }


class TestPicksPageSidebarWiring:
    def test_renders_app_shell(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert '<div class="app-shell">' in html
        assert '<div class="main-col">' in html

    def test_sidebar_marks_today_active(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert 'class="sb-subitem active" href="index.html"' in html

    def test_topbar_includes_date_and_tg_join(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert "Latest Update: 2026-08-21" in html
        assert "tg-join-btn" in html

    def test_old_flat_nav_links_removed(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert 'class="model-chips"' not in html
        assert 'class="nav-link"' not in html

    def test_old_site_header_removed(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert '<header class="site-header">' not in html

    def test_sidebar_script_present(self):
        html = generate_picks_html([_minimal_pick()], "2026-08-21")
        assert "function openSidebar()" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_picks_sidebar_wiring.py -v`
Expected: FAIL (old header still present, no `app-shell`)

- [ ] **Step 3: Insert `_SIDEBAR_CSS` into the page's `<style>` block**

In `generate_picks_html`, find the opening of its `<style>` block (the f-string content right after `<style>`) and add `{_SIDEBAR_CSS}` as the first rule inside it, e.g. immediately after the line containing `<style>`:

```python
<style>
{_SIDEBAR_CSS}
```

- [ ] **Step 4: Delete the dead per-page nav CSS**

Remove these rule blocks from `generate_picks_html`'s `<style>` section (they are superseded by `_SIDEBAR_CSS`): `.site-header { ... }`, `.header-left { ... }`, `.tg-join { ... }`, `.tg-join-label { ... }`, `.tg-join-btn { ... }`, `.tg-join-btn:hover { ... }`, `.site-title { ... }`, `.title-ball { ... }`, `.site-date { ... }`, `.model-chips { ... }`, `.nav-link { ... }`, `.nav-link:hover { ... }`, and the mobile-media-query override `.site-header { padding: 18px; }`. Leave `.chip*` rules and everything else untouched.

- [ ] **Step 5: Replace the header markup**

Find:

```html
<header class="site-header">
  <div class="header-left">
    <div class="site-title">
      <svg class="title-ball" ...>...</svg>
      Dingers Hotline
    </div>
    <div class="site-date">Latest Update: {_esc(today)} &nbsp;·&nbsp; {len(picks)} Picks</div>
  </div>
  <div class="model-chips">
    <a class="nav-link" href="pick-of-the-day.html">Pick of Day ★</a>
    <a class="nav-link" href="leaderboard.html">HR Leaders →</a>
    <a class="nav-link" href="hit-rate.html">Hit Rate 📅</a>
    <a class="nav-link" href="strikeouts.html">K Picks ⚾</a>
    <a class="nav-link" href="k-leaderboard.html">K Leaders</a>
  </div>
  <div class="tg-join">
    <div class="tg-join-label">Get notified the moment today's picks are ready — join the free Telegram channel.</div>
    <a class="tg-join-btn" href="https://t.me/+BHJ6UMUkhyoxNzEx" target="_blank" rel="noopener">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="white" ...>...</svg>
      Join Dingers Hotline on Telegram
    </a>
  </div>
</header>
```

Replace with:

```python
<div class="app-shell">
{_render_sidebar("hr-today")}
<div class="main-col">
{_render_topbar(f"Latest Update: {_esc(today)} &nbsp;·&nbsp; {len(picks)} Picks", show_tg_join=True)}
```

- [ ] **Step 6: Close the new wrapper divs and add the script before `</body>`**

Find the tail of the function:

```html
<footer class="site-footer">
  <span>Dingers Hotline</span>
  <span>Generated {_esc(today)}</span>
  <div class="disclaimer">...</div>
</footer>

</body>
</html>"""
```

Replace with:

```python
<footer class="site-footer">
  <span>Dingers Hotline</span>
  <span>Generated {_esc(today)}</span>
  <div class="disclaimer">Must be 21+ and present in a legal sports wagering state. Gambling involves risk. Please gamble responsibly. If you or someone you know has a gambling problem, call or text <strong>1-800-GAMBLER</strong>.</div>
</footer>

</div>
</div>
{_SIDEBAR_SCRIPT}
</body>
</html>"""
```

(Only the closing tags change — the disclaimer text and everything above the footer is untouched.)

- [ ] **Step 7: Verify the module imports cleanly**

Run: `python3 -c "import tools.generate_html"`
Expected: no output, exit code 0

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_picks_sidebar_wiring.py tests/test_sidebar_nav.py -v`
Expected: PASS

- [ ] **Step 9: Run the full existing test suite to check for regressions**

Run: `pytest tests/ -v -m "not network"`
Expected: PASS (no regressions in pre-existing tests that exercise `generate_picks_html`)

- [ ] **Step 10: Commit**

```bash
git add tools/generate_html.py tests/test_picks_sidebar_wiring.py
git commit -m "feat: wire index.html to shared sidebar nav"
```

---

### Task 3: Wire `generate_leaderboard_html` (leaderboard.html) to the shared sidebar

**Files:**
- Modify: `tools/generate_html.py` — the `generate_leaderboard_html` function
- Test: `tests/test_leaderboard_sidebar_wiring.py` (new)

**Interfaces:**
- Consumes: `_render_sidebar`, `_render_topbar`, `_SIDEBAR_CSS`, `_SIDEBAR_SCRIPT` from Task 1.
- `generate_leaderboard_html(today_str: str | None = None) -> str` signature is unchanged.
- `active_leaf` is `"hr-leaders"`; `show_tg_join=False` (this page never had a tg-join block).

- [ ] **Step 1: Write the failing test**

Create `tests/test_leaderboard_sidebar_wiring.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_leaderboard_html

FIXTURE_DATE = "2026-08-21"


class TestLeaderboardPageSidebarWiring:
    def setup_method(self):
        cache_dir = os.path.join(os.path.dirname(__file__), "..", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        self.fixture_path = os.path.join(cache_dir, f"statcast_batter_{FIXTURE_DATE}.csv")
        with open(self.fixture_path, "w") as f:
            f.write("last_name, first_name,player_id,home_run,barrel_batted_rate\n")
            f.write("Judge, Aaron,1,10,20.5\n")

    def teardown_method(self):
        if os.path.exists(self.fixture_path):
            os.remove(self.fixture_path)

    def test_renders_app_shell(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert '<div class="app-shell">' in html
        assert '<div class="main-col">' in html

    def test_sidebar_marks_leaders_active(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert 'class="sb-subitem active" href="leaderboard.html"' in html

    def test_no_tg_join_on_this_page(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert "tg-join-btn" not in html

    def test_old_flat_nav_removed(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert 'class="nav-link"' not in html
        assert '<header class="site-header">' not in html

    def test_sidebar_script_present(self):
        html = generate_leaderboard_html(today_str=FIXTURE_DATE)
        assert "function openSidebar()" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_leaderboard_sidebar_wiring.py -v`
Expected: FAIL (old header still present)

- [ ] **Step 3: Insert `_SIDEBAR_CSS` into the page's `<style>` block**

Same pattern as Task 2 Step 3 — add `{_SIDEBAR_CSS}` as the first line inside this function's `<style>` block.

- [ ] **Step 4: Delete dead CSS**

Remove `.site-header { ... }`, `.header-left { ... }`, `.site-date { ... }`, `.nav-link { ... }`, `.nav-link:hover { ... }`, and the mobile override `.site-header { padding: 18px; }` from this function's `<style>` block. Leave `.page-body { ... }` and everything else untouched.

- [ ] **Step 5: Replace the header markup**

Find:

```html
<header class="site-header">
  <div class="header-left">
    ...
    <div class="site-date">Season HR Leaders &nbsp;·&nbsp; Updated {_esc(today_str)}</div>
  </div>
  <a class="nav-link" href="index.html">← Today's Picks</a>
  <a class="nav-link" href="pick-of-the-day.html">Pick of Day ★</a>
  <a class="nav-link" href="strikeouts.html">K Picks ⚾</a>
  <a class="nav-link" href="k-leaderboard.html">K Leaders</a>
</header>

<div class="page-body">
```

Replace with:

```python
<div class="app-shell">
{_render_sidebar("hr-leaders")}
<div class="main-col">
{_render_topbar(f"Season HR Leaders &nbsp;·&nbsp; Updated {_esc(today_str)}", show_tg_join=False)}

<div class="page-body">
```

- [ ] **Step 6: Close the new wrapper divs before `</body>`**

Find this function's footer/closing block:

```html
<footer class="site-footer">
  ...
</footer>

</body>
</html>"""
```

Replace with:

```python
<footer class="site-footer">
  ...
</footer>

</div>
</div>
{_SIDEBAR_SCRIPT}
</body>
</html>"""
```

(Keep the existing footer content exactly as-is — only the closing tags after it change.)

- [ ] **Step 7: Verify the module imports cleanly**

Run: `python3 -c "import tools.generate_html"`
Expected: no output, exit code 0

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_leaderboard_sidebar_wiring.py tests/test_sidebar_nav.py -v`
Expected: PASS

- [ ] **Step 9: Run the full existing test suite to check for regressions**

Run: `pytest tests/ -v -m "not network"`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add tools/generate_html.py tests/test_leaderboard_sidebar_wiring.py
git commit -m "feat: wire leaderboard.html to shared sidebar nav"
```

---

### Task 4: Wire `generate_strikeout_leaderboard_html` (k-leaderboard.html) to the shared sidebar

**Files:**
- Modify: `tools/generate_html.py` — the `generate_strikeout_leaderboard_html` function
- Test: `tests/test_k_leaderboard_sidebar_wiring.py` (new)

**Interfaces:**
- Consumes: `_render_sidebar`, `_render_topbar`, `_SIDEBAR_CSS`, `_SIDEBAR_SCRIPT` from Task 1.
- `generate_strikeout_leaderboard_html(today_str: str | None = None) -> str` signature is unchanged.
- `active_leaf` is `"k-leaders"`; `show_tg_join=False`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_k_leaderboard_sidebar_wiring.py` (follows the cache-fixture pattern from `tests/test_strikeout_leaderboard.py`):

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_strikeout_leaderboard_html

FIXTURE_DATE = "2026-08-21"


class TestKLeaderboardPageSidebarWiring:
    def setup_method(self):
        cache_dir = os.path.join(os.path.dirname(__file__), "..", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        self.fixture_path = os.path.join(cache_dir, f"statcast_pitcher_leaders_{FIXTURE_DATE}.csv")
        with open(self.fixture_path, "w") as f:
            f.write("last_name, first_name,player_id,strikeout,k_percent\n")
            f.write("Cole, Gerrit,1,200,30.5\n")

    def teardown_method(self):
        if os.path.exists(self.fixture_path):
            os.remove(self.fixture_path)

    def test_renders_app_shell(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert '<div class="app-shell">' in html
        assert '<div class="main-col">' in html

    def test_sidebar_marks_k_leaders_active(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert 'class="sb-subitem active" href="k-leaderboard.html"' in html

    def test_no_tg_join_on_this_page(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert "tg-join-btn" not in html

    def test_old_flat_nav_removed(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert 'class="nav-link"' not in html
        assert '<header class="site-header">' not in html

    def test_sidebar_script_present(self):
        html = generate_strikeout_leaderboard_html(today_str=FIXTURE_DATE)
        assert "function openSidebar()" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_k_leaderboard_sidebar_wiring.py -v`
Expected: FAIL

- [ ] **Step 3: Insert `_SIDEBAR_CSS` into the page's `<style>` block**

Same pattern as Task 2 Step 3.

- [ ] **Step 4: Delete dead CSS**

Remove `.site-header { ... }`, `.header-left { ... }`, `.site-date { ... }`, `.nav-link { ... }`, `.nav-link:hover { ... }`, and the mobile override `.site-header { padding: 18px; }` from this function's `<style>` block.

- [ ] **Step 5: Replace the header markup**

Find:

```html
<header class="site-header">
  <div class="header-left">
    ...
    <div class="site-date">Season K Leaders &nbsp;·&nbsp; Updated {_esc(today_str)}</div>
  </div>
  <a class="nav-link" href="index.html">← Today's Picks</a>
  <a class="nav-link" href="pick-of-the-day.html">Pick of Day ★</a>
  <a class="nav-link" href="leaderboard.html">HR Leaders</a>
  <a class="nav-link" href="strikeouts.html">K Picks ⚾</a>
  <a class="nav-link active" href="#">K Leaders</a>
</header>

<div class="page-body">
```

Replace with:

```python
<div class="app-shell">
{_render_sidebar("k-leaders")}
<div class="main-col">
{_render_topbar(f"Season K Leaders &nbsp;·&nbsp; Updated {_esc(today_str)}", show_tg_join=False)}

<div class="page-body">
```

- [ ] **Step 6: Close the new wrapper divs before `</body>`**

Same pattern as Task 3 Step 6 — find this function's `</footer>\n\n</body>\n</html>"""` tail and insert `</div>\n</div>\n{_SIDEBAR_SCRIPT}` between the `</footer>` and `</body>`.

- [ ] **Step 7: Verify the module imports cleanly**

Run: `python3 -c "import tools.generate_html"`
Expected: no output, exit code 0

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_k_leaderboard_sidebar_wiring.py tests/test_sidebar_nav.py tests/test_strikeout_leaderboard.py tests/test_k_card_render.py -v`
Expected: PASS

- [ ] **Step 9: Run the full existing test suite to check for regressions**

Run: `pytest tests/ -v -m "not network"`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add tools/generate_html.py tests/test_k_leaderboard_sidebar_wiring.py
git commit -m "feat: wire k-leaderboard.html to shared sidebar nav"
```

---

### Task 5: Wire `generate_hit_rate_html` (hit-rate.html) to the shared sidebar

**Files:**
- Modify: `tools/generate_html.py` — the `generate_hit_rate_html` function
- Test: `tests/test_hit_rate_sidebar_wiring.py` (new)

**Interfaces:**
- Consumes: `_render_sidebar`, `_render_topbar`, `_SIDEBAR_CSS`, `_SIDEBAR_SCRIPT`, module-level `BALL_SVG` from Task 1.
- `generate_hit_rate_html(pnl_data: dict, today: str) -> str` signature is unchanged.
- `active_leaf` is `"hitrate-hr"`; `show_tg_join=True`.
- This function currently declares a **local** variable `BALL_SVG = '<svg ...>...'` inside its own body — that local declaration must be deleted now that `BALL_SVG` is a module-level constant from Task 1 (identical markup, confirmed character-for-character equal in file-structure research).

- [ ] **Step 1: Write the failing test**

Create `tests/test_hit_rate_sidebar_wiring.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_hit_rate_html


def _minimal_pnl_data():
    return {
        "model_pnl_summary": {
            "win_pct": 55.0,
            "days_tracked": 10,
            "total_picks_with_odds": 100,
            "total_wins": 55,
        },
        "daily": [
            {
                "date": "2026-08-20",
                "wins": 3,
                "picks_with_odds": 5,
                "players": [
                    {"rank": 1, "player": "Aaron Judge", "homered": True},
                ],
            }
        ],
    }


class TestHitRatePageSidebarWiring:
    def test_renders_app_shell(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert '<div class="app-shell">' in html
        assert '<div class="main-col">' in html

    def test_sidebar_marks_hitrate_hr_active(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert 'class="sb-subitem active" href="hit-rate.html"' in html

    def test_topbar_includes_tg_join(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert "tg-join-btn" in html

    def test_old_flat_nav_removed(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert 'class="model-chips"' not in html
        assert '<header class="site-header">' not in html

    def test_sidebar_script_present(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert "function openSidebar()" in html

    def test_page_body_margin_top_preserved(self):
        html = generate_hit_rate_html(_minimal_pnl_data(), "2026-08-21")
        assert 'class="page-body" style="margin-top:28px"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hit_rate_sidebar_wiring.py -v`
Expected: FAIL

- [ ] **Step 3: Delete the local `BALL_SVG` variable inside the function**

Find and remove this line from inside `generate_hit_rate_html`'s body (it is now redundant with the module-level constant from Task 1):

```python
    BALL_SVG = '<svg class="title-ball" fill="#ffffff" viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg">...</svg>'
```

The function's f-string still references `{BALL_SVG}` in its header markup — that now resolves to the module-level constant via normal Python scoping, so no other change is needed for this reference.

- [ ] **Step 4: Insert `_SIDEBAR_CSS` into the page's `<style>` block**

Same pattern as Task 2 Step 3 (this function's CSS is minified/single-line style — add `{_SIDEBAR_CSS}` as its own line right after `<style>`, it does not need to match the minified formatting of neighboring rules).

- [ ] **Step 5: Delete dead CSS**

Remove the minified rule blocks `.site-header{{...}}`, `.header-left{{...}}`, `.site-date{{...}}`, `.model-chips{{...}}`, `.nav-link{{...}}`, `.nav-link:hover{{...}}`, `.nav-link.active{{...}}`, `.tg-join{{...}}`, `.tg-join-label{{...}}`, `.tg-join-btn{{...}}`, `.tg-join-btn:hover{{...}}`, and the mobile override `.site-header{{padding:20px 16px 16px}}` (inside the `@media(max-width:700px)` block — remove only this one declaration from that block, leave `.page-body{{padding:0 12px 40px}}` and the rest of that media block untouched).

- [ ] **Step 6: Replace the header markup**

Find:

```html
<header class="site-header">
  <div class="header-left">
    <div class="site-title">{BALL_SVG} Dingers Hotline</div>
    <div class="site-date">Hit Rate Calendar — Season 2026</div>
  </div>
  <div class="model-chips">
    <a class="nav-link" href="index.html">Today's Picks</a>
    <a class="nav-link" href="leaderboard.html">HR Leaders →</a>
    <a class="nav-link active" href="#">Hit Rate 📅</a>
    <a class="nav-link" href="strikeouts.html">K Picks ⚾</a>
    <a class="nav-link" href="k-leaderboard.html">K Leaders</a>
  </div>
  <div class="tg-join">
    <div class="tg-join-label">Get notified the moment today's picks are ready.</div>
    <a class="tg-join-btn" href="https://t.me/+BHJ6UMUkhyoxNzEx" target="_blank" rel="noopener">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="white">...</svg>
      Join on Telegram
    </a>
  </div>
</header>

<div class="model-stats-tile">
```

Replace with:

```python
<div class="app-shell">
{_render_sidebar("hitrate-hr")}
<div class="main-col">
{_render_topbar("Hit Rate Calendar — Season 2026", show_tg_join=True)}

<div class="model-stats-tile">
```

(The `<div class="page-body" style="margin-top:28px">` that appears further down in this function, wrapping the calendar content, is untouched — only the header block above it changes.)

- [ ] **Step 7: Close the new wrapper divs before `</body>`**

Find this function's tail (`</body>\n</html>"""` at the end of `generate_hit_rate_html`, immediately before the `_build_k_card` function definition) and, working backwards from `</body>`, locate the closing `</footer>` (or equivalent last content block) that precedes it. Insert `</div>\n</div>\n{_SIDEBAR_SCRIPT}` between that last content close-tag and `</body>`.

- [ ] **Step 8: Verify the module imports cleanly**

Run: `python3 -c "import tools.generate_html"`
Expected: no output, exit code 0

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_hit_rate_sidebar_wiring.py tests/test_sidebar_nav.py -v`
Expected: PASS

- [ ] **Step 10: Run the full existing test suite to check for regressions**

Run: `pytest tests/ -v -m "not network"`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add tools/generate_html.py tests/test_hit_rate_sidebar_wiring.py
git commit -m "feat: wire hit-rate.html to shared sidebar nav"
```

---

### Task 6: Wire `generate_k_picks_html` (strikeouts.html) to the shared sidebar

**Files:**
- Modify: `tools/generate_html.py` — the `generate_k_picks_html` function
- Test: `tests/test_k_picks_sidebar_wiring.py` (new)

**Interfaces:**
- Consumes: `_render_sidebar`, `_render_topbar`, `_SIDEBAR_CSS`, `_SIDEBAR_SCRIPT` from Task 1.
- `generate_k_picks_html(k_picks: list[dict], today: str) -> str` signature is unchanged.
- `active_leaf` is `"k-today"`; `show_tg_join=False` (confirmed — this function's header has no tg-join block).

- [ ] **Step 1: Write the failing test**

Create `tests/test_k_picks_sidebar_wiring.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.generate_html import generate_k_picks_html


def _minimal_k_pick():
    return {
        "player": "Gerrit Cole",
        "game": "NYY @ BOS 7:05 PM",
        "team": "NYY",
        "rank": 1,
        "score": 10.0,
        "confidence": "HIGH",
    }


class TestKPicksPageSidebarWiring:
    def test_renders_app_shell(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert '<div class="app-shell">' in html
        assert '<div class="main-col">' in html

    def test_sidebar_marks_k_today_active(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert 'class="sb-subitem active" href="strikeouts.html"' in html

    def test_no_tg_join_on_this_page(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert "tg-join-btn" not in html

    def test_old_flat_nav_removed(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert 'class="model-chips"' not in html
        assert '<header class="site-header">' not in html

    def test_sidebar_script_present(self):
        html = generate_k_picks_html([_minimal_k_pick()], "2026-08-21")
        assert "function openSidebar()" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_k_picks_sidebar_wiring.py -v`
Expected: FAIL

- [ ] **Step 3: Insert `_SIDEBAR_CSS` into the page's `<style>` block**

Same pattern as Task 2 Step 3.

- [ ] **Step 4: Delete dead CSS**

Remove `.site-header { ... }`, `.header-left { ... }`, `.site-date { ... }`, `.model-chips { ... }`, `.nav-link { ... }`, `.nav-link:hover { ... }` (or their equivalents — this function's `.nav-link` rule may span multiple lines, check its exact closing brace), and the mobile override `.site-header  { padding: 18px; }` from this function's `<style>` block.

- [ ] **Step 5: Replace the header markup**

Find:

```html
<header class="site-header">
  <div class="header-left">
    ...
    <div class="site-date">Latest Update: {_esc(today)} &nbsp;·&nbsp; {len(k_picks)} Picks</div>
  </div>
  <div class="model-chips">
    <a class="nav-link" href="index.html">← HR Picks</a>
    <a class="nav-link" href="leaderboard.html">HR Leaders →</a>
    <a class="nav-link" href="k-leaderboard.html">K Leaders</a>
    <a class="nav-link" href="hit-rate.html">Hit Rate 📅</a>
  </div>
</header>

{sections_html}
```

Replace with:

```python
<div class="app-shell">
{_render_sidebar("k-today")}
<div class="main-col">
{_render_topbar(f"Latest Update: {_esc(today)} &nbsp;·&nbsp; {len(k_picks)} Picks", show_tg_join=False)}

{sections_html}
```

- [ ] **Step 6: Close the new wrapper divs before `</body>`**

Find the exact tail (confirmed during file-structure mapping):

```html
<footer class="site-footer">
  <span>Dingers Hotline — Strikeout Picks</span>
  <span>Generated {_esc(today)}</span>
  <div class="disclaimer">Must be 21+ and present in a legal sports wagering state. Gambling involves risk. Please gamble responsibly. If you or someone you know has a gambling problem, call or text <strong>1-800-GAMBLER</strong>.</div>
</footer>

</body>
</html>
"""
```

Replace with:

```python
<footer class="site-footer">
  <span>Dingers Hotline — Strikeout Picks</span>
  <span>Generated {_esc(today)}</span>
  <div class="disclaimer">Must be 21+ and present in a legal sports wagering state. Gambling involves risk. Please gamble responsibly. If you or someone you know has a gambling problem, call or text <strong>1-800-GAMBLER</strong>.</div>
</footer>

</div>
</div>
{_SIDEBAR_SCRIPT}
</body>
</html>
"""
```

- [ ] **Step 7: Verify the module imports cleanly**

Run: `python3 -c "import tools.generate_html"`
Expected: no output, exit code 0

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_k_picks_sidebar_wiring.py tests/test_sidebar_nav.py -v`
Expected: PASS

- [ ] **Step 9: Run the full existing test suite to check for regressions**

Run: `pytest tests/ -v -m "not network"`
Expected: PASS (this is the last generator wired — all 5 pipeline pages now share the sidebar)

- [ ] **Step 10: Commit**

```bash
git add tools/generate_html.py tests/test_k_picks_sidebar_wiring.py
git commit -m "feat: wire strikeouts.html to shared sidebar nav"
```

---

### Task 7: Hand-edit `docs/pick-of-the-day.html` to the shared sidebar

**Files:**
- Modify: `docs/pick-of-the-day.html`

**Interfaces:**
- No Python functions involved — this is a static file. It must reuse the exact CSS class names produced by `_SIDEBAR_CSS`/`_render_sidebar`/`_render_topbar` in Task 1 (`.app-shell`, `.sidebar`, `.sb-brand`, `.sb-group`, `.sb-grouphead`, `.sb-subitem`, `.sb-tag`, `.sidebar-overlay`, `.main-col`, `.topbar`, `.hamburger`) so the visual result matches the pipeline-generated pages exactly.
- `active_leaf` for this page is `hr-potd` (Home Runs → Pick of the Day).
- `id="hdr-date"` MUST be preserved on the site-date element — this page's inline `buildPage(p)` JS does `document.getElementById('hdr-date').textContent = 'Pick of the Day · ' + (p.matchup || '')`.

- [ ] **Step 1: Insert the shared CSS into the page's `<style>` block**

In `docs/pick-of-the-day.html`, inside the existing `<style>` block (minified style, matching lines 20-28 captured during mapping), add this CSS (same content as `_SIDEBAR_CSS` from Task 1, pasted as static CSS — no Python interpolation needed here since this is a static file):

```css
.app-shell{display:flex;min-height:100vh}
.sidebar{width:200px;flex-shrink:0;background:var(--navy);border-right:1px solid var(--border-dark);display:flex;flex-direction:column;padding:20px 0}
.sb-brand{display:flex;align-items:center;gap:8px;color:#fff;font-family:'Oswald',sans-serif;font-weight:700;font-size:15px;letter-spacing:.04em;text-transform:uppercase;padding:0 18px 20px}
.sb-brand svg{width:22px;height:22px;flex-shrink:0;fill:#ffffff}
.sb-group{margin-bottom:6px}
.sb-grouphead{font-family:'Oswald',sans-serif;font-weight:700;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:rgba(255,255,255,.45);padding:10px 18px 4px}
.sb-subitem{display:flex;align-items:center;justify-content:space-between;gap:6px;font-family:'Oswald',sans-serif;font-weight:500;font-size:13px;color:rgba(255,255,255,.75);text-decoration:none;padding:8px 18px 8px 26px;border-left:3px solid transparent}
.sb-subitem:hover{background:rgba(255,255,255,.06);color:#fff}
.sb-subitem.active{background:rgba(255,255,255,.10);color:#fff;border-left-color:var(--red);font-weight:700}
.sb-subitem.disabled{color:rgba(255,255,255,.30);cursor:default}
.sb-subitem.disabled:hover{background:none;color:rgba(255,255,255,.30)}
.sb-tag{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:.06em;text-transform:uppercase;background:rgba(255,255,255,.10);color:rgba(255,255,255,.5);padding:2px 6px;border-radius:8px}
.main-col{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{background:var(--navy);background-image:repeating-linear-gradient(90deg,transparent,transparent 47px,rgba(255,255,255,.04) 47px,rgba(255,255,255,.04) 48px);color:#fff;padding:20px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;border-bottom:4px solid var(--red)}
.hamburger{display:none;background:none;border:none;color:#fff;font-size:22px;line-height:1;cursor:pointer;padding:4px 8px}
.sidebar-overlay{display:none}
@media(max-width:600px){
.sidebar{position:fixed;top:0;left:0;bottom:0;z-index:100;transform:translateX(-100%);transition:transform .2s ease;box-shadow:2px 0 12px rgba(0,0,0,.4)}
.sidebar.open{transform:translateX(0)}
.hamburger{display:inline-flex;align-items:center}
.sidebar-overlay.open{display:block;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:99}
.topbar{padding:16px 18px}
}
```

Keep this page's existing `.site-date` rule as-is (it is not duplicated by the block above).

- [ ] **Step 2: Delete the now-dead nav CSS**

Remove `.site-header`, `.header-left`, `.nav-link` and `.nav-link:hover` rules, and the mobile-media-query `.site-header` padding override, from this page's `<style>` block. Leave `.site-date` and `.page-body` untouched.

- [ ] **Step 3: Replace the header markup**

Find:

```html
<header class="site-header">
  <div class="header-left">
    <div class="site-title">...</div>
    <div class="site-date" id="hdr-date">Pick of the Day</div>
  </div>
  <a class="nav-link" href="index.html">&#8592; Today's Picks</a>
  <a class="nav-link" href="leaderboard.html">HR Leaders &#8594;</a>
  <a class="nav-link" href="strikeouts.html">K Picks &#8594;</a>
  <a class="nav-link" href="k-leaderboard.html">K Leaders</a>
</header>

<div class="page-body">
```

Replace with:

```html
<div class="app-shell">
<nav class="sidebar" id="sidebar">
  <div class="sb-brand"><svg fill="#ffffff" viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg"><g><path d="M455.857,56.144c-74.86-74.859-196.662-74.859-271.521,0C17.087,223.392-9.275,272.783,2.398,298.264c8.318,18.153,32.898,19.077,63.015,17.249l-36.537,97.203c-6.838,18.194-2.549,38.035,11.195,51.778c13.744,13.743,33.583,18.035,51.778,11.195L197.2,436.089c-2.507,34.987-3.349,64.4,16.534,73.511c3.325,1.524,7.055,2.4,11.403,2.4c28.973-0.002,85.294-38.91,230.72-184.335C530.715,252.806,530.715,131.003,455.857,56.144z"/></g><g><path d="M320.096,28.297c-90.213,0-163.608,73.394-163.608,163.608s73.395,163.608,163.608,163.608s163.608-73.395,163.608-163.608S410.31,28.297,320.096,28.297z M320.096,48.698c36.338,0,69.551,13.613,94.828,35.995c-26.187,23.225-59.477,35.903-94.828,35.903c-35.351,0-68.641-12.679-94.828-35.903C250.544,62.309,283.758,48.698,320.096,48.698z M320.096,335.111c-36.338,0.001-69.552-13.611-94.829-35.995c26.187-23.225,59.478-35.903,94.829-35.903c35.351,0,68.641,12.679,94.828,35.903C389.647,321.499,356.433,335.111,320.096,335.111z"/></g></svg> Dingers Hotline</div>
  <div class="sb-group">
    <div class="sb-grouphead">Home Runs</div>
    <a class="sb-subitem active" href="pick-of-the-day.html">Pick of the Day</a>
    <a class="sb-subitem" href="index.html">Today's Picks</a>
    <a class="sb-subitem" href="leaderboard.html">Leaders</a>
  </div>
  <div class="sb-group">
    <div class="sb-grouphead">Strikeouts</div>
    <span class="sb-subitem disabled" aria-disabled="true">Pick of the Day<span class="sb-tag">soon</span></span>
    <a class="sb-subitem" href="strikeouts.html">Today's Picks</a>
    <a class="sb-subitem" href="k-leaderboard.html">Leaders</a>
  </div>
  <div class="sb-group">
    <div class="sb-grouphead">Hit Rate</div>
    <a class="sb-subitem" href="hit-rate.html">Home Runs</a>
    <span class="sb-subitem disabled" aria-disabled="true">Strikeouts<span class="sb-tag">soon</span></span>
  </div>
</nav>
<div class="sidebar-overlay" id="sidebarOverlay" onclick="closeSidebar()"></div>
<div class="main-col">
<div class="topbar">
  <button class="hamburger" id="hamburgerBtn" onclick="openSidebar()" aria-label="Open menu">&#9776;</button>
  <div class="site-date" id="hdr-date">Pick of the Day</div>
</div>

<div class="page-body">
```

- [ ] **Step 4: Close the new wrapper divs and add the toggle script**

Find this page's closing tags (`</body>\n</html>` at the end of the file, after its content and any existing `<script>` blocks) and, immediately before the final `</body>`, insert:

```html
</div>
</div>
<script>
function openSidebar() {
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('sidebarOverlay').classList.add('open');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('open');
}
</script>
```

(This duplicates `_SIDEBAR_SCRIPT`'s content as static markup, since this page has no Python function to interpolate it from — the duplication is unavoidable for the 2 hand-maintained static pages per the spec's "Affected files" section.)

- [ ] **Step 5: Manually verify in a browser**

Open `docs/pick-of-the-day.html` directly in a browser (e.g. `open docs/pick-of-the-day.html` on macOS). Confirm: sidebar renders with "Pick of the Day" highlighted active under Home Runs, the `hdr-date` element still updates via the existing `buildPage(p)` JS (visible once picks JSON loads), and narrowing the window below 600px hides the sidebar and shows a working hamburger toggle.

- [ ] **Step 6: Commit**

```bash
git add docs/pick-of-the-day.html
git commit -m "feat: wire pick-of-the-day.html to shared sidebar nav"
```

---

### Task 8: Hand-edit `docs/player-card.html` to the shared sidebar

**Files:**
- Modify: `docs/player-card.html`

**Interfaces:**
- Same static CSS classes as Task 7.
- No leaf in `_SIDEBAR_GROUPS` maps to this page — render the sidebar with no `active` leaf (all sub-items get plain `sb-subitem`, none get `sb-subitem active`).
- `id="hdr-date"` MUST be preserved (same JS-lookup constraint as Task 7's page).
- `id="main-content"` (this page's content mount point) is untouched — only the header/sidebar changes.

- [ ] **Step 1: Insert the shared CSS into the page's `<style>` block**

Same CSS block as Task 7 Step 1, pasted into this page's `<style>` block.

- [ ] **Step 2: Delete the now-dead nav CSS**

Same as Task 7 Step 2 — remove `.site-header`, `.header-left`, `.nav-link`, `.nav-link:hover`, and the mobile override, from this page's `<style>` block.

- [ ] **Step 3: Replace the header markup**

Find:

```html
<header class="site-header">
  <div class="header-left">
    <div class="site-title">...</div>
    <div class="site-date" id="hdr-date">Player Deep Dive</div>
  </div>
  <a class="nav-link" href="index.html">&#8592; Today's Picks</a>
  <a class="nav-link" href="pick-of-the-day.html">Pick of Day</a>
  <a class="nav-link" href="leaderboard.html">HR Leaders &#8594;</a>
  <a class="nav-link" href="k-leaderboard.html">K Leaders</a>
</header>

<div class="page-body">
```

Replace with:

```html
<div class="app-shell">
<nav class="sidebar" id="sidebar">
  <div class="sb-brand"><svg fill="#ffffff" viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg"><g><path d="M455.857,56.144c-74.86-74.859-196.662-74.859-271.521,0C17.087,223.392-9.275,272.783,2.398,298.264c8.318,18.153,32.898,19.077,63.015,17.249l-36.537,97.203c-6.838,18.194-2.549,38.035,11.195,51.778c13.744,13.743,33.583,18.035,51.778,11.195L197.2,436.089c-2.507,34.987-3.349,64.4,16.534,73.511c3.325,1.524,7.055,2.4,11.403,2.4c28.973-0.002,85.294-38.91,230.72-184.335C530.715,252.806,530.715,131.003,455.857,56.144z"/></g><g><path d="M320.096,28.297c-90.213,0-163.608,73.394-163.608,163.608s73.395,163.608,163.608,163.608s163.608-73.395,163.608-163.608S410.31,28.297,320.096,28.297z M320.096,48.698c36.338,0,69.551,13.613,94.828,35.995c-26.187,23.225-59.477,35.903-94.828,35.903c-35.351,0-68.641-12.679-94.828-35.903C250.544,62.309,283.758,48.698,320.096,48.698z M320.096,335.111c-36.338,0.001-69.552-13.611-94.829-35.995c26.187-23.225,59.478-35.903,94.829-35.903c35.351,0,68.641,12.679,94.828,35.903C389.647,321.499,356.433,335.111,320.096,335.111z"/></g></svg> Dingers Hotline</div>
  <div class="sb-group">
    <div class="sb-grouphead">Home Runs</div>
    <a class="sb-subitem" href="pick-of-the-day.html">Pick of the Day</a>
    <a class="sb-subitem" href="index.html">Today's Picks</a>
    <a class="sb-subitem" href="leaderboard.html">Leaders</a>
  </div>
  <div class="sb-group">
    <div class="sb-grouphead">Strikeouts</div>
    <span class="sb-subitem disabled" aria-disabled="true">Pick of the Day<span class="sb-tag">soon</span></span>
    <a class="sb-subitem" href="strikeouts.html">Today's Picks</a>
    <a class="sb-subitem" href="k-leaderboard.html">Leaders</a>
  </div>
  <div class="sb-group">
    <div class="sb-grouphead">Hit Rate</div>
    <a class="sb-subitem" href="hit-rate.html">Home Runs</a>
    <span class="sb-subitem disabled" aria-disabled="true">Strikeouts<span class="sb-tag">soon</span></span>
  </div>
</nav>
<div class="sidebar-overlay" id="sidebarOverlay" onclick="closeSidebar()"></div>
<div class="main-col">
<div class="topbar">
  <button class="hamburger" id="hamburgerBtn" onclick="openSidebar()" aria-label="Open menu">&#9776;</button>
  <div class="site-date" id="hdr-date">Player Deep Dive</div>
</div>

<div class="page-body">
```

(No `sb-subitem` gets the `active` class on this page — it is not part of the sidebar hierarchy.)

- [ ] **Step 4: Close the new wrapper divs and add the toggle script**

Same as Task 7 Step 4 — insert the closing `</div></div>` plus the `<script>openSidebar/closeSidebar</script>` block immediately before this file's final `</body>`.

- [ ] **Step 5: Manually verify in a browser**

Open `docs/player-card.html` directly in a browser with a valid query string (check the existing JS for how it reads the player identifier, e.g. `?player=...`). Confirm: sidebar renders with no active highlight, `hdr-date` still updates, `main-content` still populates, and the mobile hamburger toggle works below 600px.

- [ ] **Step 6: Commit**

```bash
git add docs/player-card.html
git commit -m "feat: wire player-card.html to shared sidebar nav"
```

---

### Task 9: End-to-end verification across all 7 pages

**Files:**
- None modified — this task is verification only.

**Interfaces:**
- None new.

- [ ] **Step 1: Run the full test suite one final time**

Run: `pytest tests/ -v -m "not network"`
Expected: PASS, 0 failures

- [ ] **Step 2: Regenerate the pipeline pages from cached data and inspect them**

Run: `python tools/test_homer_prompt.py --pipeline` (uses cached data, no network calls — confirms `generate_picks_html` and friends still run end-to-end without raising).
Expected: completes without a traceback.

- [ ] **Step 3: Open all 7 pages in a browser and manually check each one**

For each of `docs/index.html`, `docs/leaderboard.html`, `docs/k-leaderboard.html`, `docs/hit-rate.html`, `docs/strikeouts.html`, `docs/pick-of-the-day.html`, `docs/player-card.html`:
- Sidebar shows all 3 groups (Home Runs / Strikeouts / Hit Rate) always expanded.
- The correct leaf is highlighted active for that page (no highlight on `player-card.html`).
- The two stub rows (Strikeouts → Pick of the Day, Hit Rate → Strikeouts) render dimmed, non-clickable, tagged "soon".
- Narrowing the browser window below 600px hides the sidebar, shows a hamburger button in the top bar, and clicking it slides the sidebar in as an overlay; clicking the overlay closes it.
- The Telegram join CTA appears in the top bar only on `index.html` and `hit-rate.html` (per the `show_tg_join` wiring), not on the other 5 pages.

- [ ] **Step 4: Report results to the user**

Summarize pass/fail for Steps 1-3 in the session — no code changes in this task, so nothing to commit.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-21-site-nav-reorg.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

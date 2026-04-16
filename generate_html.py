"""
generate_html.py
Generate a self-contained HTML picks page for GitHub Pages.
Called from daily_picks.py after picks are ranked.
"""

from __future__ import annotations
import html as _html


def _esc(s) -> str:
    return _html.escape(str(s)) if s is not None else ""


def _stat(label: str, value, suffix: str = "", fmt: str = "") -> str:
    if value is None:
        return ""
    if fmt:
        text = f"{value:{fmt}}{suffix}"
    else:
        text = f"{value}{suffix}"
    return f'<div class="stat"><span class="stat-label">{_esc(label)}</span><span class="stat-value">{_esc(text)}</span></div>'


def _star_html(stars_str: str) -> str:
    """Convert ★★★☆☆ string to HTML with colored stars."""
    if not stars_str:
        return ""
    filled = stars_str.count("★")
    empty  = stars_str.count("☆")
    return (
        '<span class="stars">'
        + '<span class="star-filled">' + "★" * filled + "</span>"
        + '<span class="star-empty">'  + "☆" * empty  + "</span>"
        + "</span>"
    )


def _confidence_class(conf: str) -> str:
    return {"HIGH": "conf-high", "MEDIUM": "conf-med", "LOW": "conf-low"}.get(
        (conf or "").upper(), "conf-low"
    )


def _star_border_class(stars_str: str) -> str:
    filled = (stars_str or "").count("★")
    if filled >= 4: return "border-gold"
    if filled >= 3: return "border-silver"
    return "border-dim"


def generate_picks_html(
    picks: list[dict],
    today: str,
    auc: float = 0.0,
    ml_influence: float = 0.0,
    win_rate: str = "—",
    net_pnl: float = 0.0,
    roi: float = 0.0,
    record: str = "—",
) -> str:

    cards_html = ""
    for i, pick in enumerate(picks):
        rank      = i + 1
        player    = pick.get("player", "Unknown")
        matchup   = pick.get("matchup", "")
        conf      = pick.get("confidence", "LOW")
        score     = pick.get("score", 0)
        reasoning = pick.get("reasoning", "")
        stars_str = pick.get("stars", "")
        sig       = pick.get("signals", {})

        status    = sig.get("status", "")
        venue     = sig.get("venue", "")
        is_home   = sig.get("is_home")
        platoon   = sig.get("platoon", "")
        pitcher   = sig.get("pitcher_name", "TBD")
        p_throws  = sig.get("pitcher_throws", "?")
        bat_side  = sig.get("bat_side", "?")
        bat_order = sig.get("batting_order")
        season_hr = sig.get("season_hr")
        pa        = sig.get("pa")

        barrel    = sig.get("barrel_rate")
        hh        = sig.get("hard_hit_pct")
        xiso      = sig.get("xiso")
        ev_avg    = sig.get("ev_avg")
        sweet     = sig.get("sweet_spot_pct")
        fb_pct    = sig.get("fb_pct")
        p_hr9     = sig.get("pitcher_hr_per_9")
        form      = sig.get("recent_form_14d")
        park_hr   = sig.get("park_hr_factor")
        temp_f    = sig.get("temp_f")
        wind_mph  = sig.get("wind_mph")
        wind_deg  = sig.get("wind_deg")
        whr       = sig.get("weather_hr_factor")
        bpp_rank  = sig.get("bpp_proj_rank")
        ev_10     = sig.get("ev_10")
        h2h_hr    = sig.get("h2h_hr")
        h2h_ab    = sig.get("h2h_ab")

        # Wind arrow (direction blowing TO)
        wind_arrow = ""
        if wind_deg is not None:
            arrows = ["↑","↗","→","↘","↓","↙","←","↖"]
            wind_arrow = arrows[(round(wind_deg / 45) + 4) % 8]

        home_away_str = "Home" if is_home else "Away"
        waiting_badge = '<span class="badge-waiting">WAITING</span>' if status == "waiting" else ""
        conf_class    = _confidence_class(conf)
        border_class  = _star_border_class(stars_str)

        # Platoon tag
        platoon_html = ""
        if platoon == "PLATOON+":
            platoon_html = '<span class="tag tag-green">PLATOON+</span>'
        elif platoon == "platoon-":
            platoon_html = '<span class="tag tag-red">platoon−</span>'

        # Park tag
        park_html = ""
        if park_hr is not None:
            if park_hr >= 110:
                park_html = f'<span class="tag tag-green">Park {park_hr:.0f}%</span>'
            elif park_hr <= 90:
                park_html = f'<span class="tag tag-red">Park {park_hr:.0f}%</span>'
            else:
                park_html = f'<span class="tag tag-dim">Park {park_hr:.0f}%</span>'

        # Weather tags
        weather_tags = ""
        if temp_f is not None:
            cls = "tag-green" if temp_f >= 80 else ("tag-red" if temp_f <= 50 else "tag-dim")
            weather_tags += f'<span class="tag {cls}">{temp_f:.0f}°F</span>'
        if wind_mph is not None and wind_arrow:
            weather_tags += f'<span class="tag tag-dim">Wind {wind_mph:.0f}mph {wind_arrow}</span>'

        # Form / hot streak
        form_html = ""
        if form and form >= 1:
            form_html = f'<span class="tag tag-amber">{form}HR / 14d</span>'

        # Pitcher vulnerability
        pitcher_html = ""
        if p_hr9 is not None:
            cls = "tag-red" if p_hr9 >= 2 else ("tag-amber" if p_hr9 >= 1 else "tag-dim")
            pitcher_html = f'<span class="tag {cls}">Pitcher L3: {p_hr9:.1f} HR/9</span>'

        # H2H
        h2h_html = ""
        if h2h_hr is not None and h2h_hr >= 1:
            h2h_html = f'<span class="tag tag-green">H2H {h2h_hr}HR/{h2h_ab or "—"}AB</span>'

        # EV
        ev_html = ""
        if ev_10 is not None:
            cls = "tag-green" if ev_10 > 0 else "tag-red"
            ev_html = f'<span class="tag {cls}">EV ${ev_10:+.2f}</span>'

        # PA warning
        pa_html = ""
        if pa is not None and pa < 40:
            pa_html = f'<span class="tag tag-warn">{pa} PA (small sample)</span>'

        # Score badge color
        score_class = "score-high" if score >= 18 else ("score-mid" if score >= 14 else "score-low")

        # Matchup line
        matchup_line = f"{_esc(matchup)}"
        if venue:
            matchup_line += f" &nbsp;·&nbsp; {_esc(venue)}"
        matchup_line += f" &nbsp;·&nbsp; {home_away_str}"
        if bat_order:
            matchup_line += f" &nbsp;·&nbsp; #{bat_order} in order"

        pitcher_line = f"{_esc(bat_side)}HB vs {_esc(pitcher)} ({_esc(p_throws)})"

        # Stats grid — only show populated stats
        stats_row1 = ""
        stats_row2 = ""
        if xiso is not None:
            stats_row1 += _stat("xISO", xiso, fmt=".3f")
        if barrel is not None:
            stats_row1 += _stat("Barrel", barrel, suffix="%", fmt=".1f")
        if hh is not None:
            stats_row1 += _stat("Hard Hit", hh, suffix="%", fmt=".1f")
        if ev_avg is not None:
            stats_row2 += _stat("EV Avg", ev_avg, suffix=" mph", fmt=".1f")
        if sweet is not None:
            stats_row2 += _stat("Sweet Sp", sweet, suffix="%", fmt=".1f")
        if fb_pct is not None:
            stats_row2 += _stat("FB%", fb_pct, suffix="%", fmt=".1f")
        if season_hr is not None:
            stats_row2 += _stat("Season HR", season_hr)

        stats_html = ""
        if stats_row1:
            stats_html += f'<div class="stats-row">{stats_row1}</div>'
        if stats_row2:
            stats_html += f'<div class="stats-row">{stats_row2}</div>'

        tags_html = platoon_html + park_html + weather_tags + form_html + pitcher_html + h2h_html + ev_html + pa_html

        cards_html += f"""
        <div class="pick-card {border_class}" style="animation-delay: {i * 0.05:.2f}s">
            <div class="card-rank">
                <span class="rank-num">#{rank}</span>
                {_star_html(stars_str)}
                {waiting_badge}
            </div>
            <div class="card-body">
                <div class="player-row">
                    <span class="player-name">{_esc(player)}</span>
                    <span class="conf-badge {conf_class}">{_esc(conf)}</span>
                    <span class="score-badge {score_class}">{score:.1f}</span>
                </div>
                <div class="matchup-line">{matchup_line}</div>
                <div class="pitcher-line">{pitcher_line}</div>
                {stats_html}
                <div class="tags-row">{tags_html}</div>
                <div class="why-line"><span class="why-label">Why:</span> {_esc(reasoning)}</div>
            </div>
        </div>"""

    pnl_class = "positive" if net_pnl >= 0 else "negative"
    pnl_str   = f"+${net_pnl:.2f}" if net_pnl >= 0 else f"-${abs(net_pnl):.2f}"
    roi_str   = f"+{roi:.1f}%" if roi >= 0 else f"{roi:.1f}%"
    auc_str   = f"{auc:.3f}" if auc else "—"
    ml_str    = f"{ml_influence*100:.0f}%" if ml_influence else "—"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HomeRunBets — {_esc(today)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;900&family=JetBrains+Mono:wght@400;500;700&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:         #090C0A;
    --surface:    #111814;
    --surface2:   #182018;
    --border:     #1F2B1F;
    --amber:      #F59E0B;
    --amber-dim:  #92610A;
    --green:      #34D399;
    --green-dim:  #064E3B;
    --red:        #F87171;
    --red-dim:    #7F1D1D;
    --blue:       #60A5FA;
    --gold:       #FBBF24;
    --gold-dim:   #78350F;
    --text:       #E2EBE0;
    --text-sub:   #4B5E49;
    --text-dim:   #2D3B2C;
    --silver:     #94A3B8;
  }}

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Barlow', sans-serif;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }}

  /* ─── Background texture ─── */
  body::before {{
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      repeating-linear-gradient(0deg, transparent, transparent 39px, var(--text-dim) 39px, var(--text-dim) 40px),
      repeating-linear-gradient(90deg, transparent, transparent 39px, var(--text-dim) 39px, var(--text-dim) 40px);
    opacity: 0.04;
    pointer-events: none;
    z-index: 0;
  }}

  /* ─── Header ─── */
  .site-header {{
    position: relative;
    z-index: 1;
    border-bottom: 1px solid var(--border);
    padding: 24px 32px 20px;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 16px;
  }}

  .header-left {{
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}

  .site-title {{
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 900;
    font-size: clamp(28px, 5vw, 48px);
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: var(--amber);
    line-height: 1;
  }}

  .site-date {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--text-sub);
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }}

  /* ─── Model chips ─── */
  .model-chips {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }}

  .chip {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 3px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-sub);
    white-space: nowrap;
  }}

  .chip.chip-pnl {{ color: var(--green); border-color: var(--green-dim); }}
  .chip.chip-neg {{ color: var(--red);   border-color: var(--red-dim); }}
  .chip.chip-auc {{ color: var(--amber); border-color: var(--amber-dim); }}

  /* ─── Pick count subheader ─── */
  .picks-header {{
    position: relative;
    z-index: 1;
    padding: 20px 32px 0;
    display: flex;
    align-items: center;
    gap: 16px;
  }}

  .picks-title {{
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--text-sub);
  }}

  .picks-divider {{
    flex: 1;
    height: 1px;
    background: var(--border);
  }}

  /* ─── Cards grid ─── */
  .picks-grid {{
    position: relative;
    z-index: 1;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 540px), 1fr));
    gap: 12px;
    padding: 16px 32px 48px;
  }}

  /* ─── Card ─── */
  .pick-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-left-width: 3px;
    border-radius: 4px;
    padding: 16px;
    display: flex;
    gap: 14px;
    opacity: 0;
    transform: translateY(12px);
    animation: reveal 0.4s ease forwards;
  }}

  @keyframes reveal {{
    to {{ opacity: 1; transform: translateY(0); }}
  }}

  .border-gold   {{ border-left-color: var(--gold); }}
  .border-silver {{ border-left-color: var(--silver); }}
  .border-dim    {{ border-left-color: var(--border); }}

  .pick-card:hover {{
    background: var(--surface2);
    border-color: var(--text-dim);
    border-left-color: inherit;
  }}

  /* ─── Rank column ─── */
  .card-rank {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    min-width: 36px;
    padding-top: 2px;
  }}

  .rank-num {{
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 900;
    font-size: 22px;
    line-height: 1;
    color: var(--amber);
  }}

  .stars {{
    font-size: 10px;
    letter-spacing: 1px;
    line-height: 1;
  }}

  .star-filled {{ color: var(--gold); }}
  .star-empty  {{ color: var(--text-dim); }}

  .badge-waiting {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 8px;
    letter-spacing: 0.05em;
    color: var(--amber-dim);
    border: 1px solid var(--amber-dim);
    padding: 1px 4px;
    border-radius: 2px;
    text-align: center;
    line-height: 1.4;
  }}

  /* ─── Card body ─── */
  .card-body {{
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}

  .player-row {{
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }}

  .player-name {{
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 700;
    font-size: 18px;
    color: var(--text);
    letter-spacing: 0.02em;
    flex: 1;
    min-width: 0;
  }}

  .conf-badge {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
    padding: 2px 7px;
    border-radius: 2px;
    text-transform: uppercase;
  }}

  .conf-high {{ background: var(--green-dim);  color: var(--green); }}
  .conf-med  {{ background: var(--amber-dim);  color: var(--amber); }}
  .conf-low  {{ background: var(--text-dim);   color: var(--text-sub); }}

  .score-badge {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 2px;
  }}

  .score-high {{ color: var(--amber); border: 1px solid var(--amber-dim); }}
  .score-mid  {{ color: var(--silver); border: 1px solid var(--border); }}
  .score-low  {{ color: var(--text-sub); border: 1px solid var(--text-dim); }}

  .matchup-line {{
    font-size: 12px;
    color: var(--text-sub);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}

  .pitcher-line {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-sub);
  }}

  /* ─── Stats rows ─── */
  .stats-row {{
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }}

  .stat {{
    display: flex;
    flex-direction: column;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 4px 8px;
    min-width: 60px;
  }}

  .stat-label {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 8px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-sub);
    line-height: 1;
    margin-bottom: 2px;
  }}

  .stat-value {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    font-weight: 700;
    color: var(--text);
    line-height: 1;
  }}

  /* ─── Tags ─── */
  .tags-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }}

  .tag {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    padding: 2px 7px;
    border-radius: 2px;
    border: 1px solid transparent;
    letter-spacing: 0.03em;
  }}

  .tag-green {{ color: var(--green);    background: rgba(52, 211, 153, 0.08);  border-color: var(--green-dim); }}
  .tag-red   {{ color: var(--red);      background: rgba(248, 113, 113, 0.08); border-color: var(--red-dim); }}
  .tag-amber {{ color: var(--amber);    background: rgba(245, 158, 11, 0.08);  border-color: var(--amber-dim); }}
  .tag-dim   {{ color: var(--text-sub); background: transparent;               border-color: var(--border); }}
  .tag-warn  {{ color: #FB923C;         background: rgba(251, 146, 60, 0.08);  border-color: #7C2D12; }}

  /* ─── Why line ─── */
  .why-line {{
    font-size: 11px;
    color: var(--text-sub);
    line-height: 1.4;
  }}

  .why-label {{
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    font-size: 9px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-dim);
    margin-right: 4px;
  }}

  /* ─── Footer ─── */
  .site-footer {{
    position: relative;
    z-index: 1;
    border-top: 1px solid var(--border);
    padding: 16px 32px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--text-sub);
    letter-spacing: 0.05em;
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
  }}

  /* ─── Responsive ─── */
  @media (max-width: 600px) {{
    .site-header  {{ padding: 16px; }}
    .picks-header {{ padding: 16px 16px 0; }}
    .picks-grid   {{ padding: 12px 16px 32px; gap: 8px; }}
    .site-footer  {{ padding: 12px 16px; }}
    .stat         {{ min-width: 52px; }}
  }}
</style>
</head>
<body>

<header class="site-header">
  <div class="header-left">
    <div class="site-title">⚾ HomeRunBets</div>
    <div class="site-date">{_esc(today)} &nbsp;·&nbsp; Top {len(picks)} Picks</div>
  </div>
  <div class="model-chips">
    <div class="chip chip-auc">Model AUC {_esc(auc_str)}</div>
    <div class="chip chip-auc">ML Weight {_esc(ml_str)}</div>
    <div class="chip {'chip-pnl' if net_pnl >= 0 else 'chip-neg'}">P&amp;L {_esc(pnl_str)}</div>
    <div class="chip {'chip-pnl' if net_pnl >= 0 else 'chip-neg'}">ROI {_esc(roi_str)}</div>
    <div class="chip">{_esc(record)}</div>
  </div>
</header>

<div class="picks-header">
  <span class="picks-title">Today's Ranked Picks</span>
  <div class="picks-divider"></div>
</div>

<div class="picks-grid">
{cards_html}
</div>

<footer class="site-footer">
  <span>HomeRunBets · github.com/sliwij25/HomeRunBets</span>
  <span>Generated {_esc(today)} · AUC {_esc(auc_str)}</span>
</footer>

</body>
</html>"""

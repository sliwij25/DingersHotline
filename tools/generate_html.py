"""
generate_html.py
Generate a self-contained HTML picks page for GitHub Pages.
Called from daily_picks.py after picks are ranked.
"""

from __future__ import annotations
import html as _html
from itertools import groupby


def _esc(s) -> str:
    return _html.escape(str(s)) if s is not None else ""


def _stat(label: str, value, suffix: str = "", fmt: str = "") -> str:
    if value is None:
        return ""
    text = f"{value:{fmt}}{suffix}" if fmt else f"{value}{suffix}"
    return (
        f'<div class="stat">'
        f'<span class="stat-label">{_esc(label)}</span>'
        f'<span class="stat-value">{_esc(text)}</span>'
        f'</div>'
    )


def _star_count(stars_str: str) -> int:
    return (stars_str or "").count("★")


def _star_html(stars_str: str) -> str:
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


def _bucket_label(n: int) -> str:
    return {
        5: "Elite Picks",
        4: "Strong Plays",
        3: "Solid Looks",
        2: "Worth Watching",
        1: "Speculative",
        0: "Low Confidence",
    }.get(n, "Other")


def _build_card(rank: int, pick: dict) -> str:
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
    bpp_rank  = sig.get("bpp_proj_rank")
    ev_10     = sig.get("ev_10")
    h2h_hr    = sig.get("h2h_hr")
    h2h_ab    = sig.get("h2h_ab")

    wind_arrow = ""
    if wind_deg is not None:
        arrows = ["↑","↗","→","↘","↓","↙","←","↖"]
        wind_arrow = arrows[(round(wind_deg / 45) + 4) % 8]

    home_away_str = "Home" if is_home else "Away"
    waiting_badge = '<span class="badge-waiting">LINEUP PENDING</span>' if status == "waiting" else ""
    conf_class    = _confidence_class(conf)

    # Tags
    platoon_html = ""
    if platoon == "PLATOON+":
        platoon_html = '<span class="tag tag-green">PLATOON+</span>'
    elif platoon == "platoon-":
        platoon_html = '<span class="tag tag-red">platoon−</span>'

    park_html = ""
    if park_hr is not None:
        if park_hr >= 110:
            park_html = f'<span class="tag tag-green">Park {park_hr:.0f}%</span>'
        elif park_hr <= 90:
            park_html = f'<span class="tag tag-red">Park {park_hr:.0f}%</span>'
        else:
            park_html = f'<span class="tag tag-dim">Park {park_hr:.0f}%</span>'

    weather_tags = ""
    if temp_f is not None:
        cls = "tag-green" if temp_f >= 80 else ("tag-red" if temp_f <= 50 else "tag-dim")
        weather_tags += f'<span class="tag {cls}">{temp_f:.0f}°F</span>'
    if wind_mph is not None and wind_arrow:
        weather_tags += f'<span class="tag tag-dim">Wind {wind_mph:.0f}mph {wind_arrow}</span>'

    form_html = ""
    if form and form >= 1:
        form_html = f'<span class="tag tag-amber">{form}HR / 14d</span>'

    pitcher_html = ""
    if p_hr9 is not None:
        cls = "tag-red" if p_hr9 >= 2 else ("tag-amber" if p_hr9 >= 1 else "tag-dim")
        pitcher_html = f'<span class="tag {cls}">Pitcher L3: {p_hr9:.1f} HR/9</span>'

    h2h_html = ""
    if h2h_hr is not None and h2h_hr >= 1:
        h2h_html = f'<span class="tag tag-green">H2H {h2h_hr}HR/{h2h_ab or "—"}AB</span>'

    ev_html = ""
    if ev_10 is not None:
        cls = "tag-green" if ev_10 > 0 else "tag-red"
        ev_html = f'<span class="tag {cls}">EV ${ev_10:+.2f}</span>'

    best_odds  = sig.get("best_odds")
    pin_odds   = sig.get("pinnacle_odds")
    best_book  = sig.get("best_book")
    odds_html  = ""
    if best_odds:
        book_label = f" · {best_book}" if best_book else ""
        pin_part   = f" &nbsp;|&nbsp; <span class='odds-pin'>Pinnacle {_esc(str(pin_odds))}</span>" if pin_odds else ""
        odds_html  = (
            f'<div class="odds-line">'
            f'Best odds: <span class="odds-best">{_esc(str(best_odds))}</span>'
            f'<span class="odds-book">{_esc(book_label)}</span>'
            f'{pin_part}'
            f'</div>'
        )

    pa_html = ""
    if pa is not None and pa < 40:
        pa_html = f'<span class="tag tag-warn">{pa} PA — small sample</span>'

    score_class = "score-high" if score >= 18 else ("score-mid" if score >= 14 else "score-low")

    matchup_line = f"{_esc(matchup)}"
    if venue:
        matchup_line += f" &nbsp;·&nbsp; {_esc(venue)}"
    matchup_line += f" &nbsp;·&nbsp; {home_away_str}"
    if bat_order:
        matchup_line += f" &nbsp;·&nbsp; #{bat_order} in order"

    pitcher_line = f"{_esc(bat_side)}HB vs {_esc(pitcher)} ({_esc(p_throws)})"

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

    delay = (rank - 1) * 0.04

    return f"""
        <div class="pick-card" style="animation-delay:{delay:.2f}s">
            <div class="card-rank">
                <span class="rank-num">#{rank}</span>
                {_star_html(stars_str)}
                {waiting_badge}
            </div>
            <div class="card-body">
                <div class="player-row">
                    <span class="player-name">{_esc(player)}</span>
                    <span class="score-badge {score_class}">{score:.1f}</span>
                </div>
                <div class="matchup-line">{matchup_line}</div>
                <div class="pitcher-line">{pitcher_line}</div>
                {stats_html}
                <div class="tags-row">{tags_html}</div>
                {odds_html}
                <div class="why-line"><span class="why-label">Why:</span> {_esc(reasoning)}</div>
            </div>
        </div>"""


def generate_picks_html(
    picks: list[dict],
    today: str,
    auc: float = 0.0,
    ml_influence: float = 0.0,
    win_rate: str = "—",
    net_pnl: float = 0.0,
    roi: float = 0.0,
    record: str = "—",
    model_yesterday_pnl: float | None = None,
    model_cumulative_pnl: float | None = None,
    tier_hit_rates: dict | None = None,
) -> str:
    # tier_hit_rates: {star_count: (n_picks, n_homers)} — pre-computed by daily_picks.py

    # Group picks by star count (descending)
    buckets: dict[int, list[tuple[int, dict]]] = {}
    for i, pick in enumerate(picks):
        n = _star_count(pick.get("stars", ""))
        buckets.setdefault(n, []).append((i + 1, pick))

    sections_html = ""
    for star_n in sorted(buckets.keys(), reverse=True):
        label        = _bucket_label(star_n)
        filled_stars = "★" * star_n
        empty_stars  = "☆" * (5 - star_n)
        group_picks  = buckets[star_n]

        # Hit rate badge for this tier
        hit_rate_html = ""
        if tier_hit_rates and star_n in tier_hit_rates:
            n_picks, n_homers = tier_hit_rates[star_n]
            if n_picks > 0:
                rate = n_homers / n_picks * 100
                hit_rate_html = (
                    f'<span class="tier-hit-rate">'
                    f'{rate:.0f}% HR rate'
                    f'<span class="tier-hit-count"> ({n_picks} picks)</span>'
                    f'</span>'
                )
            else:
                hit_rate_html = '<span class="tier-hit-rate tier-no-history">no history yet</span>'

        cards = "".join(_build_card(rank, pick) for rank, pick in group_picks)

        sections_html += f"""
    <section class="tier-section">
        <div class="tier-header">
            <span class="tier-stars">
                <span class="star-filled">{filled_stars}</span><span class="star-empty">{empty_stars}</span>
            </span>
            <span class="tier-label">{_esc(label)}</span>
            <span class="tier-count">{len(group_picks)} pick{"s" if len(group_picks) != 1 else ""}</span>
            {hit_rate_html}
            <div class="tier-rule"></div>
        </div>
        <div class="picks-grid">
{cards}
        </div>
    </section>"""

    auc_str = f"{auc:.3f}" if auc else "—"
    ml_str  = f"{ml_influence*100:.0f}%" if ml_influence else "—"

    def _pnl_chip(label: str, value: float | None, since: str = "") -> str:
        if value is None:
            return ""
        fmt = f"${value:+.2f}"
        css = "chip-pnl-pos" if value > 0 else "chip-pnl-neg" if value < 0 else "chip-auc"
        since_html = f' <span class="chip-since">since {_esc(since)}</span>' if since else ""
        return f'<div class="chip {css}">{_esc(label)} {_esc(fmt)}{since_html}</div>'

    yesterday_chip  = _pnl_chip("Yesterday", model_yesterday_pnl)
    cumulative_chip = _pnl_chip("Model P&L", model_cumulative_pnl, since="Apr 16")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dingers Hotline</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600;700&family=Source+Serif+4:wght@400;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:         #FAFAF7;
    --surface:    #FFFFFF;
    --surface2:   #F3F2EE;
    --border:     #E2DED6;
    --border-dark:#C8C2B8;
    --navy:       #1B2A4A;
    --navy-mid:   #2D4070;
    --red:        #C8102E;
    --red-dim:    #F9E5E8;
    --gold:       #D4A017;
    --gold-dim:   #FDF5DC;
    --green:      #1A6B3C;
    --green-dim:  #E4F2EB;
    --amber:      #B45309;
    --amber-dim:  #FEF3C7;
    --text:       #1A1A1A;
    --text-sub:   #6B6560;
    --text-dim:   #A8A29E;
    --grass:      #2D5A27;
  }}

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }}

  /* ─── Pinstripe header ─── */
  .site-header {{
    background: var(--navy);
    background-image: repeating-linear-gradient(
      90deg,
      transparent,
      transparent 47px,
      rgba(255,255,255,0.04) 47px,
      rgba(255,255,255,0.04) 48px
    );
    color: #fff;
    padding: 28px 36px 24px;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 20px;
    border-bottom: 4px solid var(--red);
  }}

  .header-left {{
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}

  .site-title {{
    font-family: 'Oswald', sans-serif;
    font-weight: 700;
    font-size: clamp(30px, 5vw, 52px);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #FFFFFF;
    line-height: 1;
    display: flex;
    align-items: center;
    gap: 12px;
  }}

  .title-ball {{
    display: inline-block;
    width: 0.85em;
    height: 0.85em;
    flex-shrink: 0;
    opacity: 0.9;
  }}

  .site-date {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: rgba(255,255,255,0.55);
    letter-spacing: 0.12em;
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
    padding: 5px 12px;
    border-radius: 3px;
    border: 1px solid rgba(255,255,255,0.2);
    background: rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.7);
    white-space: nowrap;
  }}
  .chip.chip-auc {{ color: #FBBF24; border-color: rgba(251,191,36,0.4); }}
  .chip.chip-pnl-pos {{ color: #4ADE80; border-color: rgba(74,222,128,0.4); }}
  .chip.chip-pnl-neg {{ color: #F87171; border-color: rgba(248,113,113,0.4); }}
  .chip-since {{ font-size: 9px; opacity: 0.55; font-weight: 400; }}

  /* ─── Tier section ─── */
  .tier-section {{
    padding: 28px 36px 8px;
  }}

  .tier-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }}

  .tier-stars {{
    font-size: 16px;
    letter-spacing: 2px;
    line-height: 1;
    flex-shrink: 0;
  }}

  .star-filled {{ color: var(--gold); }}
  .star-empty  {{ color: var(--border-dark); }}

  .tier-label {{
    font-family: 'Oswald', sans-serif;
    font-weight: 600;
    font-size: 15px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--navy);
    white-space: nowrap;
  }}

  .tier-count {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-dim);
    white-space: nowrap;
  }}

  .tier-hit-rate {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 700;
    color: var(--green);
    background: var(--green-dim);
    border: 1px solid #A7D7B8;
    border-radius: 3px;
    padding: 2px 8px;
    white-space: nowrap;
  }}

  .tier-hit-count {{
    font-weight: 400;
    color: var(--text-dim);
    font-size: 10px;
  }}

  .tier-no-history {{
    color: var(--text-dim);
    background: var(--surface2);
    border-color: var(--border);
    font-weight: 400;
  }}

  .tier-rule {{
    flex: 1;
    height: 1px;
    background: var(--border);
  }}

  /* ─── Cards grid ─── */
  .picks-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 560px), 1fr));
    gap: 10px;
    margin-bottom: 20px;
  }}

  /* ─── Card ─── */
  .pick-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px;
    display: flex;
    gap: 14px;
    opacity: 0;
    transform: translateY(10px);
    animation: reveal 0.35s ease forwards;
    transition: box-shadow 0.15s, border-color 0.15s;
  }}

  @keyframes reveal {{
    to {{ opacity: 1; transform: translateY(0); }}
  }}

  .pick-card:hover {{
    border-color: var(--navy);
    box-shadow: 0 2px 12px rgba(27,42,74,0.10);
  }}

  /* ─── Rank column ─── */
  .card-rank {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    min-width: 40px;
    padding-top: 2px;
  }}

  .rank-num {{
    font-family: 'Oswald', sans-serif;
    font-weight: 700;
    font-size: 24px;
    line-height: 1;
    color: var(--navy);
  }}

  .stars {{
    font-size: 10px;
    letter-spacing: 1px;
    line-height: 1;
  }}

  .badge-waiting {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 7px;
    letter-spacing: 0.04em;
    color: var(--amber);
    border: 1px solid #D97706;
    background: var(--amber-dim);
    padding: 2px 4px;
    border-radius: 2px;
    text-align: center;
    line-height: 1.4;
    white-space: nowrap;
    margin-top: 2px;
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
    font-family: 'Oswald', sans-serif;
    font-weight: 600;
    font-size: 19px;
    color: var(--navy);
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

  .conf-high {{ background: var(--green-dim);  color: var(--green);  border: 1px solid #A7D7B8; }}
  .conf-med  {{ background: var(--amber-dim);  color: var(--amber);  border: 1px solid #FCD34D; }}
  .conf-low  {{ background: var(--surface2);   color: var(--text-dim); border: 1px solid var(--border); }}

  .score-badge {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 2px;
  }}

  .score-high {{ color: var(--red);     background: var(--red-dim);    border: 1px solid #F9A8B4; }}
  .score-mid  {{ color: var(--navy);    background: #EEF1F8;           border: 1px solid #C5CDE8; }}
  .score-low  {{ color: var(--text-sub); background: var(--surface2);  border: 1px solid var(--border); }}

  .matchup-line {{
    font-size: 12px;
    color: var(--text-sub);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-family: 'Source Serif 4', serif;
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
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 9px;
    min-width: 64px;
  }}

  .stat-label {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 8px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-dim);
    line-height: 1;
    margin-bottom: 2px;
  }}

  .stat-value {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    font-weight: 700;
    color: var(--navy);
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
    border-radius: 3px;
    border: 1px solid transparent;
    letter-spacing: 0.02em;
  }}

  .tag-green {{ color: var(--green);  background: var(--green-dim);  border-color: #A7D7B8; }}
  .tag-red   {{ color: var(--red);    background: var(--red-dim);    border-color: #F9A8B4; }}
  .tag-amber {{ color: var(--amber);  background: var(--amber-dim);  border-color: #FCD34D; }}
  .tag-dim   {{ color: var(--text-sub); background: var(--surface2); border-color: var(--border); }}
  .tag-warn  {{ color: #92400E;       background: #FEF3C7;           border-color: #FCD34D; }}

  /* ─── Why line ─── */
  .why-line {{
    font-size: 12px;
    color: var(--text-sub);
    line-height: 1.4;
    font-family: 'Source Serif 4', serif;
    font-style: italic;
  }}

  .why-label {{
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    font-size: 9px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-dim);
    margin-right: 4px;
    font-style: normal;
  }}

  .odds-line {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-sub);
    margin-top: 6px;
  }}
  .odds-best {{
    color: #4ADE80;
    font-weight: 700;
  }}
  .odds-book {{
    color: var(--text-dim);
    font-size: 10px;
  }}
  .odds-pin {{
    color: var(--text-dim);
    font-size: 10px;
  }}

  /* ─── Footer ─── */
  .site-footer {{
    background: var(--navy);
    border-top: 3px solid var(--red);
    padding: 14px 36px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: rgba(255,255,255,0.4);
    letter-spacing: 0.06em;
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 24px;
  }}

  /* ─── Responsive ─── */
  @media (max-width: 600px) {{
    .site-header   {{ padding: 18px; }}
    .tier-section  {{ padding: 20px 16px 4px; }}
    .picks-grid    {{ gap: 8px; }}
    .site-footer   {{ padding: 12px 16px; }}
    .stat          {{ min-width: 54px; }}
  }}
</style>
</head>
<body>

<header class="site-header">
  <div class="header-left">
    <div class="site-title">
      <svg class="title-ball" fill="#ffffff" viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg"><g><path d="M455.857,56.144c-74.86-74.859-196.662-74.859-271.521,0C17.087,223.392-9.275,272.783,2.398,298.264c8.318,18.153,32.898,19.077,63.015,17.249l-36.537,97.203c-6.838,18.194-2.549,38.035,11.195,51.778c13.744,13.743,33.583,18.035,51.778,11.195L197.2,436.089c-2.507,34.987-3.349,64.4,16.534,73.511c3.325,1.524,7.055,2.4,11.403,2.4c28.973-0.002,85.294-38.91,230.72-184.335C530.715,252.806,530.715,131.003,455.857,56.144z M441.431,313.239C369.446,385.224,316.37,433.95,279.174,462.2c-41.868,31.797-54.167,30.124-56.94,28.854c-2.851-1.307-4.901-7.374-5.626-16.646c-0.922-11.81,0.244-27.541,1.479-44.196c0.209-2.826,0.421-5.681,0.625-8.557c0.247-3.466-1.288-6.82-4.073-8.899c-1.788-1.335-3.934-2.026-6.102-2.026c-1.209,0-2.424,0.214-3.589,0.652l-120.277,45.21c-10.765,4.047-22.043,1.608-30.174-6.524c-8.131-8.131-10.57-19.411-6.524-30.174l42.126-112.072c1.224-3.258,0.703-6.915-1.382-9.702c-2.085-2.787-5.444-4.321-8.919-4.06c-14.536,1.076-31.012,2.295-42.857,1.278c-8.892-0.763-14.721-2.793-15.994-5.572c-1.27-2.772-2.944-15.072,28.855-56.941c28.25-37.196,76.975-90.271,148.96-162.255c66.904-66.905,175.764-66.905,242.669,0C508.335,137.474,508.335,246.335,441.431,313.239z"/></g><g><path d="M320.096,28.297c-90.213,0-163.608,73.394-163.608,163.608s73.395,163.608,163.608,163.608s163.608-73.395,163.608-163.608S410.31,28.297,320.096,28.297z M320.096,48.698c36.338,0,69.551,13.613,94.828,35.995c-26.187,23.225-59.477,35.903-94.828,35.903c-35.351,0-68.641-12.679-94.828-35.903C250.544,62.309,283.758,48.698,320.096,48.698z M320.096,335.111c-36.338,0.001-69.552-13.611-94.829-35.995c26.187-23.225,59.478-35.903,94.829-35.903c35.351,0,68.641,12.679,94.828,35.903C389.647,321.499,356.433,335.111,320.096,335.111z M429.215,284.535c-30.034-26.977-68.377-41.722-109.12-41.722c-40.743,0-79.086,14.745-109.12,41.722c-21.246-24.99-34.087-57.336-34.087-92.631c0.001-35.293,12.842-67.64,34.088-92.63c30.034,26.977,68.377,41.722,109.12,41.722s79.086-14.745,109.119-41.722c21.246,24.99,34.087,57.336,34.087,92.63C463.302,227.198,450.46,259.545,429.215,284.535z"/></g></svg>
      Dingers Hotline
    </div>
    <div class="site-date">Latest Update: {_esc(today)} &nbsp;·&nbsp; {len(picks)} Picks</div>
  </div>
  <div class="model-chips">
    <div class="chip chip-auc">Model AUC {_esc(auc_str)}</div>
    <div class="chip chip-auc">ML Weight {_esc(ml_str)}</div>
    {yesterday_chip}
    {cumulative_chip}
  </div>
</header>

{sections_html}

<footer class="site-footer">
  <span>Dingers Hotline &nbsp;·&nbsp; github.com/sliwij25/DingersHotline</span>
  <span>Generated {_esc(today)} &nbsp;·&nbsp; Model AUC {_esc(auc_str)}</span>
</footer>

</body>
</html>"""

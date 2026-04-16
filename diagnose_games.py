"""
Diagnostic script to identify where the 2-game limitation is coming from.
Run this to see exactly what the MLB API is returning.
"""

import json
from datetime import date
import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

today = date.today().isoformat()

print("=" * 80)
print(f"GAME SCHEDULE DIAGNOSTIC — {today}")
print("=" * 80)

# Step 1: Fetch raw schedule from MLB API
print("\n[1] Fetching raw schedule from MLB API...")
try:
    resp = requests.get(
        f"{MLB_API_BASE}/schedule",
        params={
            "sportId": 1,
            "date": today,
            "hydrate": "lineups(person),probablePitcher,team,venue"
        },
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()
except Exception as e:
    print(f"ERROR: {e}")
    exit(1)

# Step 2: Show what we got
dates = data.get("dates", [])
print(f"\n    Dates returned: {len(dates)}")

if not dates:
    print("    ** No dates in response **")
    exit(1)

games = dates[0].get("games", [])
print(f"    Games in dates[0]: {len(games)}")

if not games:
    print("    ** No games in dates[0] **")
    exit(1)

# Step 3: Show each game
print(f"\n[2] Game Details:")
for i, game in enumerate(games, 1):
    away_team = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "?")
    home_team = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "?")
    game_time = game.get("gameDate", "?")[:16] if game.get("gameDate") else "?"
    away_lineup_confirmed = bool(game.get("lineups", {}).get("awayPlayers"))
    home_lineup_confirmed = bool(game.get("lineups", {}).get("homePlayers"))
    
    away_order = game.get("teams", {}).get("away", {}).get("battingOrder", [])
    home_order = game.get("teams", {}).get("home", {}).get("battingOrder", [])
    
    print(f"\n    Game {i}: {away_team} @ {home_team}  ({game_time})")
    print(f"      Away lineup confirmed: {away_lineup_confirmed} ({len(away_order)} batters)")
    print(f"      Home lineup confirmed: {home_lineup_confirmed} ({len(home_order)} batters)")
    
    # Show first 3 batters if available
    if away_lineup_confirmed:
        away_batters = game.get("lineups", {}).get("awayPlayers", [])[:3]
        print(f"      Away batters: {[b.get('fullName') for b in away_batters]}")
    
    if home_lineup_confirmed:
        home_batters = game.get("lineups", {}).get("homePlayers", [])[:3]
        print(f"      Home batters: {[b.get('fullName') for b in home_batters]}")

# Step 4: Summary
confirmed_away = sum(1 for g in games if bool(g.get("lineups", {}).get("awayPlayers")))
confirmed_home = sum(1 for g in games if bool(g.get("lineups", {}).get("homePlayers")))
both_confirmed = sum(
    1 for g in games
    if bool(g.get("lineups", {}).get("awayPlayers")) and
       bool(g.get("lineups", {}).get("homePlayers"))
)

print(f"\n[3] Summary:")
print(f"    Total games: {len(games)}")
print(f"    Away lineups confirmed: {confirmed_away}")
print(f"    Home lineups confirmed: {confirmed_home}")
print(f"    Both sides confirmed: {both_confirmed}")
print(f"    Time: {today}")

print("\n" + "=" * 80)
print("If you see only 2 games here, then MLB API is only returning 2 games for today.")
print("This is normal in early morning before lineups are posted.")
print("=" * 80)

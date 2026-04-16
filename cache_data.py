"""
cache_data.py
Save today's Homer context to a JSON file for offline testing.

Run this ONCE per morning after daily_picks.py, then iterate on
pick logic with test_homer_prompt.py without re-fetching data.

Usage:
    python cache_data.py

Output:
    debug_context_YYYY-MM-DD.json (timestamped, ~500KB–1MB)
"""

import json
import sys
import os
from datetime import date
from pathlib import Path

# Add agents to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents import Homer

def main():
    today = date.today().isoformat()
    cache_file = Path(__file__).parent / f"debug_context_{today}.json"
    
    print(f"Saving today's Homer context to {cache_file.name}...")
    
    homer = Homer()
    context = homer._gather_data()
    
    # Save the context dict
    with open(cache_file, "w") as f:
        json.dump(context, f, indent=2)
    
    print(f"✓ Saved {cache_file.name}")
    print(f"  Size: {cache_file.stat().st_size / 1024:.1f}KB")
    print(f"  Players in signals: {len(context.get('player_signals', {}))}")
    print(f"\nUse test_homer_prompt.py to iterate on pick logic.")

if __name__ == "__main__":
    main()

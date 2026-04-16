# Claude Usage Optimization for HomeRunBets

This guide explains how to cut Claude API costs (and other API costs) by 10-50x during development.

---

## The Problem

**Old workflow (expensive):**
1. Run `daily_picks.py` → fetches ~100 API calls, generates picks
2. Results don't look right → tweak the code
3. Run `daily_picks.py` again → **another ~100 API calls**
4. Repeat 3-5x during morning dev → **massive token/API bill**

**Each run costs:**
- ~50-100 Odds API requests (one per game)
- ~100 MLB Stats API calls (confirmed lineups, pitcher form, splits, H2H)
- ~10 Statcast CSV fetches (batter/pitcher leaderboards)
- **Total:** ~200 external API calls per run

---

## The Solution: Cache + Test Loop

### Step 1: Run Once per Day (Fresh Data)

```bash
python daily_picks.py
```

This runs normally, fetches all real data, and **automatically saves to:**
```
debug_context_2026-04-15.json  (~500KB–1MB)
```

### Step 2: Iterate with Cached Data (Unlimited Free Testing)

```bash
# Run 5-10 times without re-fetching:
python daily_picks.py --use-cache
python test_homer_prompt.py                  # alternative test script
python test_homer_prompt.py debug_context_2026-04-15.json  # specific date
```

Each of these **costs $0** — no external API calls.

---

## Workflow Examples

### Example 1: You want to tweak pick scoring logic

```bash
# Morning: fetch data once
$ python daily_picks.py
  ✓ ~200 API calls, 2 minutes, costs ~$0.10

# You see picks and want to test a new scoring formula
# Edit predictor.py → modify _score_player() function

# Test it 5x without re-fetching (each <5 seconds):
$ python daily_picks.py --use-cache
$ python daily_picks.py --use-cache
$ python daily_picks.py --use-cache
  ✓ 0 API calls, 15 seconds, costs $0.00
```

**Cost savings:** 4 full runs worth of data fetching avoided.

### Example 2: You want to debug player signal accuracy

```bash
# Start with cached data
$ python test_homer_prompt.py

# See output, then modify Python logic in predictor.py
# Re-run test without refetching:
$ python test_homer_prompt.py

# Repeat 10x if needed — costs $0.00
```

---

## New Tools

### `cache_data.py` — Explicit cache saving
```bash
python cache_data.py
```
Output: `debug_context_YYYY-MM-DD.json` with today's full data context.

**When to use:** If you deleted the cache file by accident, run this to regenerate.

### `test_homer_prompt.py` — Offline iteration
```bash
python test_homer_prompt.py                          # uses latest cache
python test_homer_prompt.py debug_context_2026-04-15.json  # specific cache
```

Output: Same pick ranking + narrative as `daily_picks.py`, but **instantly** (no API calls).

**When to use:** To test new ranking logic or verify signal accuracy.

### `daily_picks.py --use-cache` — Quick dev iteration
```bash
python daily_picks.py --use-cache
```

Output: Same as normal run, but loads cached data instead of fetching fresh.

**When to use:** Quick iteration on daily_picks.py without waiting for API calls.

---

## Cost Breakdown

| Task | Time | API Calls | Cost |
|------|------|-----------|------|
| `python daily_picks.py` (fresh) | 2 min | ~200 | ~$0.10 |
| `python daily_picks.py --use-cache` | 5 sec | 0 | $0.00 |
| `python test_homer_prompt.py` | 3 sec | 0 | $0.00 |
| Manual Claude Code iteration (10 min) | 10 min | 0 | ~$0.50 (chat context) |

**Scenario: Morning development with 5 test runs**
- **Old way:** Run `daily_picks.py` 5 times = 5 × 200 API calls = $0.50
- **New way:** Run `daily_picks.py` once + `--use-cache` 4 times = 200 API calls = $0.10

**Savings: 80% on API costs.**

---

## Best Practices

### ✅ DO

- ✅ Run `daily_picks.py` **once per morning** to fetch real data
- ✅ Use `--use-cache` flag for **all subsequent testing**
- ✅ Save your `debug_context_*.json` files (they're ephemeral but useful)
- ✅ Modify `predictor.py` score functions and test with cached data
- ✅ **Close Claude Code tabs** at end of day to avoid idle context accumulation

### ❌ DON'T

- ❌ Run `daily_picks.py` 5+ times during development (reuse cache instead)
- ❌ Leave Claude Code sessions open for 8+ hours
- ❌ Spawn subagents for simple debugging (use grep_search or semantic_search in main chat)
- ❌ Manually refetch odds/lineups — let the caching handle it

---

## Troubleshooting

### "No cache file found"
```bash
# You tried --use-cache but didn't run fresh first
$ python daily_picks.py                # fetch fresh data, creates cache
$ python daily_picks.py --use-cache    # now works
```

### "Cache is stale (wrong date)"
```bash
# Cache from yesterday, but you want today's data
$ python daily_picks.py                # creates fresh cache for today
```

### "I want to force a fresh run"
```bash
# Just don't use --use-cache
$ python daily_picks.py                # always fetches fresh
```

---

## Integration with Development

**Recommended workflow for feature development:**

1. **Session A:** Plan changes (~30 min)
   - Read predictor.py, understand current scoring
   - Plan new logic
   - `/close` chat when done (avoids context creep)

2. **Session B:** Implement & test (~1 hour)
   - Edit predictor.py with new scoring logic
   - `python daily_picks.py` (fresh run, creates cache)
   - `python daily_picks.py --use-cache` (iterate 5-10x)
   - Compare results to old picks
   - `/close` when satisfied

3. **Session C:** Deploy to production (~15 min)
   - Run final `daily_picks.py` to confirm picks
   - Record bets in HomeRunBets.ipynb
   - Done

**Token savings:** Each separate session avoids context accumulation from the previous session.

---

## Questions?

If you notice a cache-related bug or want to extend this system, see the implementation in:
- `cache_data.py` — explicit cache saving
- `test_homer_prompt.py` — offline test runner
- `daily_picks.py --use-cache` — flag implementation

# HomeRunBets — Pick Grading System

Stars reflect **rank within today's top-20 pool** — fixed bands ensure consistent tier sizes
regardless of whether the overall pool is strong or weak on a given day.

---

## Star Meanings (AUC ≥ 0.65 — 5-tier system, active)

| Stars | Label | Ranks | Meaning |
|-------|-------|-------|---------|
| ★★★★★ | Elite | #1–3 | Top tier — strongest signal, model most confident |
| ★★★★☆ | Strong | #4–6 | High-confidence plays |
| ★★★☆☆ | Solid | #7–9 | Core picks — solid signal |
| ★★☆☆☆ | Speculative | #10–12 | Worth considering at favorable odds |
| ★☆☆☆☆ | Long shot | #13–15+ | Bottom tier / roster fallback |

### Star Meanings (AUC < 0.65 — 4-tier system)

| Stars | Label | Ranks | Meaning |
|-------|-------|-------|---------|
| ★★★★☆ | Strong | #1–5 | Top quartile — highest-confidence plays |
| ★★★☆☆ | Solid | #6–10 | Core picks — solid signal |
| ★★☆☆☆ | Speculative | #11–15 | Bottom tier — worth considering at favorable odds |
| ★☆☆☆☆ | Long shot | Beyond top 15 | Roster fallback only |

---

## AUC Ceiling (model accuracy → max stars available today)

| AUC Range | Max Stars | Label |
|-----------|-----------|-------|
| ≥ 0.65 | ★★★★★ | Reliable — ML is driving meaningful signal |
| 0.55–0.64 | ★★★★☆ | Developing — ML adds value, heuristics still lead |
| < 0.55 | ★★★☆☆ | Early stage — model near random, trust heuristics only |

Current AUC: **0.612** → max stars today: **★★★★☆**

---

## Updating This File

- **Rank band cutoffs** — adjust `_stars_from_rank()` in `agents/predictor.py` → `Homer._rank_picks_python()`
- The "Current AUC" line above is informational — the code reads it live from `ml_weights.json`

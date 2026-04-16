# HomeRunBets — Pick Grading System

Stars combine two signals into one rating:
1. **Rank within today's pool** — where this pick sits relative to all 20 picks today
2. **Model accuracy ceiling** — how much to trust the rankings at the current AUC

---

## Star Meanings

| Stars | Label | Meaning |
|-------|-------|---------|
| ★★★★★ | Elite | Top-ranked pick AND model is reliable (AUC ≥ 0.65). High conviction. |
| ★★★★☆ | Strong | Top-ranked pick at current model accuracy, or high-ranked with reliable model. |
| ★★★☆☆ | Good | Solid pick, middle of today's pool. Worth considering. |
| ★★☆☆☆ | Speculative | Lower half of today's pool. Situational — good odds may justify. |
| ★☆☆☆☆ | Long shot | Bottom of today's rankings. Only play with very favorable odds. |

---

## AUC Ceiling (model accuracy → max stars available today)

| AUC Range | Max Stars | Label |
|-----------|-----------|-------|
| ≥ 0.65 | ★★★★★ | Reliable — ML is driving meaningful signal |
| 0.55–0.64 | ★★★★☆ | Developing — ML adds value, heuristics still lead |
| < 0.55 | ★★★☆☆ | Early stage — model near random, trust heuristics only |

Current AUC: **0.634** → max stars today: **★★★★☆**

---

## Rank Bands (top 20 picks)

| Ranks | Base Stars |
|-------|------------|
| 1–3 | 5 stars (capped by AUC ceiling) |
| 4–7 | 4 stars (capped by AUC ceiling) |
| 8–12 | 3 stars |
| 13–16 | 2 stars |
| 17–20 | 1 star |

Final stars = `min(rank_band_stars, auc_ceiling_stars)`

---

## Updating This File

- **AUC ceiling thresholds** — adjust in `agents/predictor.py` → `Homer._star_rating()`
- **Rank bands** — adjust in the same method
- **Star labels/meanings** — update the table above and keep in sync with `_star_rating()`
- The "Current AUC" line above is informational — the code reads it live from `ml_weights.json`

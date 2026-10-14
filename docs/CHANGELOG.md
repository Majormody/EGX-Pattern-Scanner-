# Changelog

## Pivot-aware update

- Replaced always-highest-high resistance selection with the most recent confirmed local swing high that has at least 0.45 ATR of nearby prominence; explicitly labels the previous-range-high fallback.
- Added `pivot_date`, `pivot_method`, `pivot_prominence_atr`, `pivot_count`, `pivot_age_bars`, and `base_highest_high` output fields.
- Strength's impulse-peak alignment is compared to the overall base high, not the newly selected lower breakout pivot.
- Normalizes stock and EGX30 indexes to calendar dates before aligning relative-strength data.
- Missing RS data no longer receives an artificial 50/100 grade; the grade remains blank and the total score is normalized over available components.
- Adds offline tests for recent-lower-pivot detection and timestamp-normalized benchmark alignment.

The pivot method remains a heuristic, not a fitted trendline or guarantee that the selected pivot matches a chart annotation. Visually validate `pivot_date`, `pivot_method`, and `ceiling` before trading.

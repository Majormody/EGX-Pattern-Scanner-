# Pattern and relative-strength methodology

## Design goal

Approximate how a chart reader notices a strong prior advance, a quiet consolidation, and price tightening below a resistance shelf. The scanner does not try to prove that a pattern will succeed; it ranks candidates and exposes the ingredient grades for review. The selected `ceiling` is now a candidate breakout pivot, not necessarily the highest high in the base; `base_highest_high`, `pivot_date`, `pivot_method`, `pivot_prominence_atr`, `pivot_count`, and `pivot_age_bars` help you inspect that choice.

## The base search

The scanner tests every configured base length (default 12 to 45 trading bars), rather than selecting one base length in advance. For each candidate:

1. The candidate base consists of the chosen number of latest bars (for a forming candidate) or the bars immediately before a potential breakout bar.
2. The resistance pivot is the **most recent confirmed local swing high** in the base, excluding the newest base bar. The current detector requires two bars on either side and at least 0.45 ATR of nearby prominence. If no such swing is found, it falls back to the previous range high and labels that method explicitly. This is still a heuristic: it does not yet fit descending trendlines or fully score multi-touch resistance shelves.
3. The impulse search examines the bars immediately before the base, locates a recent peak, and compares it with the lowest low before that peak. It also compares the base pullback to the advance and checks that the base's resistance is reasonably close to the impulse peak.
4. The oldest and newest thirds of the base are compared for average candle-range shrinkage and total swing-width shrinkage.
5. Volume is evaluated within the stock itself: average up-day vs down-day volume, whether down-day volume fades toward the end of the base, and whether base volume is below the preceding impulse-leg volume.
6. The current close is measured against the ceiling as a fraction of base height.
7. Relative strength compares the stock's close with EGX30's close on aligned trading dates.

## Score components

| Grade | Weight | Implementation intent |
|---|---:|---|
| Strength | 20 | Advance/pullback ratio, advance measured in ATR units, alignment with the base ceiling, and time from the peak to base |
| Trend | 15 | Mid-SMA slope, fast-EMA vs mid-SMA alignment, and share of base closes above the mid-SMA |
| Contraction | 25 | Relative reduction in average candle range and swing width from oldest to newest third |
| Volume | 15 | Up/down volume balance, fading late-base down-day volume, and base-vs-advance volume quietness |
| Closeness | 15 | Gap below the ceiling relative to the base's height |
| Relative strength | 10 | RSI of the stock/EGX30 close ratio; the score rises as RS RSI goes from 35 to 65 |

These weights sum to 100. The output score is a normalized weighted grade, not a probability. Most thresholds are continuous scores. The user-controlled minimum forming score (default 62) and the minimum required recent breakout volume are operational filters, not calibrated statistical boundaries.

## The EGX relative-strength RSI

For each date where stock and benchmark prices can be aligned:

`RS ratio = stock close / EGX30 close`

`RS RSI = 14-period RSI(RS ratio)`

The ratio's absolute level is not meaningful; its direction and RSI are. Stock and benchmark indexes are aligned by normalized calendar date. RS RSI above 50 usually indicates the ratio has had more/upward than downward momentum over the RSI's smoothing window. A stronger reading suggests the stock is outperforming EGX30 in recent relative momentum. If RS data is unavailable, the RS grade remains blank and the total score is renormalized across the other available components rather than treating missing data as a neutral grade. The scanner also reports:

- `excess_return_20d_pct` = stock 20-bar price return minus EGX30 20-bar price return.
- `excess_return_60d_pct` = stock 60-bar price return minus EGX30 60-bar price return.

This is a first-step **relative price-strength** measure. Since `^CASE30` is the price-return index and the input uses regular closes, the measure does not include dividends on either side.

## Status logic

- `FORMING`: latest close remains at/below the estimated ceiling; the score passes the threshold; closeness grade is at least 10/100.
- `BREAKOUT`: a recent setup scored above the threshold and a later bar closed above its pivot with at least the configured relative volume (default 1.3×) and close in the upper part of the daily range. The status remains under review during the hold window as long as no close has fallen below the pivot.
- `FAILED`: a recent qualifying trigger was followed by a close below its pivot within the monitoring window.
- `NONE`: no candidate met the forming or recent-breakout conditions. The best available candidate's score and grades are still reported.
- `INSUFFICIENT_DATA`: there are not enough daily bars for the chosen SMA/base/impulse windows.
- `NO_PRICE_DATA`: usable daily OHLCV is unavailable for the ticker alias.

The current implementation is a daily-bar scanner. A trigger can only be evaluated after a daily candle is available from the provider. It does not trade intraday or issue orders.

## What should be improved after first use

1. Compare candidate pivots and base windows with manually labeled EGX charts, then tune weights and score thresholds.
2. Add exchange-calendar checks and anomaly validation for split, rights-issue, dividend, and price-limit events.
3. Backtest only using data as it would have been known at each historical date. Include EGX liquidity constraints, fees, slippage, price limits, and survivorship bias in the evaluation.
4. Validate the stock universe against a current official EGX-listed-securities export. Public screeners and free price history are not guaranteed complete.
5. Track failures and post-breakout returns in a separate evaluation report before treating any score as useful for investment decisions.

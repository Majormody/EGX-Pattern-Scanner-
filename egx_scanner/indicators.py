"""Indicator helpers kept independent from market-data providers."""
from __future__ import annotations

import numpy as np
import pandas as pd


def clip01(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return float(np.clip(value, 0.0, 1.0))


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Wilder-style RSI using exponential smoothing."""
    x = pd.to_numeric(series, errors="coerce").astype(float)
    delta = x.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = losses.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # Handle uninterrupted rises/falls and a flat series explicitly.
    out = out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    out = out.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    out = out.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return out


def true_range(data: pd.DataFrame) -> pd.Series:
    previous_close = data["Close"].shift(1)
    pieces = pd.concat(
        [
            data["High"] - data["Low"],
            (data["High"] - previous_close).abs(),
            (data["Low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return pieces.max(axis=1)


def add_price_indicators(data: pd.DataFrame, fast_ema: int, mid_sma: int, atr_length: int,
                         rv_length: int) -> pd.DataFrame:
    out = data.copy()
    out["EMA_fast"] = out["Close"].ewm(span=fast_ema, adjust=False, min_periods=fast_ema).mean()
    out["SMA_mid"] = out["Close"].rolling(mid_sma, min_periods=mid_sma).mean()
    out["ATR"] = true_range(out).rolling(atr_length, min_periods=atr_length).mean()
    # Exclude the current session from the relative-volume average to avoid diluting a spike.
    out["RV"] = out["Volume"] / out["Volume"].shift(1).rolling(rv_length, min_periods=max(5, rv_length // 2)).mean()
    return out


def add_relative_strength(stock: pd.DataFrame, benchmark_close: pd.Series, rsi_length: int = 14) -> pd.DataFrame:
    """Add RS ratio RSI and excess returns against the EGX30 benchmark.

    RS ratio = stock close / EGX30 close. RSI is calculated on the ratio, not on
    the stock price alone. Both indexes are normalized to exchange calendar dates
    before alignment so timezone/time-of-day metadata cannot silently erase the
    benchmark series. The output retains the stock's original index.
    """
    out = stock.copy()

    def _calendar_dates(index: pd.Index) -> pd.DatetimeIndex:
        dates = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
        if dates.tz is not None:
            dates = dates.tz_localize(None)
        return dates.normalize()

    stock_dates = _calendar_dates(out.index)
    benchmark = pd.to_numeric(benchmark_close, errors="coerce").copy()
    benchmark.index = _calendar_dates(benchmark.index)
    benchmark = benchmark.loc[~benchmark.index.isna()].sort_index()
    benchmark = benchmark[~benchmark.index.duplicated(keep="last")]

    # Reindex by normalized date and forward-fill only across the stock's trading
    # dates. A prior benchmark close is valid on holidays/non-overlapping sessions.
    aligned_values = benchmark.reindex(stock_dates).ffill().to_numpy(dtype=float)
    aligned_benchmark = pd.Series(aligned_values, index=out.index, dtype=float)

    stock_close = pd.to_numeric(out["Close"], errors="coerce")
    valid = (stock_close > 0) & (aligned_benchmark > 0)
    ratio = (stock_close / aligned_benchmark).where(valid)
    out["RS_Ratio"] = ratio
    out["RS_RSI"] = rsi(ratio, rsi_length)
    for days in (20, 60):
        stock_return = stock_close.pct_change(days, fill_method=None) * 100.0
        benchmark_return = aligned_benchmark.pct_change(days, fill_method=None) * 100.0
        out[f"Excess_Return_{days}D_pct"] = stock_return - benchmark_return
    return out

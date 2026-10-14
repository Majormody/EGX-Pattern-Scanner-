"""Human-inspired tight-base pattern scoring and breakout state detection.

This is a ranking heuristic, not a predictive probability model. It scores multiple
candidate base lengths and makes all major ingredients visible in the output.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd

from .indicators import add_price_indicators, add_relative_strength, clip01
from .settings import ScanConfig

WEIGHTS = {
    "strength": 20.0,
    "trend": 15.0,
    "contraction": 25.0,
    "volume": 15.0,
    "closeness": 15.0,
    "relative_strength": 10.0,
}


def _mean_or_nan(values: pd.Series) -> float:
    cleaned = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(cleaned.mean()) if not cleaned.empty else float("nan")


def _safe_ratio(numerator: float, denominator: float) -> float:
    if not np.isfinite(numerator) or not np.isfinite(denominator) or denominator == 0:
        return float("nan")
    return float(numerator / denominator)


def _select_pivot_ceiling(base: pd.DataFrame, left_bars: int = 2,
                          right_bars: int = 2, min_prominence_atr: float = 0.45) -> dict[str, Any]:
    """Select the most recent confirmed, meaningful swing high in a candidate base.

    The newest base bar is excluded: its high cannot define the resistance it is
    supposed to break. A pivot must be a local high with two bars on either side
    and must stand at least `min_prominence_atr` above a nearby local low. If no
    swing high is prominent enough, fall back explicitly to the previous range
    high. The fallback is reported so it is not confused with a detected pivot.
    """
    prior = base.iloc[:-1]
    if prior.empty:
        return {"ceiling": float("nan"), "pivot_date": "", "pivot_method": "unavailable",
                "pivot_prominence_atr": float("nan"), "pivot_count": 0, "pivot_age_bars": -1}

    highs = prior["High"].to_numpy(dtype=float)
    lows = prior["Low"].to_numpy(dtype=float)
    atrs = prior["ATR"].to_numpy(dtype=float) if "ATR" in prior else np.full(len(prior), np.nan)
    candidates: list[dict[str, Any]] = []

    for i in range(left_bars, len(prior) - right_bars):
        hi = highs[i]
        left_max = float(np.nanmax(highs[i - left_bars:i]))
        right_max = float(np.nanmax(highs[i + 1:i + right_bars + 1]))
        # Strict comparison on the right makes the right-most bar of a flat
        # high plateau the representative swing-high pivot.
        if not (hi >= left_max and hi > right_max):
            continue
        atr_i = atrs[i] if i < len(atrs) and np.isfinite(atrs[i]) and atrs[i] > 0 else float("nan")
        if not np.isfinite(atr_i):
            continue
        lo = max(0, i - 3)
        end = min(len(prior), i + 4)
        nearby_low = float(np.nanmin(lows[lo:end]))
        prominence = (hi - nearby_low) / atr_i
        if prominence >= min_prominence_atr:
            candidates.append({
                "position": i,
                "price": float(hi),
                "date": prior.index[i].date().isoformat(),
                "prominence_atr": float(prominence),
            })

    if candidates:
        selected = candidates[-1]  # most recent confirmed meaningful pivot
        return {
            "ceiling": selected["price"],
            "pivot_date": selected["date"],
            "pivot_method": "last_confirmed_swing_high",
            "pivot_prominence_atr": selected["prominence_atr"],
            "pivot_count": len(candidates),
            "pivot_age_bars": int(len(base) - 1 - selected["position"]),
        }

    # Flat/tight bases sometimes have no individually prominent swing high.
    # Keep those candidates evaluable, but label this conservative fallback.
    fallback_pos = int(np.nanargmax(highs))
    atr_i = atrs[fallback_pos] if fallback_pos < len(atrs) else float("nan")
    prominence = ((highs[fallback_pos] - float(np.nanmin(lows[max(0, fallback_pos - 3):min(len(prior), fallback_pos + 4)]))) / atr_i
                  if np.isfinite(atr_i) and atr_i > 0 else float("nan"))
    return {
        "ceiling": float(highs[fallback_pos]),
        "pivot_date": prior.index[fallback_pos].date().isoformat(),
        "pivot_method": "previous_range_high_fallback",
        "pivot_prominence_atr": float(prominence),
        "pivot_count": 0,
        "pivot_age_bars": int(len(base) - 1 - fallback_pos),
    }


def _internal_rally_metrics(base: pd.DataFrame, lookback_bars: int,
                            rally_pct_threshold: float, rally_atr_threshold: float) -> dict[str, Any]:
    """Measure strong low-to-high moves inside a proposed base window.

    A tight base should follow the advance, not contain the whole advance. We
    examine each high against lows from the preceding `lookback_bars` trading
    bars. A candidate is rejected only when at least one ordered low-to-high
    move exceeds BOTH the percentage and ATR thresholds; this avoids rejecting
    ordinary wide but directionless consolidations just because their total
    height is large.
    """
    result: dict[str, Any] = {
        "base_internal_rally_pct": 0.0,
        "base_internal_rally_atr": 0.0,
        "base_internal_rally_start_date": "",
        "base_internal_rally_peak_date": "",
        "contains_internal_rally": False,
    }
    if base is None or len(base) < 4 or not {"High", "Low"}.issubset(base.columns):
        return result

    highs = pd.to_numeric(base["High"], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(base["Low"], errors="coerce").to_numpy(dtype=float)
    atrs = (pd.to_numeric(base["ATR"], errors="coerce").to_numpy(dtype=float)
            if "ATR" in base else np.full(len(base), np.nan))
    largest_pct = -1.0
    largest_atr = 0.0
    largest_start = -1
    largest_peak = -1
    qualifying: tuple[float, float, int, int] | None = None

    for peak_i in range(2, len(base)):
        left = max(0, peak_i - int(lookback_bars))
        # The low must occur before the high; exclude the high bar itself.
        prior_lows = lows[left:peak_i]
        valid = np.isfinite(prior_lows)
        if not valid.any() or not np.isfinite(highs[peak_i]):
            continue
        safe_lows = np.where(valid, prior_lows, np.inf)
        low_rel = int(np.argmin(safe_lows))
        low_i = left + low_rel
        low_px = float(lows[low_i])
        high_px = float(highs[peak_i])
        if not np.isfinite(low_px) or low_px <= 0 or high_px <= low_px:
            continue
        move_pct = 100.0 * (high_px / low_px - 1.0)
        atr = float(atrs[peak_i]) if peak_i < len(atrs) else float("nan")
        move_atr = (high_px - low_px) / atr if np.isfinite(atr) and atr > 0 else 0.0
        if move_pct > largest_pct:
            largest_pct, largest_atr, largest_start, largest_peak = move_pct, move_atr, low_i, peak_i
        if move_pct >= rally_pct_threshold and move_atr >= rally_atr_threshold:
            candidate = (move_pct, move_atr, low_i, peak_i)
            if qualifying is None or candidate[0] > qualifying[0]:
                qualifying = candidate

    if largest_pct >= 0:
        result.update({
            "base_internal_rally_pct": float(largest_pct),
            "base_internal_rally_atr": float(largest_atr),
            "base_internal_rally_start_date": base.index[largest_start].date().isoformat() if largest_start >= 0 else "",
            "base_internal_rally_peak_date": base.index[largest_peak].date().isoformat() if largest_peak >= 0 else "",
        })
    if qualifying is not None:
        pct, atr, low_i, peak_i = qualifying
        result.update({
            "contains_internal_rally": True,
            "base_internal_rally_pct": float(pct),
            "base_internal_rally_atr": float(atr),
            "base_internal_rally_start_date": base.index[low_i].date().isoformat(),
            "base_internal_rally_peak_date": base.index[peak_i].date().isoformat(),
        })
    return result


def _candidate_metrics(data: pd.DataFrame, base_len: int, end_exclusive: int,
                       config: ScanConfig) -> dict[str, Any] | None:
    """Score a base ending at end_exclusive-1 using its most recent valid pivot.

    `end_exclusive` and all other positions are integer positions in `data`.
    The newest bar in the base is excluded from pivot selection so its own high
    cannot raise the resistance level it is being tested against.
    """
    start = end_exclusive - base_len
    if start < 2 or end_exclusive > len(data) or base_len < config.base_min_bars:
        return None
    base = data.iloc[start:end_exclusive]
    if len(base) != base_len or base_len < 8:
        return None
    pre_ceiling = base.iloc[:-1]
    if pre_ceiling.empty:
        return None

    # Reject candidate windows that contain a sharp low-to-high advance. Such a
    # window is not a clean post-advance base and can otherwise win on an
    # inflated range/strength calculation (the issue seen in KZPC).
    internal_rally = _internal_rally_metrics(
        base,
        lookback_bars=config.base_internal_rally_lookback_bars,
        rally_pct_threshold=config.base_internal_rally_pct,
        rally_atr_threshold=config.base_internal_rally_atr,
    )
    if internal_rally["contains_internal_rally"]:
        return None

    pivot_info = _select_pivot_ceiling(base)
    ceiling = float(pivot_info["ceiling"])
    setup_close = float(base["Close"].iloc[-1])
    base_high = float(base["High"].max())
    base_low = float(base["Low"].min())
    height = max(0.0, base_high - base_low)
    atr_now = float(base["ATR"].iloc[-1]) if pd.notna(base["ATR"].iloc[-1]) else float("nan")
    atr_pct = 100.0 * _safe_ratio(atr_now, setup_close)
    if not np.isfinite(atr_pct) or atr_pct <= 0:
        atr_pct = 0.0

    # 1) STRENGTH: anchor the impulse at the highest high in the base's first
    # third. The internal-rally gate above ensures that this chosen window has
    # already entered the consolidation instead of including the full advance.
    strength_score = 0.0
    advance_pct = float("nan")
    pullback_pct = float("nan")
    advance_volume = float("nan")
    peak_age = -1
    peak_high = float("nan")
    early_len = max(4, min(base_len // 3, 12))
    early_base = base.iloc[:early_len]
    if not early_base.empty:
        peak_local = int(np.nanargmax(early_base["High"].to_numpy(dtype=float)))
        peak_pos = start + peak_local
        peak_high = float(data["High"].iloc[peak_pos])
        # Peak position within the first part of the base: zero means the base
        # begins right at the high zone, which is typical of a tight base.
        peak_age = peak_local
        low_start = max(0, peak_pos - config.impulse_low_search_bars)
        low_segment = data.iloc[low_start:peak_pos]
        if not low_segment.empty:
            low_local = int(np.nanargmin(low_segment["Low"].to_numpy(dtype=float)))
            impulse_low = float(low_segment["Low"].iloc[low_local])
            impulse_low_pos = low_start + low_local
            if impulse_low > 0 and peak_high > impulse_low:
                advance_pct = (peak_high / impulse_low - 1.0) * 100.0
                pullback_pct = max(0.0, (peak_high - base_low) / peak_high * 100.0)
                ratio = _safe_ratio(advance_pct, pullback_pct)
                ratio_score = clip01((ratio - 1.0) / 2.0) if np.isfinite(ratio) else 0.0
                magnitude_in_atr = _safe_ratio(advance_pct, atr_pct) if atr_pct > 0 else 0.0
                magnitude_score = clip01((magnitude_in_atr - 1.5) / 6.5)
                atr_at_peak = data["ATR"].iloc[peak_pos]
                if pd.isna(atr_at_peak) or float(atr_at_peak) <= 0:
                    atr_at_peak = atr_now
                peak_alignment = clip01(
                    1.0 - abs(peak_high - base_high) / max(3.0 * float(atr_at_peak or 0.0), 1e-9)
                )
                age_score = clip01(1.0 - max(0, peak_age - 2) / max(3.0, float(early_len)))
                strength_blend = (
                    0.40 * ratio_score
                    + 0.30 * magnitude_score
                    + 0.15 * peak_alignment
                    + 0.15 * age_score
                )
                impulse_size_gate = clip01(magnitude_in_atr / 4.0)
                strength_score = strength_blend * impulse_size_gate
                impulse = data.iloc[impulse_low_pos:peak_pos + 1]
                advance_volume = _mean_or_nan(impulse["Volume"])

    # 2) TREND: slope of the mid SMA, fast/mid alignment, and time spent above
    # the mid SMA during the base. Missing early MA values do not count as holds.
    mid = pd.to_numeric(base["SMA_mid"], errors="coerce")
    ema = pd.to_numeric(base["EMA_fast"], errors="coerce")
    close_values = base["Close"].astype(float)
    valid_mid = mid.notna()
    held_score = float((close_values[valid_mid] > mid[valid_mid]).mean()) if valid_mid.any() else 0.0
    last_mid = float(mid.iloc[-1]) if pd.notna(mid.iloc[-1]) else float("nan")
    ref_pos = max(0, len(base) - 1 - min(10, len(base) - 1))
    ref_mid = float(mid.iloc[ref_pos]) if pd.notna(mid.iloc[ref_pos]) else float("nan")
    mid_slope_pct = 100.0 * (last_mid / ref_mid - 1.0) if np.isfinite(last_mid) and np.isfinite(ref_mid) and ref_mid != 0 else 0.0
    slope_score = clip01(0.5 + mid_slope_pct / 4.0)
    last_ema = float(ema.iloc[-1]) if pd.notna(ema.iloc[-1]) else float("nan")
    if np.isfinite(last_ema) and np.isfinite(last_mid) and atr_now > 0:
        fast_alignment = clip01(0.5 + (last_ema - last_mid) / (4.0 * atr_now))
    else:
        fast_alignment = 0.5
    trend_score = 0.35 * slope_score + 0.30 * fast_alignment + 0.35 * held_score

    # 3) CONTRACTION: compare equal-sized older and newer thirds. Both candle
    # range and swing width matter; neither one alone determines the grade.
    third = max(3, base_len // 3)
    early = base.iloc[:third]
    late = base.iloc[-third:]
    early_ranges = (early["High"] - early["Low"]) / early["Close"].replace(0, np.nan) * 100.0
    late_ranges = (late["High"] - late["Low"]) / late["Close"].replace(0, np.nan) * 100.0
    early_range_avg = _mean_or_nan(early_ranges)
    late_range_avg = _mean_or_nan(late_ranges)
    range_shrink = clip01(1.0 - late_range_avg / early_range_avg) if np.isfinite(early_range_avg) and early_range_avg > 0 and np.isfinite(late_range_avg) else 0.0
    early_width = float(early["High"].max() - early["Low"].min())
    late_width = float(late["High"].max() - late["Low"].min())
    width_shrink = clip01(1.0 - late_width / early_width) if early_width > 0 else 0.0
    contraction_score = 0.55 * range_shrink + 0.45 * width_shrink

    # 4) VOLUME: up-day volume relative to down-day volume, fading sell volume,
    # and lower average base volume compared with the prior impulse.
    base_change = base["Close"].diff()
    up_mask = base_change > 0
    down_mask = base_change < 0
    avg_up_vol = _mean_or_nan(base.loc[up_mask, "Volume"])
    avg_down_vol = _mean_or_nan(base.loc[down_mask, "Volume"])
    if np.isfinite(avg_up_vol) and np.isfinite(avg_down_vol) and avg_up_vol > 0 and avg_down_vol > 0:
        balance_score = clip01(0.5 + 0.25 * np.log2(avg_up_vol / avg_down_vol))
    else:
        balance_score = 0.5
    early_change = early["Close"].diff()
    late_change = late["Close"].diff()
    early_down_vol = _mean_or_nan(early.loc[early_change < 0, "Volume"])
    late_down_vol = _mean_or_nan(late.loc[late_change < 0, "Volume"])
    if np.isfinite(late_down_vol) and late_down_vol == 0:
        fade_score = 1.0
    elif np.isfinite(early_down_vol) and early_down_vol > 0 and np.isfinite(late_down_vol):
        fade_score = clip01(1.0 - late_down_vol / early_down_vol)
    else:
        fade_score = 0.5
    base_volume = _mean_or_nan(base["Volume"])
    if np.isfinite(base_volume) and np.isfinite(advance_volume) and advance_volume > 0:
        quiet_score = clip01(1.0 - base_volume / advance_volume)
    else:
        quiet_score = 0.0
    volume_score = 0.30 * balance_score + 0.30 * fade_score + 0.40 * quiet_score

    # 5) CLOSENESS: measure the gap in units of this base's own height.
    gap = _safe_ratio(ceiling - setup_close, height)
    closeness_score = clip01(1.0 - 2.0 * gap) if np.isfinite(gap) else 0.0
    distance_pct = 100.0 * _safe_ratio(ceiling - setup_close, setup_close)

    # 6) RELATIVE STRENGTH: RSI of stock/EGX30 price ratio, not plain price RSI.
    rs_rsi = float(base["RS_RSI"].iloc[-1]) if "RS_RSI" in base and pd.notna(base["RS_RSI"].iloc[-1]) else float("nan")
    rs_available = bool(np.isfinite(rs_rsi))
    rs_score = clip01((rs_rsi - 35.0) / 30.0) if rs_available else float("nan")

    # Do not silently award a neutral 50/100 for missing benchmark data. If the
    # RS series is unavailable, leave its grade blank and renormalize the score
    # over the five available price/volume ingredients.
    weighted_score = (
        WEIGHTS["strength"] * strength_score
        + WEIGHTS["trend"] * trend_score
        + WEIGHTS["contraction"] * contraction_score
        + WEIGHTS["volume"] * volume_score
        + WEIGHTS["closeness"] * closeness_score
    )
    effective_weight = sum(WEIGHTS[key] for key in ("strength", "trend", "contraction", "volume", "closeness"))
    if rs_available:
        weighted_score += WEIGHTS["relative_strength"] * rs_score
        effective_weight += WEIGHTS["relative_strength"]
    score = 100.0 * weighted_score / effective_weight

    return {
        "pattern_score": float(np.clip(score, 0.0, 100.0)),
        "base_len": int(base_len),
        "base_start_date": base.index[0].date().isoformat(),
        "ceiling": ceiling,
        "pivot_date": pivot_info["pivot_date"],
        "pivot_method": pivot_info["pivot_method"],
        "pivot_prominence_atr": pivot_info["pivot_prominence_atr"],
        "pivot_count": pivot_info["pivot_count"],
        "pivot_age_bars": pivot_info["pivot_age_bars"],
        "base_low": base_low,
        "base_high": base_high,
        "base_highest_high": base_high,
        "base_peak_date": early_base.index[int(np.nanargmax(early_base["High"].to_numpy(dtype=float)))].date().isoformat() if not early_base.empty else "",
        "base_internal_rally_pct": float(internal_rally["base_internal_rally_pct"]),
        "base_internal_rally_atr": float(internal_rally["base_internal_rally_atr"]),
        "base_internal_rally_start_date": internal_rally["base_internal_rally_start_date"],
        "base_internal_rally_peak_date": internal_rally["base_internal_rally_peak_date"],
        "base_height_pct": 100.0 * _safe_ratio(height, setup_close),
        "setup_close": setup_close,
        "distance_to_ceiling_pct": distance_pct,
        "relative_volume": float(base["RV"].iloc[-1]) if pd.notna(base["RV"].iloc[-1]) else float("nan"),
        "rs_rsi": rs_rsi,
        "rs_data_available": rs_available,
        "excess_return_20d_pct": float(base["Excess_Return_20D_pct"].iloc[-1]) if "Excess_Return_20D_pct" in base and pd.notna(base["Excess_Return_20D_pct"].iloc[-1]) else float("nan"),
        "excess_return_60d_pct": float(base["Excess_Return_60D_pct"].iloc[-1]) if "Excess_Return_60D_pct" in base and pd.notna(base["Excess_Return_60D_pct"].iloc[-1]) else float("nan"),
        "strength_grade": strength_score * 100.0,
        "trend_grade": trend_score * 100.0,
        "contraction_grade": contraction_score * 100.0,
        "volume_grade": volume_score * 100.0,
        "closeness_grade": closeness_score * 100.0,
        "relative_strength_grade": rs_score * 100.0,
        "advance_pct": advance_pct,
        "pullback_pct": pullback_pct,
        "peak_age_bars": peak_age,
        "atr_pct": atr_pct,
    }


def _as_result(symbol: str, data: pd.DataFrame, metrics: dict[str, Any] | None,
               status: str, reason: str = "", **extra: Any) -> dict[str, Any]:
    latest = data.iloc[-1] if not data.empty else pd.Series(dtype=float)
    result: dict[str, Any] = {
        "symbol": symbol,
        "date": data.index[-1].date().isoformat() if not data.empty else "",
        "status": status,
        "pattern_score": metrics.get("pattern_score", 0.0) if metrics else 0.0,
        "close": float(latest["Close"]) if "Close" in latest and pd.notna(latest["Close"]) else float("nan"),
        "relative_volume": float(latest["RV"]) if "RV" in latest and pd.notna(latest["RV"]) else float("nan"),
        "rs_rsi": float(latest["RS_RSI"]) if "RS_RSI" in latest and pd.notna(latest["RS_RSI"]) else float("nan"),
        "excess_return_20d_pct": float(latest["Excess_Return_20D_pct"]) if "Excess_Return_20D_pct" in latest and pd.notna(latest["Excess_Return_20D_pct"]) else float("nan"),
        "excess_return_60d_pct": float(latest["Excess_Return_60D_pct"]) if "Excess_Return_60D_pct" in latest and pd.notna(latest["Excess_Return_60D_pct"]) else float("nan"),
        "ceiling": metrics.get("ceiling", float("nan")) if metrics else float("nan"),
        "pivot_date": metrics.get("pivot_date", "") if metrics else "",
        "pivot_method": metrics.get("pivot_method", "") if metrics else "",
        "pivot_prominence_atr": metrics.get("pivot_prominence_atr", float("nan")) if metrics else float("nan"),
        "pivot_count": metrics.get("pivot_count", 0) if metrics else 0,
        "pivot_age_bars": metrics.get("pivot_age_bars", -1) if metrics else -1,
        "base_highest_high": metrics.get("base_highest_high", float("nan")) if metrics else float("nan"),
        "base_peak_date": metrics.get("base_peak_date", "") if metrics else "",
        "base_internal_rally_pct": metrics.get("base_internal_rally_pct", float("nan")) if metrics else float("nan"),
        "base_internal_rally_atr": metrics.get("base_internal_rally_atr", float("nan")) if metrics else float("nan"),
        "base_internal_rally_start_date": metrics.get("base_internal_rally_start_date", "") if metrics else "",
        "base_internal_rally_peak_date": metrics.get("base_internal_rally_peak_date", "") if metrics else "",
        "distance_to_ceiling_pct": metrics.get("distance_to_ceiling_pct", float("nan")) if metrics else float("nan"),
        "base_len": metrics.get("base_len", 0) if metrics else 0,
        "base_start_date": metrics.get("base_start_date", "") if metrics else "",
        "strength_grade": metrics.get("strength_grade", float("nan")) if metrics else float("nan"),
        "trend_grade": metrics.get("trend_grade", float("nan")) if metrics else float("nan"),
        "contraction_grade": metrics.get("contraction_grade", float("nan")) if metrics else float("nan"),
        "volume_grade": metrics.get("volume_grade", float("nan")) if metrics else float("nan"),
        "closeness_grade": metrics.get("closeness_grade", float("nan")) if metrics else float("nan"),
        "relative_strength_grade": metrics.get("relative_strength_grade", float("nan")) if metrics else float("nan"),
        "rs_data_available": metrics.get("rs_data_available", False) if metrics else False,
        "advance_pct": metrics.get("advance_pct", float("nan")) if metrics else float("nan"),
        "pullback_pct": metrics.get("pullback_pct", float("nan")) if metrics else float("nan"),
        "data_reason": reason,
    }
    result.update(extra)
    return result


def scan_symbol(symbol: str, prices: pd.DataFrame, benchmark_close: pd.Series,
                config: ScanConfig | None = None) -> dict[str, Any]:
    """Score the latest daily bar for one symbol and assign its current status."""
    config = config or ScanConfig()
    config.validate()
    required = {"Open", "High", "Low", "Close", "Volume"}
    if prices is None or prices.empty or not required.issubset(set(prices.columns)):
        return {"symbol": symbol, "status": "NO_PRICE_DATA", "pattern_score": 0.0,
                "data_reason": "No usable OHLCV data from the configured source."}

    data = prices.copy()
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data.loc[~data.index.isna()].sort_index()
    data = data[~data.index.duplicated(keep="last")]
    for col in required:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["High", "Low", "Close"])
    data = data[(data["Close"] > 0) & (data["High"] >= data["Low"])]
    data["Volume"] = data["Volume"].fillna(0.0).clip(lower=0.0)
    if data.empty:
        return {"symbol": symbol, "status": "NO_PRICE_DATA", "pattern_score": 0.0,
                "data_reason": "Price rows were present but failed OHLC validation."}

    min_bars = max(config.mid_sma_bars + 10, config.base_max_bars + config.impulse_search_bars + 10)
    if len(data) < min_bars:
        return _as_result(symbol, data, None, "INSUFFICIENT_DATA",
                          f"Need about {min_bars} daily bars; received {len(data)}.")

    data = add_price_indicators(data, config.fast_ema_bars, config.mid_sma_bars,
                                config.atr_bars, config.relative_volume_bars)
    benchmark = pd.to_numeric(benchmark_close, errors="coerce")
    benchmark.index = pd.to_datetime(benchmark.index, errors="coerce")
    benchmark = benchmark.loc[~benchmark.index.isna()].sort_index()
    benchmark = benchmark[~benchmark.index.duplicated(keep="last")]
    data = add_relative_strength(data, benchmark, config.rs_rsi_bars)

    latest_pos = len(data) - 1
    best_latest: dict[str, Any] | None = None
    best_forming: dict[str, Any] | None = None
    for length in range(config.base_min_bars, config.base_max_bars + 1):
        metrics = _candidate_metrics(data, length, len(data), config)
        if metrics is None:
            continue
        if best_latest is None or metrics["pattern_score"] > best_latest["pattern_score"]:
            best_latest = metrics
        if metrics["setup_close"] <= metrics["ceiling"] and metrics["pattern_score"] >= config.min_score and metrics["closeness_grade"] >= 10:
            if best_forming is None or metrics["pattern_score"] > best_forming["pattern_score"]:
                best_forming = metrics

    # Check recent breakout events first, so a current/active breakout is not
    # hidden by a separate base-length candidate that still looks FORMING.
    max_age = min(config.breakout_hold_bars - 1, len(data) - 2)
    for age in range(max_age + 1):
        trigger_pos = latest_pos - age
        event_candidates: list[dict[str, Any]] = []
        for length in range(config.base_min_bars, config.base_max_bars + 1):
            setup = _candidate_metrics(data, length, trigger_pos, config)
            if setup is None or setup["pattern_score"] < config.min_score:
                continue
            pivot = float(setup["ceiling"])
            setup_close = float(setup["setup_close"])
            bar = data.iloc[trigger_pos]
            previous_close = float(data["Close"].iloc[trigger_pos - 1])
            atr_break = float(bar["ATR"]) if pd.notna(bar["ATR"]) else 0.0
            rv_break = float(bar["RV"]) if pd.notna(bar["RV"]) else 0.0
            candle_range = float(bar["High"] - bar["Low"])
            close_position = (float(bar["Close"]) - float(bar["Low"])) / candle_range if candle_range > 0 else 0.0
            buffer = max(0.0, config.breakout_buffer_atr * atr_break)
            valid_trigger = (
                setup_close <= pivot
                and previous_close <= pivot
                and float(bar["Close"]) > pivot + buffer
                and rv_break >= config.breakout_relative_volume
                and close_position >= config.breakout_close_position
            )
            if valid_trigger:
                setup["_trigger_pivot"] = pivot
                setup["_trigger_age"] = age
                setup["_trigger_date"] = data.index[trigger_pos].date().isoformat()
                event_candidates.append(setup)
        if event_candidates:
            selected = max(event_candidates, key=lambda row: row["pattern_score"])
            pivot = float(selected["_trigger_pivot"])
            post_break_closes = data["Close"].iloc[trigger_pos + 1:]
            fell_below = bool((post_break_closes < pivot).any())
            status = "FAILED" if fell_below else "BREAKOUT"
            result = _as_result(
                symbol, data, selected, status,
                reason="Recent high-volume close through a base ceiling; monitored for the configured hold window.",
                pivot=pivot,
                breakout_date=selected["_trigger_date"],
                breakout_age_bars=selected["_trigger_age"],
                breakout_relative_volume=float(data["RV"].iloc[trigger_pos]) if pd.notna(data["RV"].iloc[trigger_pos]) else float("nan"),
            )
            # For a breakout/failure row, distance should refer to the current
            # close and the saved pivot, not the older close used to grade setup.
            latest_close = float(data["Close"].iloc[-1])
            result["ceiling"] = pivot
            result["distance_to_ceiling_pct"] = 100.0 * (pivot - latest_close) / latest_close if latest_close else float("nan")
            return result

    if best_forming is not None:
        return _as_result(symbol, data, best_forming, "FORMING",
                          reason="Score passes the threshold and the latest close remains at/below the candidate ceiling.")
    return _as_result(symbol, data, best_latest, "NONE",
                      reason="No candidate passed the forming or recent-breakout conditions.")

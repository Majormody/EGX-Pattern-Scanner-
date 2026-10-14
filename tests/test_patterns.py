import unittest
import numpy as np
import pandas as pd

from egx_scanner.indicators import rsi, add_relative_strength
from egx_scanner.patterns import scan_symbol, _select_pivot_ceiling, _internal_rally_metrics
from egx_scanner.settings import ScanConfig


def synthetic_prices(seed: int = 7) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    n = 260
    dates = pd.bdate_range("2025-01-01", periods=n)
    # Stock: advance, then a narrower consolidation near the prior high.
    trend = np.linspace(18.0, 35.0, 190)
    advance = trend + rng.normal(0, 0.22, 190)
    base_n = n - 190
    base_x = np.arange(base_n)
    base = 34.6 + 0.18 * np.sin(base_x / 2.7) + rng.normal(0, 0.045, base_n)
    close = np.concatenate([advance, base])
    spread = np.concatenate([
        rng.uniform(0.35, 0.85, 190),
        np.linspace(0.42, 0.16, base_n),
    ])
    high = close + spread / 2
    low = close - spread / 2
    open_ = close + rng.normal(0, 0.12, n)
    volume = np.concatenate([
        rng.integers(120_000, 250_000, 190),
        np.linspace(100_000, 55_000, base_n) * rng.uniform(0.8, 1.2, base_n),
    ]).astype(float)
    stock = pd.DataFrame({"Open": open_, "High": high, "Low": low,
                          "Close": close, "Volume": volume}, index=dates)
    bench_close = pd.Series(10_000 * np.exp(np.cumsum(rng.normal(0.0005, 0.006, n))), index=dates)
    return stock, bench_close


class IndicatorTests(unittest.TestCase):
    def test_rsi_limits_and_flat_series(self):
        rising = pd.Series(np.arange(1, 50, dtype=float))
        falling = pd.Series(np.arange(50, 1, -1, dtype=float))
        flat = pd.Series(np.ones(50, dtype=float))
        self.assertGreater(float(rsi(rising, 14).iloc[-1]), 99.0)
        self.assertLess(float(rsi(falling, 14).iloc[-1]), 1.0)
        self.assertEqual(float(rsi(flat, 14).iloc[-1]), 50.0)

    def test_relative_strength_outputs_ratio_rsi_and_excess_returns(self):
        stock, benchmark = synthetic_prices()
        added = add_relative_strength(stock, benchmark, 14)
        self.assertIn("RS_RSI", added.columns)
        self.assertIn("Excess_Return_20D_pct", added.columns)
        # Make stock outperform benchmark, so RS ratio trends upward.
        outperform = stock.copy()
        outperform["Close"] = np.linspace(10, 100, len(outperform))
        added = add_relative_strength(outperform, benchmark, 14)
        self.assertGreater(float(added["RS_RSI"].iloc[-1]), 50.0)

    def test_relative_strength_aligns_by_calendar_day_not_timestamp(self):
        dates = pd.bdate_range("2026-01-01", periods=100)
        stock = pd.DataFrame({"Close": np.linspace(10, 20, len(dates))}, index=dates)
        benchmark_index = dates + pd.Timedelta(hours=15, minutes=30)
        benchmark = pd.Series(np.linspace(1000, 1200, len(dates)), index=benchmark_index)
        added = add_relative_strength(stock, benchmark, 14)
        self.assertTrue(pd.notna(added["RS_RSI"].iloc[-1]))
        self.assertTrue(pd.notna(added["Excess_Return_20D_pct"].iloc[-1]))
        self.assertTrue(pd.notna(added["Excess_Return_60D_pct"].iloc[-1]))


class PivotTests(unittest.TestCase):
    def test_selects_most_recent_significant_swing_high_not_absolute_high(self):
        dates = pd.bdate_range("2026-08-01", periods=24)
        highs = np.full(24, 12.0)
        lows = np.full(24, 11.5)
        # Earlier, higher swing. Later, lower but still meaningful pivot.
        highs[5] = 16.0
        lows[4:8] = [13.0, 12.0, 12.7, 13.2]
        highs[12] = 14.0
        lows[11:15] = [12.4, 11.8, 12.1, 12.5]
        frame = pd.DataFrame({"High": highs, "Low": lows, "ATR": np.ones(24)}, index=dates)
        selected = _select_pivot_ceiling(frame)
        self.assertEqual(selected["pivot_method"], "last_confirmed_swing_high")
        self.assertEqual(selected["ceiling"], 14.0)
        self.assertEqual(selected["pivot_date"], dates[12].date().isoformat())
        self.assertGreaterEqual(selected["pivot_count"], 2)


    def test_internal_rally_gate_detects_advance_inside_candidate_base(self):
        dates = pd.bdate_range("2026-08-01", periods=30)
        close = np.full(30, 12.8, dtype=float)
        close[3:8] = np.linspace(13.0, 16.2, 5)
        close[8:] = 15.2 + 0.15 * np.sin(np.arange(22) / 2.0)
        frame = pd.DataFrame({
            "Open": close, "High": close + 0.2, "Low": close - 0.2,
            "Close": close, "Volume": np.full(30, 100_000.0),
            "ATR": np.full(30, 0.6),
        }, index=dates)
        result = _internal_rally_metrics(frame, 12, 18.0, 3.0)
        self.assertTrue(result["contains_internal_rally"])
        self.assertGreaterEqual(result["base_internal_rally_pct"], 18.0)
        self.assertGreaterEqual(result["base_internal_rally_atr"], 3.0)


    def test_default_rally_gate_catches_near_threshold_17_7_percent_move(self):
        # KZPC's latest diagnostic showed a 17.698% move over 3.29 ATR.
        # The old 18% threshold let this candidate window slip through even
        # though the move was larger than 3 ATR.
        dates = pd.bdate_range("2026-08-01", periods=20)
        close = np.full(20, 10.1, dtype=float)
        high = np.full(20, 10.2, dtype=float)
        low = np.full(20, 10.0, dtype=float)
        high[10] = 11.77
        low[10] = 11.50
        close[10] = 11.65
        frame = pd.DataFrame({
            "Open": close, "High": high, "Low": low, "Close": close,
            "Volume": np.full(20, 100_000.0),
            "ATR": np.full(20, 1.77 / 3.29),
        }, index=dates)
        config = ScanConfig()
        self.assertEqual(config.base_internal_rally_pct, 15.0)
        result = _internal_rally_metrics(
            frame, config.base_internal_rally_lookback_bars,
            config.base_internal_rally_pct, config.base_internal_rally_atr,
        )
        self.assertTrue(result["contains_internal_rally"])
        self.assertGreaterEqual(result["base_internal_rally_pct"], 15.0)
        self.assertGreaterEqual(result["base_internal_rally_atr"], 3.0)

    def test_internal_rally_gate_keeps_orderly_tight_consolidation(self):
        dates = pd.bdate_range("2026-08-01", periods=30)
        close = 15.0 + 0.12 * np.sin(np.arange(30) / 2.0)
        frame = pd.DataFrame({
            "Open": close, "High": close + 0.15, "Low": close - 0.15,
            "Close": close, "Volume": np.full(30, 100_000.0),
            "ATR": np.full(30, 0.5),
        }, index=dates)
        result = _internal_rally_metrics(frame, 12, 18.0, 3.0)
        self.assertFalse(result["contains_internal_rally"])


class ScannerTests(unittest.TestCase):
    def test_scan_returns_valid_status_and_bounded_score(self):
        stock, benchmark = synthetic_prices()
        result = scan_symbol("TEST", stock, benchmark, ScanConfig())
        self.assertIn(result["status"], {"FORMING", "BREAKOUT", "FAILED", "NONE", "INSUFFICIENT_DATA", "NO_PRICE_DATA"})
        self.assertGreaterEqual(float(result.get("pattern_score", 0.0)), 0.0)
        self.assertLessEqual(float(result.get("pattern_score", 0.0)), 100.0)
        self.assertIn("rs_rsi", result)
        self.assertIn("contraction_grade", result)

    def test_missing_benchmark_does_not_receive_fake_neutral_rs_grade(self):
        stock, _ = synthetic_prices()
        result = scan_symbol("TEST", stock, pd.Series(dtype=float), ScanConfig())
        self.assertFalse(result["rs_data_available"])
        self.assertTrue(np.isnan(result["relative_strength_grade"]))
        self.assertTrue(np.isnan(result["rs_rsi"]))
        self.assertGreaterEqual(float(result["pattern_score"]), 0.0)
        self.assertLessEqual(float(result["pattern_score"]), 100.0)

    def test_invalid_prices_are_reported_not_crashed(self):
        empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        result = scan_symbol("EMPTY", empty, pd.Series(dtype=float), ScanConfig())
        self.assertEqual(result["status"], "NO_PRICE_DATA")


if __name__ == "__main__":
    unittest.main()

import sys
import types
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from egx_scanner.sources import (
    _download_benchmark_history,
    _extract_ticker_frame,
    _normalise_price_frame,
    _normalise_tradingview_benchmark,
)


class SourceNormalizationTests(unittest.TestCase):
    def _frame(self):
        dates = pd.date_range("2025-01-01", periods=3, freq="B")
        return pd.DataFrame({
            "Open": [10.0, 10.5, 10.2],
            "High": [11.0, 11.0, 10.8],
            "Low": [9.5, 10.1, 10.0],
            "Close": [10.5, 10.2, 10.7],
            "Volume": [1000, 1200, 1500],
        }, index=dates)

    def test_normalizes_regular_ohlcv(self):
        frame = self._frame()
        normal = _normalise_price_frame(frame)
        self.assertEqual(list(normal.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(normal), 3)

    def test_extracts_yahoo_multiindex_ticker_first(self):
        frame = self._frame()
        multi = pd.concat({"ABC.CA": frame, "XYZ.CA": frame * 2}, axis=1)
        result = _extract_ticker_frame(multi, "ABC.CA")
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(float(result["Close"].iloc[0]), 10.5)

    def test_extracts_yahoo_multiindex_field_first(self):
        frame = self._frame()
        multi = pd.concat({col: pd.concat({"ABC.CA": frame[col], "XYZ.CA": frame[col] * 2}, axis=1)
                           for col in frame.columns}, axis=1)
        result = _extract_ticker_frame(multi, "ABC.CA")
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(float(result["Close"].iloc[0]), 10.5)


class TradingViewBenchmarkTests(unittest.TestCase):
    def test_normalizes_lowercase_columns_and_strips_time_of_day(self):
        dates = pd.date_range("2025-01-01 10:00", periods=3, freq="B")
        raw = pd.DataFrame({
            "symbol": ["EGX:EGX30"] * 3,
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [1000, 1100, 1200],
        }, index=dates)

        result = _normalise_tradingview_benchmark(raw)

        self.assertEqual(len(result), 3)
        self.assertEqual(list(result.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertTrue(all(ts.hour == 0 for ts in result.index))
        self.assertAlmostEqual(float(result["Close"].iloc[-1]), 103.0)

    def test_download_uses_tradingview_history(self):
        dates = pd.date_range("2024-01-01 10:00", periods=120, freq="B")
        bars = pd.DataFrame({
            "symbol": ["EGX:EGX30"] * len(dates),
            "open": np.linspace(1000, 1100, len(dates)),
            "high": np.linspace(1010, 1110, len(dates)),
            "low": np.linspace(990, 1090, len(dates)),
            "close": np.linspace(1005, 1105, len(dates)),
            "volume": np.full(len(dates), 10000),
        }, index=dates)

        fake_tv_module = types.ModuleType("tvDatafeed")
        fake_tv_module.Interval = types.SimpleNamespace(in_daily="daily")
        fake_tv_module.TvDatafeed = lambda: types.SimpleNamespace(
            get_hist=lambda **kwargs: bars
        )

        with patch.dict(sys.modules, {"tvDatafeed": fake_tv_module}):
            result, attempts = _download_benchmark_history()

        self.assertEqual(len(result), 120)
        self.assertIn("SUCCESS TradingView EGX:EGX30", attempts[-1])



if __name__ == "__main__":
    unittest.main()

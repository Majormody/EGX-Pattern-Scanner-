from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
PRICE_CACHE_DIR = CACHE_DIR / "prices"
OUTPUT_DIR = ROOT / "outputs"
UNIVERSE_FILE = DATA_DIR / "universe.csv"
MANUAL_SYMBOLS_FILE = DATA_DIR / "manual_symbols.csv"
BENCHMARK_CACHE = CACHE_DIR / "egx30_benchmark.csv"

BENCHMARK_TICKER = "^CASE30"  # Yahoo Finance: EGX 30 Price Return Index


@dataclass(frozen=True)
class ScanConfig:
    # Pattern windows are in trading bars, not calendar days.
    base_min_bars: int = 12
    base_max_bars: int = 45
    impulse_search_bars: int = 25
    impulse_low_search_bars: int = 80
    # Reject candidate windows that still contain a strong advance instead of a base.
    base_internal_rally_lookback_bars: int = 12
    base_internal_rally_pct: float = 15.0
    base_internal_rally_atr: float = 3.0
    fast_ema_bars: int = 20
    mid_sma_bars: int = 50
    atr_bars: int = 14
    relative_volume_bars: int = 20
    rs_rsi_bars: int = 14
    min_score: float = 62.0
    breakout_relative_volume: float = 1.30
    breakout_close_position: float = 0.55
    breakout_buffer_atr: float = 0.10
    breakout_hold_bars: int = 5

    def validate(self) -> None:
        if self.base_min_bars < 8:
            raise ValueError("base_min_bars must be >= 8")
        if self.base_max_bars < self.base_min_bars:
            raise ValueError("base_max_bars must be >= base_min_bars")
        if not 0 <= self.min_score <= 100:
            raise ValueError("min_score must be between 0 and 100")
        if self.breakout_relative_volume <= 0:
            raise ValueError("breakout_relative_volume must be > 0")
        if self.base_internal_rally_lookback_bars < 3:
            raise ValueError("base_internal_rally_lookback_bars must be >= 3")
        if self.base_internal_rally_pct <= 0 or self.base_internal_rally_atr <= 0:
            raise ValueError("internal-rally thresholds must be > 0")

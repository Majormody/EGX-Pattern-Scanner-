"""Orchestrates universe, cached prices, scoring, and CSV reports."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any
import pandas as pd

from .patterns import scan_symbol
from .settings import OUTPUT_DIR
from .sources import (
    discover_universe,
    load_benchmark_close,
    load_price_cache,
    load_universe,
    refresh_price_cache,
)
from .settings import ScanConfig

STATUS_ORDER = {"BREAKOUT": 0, "FAILED": 1, "FORMING": 2, "NONE": 3,
                "INSUFFICIENT_DATA": 4, "NO_PRICE_DATA": 5}


def run_scan(config: ScanConfig | None = None, refresh_prices: bool = True,
             refresh_universe: bool = False, period: str = "2y",
             batch_size: int = 20, pause_seconds: float = 1.0) -> tuple[pd.DataFrame, dict[str, Any]]:
    config = config or ScanConfig()
    config.validate()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    universe_message = "Using the saved universe."
    if refresh_universe:
        universe, universe_message = discover_universe(save=True)
    else:
        universe = load_universe()

    coverage = pd.DataFrame()
    if refresh_prices:
        coverage = refresh_price_cache(universe, period=period, batch_size=batch_size,
                                       pause_seconds=pause_seconds)
    benchmark = load_benchmark_close()
    audit_lookup = {}
    if not coverage.empty:
        audit_lookup = {str(row["symbol"]): row.to_dict() for _, row in coverage.iterrows()}
    elif (coverage_path := Path(__file__).resolve().parents[1] / "data" / "cache" / "price_coverage_audit.csv").exists():
        try:
            prior = pd.read_csv(coverage_path).fillna("")
            audit_lookup = {str(row["symbol"]): row.to_dict() for _, row in prior.iterrows()}
        except Exception:
            audit_lookup = {}

    output_rows: list[dict[str, Any]] = []
    for _, ticker in universe.iterrows():
        symbol = str(ticker.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        prices = load_price_cache(symbol)
        result = scan_symbol(symbol, prices, benchmark, config)
        result["name"] = str(ticker.get("name", symbol))
        result["yahoo_symbol"] = str(ticker.get("yahoo_symbol", f"{symbol}.CA"))
        result["universe_source"] = str(ticker.get("source", "cache"))
        result["history_bars"] = len(prices)
        result["price_last_date"] = prices.index.max().date().isoformat() if not prices.empty else ""
        audit = audit_lookup.get(symbol, {})
        result["price_fetch_status"] = audit.get("fetch_status", "CACHE")
        result["price_fetch_details"] = audit.get("details", "")
        output_rows.append(result)

    results = pd.DataFrame(output_rows)
    if results.empty:
        raise RuntimeError("The current symbol universe is empty; nothing was scanned.")
    results["_status_order"] = results["status"].map(STATUS_ORDER).fillna(99)
    results = results.sort_values(["_status_order", "pattern_score"], ascending=[True, False]).drop(columns="_status_order")
    results = results.reset_index(drop=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dated_file = OUTPUT_DIR / f"egx_tight_base_scan_{timestamp}.csv"
    latest_file = OUTPUT_DIR / "latest_scan.csv"
    results.to_csv(dated_file, index=False)
    results.to_csv(latest_file, index=False)

    status_counts = results["status"].value_counts().to_dict()
    info = {
        "universe_count": int(len(universe)),
        "symbols_with_price_data": int((results["history_bars"].fillna(0) > 0).sum()),
        "symbols_with_enough_history": int((~results["status"].isin(["INSUFFICIENT_DATA", "NO_PRICE_DATA"])).sum()),
        "symbols_with_rs_data": int(results.get("rs_data_available", pd.Series(False, index=results.index)).fillna(False).astype(bool).sum()),
        "status_counts": status_counts,
        "universe_message": universe_message,
        "benchmark_last_date": pd.Timestamp(benchmark.index.max()).date().isoformat(),
        "output_file": str(dated_file),
        "latest_file": str(latest_file),
    }
    return results, info

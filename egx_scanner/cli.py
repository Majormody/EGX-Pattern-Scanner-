"""Command-line interface for the EGX Tight-Base Breakout Scanner."""
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

from .scanner import run_scan
from .settings import ScanConfig, OUTPUT_DIR
from .sources import discover_universe, load_universe, refresh_price_cache


def _print_coverage(audit: pd.DataFrame) -> None:
    if audit.empty:
        print("No coverage rows were returned.")
        return
    counts = audit["fetch_status"].value_counts().to_dict()
    print(f"Symbols updated/cached: {len(audit)} | Statuses: {counts}")
    print("Coverage audit:", Path(__file__).resolve().parents[1] / "data" / "cache" / "price_coverage_audit.csv")
    failures = audit[audit["fetch_status"].isin(["NO_DATA"])]
    if not failures.empty:
        print("No Yahoo daily history for these aliases (edit data/manual_symbols.csv if needed):")
        print(", ".join(failures["symbol"].astype(str).tolist()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Free daily EGX tight-base breakout scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("universe", help="Refresh the EGX ticker universe from TradingView and merge manual aliases")

    prices = sub.add_parser("prices", help="Refresh Yahoo daily OHLCV cache and report symbol coverage")
    prices.add_argument("--period", default="2y", help="History for first download, e.g. 1y, 2y, 5y, max")
    prices.add_argument("--batch-size", type=int, default=20)
    prices.add_argument("--pause", type=float, default=1.0, help="Pause between download batches, seconds")

    scan = sub.add_parser("scan", help="Scan cached prices, optionally refreshing them first")
    scan.add_argument("--no-refresh", action="store_true", help="Use existing price cache only")
    scan.add_argument("--refresh-universe", action="store_true", help="Refresh symbol universe before scanning")
    scan.add_argument("--period", default="2y")
    scan.add_argument("--min-score", type=float, default=62.0)
    scan.add_argument("--base-min", type=int, default=12)
    scan.add_argument("--base-max", type=int, default=45)
    scan.add_argument("--break-rv", type=float, default=1.30)
    scan.add_argument("--hold-bars", type=int, default=5)
    scan.add_argument("--batch-size", type=int, default=20)
    scan.add_argument("--pause", type=float, default=1.0)

    run = sub.add_parser("run", help="Refresh universe, update prices, scan all available symbols")
    run.add_argument("--period", default="2y")
    run.add_argument("--min-score", type=float, default=62.0)
    run.add_argument("--base-min", type=int, default=12)
    run.add_argument("--base-max", type=int, default=45)
    run.add_argument("--break-rv", type=float, default=1.30)
    run.add_argument("--hold-bars", type=int, default=5)
    run.add_argument("--batch-size", type=int, default=20)
    run.add_argument("--pause", type=float, default=1.0)

    sub.add_parser("coverage", help="Print last saved price-source coverage audit")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "universe":
        universe, message = discover_universe(save=True)
        print(message)
        print(f"Saved {len(universe)} symbols to data/universe.csv")
        print(universe.head(15).to_string(index=False))
        return
    if args.command == "prices":
        universe = load_universe()
        audit = refresh_price_cache(universe, period=args.period, batch_size=args.batch_size,
                                    pause_seconds=args.pause)
        _print_coverage(audit)
        return
    if args.command == "coverage":
        audit_file = Path(__file__).resolve().parents[1] / "data" / "cache" / "price_coverage_audit.csv"
        if audit_file.exists():
            audit = pd.read_csv(audit_file).fillna("")
            _print_coverage(audit)
            print(audit.to_string(index=False))
        else:
            print("No coverage audit exists yet. Run: python -m egx_scanner.cli prices")
        return

    config = ScanConfig(
        min_score=args.min_score,
        base_min_bars=args.base_min,
        base_max_bars=args.base_max,
        breakout_relative_volume=args.break_rv,
        breakout_hold_bars=args.hold_bars,
    )
    results, info = run_scan(
        config=config,
        refresh_prices=(args.command == "run" or not args.no_refresh),
        refresh_universe=(args.command == "run" or getattr(args, "refresh_universe", False)),
        period=args.period,
        batch_size=args.batch_size,
        pause_seconds=args.pause,
    )
    print(info["universe_message"])
    print(f"Universe: {info['universe_count']} | Has price data: {info['symbols_with_price_data']} | "
          f"Status counts: {info['status_counts']}")
    print(f"EGX30 benchmark last date: {info['benchmark_last_date']} | Symbols with RS data: {info['symbols_with_rs_data']}/{info['universe_count']}")
    print(f"Full output: {info['output_file']}")
    print("\nHighest-ranked rows:")
    display = [col for col in ["symbol", "status", "pattern_score", "close", "ceiling", "pivot_date",
                               "pivot_method", "distance_to_ceiling_pct", "relative_volume", "rs_rsi",
                               "rs_data_available", "excess_return_20d_pct", "base_len", "history_bars"] if col in results]
    print(results[display].head(25).to_string(index=False))


if __name__ == "__main__":
    main()

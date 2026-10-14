"""Free-market-data adapters: TradingView symbol discovery and Yahoo daily OHLCV.

These providers are unofficial/public interfaces and can change or rate-limit clients.
The program keeps local CSV caches and reports missing symbols instead of silently
pretending that unavailable securities were scanned.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any
import pandas as pd

from .settings import (
    BENCHMARK_CACHE,
    BENCHMARK_TICKER,
    CACHE_DIR,
    MANUAL_SYMBOLS_FILE,
    PRICE_CACHE_DIR,
    UNIVERSE_FILE,
)

OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _ensure_dirs() -> None:
    PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _clean_symbol(symbol: Any) -> str:
    value = str(symbol or "").strip().upper()
    if ":" in value:
        value = value.rsplit(":", 1)[-1]
    return value


def _normalise_universe_rows(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(columns=["symbol", "name", "yahoo_symbol", "source"])
    records: list[dict[str, str]] = []
    for _, row in frame.iterrows():
        tv_ticker = str(row.get("ticker", "")).strip()
        if not tv_ticker:
            continue
        if ":" in tv_ticker and tv_ticker.split(":", 1)[0].upper() not in {"EGX"}:
            continue
        symbol = _clean_symbol(tv_ticker)
        if not symbol or symbol in {"NAN", "NONE"}:
            continue
        # Users may override this convention in manual_symbols.csv when Yahoo
        # uses a different alias or doesn't cover the listed symbol.
        records.append({
            "symbol": symbol,
            "name": str(row.get("name", row.get("description", symbol)) or symbol).strip(),
            "yahoo_symbol": f"{symbol}.CA",
            "source": source,
        })
    if not records:
        return pd.DataFrame(columns=["symbol", "name", "yahoo_symbol", "source"])
    return pd.DataFrame(records).drop_duplicates(subset=["symbol"], keep="first")


def load_manual_symbols() -> pd.DataFrame:
    _ensure_dirs()
    columns = ["symbol", "name", "yahoo_symbol", "source"]
    if not MANUAL_SYMBOLS_FILE.exists():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(MANUAL_SYMBOLS_FILE, dtype=str).fillna("")
    if "symbol" not in frame.columns:
        return pd.DataFrame(columns=columns)
    rows = []
    for _, row in frame.iterrows():
        symbol = _clean_symbol(row.get("symbol", ""))
        if not symbol:
            continue
        name = str(row.get("name", "")).strip() or symbol
        yahoo_symbol = str(row.get("yahoo_symbol", "")).strip() or f"{symbol}.CA"
        rows.append({"symbol": symbol, "name": name, "yahoo_symbol": yahoo_symbol,
                     "source": "manual"})
    return pd.DataFrame(rows, columns=columns).drop_duplicates("symbol", keep="last")


def discover_universe(save: bool = True) -> tuple[pd.DataFrame, str]:
    """Discover current EGX symbols through TradingView's public screener wrapper.

    Manual symbols are merged into the result to allow correcting free-source gaps.
    If live discovery fails, a previously saved universe is used; otherwise the
    configured manual symbols are returned with a clear source label.
    """
    _ensure_dirs()
    tv_frame = pd.DataFrame()
    live_error = ""
    try:
        from tradingview_screener import stocks
        query = stocks("egypt").select("name", "close", "volume", "exchange", "type").limit(2000)
        _count, raw = query.get_scanner_data()
        tv_frame = _normalise_universe_rows(raw, "TradingView")
        if tv_frame.empty:
            live_error = "TradingView returned no EGX ticker rows."
    except Exception as exc:  # Keep the cache usable if an upstream endpoint changes.
        live_error = f"TradingView discovery failed: {type(exc).__name__}: {exc}"

    manual = load_manual_symbols()
    if not tv_frame.empty:
        combined = pd.concat([tv_frame, manual], ignore_index=True)
        combined = combined.drop_duplicates(subset=["symbol"], keep="last").sort_values("symbol")
        source_message = f"Live TradingView discovery plus {len(manual)} manual symbol(s)."
    else:
        if UNIVERSE_FILE.exists():
            try:
                cached = pd.read_csv(UNIVERSE_FILE, dtype=str).fillna("")
                if not cached.empty:
                    combined = pd.concat([cached, manual], ignore_index=True).drop_duplicates("symbol", keep="last")
                    source_message = f"Using cached universe because live discovery was unavailable. {live_error}"
                else:
                    combined = manual.copy()
                    source_message = f"Only manual symbols are available. {live_error}"
            except Exception:
                combined = manual.copy()
                source_message = f"Could not read cached universe; using manual symbols. {live_error}"
        else:
            combined = manual.copy()
            source_message = f"No saved universe; using manual symbols only. {live_error}"

    if combined.empty:
        raise RuntimeError(
            "No EGX symbols were discovered and no manual symbols are configured. "
            "Check internet access or add symbols to data/manual_symbols.csv. " + live_error
        )
    combined = combined[["symbol", "name", "yahoo_symbol", "source"]].copy()
    combined["symbol"] = combined["symbol"].map(_clean_symbol)
    combined = combined.drop_duplicates("symbol", keep="last").sort_values("symbol")
    if save:
        combined.to_csv(UNIVERSE_FILE, index=False)
    return combined.reset_index(drop=True), source_message


def load_universe() -> pd.DataFrame:
    _ensure_dirs()
    if UNIVERSE_FILE.exists():
        frame = pd.read_csv(UNIVERSE_FILE, dtype=str).fillna("")
        if not frame.empty and {"symbol", "yahoo_symbol"}.issubset(frame.columns):
            return frame
    return discover_universe(save=True)[0]


def _normalise_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(col[-1]) for col in out.columns]
    out.columns = [str(col).strip().title() for col in out.columns]
    missing = [c for c in OHLCV_COLUMNS if c not in out.columns]
    if missing:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    out = out[OHLCV_COLUMNS].copy()
    out.index = pd.to_datetime(out.index, errors="coerce")
    out = out.loc[~out.index.isna()].sort_index()
    # yfinance normally returns exchange-local date bars. Strip timezone if present.
    try:
        if out.index.tz is not None:
            out.index = out.index.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    for col in OHLCV_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["High", "Low", "Close"])
    out = out[(out["Close"] > 0) & (out["High"] >= out["Low"])]
    out["Volume"] = out["Volume"].fillna(0).clip(lower=0)
    return out[OHLCV_COLUMNS]


def load_price_cache(symbol: str) -> pd.DataFrame:
    path = PRICE_CACHE_DIR / f"{_clean_symbol(symbol)}.csv"
    if not path.exists():
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    try:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        return _normalise_price_frame(frame)
    except Exception:
        return pd.DataFrame(columns=OHLCV_COLUMNS)


def _save_price_cache(symbol: str, frame: pd.DataFrame) -> None:
    path = PRICE_CACHE_DIR / f"{_clean_symbol(symbol)}.csv"
    _normalise_price_frame(frame).to_csv(path, index_label="Date")


def _extract_ticker_frame(raw: pd.DataFrame, yahoo_symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    try:
        if not isinstance(raw.columns, pd.MultiIndex):
            return _normalise_price_frame(raw)
        levels = raw.columns.nlevels
        wanted = str(yahoo_symbol).upper()
        for level in range(levels):
            match = next((v for v in raw.columns.get_level_values(level).unique()
                          if str(v).upper() == wanted), None)
            if match is not None:
                part = raw.xs(match, axis=1, level=level, drop_level=True)
                if isinstance(part.columns, pd.MultiIndex):
                    # Remaining level can happen on unusual yfinance layouts.
                    part.columns = [str(col[-1]) for col in part.columns]
                cleaned = _normalise_price_frame(part)
                if not cleaned.empty:
                    return cleaned
        # If a one-ticker response has a MultiIndex with a strange alias, try
        # flattening the field names; safe because callers validate the result.
        flattened = raw.copy()
        flattened.columns = [str(col[-1]) for col in flattened.columns]
        return _normalise_price_frame(flattened)
    except Exception:
        return pd.DataFrame(columns=OHLCV_COLUMNS)


def _download_batch(tickers: list[str], period: str | None = None,
                    start: str | None = None) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    if not tickers:
        return {}
    kwargs: dict[str, Any] = {
        "tickers": tickers,
        "interval": "1d",
        "group_by": "ticker",
        "auto_adjust": False,
        "actions": False,
        "threads": 3,
        "progress": False,
        "timeout": 30,
    }
    if start:
        kwargs["start"] = start
    else:
        kwargs["period"] = period or "2y"
    raw = yf.download(**kwargs)
    return {ticker: _extract_ticker_frame(raw, ticker) for ticker in tickers}


MIN_BENCHMARK_HISTORY_BARS = 100  # Enough for RS RSI and 60-session excess return with margin.
TRADINGVIEW_BENCHMARK_BARS = 500


def _read_benchmark_cache() -> pd.DataFrame:
    """Read a cached benchmark and canonicalize it to one row per calendar day."""
    if not BENCHMARK_CACHE.exists():
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    try:
        frame = _normalise_price_frame(
            pd.read_csv(BENCHMARK_CACHE, index_col=0, parse_dates=True)
        )
        if frame.empty:
            return frame
        dates = pd.DatetimeIndex(frame.index)
        if dates.tz is not None:
            dates = dates.tz_localize(None)
        frame.index = dates.normalize()
        frame = frame.sort_index()
        return frame.loc[~frame.index.duplicated(keep="last")]
    except Exception:
        return pd.DataFrame(columns=OHLCV_COLUMNS)


def _normalise_tradingview_benchmark(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert tvDatafeed's lowercase OHLCV columns and timed index to daily bars."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    frame = raw.copy()
    column_map = {}
    for column in frame.columns:
        name = str(column).strip().lower()
        if name in {"open", "high", "low", "close", "volume"}:
            column_map[column] = name.title()
    frame = frame.rename(columns=column_map)
    out = _normalise_price_frame(frame)
    if out.empty:
        return out
    dates = pd.DatetimeIndex(out.index)
    if dates.tz is not None:
        dates = dates.tz_localize(None)
    out.index = dates.normalize()
    out = out.sort_index()
    return out.loc[~out.index.duplicated(keep="last")]


def _download_benchmark_history() -> tuple[pd.DataFrame, list[str]]:
    """Fetch EGX30 history from TradingView first, then try Yahoo as a fallback.

    TradingView's public EGX:EGX30 chart has been verified to return daily history
    via tvDatafeed in the current setup. Yahoo can still serve as a fallback, but
    neither provider is allowed to contribute a one-row 'history'.
    """
    attempts: list[str] = []

    # Primary source: TradingView public chart data through the installed
    # tradingview-datafeed package (import name: tvDatafeed).
    try:
        from tvDatafeed import TvDatafeed, Interval
        tv = TvDatafeed()
        raw = tv.get_hist(
            symbol="EGX30",
            exchange="EGX",
            interval=Interval.in_daily,
            n_bars=TRADINGVIEW_BENCHMARK_BARS,
        )
        frame = _normalise_tradingview_benchmark(raw)
        if len(frame) >= MIN_BENCHMARK_HISTORY_BARS:
            latest = frame.index.max().date().isoformat()
            return frame, attempts + [
                f"SUCCESS TradingView EGX:EGX30: {len(frame)} bars through {latest}"
            ]
        attempts.append(f"TradingView EGX:EGX30: only {len(frame)} usable bars")
    except Exception as exc:
        attempts.append(f"TradingView EGX:EGX30: {type(exc).__name__}: {exc}")

    # Fallback source: try several Yahoo Finance request styles. Accept it only
    # if a substantial daily history is returned.
    try:
        import yfinance as yf
        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        start = (today - pd.Timedelta(days=800)).date().isoformat()
        end = (today + pd.Timedelta(days=1)).date().isoformat()  # Yahoo end is exclusive.
        requests = [
            ("yf.download with explicit start/end", lambda: yf.download(
                tickers=BENCHMARK_TICKER, start=start, end=end, interval="1d",
                group_by="ticker", auto_adjust=False, actions=False, progress=False,
                threads=False, timeout=30,
            )),
            ("Ticker.history with explicit start/end", lambda: yf.Ticker(BENCHMARK_TICKER).history(
                start=start, end=end, interval="1d", auto_adjust=False, actions=False,
            )),
            ("yf.download period=2y fallback", lambda: yf.download(
                tickers=BENCHMARK_TICKER, period="2y", interval="1d",
                group_by="ticker", auto_adjust=False, actions=False, progress=False,
                threads=False, timeout=30,
            )),
        ]
        for description, request in requests:
            try:
                raw = request()
                frame = _extract_ticker_frame(raw, BENCHMARK_TICKER)
                if len(frame) >= MIN_BENCHMARK_HISTORY_BARS:
                    dates = pd.DatetimeIndex(frame.index)
                    if dates.tz is not None:
                        dates = dates.tz_localize(None)
                    frame.index = dates.normalize()
                    frame = frame.sort_index()
                    frame = frame.loc[~frame.index.duplicated(keep="last")]
                    latest = frame.index.max().date().isoformat()
                    return frame, attempts + [
                        f"SUCCESS Yahoo Finance {BENCHMARK_TICKER}: {len(frame)} bars through {latest}"
                    ]
                attempts.append(f"Yahoo {description}: only {len(frame)} bars")
            except Exception as exc:
                attempts.append(f"Yahoo {description}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        attempts.append(f"Yahoo fallback unavailable: {type(exc).__name__}: {exc}")

    return pd.DataFrame(columns=OHLCV_COLUMNS), attempts


def _fetch_benchmark() -> tuple[pd.DataFrame, str]:
    """Fetch, validate and cache EGX30 history, keeping a good cache on outages."""
    _ensure_dirs()
    cached = _read_benchmark_cache()
    fresh, attempts = _download_benchmark_history()

    if len(fresh) >= MIN_BENCHMARK_HISTORY_BARS:
        # Fresh daily rows replace cached rows for the same session. Indexes are
        # normalized to calendar dates before merge, preventing duplicate 00:00
        # and 10:00 timestamps for the same EGX session.
        combined = pd.concat([cached, fresh]).sort_index(kind="stable")
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = _normalise_price_frame(combined)
        combined.to_csv(BENCHMARK_CACHE, index_label="Date")
        latest = combined.index.max().date().isoformat()
        return combined, f"{attempts[-1]}; cache has {len(combined)} bars through {latest}"

    # Never accept the stale/one-row cache as usable RS data.
    if len(cached) >= MIN_BENCHMARK_HISTORY_BARS:
        latest = cached.index.max().date().isoformat()
        details = "; ".join(attempts)
        return cached, f"Using cached EGX30 ({len(cached)} bars through {latest}); refresh failed: {details}"

    details = "; ".join(attempts) or "no response"
    raise RuntimeError(
        "No usable EGX30 benchmark history from TradingView or Yahoo Finance. "
        f"At least {MIN_BENCHMARK_HISTORY_BARS} daily bars are required; cached bars: {len(cached)}. "
        f"Attempts: {details}. A one-row response is deliberately rejected. "
        "Check connectivity and confirm `tradingview-datafeed` is installed with "
        "`uv pip install -r requirements.txt`."
    )


def refresh_price_cache(universe: pd.DataFrame | None = None, period: str = "2y",
                        batch_size: int = 20, pause_seconds: float = 1.0) -> pd.DataFrame:
    """Refresh stock and benchmark caches, returning a per-symbol coverage audit.

    For existing cache files, only recent rows are requested and merged. New symbols
    download the selected period. Individual gaps are retained as failures in the
    audit instead of aborting the complete market scan.
    """
    _ensure_dirs()
    if universe is None or universe.empty:
        universe = load_universe()
    benchmark, bench_source = _fetch_benchmark()
    records: list[dict[str, Any]] = []

    items: list[dict[str, str]] = []
    for _, row in universe.iterrows():
        symbol = _clean_symbol(row.get("symbol", ""))
        yahoo_symbol = str(row.get("yahoo_symbol", "")).strip() or f"{symbol}.CA"
        if symbol:
            items.append({"symbol": symbol, "yahoo_symbol": yahoo_symbol})

    # Cold tickers can be downloaded as multi-symbol batches. Existing caches are
    # also fetched in batches, starting shortly before their oldest latest date.
    cold: list[dict[str, str]] = []
    warm: list[dict[str, str]] = []
    for item in items:
        cache = load_price_cache(item["symbol"])
        item["cache_rows"] = str(len(cache))
        item["cache_last"] = cache.index.max().date().isoformat() if not cache.empty else ""
        (warm if not cache.empty else cold).append(item)

    for batch in [cold[i:i + batch_size] for i in range(0, len(cold), batch_size)]:
        tickers = [item["yahoo_symbol"] for item in batch]
        try:
            downloaded = _download_batch(tickers, period=period)
        except Exception as exc:
            downloaded = {ticker: pd.DataFrame(columns=OHLCV_COLUMNS) for ticker in tickers}
            batch_error = f"batch download error: {type(exc).__name__}: {exc}"
        else:
            batch_error = ""
        for item in batch:
            frame = downloaded.get(item["yahoo_symbol"], pd.DataFrame(columns=OHLCV_COLUMNS))
            if not frame.empty:
                _save_price_cache(item["symbol"], frame)
                records.append({"symbol": item["symbol"], "yahoo_symbol": item["yahoo_symbol"],
                                "rows": len(frame), "last_date": frame.index.max().date().isoformat(),
                                "fetch_status": "UPDATED", "source": "Yahoo Finance", "details": ""})
            else:
                records.append({"symbol": item["symbol"], "yahoo_symbol": item["yahoo_symbol"],
                                "rows": 0, "last_date": "", "fetch_status": "NO_DATA",
                                "source": "Yahoo Finance", "details": batch_error or "No daily bars returned for this alias."})
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    for batch in [warm[i:i + batch_size] for i in range(0, len(warm), batch_size)]:
        # Use the earliest cache date in this batch minus ten days so a temporarily
        # stale symbol can catch up; merge replaces duplicate dates with fresh rows.
        start_dates = []
        for item in batch:
            try:
                last = pd.Timestamp(item["cache_last"])
                start_dates.append((last - pd.Timedelta(days=10)).date().isoformat())
            except Exception:
                pass
        fetch_start = min(start_dates) if start_dates else None
        tickers = [item["yahoo_symbol"] for item in batch]
        try:
            downloaded = _download_batch(tickers, start=fetch_start) if fetch_start else _download_batch(tickers, period=period)
        except Exception as exc:
            downloaded = {ticker: pd.DataFrame(columns=OHLCV_COLUMNS) for ticker in tickers}
            batch_error = f"incremental download error: {type(exc).__name__}: {exc}"
        else:
            batch_error = ""
        for item in batch:
            old = load_price_cache(item["symbol"])
            fresh = downloaded.get(item["yahoo_symbol"], pd.DataFrame(columns=OHLCV_COLUMNS))
            if not fresh.empty:
                merged = pd.concat([old, fresh]).sort_index()
                merged = merged[~merged.index.duplicated(keep="last")]
                _save_price_cache(item["symbol"], merged)
                final = merged
                status = "UPDATED"
                details = ""
            else:
                final = old
                status = "CACHE_ONLY" if not old.empty else "NO_DATA"
                details = batch_error or ("Refresh returned no new rows; retained cache." if not old.empty else "No rows returned.")
            records.append({"symbol": item["symbol"], "yahoo_symbol": item["yahoo_symbol"],
                            "rows": len(final), "last_date": final.index.max().date().isoformat() if not final.empty else "",
                            "fetch_status": status, "source": "Yahoo Finance", "details": details})
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    audit = pd.DataFrame(records)
    audit.attrs["benchmark_source"] = bench_source
    if not audit.empty:
        audit.to_csv(CACHE_DIR / "price_coverage_audit.csv", index=False)
    return audit


def load_benchmark_close() -> pd.Series:
    frame = _read_benchmark_cache()
    if len(frame) < MIN_BENCHMARK_HISTORY_BARS:
        frame, _source = _fetch_benchmark()
    if len(frame) < MIN_BENCHMARK_HISTORY_BARS:
        raise RuntimeError(
            f"EGX30 benchmark history is insufficient ({len(frame)} bars); "
            f"need at least {MIN_BENCHMARK_HISTORY_BARS}. Relative strength cannot be trusted."
        )
    return frame["Close"].copy()

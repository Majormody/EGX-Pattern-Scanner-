from __future__ import annotations
from pathlib import Path
import pandas as pd
import streamlit as st

from egx_scanner.scanner import run_scan
from egx_scanner.settings import OUTPUT_DIR, ScanConfig
from egx_scanner.sources import discover_universe, load_universe, load_price_cache
from egx_scanner.indicators import add_price_indicators

st.set_page_config(page_title="EGX Tight-Base Scanner", page_icon="📈", layout="wide")
st.title("EGX Tight-Base Breakout Scanner")
st.caption("Daily end-of-day research tool • Free data sources • Heuristic ranking, not investment advice")

with st.sidebar:
    st.header("Pattern settings")
    min_score = st.slider("Minimum setup score", min_value=35, max_value=90, value=62, step=1)
    base_min = st.slider("Shortest base (bars)", min_value=8, max_value=25, value=12, step=1)
    base_max = st.slider("Longest base (bars)", min_value=max(20, base_min), max_value=70, value=max(45, base_min), step=1)
    breakout_rv = st.slider("Breakout relative-volume minimum", min_value=0.8, max_value=3.0, value=1.3, step=0.1)
    hold_bars = st.slider("Breakout monitoring window (bars)", min_value=1, max_value=10, value=5, step=1)
    period = st.selectbox("Initial history for new symbols", ["1y", "2y", "5y", "max"], index=1)
    st.divider()
    st.write("**Data sources**")
    st.caption("TradingView public screener for the ticker universe; Yahoo Finance daily bars; EGX30 benchmark `^CASE30`.")

config = ScanConfig(min_score=float(min_score), base_min_bars=int(base_min), base_max_bars=int(base_max),
                    breakout_relative_volume=float(breakout_rv), breakout_hold_bars=int(hold_bars))

universe_cols = st.columns([1, 1, 2])
with universe_cols[0]:
    if st.button("Refresh EGX symbol list", use_container_width=True):
        try:
            with st.spinner("Discovering EGX symbols..."):
                universe, message = discover_universe(save=True)
            st.success(f"Saved {len(universe)} symbols.")
            st.info(message)
        except Exception as exc:
            st.error(f"Could not refresh the symbol list: {exc}")
with universe_cols[1]:
    cached_file = OUTPUT_DIR / "latest_scan.csv"
    if st.button("Load last saved scan", use_container_width=True):
        if cached_file.exists():
            st.session_state["results"] = pd.read_csv(cached_file)
        else:
            st.warning("No saved scan yet. Run a scan first.")

try:
    universe = load_universe()
    st.caption(f"Current saved universe: {len(universe)} symbols. This is the source-discovered/manual universe, not a guarantee of complete EGX listing coverage.")
except Exception as exc:
    st.warning(f"No symbol universe is currently available: {exc}")

if st.button("Run full market scan", type="primary", use_container_width=True):
    try:
        with st.spinner("Refreshing daily prices and evaluating available symbols. First run can take longer; missing aliases will be reported."):
            results, info = run_scan(config=config, refresh_prices=True, refresh_universe=False, period=period)
        st.session_state["results"] = results
        st.session_state["scan_info"] = info
        st.success(f"Scan finished. {info['symbols_with_price_data']} of {info['universe_count']} symbols have cached prices.")
        st.info(f"Universe: {info['universe_message']} | EGX30 data through {info['benchmark_last_date']} | Saved to {info['latest_file']}")
    except Exception as exc:
        st.error(f"The scan could not complete: {type(exc).__name__}: {exc}")

results = st.session_state.get("results")
if results is None:
    latest = OUTPUT_DIR / "latest_scan.csv"
    if latest.exists():
        try:
            results = pd.read_csv(latest)
            st.session_state["results"] = results
        except Exception:
            results = None

if results is not None and not results.empty:
    results = results.copy()
    total = len(results)
    price_rows = int((pd.to_numeric(results.get("history_bars", 0), errors="coerce").fillna(0) > 0).sum()) if "history_bars" in results else int((results.get("close", pd.Series(dtype=float)).notna()).sum())
    forming_n = int((results["status"] == "FORMING").sum()) if "status" in results else 0
    breakout_n = int((results["status"] == "BREAKOUT").sum()) if "status" in results else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Symbols in universe", total)
    c2.metric("Symbols with price data", price_rows)
    c3.metric("Forming setups", forming_n)
    c4.metric("Recent breakouts", breakout_n)

    statuses = [s for s in ["BREAKOUT", "FAILED", "FORMING", "NONE", "INSUFFICIENT_DATA", "NO_PRICE_DATA"] if s in set(results["status"].astype(str))]
    chosen_statuses = st.multiselect("Show statuses", statuses, default=[s for s in ["BREAKOUT", "FAILED", "FORMING"] if s in statuses] or statuses)
    score_floor = st.slider("Minimum displayed score", min_value=0, max_value=100, value=0, step=1)
    view = results[results["status"].isin(chosen_statuses)].copy()
    if "pattern_score" in view:
        view = view[pd.to_numeric(view["pattern_score"], errors="coerce").fillna(0) >= score_floor]
        view = view.sort_values("pattern_score", ascending=False)
    preferred = [
        "symbol", "name", "status", "pattern_score", "close", "ceiling", "pivot_date", "pivot_method",
        "pivot_prominence_atr", "pivot_count", "distance_to_ceiling_pct", "relative_volume", "rs_rsi",
        "rs_data_available",
        "excess_return_20d_pct", "excess_return_60d_pct", "base_len",
        "strength_grade", "trend_grade", "contraction_grade", "volume_grade", "closeness_grade",
        "relative_strength_grade", "advance_pct", "pullback_pct", "price_last_date", "history_bars",
        "price_fetch_status", "price_fetch_details",
    ]
    visible = [col for col in preferred if col in view.columns]
    st.dataframe(view[visible], use_container_width=True, hide_index=True, height=520)
    st.download_button(
        "Download displayed results as CSV",
        data=view.to_csv(index=False).encode("utf-8-sig"),
        file_name="egx_tight_base_results.csv",
        mime="text/csv",
    )

    st.subheader("Chart review")
    st.caption("Use the chart to visually verify whether the selected candidate really looks like a tight base. The dashed orange line is the selected breakout pivot; the dotted vertical marker shows the bar where that pivot was detected. The shaded region is the candidate base window.")
    chart_rows = results.copy()
    if "pattern_score" in chart_rows:
        chart_rows = chart_rows.sort_values("pattern_score", ascending=False)
    chart_options = chart_rows[chart_rows.get("history_bars", pd.Series(0, index=chart_rows.index)).fillna(0).astype(float) > 0]["symbol"].astype(str).tolist()
    if chart_options:
        selected_symbol = st.selectbox(
            "Stock to inspect",
            chart_options,
            format_func=lambda symbol: (
                f"{symbol} — {str(chart_rows.loc[chart_rows['symbol'].astype(str) == symbol, 'status'].iloc[0])} — "
                f"score {float(chart_rows.loc[chart_rows['symbol'].astype(str) == symbol, 'pattern_score'].iloc[0]):.1f}"
            ),
        )
        chart_prices = load_price_cache(selected_symbol)
        if not chart_prices.empty:
            chart_prices = add_price_indicators(chart_prices, 20, 50, 14, 20).tail(160)
            candidate_row = chart_rows[chart_rows["symbol"].astype(str) == selected_symbol].iloc[0]
            try:
                import plotly.graph_objects as go
                from plotly.subplots import make_subplots
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                                    row_heights=[0.74, 0.26],
                                    subplot_titles=(f"{selected_symbol} — daily candles", "Volume"))
                fig.add_trace(go.Candlestick(
                    x=chart_prices.index, open=chart_prices["Open"], high=chart_prices["High"],
                    low=chart_prices["Low"], close=chart_prices["Close"], name="Daily OHLC",
                ), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_prices.index, y=chart_prices["EMA_fast"],
                                         name="EMA 20", line={"width": 1.3}), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_prices.index, y=chart_prices["SMA_mid"],
                                         name="SMA 50", line={"width": 1.3}), row=1, col=1)
                ceiling = pd.to_numeric(pd.Series([candidate_row.get("ceiling", float("nan"))]), errors="coerce").iloc[0]
                if pd.notna(ceiling):
                    fig.add_trace(go.Scatter(x=chart_prices.index, y=[float(ceiling)] * len(chart_prices),
                                             name="Estimated ceiling / pivot", line={"dash": "dash", "width": 1.5}), row=1, col=1)
                pivot_date = pd.to_datetime(candidate_row.get("pivot_date", ""), errors="coerce")
                if pd.notna(pivot_date) and chart_prices.index.min() <= pivot_date <= chart_prices.index.max():
                    fig.add_vline(x=pivot_date, line_dash="dot", line_width=1,
                                  annotation_text="Selected pivot", row=1, col=1)
                fig.add_trace(go.Bar(x=chart_prices.index, y=chart_prices["Volume"], name="Volume", opacity=0.55), row=2, col=1)
                base_start = str(candidate_row.get("base_start_date", ""))
                if base_start:
                    start_dt = pd.to_datetime(base_start, errors="coerce")
                    if pd.notna(start_dt) and start_dt >= chart_prices.index.min():
                        fig.add_vrect(x0=start_dt, x1=chart_prices.index.max(), fillcolor="LightSkyBlue",
                                      opacity=0.10, line_width=0, row=1, col=1)
                fig.update_layout(height=650, xaxis_rangeslider_visible=False,
                                  legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
                                  margin={"l": 20, "r": 20, "t": 70, "b": 20})
                fig.update_yaxes(title_text="Price (EGP)", row=1, col=1)
                fig.update_yaxes(title_text="Shares", row=2, col=1)
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                st.info("Install Plotly (`pip install plotly`) to enable interactive candlestick charts.")
    else:
        st.caption("No symbols with cached prices are available for chart review yet.")

    st.subheader("How to interpret relative strength")
    st.write("**RS RSI** is the 14-bar RSI of the stock's close divided by the EGX30 close. Above 50 suggests improving relative momentum; it is not the same as the ordinary RSI of the stock. The 20D/60D excess-return columns show stock price return minus EGX30 price-index return over those windows.")
    st.warning("A high score is a pattern match, not a probability or a buy signal. Review liquidity, corporate actions, price limits, and execution costs before acting.")
else:
    st.info("No scan results are loaded yet. Use **Run full market scan** to discover/update the available universe, download daily history, score patterns, and save a CSV.")

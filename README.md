# EGX Tight-Base Breakout Scanner

A free, open-source Python tool for finding Egyptian Exchange (EGX) stocks that resemble a **tight-base breakout setup**: a strong prior advance, a consolidation period, price tightening near resistance, and a potential breakout supported by volume.

The scanner evaluates multiple possible base lengths, estimates a candidate breakout pivot, compares each stock's relative strength against EGX30, and ranks candidates using a weighted pattern score. It provides a command-line interface, an interactive Streamlit dashboard, and CSV reports.

> **Important:** This is a technical-analysis research tool, not a trading system or a prediction model. A pattern score of 80/100 means the observed chart characteristics match the defined criteria; it does not mean there is an 80% probability of a successful breakout. Always verify candidates against the actual chart.

## Contents

- [Features](#features)
- [How the methodology works](#how-the-methodology-works)
- [Data sources and coverage](#data-sources-and-coverage)
- [Installation](#installation)
- [Run your first scan](#run-your-first-scan)
- [Launch the dashboard](#launch-the-dashboard)
- [Command-line reference](#command-line-reference)
- [Understanding the results](#understanding-the-results)
- [Configuration and manual symbols](#configuration-and-manual-symbols)
- [Project structure](#project-structure)
- [Tests and continuous integration](#tests-and-continuous-integration)
- [Limitations and responsible use](#limitations-and-responsible-use)

## Features

- **EGX universe discovery:** Retrieves symbols through TradingView's public screener interface and merges optional manual symbol mappings.
- **Daily OHLCV history:** Downloads daily open, high, low, close, and volume data through Yahoo Finance.
- **Local caching:** Saves downloaded prices and benchmark history so repeated scans can reuse existing data.
- **Multiple base lengths:** Evaluates candidate consolidation windows rather than requiring one fixed base length.
- **Pivot-aware resistance detection:** Searches for recent, confirmed swing highs and reports when a fallback resistance level is used.
- **Weighted pattern scoring:** Grades prior strength, trend, contraction, volume behavior, proximity to resistance, and relative strength.
- **EGX30-relative strength:** Calculates the RSI of the stock's closing-price ratio to EGX30, along with 20- and 60-bar excess returns.
- **Coverage reporting:** Keeps unavailable symbols visible instead of silently treating missing prices as a lack of a setup.
- **Interactive chart review:** Provides candlestick charts, moving averages, volume, candidate base regions, and the selected pivot.
- **CSV export:** Saves complete scan results for further analysis in Python, Excel, or other tools.

## How the methodology works

The goal is to approximate how a human chart reader recognizes a promising consolidation pattern. Rather than relying on a single rigid price shape, the scanner evaluates several components and combines them into a score.

### 1. Find a prior advance and a candidate base

The scanner evaluates base lengths between **12 and 45 trading bars by default**. These are trading sessions, not calendar days.

For each candidate window, it examines the preceding price history to estimate the earlier impulse advance, its peak, and the pullback leading into the base.

A candidate base should represent consolidation after an advance, not the entire advance itself. The scanner therefore measures strong low-to-high rallies occurring within candidate windows and rejects a candidate if it finds a move meeting both of these initial conditions:

- At least 15% price appreciation.
- At least 3 Average True Range (ATR).

The move must occur within the configured 12-bar lookback window.

These are heuristic safeguards, not universal definitions of a valid base. The scanner tests other candidate lengths, but it cannot guarantee that its chosen boundaries will match a human analyst's interpretation.

### 2. Detect the potential breakout pivot

The **ceiling** is the candidate resistance level the scanner monitors for a possible breakout. It is not automatically the highest price in the entire consolidation.

The current pivot detector:

1. Searches for local swing highs in the candidate base.
2. Requires two bars on each side to confirm a local high.
3. Requires at least 0.45 ATR of local prominence.
4. Selects the most recent qualifying swing high, excluding the newest base bar from pivot selection.
5. If no qualifying swing high is found, uses the previous range high as a fallback and labels the method explicitly.

The scanner reports the selected pivot date, its prominence, the number of detected pivots, and the highest high within the full base.

This is an approximation of human chart reading. It does not yet identify every meaningful multi-touch resistance shelf or fit descending resistance trendlines.

### 3. Grade the pattern

The default pattern score combines six components:

| Component | Weight | What it measures |
|---|---:|---|
| Strength | 20% | Quality of the preceding advance relative to the pullback |
| Trend | 15% | Moving-average direction and price behavior above the mid-term average |
| Contraction | 25% | Reduction in candle ranges and overall swing width toward the end of the base |
| Volume | 15% | Up-day versus down-day volume, fading selling volume, and quieter base volume relative to the advance |
| Closeness | 15% | How close the current price is to the estimated resistance pivot, relative to the base's height |
| Relative strength | 10% | Momentum of the stock relative to EGX30 |

The default minimum score for a forming setup is **62/100**.

If relative-strength data is unavailable, the scanner leaves the relative-strength grade blank and recalculates the total from the available components. This avoids treating missing benchmark data as a neutral score.

### 4. Measure relative strength against EGX30

Ordinary RSI measures a stock's own price momentum. This scanner additionally calculates a relative-strength RSI (RS RSI) to assess momentum against the market benchmark.

First, it calculates:

`Relative-strength ratio = Stock close / EGX30 close`

It then applies a 14-period RSI calculation to this ratio.

- **RS RSI above 50:** Generally indicates positive recent momentum in the stock's price relative to EGX30.
- **RS RSI below 50:** Generally indicates negative recent relative momentum.
- **RS RSI near 50:** Indicates relatively balanced momentum over the RSI's smoothing window.

The scanner also reports:

- `excess_return_20d_pct`: the stock's 20-bar price return minus EGX30's 20-bar price return.
- `excess_return_60d_pct`: the stock's 60-bar price return minus EGX30's 60-bar price return.

These are relative **price-return** measurements, not dividend-inclusive total returns. They complement the pattern score; they do not predict future outperformance.

### 5. Identify forming setups and breakout attempts

The scanner uses the following status labels:

| Status | Meaning |
|---|---|
| `FORMING` | The latest price remains at or below the candidate ceiling, the score meets the configured threshold, and the closeness criterion is satisfied. |
| `BREAKOUT` | A qualifying recent setup closed above its pivot with sufficient relative volume and a strong close within the candle, and no monitored failure was detected. |
| `FAILED` | A qualifying breakout was followed by a close below its saved pivot during the monitored window. |
| `NONE` | No candidate met the forming or recent-breakout conditions. The best available candidate's score is still reported. |
| `INSUFFICIENT_DATA` | Available history is insufficient for the required calculations. |
| `NO_PRICE_DATA` | Usable daily price history is unavailable for the symbol. |

The default breakout conditions include:

- A close above the pivot by an ATR-based buffer.
- Relative volume of at least 1.30 times its moving average.
- A close at least 55% of the way from the candle's low to its high.
- A recent qualifying setup.
- Monitoring over a configured window of five bars.

A `BREAKOUT` label is a detection result, **not a buy instruction**. A breakout can fail, encounter overhead resistance, or be difficult to trade because of liquidity, price limits, or transaction costs.

For more details about the calculations and assumptions, see [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Data sources and coverage

The project uses free, unofficial data interfaces.

| Purpose | Source | Python package |
|---|---|---|
| EGX symbol discovery | TradingView public screener | `tradingview-screener` |
| Stock daily OHLCV | Yahoo Finance | `yfinance` |
| EGX30 benchmark history | TradingView chart first, Yahoo Finance fallback | `tradingview-datafeed`, `yfinance` |
| Data processing | pandas and NumPy | `pandas`, `numpy` |
| Dashboard and charts | Streamlit and Plotly | `streamlit`, `plotly` |

For the benchmark, the program requests daily history for `EGX:EGX30` through the `tvDatafeed` Python import. It can fall back to Yahoo Finance's `^CASE30` symbol. The loader requires at least 100 usable benchmark bars before accepting the history.

The providers are not guaranteed APIs. They can change, rate-limit requests, return incomplete histories, or temporarily become unavailable. The scanner reports missing data rather than assuming every discovered symbol has been successfully evaluated.

**Coverage is not guaranteed to include every currently listed EGX security.** The discovered universe and the subset with usable price history can differ. Check the coverage report after downloading prices.

The project does not include downloaded stock-price histories in the repository. Each user builds a local cache by running the scanner. This avoids publishing market data without permission to redistribute it.

## Installation

The project uses [`uv`](https://docs.astral.sh/uv/) to manage Python and dependencies. You do not need to install packages globally or create a virtual environment manually.

### Prerequisites

- Windows, macOS, Linux, or WSL.
- Git, if cloning the repository.
- `uv`, the Python project and package manager.
- An internet connection for symbol discovery and price downloads.

The project targets Python 3.12. `uv` can install the required Python version for you.

### 1. Install uv

If you already have `uv` installed, skip this step.

**Windows — PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen the terminal, then verify:

```powershell
uv --version
```

**macOS, Linux, or WSL — terminal:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the terminal if necessary, then verify:

```bash
uv --version
```

See the [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) for other installation options.

### 2. Get the project

Once the repository has been published, clone it using its GitHub URL:

```bash
git clone https://github.com/<YOUR-USERNAME>/<YOUR-REPOSITORY>.git
cd <YOUR-REPOSITORY>
```

Replace the placeholders with the actual GitHub owner and repository name.

Alternatively, use GitHub's **Code → Download ZIP** option and extract the project. Then open a terminal in the extracted folder.

### 3. Install Python and dependencies

From the project root, run:

```bash
uv python install 3.12
uv sync --locked
```

`uv sync --locked` reads dependencies from `pyproject.toml`, uses `uv.lock` to reproduce the resolved versions, and creates or synchronizes the project's `.venv` environment.

The lockfile should be kept in version control. If the project configuration and lockfile disagree, this command fails rather than silently changing the lockfile.

You don't need to activate `.venv` manually when using `uv run`.

### 4. Verify the installation

Run the automated tests:

```bash
uv run python -m unittest discover -s tests -v
```

If the tests pass, the environment is ready.

## Run your first scan

A fresh clone does not include a downloaded EGX universe or local price history. The first scan needs to discover the available symbols and download data.

### Option A: Run the complete workflow

From the project root, execute:

```bash
uv run python -m egx_scanner.cli run --period 2y --batch-size 8 --pause 3
```

This command:

1. Refreshes the available symbol universe.
2. Downloads or updates stock price histories.
3. Fetches or refreshes EGX30 benchmark history.
4. Evaluates available stocks.
5. Writes the scan results to CSV.

The first full-market download can take several minutes or longer. The small batch size and three-second pause are cautious initial settings intended to reduce rate-limit issues.

If a provider limits requests, wait and retry the affected data download later. Do not interpret failed downloads as stocks without a setup.

### Option B: Run each stage separately

**1. Discover the symbols**

```bash
uv run python -m egx_scanner.cli universe
```

This saves the discovered and manually configured universe to `data/universe.csv`.

**2. Download historical prices**

```bash
uv run python -m egx_scanner.cli prices --period 2y --batch-size 8 --pause 3
```

This populates the local price cache and refreshes the coverage audit.

**3. Inspect data coverage**

```bash
uv run python -m egx_scanner.cli coverage
```

Review symbols with `NO_DATA` status and check the latest available dates. Some symbols may have unsupported or incorrect Yahoo aliases.

**4. Run the scanner against cached prices**

```bash
uv run python -m egx_scanner.cli scan --no-refresh
```

This uses existing stock price caches rather than downloading stock histories again. It still requires a valid EGX30 benchmark history; if benchmark data is missing or insufficient, the scanner attempts to retrieve it and reports an error if that fails.

## Launch the dashboard

After setup, run:

```bash
uv run streamlit run app.py
```

Streamlit prints a local URL, usually `http://localhost:8501`. Open it in your browser.

For a first-time user:

1. Click **Refresh EGX symbol list**.
2. Click **Run full market scan**.
3. Wait for the download and scoring process to finish.
4. Filter the results by status and minimum displayed score.
5. Select a stock under **Chart review** to inspect its daily candles, volume, moving averages, base region, and selected pivot.
6. Download the displayed table as CSV if needed.

The dashboard also lets you load the last saved scan. It is an interface for running and inspecting the scanner, not a hosted market-data service.

## Command-line reference

Run `uv run python -m egx_scanner.cli --help` for general help or append `--help` to an individual command.

| Command | Purpose |
|---|---|
| `uv run python -m egx_scanner.cli universe` | Refresh symbol discovery |
| `uv run python -m egx_scanner.cli prices` | Download or update daily price history |
| `uv run python -m egx_scanner.cli coverage` | Display the last saved source-coverage audit |
| `uv run python -m egx_scanner.cli scan --no-refresh` | Scan existing cached stock prices |
| `uv run python -m egx_scanner.cli scan --min-score 68` | Require a higher score for a forming setup |
| `uv run python -m egx_scanner.cli run` | Refresh symbols, update prices, and scan |

Useful configurable arguments include:

- `--period`: requested stock-price history for a first download, such as `1y`, `2y`, or `5y`.
- `--min-score`: minimum score for a forming setup; default `62`.
- `--base-min`: minimum candidate base length; default `12` bars.
- `--base-max`: maximum candidate base length; default `45` bars.
- `--break-rv`: required relative volume on the breakout bar; default `1.30`.
- `--hold-bars`: breakout monitoring window; default `5` bars.
- `--batch-size`: number of stock symbols requested per price-download batch.
- `--pause`: delay between batches in seconds.

For example, to perform a stricter scan using cached prices:

```bash
uv run python -m egx_scanner.cli scan --no-refresh --min-score 68
```

## Understanding the results

The scanner writes:

- `outputs/latest_scan.csv` — the most recent scan results.
- `outputs/egx_tight_base_scan_<timestamp>.csv` — a timestamped copy of each scan.
- `data/universe.csv` — the current discovered/manual symbol universe.
- `data/cache/prices/` — per-symbol local price histories.
- `data/cache/egx30_benchmark.csv` — cached EGX30 benchmark history.
- `data/cache/price_coverage_audit.csv` — data-fetch results and missing-price information.

These generated CSV files and caches are local data. They are intentionally excluded from the Git repository.

Important result columns include:

| Column | Meaning |
|---|---|
| `symbol` | EGX ticker symbol |
| `status` | Current candidate status |
| `pattern_score` | Weighted score from 0 to 100 |
| `close` | Latest available closing price |
| `ceiling` | Selected potential breakout pivot |
| `pivot_date` | Date of the selected pivot |
| `pivot_method` | Swing-high detection or fallback method |
| `pivot_prominence_atr` | Pivot prominence relative to ATR |
| `base_len` | Candidate base length in trading bars |
| `distance_to_ceiling_pct` | Percentage gap between the close and the selected ceiling |
| `relative_volume` | Latest volume relative to its moving average |
| `rs_rsi` | RSI of the stock/EGX30 closing-price ratio |
| `excess_return_20d_pct` | 20-bar excess price return versus EGX30 |
| `excess_return_60d_pct` | 60-bar excess price return versus EGX30 |
| `strength_grade` | Grade for the preceding advance versus pullback |
| `trend_grade` | Trend grade |
| `contraction_grade` | Contraction grade |
| `volume_grade` | Volume-behavior grade |
| `closeness_grade` | Closeness-to-ceiling grade |
| `relative_strength_grade` | Relative-strength grade, blank when unavailable |
| `price_fetch_status` | Latest recorded status of the price download |

A positive `distance_to_ceiling_pct` means the close is below the pivot. A value near zero means price is close to resistance. A negative value means price is above the selected pivot.

For a `BREAKOUT` or `FAILED` row, the distance refers to the saved breakout pivot.

The ceiling is a candidate trigger level, not necessarily the only resistance visible on the chart. Inspect the candles and the surrounding price structure before interpreting the level.

## Configuration and manual symbols

The default scan settings are defined in `egx_scanner/settings.py`. The CLI can override several of these settings without editing source code.

If the public screener misses a ticker or Yahoo Finance requires a different symbol alias, edit `data/manual_symbols.csv`.

The file has these columns:

```csv
symbol,name,yahoo_symbol
ABUK,Abu Qir Fertilizers,ABUK.CA
```

Replace the example with the relevant ticker mapping, or add a row beneath the header. Use the exact Yahoo Finance symbol that returns the intended stock's history.

Then run:

```bash
uv run python -m egx_scanner.cli universe
uv run python -m egx_scanner.cli prices --period 2y
uv run python -m egx_scanner.cli coverage
```

Check that the symbol has usable rows in the coverage audit. Do not assume that an alias works just because it has the expected format.

## Project structure

```text
EGX_scanner/
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions test workflow
├── data/
│   └── manual_symbols.csv      # Optional symbol corrections
├── docs/
│   ├── CHANGELOG.md
│   ├── METHODOLOGY.md          # Detailed scoring methodology
│   └── SETUP_WINDOWS.md
├── egx_scanner/
│   ├── cli.py                  # Command-line interface
│   ├── indicators.py           # Technical indicators and relative strength
│   ├── patterns.py             # Pattern detection and scoring
│   ├── scanner.py              # Scan orchestration and output
│   ├── settings.py             # Default settings and paths
│   └── sources.py              # Market-data source adapters and caching
├── tests/                      # Offline tests
├── app.py                      # Streamlit dashboard
├── pyproject.toml              # Project metadata and dependencies
├── uv.lock                     # Resolved dependency versions
├── requirements.txt             # Compatibility dependency list
├── .python-version              # Selected Python version
├── .gitignore
├── LICENSE
└── README.md
```

Downloaded histories, generated CSV outputs, virtual environments, and local secrets should not be committed to GitHub.

## Tests and continuous integration

Run the unit tests locally with:

```bash
uv run python -m unittest discover -s tests -v
```

The GitHub Actions workflow in `.github/workflows/ci.yml` installs Python and `uv`, synchronizes dependencies using `uv.lock`, runs the offline unit tests, and checks Python syntax.

CI does not perform a full EGX market-data download. This keeps automated tests independent of external data availability and rate limits.

## Limitations and responsible use

- **Incomplete coverage:** The public screener and free price providers may not cover every currently listed EGX security. Always inspect the coverage report.
- **Unofficial data interfaces:** External endpoints can change, return incomplete data, impose rate limits, or become unavailable.
- **Corporate actions:** Splits, rights issues, dividends, and other events can affect price series and calculated chart patterns. Check unusual price moves against a reliable chart.
- **Pivot approximation:** The selected pivot is algorithmic and may not match a human analyst's preferred resistance level.
- **Heuristic scoring:** The weights and thresholds are starting hypotheses. The score is not a probability and has not been established as a predictor of profitable trades.
- **No validated walk-forward backtest:** Historical success rates, drawdowns, and post-breakout returns need systematic testing before the score can be considered useful for investment decisions.
- **Trading costs and liquidity:** Fees, slippage, liquidity constraints, daily price limits, and execution timing are not included in the pattern score.
- **Data redistribution:** This repository does not distribute downloaded market-price histories. Check the providers' terms before redistributing data or using it commercially.

This project is intended for research, learning, and candidate discovery. It does not place orders and should not be treated as financial advice.

## License

This project is distributed under the MIT License. See [`LICENSE`](LICENSE).

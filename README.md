# Alpaca Data Connector

This project provides a small Python module `data_connector.py` that:

- Loads Alpaca API keys from environment variables
- Downloads historical bars via Alpaca Market Data REST API (auto-paginated)
- Streams realtime quotes and trades (bid/ask/last trade) via Alpaca websocket market data stream

`app.py` is a Streamlit UI built on top of the connector with two tabs:

- **Historical Viewer** — pick a ticker, timeframe (1Min/5Min), and lookback window, then see an
  OHLC candlestick chart with a volume bar chart below it.
- **Real-Time Quotes** — type a ticker, click "Start streaming", and watch live bid, ask, and last
  trade price update automatically (polls a background websocket thread once per second).

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Provide your Alpaca credentials. The app loads them automatically from a `.env`
file in the project root (via `python-dotenv`). Create one:

```bash
# .env  (this file is gitignored — never commit it)
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
```

Supported variables:

- `ALPACA_API_KEY` — your Alpaca API key (required)
- `ALPACA_SECRET_KEY` — your Alpaca secret key (required)
- `ALPACA_BASE_URL` — override the default data endpoint (optional)
- `ALPACA_DATA_STREAM` — choose `iex` or `sip` (optional, default: `iex`)

> A free Alpaca plan can only query the `iex` feed for recent data; the `sip`
> feed requires a paid subscription.

Alternatively, you can set the variables in your shell with `export` instead of
using a `.env` file.

## Run

Run the CLI example:

```bash
python homework1.py
```

Run the Streamlit UI:

```bash
streamlit run app.py
```

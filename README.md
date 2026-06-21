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

Required environment variables:

- `ALPACA_API_KEY` — your Alpaca API key
- `ALPACA_SECRET_KEY` — your Alpaca secret key
- Optional: `ALPACA_BASE_URL` to override the default data endpoint
- Optional: `ALPACA_DATA_STREAM` to choose `iex` or `sip` (default: `iex`)

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the CLI example:

```bash
export ALPACA_API_KEY=your_key_here
export ALPACA_SECRET_KEY=your_secret_here
python homework1.py
```

Run the Streamlit UI:

```bash
export ALPACA_API_KEY=your_key_here
export ALPACA_SECRET_KEY=your_secret_here
streamlit run app.py
```

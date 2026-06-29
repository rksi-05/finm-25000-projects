# Technical Indicators & Strategy Backtesting with Alpaca

This project is a Streamlit backtesting platform that downloads historical market data from Alpaca, calculates technical indicators, compares multiple long-only strategies, and generates charts plus a final report.

## Features

- Downloads at least 5 years of daily OHLCV data from Alpaca
- Lets the user select common tickers such as AAPL, MSFT, SPY, QQQ, and NVDA or enter a custom ticker
- Stores historical bars in a Pandas DataFrame
- Calculates 10 technical indicators across trend, momentum, volatility, and volume
- Backtests Buy & Hold plus three strategies:
  - Trend Following
  - Mean Reversion
  - Custom Strategy
- Uses a reusable long-only backtesting engine with $100,000 initial capital, no leverage, and no short selling
- Tracks portfolio value, daily returns, and trades executed
- Calculates Total Return, CAGR, Volatility, Sharpe Ratio, Sortino Ratio, Maximum Drawdown, Win Rate, and trade count
- Displays price charts with indicators and buy/sell signals, equity curves, and drawdown comparisons
- Produces downloadable Markdown and PDF final reports
- Keeps the original real-time Alpaca quote streamer

## Indicators

Trend:
- SMA
- EMA
- MACD
- ADX

Momentum:
- RSI
- Stochastic Oscillator
- Williams %R

Volatility:
- Bollinger Bands
- ATR

Volume:
- OBV
- Chaikin Money Flow

## Strategy Rules

Trend Following:
- Buy when MACD is above signal, ADX is above 25, and SMA 20 is above SMA 50
- Sell when those trend conditions are no longer met

Mean Reversion:
- Buy when RSI is below 30 or price is below the lower Bollinger Band
- Sell when RSI is above 70 or price is above the upper Bollinger Band

Custom Strategy:
- Combines trend, momentum, volatility, and volume
- Buy/hold when SMA 20 is above SMA 50, RSI is between 45 and 70, CMF is positive, and price is above the lower Bollinger Band
- Exit when those combined conditions are no longer met

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```bash
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
ALPACA_DATA_STREAM=iex
```

Supported environment variables:

- `ALPACA_API_KEY` or `APCA_API_KEY_ID`
- `ALPACA_SECRET_KEY` or `APCA_API_SECRET`
- `ALPACA_BASE_URL`, optional, defaults to `https://data.alpaca.markets`
- `ALPACA_DATA_STREAM`, optional, defaults to `iex`

## Run

```bash
streamlit run app.py
```

The main Backtesting tab covers the assignment workflow. The Indicators tab summarizes the implemented indicator set. The Real-Time Quotes tab streams live bid, ask, and last trade data.

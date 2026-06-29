import asyncio
from io import BytesIO
import threading
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from data_connector import AlpacaDataConnector

load_dotenv()

INITIAL_CAPITAL = 100_000
TRADING_DAYS = 252

st.set_page_config(page_title="Alpaca Strategy Backtester", layout="wide")


@st.cache_resource
def get_connector():
    return AlpacaDataConnector()


@st.cache_data(show_spinner=False)
def load_daily_bars(symbol: str, years: int, feed: str) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(years * 365.25) + 10)
    df = get_connector().get_historical(
        symbol=symbol,
        start=start,
        end=end,
        timeframe="1Day",
        feed=feed,
        limit=10_000,
    )
    return normalize_bars(df)


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.sort_index()
    columns = ["open", "high", "low", "close", "volume"]
    return df[[c for c in columns if c in df.columns]].dropna()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    close = data["close"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]

    data["sma_20"] = close.rolling(20).mean()
    data["sma_50"] = close.rolling(50).mean()
    data["ema_12"] = close.ewm(span=12, adjust=False).mean()
    data["ema_26"] = close.ewm(span=26, adjust=False).mean()
    data["macd"] = data["ema_12"] - data["ema_26"]
    data["macd_signal"] = data["macd"].ewm(span=9, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    data["rsi"] = 100 - (100 / (1 + rs))

    low_14 = low.rolling(14).min()
    high_14 = high.rolling(14).max()
    data["stoch_k"] = 100 * (close - low_14) / (high_14 - low_14)
    data["stoch_d"] = data["stoch_k"].rolling(3).mean()
    data["williams_r"] = -100 * (high_14 - close) / (high_14 - low_14)

    sma_20 = data["sma_20"]
    std_20 = close.rolling(20).std()
    data["bb_upper"] = sma_20 + 2 * std_20
    data["bb_lower"] = sma_20 - 2 * std_20

    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    data["atr"] = tr.rolling(14).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_14 = tr.rolling(14).sum()
    plus_di = 100 * pd.Series(plus_dm, index=data.index).rolling(14).sum() / atr_14
    minus_di = 100 * pd.Series(minus_dm, index=data.index).rolling(14).sum() / atr_14
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    data["adx"] = dx.rolling(14).mean()

    data["obv"] = (np.sign(close.diff()).fillna(0) * volume).cumsum()
    money_flow_multiplier = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    money_flow_volume = money_flow_multiplier * volume
    data["cmf"] = money_flow_volume.rolling(20).sum() / volume.rolling(20).sum()

    return data


def build_strategy_signals(data: pd.DataFrame) -> dict[str, pd.Series]:
    trend = (
        (data["macd"] > data["macd_signal"])
        & (data["adx"] > 25)
        & (data["sma_20"] > data["sma_50"])
    ).astype(int)

    mean_buy = (data["rsi"] < 30) | (data["close"] < data["bb_lower"])
    mean_sell = (data["rsi"] > 70) | (data["close"] > data["bb_upper"])
    mean_reversion = stateful_position(mean_buy, mean_sell).rename("Mean Reversion")

    custom = (
        (data["sma_20"] > data["sma_50"])
        & (data["rsi"].between(45, 70))
        & (data["cmf"] > 0)
        & (data["close"] > data["bb_lower"])
    ).astype(int)

    buy_hold = pd.Series(1, index=data.index, name="Buy & Hold")
    return {
        "Buy & Hold": buy_hold,
        "Trend Following": trend.rename("Trend Following"),
        "Mean Reversion": mean_reversion,
        "Custom Strategy": custom.rename("Custom Strategy"),
    }


def stateful_position(buy_signal: pd.Series, sell_signal: pd.Series) -> pd.Series:
    position = []
    invested = 0
    for buy, sell in zip(buy_signal.fillna(False), sell_signal.fillna(False)):
        if sell:
            invested = 0
        elif buy:
            invested = 1
        position.append(invested)
    return pd.Series(position, index=buy_signal.index, dtype=int)


def run_backtest(df: pd.DataFrame, position: pd.Series) -> dict:
    data = df.copy()
    aligned_position = position.reindex(data.index).fillna(0).shift(1).fillna(0)
    daily_returns = data["close"].pct_change().fillna(0)
    strategy_returns = daily_returns * aligned_position
    equity = INITIAL_CAPITAL * (1 + strategy_returns).cumprod()
    trades = aligned_position.diff().abs().fillna(0)
    drawdown = equity / equity.cummax() - 1

    return {
        "position": aligned_position,
        "returns": strategy_returns,
        "equity": equity,
        "drawdown": drawdown,
        "trades": trades,
    }


def calculate_metrics(result: dict) -> dict:
    returns = result["returns"]
    equity = result["equity"]
    total_return = equity.iloc[-1] / INITIAL_CAPITAL - 1
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 365.25)
    cagr = (equity.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    volatility = returns.std() * np.sqrt(TRADING_DAYS)
    sharpe = (returns.mean() * TRADING_DAYS) / volatility if volatility else np.nan
    downside = returns[returns < 0].std() * np.sqrt(TRADING_DAYS)
    sortino = (returns.mean() * TRADING_DAYS) / downside if downside else np.nan
    max_drawdown = result["drawdown"].min()
    invested_returns = returns[result["position"] > 0]
    win_rate = (invested_returns > 0).mean() if not invested_returns.empty else np.nan

    return {
        "Total Return": total_return,
        "CAGR": cagr,
        "Volatility": volatility,
        "Sharpe Ratio": sharpe,
        "Sortino Ratio": sortino,
        "Maximum Drawdown": max_drawdown,
        "Win Rate": win_rate,
        "Trades": int(result["trades"].sum()),
    }


def format_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    formatted = metrics.copy()
    pct_cols = ["Total Return", "CAGR", "Volatility", "Maximum Drawdown", "Win Rate"]
    for col in pct_cols:
        formatted[col] = formatted[col].map(lambda x: "N/A" if pd.isna(x) else f"{x:.2%}")
    for col in ["Sharpe Ratio", "Sortino Ratio"]:
        formatted[col] = formatted[col].map(lambda x: "N/A" if pd.isna(x) else f"{x:.2f}")
    formatted["Trades"] = formatted["Trades"].astype(int)
    return formatted


def make_price_chart(data: pd.DataFrame, signals: pd.Series, strategy_name: str, symbol: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=data.index,
        open=data["open"],
        high=data["high"],
        low=data["low"],
        close=data["close"],
        name="Price",
    ))
    fig.add_trace(go.Scatter(x=data.index, y=data["sma_20"], name="SMA 20", line=dict(width=1.3)))
    fig.add_trace(go.Scatter(x=data.index, y=data["sma_50"], name="SMA 50", line=dict(width=1.3)))
    fig.add_trace(go.Scatter(x=data.index, y=data["bb_upper"], name="Upper BB", line=dict(width=1, dash="dot")))
    fig.add_trace(go.Scatter(x=data.index, y=data["bb_lower"], name="Lower BB", line=dict(width=1, dash="dot")))

    entries = signals.diff().fillna(0) > 0
    exits = signals.diff().fillna(0) < 0
    fig.add_trace(go.Scatter(
        x=data.index[entries],
        y=data.loc[entries, "close"],
        mode="markers",
        name="Buy",
        marker=dict(symbol="triangle-up", size=11, color="#1f9d55"),
    ))
    fig.add_trace(go.Scatter(
        x=data.index[exits],
        y=data.loc[exits, "close"],
        mode="markers",
        name="Sell",
        marker=dict(symbol="triangle-down", size=11, color="#d64545"),
    ))
    fig.update_layout(
        title=f"{symbol} Price, Indicators, and {strategy_name} Signals",
        height=560,
        xaxis_rangeslider_visible=False,
        legend_orientation="h",
    )
    return fig


def make_equity_chart(results: dict[str, dict]) -> go.Figure:
    fig = go.Figure()
    for name, result in results.items():
        fig.add_trace(go.Scatter(x=result["equity"].index, y=result["equity"], name=name))
    fig.update_layout(title="Equity Curve Comparison", height=450, yaxis_title="Portfolio Value ($)")
    return fig


def make_drawdown_chart(results: dict[str, dict]) -> go.Figure:
    fig = go.Figure()
    for name, result in results.items():
        fig.add_trace(go.Scatter(
            x=result["drawdown"].index,
            y=result["drawdown"],
            name=name,
            fill="tozeroy",
        ))
    fig.update_layout(title="Drawdown Comparison", height=420, yaxis_tickformat=".0%")
    return fig


def build_report(symbol: str, years: int, best_name: str, metrics: pd.DataFrame) -> str:
    table = format_metrics(metrics).to_markdown()
    return f"""# Technical Indicators & Strategy Backtesting with Alpaca

## Objective
This report evaluates multiple long-only algorithmic trading strategies for {symbol} using daily OHLCV data from Alpaca over approximately {years} years.

## Strategies
- Buy & Hold: continuously invested benchmark.
- Trend Following: buys when MACD is above signal, ADX is above 25, and SMA 20 is above SMA 50.
- Mean Reversion: buys when RSI is below 30 or price falls below the lower Bollinger Band, and exits when RSI exceeds 70 or price rises above the upper Bollinger Band.
- Custom Strategy: combines trend, momentum, volatility, and volume by requiring SMA 20 above SMA 50, RSI between 45 and 70, positive CMF, and price above the lower Bollinger Band.

## Performance Comparison
{table}

## Discussion
The best risk-adjusted strategy by Sharpe Ratio is **{best_name}**. Review the price, equity, and drawdown charts in the Streamlit app before making conclusions because a high Sharpe Ratio can still coincide with low market exposure, few trades, or sensitivity to the selected ticker and date range.
"""


def build_pdf_report(symbol: str, years: int, best_name: str, metrics: pd.DataFrame) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    formatted = format_metrics(metrics).reset_index().rename(columns={"index": "Strategy"})

    story = [
        Paragraph("Technical Indicators & Strategy Backtesting with Alpaca", styles["Title"]),
        Spacer(1, 12),
        Paragraph(
            f"This report evaluates long-only algorithmic trading strategies for {symbol} "
            f"using approximately {years} years of daily OHLCV data from Alpaca.",
            styles["BodyText"],
        ),
        Spacer(1, 12),
        Paragraph("Strategy Descriptions and Rules", styles["Heading2"]),
        Paragraph("Buy & Hold: continuously invested benchmark.", styles["BodyText"]),
        Paragraph("Trend Following: MACD above signal, ADX above 25, and SMA 20 above SMA 50.", styles["BodyText"]),
        Paragraph("Mean Reversion: buy on RSI below 30 or price below lower Bollinger Band; sell on RSI above 70 or price above upper Bollinger Band.", styles["BodyText"]),
        Paragraph("Custom Strategy: combines trend, momentum, volatility, and volume using SMA, RSI, Bollinger Bands, and CMF.", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Performance Comparison", styles["Heading2"]),
    ]

    table_data = [formatted.columns.tolist()] + formatted.values.tolist()
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.extend([
        table,
        Spacer(1, 12),
        Paragraph("Discussion of Results", styles["Heading2"]),
        Paragraph(
            f"The best risk-adjusted strategy by Sharpe Ratio is {best_name}. "
            "Review the app charts before drawing final conclusions because performance can depend on ticker, time period, and trade frequency.",
            styles["BodyText"],
        ),
    ])

    doc.build(story)
    return buffer.getvalue()


class QuoteStreamer:
    """Runs the websocket stream on a background thread and exposes a thread-safe snapshot."""

    def __init__(self, connector: AlpacaDataConnector, symbol: str):
        self.connector = connector
        self.symbol = symbol
        self._lock = threading.Lock()
        self._latest = {"symbol": symbol, "bid": None, "ask": None, "last_trade": None}
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _on_message(self, msg):
        with self._lock:
            if msg["type"] == "trade":
                self._latest["last_trade"] = msg["price"]
            else:
                if msg["bid"] is not None:
                    self._latest["bid"] = msg["bid"]
                if msg["ask"] is not None:
                    self._latest["ask"] = msg["ask"]

    def _run(self):
        asyncio.run(self.connector.stream_market_data(
            self.symbol, on_message=self._on_message, stop_event=self._stop_event
        ))

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._latest)

    def stop(self):
        self._stop_event.set()


def render_backtesting_tab():
    st.header("Strategy Backtesting Platform")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        symbol = st.selectbox("Ticker", ["AAPL", "MSFT", "SPY", "QQQ", "NVDA"], index=2)
        custom_symbol = st.text_input("Or enter another ticker", "")
        symbol = (custom_symbol or symbol).strip().upper()
    with c2:
        years = st.slider("Years of daily data", min_value=5, max_value=10, value=5)
    with c3:
        feed = st.selectbox("Alpaca feed", ["iex", "sip"], index=0)

    run_clicked = st.button("Run backtest", type="primary")
    if not run_clicked and "backtest_data" not in st.session_state:
        st.info("Choose a ticker and run the backtest to compare Buy & Hold plus three indicator strategies.")
        return

    if run_clicked:
        try:
            with st.spinner(f"Downloading {years}+ years of daily {symbol} bars from Alpaca..."):
                raw = load_daily_bars(symbol, years, feed)
            if raw.empty or len(raw) < TRADING_DAYS:
                st.warning("Alpaca returned too little data for a reliable backtest. Try a different ticker or feed.")
                return
            data = compute_indicators(raw).dropna()
            signals = build_strategy_signals(data)
            results = {name: run_backtest(data, signal) for name, signal in signals.items()}
            metrics = pd.DataFrame({name: calculate_metrics(result) for name, result in results.items()}).T
            st.session_state["backtest_data"] = data
            st.session_state["backtest_signals"] = signals
            st.session_state["backtest_results"] = results
            st.session_state["backtest_metrics"] = metrics
            st.session_state["backtest_symbol"] = symbol
            st.session_state["backtest_years"] = years
        except Exception as exc:
            st.error(f"Could not run backtest: {exc}")
            return

    data = st.session_state["backtest_data"]
    signals = st.session_state["backtest_signals"]
    results = st.session_state["backtest_results"]
    metrics = st.session_state["backtest_metrics"]
    symbol = st.session_state["backtest_symbol"]
    years = st.session_state["backtest_years"]

    best_name = metrics["Sharpe Ratio"].astype(float).idxmax()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Bars", f"{len(data):,}")
    k2.metric("Best Sharpe Strategy", best_name)
    k3.metric("Best Sharpe", f"{metrics.loc[best_name, 'Sharpe Ratio']:.2f}")
    k4.metric("Initial Capital", f"${INITIAL_CAPITAL:,.0f}")

    st.subheader("Performance Metrics")
    st.dataframe(format_metrics(metrics), width="stretch")

    st.subheader("Visualizations")
    selected_strategy = st.selectbox(
        "Price chart strategy signals",
        ["Trend Following", "Mean Reversion", "Custom Strategy"],
    )
    st.plotly_chart(
        make_price_chart(data, signals[selected_strategy], selected_strategy, symbol),
        width="stretch",
    )
    st.plotly_chart(make_equity_chart(results), width="stretch")
    st.plotly_chart(make_drawdown_chart(results), width="stretch")

    st.subheader("Final Report")
    report = build_report(symbol, years, best_name, metrics)
    st.markdown(report)
    st.download_button(
        "Download final report (Markdown)",
        data=report,
        file_name=f"{symbol.lower()}_strategy_backtest_report.md",
        mime="text/markdown",
    )
    st.download_button(
        "Download final report (PDF)",
        data=build_pdf_report(symbol, years, best_name, metrics),
        file_name=f"{symbol.lower()}_strategy_backtest_report.pdf",
        mime="application/pdf",
    )


def render_indicators_tab():
    st.header("Implemented Technical Indicators")
    st.write("The app calculates ten indicators across trend, momentum, volatility, and volume categories.")
    st.dataframe(pd.DataFrame(
        [
            ("Trend", "SMA 20 / SMA 50"),
            ("Trend", "EMA 12 / EMA 26"),
            ("Trend", "MACD and Signal"),
            ("Trend", "ADX"),
            ("Momentum", "RSI"),
            ("Momentum", "Stochastic Oscillator"),
            ("Momentum", "Williams %R"),
            ("Volatility", "Bollinger Bands"),
            ("Volatility", "ATR"),
            ("Volume", "OBV and Chaikin Money Flow"),
        ],
        columns=["Category", "Indicator"],
    ), width="stretch", hide_index=True)


def render_realtime_tab():
    st.header("Real-Time Quotes")

    symbol = st.text_input("Ticker", value="AAPL", key="rt_symbol").strip().upper()
    col1, col2 = st.columns(2)
    start_clicked = col1.button("Start streaming", key="rt_start")
    stop_clicked = col2.button("Stop streaming", key="rt_stop")

    streamer: QuoteStreamer = st.session_state.get("streamer")

    if start_clicked:
        if streamer is not None:
            streamer.stop()
        try:
            st.session_state["streamer"] = QuoteStreamer(get_connector(), symbol)
            streamer = st.session_state["streamer"]
        except Exception as exc:
            st.error(f"Could not start stream: {exc}")
            return

    if stop_clicked and streamer is not None:
        streamer.stop()
        st.session_state["streamer"] = None
        streamer = None

    if streamer is None:
        st.info("Enter a ticker and click Start streaming to see live bid, ask, and last trade.")
        return

    render_quote_panel(streamer)


@st.fragment(run_every=1)
def render_quote_panel(streamer: QuoteStreamer):
    quote = streamer.snapshot()
    c1, c2, c3 = st.columns(3)
    c1.metric("Bid", f"{quote['bid']:.2f}" if quote["bid"] is not None else "N/A")
    c2.metric("Ask", f"{quote['ask']:.2f}" if quote["ask"] is not None else "N/A")
    c3.metric("Last trade", f"{quote['last_trade']:.2f}" if quote["last_trade"] is not None else "N/A")
    st.caption(f"Streaming {quote['symbol']}")


def main():
    st.title("Technical Indicators & Strategy Backtesting with Alpaca")
    st.caption("Long-only, no leverage, no short selling. Initial capital: $100,000.")
    tab1, tab2, tab3 = st.tabs(["Backtesting", "Indicators", "Real-Time Quotes"])
    with tab1:
        render_backtesting_tab()
    with tab2:
        render_indicators_tab()
    with tab3:
        render_realtime_tab()


if __name__ == "__main__":
    main()

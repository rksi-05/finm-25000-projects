import threading
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from data_connector import AlpacaDataConnector

load_dotenv()

st.set_page_config(page_title="Alpaca Market Data", layout="wide")


@st.cache_resource
def get_connector():
    return AlpacaDataConnector()


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
        import asyncio
        asyncio.run(self.connector.stream_market_data(
            self.symbol, on_message=self._on_message, stop_event=self._stop_event
        ))

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._latest)

    def stop(self):
        self._stop_event.set()


def render_historical_tab():
    st.header("Historical Data Viewer")

    col1, col2, col3 = st.columns(3)
    with col1:
        symbol = st.text_input("Symbol", value="AAPL", key="hist_symbol").strip().upper()
    with col2:
        timeframe = st.selectbox("Timeframe", ["1Min", "5Min"], key="hist_timeframe")
    with col3:
        days = st.number_input("Days of history", min_value=1, max_value=90, value=30, key="hist_days")

    if st.button("Load chart", key="hist_load"):
        connector = get_connector()
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        with st.spinner(f"Downloading {timeframe} bars for {symbol}..."):
            df = connector.get_historical(symbol, start=start, end=end, timeframe=timeframe)

        if df.empty:
            st.warning("No bars returned for this symbol/range.")
            return

        st.session_state["hist_df"] = df
        st.session_state["hist_df_symbol"] = symbol

    df = st.session_state.get("hist_df")
    if df is None:
        return

    symbol = st.session_state.get("hist_df_symbol", symbol)
    st.caption(f"{len(df)} bars for {symbol}")

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="OHLC",
    ))
    fig.update_layout(title=f"{symbol} price", xaxis_rangeslider_visible=False, height=450)
    st.plotly_chart(fig, use_container_width=True)

    vol_fig = go.Figure()
    vol_fig.add_trace(go.Bar(x=df.index, y=df["volume"], name="Volume"))
    vol_fig.update_layout(title=f"{symbol} volume", height=200)
    st.plotly_chart(vol_fig, use_container_width=True)

    st.dataframe(df[["open", "high", "low", "close", "volume"]])


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
        st.session_state["streamer"] = QuoteStreamer(get_connector(), symbol)
        streamer = st.session_state["streamer"]

    if stop_clicked and streamer is not None:
        streamer.stop()
        st.session_state["streamer"] = None
        streamer = None

    if streamer is None:
        st.info("Enter a ticker and click 'Start streaming' to see live bid/ask/last trade.")
        return

    render_quote_panel(streamer)


@st.fragment(run_every=1)
def render_quote_panel(streamer: QuoteStreamer):
    quote = streamer.snapshot()
    c1, c2, c3 = st.columns(3)
    c1.metric("Bid", f"{quote['bid']:.2f}" if quote["bid"] is not None else "—")
    c2.metric("Ask", f"{quote['ask']:.2f}" if quote["ask"] is not None else "—")
    c3.metric("Last trade", f"{quote['last_trade']:.2f}" if quote["last_trade"] is not None else "—")
    st.caption(f"Streaming {quote['symbol']}")


def main():
    st.title("Alpaca Market Data")
    tab1, tab2 = st.tabs(["Historical Viewer", "Real-Time Quotes"])
    with tab1:
        render_historical_tab()
    with tab2:
        render_realtime_tab()


if __name__ == "__main__":
    main()

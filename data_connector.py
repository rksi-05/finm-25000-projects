import os
import asyncio
import json
from datetime import datetime
from typing import Callable, Optional, Any

import requests
import pandas as pd
import websockets


class AlpacaDataConnector:
    """Simple Alpaca Market Data connector.

    Loads credentials from environment variables (or accepts them directly).
    Provides methods to fetch historical bars and to stream realtime quotes.
    """

    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None,
                 base_url: Optional[str] = None, data_stream: str = "iex"):
        self.api_key = api_key or os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET")
        self.base_url = base_url or os.getenv("ALPACA_BASE_URL", "https://data.alpaca.markets")
        self.data_stream = os.getenv("ALPACA_DATA_STREAM", data_stream)

        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API key and secret must be provided via env vars or constructor")

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    def get_historical(self, symbol: str, start: Optional[Any] = None, end: Optional[Any] = None,
                       timeframe: str = "1Min", limit: int = 10000) -> pd.DataFrame:
        """Download historical bars for `symbol`.

        start/end can be ISO strings or datetime objects. Pages through Alpaca's
        `next_page_token` automatically so multi-week intraday ranges come back complete.
        Returns a pandas DataFrame indexed by timestamp (column name 't'), with
        OHLCV columns renamed to open/high/low/close/volume.
        """
        url = f"{self.base_url}/v2/stocks/{symbol}/bars"
        params = {"timeframe": timeframe, "limit": limit}
        if start:
            params["start"] = start.isoformat() if isinstance(start, datetime) else str(start)
        if end:
            params["end"] = end.isoformat() if isinstance(end, datetime) else str(end)

        all_bars = []
        page_token = None
        while True:
            if page_token:
                params["page_token"] = page_token

            resp = requests.get(url, headers=self._headers(), params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()

            if isinstance(payload, dict):
                bars = payload.get("bars")
                if isinstance(bars, list):
                    all_bars.extend(bars)
                elif bars is None and "bars" in payload:
                    pass  # valid response, just no data in this window
                elif {"t", "o", "h", "l", "c"} & set(payload.keys()):
                    all_bars.append(payload)  # single-bar shape
                else:
                    raise RuntimeError(f"Unexpected response from Alpaca: {payload}")
                page_token = payload.get("next_page_token")
            elif isinstance(payload, list):
                all_bars.extend(payload)
                page_token = None
            else:
                raise RuntimeError(f"Unexpected response type from Alpaca: {type(payload)}")

            if not page_token:
                break

        df = pd.DataFrame(all_bars)
        if not df.empty and "t" in df.columns:
            df["t"] = pd.to_datetime(df["t"])
            df = df.set_index("t")
            df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})

        return df

    async def stream_quotes(self, symbol: str, on_quote: Optional[Callable[[dict], None]] = None):
        """Asynchronously stream realtime quotes for `symbol` and call `on_quote` for each update.

        The method prints incoming messages and attempts to extract bid/ask when present.
        """
        ws_url = f"wss://stream.data.alpaca.markets/v2/{self.data_stream}"
        async with websockets.connect(ws_url) as ws:
            # Authenticate
            auth_msg = {"action": "auth", "key": self.api_key, "secret": self.secret_key}
            await ws.send(json.dumps(auth_msg))
            try:
                auth_resp = await ws.recv()
            except Exception:
                auth_resp = None
            # Subscribe to quotes for the symbol
            sub_msg = {"action": "subscribe", "quotes": [symbol]}
            await ws.send(json.dumps(sub_msg))

            while True:
                msg = await ws.recv()
                try:
                    data = json.loads(msg)
                except Exception:
                    # Non-JSON message; skip
                    continue

                # Alpaca often sends a list of messages
                messages = data if isinstance(data, list) else [data]
                for m in messages:
                    # Try common fields for symbol/bid/ask across different message formats
                    sym = m.get("S") or m.get("symbol") or m.get("s")
                    bid = m.get("b") or m.get("bp") or m.get("bid")
                    ask = m.get("a") or m.get("ap") or m.get("ask")

                    quote = {"symbol": sym, "bid": bid, "ask": ask, "raw": m}
                    if on_quote:
                        try:
                            on_quote(quote)
                        except Exception:
                            # ensure streaming continues even if callback fails
                            pass
                    else:
                        print(quote)

    async def stream_market_data(self, symbol: str, on_message: Optional[Callable[[dict], None]] = None,
                                  stop_event: Optional["Any"] = None):
        """Stream both quotes and trades for `symbol`, calling `on_message` for each update.

        Each message passed to `on_message` is normalized to:
            {"type": "quote"|"trade", "symbol": str, "bid": float|None, "ask": float|None,
             "price": float|None, "raw": dict}

        `stop_event` (a `threading.Event`) can be set from another thread to stop the loop,
        which is useful when this coroutine is driven from a background thread for a UI.
        """
        ws_url = f"wss://stream.data.alpaca.markets/v2/{self.data_stream}"
        async with websockets.connect(ws_url) as ws:
            auth_msg = {"action": "auth", "key": self.api_key, "secret": self.secret_key}
            await ws.send(json.dumps(auth_msg))
            try:
                await ws.recv()
            except Exception:
                pass

            sub_msg = {"action": "subscribe", "quotes": [symbol], "trades": [symbol]}
            await ws.send(json.dumps(sub_msg))

            while stop_event is None or not stop_event.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                try:
                    data = json.loads(msg)
                except Exception:
                    continue

                messages = data if isinstance(data, list) else [data]
                for m in messages:
                    msg_type = m.get("T")
                    sym = m.get("S") or m.get("symbol") or m.get("s")

                    if msg_type == "t":
                        normalized = {"type": "trade", "symbol": sym, "bid": None, "ask": None,
                                      "price": m.get("p"), "raw": m}
                    elif msg_type == "q":
                        normalized = {"type": "quote", "symbol": sym, "bid": m.get("bp"),
                                      "ask": m.get("ap"), "price": None, "raw": m}
                    else:
                        # Unhandled message type (e.g. subscription ack); skip
                        continue

                    if on_message:
                        try:
                            on_message(normalized)
                        except Exception:
                            # ensure streaming continues even if callback fails
                            pass
                    else:
                        print(normalized)

    def start_stream(self, symbol: str, on_quote: Optional[Callable[[dict], None]] = None,
                     run_seconds: Optional[int] = None):
        """Start the async stream and optionally stop after `run_seconds` seconds."""

        async def _runner():
            task = asyncio.create_task(self.stream_quotes(symbol, on_quote))
            if run_seconds:
                try:
                    await asyncio.sleep(run_seconds)
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            else:
                await task

        asyncio.run(_runner())


__all__ = ["AlpacaDataConnector"]

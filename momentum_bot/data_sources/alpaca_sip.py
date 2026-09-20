"""
Alpaca real-time SIP market data (WebSocket).

Stream URL: wss://stream.data.alpaca.markets/v2/sip
Requires Alpaca API key + Algo Trader Plus (~$99/mo). Live-only —
never used for historical training / backtests.

On disconnect/error the factory falls back to the free yfinance source.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

import pandas as pd

from .base import LatestQuote, LatestTrade, MarketDataSource
from .yfinance_source import YFinanceSource

logger = logging.getLogger(__name__)

SIP_WS_URL = "wss://stream.data.alpaca.markets/v2/sip"
IEX_WS_URL = "wss://stream.data.alpaca.markets/v2/iex"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alpaca_symbol(ticker: str) -> str:
    """yfinance BRK-B → Alpaca BRK.B"""
    return ticker.upper().replace("-", ".")


def _yf_symbol(symbol: str) -> str:
    return symbol.upper().replace(".", "-")


class AlpacaSIPSource(MarketDataSource):
    """
    Real-time SIP trades/quotes via Alpaca WebSocket.

    Historical OHLCV for lookbacks still comes from the free source; the
    latest bar Close/Volume is overlaid from the live trade cache so
    live signal generation and forward-estimate see current prices.
    """

    name = "alpaca_sip"
    is_realtime = True

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        *,
        on_error: Optional[Callable[[str], None]] = None,
        history_source: Optional[MarketDataSource] = None,
        ws_url: str = SIP_WS_URL,
    ) -> None:
        self.api_key = api_key or os.environ.get("ALPACA_DATA_KEY") or os.environ.get("ALPACA_API_KEY", "")
        self.api_secret = (
            api_secret
            or os.environ.get("ALPACA_DATA_SECRET")
            or os.environ.get("ALPACA_API_SECRET", "")
        )
        self.ws_url = ws_url
        self._history = history_source or YFinanceSource()
        self._on_error = on_error

        self._trades: Dict[str, LatestTrade] = {}
        self._quotes: Dict[str, LatestQuote] = {}
        self._subscribed: Set[str] = set()
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False
        self._last_error: Optional[str] = None
        self._auth_ok = False
        self._ws = None  # active websocket (set in thread)
        self._last_tick_at: Optional[float] = None  # monotonic time of last trade/quote
        self._last_tick_ts: Optional[str] = None
        self._feed: str = "sip" if "sip" in (ws_url or "").lower() else ("iex" if "iex" in (ws_url or "").lower() else "sip")

        if not self.api_key or not self.api_secret:
            raise RuntimeError(
                "Alpaca data credentials missing. Set ALPACA_API_KEY + ALPACA_API_SECRET "
                "(or ALPACA_DATA_KEY / ALPACA_DATA_SECRET). Requires Algo Trader Plus for SIP."
            )

    # ---- MarketDataSource ----

    def download_ohlcv(
        self,
        tickers: List[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: Optional[str] = None,
        batch_size: int = 50,
        auto_adjust: bool = True,
        **kwargs: Any,
    ) -> Dict[str, pd.DataFrame]:
        # Ensure stream covers these symbols for live overlay
        try:
            self.start_stream(tickers)
        except Exception as exc:  # noqa: BLE001
            self._fail(f"SIP stream start failed: {exc}")

        frames = self._history.download_ohlcv(
            tickers,
            start=start,
            end=end,
            period=period,
            batch_size=batch_size,
            auto_adjust=auto_adjust,
            **kwargs,
        )
        return self._overlay_live(frames)

    def get_latest_trade(self, ticker: str) -> Optional[LatestTrade]:
        with self._lock:
            return self._trades.get(ticker.upper().replace(".", "-"))

    def get_latest_quote(self, ticker: str) -> Optional[LatestQuote]:
        with self._lock:
            return self._quotes.get(ticker.upper().replace(".", "-"))

    def start_stream(self, tickers: List[str]) -> None:
        syms = [_alpaca_symbol(t) for t in tickers if t]
        if not syms:
            return
        with self._lock:
            new = set(syms) - self._subscribed
            self._subscribed |= set(syms)
        if self._thread and self._thread.is_alive():
            if new and self._connected and self._ws is not None:
                self._send_subscribe(list(new))
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="alpaca-sip-ws", daemon=True)
        self._thread.start()
        # Brief wait for auth
        deadline = time.time() + 8.0
        while time.time() < deadline and not self._auth_ok and not self._last_error:
            time.sleep(0.1)
        if self._last_error and not self._auth_ok:
            raise RuntimeError(self._last_error)

    def stop_stream(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                # Close from worker thread's loop via flag; best-effort
                import asyncio

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(ws.close(), loop)
                except Exception:
                    pass
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None
        self._connected = False
        self._auth_ok = False
        self._ws = None

    def is_connected(self) -> bool:
        return bool(self._connected and self._auth_ok and not self._stop.is_set())

    def status(self) -> Dict[str, Any]:
        import time as _time
        with self._lock:
            n_trades = len(self._trades)
            n_quotes = len(self._quotes)
            n_sub = len(self._subscribed)
            last_at = self._last_tick_at
            last_ts = self._last_tick_ts
        age = None
        if last_at is not None:
            age = round(_time.monotonic() - float(last_at), 2)
        healthy = self.is_connected() and (age is None or age < 120)
        return {
            "name": self.name,
            "is_realtime": True,
            "feed": self._feed,
            "connected": self.is_connected(),
            "connection_health": "ok" if healthy else ("stale" if self.is_connected() else "down"),
            "auth_ok": self._auth_ok,
            "subscribed": n_sub,
            "cached_trades": n_trades,
            "cached_quotes": n_quotes,
            "last_tick_age_sec": age,
            "last_tick_ts": last_ts,
            "last_error": self._last_error,
            "ws_url": self.ws_url,
            "cost_note": (
                "Alpaca Algo Trader Plus ~$99/mo required for SIP"
                if self._feed == "sip"
                else "Alpaca IEX feed (often included with free/data plans) — not full SIP"
            ),
            "not_level2": True,
        }

    # ---- internals ----

    def _fail(self, msg: str) -> None:
        self._last_error = msg
        self._connected = False
        self._auth_ok = False
        logger.warning("[alpaca_sip] %s", msg)
        if self._on_error:
            try:
                self._on_error(msg)
            except Exception:  # noqa: BLE001
                pass

    def _overlay_live(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        out: Dict[str, pd.DataFrame] = {}
        for ticker, df in frames.items():
            if df is None or df.empty:
                continue
            trade = self.get_latest_trade(ticker)
            if trade is None or trade.price <= 0:
                out[ticker] = df
                continue
            patched = df.copy()
            # Update last bar with live trade price; bump volume if size known
            idx = patched.index[-1]
            patched.loc[idx, "Close"] = float(trade.price)
            if "High" in patched.columns:
                patched.loc[idx, "High"] = max(float(patched.loc[idx, "High"]), float(trade.price))
            if "Low" in patched.columns:
                patched.loc[idx, "Low"] = min(float(patched.loc[idx, "Low"]), float(trade.price))
            if trade.size and "Volume" in patched.columns:
                try:
                    patched.loc[idx, "Volume"] = float(patched.loc[idx, "Volume"]) + float(trade.size)
                except Exception:
                    pass
            out[ticker] = patched
        return out

    def _send_subscribe(self, alpaca_symbols: List[str]) -> None:
        ws = self._ws
        if ws is None or not alpaca_symbols:
            return
        msg = {
            "action": "subscribe",
            "trades": alpaca_symbols,
            "quotes": alpaca_symbols,
        }
        try:
            import asyncio

            fut = asyncio.run_coroutine_threadsafe(ws.send(json.dumps(msg)), ws.loop)  # type: ignore[attr-defined]
            fut.result(timeout=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[alpaca_sip] subscribe send failed: %s", exc)

    def _run_loop(self) -> None:
        try:
            import asyncio

            asyncio.run(self._async_main())
        except Exception as exc:  # noqa: BLE001
            self._fail(f"SIP websocket loop crashed: {exc}")

    async def _async_main(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            self._fail(
                "websockets package required for Alpaca SIP "
                "(pip install websockets). Falling back to free source."
            )
            raise RuntimeError(str(exc)) from exc

        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=8 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    # Attach loop for cross-thread subscribe
                    try:
                        ws.loop = asyncio.get_running_loop()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    self._connected = True
                    self._last_error = None
                    await ws.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": self.api_key,
                                "secret": self.api_secret,
                            }
                        )
                    )
                    # Wait for auth response
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    if not self._handle_messages(raw):
                        self._fail("SIP auth rejected or unexpected response")
                        return
                    # Subscribe current set
                    with self._lock:
                        syms = list(self._subscribed)
                    if syms:
                        # Chunk subscriptions (Alpaca limits message size)
                        for i in range(0, len(syms), 100):
                            chunk = syms[i : i + 100]
                            await ws.send(
                                json.dumps(
                                    {
                                        "action": "subscribe",
                                        "trades": chunk,
                                        "quotes": chunk,
                                    }
                                )
                            )
                    backoff = 1.0
                    while not self._stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            # idle — keep connection; ping_interval handles keepalive
                            continue
                        self._handle_messages(raw)
            except Exception as exc:  # noqa: BLE001
                self._connected = False
                self._auth_ok = False
                self._ws = None
                if self._stop.is_set():
                    break
                self._fail(f"SIP disconnect/error: {exc}")
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
            finally:
                self._ws = None
                self._connected = False

    def _handle_messages(self, raw: Any) -> bool:
        """Parse one or more Alpaca stream messages. Returns False on auth failure."""
        try:
            data = json.loads(raw)
        except Exception:
            return True
        if not isinstance(data, list):
            data = [data]
        ok = True
        for msg in data:
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("T") or msg.get("msg") or ""
            if mtype in ("success",) and "authenticated" in str(msg.get("msg", "")).lower():
                self._auth_ok = True
                continue
            if mtype == "success" and str(msg.get("msg", "")).lower() == "connected":
                continue
            if mtype in ("error",) or str(msg.get("msg", "")).lower() in (
                "authentication failed",
                "unauthorized",
            ):
                self._fail(f"SIP error: {msg}")
                ok = False
                continue
            if mtype == "subscription":
                self._auth_ok = True
                continue
            if mtype == "t":  # trade
                self._ingest_trade(msg)
            elif mtype == "q":  # quote
                self._ingest_quote(msg)
        return ok

    def _ingest_trade(self, msg: Dict[str, Any]) -> None:
        sym = _yf_symbol(str(msg.get("S") or ""))
        if not sym:
            return
        try:
            price = float(msg.get("p") or 0)
            size = float(msg.get("s") or 0)
        except (TypeError, ValueError):
            return
        if price <= 0:
            return
        trade = LatestTrade(
            ticker=sym,
            price=price,
            size=size,
            timestamp=str(msg.get("t") or _utc_now()),
            exchange=str(msg.get("x") or ""),
        )
        with self._lock:
            self._trades[sym] = trade
            self._last_tick_at = time.monotonic()
            self._last_tick_ts = trade.timestamp

    def _ingest_quote(self, msg: Dict[str, Any]) -> None:
        sym = _yf_symbol(str(msg.get("S") or ""))
        if not sym:
            return
        try:
            bid = float(msg.get("bp") or 0)
            ask = float(msg.get("ap") or 0)
            bid_size = float(msg.get("bs") or 0)
            ask_size = float(msg.get("as") or 0)
        except (TypeError, ValueError):
            return
        quote = LatestQuote(
            ticker=sym,
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            timestamp=str(msg.get("t") or _utc_now()),
        )
        with self._lock:
            self._quotes[sym] = quote
            self._last_tick_at = time.monotonic()
            self._last_tick_ts = quote.timestamp

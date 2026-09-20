"""
NBBO / top-of-book quote stream (L2-lite).

Best bid/ask/mid/spread/size for watchlist symbols when Alpaca keys (or a
healthy SIP/IEX cache) are available. Explicitly **not** a Level-2 order book
or full depth tape — top-of-book only.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(sym: str) -> str:
    return str(sym or "").strip().upper().replace(".", "-")


def _alpaca_sym(sym: str) -> str:
    return _norm(sym).replace("-", ".")


def _keys() -> tuple[str, str]:
    key = os.environ.get("ALPACA_DATA_KEY") or os.environ.get("ALPACA_API_KEY") or ""
    secret = (
        os.environ.get("ALPACA_DATA_SECRET")
        or os.environ.get("ALPACA_API_SECRET")
        or ""
    )
    return key.strip(), secret.strip()


def _enrich(row: Dict[str, Any]) -> Dict[str, Any]:
    bid = row.get("bid")
    ask = row.get("ask")
    mid = row.get("mid")
    spread = row.get("spread")
    try:
        b = float(bid) if bid is not None else None
        a = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        b, a = None, None
    if b is not None and a is not None and b > 0 and a > 0:
        if mid is None:
            mid = round((b + a) / 2.0, 6)
        if spread is None:
            spread = round(a - b, 6)
        row["bid"] = b
        row["ask"] = a
        row["mid"] = mid
        row["spread"] = spread
        if a > 0:
            row["spread_bps"] = round((a - b) / a * 10000.0, 2)
    return row


def _from_realtime_cache(symbols: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        from .data_sources import get_data_source, get_data_source_status, realtime_sip_enabled

        if not realtime_sip_enabled():
            return out
        ds = get_data_source_status() or {}
        if ds.get("fallback_active"):
            return out
        src = get_data_source(purpose="live")
        try:
            if hasattr(src, "start_stream"):
                src.start_stream(list(symbols))
        except Exception:
            pass
        feed = (ds.get("feed_badge") or "SIP").upper()
        if feed not in ("SIP", "IEX", "NBBO"):
            feed = "SIP"
        for t in symbols:
            quote = src.get_latest_quote(t) if hasattr(src, "get_latest_quote") else None
            trade = src.get_latest_trade(t) if hasattr(src, "get_latest_trade") else None
            if quote is None and trade is None:
                continue
            row: Dict[str, Any] = {
                "ticker": _norm(t),
                "bid": getattr(quote, "bid", None) if quote else None,
                "ask": getattr(quote, "ask", None) if quote else None,
                "bid_size": getattr(quote, "bid_size", None) if quote else None,
                "ask_size": getattr(quote, "ask_size", None) if quote else None,
                "price": getattr(trade, "price", None) if trade else None,
                "size": getattr(trade, "size", None) if trade else None,
                "ts": (
                    getattr(quote, "timestamp", None)
                    if quote
                    else None
                )
                or (getattr(trade, "timestamp", None) if trade else None)
                or _utc_now(),
                "feed": "NBBO" if quote and getattr(quote, "bid", 0) and getattr(quote, "ask", 0) else feed,
                "source": "realtime_cache",
            }
            out.append(_enrich(row))
    except Exception:
        return out
    return out


def _from_alpaca_rest(symbols: Sequence[str]) -> List[Dict[str, Any]]:
    key, secret = _keys()
    if not key or not secret or not symbols:
        return []
    # Prefer IEX on free plans; SIP when DATA_FEED=sip
    feed = (os.environ.get("ALPACA_DATA_FEED") or os.environ.get("ALPACA_FEED") or "iex").strip().lower()
    if feed not in ("iex", "sip"):
        feed = "iex"
    alpaca_syms = [_alpaca_sym(s) for s in symbols]
    qs = urllib.parse.urlencode({"symbols": ",".join(alpaca_syms), "feed": feed})
    url = f"https://data.alpaca.markets/v2/stocks/quotes/latest?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "User-Agent": "GAMMA-R/quotes",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    quotes = raw.get("quotes") if isinstance(raw, dict) else None
    if not isinstance(quotes, dict):
        return []
    out: List[Dict[str, Any]] = []
    for alp, q in quotes.items():
        if not isinstance(q, dict):
            continue
        try:
            bid = float(q.get("bp") or 0) or None
            ask = float(q.get("ap") or 0) or None
            bid_size = float(q.get("bs") or 0) or None
            ask_size = float(q.get("as") or 0) or None
        except (TypeError, ValueError):
            continue
        if not bid and not ask:
            continue
        row = {
            "ticker": _norm(alp),
            "bid": bid,
            "ask": ask,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "price": None,
            "size": None,
            "ts": str(q.get("t") or _utc_now()),
            "feed": "NBBO",
            "source": f"alpaca_rest_{feed}",
            "underlying_feed": feed.upper(),
        }
        out.append(_enrich(row))
    return out


def _from_delayed(symbols: Sequence[str]) -> List[Dict[str, Any]]:
    """Last price only — no fabricated bid/ask. Clearly Delayed."""
    out: List[Dict[str, Any]] = []
    try:
        import yfinance as yf
    except ImportError:
        return out
    for t in symbols:
        try:
            tk = yf.Ticker(t)
            px = None
            fi = getattr(tk, "fast_info", None)
            if fi is not None:
                px = getattr(fi, "last_price", None) or getattr(fi, "lastPrice", None)
            if px is None:
                h = tk.history(period="1d", interval="1m")
                if h is not None and not h.empty and "Close" in h.columns:
                    px = float(h["Close"].dropna().iloc[-1])
            if px is None:
                continue
            out.append(
                _enrich(
                    {
                        "ticker": _norm(t),
                        "bid": None,
                        "ask": None,
                        "bid_size": None,
                        "ask_size": None,
                        "mid": None,
                        "spread": None,
                        "price": float(px),
                        "size": None,
                        "ts": _utc_now(),
                        "feed": "Delayed",
                        "source": "delayed_poll",
                    }
                )
            )
        except Exception:
            continue
    return out


def build_quotes(
    symbols: Optional[Sequence[str]] = None,
    *,
    limit: int = 40,
) -> Dict[str, Any]:
    """
    Top-of-book quotes for watchlist (or explicit symbols).
    Badge: Delayed | IEX | SIP | NBBO. Never claims full depth / L2 book.
    """
    from .config import get_runtime_config
    from .data_sources import get_data_source_status, realtime_sip_enabled
    from .watchlist import load_watchlist

    cfg = get_runtime_config()
    ds = get_data_source_status() or {}
    syms: List[str] = []
    if symbols:
        syms = [_norm(s) for s in symbols if s]
    else:
        try:
            syms = [_norm(s) for s in (load_watchlist() or [])]
        except Exception:
            syms = []
        if not syms:
            syms = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
    syms = list(dict.fromkeys(syms))[: max(1, min(60, int(limit or 40)))]

    quotes = _from_realtime_cache(syms)
    source = "realtime_cache" if quotes else None
    if not quotes:
        quotes = _from_alpaca_rest(syms)
        source = "alpaca_rest" if quotes else None
    if not quotes:
        quotes = _from_delayed(syms)
        source = "delayed_poll"

    # Prefer NBBO badge when any row has bid+ask
    has_nbbo = any(
        (q.get("bid") is not None and q.get("ask") is not None and float(q.get("bid") or 0) > 0)
        for q in quotes
    )
    feeds = {str(q.get("feed") or "") for q in quotes}
    if has_nbbo:
        feed_badge = "NBBO"
    elif "SIP" in feeds:
        feed_badge = "SIP"
    elif "IEX" in feeds:
        feed_badge = "IEX"
    else:
        feed_badge = "Delayed"

    key, secret = _keys()
    return {
        "ok": True,
        "ts": _utc_now(),
        "symbols": syms,
        "quotes": quotes,
        "count": len(quotes),
        "source": source or "none",
        "feed_badge": feed_badge,
        "keys_present": bool(key and secret),
        "realtime_sip_enabled": bool(realtime_sip_enabled()),
        "data_label": ds.get("data_label"),
        "poll_recommended_sec": 2 if feed_badge in ("NBBO", "SIP", "IEX") else 5,
        "not_level2": True,
        "label": "Top-of-book quotes (NBBO/L2-lite) — not full depth / not Level-2 order book",
        "flags": {
            "dashboard_poll_sec": int(getattr(cfg, "dashboard_poll_sec", 3) or 3),
            "fallback_active": bool(ds.get("fallback_active")),
        },
    }

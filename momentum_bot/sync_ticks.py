"""
Fast tick poll for watchlist symbols.

Uses Alpaca SIP/IEX cache when realtime is healthy; otherwise delayed last prices
clearly labeled. Includes NBBO top-of-book (bid/ask/mid/spread/size) when available.
Not a Level-2 book.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_ticks(symbols: Optional[Sequence[str]] = None, *, limit: int = 40) -> Dict[str, Any]:
    from .quotes import build_quotes

    q = build_quotes(symbols, limit=limit)
    ticks: List[Dict[str, Any]] = []
    for row in q.get("quotes") or []:
        ticks.append({
            "ticker": row.get("ticker"),
            "price": row.get("price") or row.get("mid"),
            "size": row.get("size"),
            "bid": row.get("bid"),
            "ask": row.get("ask"),
            "bid_size": row.get("bid_size"),
            "ask_size": row.get("ask_size"),
            "mid": row.get("mid"),
            "spread": row.get("spread"),
            "spread_bps": row.get("spread_bps"),
            "ts": row.get("ts") or _utc_now(),
            "feed": row.get("feed") or q.get("feed_badge"),
        })

    return {
        "ok": bool(q.get("ok", True)),
        "ts": q.get("ts") or _utc_now(),
        "symbols": q.get("symbols") or [],
        "ticks": ticks,
        "quotes": q.get("quotes") or [],
        "count": len(ticks),
        "source": q.get("source"),
        "feed_badge": q.get("feed_badge") or "Delayed",
        "data_label": q.get("data_label"),
        "last_tick_age_sec": (q.get("flags") or {}).get("last_tick_age_sec"),
        "poll_recommended_sec": q.get("poll_recommended_sec") or 5,
        "not_level2": True,
        "label": "Top-of-book tick/quote poll — not Level-2 order book",
        "flags": q.get("flags") or {},
        "keys_present": q.get("keys_present"),
    }

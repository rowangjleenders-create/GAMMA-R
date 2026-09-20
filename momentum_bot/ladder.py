"""
DOM / ladder UI — NBBO-driven top-of-book ladder.

Visual price ladder centered on mid; bid/ask sizes from NBBO quotes.
Explicitly NOT full exchange depth.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(sym: str) -> str:
    return (sym or "").strip().upper().replace(".", "-")


def build_ladder(
    symbol: str,
    *,
    levels: int = 8,
    tick: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Build a synthetic price ladder from top-of-book NBBO.
    Only the mid row has real size; other rows are empty placeholders
    so the UI looks like a ladder without claiming depth.
    """
    from .quotes import build_quotes

    t = _norm(symbol)
    n = max(3, min(int(levels or 8), 20))
    qpay = build_quotes([t], limit=1)
    quotes = qpay.get("quotes") or []
    q = next((x for x in quotes if str(x.get("symbol") or "").upper().replace(".", "-") == t), None)
    if q is None and quotes:
        q = quotes[0]

    caption = "Top-of-book ladder — not full exchange depth."
    base: Dict[str, Any] = {
        "ok": True,
        "symbol": t,
        "caption": caption,
        "not_level2": True,
        "full_depth": False,
        "feed_badge": qpay.get("feed_badge"),
        "generated_at": _utc_now(),
        "label": caption,
        "rows": [],
        "bid": None,
        "ask": None,
        "mid": None,
        "spread": None,
        "bid_size": None,
        "ask_size": None,
        "last": None,
    }
    if not q:
        base["note"] = "No quote available — ladder empty."
        base["ok"] = True
        return base

    bid = q.get("bid")
    ask = q.get("ask")
    last = q.get("last") or q.get("price")
    mid = q.get("mid")
    try:
        if mid is None and bid is not None and ask is not None:
            mid = (float(bid) + float(ask)) / 2.0
        elif mid is None and last is not None:
            mid = float(last)
    except (TypeError, ValueError):
        mid = None

    if mid is None:
        base["note"] = "No mid/bid/ask — cannot center ladder."
        base.update({k: q.get(k) for k in ("bid", "ask", "last", "spread", "bid_size", "ask_size")})
        return base

    mid_f = float(mid)
    # Tick heuristic
    if tick is None or tick <= 0:
        if mid_f >= 100:
            tick_f = 0.05
        elif mid_f >= 20:
            tick_f = 0.01
        elif mid_f >= 1:
            tick_f = 0.01
        else:
            tick_f = 0.0001
    else:
        tick_f = float(tick)

    # Round mid to tick
    center = round(round(mid_f / tick_f) * tick_f, 6)
    half = n // 2
    rows: List[Dict[str, Any]] = []
    bid_f = float(bid) if bid is not None else None
    ask_f = float(ask) if ask is not None else None
    bid_sz = q.get("bid_size")
    ask_sz = q.get("ask_size")

    for i in range(half, -half - 1, -1):
        px = round(center + i * tick_f, 6)
        side = None
        size = None
        is_tob = False
        if ask_f is not None and abs(px - ask_f) < tick_f * 0.51:
            side = "ask"
            size = ask_sz
            is_tob = True
        elif bid_f is not None and abs(px - bid_f) < tick_f * 0.51:
            side = "bid"
            size = bid_sz
            is_tob = True
        elif i > 0:
            side = "ask"
        elif i < 0:
            side = "bid"
        rows.append({
            "price": px,
            "side": side,
            "size": size if is_tob else None,
            "top_of_book": is_tob,
            "is_mid": i == 0,
            "placeholder": not is_tob,
        })

    base.update({
        "bid": bid_f,
        "ask": ask_f,
        "mid": round(mid_f, 6),
        "spread": q.get("spread"),
        "bid_size": bid_sz,
        "ask_size": ask_sz,
        "last": last,
        "tick": tick_f,
        "rows": rows,
        "levels": n,
        "note": (
            "Only bid/ask rows carry real size from NBBO. "
            "Other rungs are visual placeholders — not exchange depth."
        ),
        "poll_recommended_sec": qpay.get("poll_recommended_sec") or 2,
    })
    return base

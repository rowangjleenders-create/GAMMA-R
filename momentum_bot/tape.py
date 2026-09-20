"""
Tape lite — recent prints / Time & Sales.

Uses Alpaca trades REST when keys exist; otherwise honest empty + label.
Never claims full exchange tape.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(sym: str) -> str:
    return (sym or "").strip().upper().replace(".", "-")


def _alpaca_sym(sym: str) -> str:
    return _norm(sym).replace("-", ".")


def _keys() -> tuple[str, str]:
    return (
        (os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID") or "").strip(),
        (os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY") or "").strip(),
    )


def _from_alpaca(symbol: str, limit: int) -> List[Dict[str, Any]]:
    key, secret = _keys()
    if not key or not secret:
        return []
    alp = _alpaca_sym(symbol)
    qs = urlencode({"symbols": alp, "limit": min(limit, 50)})
    url = f"https://data.alpaca.markets/v2/stocks/trades/latest?{qs}"
    # latest is one trade — also try historical recent
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "User-Agent": "GAMMA-R/tape",
    }
    trades: List[Dict[str, Any]] = []
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        row = (raw.get("trades") or {}).get(alp) if isinstance(raw, dict) else None
        if isinstance(row, dict):
            trades.append({
                "t": row.get("t") or row.get("timestamp"),
                "p": row.get("p") or row.get("price"),
                "s": row.get("s") or row.get("size"),
                "x": row.get("x") or row.get("exchange"),
                "c": row.get("c") or row.get("conditions"),
            })
    except Exception:
        pass

    # Recent window trades
    try:
        qs2 = urlencode({"limit": min(limit, 50), "asof": "", "feed": "iex"})
        url2 = f"https://data.alpaca.markets/v2/stocks/{alp}/trades?{qs2}"
        req2 = Request(url2, headers=headers)
        with urlopen(req2, timeout=8) as resp2:
            raw2 = json.loads(resp2.read().decode("utf-8"))
        for row in (raw2.get("trades") or [])[-limit:]:
            if not isinstance(row, dict):
                continue
            trades.append({
                "t": row.get("t"),
                "p": row.get("p"),
                "s": row.get("s"),
                "x": row.get("x"),
                "c": row.get("c"),
            })
    except Exception:
        pass

    # Dedupe by t+p+s
    seen = set()
    out: List[Dict[str, Any]] = []
    for tr in reversed(trades):
        key_t = (tr.get("t"), tr.get("p"), tr.get("s"))
        if key_t in seen:
            continue
        seen.add(key_t)
        try:
            out.append({
                "t": tr.get("t"),
                "price": float(tr["p"]) if tr.get("p") is not None else None,
                "size": int(tr["s"]) if tr.get("s") is not None else None,
                "exchange": tr.get("x"),
                "conditions": tr.get("c"),
            })
        except (TypeError, ValueError):
            continue
        if len(out) >= limit:
            break
    return out


def _from_yfinance_last(symbol: str) -> List[Dict[str, Any]]:
    """Single last print from delayed history — not a real tape."""
    try:
        import yfinance as yf
        hist = yf.Ticker(_norm(symbol).replace("-", ".")).history(period="1d", interval="1m")
        if hist is None or hist.empty:
            return []
        last = hist.iloc[-1]
        ts = hist.index[-1]
        try:
            tstr = ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ") if getattr(ts, "tzinfo", None) else str(ts)[:19] + "Z"
        except Exception:
            tstr = str(ts)
        return [{
            "t": tstr,
            "price": float(last.get("Close")),
            "size": int(float(last.get("Volume") or 0)) or None,
            "exchange": None,
            "conditions": None,
            "approx": True,
        }]
    except Exception:
        return []


def get_tape(symbol: str, *, limit: int = 40) -> Dict[str, Any]:
    t = _norm(symbol)
    lim = max(1, min(int(limit or 40), 100))
    key, secret = _keys()
    prints = _from_alpaca(t, lim) if key and secret else []
    source = "alpaca" if prints else None
    note = ""
    if not prints:
        # Prefer honest empty when no keys; optionally one delayed last print
        if not key or not secret:
            note = (
                "No Alpaca keys — tape empty. Add ALPACA_API_KEY + ALPACA_SECRET_KEY "
                "for recent prints (IEX/SIP). Not a full exchange Time & Sales."
            )
            source = "empty"
        else:
            approx = _from_yfinance_last(t)
            if approx:
                prints = approx
                source = "yfinance_last_bar"
                note = "Alpaca trades unavailable; showing last 1m bar close as approx print (not full tape)."
            else:
                source = "empty"
                note = "No recent trades returned. Not a full exchange tape."

    return {
        "ok": True,
        "symbol": t,
        "count": len(prints),
        "prints": prints,
        "source": source,
        "keys_present": bool(key and secret),
        "full_tape": False,
        "not_level2": True,
        "label": "Tape lite — recent prints only, not full exchange Time & Sales",
        "note": note,
        "generated_at": _utc_now(),
    }


# Alias
get_trades = get_tape

"""
OHLCV bars for pro chart UI.

GET /bars/{symbol}?interval=1d|1h|15m|5m&limit=
Reuses download_ohlcv / download_ohlcv_intraday. Computes VWAP when volume present.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ALLOWED_INTERVALS = ("1d", "1h", "15m", "5m")

_INTERVAL_PERIOD = {
    "1d": "1y",
    "1h": "30d",
    "15m": "10d",
    "5m": "5d",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace(".", "-")


def _vwap_series(opens, highs, lows, closes, volumes) -> List[Optional[float]]:
    """Cumulative VWAP from typical price * volume."""
    out: List[Optional[float]] = []
    cum_pv = 0.0
    cum_v = 0.0
    for o, h, l, c, v in zip(opens, highs, lows, closes, volumes):
        try:
            tp = (float(h) + float(l) + float(c)) / 3.0
            vv = float(v or 0)
        except (TypeError, ValueError):
            out.append(None)
            continue
        if vv > 0 and tp == tp:
            cum_pv += tp * vv
            cum_v += vv
        out.append(round(cum_pv / cum_v, 6) if cum_v > 0 else None)
    return out


def get_bars(
    symbol: str,
    *,
    interval: str = "1d",
    limit: int = 120,
) -> Dict[str, Any]:
    """
    Return OHLCV bars + optional VWAP for candle charts.
    Never claims full L2; bars are delayed/yfinance or Alpaca history when configured.
    """
    t = _norm_symbol(symbol)
    iv = (interval or "1d").strip().lower()
    if iv not in ALLOWED_INTERVALS:
        return {
            "ok": False,
            "symbol": t,
            "interval": iv,
            "bars": [],
            "error": f"interval must be one of {ALLOWED_INTERVALS}",
            "allowed_intervals": list(ALLOWED_INTERVALS),
        }
    lim = max(5, min(int(limit or 120), 500))
    if not t:
        return {"ok": False, "symbol": t, "interval": iv, "bars": [], "error": "symbol required"}

    period = _INTERVAL_PERIOD[iv]
    frames = {}
    source = "yfinance"
    try:
        from .data_sources import download_ohlcv_for

        frames = download_ohlcv_for([t], period=period, interval=iv) or {}
        source = "data_source"
    except Exception:
        frames = {}
    if not frames:
        try:
            from .data import download_ohlcv, download_ohlcv_intraday

            if iv == "1d":
                frames = download_ohlcv([t], period=period, interval="1d") or {}
            else:
                frames = download_ohlcv_intraday([t], interval=iv, period=period) or {}
            source = "yfinance"
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "symbol": t,
                "interval": iv,
                "bars": [],
                "error": str(exc),
                "source": source,
                "generated_at": _utc_now(),
            }

    # Key may be SPY or AAPL depending on normalize
    df = None
    for k, v in frames.items():
        if str(k).upper().replace(".", "-") == t or str(k).upper() == t.replace("-", "."):
            df = v
            break
    if df is None and frames:
        df = next(iter(frames.values()))

    if df is None or getattr(df, "empty", True):
        return {
            "ok": True,
            "symbol": t,
            "interval": iv,
            "bars": [],
            "count": 0,
            "vwap_available": False,
            "source": source,
            "note": "No bars returned (rate limit or unknown symbol).",
            "generated_at": _utc_now(),
            "not_level2": True,
        }

    try:
        tail = df.tail(lim)
    except Exception:
        tail = df

    opens = highs = lows = closes = volumes = []
    times: List[str] = []
    try:
        opens = [float(x) if x == x else None for x in tail["Open"].tolist()]
        highs = [float(x) if x == x else None for x in tail["High"].tolist()]
        lows = [float(x) if x == x else None for x in tail["Low"].tolist()]
        closes = [float(x) if x == x else None for x in tail["Close"].tolist()]
        if "Volume" in tail.columns:
            volumes = [float(x) if x == x else 0.0 for x in tail["Volume"].tolist()]
        else:
            volumes = [0.0] * len(closes)
        for idx in tail.index:
            try:
                ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
                if getattr(ts, "tzinfo", None) is None:
                    times.append(str(ts)[:19] + "Z")
                else:
                    times.append(ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            except Exception:
                times.append(str(idx))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "symbol": t,
            "interval": iv,
            "bars": [],
            "error": f"parse failed: {exc}",
            "generated_at": _utc_now(),
        }

    vwaps = _vwap_series(opens, highs, lows, closes, volumes)
    bars: List[Dict[str, Any]] = []
    for i in range(len(closes)):
        bars.append({
            "t": times[i] if i < len(times) else None,
            "o": opens[i],
            "h": highs[i],
            "l": lows[i],
            "c": closes[i],
            "v": volumes[i],
            "vwap": vwaps[i],
        })

    return {
        "ok": True,
        "symbol": t,
        "interval": iv,
        "limit": lim,
        "count": len(bars),
        "bars": bars,
        "vwap_available": any(b.get("vwap") is not None for b in bars),
        "source": source,
        "allowed_intervals": list(ALLOWED_INTERVALS),
        "generated_at": _utc_now(),
        "not_level2": True,
        "label": "OHLCV bars for charts — not Level-2 depth",
    }

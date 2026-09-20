"""
Intraday momentum / volume anomaly scanner (best-effort, not Level-2).

Uses 1–5m or 15m bars on watchlist + a liquid mega-cap subset.
Signals: unusual volume, range break, velocity. Honest delayed/SIP labels.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Liquid mega-cap / ETF subset — avoids full-universe intraday pulls
LIQUID_SUBSET: Tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "JPM", "V", "UNH", "XOM", "LLY", "MA", "COST", "HD", "PG", "NFLX",
    "AMD", "CRM", "ORCL", "ADBE", "CSCO", "INTC", "QCOM", "TXN",
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "SMH",
)

_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_TTL = 45.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _feed_badge() -> Dict[str, Any]:
    try:
        from .data_sources import get_data_source_status
        ds = get_data_source_status() or {}
        return {
            "feed_badge": ds.get("feed_badge") or "Delayed",
            "data_label": ds.get("data_label") or ds.get("status_hint"),
            "not_level2": True,
            "last_tick_age_sec": ds.get("last_tick_age_sec"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"feed_badge": "Delayed", "not_level2": True, "error": str(exc)}


def _pick_interval(cfg: Any) -> Tuple[str, str]:
    """Return (bar_interval, period) for yfinance intraday."""
    preferred = str(getattr(cfg, "intraday_heat_interval", None) or "").strip().lower()
    wl_iv = str(getattr(cfg, "watchlist_bar_interval", "1d") or "1d").strip().lower()
    if preferred in ("1m", "2m", "5m", "15m", "30m", "1h"):
        iv = preferred
    elif wl_iv in ("1m", "5m", "15m", "1h"):
        iv = wl_iv
    else:
        iv = "5m"
    # yfinance period limits: 1m ≤ 7d, 5m/15m ≤ 60d
    if iv in ("1m", "2m"):
        period = "1d"
    elif iv in ("5m", "15m"):
        period = str(getattr(cfg, "intraday_heat_period", None) or "5d")
    else:
        period = str(getattr(cfg, "watchlist_intraday_period", None) or "5d")
    return iv, period


def _symbols(cfg: Any, extra: Optional[Sequence[str]] = None) -> List[str]:
    from .watchlist import load_watchlist

    wl: List[str] = []
    try:
        wl = list(load_watchlist() or [])
    except Exception:
        wl = []
    liquid_n = int(getattr(cfg, "intraday_heat_liquid_n", 24) or 24)
    liquid = list(LIQUID_SUBSET[: max(8, min(40, liquid_n))])
    out: List[str] = []
    seen = set()
    for t in list(wl) + liquid + list(extra or []):
        u = (t or "").strip().upper().replace(".", "-")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    max_n = int(getattr(cfg, "intraday_heat_max_symbols", 40) or 40)
    return out[: max(10, min(60, max_n))]


def _score_bar(df, *, ticker: str, interval: str) -> Optional[Dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return None
    need = ("Close", "High", "Low", "Volume")
    if any(c not in df.columns for c in need):
        return None
    if len(df) < 12:
        return None
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    vol = df["Volume"].astype(float)
    last = float(close.iloc[-1])
    if last <= 0:
        return None

    # Velocity: last N bars vs prior N
    n = 6 if interval in ("1m", "2m", "5m") else 4
    if len(close) < n * 2 + 2:
        return None
    recent = float(close.iloc[-1] / close.iloc[-n] - 1.0) if close.iloc[-n] else 0.0
    prior = float(close.iloc[-n] / close.iloc[-2 * n] - 1.0) if close.iloc[-2 * n] else 0.0
    velocity = recent - prior

    # Unusual volume vs median of prior bars
    look = min(40, len(vol) - 1)
    base = vol.iloc[-(look + 1) : -1]
    med = float(base.median()) if len(base) else 0.0
    last_vol = float(vol.iloc[-1])
    vol_ratio = (last_vol / med) if med > 0 else None

    # Range break: close vs prior high/low of lookback window
    win = min(20, len(high) - 1)
    prior_high = float(high.iloc[-(win + 1) : -1].max()) if win >= 3 else None
    prior_low = float(low.iloc[-(win + 1) : -1].min()) if win >= 3 else None
    range_break = None
    if prior_high and last > prior_high:
        range_break = "high"
    elif prior_low and last < prior_low:
        range_break = "low"

    # Session range position
    day_hi = float(high.iloc[-min(78, len(high)) :].max())
    day_lo = float(low.iloc[-min(78, len(low)) :].min())
    span = day_hi - day_lo
    range_pos = ((last - day_lo) / span) if span > 0 else None

    flags: List[str] = []
    heat = 0.0
    if vol_ratio is not None and vol_ratio >= 2.0:
        flags.append("unusual_volume")
        heat += min(3.0, (vol_ratio - 1.0))
    if abs(recent) >= 0.008:
        flags.append("velocity")
        heat += min(2.5, abs(recent) * 80)
    if range_break:
        flags.append(f"range_break_{range_break}")
        heat += 1.5
    if abs(velocity) >= 0.006:
        flags.append("accel")
        heat += min(1.5, abs(velocity) * 60)

    if not flags:
        return None

    return {
        "ticker": ticker,
        "last": round(last, 4),
        "change_pct": round(recent, 6),
        "velocity": round(velocity, 6),
        "volume_ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
        "range_break": range_break,
        "range_pos": round(range_pos, 3) if range_pos is not None else None,
        "flags": flags,
        "heat": round(heat, 3),
        "interval": interval,
        "not_level2": True,
    }


def scan_intraday_heat(
    cfg: Any = None,
    *,
    force: bool = False,
    extra_symbols: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Build Intraday heat payload for Dashboard.
    Best-effort bar scanner — explicitly not a Level-2 / tape product.
    """
    from .config import get_runtime_config
    from .data import download_ohlcv_intraday

    cfg = cfg or get_runtime_config()
    now = time.time()
    if (
        not force
        and _CACHE.get("payload") is not None
        and (now - float(_CACHE.get("at") or 0)) < _CACHE_TTL
    ):
        cached = dict(_CACHE["payload"])
        cached["cache_hit"] = True
        cached["cache_age_sec"] = round(now - float(_CACHE["at"]), 1)
        return cached

    enabled = bool(getattr(cfg, "intraday_heat_enabled", True))
    feed = _feed_badge()
    base: Dict[str, Any] = {
        "ok": True,
        "label": "Intraday heat — bar anomalies only (not Level-2 order book)",
        "watermark": "NOT L2 / NOT TAPE",
        "generated_at": _utc_now(),
        "enabled": enabled,
        "hits": [],
        "scanned": 0,
        "interval": None,
        "period": None,
        "symbols_source": "watchlist+liquid_subset",
        "cache_hit": False,
        **feed,
    }
    if not enabled:
        base["note"] = "intraday_heat_enabled=false"
        return base

    iv, period = _pick_interval(cfg)
    symbols = _symbols(cfg, extra_symbols)
    base["interval"] = iv
    base["period"] = period
    base["symbol_count"] = len(symbols)

    try:
        bars = download_ohlcv_intraday(symbols, interval=iv, period=period, batch_size=20)
    except Exception as exc:  # noqa: BLE001
        base["ok"] = False
        base["note"] = f"Intraday download failed: {exc}"
        base["hits"] = []
        return base

    hits: List[Dict[str, Any]] = []
    for t, df in (bars or {}).items():
        row = _score_bar(df, ticker=t, interval=iv)
        if row:
            hits.append(row)
    hits.sort(key=lambda r: float(r.get("heat") or 0), reverse=True)
    top_n = int(getattr(cfg, "intraday_heat_top_n", 12) or 12)
    base["hits"] = hits[: max(5, min(25, top_n))]
    base["scanned"] = len(bars or {})
    base["hit_count"] = len(hits)
    base["note"] = (
        f"Scanned {base['scanned']} symbols on {iv} bars. "
        "Unusual volume / range break / velocity from OHLCV only — not Level-2."
    )
    _CACHE["at"] = now
    _CACHE["payload"] = dict(base)
    return base

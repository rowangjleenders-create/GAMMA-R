"""
Data source factory.

DATA_SOURCE=free|alpaca_sip  (env) or settings.realtime_sip_enabled.
Free (yfinance) is DEFAULT. SIP is live-only; historical always uses free.
On SIP disconnect/error → auto-fall back to free + warning log/event.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import LatestQuote, LatestTrade, MarketDataSource
from .yfinance_source import YFinanceSource

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
SETTINGS_PATH = DATA_DIR / "data_source_settings.json"
EVENTS_PATH = DATA_DIR / "data_source_events.json"

_lock = threading.RLock()
_free: Optional[YFinanceSource] = None
_sip: Optional[MarketDataSource] = None
_active_live: Optional[MarketDataSource] = None
_fallback_active = False
_last_warning: Optional[str] = None
_realtime_enabled_override: Optional[bool] = None  # set via API; None → env/file


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_settings_file() -> Dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return dict(json.loads(SETTINGS_PATH.read_text()))
    except Exception:
        return {}


def _save_settings_file(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


def _append_event(kind: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    events: List[Dict[str, Any]] = []
    if EVENTS_PATH.exists():
        try:
            events = list(json.loads(EVENTS_PATH.read_text()).get("events", []))
        except Exception:
            events = []
    entry = {"ts": _utc_now(), "kind": kind, "message": message}
    if extra:
        entry.update(extra)
    events.append(entry)
    events = events[-200:]  # cap
    EVENTS_PATH.write_text(json.dumps({"events": events}, indent=2))
    logger.warning("[data_source] %s: %s", kind, message)


def env_data_source() -> str:
    """Raw env preference: free | alpaca_sip."""
    raw = (os.environ.get("DATA_SOURCE") or "").strip().lower()
    if raw in ("alpaca_sip", "sip", "alpaca"):
        return "alpaca_sip"
    if raw in ("free", "yfinance", "yf"):
        return "free"
    return ""


def realtime_sip_enabled() -> bool:
    """
    Whether live path should prefer Alpaca SIP.
    Priority: API override → DATA_SOURCE env → settings file → False (default).
    """
    with _lock:
        if _realtime_enabled_override is not None:
            return bool(_realtime_enabled_override)
    env = env_data_source()
    if env == "alpaca_sip":
        return True
    if env == "free":
        return False
    # Also honor REALTIME_SIP_ENABLED=1
    if os.environ.get("REALTIME_SIP_ENABLED", "").strip() in ("1", "true", "True", "yes"):
        return True
    file_cfg = _load_settings_file()
    return bool(file_cfg.get("realtime_sip_enabled", False))


def set_realtime_sip_enabled(enabled: bool, *, persist: bool = True) -> Dict[str, Any]:
    """Toggle SIP for live path. Does not enable by default; paper trading unchanged."""
    global _realtime_enabled_override, _fallback_active, _active_live, _sip, _last_warning
    with _lock:
        _realtime_enabled_override = bool(enabled)
        if persist:
            cfg = _load_settings_file()
            cfg["realtime_sip_enabled"] = bool(enabled)
            cfg["updated_at"] = _utc_now()
            _save_settings_file(cfg)
        # Reset live source so next get rebuilds
        if _sip is not None:
            try:
                _sip.stop_stream()
            except Exception:
                pass
        _sip = None
        _active_live = None
        _fallback_active = False
        _last_warning = None
    _append_event(
        "config",
        f"realtime_sip_enabled={bool(enabled)}",
        {"enabled": bool(enabled)},
    )
    return get_data_source_status()


def _get_free() -> YFinanceSource:
    global _free
    with _lock:
        if _free is None:
            _free = YFinanceSource()
        return _free


def _on_sip_error(message: str) -> None:
    """Graceful fallback callback from AlpacaSIPSource."""
    global _fallback_active, _active_live, _last_warning
    with _lock:
        _fallback_active = True
        _active_live = _get_free()
        _last_warning = message
    _append_event("fallback", message, {"active_source": "free"})


def preferred_alpaca_feed() -> str:
    """sip | iex — env ALPACA_FEED or settings file; default sip when realtime on."""
    raw = (os.environ.get("ALPACA_FEED") or "").strip().lower()
    if raw in ("iex", "sip"):
        return raw
    file_cfg = _load_settings_file()
    f = str(file_cfg.get("alpaca_feed") or "").strip().lower()
    if f in ("iex", "sip"):
        return f
    return "sip"


def _build_sip() -> MarketDataSource:
    from .alpaca_sip import AlpacaSIPSource, IEX_WS_URL, SIP_WS_URL

    feed = preferred_alpaca_feed()
    url = IEX_WS_URL if feed == "iex" else SIP_WS_URL
    src = AlpacaSIPSource(history_source=_get_free(), on_error=_on_sip_error, ws_url=url)
    try:
        src._feed = feed  # type: ignore[attr-defined]
    except Exception:
        pass
    return src


def get_data_source(*, purpose: str = "live") -> MarketDataSource:
    """
    Return the active market data source.

    purpose:
      - "historical" | "backtest" | "train" → always free (yfinance)
      - "live" | "scan" → SIP if enabled and healthy, else free
    """
    global _active_live, _sip, _fallback_active, _last_warning

    purpose_l = (purpose or "live").lower().strip()
    if purpose_l in ("historical", "history", "backtest", "train", "training"):
        return _get_free()

    if not realtime_sip_enabled():
        with _lock:
            _active_live = _get_free()
            _fallback_active = False
        return _get_free()

    with _lock:
        if _fallback_active and _active_live is not None:
            return _active_live
        if _sip is None:
            try:
                _sip = _build_sip()
            except Exception as exc:  # noqa: BLE001
                _fallback_active = True
                _last_warning = str(exc)
                _active_live = _get_free()
                _append_event("fallback", str(exc), {"active_source": "free"})
                return _active_live
        # If SIP reports disconnected after prior connect, fall back
        if _sip is not None and hasattr(_sip, "is_connected"):
            # Allow first-time connect during download_ohlcv/start_stream
            st = _sip.status() if hasattr(_sip, "status") else {}
            if st.get("last_error") and not st.get("connected"):
                _fallback_active = True
                _last_warning = st.get("last_error")
                _active_live = _get_free()
                return _active_live
        _active_live = _sip
        return _sip  # type: ignore[return-value]


def download_ohlcv_for(
    purpose: str,
    tickers: List[str],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Convenience: pick source by purpose then download OHLCV."""
    src = get_data_source(purpose=purpose)
    return src.download_ohlcv(tickers, **kwargs)


def get_data_source_status() -> Dict[str, Any]:
    with _lock:
        active = _active_live or _get_free()
        fallback = _fallback_active
        warning = _last_warning
        sip_status = None
        if _sip is not None:
            try:
                sip_status = _sip.status()
            except Exception as exc:  # noqa: BLE001
                sip_status = {"error": str(exc)}
    enabled = realtime_sip_enabled()
    feed = preferred_alpaca_feed() if enabled else None
    keys_present = bool(
        os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_DATA_KEY")
    ) and bool(
        os.environ.get("ALPACA_API_SECRET") or os.environ.get("ALPACA_DATA_SECRET")
    )
    sip_connected = bool((sip_status or {}).get("connected")) if isinstance(sip_status, dict) else False
    last_tick_age = None
    connection_health = "n/a"
    if isinstance(sip_status, dict):
        last_tick_age = sip_status.get("last_tick_age_sec")
        connection_health = sip_status.get("connection_health") or (
            "ok" if sip_connected else "down"
        )
        if sip_status.get("feed"):
            feed = sip_status.get("feed") or feed

    # Feed badge for mobile: Delayed | IEX | SIP
    if enabled and not fallback and sip_connected:
        feed_badge = "SIP" if (feed or "sip") == "sip" else "IEX"
        data_label = f"REALTIME (Alpaca {feed_badge})"
        status_hint = f"{feed_badge} ON + connected"
    elif enabled and fallback:
        feed_badge = "Delayed"
        data_label = "DELAYED (fallback from realtime)"
        status_hint = "Realtime requested but fallen back to free delayed"
    elif enabled:
        feed_badge = "IEX" if feed == "iex" else "SIP"
        data_label = f"REALTIME requested ({feed_badge}) — connecting"
        status_hint = f"{feed_badge} requested; waiting for first live fetch"
    else:
        feed_badge = "Delayed"
        data_label = "DELAYED (free)"
        status_hint = "Free delayed (default) — enable SIP/IEX in Settings when ready"

    enable_checklist = [
        {
            "id": "keys",
            "label": "Alpaca API keys on host",
            "done": keys_present,
            "hint": "ALPACA_API_KEY + ALPACA_API_SECRET (or DATA_KEY/SECRET)",
        },
        {
            "id": "toggle",
            "label": "Realtime toggle ON",
            "done": enabled,
            "hint": "Settings → Real-time SIP/IEX, or PUT /data-source",
        },
        {
            "id": "connected",
            "label": "WebSocket connected",
            "done": bool(enabled and sip_connected and not fallback),
            "hint": "GET /data-source/status → sip.connected",
        },
        {
            "id": "ticks",
            "label": "Receiving ticks",
            "done": bool(
                enabled and not fallback and last_tick_age is not None and float(last_tick_age) < 120
            ),
            "hint": "last_tick_age_sec under 120s",
        },
        {
            "id": "no_fallback",
            "label": "Not on delayed fallback",
            "done": bool(enabled and not fallback),
            "hint": "POST /data-source/reset-fallback after fixing keys/subscription",
        },
    ]

    return {
        "data_source": active.name if active else "free",
        "requested": ("alpaca_sip" if (feed or "sip") == "sip" else "alpaca_iex") if enabled else "free",
        "realtime_sip_enabled": enabled,
        "alpaca_feed": feed or ("sip" if enabled else None),
        "feed_badge": feed_badge,
        "data_label": data_label,
        "fallback_active": fallback,
        "using_fallback": fallback,
        "fallback_label": "DELAYED (clearly labeled fallback)" if fallback else None,
        "last_warning": warning,
        "sip": sip_status,
        "connection_health": connection_health if enabled else "delayed",
        "last_tick_age_sec": last_tick_age,
        "free_default": True,
        "historical_always_free": True,
        "not_level2": True,
        "level2_note": "GAMMA-R does not provide a Level-2 order book or full tape. Badges are Delayed | IEX | SIP last-trade/quote only.",
        "cost_note": (
            "Alpaca Algo Trader Plus ~$99/mo for SIP; IEX often available on lower tiers; free delayed is default"
        ),
        "env_DATA_SOURCE": env_data_source() or None,
        "events_path": str(EVENTS_PATH),
        "alpaca_keys_detected": keys_present,
        "enable_checklist": enable_checklist,
        "enable_instructions": [
            "1. Keys: set ALPACA_API_KEY + ALPACA_API_SECRET on the API host.",
            "2. Feed: SIP needs Algo Trader Plus (~$99/mo). Optional ALPACA_FEED=iex for IEX realtime.",
            "3. Toggle: Settings → Real-time ON, or PUT /data-source {\"realtime_sip_enabled\": true}.",
            "4. Confirm feed_badge is IEX or SIP, fallback_active=false, last_tick_age_sec fresh.",
            "5. If fallback: POST /data-source/reset-fallback after fixing keys/subscription.",
            "6. Historical training / backtests always use free delayed yfinance.",
            "NOT Level-2: mobile badges are Delayed | IEX | SIP — last trade/quote, not an order book.",
        ],
        "status_hint": status_hint,
    }


def recent_events(limit: int = 50) -> List[Dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    try:
        events = list(json.loads(EVENTS_PATH.read_text()).get("events", []))
        return events[-limit:]
    except Exception:
        return []


def reset_fallback() -> Dict[str, Any]:
    """Clear fallback flag and rebuild SIP on next live fetch (if still enabled)."""
    global _fallback_active, _active_live, _sip, _last_warning
    with _lock:
        _fallback_active = False
        _last_warning = None
        if _sip is not None:
            try:
                _sip.stop_stream()
            except Exception:
                pass
        _sip = None
        _active_live = None
    _append_event("reset", "fallback cleared; next live fetch will retry SIP if enabled")
    return get_data_source_status()


__all__ = [
    "MarketDataSource",
    "LatestTrade",
    "LatestQuote",
    "YFinanceSource",
    "get_data_source",
    "download_ohlcv_for",
    "realtime_sip_enabled",
    "set_realtime_sip_enabled",
    "get_data_source_status",
    "recent_events",
    "reset_fallback",
    "preferred_alpaca_feed",
]

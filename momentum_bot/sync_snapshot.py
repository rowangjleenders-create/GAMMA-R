"""
Lightweight status snapshot for mobile 2–5s polling / SSE.

Reuses scan status, crash mode, paper equity, and last audit — no heavy scans.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_sync_snapshot(cfg: Any = None) -> Dict[str, Any]:
    """Compact payload optimized for frequent poll (GET /sync/snapshot)."""
    from .config import get_runtime_config
    from .scanner import get_scan_status
    from .data_sources import get_data_source_status, realtime_sip_enabled

    cfg = cfg or get_runtime_config()
    scan = {}
    try:
        scan = get_scan_status() or {}
    except Exception as exc:  # noqa: BLE001
        scan = {"error": str(exc)}

    crash: Dict[str, Any] = {"active": False, "enabled": True}
    try:
        from .crash_mode import get_crash_status
        crash = get_crash_status(cfg).to_dict()
    except Exception as exc:  # noqa: BLE001
        crash = {"active": False, "error": str(exc)}

    paper: Dict[str, Any] = {}
    try:
        from .paper import performance
        perf = performance()
        paper = {
            "equity": perf.get("equity"),
            "cash": perf.get("cash"),
            "return_pct": perf.get("return_pct"),
            "open_trades": perf.get("open_trades"),
            "closed_trades": perf.get("closed_trades"),
            "win_rate": perf.get("win_rate"),
            "mode": perf.get("mode") or "paper",
            "label": "PAPER",
        }
    except Exception as exc:  # noqa: BLE001
        paper = {"error": str(exc), "label": "PAPER"}

    last_audit: Optional[Dict[str, Any]] = None
    try:
        from .decision_audit import read_decisions
        rows = read_decisions(limit=1)
        if rows:
            r = rows[0]
            last_audit = {
                "timestamp": r.get("timestamp"),
                "ticker": r.get("ticker"),
                "strategy_id": r.get("strategy_id"),
                "order_id": r.get("order_id"),
                "skip_reason": r.get("skip_reason"),
                "firewall_allow": r.get("firewall_allow"),
                "source": r.get("source"),
            }
    except Exception:
        last_audit = None

    ds: Dict[str, Any] = {}
    try:
        ds = get_data_source_status() or {}
    except Exception as exc:  # noqa: BLE001
        ds = {"error": str(exc)}

    sip_on = bool(realtime_sip_enabled() or getattr(cfg, "realtime_sip_enabled", False))
    fallback = bool(ds.get("fallback_active"))
    feed_badge = ds.get("feed_badge") or ("SIP" if sip_on and not fallback else "Delayed")
    age = scan.get("cache_age_sec")
    stale_warn = int(getattr(cfg, "scan_stale_warn_sec", 180) or 180)
    live_updating = True
    if age is not None:
        try:
            live_updating = float(age) <= float(stale_warn)
        except (TypeError, ValueError):
            live_updating = bool(scan.get("cache_fresh"))

    poll_sec = int(getattr(cfg, "dashboard_poll_sec", 3) or 3)
    poll_sec = max(2, min(30, poll_sec))
    tick_poll = 2 if sip_on and not fallback else max(3, poll_sec)

    quotes_brief: Dict[str, Any] = {"enabled": bool(getattr(cfg, "quotes_enabled", True)), "not_level2": True}
    try:
        if getattr(cfg, "quotes_enabled", True):
            from .quotes import build_quotes
            from .watchlist import load_watchlist
            syms = list(load_watchlist() or [])[:12]
            q = build_quotes(syms or None, limit=12)
            # Prefer NBBO badge on snapshot when quotes have bid/ask
            qb = q.get("feed_badge") or feed_badge
            if qb == "NBBO":
                feed_badge = "NBBO"
            quotes_brief = {
                "enabled": True,
                "feed_badge": qb,
                "count": q.get("count"),
                "quotes": (q.get("quotes") or [])[:12],
                "not_level2": True,
                "label": "Top-of-book — not full depth",
                "keys_present": q.get("keys_present"),
            }
    except Exception as exc:  # noqa: BLE001
        quotes_brief = {"enabled": True, "error": str(exc), "not_level2": True}

    edge_teaser: Dict[str, Any] = {}
    try:
        from .edge import why_gamma_r_card
        card = why_gamma_r_card(cfg)
        edge_teaser = {
            "title": card.get("title"),
            "tagline": card.get("tagline"),
            "bullet_ids": [b.get("id") for b in (card.get("bullets") or [])[:6]],
        }
    except Exception:
        edge_teaser = {}

    return {
        "ok": True,
        "ts": _utc_now(),
        "poll_recommended_sec": poll_sec,
        "tick_poll_recommended_sec": tick_poll,
        "live_updating": live_updating,
        "stale": not live_updating,
        "label": "PAPER-first sync snapshot — not a WebSocket L2 tape / not Level-2 order book",
        "not_level2": True,
        "scan": {
            "cache_age_sec": scan.get("cache_age_sec"),
            "cache_fresh": scan.get("cache_fresh"),
            "stale_warning": scan.get("stale_warning"),
            "last_scan_at": scan.get("last_scan_at"),
            "cached_count": scan.get("cached_count"),
            "scan_kind": scan.get("scan_kind"),
            "data_mode": scan.get("data_mode"),
            "has_cache": scan.get("has_cache"),
        },
        "crash_mode": {
            "active": bool(crash.get("active")),
            "enabled": crash.get("enabled", True),
            "until": crash.get("until"),
            "reason": (str(crash.get("reason") or ""))[:120] or None,
            "label": crash.get("label"),
        },
        "paper": paper,
        "last_audit": last_audit,
        "data_source": {
            "realtime_sip_enabled": sip_on,
            "fallback_active": fallback,
            "data_source": ds.get("data_source"),
            "feed_badge": feed_badge,
            "data_label": ds.get("data_label") or (
                "REALTIME (Alpaca SIP)" if sip_on and not fallback else "DELAYED (free)"
            ),
            "last_warning": ds.get("last_warning"),
            "last_tick_age_sec": ds.get("last_tick_age_sec"),
            "connection_health": ds.get("connection_health"),
            "not_level2": True,
        },
        "flags": {
            "options_read_only": bool(getattr(cfg, "options_read_only", False)),
            "watchlist_bar_interval": getattr(cfg, "watchlist_bar_interval", "1d") or "1d",
            "quick_scan_enabled": bool(getattr(cfg, "quick_scan_enabled", True)),
            "intraday_heat_enabled": bool(getattr(cfg, "intraday_heat_enabled", True)),
            "quotes_enabled": bool(getattr(cfg, "quotes_enabled", True)),
            "paper_options_enabled": bool(getattr(cfg, "paper_options_enabled", True)),
            "alerts_enabled": bool(getattr(cfg, "alerts_enabled", True)),
        },
        "quotes": quotes_brief,
        "edge_teaser": edge_teaser,
    }

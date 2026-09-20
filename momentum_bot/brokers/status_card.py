"""
Unified broker connect status card (marketplace-lite).

paper sim / alpaca paper / alpaca live(locked) / ibkr(planned)
Never unlocks live by default. Test button probes Alpaca paper account only.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _keys_present() -> bool:
    return bool(os.environ.get("ALPACA_API_KEY")) and bool(os.environ.get("ALPACA_API_SECRET"))


def test_alpaca_connection(*, paper: bool = True) -> Dict[str, Any]:
    """
    Probe Alpaca account endpoint with force=True (status only).
    Does not place orders. Prefer paper endpoint.
    """
    from .factory import get_broker

    out: Dict[str, Any] = {
        "ok": False,
        "broker": "alpaca",
        "paper": bool(paper),
        "tested_at": _utc_now(),
        "equity": None,
        "account_status": None,
        "error": None,
        "note": "Connection test only — no orders placed.",
    }
    if not _keys_present():
        out["error"] = "ALPACA_API_KEY / ALPACA_API_SECRET not set on API host"
        out["how_to"] = [
            "Set ALPACA_API_KEY and ALPACA_API_SECRET in the API environment",
            "Prefer ALPACA_PAPER=1 (default)",
            "Retry POST /brokers/alpaca/test",
        ]
        return out
    try:
        b = get_broker("alpaca", paper=paper, force=True)
        bal = b.get_balance()
        out["ok"] = True
        out["equity"] = getattr(bal, "equity", None)
        out["cash"] = getattr(bal, "cash", None)
        out["currency"] = getattr(bal, "currency", "USD")
        out["account_status"] = "reachable"
        out["endpoint"] = "paper" if paper else "live"
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
        out["account_status"] = "failed"
    return out


def unified_brokers_status() -> Dict[str, Any]:
    """GET /brokers/status card for Settings marketplace-lite."""
    from .factory import live_trading_enabled

    live_on = bool(live_trading_enabled())
    keys = _keys_present()
    alpaca_paper_pref = os.environ.get("ALPACA_PAPER", "1") != "0"
    ibkr_setup = {}
    try:
        from .ibkr import IBKRBroker
        ibkr_setup = IBKRBroker().setup_info()
    except Exception as exc:  # noqa: BLE001
        ibkr_setup = {"status": "planned", "error": str(exc), "docs_url": "https://www.interactivebrokers.com/campus/ibkr-api-page/trader-workstation-api/"}

    cards = [
        {
            "id": "paper_sim",
            "name": "Paper simulator",
            "status": "active",
            "connected": True,
            "mode": "paper",
            "note": "Built-in GAMMA-R paper portfolio (default). No broker keys required.",
            "actions": [],
        },
        {
            "id": "alpaca_paper",
            "name": "Alpaca Paper",
            "status": "ready" if keys else "needs_keys",
            "connected": False,
            "mode": "paper",
            "keys_detected": keys,
            "note": (
                "Connect via ALPACA_API_KEY/SECRET. Test with POST /brokers/alpaca/test. "
                "Does not unlock live routing."
            ),
            "actions": ["test_connection", "docs"],
            "docs_url": "https://docs.alpaca.markets/",
        },
        {
            "id": "alpaca_live",
            "name": "Alpaca Live",
            "status": "locked" if not live_on else ("ready" if keys else "needs_keys"),
            "connected": False,
            "mode": "live",
            "locked": not live_on,
            "live_trading_enabled": live_on,
            "note": (
                "LOCKED by default. Requires LIVE_TRADING_ENABLED=1, owner secret when hardened, "
                "firewall on, and explicit unlock. Prefer paper."
            ),
            "actions": ["unlock_docs"] if not live_on else ["test_connection"],
        },
        {
            "id": "ibkr",
            "name": "Interactive Brokers",
            "status": "planned",
            "connected": False,
            "mode": None,
            "coming_soon": True,
            "note": (
                "Adapter stub exists (momentum_bot/brokers/ibkr.py). "
                "Client Portal / TWS wiring not implemented — planned, not blocking."
            ),
            "actions": ["docs", "setup"],
            "docs_url": "https://www.interactivebrokers.com/campus/ibkr-api-page/trader-workstation-api/",
            "setup": ibkr_setup,
        },
    ]

    return {
        "ok": True,
        "generated_at": _utc_now(),
        "default": "paper_sim",
        "live_unlocked_by_default": False,
        "live_trading_enabled": live_on,
        "alpaca_keys_detected": keys,
        "alpaca_paper_preferred": alpaca_paper_pref,
        "brokers": cards,
        "label": "Broker connect (marketplace-lite) — paper-first; live locked by default",
    }

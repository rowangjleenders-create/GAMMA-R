"""Broker factory + live-trading gate (OFF by default)."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .alpaca import AlpacaBroker
from .base import BrokerAdapter
from .ibkr import IBKRBroker


def live_trading_enabled() -> bool:
    """
    Master kill for live routing. Default False.
    Set LIVE_TRADING_ENABLED=1 AND provide broker credentials to activate.
    """
    return os.environ.get("LIVE_TRADING_ENABLED", "0").strip() in ("1", "true", "True", "yes")


def get_broker(
    name: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    paper: Optional[bool] = None,
    force: bool = False,
) -> BrokerAdapter:
    """
    Return a broker adapter. Raises if live trading is not enabled
    (unless force=True for status checks / paper Alpaca sandbox).
    Live also requires owner secret (when hardened) + firewall_enabled.
    """
    if not force and not live_trading_enabled():
        raise RuntimeError(
            "Live trading is DISABLED (LIVE_TRADING_ENABLED!=1). "
            "Paper mode remains active. See README to activate when ready."
        )
    if not force and live_trading_enabled():
        try:
            from ..security import live_unlock_allowed
            ok, why = live_unlock_allowed()
            if not ok:
                raise RuntimeError(
                    f"Live trading blocked by security gate: {why}. "
                    "Paper mode remains active."
                )
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Live trading blocked (security check failed): {exc}"
            ) from exc
    name = (name or os.environ.get("BROKER", "alpaca")).lower().strip()
    if name == "alpaca":
        # Prefer paper endpoint unless explicitly ALPACA_PAPER=0
        return AlpacaBroker(api_key=api_key, api_secret=api_secret, paper=paper)
    if name in ("ibkr", "ib", "interactive"):
        return IBKRBroker()
    raise ValueError(f"Unknown broker: {name}")


def kill_switch(broker: Optional[BrokerAdapter] = None) -> Dict[str, Any]:
    """Cancel all orders + close all positions on the active live broker."""
    b = broker or get_broker(force=False)
    return b.kill_switch()

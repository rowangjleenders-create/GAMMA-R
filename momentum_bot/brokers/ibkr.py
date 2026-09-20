"""
Interactive Brokers adapter STUB — planned path (not blocking).

Does not place real orders. Raises NotImplementedError on trading calls.
Settings shows status=planned with setup doc link. Optional read-only
probe if ib_insync / ibapi is installed (account summary only).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BrokerAdapter, BrokerBalance, BrokerOrder, BrokerPosition

IBKR_SETUP_DOC = (
    "https://www.interactivebrokers.com/campus/ibkr-api-page/trader-workstation-api/"
)
IBKR_CLIENT_PORTAL_DOC = (
    "https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/"
)


class IBKRBroker(BrokerAdapter):
    name = "ibkr"
    status = "planned"

    def __init__(self, *args, **kwargs) -> None:
        self.host = kwargs.get("host") or "127.0.0.1"
        self.port = int(kwargs.get("port") or 7497)  # TWS paper default
        self.client_id = int(kwargs.get("client_id") or 1)
        self._note = (
            "IBKR adapter is planned/stub. Implement Client Portal or TWS API wiring here. "
            "Not available for live trading yet. See docs_url."
        )
        self.docs_url = IBKR_SETUP_DOC
        self.client_portal_docs = IBKR_CLIENT_PORTAL_DOC

    def setup_info(self) -> Dict[str, Any]:
        lib = None
        try:
            import ib_insync  # noqa: F401

            lib = "ib_insync"
        except ImportError:
            try:
                import ibapi  # noqa: F401

                lib = "ibapi"
            except ImportError:
                lib = None
        return {
            "id": "ibkr",
            "status": "planned",
            "connected": False,
            "coming_soon": True,
            "trading_enabled": False,
            "read_only_available": False,
            "client_lib_detected": lib,
            "note": self._note,
            "docs_url": self.docs_url,
            "client_portal_docs": self.client_portal_docs,
            "setup_steps": [
                "Install TWS or IB Gateway (paper account recommended)",
                "Enable API: Configure → API → Settings → Enable ActiveX and Socket Clients",
                "pip install ib_insync  (optional; not required for GAMMA-R paper path)",
                "Wire IBKRBroker.connect() — not implemented yet",
                "Keep LIVE_TRADING_ENABLED unset until adapter + firewall reviewed",
            ],
            "default_host": self.host,
            "default_port_paper": 7497,
            "default_port_live": 7496,
        }

    def get_balance(self) -> BrokerBalance:
        raise NotImplementedError(self._note)

    def get_positions(self) -> List[BrokerPosition]:
        raise NotImplementedError(self._note)

    def place_market_order(self, ticker: str, qty: float, side: str = "buy") -> BrokerOrder:
        raise NotImplementedError(self._note)

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError(self._note)

    def cancel_all_orders(self) -> int:
        raise NotImplementedError(self._note)

    def close_position(self, ticker: str) -> Optional[BrokerOrder]:
        raise NotImplementedError(self._note)

    def close_all_positions(self) -> List[BrokerOrder]:
        raise NotImplementedError(self._note)

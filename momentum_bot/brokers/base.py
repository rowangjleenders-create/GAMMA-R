"""Abstract brokerage adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class BrokerBalance:
    cash: float
    equity: float
    buying_power: float
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BrokerPosition:
    ticker: str
    shares: float
    avg_entry: float
    market_value: float
    unrealized_pnl: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BrokerOrder:
    id: str
    ticker: str
    side: str  # buy | sell
    qty: float
    status: str
    filled_avg_price: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class BrokerAdapter(ABC):
    """Common interface for place orders / balances / positions / cancel / kill."""

    name: str = "base"

    @abstractmethod
    def get_balance(self) -> BrokerBalance: ...

    @abstractmethod
    def get_positions(self) -> List[BrokerPosition]: ...

    @abstractmethod
    def place_market_order(self, ticker: str, qty: float, side: str = "buy") -> BrokerOrder: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    def cancel_all_orders(self) -> int: ...

    @abstractmethod
    def close_position(self, ticker: str) -> Optional[BrokerOrder]: ...

    @abstractmethod
    def close_all_positions(self) -> List[BrokerOrder]: ...

    def kill_switch(self) -> Dict[str, Any]:
        """Cancel all open orders and close all positions immediately."""
        n_cancel = self.cancel_all_orders()
        closed = self.close_all_positions()
        return {
            "cancelled_orders": n_cancel,
            "closed_positions": [c.to_dict() for c in closed],
            "broker": self.name,
        }

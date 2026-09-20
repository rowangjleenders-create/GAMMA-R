"""
Brokerage adapters — DISABLED by default.

Paper trading remains the active path. Live routing only engages when
LIVE_TRADING_ENABLED=1 in the environment AND valid credentials are
provided via env / SecureStore — never plain text in the repo.
(There is no StrategyConfig flag that unlocks live trading.)

Adapters:
  - AlpacaBroker: paper + live REST endpoints
  - IBKRBroker: stub for later Interactive Brokers implementation
"""

from .base import BrokerAdapter, BrokerBalance, BrokerOrder, BrokerPosition
from .factory import get_broker, live_trading_enabled, kill_switch

__all__ = [
    "BrokerAdapter",
    "BrokerBalance",
    "BrokerOrder",
    "BrokerPosition",
    "get_broker",
    "live_trading_enabled",
    "kill_switch",
]

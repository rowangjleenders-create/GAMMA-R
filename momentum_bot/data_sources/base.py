"""
Market data source adapter interface.

Live scans can switch between free delayed (yfinance) and paid real-time
Alpaca SIP. Historical training / backtests always use the free source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class LatestTrade:
    ticker: str
    price: float
    size: float
    timestamp: str = ""
    exchange: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LatestQuote:
    ticker: str
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MarketDataSource(ABC):
    """Common interface for OHLCV history + optional real-time quotes/trades."""

    name: str = "base"
    is_realtime: bool = False

    @abstractmethod
    def download_ohlcv(
        self,
        tickers: List[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: Optional[str] = None,
        batch_size: int = 50,
        auto_adjust: bool = True,
    ) -> Dict[str, pd.DataFrame]:
        """Return {ticker: OHLCV DataFrame} for usable tickers."""

    def get_latest_trade(self, ticker: str) -> Optional[LatestTrade]:
        return None

    def get_latest_quote(self, ticker: str) -> Optional[LatestQuote]:
        return None

    def start_stream(self, tickers: List[str]) -> None:
        """Begin real-time stream for tickers (no-op for delayed sources)."""

    def stop_stream(self) -> None:
        """Stop real-time stream if running."""

    def is_connected(self) -> bool:
        return True

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "is_realtime": self.is_realtime,
            "connected": self.is_connected(),
        }

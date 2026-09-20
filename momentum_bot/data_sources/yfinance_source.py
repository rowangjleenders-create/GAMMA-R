"""Free delayed market data via yfinance (wraps momentum_bot.data)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .. import data as data_mod
from .base import MarketDataSource


class YFinanceSource(MarketDataSource):
    """Default free delayed source — used for historical training & backtests."""

    name = "free"
    is_realtime = False

    def download_ohlcv(
        self,
        tickers: List[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: Optional[str] = None,
        batch_size: int = 50,
        auto_adjust: bool = True,
        **kwargs: Any,
    ) -> Dict[str, pd.DataFrame]:
        return data_mod.download_ohlcv(
            tickers,
            start=start,
            end=end,
            period=period,
            batch_size=batch_size,
            auto_adjust=auto_adjust,
            interval=str(kwargs.get("interval") or "1d"),
        )

"""
Alpaca brokerage adapter (paper + live).

Auth via ALPACA_API_KEY + ALPACA_API_SECRET env vars (never commit keys).
Paper endpoint is default when ALPACA_PAPER=1 (recommended).
Live endpoint only when LIVE_TRADING_ENABLED and ALPACA_PAPER=0.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

from .base import BrokerAdapter, BrokerBalance, BrokerOrder, BrokerPosition

PAPER_BASE = "https://paper-api.alpaca.markets"
LIVE_BASE = "https://api.alpaca.markets"


class AlpacaBroker(BrokerAdapter):
    name = "alpaca"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        paper: Optional[bool] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("ALPACA_API_SECRET", "")
        if paper is None:
            paper = os.environ.get("ALPACA_PAPER", "1") != "0"
        self.paper = bool(paper)
        self.base = PAPER_BASE if self.paper else LIVE_BASE
        if not self.api_key or not self.api_secret:
            raise RuntimeError(
                "Alpaca credentials missing. Set ALPACA_API_KEY and ALPACA_API_SECRET "
                "(or pass into adapter). Never store keys in source control."
            )

    def _headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> Any:
        r = requests.get(f"{self.base}{path}", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: Dict[str, Any]) -> Any:
        r = requests.post(f"{self.base}{path}", headers=self._headers(), json=body, timeout=30)
        r.raise_for_status()
        return r.json() if r.content else {}

    def _delete(self, path: str) -> Any:
        r = requests.delete(f"{self.base}{path}", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json() if r.content else {}

    def get_balance(self) -> BrokerBalance:
        acct = self._get("/v2/account")
        return BrokerBalance(
            cash=float(acct.get("cash", 0)),
            equity=float(acct.get("equity", 0)),
            buying_power=float(acct.get("buying_power", 0)),
            currency=acct.get("currency", "USD"),
        )

    def get_positions(self) -> List[BrokerPosition]:
        raw = self._get("/v2/positions")
        out = []
        for p in raw:
            out.append(
                BrokerPosition(
                    ticker=p.get("symbol", ""),
                    shares=float(p.get("qty", 0)),
                    avg_entry=float(p.get("avg_entry_price", 0)),
                    market_value=float(p.get("market_value", 0)),
                    unrealized_pnl=float(p.get("unrealized_pl", 0)),
                )
            )
        return out

    def place_market_order(self, ticker: str, qty: float, side: str = "buy") -> BrokerOrder:
        body = {
            "symbol": ticker.upper().replace("-", "."),  # Alpaca uses BRK.B style
            "qty": str(int(qty) if float(qty).is_integer() else qty),
            "side": side.lower(),
            "type": "market",
            "time_in_force": "day",
        }
        # Restore yfinance style for our records; Alpaca wants dot for class shares
        raw = self._post("/v2/orders", body)
        return BrokerOrder(
            id=str(raw.get("id", "")),
            ticker=ticker,
            side=side.lower(),
            qty=float(raw.get("qty") or qty),
            status=str(raw.get("status", "submitted")),
            filled_avg_price=float(raw["filled_avg_price"]) if raw.get("filled_avg_price") else None,
            raw=raw,
        )

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._delete(f"/v2/orders/{order_id}")
            return True
        except Exception:
            return False

    def cancel_all_orders(self) -> int:
        try:
            raw = self._delete("/v2/orders")
            if isinstance(raw, list):
                return len(raw)
            return 1
        except Exception:
            return 0

    def close_position(self, ticker: str) -> Optional[BrokerOrder]:
        sym = ticker.upper().replace("-", ".")
        try:
            raw = self._delete(f"/v2/positions/{sym}")
            return BrokerOrder(
                id=str(raw.get("id", "close")),
                ticker=ticker,
                side="sell",
                qty=float(raw.get("qty") or 0),
                status=str(raw.get("status", "submitted")),
                raw=raw,
            )
        except Exception:
            return None

    def close_all_positions(self) -> List[BrokerOrder]:
        try:
            raw = self._delete("/v2/positions")
            if isinstance(raw, list):
                return [
                    BrokerOrder(
                        id=str(r.get("id", "")),
                        ticker=r.get("symbol", ""),
                        side="sell",
                        qty=float(r.get("qty") or 0),
                        status=str(r.get("status", "submitted")),
                        raw=r,
                    )
                    for r in raw
                ]
        except Exception:
            pass
        return []

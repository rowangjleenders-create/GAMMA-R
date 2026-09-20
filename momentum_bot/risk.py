"""Position sizing, stop-loss, and take-profit helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .config import StrategyConfig


@dataclass
class TradePlan:
    ticker: str
    entry: float
    shares: int
    stop: float
    take_profit: float
    dollar_risk: float
    position_value: float


def size_position(
    ticker: str,
    entry_price: float,
    equity: float,
    cfg: StrategyConfig,
) -> TradePlan:
    """
    Risk-based position size.

    dollars_to_risk = equity * risk_per_trade
    shares = floor(dollars_to_risk / (entry * stop_loss_pct))
    then capped by max_position_pct of equity.
    """
    if entry_price <= 0 or equity <= 0:
        raise ValueError("entry_price and equity must be positive")

    stop = entry_price * (1.0 - cfg.stop_loss_pct)
    take_profit = entry_price * (1.0 + cfg.take_profit_pct)
    per_share_risk = entry_price - stop
    if per_share_risk <= 0:
        raise ValueError("stop_loss_pct too small / invalid")

    dollar_risk = equity * cfg.risk_per_trade
    shares_by_risk = int(dollar_risk // per_share_risk)

    max_dollars = equity * cfg.max_position_pct
    shares_by_cap = int(max_dollars // entry_price)

    shares = max(0, min(shares_by_risk, shares_by_cap))
    position_value = shares * entry_price

    return TradePlan(
        ticker=ticker,
        entry=round(entry_price, 4),
        shares=shares,
        stop=round(stop, 4),
        take_profit=round(take_profit, 4),
        dollar_risk=round(min(dollar_risk, shares * per_share_risk), 2),
        position_value=round(position_value, 2),
    )


def max_notional_for_equity(equity: float, cfg: StrategyConfig) -> float:
    """Hard cap dollars for any single ticker: equity * max_position_pct."""
    return max(0.0, float(equity) * float(cfg.max_position_pct))


def budget_shares(
    ticker: str,
    entry_price: float,
    equity: float,
    cfg: StrategyConfig,
    *,
    existing_notional: float = 0.0,
) -> TradePlan:
    """
    Risk-size then clamp so (existing_notional + new) ≤ equity * max_position_pct.
    Prevents one name from dominating the book.
    """
    plan = size_position(ticker, entry_price, equity, cfg)
    cap = max_notional_for_equity(equity, cfg)
    room = max(0.0, cap - float(existing_notional or 0.0))
    if entry_price <= 0:
        return plan
    max_shares_by_book = int(room // entry_price)
    shares = max(0, min(plan.shares, max_shares_by_book))
    position_value = shares * entry_price
    per_share_risk = entry_price * cfg.stop_loss_pct
    return TradePlan(
        ticker=ticker,
        entry=round(entry_price, 4),
        shares=shares,
        stop=plan.stop,
        take_profit=plan.take_profit,
        dollar_risk=round(shares * per_share_risk, 2),
        position_value=round(position_value, 2),
    )

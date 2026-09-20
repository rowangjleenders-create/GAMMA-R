"""
Transaction cost modeling for paper trading and backtests.

Default (ON for realism):
  - commission: $0.005 per share  (mode=per_share)
  - optional flat mode: $1.00 per trade
  - slippage: 0.1% of trade notional (market impact)
  - applied on BOTH entry and exit (round-trip visible)

Disable with fees_enabled=False in StrategyConfig / Settings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

# Sensible realism defaults (also mirrored in config.SEED_DEFAULTS)
DEFAULT_FEES_ENABLED = True
DEFAULT_COMMISSION_MODE = "per_share"  # per_share | flat
DEFAULT_COMMISSION_PER_SHARE = 0.005
DEFAULT_COMMISSION_FLAT = 1.0
DEFAULT_SLIPPAGE_PCT = 0.001  # 0.1% of trade value


@dataclass
class FeeBreakdown:
    """Cost of a single fill (entry or exit)."""

    enabled: bool
    side: str  # buy | sell
    shares: int
    price: float
    notional: float
    commission: float
    slippage: float
    total: float
    commission_mode: str
    slippage_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _cfg_get(cfg: Any, name: str, default: Any) -> Any:
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        return cfg.get(name, default)
    return getattr(cfg, name, default)


def fees_enabled(cfg: Any = None) -> bool:
    return bool(_cfg_get(cfg, "fees_enabled", DEFAULT_FEES_ENABLED))


def compute_trade_fees(
    shares: int,
    price: float,
    side: str = "buy",
    cfg: Any = None,
) -> FeeBreakdown:
    """
    Compute commission + slippage for one fill.

    Slippage is modeled as a dollar drag equal to slippage_pct * notional
    (adverse market impact). Commission is either per-share or flat per trade.
    When fees_enabled is False, all costs are zero.
    """
    shares = int(shares or 0)
    price = float(price or 0.0)
    notional = abs(shares * price)
    mode = str(_cfg_get(cfg, "commission_mode", DEFAULT_COMMISSION_MODE) or DEFAULT_COMMISSION_MODE).lower()
    if mode not in ("per_share", "flat"):
        mode = DEFAULT_COMMISSION_MODE
    per_share = float(_cfg_get(cfg, "commission_per_share", DEFAULT_COMMISSION_PER_SHARE))
    flat = float(_cfg_get(cfg, "commission_flat", DEFAULT_COMMISSION_FLAT))
    slip_pct = float(_cfg_get(cfg, "slippage_pct", DEFAULT_SLIPPAGE_PCT))
    enabled = fees_enabled(cfg)

    if not enabled or shares <= 0 or price <= 0:
        return FeeBreakdown(
            enabled=enabled,
            side=side,
            shares=shares,
            price=price,
            notional=round(notional, 6),
            commission=0.0,
            slippage=0.0,
            total=0.0,
            commission_mode=mode,
            slippage_pct=slip_pct,
        )

    if mode == "flat":
        commission = max(0.0, flat)
    else:
        commission = max(0.0, shares * per_share)

    slippage = max(0.0, notional * max(0.0, slip_pct))
    total = commission + slippage
    return FeeBreakdown(
        enabled=True,
        side=side,
        shares=shares,
        price=price,
        notional=round(notional, 6),
        commission=round(commission, 6),
        slippage=round(slippage, 6),
        total=round(total, 6),
        commission_mode=mode,
        slippage_pct=slip_pct,
    )


def round_trip_fees(
    shares: int,
    entry_price: float,
    exit_price: float,
    cfg: Any = None,
) -> Dict[str, Any]:
    """Entry + exit fee pair for a completed trade."""
    entry = compute_trade_fees(shares, entry_price, side="buy", cfg=cfg)
    exit_ = compute_trade_fees(shares, exit_price, side="sell", cfg=cfg)
    total = entry.total + exit_.total
    return {
        "entry": entry.to_dict(),
        "exit": exit_.to_dict(),
        "total_fees": round(total, 6),
        "entry_fees": entry.total,
        "exit_fees": exit_.total,
    }


def net_pnl(
    shares: int,
    entry_price: float,
    exit_price: float,
    cfg: Any = None,
    entry_fees: Optional[float] = None,
    exit_fees: Optional[float] = None,
) -> Dict[str, float]:
    """
    Gross vs net P&L for a closed trade.

    gross = (exit - entry) * shares
    net   = gross - entry_fees - exit_fees
    """
    shares = int(shares or 0)
    entry_price = float(entry_price or 0.0)
    exit_price = float(exit_price or 0.0)
    gross = (exit_price - entry_price) * shares
    if entry_fees is None or exit_fees is None:
        rt = round_trip_fees(shares, entry_price, exit_price, cfg=cfg)
        entry_fees = float(rt["entry_fees"])
        exit_fees = float(rt["exit_fees"])
    fees = float(entry_fees or 0.0) + float(exit_fees or 0.0)
    return {
        "gross_pnl": round(gross, 6),
        "total_fees": round(fees, 6),
        "net_pnl": round(gross - fees, 6),
        "entry_fees": round(float(entry_fees or 0.0), 6),
        "exit_fees": round(float(exit_fees or 0.0), 6),
    }


def fee_impact_summary(
    closed_trades: list,
    starting_equity: float = 0.0,
) -> Dict[str, Any]:
    """
    Aggregate fee impact from closed trade records.

    Expects each trade dict to optionally include:
      fees / total_fees / entry_fees / exit_fees / realized_pnl / gross_pnl
    Falls back to treating realized_pnl as net when fees are missing.
    """
    total_fees = 0.0
    gross_pnl = 0.0
    net_pnl_sum = 0.0
    n = 0
    for t in closed_trades or []:
        if not isinstance(t, dict):
            continue
        n += 1
        fees = t.get("total_fees")
        if fees is None:
            fees = float(t.get("entry_fees") or 0) + float(t.get("exit_fees") or 0)
        fees = float(fees or 0)
        total_fees += fees

        if t.get("gross_pnl") is not None:
            g = float(t["gross_pnl"])
        elif t.get("realized_pnl") is not None and fees:
            g = float(t["realized_pnl"]) + fees
        elif t.get("realized_pnl") is not None:
            g = float(t["realized_pnl"])
        else:
            entry = float(t.get("entry") or 0)
            exit_ = float(t.get("exit") or 0)
            shares = int(t.get("shares") or 0)
            g = (exit_ - entry) * shares
        gross_pnl += g

        if t.get("realized_pnl") is not None:
            net_pnl_sum += float(t["realized_pnl"])
        elif t.get("net_pnl") is not None:
            net_pnl_sum += float(t["net_pnl"])
        else:
            net_pnl_sum += g - fees

    fees_vs_gross = (total_fees / gross_pnl) if gross_pnl > 1e-9 else None
    # When gross is negative, report fees as fraction of |gross| with sign note
    if fees_vs_gross is None and abs(gross_pnl) > 1e-9:
        fees_vs_gross = total_fees / abs(gross_pnl)

    start = float(starting_equity or 0.0)
    gross_return = (gross_pnl / start) if start > 0 else None
    net_return = (net_pnl_sum / start) if start > 0 else None

    return {
        "closed_trades": n,
        "total_fees_paid": round(total_fees, 2),
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl_sum, 2),
        "fees_as_pct_of_gross_profit": round(fees_vs_gross, 6) if fees_vs_gross is not None else None,
        "gross_return_pct": round(gross_return, 6) if gross_return is not None else None,
        "net_return_pct": round(net_return, 6) if net_return is not None else None,
        "fee_drag_pct": round((gross_return or 0) - (net_return or 0), 6)
        if gross_return is not None and net_return is not None
        else None,
    }


def describe_defaults() -> Dict[str, Any]:
    return {
        "fees_enabled": DEFAULT_FEES_ENABLED,
        "commission_mode": DEFAULT_COMMISSION_MODE,
        "commission_per_share": DEFAULT_COMMISSION_PER_SHARE,
        "commission_flat": DEFAULT_COMMISSION_FLAT,
        "slippage_pct": DEFAULT_SLIPPAGE_PCT,
        "note": (
            "Fees ON by default. Per-share $0.005 + 0.1% slippage on entry and exit. "
            "Switch commission_mode to 'flat' for $1/trade, or set fees_enabled=false."
        ),
    }

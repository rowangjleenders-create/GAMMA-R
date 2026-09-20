"""
Vol-target overlay — position sizing scaler, not a standalone entry signal.

Computes a global size multiplier so recent realized vol is pulled toward
a target annualized volatility.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from ..config import StrategyConfig
from .base import Strategy, StrategySignal


def realized_vol_annual(closes: pd.Series, lookback: int = 20) -> Optional[float]:
    s = closes.dropna().astype(float)
    if len(s) < lookback + 1:
        return None
    rets = s.pct_change().dropna().iloc[-lookback:]
    if rets.empty:
        return None
    return float(rets.std() * (252 ** 0.5))


def compute_vol_target_mult(
    bars: Mapping[str, pd.DataFrame],
    cfg: StrategyConfig,
    *,
    benchmark: str = "SPY",
) -> Dict[str, Any]:
    """
    Return {multiplier, realized_vol, target_vol, capped}.
    Multiplier is clamped to a safe band (e.g. 0.25–1.5).
    """
    target = float(getattr(cfg, "vol_target_annual", 0.15) or 0.15)
    lookback = int(getattr(cfg, "vol_target_lookback", 20) or 20)
    floor = float(getattr(cfg, "vol_target_floor", 0.25) or 0.25)
    ceil = float(getattr(cfg, "vol_target_ceil", 1.5) or 1.5)

    df = bars.get(benchmark)
    realized = None
    if df is not None and "Close" in df.columns:
        realized = realized_vol_annual(df["Close"], lookback)
    if realized is None or realized <= 1e-8:
        # Fallback: median vol of a few liquid names
        vols = []
        for t in list(bars.keys())[:40]:
            d = bars.get(t)
            if d is None or "Close" not in d.columns:
                continue
            v = realized_vol_annual(d["Close"], lookback)
            if v is not None:
                vols.append(v)
        if vols:
            vols.sort()
            realized = vols[len(vols) // 2]

    if realized is None or realized <= 1e-8:
        return {
            "multiplier": 1.0,
            "realized_vol": None,
            "target_vol": target,
            "capped": False,
            "note": "insufficient data — vol-target neutral",
        }

    raw = target / realized
    mult = max(floor, min(ceil, raw))
    return {
        "multiplier": round(float(mult), 4),
        "realized_vol": round(float(realized), 4),
        "target_vol": target,
        "raw_multiplier": round(float(raw), 4),
        "capped": abs(mult - raw) > 1e-6,
        "lookback": lookback,
        "benchmark": benchmark,
    }


class VolTargetStrategy(Strategy):
    id = "vol_target"
    name = "Vol-target overlay"
    description = "Scales position size toward a target annualized volatility (not an entry signal)."
    is_overlay = True

    def generate_signals(
        self,
        universe: Sequence[str],
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[StrategySignal]:
        # Overlay — no entry signals
        return []

    def size_multiplier(
        self,
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
    ) -> Dict[str, Any]:
        return compute_vol_target_mult(bars, cfg)

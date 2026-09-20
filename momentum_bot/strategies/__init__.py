"""
GAMMA-R multi-strategy plugins.

Momentum remains one strategy among several. The router selects a subset
by regime; auto paper loops consume merged signals.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from .base import Strategy, StrategySignal
from .breakout import BreakoutStrategy
from .earnings_drift import EarningsDriftStrategy, earnings_provider_status
from .fx_mean_reversion import FxMeanReversionStrategy
from .mean_reversion import MeanReversionStrategy
from .momentum import MomentumStrategy
from .pairs import PairsStrategy
from .relative_strength import RelativeStrengthStrategy
from .router import (
    RouterDecision,
    explain_choice,
    get_last_router_decision,
    route_strategies,
)
from .vol_target import VolTargetStrategy, compute_vol_target_mult

STRATEGY_CLASSES: List[Type[Strategy]] = [
    MomentumStrategy,
    MeanReversionStrategy,
    BreakoutStrategy,
    RelativeStrengthStrategy,
    EarningsDriftStrategy,
    PairsStrategy,
    FxMeanReversionStrategy,
    VolTargetStrategy,
]

_REGISTRY: Dict[str, Strategy] = {cls.id: cls() for cls in STRATEGY_CLASSES}

DEFAULT_STRATEGY_ENABLED: Dict[str, bool] = {
    "momentum": True,
    "mean_reversion": True,
    "breakout": True,
    "relative_strength": True,
    "vol_target": True,
    "pairs": True,
    "fx_mean_reversion": True,
    "earnings_drift": True,
}


def all_strategy_ids() -> List[str]:
    return list(_REGISTRY.keys())


def get_strategy(strategy_id: str) -> Optional[Strategy]:
    return _REGISTRY.get(strategy_id)


def list_strategies() -> List[Dict]:
    out = []
    for sid, s in _REGISTRY.items():
        out.append({
            "id": sid,
            "name": s.name,
            "description": s.description,
            "is_overlay": bool(s.is_overlay),
        })
    return out


def get_registry() -> Dict[str, Strategy]:
    return dict(_REGISTRY)


__all__ = [
    "Strategy",
    "StrategySignal",
    "RouterDecision",
    "DEFAULT_STRATEGY_ENABLED",
    "all_strategy_ids",
    "get_strategy",
    "list_strategies",
    "get_registry",
    "route_strategies",
    "get_last_router_decision",
    "explain_choice",
    "compute_vol_target_mult",
    "earnings_provider_status",
]

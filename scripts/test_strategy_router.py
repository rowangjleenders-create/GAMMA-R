#!/usr/bin/env python3
"""Smoke test: router picks different strategies in bull vs sideways fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from momentum_bot.config import StrategyConfig
from momentum_bot.strategies import list_strategies, route_strategies, get_registry
from momentum_bot.strategies.router import DEFAULT_PRIORS, ACTIVE_FLOOR
from momentum_bot.optimization import RegimeState


def _regime(label: str, trend: str, vol: str) -> RegimeState:
    return RegimeState(
        label=label,
        trend=trend,
        vol_regime=vol,
        size_multiplier=1.0,
        pause_entries=False,
        metrics={},
    )


def main() -> int:
    cfg = StrategyConfig.seed()
    cfg = cfg.update({"router_mode": "auto"})

    ids = [s["id"] for s in list_strategies()]
    assert "momentum" in ids and "mean_reversion" in ids and "vol_target" in ids
    print("plugins:", ids)

    bull = route_strategies(cfg, regime=_regime("bull", "bull", "low"), fx_available=True)
    side = route_strategies(cfg, regime=_regime("sideways", "sideways", "low"), fx_available=True)
    high = route_strategies(cfg, regime=_regime("high_vol", "bull", "high"), fx_available=True)

    print("bull active:", bull.active, "weights mom/bo/mr:",
          bull.weights.get("momentum"), bull.weights.get("breakout"), bull.weights.get("mean_reversion"))
    print("sideways active:", side.active, "weights mom/mr/pairs:",
          side.weights.get("momentum"), side.weights.get("mean_reversion"), side.weights.get("pairs"))
    print("high_vol active:", high.active, "weights rs/vt:",
          high.weights.get("relative_strength"), high.weights.get("vol_target"))

    # Bull should prefer momentum/breakout over mean_reversion
    assert bull.weights.get("momentum", 0) >= bull.weights.get("mean_reversion", 0)
    assert bull.weights.get("breakout", 0) >= DEFAULT_PRIORS["sideways"]["breakout"] - 0.01

    # Sideways should prefer mean_reversion / pairs
    assert side.weights.get("mean_reversion", 0) >= side.weights.get("momentum", 0)
    assert side.weights.get("pairs", 0) >= ACTIVE_FLOOR

    # Different subsets / ordering of emphasis
    assert set(bull.active) != set(side.active) or (
        bull.weights.get("momentum", 0) != side.weights.get("momentum", 0)
    ), "bull vs sideways should differ in weights or active set"

    # High vol keeps vol_target and elevates RS vs breakout
    assert "vol_target" in high.weights
    assert high.weights.get("relative_strength", 0) >= high.weights.get("breakout", 0)

    # Manual mode activates all enabled
    manual = route_strategies(
        cfg.update({"router_mode": "manual"}),
        regime=_regime("bull", "bull", "low"),
    )
    assert set(manual.active) >= {"momentum", "mean_reversion", "breakout"}

    # Momentum-only still callable
    from momentum_bot.strategies.momentum import MomentumStrategy
    import pandas as pd
    import numpy as np
    dates = pd.date_range("2024-01-01", periods=40, freq="B")
    # Jump last 10d by >5% with 2x volume so seed momentum filters pass
    close = np.concatenate([np.full(30, 100.0), np.linspace(100, 110, 10)])
    vol = np.full(len(dates), 1_000_000.0)
    vol[-1] = 2_500_000.0
    df = pd.DataFrame({"Close": close, "High": close * 1.01, "Volume": vol}, index=dates)
    sigs = MomentumStrategy().generate_signals(["TEST"], {"TEST": df}, cfg)
    assert isinstance(sigs, list) and len(sigs) >= 1
    assert sigs[0].strategy_id == "momentum"
    print("momentum fixture signals:", len(sigs), sigs[0].strategy_id)

    # mean reversion fixture (pullback)
    from momentum_bot.strategies.mean_reversion import MeanReversionStrategy
    close_mr = np.concatenate([np.linspace(100, 110, 30), np.linspace(110, 102, 10)])
    df_mr = pd.DataFrame({
        "Close": close_mr,
        "High": close_mr * 1.01,
        "Volume": np.full(len(close_mr), 1_000_000.0),
    }, index=pd.date_range("2024-01-01", periods=len(close_mr), freq="B"))
    mr = MeanReversionStrategy().generate_signals(["TEST"], {"TEST": df_mr}, cfg)
    print("mean_reversion fixture signals:", len(mr))

    print("OK — router differs bull vs sideways; strategies importable/callable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

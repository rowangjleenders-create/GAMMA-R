"""Equity momentum — classic 12–1 ranking (primary trend-following strategy).

Default ranking signal: total return over ~12 months (252 trading days)
excluding the most recent month (~21 trading days). Short-history names
fall back to a scaled window or short-term lookback.

Strategy id remains ``momentum``. Router may still select other strategies;
this module only upgrades the momentum signal itself.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from ..config import StrategyConfig
from .base import Strategy, StrategySignal, classic_momentum_return, last_close, volume_ratio


class MomentumStrategy(Strategy):
    id = "momentum"
    name = "Momentum"
    description = (
        "Classic 12–1 price momentum (≈12m return skip 1m) with volume confirmation."
    )

    def generate_signals(
        self,
        universe: Sequence[str],
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[StrategySignal]:
        context = context or {}
        lookback = int(getattr(cfg, "momentum_lookback_days", 252) or 252)
        skip = int(getattr(cfg, "momentum_skip_days", 21) or 21)
        short_fb = int(getattr(cfg, "lookback_days", 10) or 10)
        min_ret = float(getattr(cfg, "min_return", 0.05) or 0.05)
        vol_mult = float(getattr(cfg, "volume_multiple", 1.5) or 1.5)
        vol_days = int(getattr(cfg, "volume_avg_days", 20) or 20)
        min_price = float(getattr(cfg, "min_price", 5.0) or 5.0)
        out: List[StrategySignal] = []

        for ticker in universe:
            df = bars.get(ticker)
            if df is None:
                continue
            entry = last_close(df)
            if entry is None or entry < min_price:
                continue
            cm = classic_momentum_return(
                df, lookback=lookback, skip=skip, short_fallback=short_fb
            )
            if cm is None:
                continue
            mom, mom_meta = cm
            vr = volume_ratio(df, vol_days)
            if vr is None:
                continue
            if mom < min_ret or vr < vol_mult:
                continue
            score = float(mom) * min(2.0, float(vr) / max(vol_mult, 0.1))
            mode = mom_meta.get("mode", "12_1")
            used_lb = mom_meta.get("lookback_days", lookback)
            used_skip = mom_meta.get("skip_days", skip)
            if mode == "12_1":
                rationale = (
                    f"12–1 momentum {mom*100:.1f}% "
                    f"({used_lb}d lookback skip {used_skip}d) with "
                    f"volume {vr:.2f}× {vol_days}d avg"
                )
            elif mode == "12_1_scaled":
                rationale = (
                    f"Scaled 12–1 momentum {mom*100:.1f}% "
                    f"({used_lb}d skip {used_skip}d; short history) with "
                    f"volume {vr:.2f}× {vol_days}d avg"
                )
            else:
                rationale = (
                    f"Short-fallback momentum {mom*100:.1f}% over {used_lb}d "
                    f"(12–1 history unavailable) with volume {vr:.2f}× {vol_days}d avg"
                )
            out.append(
                StrategySignal(
                    ticker=ticker,
                    side="long",
                    score=round(score, 6),
                    strategy_id=self.id,
                    rationale=rationale,
                    suggested_size_mult=1.0,
                    entry=round(entry, 4),
                    volume_ratio=round(vr, 4),
                    momentum_pct=round(mom, 6),
                    meta={
                        "momentum_lookback_days": lookback,
                        "momentum_skip_days": skip,
                        **mom_meta,
                    },
                )
            )

        out.sort(key=lambda s: s.score, reverse=True)
        top_n = int(getattr(cfg, "top_n", 20) or 20)
        top_pct = float(getattr(cfg, "top_pct", 0.10) or 0.10)
        keep = max(1, min(top_n, int(round(len(out) * top_pct)) or top_n))
        return out[:keep]

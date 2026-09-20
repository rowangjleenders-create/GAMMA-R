"""Breakout — range or N-day high on elevated volume."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from ..config import StrategyConfig
from .base import Strategy, StrategySignal, last_close, volume_ratio


class BreakoutStrategy(Strategy):
    id = "breakout"
    name = "Breakout"
    description = "N-day high / range breakout confirmed by volume."

    def generate_signals(
        self,
        universe: Sequence[str],
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[StrategySignal]:
        n = int(getattr(cfg, "breakout_lookback", 20) or 20)
        vol_mult = float(getattr(cfg, "breakout_volume_multiple", 1.4) or 1.4)
        min_price = float(getattr(cfg, "min_price", 5.0) or 5.0)
        out: List[StrategySignal] = []

        for ticker in universe:
            df = bars.get(ticker)
            if df is None or len(df) < n + 2:
                continue
            entry = last_close(df)
            if entry is None or entry < min_price:
                continue
            highs = df["High"].dropna() if "High" in df.columns else df["Close"].dropna()
            if len(highs) < n + 1:
                continue
            prior_high = float(highs.iloc[-(n + 1) : -1].max())
            if prior_high <= 0 or entry < prior_high * 1.001:
                continue
            vr = volume_ratio(df, int(getattr(cfg, "volume_avg_days", 20) or 20))
            if vr is None or vr < vol_mult:
                continue
            breakout_pct = (entry - prior_high) / prior_high
            score = breakout_pct * min(2.5, vr)
            out.append(
                StrategySignal(
                    ticker=ticker,
                    side="long",
                    score=round(float(score), 6),
                    strategy_id=self.id,
                    rationale=(
                        f"Breakout above {n}d high ${prior_high:.2f} "
                        f"(+{breakout_pct*100:.2f}%) on {vr:.2f}× volume"
                    ),
                    suggested_size_mult=1.0,
                    entry=round(entry, 4),
                    volume_ratio=round(float(vr), 4),
                    momentum_pct=round(float(breakout_pct), 6),
                    meta={"n_day_high": prior_high, "lookback": n},
                )
            )

        out.sort(key=lambda s: s.score, reverse=True)
        return out[: int(getattr(cfg, "top_n", 20) or 20)]

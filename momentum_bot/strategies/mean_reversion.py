"""Short-term mean reversion — oversold pullbacks in otherwise healthy names."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from ..config import StrategyConfig
from .base import Strategy, StrategySignal, last_close, pct_change, rsi, volume_ratio


class MeanReversionStrategy(Strategy):
    id = "mean_reversion"
    name = "Mean reversion"
    description = "Short-term oversold / pullback entries (RSI + distance from MA)."

    def generate_signals(
        self,
        universe: Sequence[str],
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[StrategySignal]:
        min_price = float(getattr(cfg, "min_price", 5.0) or 5.0)
        rsi_max = float(getattr(cfg, "mr_rsi_max", 32.0) or 32.0)
        pullback_min = float(getattr(cfg, "mr_pullback_min", -0.04) or -0.04)
        out: List[StrategySignal] = []

        for ticker in universe:
            df = bars.get(ticker)
            if df is None or len(df) < 30:
                continue
            entry = last_close(df)
            if entry is None or entry < min_price:
                continue
            closes = df["Close"].dropna().astype(float)
            r = rsi(closes, 14)
            ret_5 = pct_change(df, 5)
            if r is None or ret_5 is None:
                continue
            # Oversold + recent pullback, but not a freefall (avoid -15% wrecks)
            if r > rsi_max or ret_5 > pullback_min or ret_5 < -0.15:
                continue
            ma20 = float(closes.iloc[-20:].mean())
            if entry > ma20 * 1.02:
                # Prefer pullbacks toward / under short MA
                continue
            vr = volume_ratio(df, 20) or 1.0
            # Higher score when more oversold
            score = (rsi_max - r) / max(rsi_max, 1.0) + abs(min(ret_5, 0.0))
            out.append(
                StrategySignal(
                    ticker=ticker,
                    side="long",
                    score=round(float(score), 6),
                    strategy_id=self.id,
                    rationale=(
                        f"Oversold RSI={r:.0f}, 5d={ret_5*100:.1f}% vs MA20 "
                        f"(pullback mean-reversion)"
                    ),
                    suggested_size_mult=0.85,
                    entry=round(entry, 4),
                    volume_ratio=round(float(vr), 4),
                    momentum_pct=round(float(ret_5), 6),
                    meta={"rsi": round(r, 2), "ma20": round(ma20, 4)},
                )
            )

        out.sort(key=lambda s: s.score, reverse=True)
        return out[: int(getattr(cfg, "top_n", 20) or 20)]

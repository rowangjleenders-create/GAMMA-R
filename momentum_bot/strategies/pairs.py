"""Pairs / relative value — long strong twin, underweight weak twin (paper signals)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from ..config import StrategyConfig
from .base import Strategy, StrategySignal, last_close, pct_change

# Liquid equity twins (same industry / highly correlated)
DEFAULT_PAIRS: List[Tuple[str, str]] = [
    ("KO", "PEP"),
    ("V", "MA"),
    ("HD", "LOW"),
    ("JPM", "BAC"),
    ("XOM", "CVX"),
    ("MSFT", "AAPL"),
    ("GOOGL", "META"),
    ("UNH", "CVS"),
    ("WMT", "COST"),
    ("AVGO", "AMD"),
]


class PairsStrategy(Strategy):
    id = "pairs"
    name = "Pairs / relative value"
    description = "Long the relatively strong twin; flag weak twin for underweight (paper)."

    def generate_signals(
        self,
        universe: Sequence[str],
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[StrategySignal]:
        lookback = int(getattr(cfg, "pairs_lookback", 20) or 20)
        min_spread = float(getattr(cfg, "pairs_min_spread", 0.04) or 0.04)
        uni = {t.upper() for t in universe}
        out: List[StrategySignal] = []

        for a, b in DEFAULT_PAIRS:
            if a not in uni and a not in bars:
                continue
            if b not in uni and b not in bars:
                continue
            df_a, df_b = bars.get(a), bars.get(b)
            if df_a is None or df_b is None:
                continue
            ra, rb = pct_change(df_a, lookback), pct_change(df_b, lookback)
            ea, eb = last_close(df_a), last_close(df_b)
            if None in (ra, rb, ea, eb):
                continue
            spread = float(ra) - float(rb)
            if abs(spread) < min_spread:
                continue
            strong, weak = (a, b) if spread > 0 else (b, a)
            strong_ret, weak_ret = (ra, rb) if spread > 0 else (rb, ra)
            strong_entry = ea if spread > 0 else eb
            out.append(
                StrategySignal(
                    ticker=strong,
                    side="long",
                    score=round(abs(spread), 6),
                    strategy_id=self.id,
                    rationale=(
                        f"Pairs: long {strong} (relatively strong) vs underweight {weak}; "
                        f"{lookback}d spread {spread*100:.1f}%"
                    ),
                    suggested_size_mult=0.8,
                    entry=round(float(strong_entry), 4),
                    momentum_pct=round(float(strong_ret), 6),
                    meta={
                        "pair": [a, b],
                        "underweight": weak,
                        "spread": round(spread, 6),
                        "strong_ret": round(float(strong_ret), 6),
                        "weak_ret": round(float(weak_ret), 6),
                    },
                )
            )

        out.sort(key=lambda s: s.score, reverse=True)
        return out

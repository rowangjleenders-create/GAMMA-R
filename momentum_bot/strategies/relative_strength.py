"""Relative strength / sector rotation — prefer names beating peers & SPY."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from ..config import StrategyConfig
from .base import Strategy, StrategySignal, last_close, pct_change

# Lightweight sector twins / proxies (free data; best-effort)
SECTOR_ETFS: Dict[str, str] = {
    "XLK": "tech",
    "XLF": "financials",
    "XLE": "energy",
    "XLV": "health",
    "XLY": "consumer_disc",
    "XLP": "consumer_staples",
    "XLI": "industrials",
    "XLB": "materials",
    "XLU": "utilities",
    "XLRE": "real_estate",
    "XLC": "comms",
}

# Rough ticker → sector ETF mapping for liquid names (extend as needed)
TICKER_SECTOR: Dict[str, str] = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "AMD": "XLK",
    "GOOGL": "XLC", "GOOG": "XLC", "META": "XLC", "NFLX": "XLC",
    "JPM": "XLF", "BAC": "XLF", "GS": "XLF", "MS": "XLF", "V": "XLF", "MA": "XLF",
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE",
    "UNH": "XLV", "JNJ": "XLV", "LLY": "XLV", "ABBV": "XLV",
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "MCD": "XLY",
    "PG": "XLP", "KO": "XLP", "PEP": "XLP", "WMT": "XLP", "COST": "XLP",
    "CAT": "XLI", "GE": "XLI", "HON": "XLI",
    "LIN": "XLB", "FCX": "XLB",
    "NEE": "XLU", "DUK": "XLU",
    "AMT": "XLRE", "PLD": "XLRE",
}


class RelativeStrengthStrategy(Strategy):
    id = "relative_strength"
    name = "Relative strength"
    description = "Prefer names outperforming SPY / sector proxies (rotation tilt)."

    def generate_signals(
        self,
        universe: Sequence[str],
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[StrategySignal]:
        lookback = int(getattr(cfg, "rs_lookback", 20) or 20)
        min_price = float(getattr(cfg, "min_price", 5.0) or 5.0)
        spy_ret = pct_change(bars.get("SPY"), lookback) if bars.get("SPY") is not None else None
        # Fallback: median of universe as market proxy
        if spy_ret is None:
            rets = []
            for t in list(universe)[:80]:
                r = pct_change(bars.get(t), lookback)
                if r is not None:
                    rets.append(r)
            spy_ret = float(sorted(rets)[len(rets) // 2]) if rets else 0.0

        scored: List[Tuple[float, StrategySignal]] = []
        for ticker in universe:
            df = bars.get(ticker)
            if df is None:
                continue
            entry = last_close(df)
            if entry is None or entry < min_price:
                continue
            ret = pct_change(df, lookback)
            if ret is None:
                continue
            sector_etf = TICKER_SECTOR.get(ticker.upper())
            sector_ret = pct_change(bars.get(sector_etf), lookback) if sector_etf else None
            # Relative strength vs market (+ sector if available)
            rs_mkt = ret - float(spy_ret)
            rs_sec = (ret - float(sector_ret)) if sector_ret is not None else 0.0
            if rs_mkt < 0.02:  # need clear outperformance
                continue
            score = rs_mkt + 0.5 * rs_sec
            scored.append(
                (
                    score,
                    StrategySignal(
                        ticker=ticker,
                        side="long",
                        score=round(float(score), 6),
                        strategy_id=self.id,
                        rationale=(
                            f"RS vs market +{rs_mkt*100:.1f}% over {lookback}d"
                            + (f"; vs {sector_etf} +{rs_sec*100:.1f}%" if sector_etf else "")
                        ),
                        suggested_size_mult=1.05 if score > 0.05 else 1.0,
                        entry=round(entry, 4),
                        momentum_pct=round(float(ret), 6),
                        meta={
                            "rs_vs_spy": round(rs_mkt, 6),
                            "rs_vs_sector": round(rs_sec, 6) if sector_etf else None,
                            "sector_etf": sector_etf,
                        },
                    ),
                )
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[: int(getattr(cfg, "top_n", 20) or 20)]]

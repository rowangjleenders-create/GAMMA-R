"""Strategy plugin interface and normalized signal objects."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from ..config import StrategyConfig


@dataclass
class StrategySignal:
    """Normalized multi-strategy signal (paper-first)."""

    ticker: str
    side: str  # long | short | flat
    score: float
    strategy_id: str
    rationale: str
    suggested_size_mult: float = 1.0
    entry: Optional[float] = None
    stop: Optional[float] = None
    take_profit: Optional[float] = None
    volume_ratio: Optional[float] = None
    momentum_pct: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Strategy(ABC):
    """Plugin contract for GAMMA-R strategies."""

    id: str = "base"
    name: str = "Base"
    description: str = ""
    # Overlay strategies (e.g. vol-target) do not emit entry signals.
    is_overlay: bool = False

    @abstractmethod
    def generate_signals(
        self,
        universe: Sequence[str],
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[StrategySignal]:
        """Return zero or more normalized signals for this cycle."""

    def enabled(self, cfg: StrategyConfig) -> bool:
        enabled_map = getattr(cfg, "strategy_enabled", None) or {}
        if isinstance(enabled_map, dict) and self.id in enabled_map:
            return bool(enabled_map[self.id])
        return True


def last_close(df: pd.DataFrame) -> Optional[float]:
    if df is None or df.empty or "Close" not in df.columns:
        return None
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    return float(closes.iloc[-1])


def pct_change(df: pd.DataFrame, lookback: int) -> Optional[float]:
    closes = df["Close"].dropna() if df is not None and "Close" in getattr(df, "columns", []) else None
    if closes is None or len(closes) < lookback + 1:
        return None
    past = float(closes.iloc[-(lookback + 1)])
    now = float(closes.iloc[-1])
    if past <= 0:
        return None
    return (now - past) / past


def volume_ratio(df: pd.DataFrame, avg_days: int = 20) -> Optional[float]:
    if df is None or "Volume" not in getattr(df, "columns", []):
        return None
    vols = df["Volume"].dropna()
    if len(vols) < avg_days + 1:
        return None
    avg = float(vols.iloc[-(avg_days + 1) : -1].mean())
    today = float(vols.iloc[-1])
    if avg <= 0:
        return None
    return today / avg


def rsi(series: pd.Series, period: int = 14) -> Optional[float]:
    s = series.dropna().astype(float)
    if len(s) < period + 1:
        return None
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    if gain.empty or loss.empty:
        return None
    g = float(gain.iloc[-1])
    l = float(loss.iloc[-1])
    if l <= 0:
        return 100.0 if g > 0 else 50.0
    rs = g / l
    return 100.0 - (100.0 / (1.0 + rs))


def classic_momentum_return(
    df: pd.DataFrame,
    lookback: int = 252,
    skip: int = 21,
    *,
    short_fallback: int = 10,
) -> Optional[tuple]:
    """
    Classic 12–1 momentum: total return over `lookback` trading days,
    excluding the most recent `skip` days (≈12 months skip 1 month).

    Score = close[t - skip] / close[t - lookback] - 1

    Returns (momentum_pct, meta_dict) or None.
    Fallbacks when history is short:
      1. Scale lookback/skip down if we have ≥ skip+20 bars
      2. Else use short_fallback (no skip) if enough bars
    """
    closes = df["Close"].dropna() if df is not None and "Close" in getattr(df, "columns", []) else None
    if closes is None or closes.empty:
        return None
    n = len(closes)
    lookback = int(lookback or 252)
    skip = int(max(0, skip or 0))
    short_fallback = int(short_fallback or 10)

    if n >= lookback + 1 and skip < lookback:
        past = float(closes.iloc[-(lookback + 1)])
        near = float(closes.iloc[-(skip + 1)]) if skip > 0 else float(closes.iloc[-1])
        if past <= 0:
            return None
        mom = (near - past) / past
        return mom, {
            "mode": "12_1",
            "lookback_days": lookback,
            "skip_days": skip,
            "bars": n,
        }

    if n >= skip + 20 and n > 5:
        eff_lookback = n - 1
        eff_skip = min(skip, max(0, int(round(skip * (eff_lookback / max(lookback, 1))))))
        if eff_skip >= eff_lookback:
            eff_skip = max(0, eff_lookback // 12)
        past = float(closes.iloc[0])
        near = float(closes.iloc[-(eff_skip + 1)]) if eff_skip > 0 else float(closes.iloc[-1])
        if past <= 0:
            return None
        mom = (near - past) / past
        return mom, {
            "mode": "12_1_scaled",
            "lookback_days": eff_lookback,
            "skip_days": eff_skip,
            "bars": n,
            "requested_lookback": lookback,
            "requested_skip": skip,
        }

    if n >= short_fallback + 1:
        past = float(closes.iloc[-(short_fallback + 1)])
        now = float(closes.iloc[-1])
        if past <= 0:
            return None
        mom = (now - past) / past
        return mom, {
            "mode": "short_fallback",
            "lookback_days": short_fallback,
            "skip_days": 0,
            "bars": n,
            "requested_lookback": lookback,
            "requested_skip": skip,
        }
    return None


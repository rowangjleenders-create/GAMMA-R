"""
FX mean reversion (majors) — informational + paper signals only.

Aligns with momentum_bot.currency majors panel. Does not place live FX orders.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from ..config import StrategyConfig
from .base import Strategy, StrategySignal, last_close, pct_change, rsi


def _fx_bars_from_currency() -> Dict[str, pd.DataFrame]:
    """Best-effort history for major pairs via yfinance (reuse currency symbols)."""
    try:
        from ..currency import MAJOR_PAIRS
    except Exception:
        return {}
    out: Dict[str, pd.DataFrame] = {}
    try:
        import yfinance as yf
    except Exception:
        return {}
    for meta in MAJOR_PAIRS:
        symbol = meta["symbol"]
        pair = meta["pair"]
        try:
            hist = yf.Ticker(symbol).history(period="3mo", auto_adjust=True)
            if hist is not None and not hist.empty:
                out[pair] = hist
                out[symbol] = hist
        except Exception:
            continue
    return out


class FxMeanReversionStrategy(Strategy):
    id = "fx_mean_reversion"
    name = "FX mean reversion"
    description = "Mean-reversion tilts on major FX pairs (informational / paper only)."

    def generate_signals(
        self,
        universe: Sequence[str],
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[StrategySignal]:
        if not bool(getattr(cfg, "use_currency_panel", True)):
            return []

        context = context or {}
        fx_bars: Mapping[str, pd.DataFrame] = context.get("fx_bars") or {}
        if not fx_bars:
            # Prefer bars already keyed as FX pairs (reuse currency module / parallel worker).
            # Avoid network fetch during equity scans — optional only if fetch_fx=True.
            fx_keys = [
                k for k in bars.keys()
                if str(k).endswith("=X") or (
                    len(str(k).replace("=X", "")) == 6 and str(k).replace("=X", "").isalpha()
                )
            ]
            if fx_keys:
                fx_bars = {k: bars[k] for k in fx_keys}
            elif context.get("fetch_fx"):
                fx_bars = _fx_bars_from_currency()
        if not fx_bars:
            return []

        out: List[StrategySignal] = []
        seen = set()
        for key, df in fx_bars.items():
            pair = str(key).replace("=X", "").upper()
            if pair in seen or len(pair) != 6:
                continue
            seen.add(pair)
            if df is None or len(df) < 30:
                continue
            entry = last_close(df)
            closes = df["Close"].dropna().astype(float)
            r = rsi(closes, 14)
            ret_5 = pct_change(df, 5)
            if entry is None or r is None or ret_5 is None:
                continue
            # Fade stretched moves
            side = None
            if r <= 30 and ret_5 <= -0.01:
                side = "long"  # expect bounce in quote currency terms
            elif r >= 70 and ret_5 >= 0.01:
                side = "short"
            if not side:
                continue
            score = abs(50 - r) / 50.0 + abs(float(ret_5))
            out.append(
                StrategySignal(
                    ticker=pair,
                    side=side,
                    score=round(float(score), 6),
                    strategy_id=self.id,
                    rationale=(
                        f"FX MR {pair}: RSI={r:.0f}, 5d={ret_5*100:.2f}% → paper {side} "
                        f"(informational; not live FX)"
                    ),
                    suggested_size_mult=0.0,  # do not size into equity book by default
                    entry=round(float(entry), 6),
                    momentum_pct=round(float(ret_5), 6),
                    meta={"rsi": round(r, 2), "asset_class": "fx", "paper_only": True},
                )
            )

        out.sort(key=lambda s: s.score, reverse=True)
        return out[:8]

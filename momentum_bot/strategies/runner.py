"""
Orchestrate router + strategy plugins → merged scanner Signals.

Keeps momentum-only behavior when other entry strategies are disabled.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from ..config import StrategyConfig
from . import (
    DEFAULT_STRATEGY_ENABLED,
    get_registry,
    get_strategy,
    list_strategies,
)
from .base import StrategySignal
from .earnings_drift import earnings_provider_status, fetch_recent_earnings
from .router import RouterDecision, get_last_router_decision, route_strategies
from .vol_target import compute_vol_target_mult

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
LAST_CYCLE_PATH = DATA_DIR / "strategy_last_cycle.json"

_LAST_CYCLE: Dict[str, Any] = {}


def get_last_cycle() -> Dict[str, Any]:
    if _LAST_CYCLE:
        return dict(_LAST_CYCLE)
    if LAST_CYCLE_PATH.exists():
        try:
            return json.loads(LAST_CYCLE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_last_cycle(payload: Dict[str, Any]) -> None:
    global _LAST_CYCLE
    _LAST_CYCLE = dict(payload)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LAST_CYCLE_PATH.write_text(json.dumps(payload, indent=2, default=str))
    except OSError:
        pass


def _enabled_map(cfg: StrategyConfig) -> Dict[str, bool]:
    raw = getattr(cfg, "strategy_enabled", None)
    base = dict(DEFAULT_STRATEGY_ENABLED)
    if isinstance(raw, dict):
        base.update({str(k): bool(v) for k, v in raw.items()})
    return base


def _news_tilt(news_items: Optional[list], cfg: StrategyConfig) -> float:
    if not news_items or not getattr(cfg, "use_news_sentiment", True):
        return 0.0
    try:
        from ..news import sector_sentiment_impact
        impact = sector_sentiment_impact(news_items) or []
        if not impact:
            return 0.0
        scores = []
        for row in impact[:12]:
            if isinstance(row, dict):
                s = row.get("score") or row.get("sentiment") or row.get("avg_score")
                if s is not None:
                    scores.append(float(s))
        if not scores:
            return 0.0
        return sum(scores) / len(scores)
    except Exception:
        return 0.0


def generate_strategy_signals(
    universe: Sequence[str],
    bars: Mapping[str, pd.DataFrame],
    cfg: StrategyConfig,
    *,
    regime: Any = None,
    news_items: Optional[list] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[List[StrategySignal], RouterDecision, Dict[str, Any]]:
    """
    Run router + enabled strategies. Returns (signals, decision, cycle_meta).
    """
    context = dict(context or {})
    enabled = _enabled_map(cfg)
    fx_ok = bool(getattr(cfg, "use_currency_panel", True))
    earn_status = earnings_provider_status()
    earnings_events = []
    if enabled.get("earnings_drift"):
        try:
            earnings_events = fetch_recent_earnings(universe, lookback_days=5)
        except Exception:
            earnings_events = []
    context["earnings_events"] = earnings_events

    news_t = _news_tilt(news_items, cfg)
    decision = route_strategies(
        cfg,
        regime=regime,
        news_tilt=news_t,
        enabled_ids=[sid for sid, on in enabled.items() if on],
        fx_available=fx_ok,
        earnings_available=bool(earnings_events),
    )

    vol_info = None
    if enabled.get("vol_target") and "vol_target" in (decision.active + list(decision.weights.keys())):
        vol_info = compute_vol_target_mult(bars, cfg)
        decision.vol_target = vol_info
    vol_mult = float((vol_info or {}).get("multiplier") or 1.0)

    registry = get_registry()
    collected: List[StrategySignal] = []
    fired: List[str] = []

    for sid in decision.active:
        if sid == "vol_target":
            continue
        if not enabled.get(sid, False):
            continue
        strat = registry.get(sid) or get_strategy(sid)
        if strat is None or strat.is_overlay:
            continue
        try:
            sigs = strat.generate_signals(universe, bars, cfg, context=context)
        except Exception as exc:  # noqa: BLE001
            print(f"[strategies] {sid} failed: {exc}")
            continue
        w = float(decision.size_mults.get(sid, decision.weights.get(sid, 1.0)))
        if sigs:
            fired.append(sid)
        for s in sigs:
            # Scale score lightly by router weight; multiply size by router + vol-target
            s.score = round(float(s.score) * max(0.1, w), 6)
            s.suggested_size_mult = round(
                float(s.suggested_size_mult or 1.0) * w * vol_mult,
                4,
            )
            collected.append(s)

    # Deduplicate by ticker: keep highest score (strategy competition)
    best: Dict[str, StrategySignal] = {}
    for s in collected:
        # FX paper signals stay informational — keep them but they'll get size 0
        key = s.ticker.upper()
        prev = best.get(key)
        if prev is None or s.score > prev.score:
            best[key] = s
    merged = list(best.values())
    merged.sort(key=lambda s: s.score, reverse=True)

    cycle = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "router": decision.to_dict(),
        "fired": fired,
        "signal_count": len(merged),
        "by_strategy": {
            sid: sum(1 for s in merged if s.strategy_id == sid) for sid in fired
        },
        "vol_target": vol_info,
        "enabled": enabled,
        "top": [
            {
                "ticker": s.ticker,
                "strategy_id": s.strategy_id,
                "score": s.score,
                "side": s.side,
                "rationale": s.rationale,
                "suggested_size_mult": s.suggested_size_mult,
            }
            for s in merged[:12]
        ],
        "earnings_provider": earn_status,
        "strategies": list_strategies(),
    }
    _save_last_cycle(cycle)
    return merged, decision, cycle


def strategy_signals_to_scanner_signals(
    strategy_signals: Sequence[StrategySignal],
    cfg: StrategyConfig,
    *,
    equity: float,
    regime: Any = None,
    as_of: str = "",
    source: str = "scan",
) -> List[Any]:
    """Convert StrategySignal → scanner.Signal for paper auto-trade path."""
    from ..scanner import Signal
    from ..risk import size_position

    mult_regime = 1.0
    regime_label = None
    if regime is not None:
        mult_regime = float(getattr(regime, "size_multiplier", None) or (regime.get("size_multiplier") if isinstance(regime, dict) else 1.0) or 1.0)
        regime_label = getattr(regime, "label", None) or (regime.get("label") if isinstance(regime, dict) else None)

    out = []
    for ss in strategy_signals:
        # Skip FX / non-equity for the equity paper book (informational only)
        if (ss.meta or {}).get("asset_class") == "fx":
            continue
        if ss.side not in ("long", "buy"):
            continue
        entry = float(ss.entry or 0.0)
        if entry <= 0:
            continue
        size_mult = float(ss.suggested_size_mult or 1.0) * mult_regime
        sized_equity = max(0.0, float(equity) * max(0.0, size_mult))
        try:
            plan = size_position(ss.ticker, entry, sized_equity if sized_equity > 0 else equity * 0.01, cfg)
        except Exception:
            continue
        if plan.shares <= 0 and sized_equity > 0:
            continue
        mom = float(ss.momentum_pct if ss.momentum_pct is not None else ss.score)
        sig = Signal(
            ticker=ss.ticker,
            momentum_pct=round(mom, 6),
            entry=plan.entry,
            volume=0.0,
            volume_avg=0.0,
            volume_ratio=float(ss.volume_ratio or 1.0),
            stop=plan.stop,
            take_profit=plan.take_profit,
            shares=plan.shares,
            position_value=plan.position_value,
            dollar_risk=plan.dollar_risk,
            source=source if ss.strategy_id == "momentum" else f"strategy:{ss.strategy_id}",
            as_of=as_of,
            regime=regime_label,
            regime_size_mult=mult_regime,
            blended_score=round(float(ss.score), 6),
            confidence=min(0.95, max(0.2, 0.45 + float(ss.score) * 2)),
        )
        # Attach multi-strategy fields (dataclass may not list them — set attrs)
        try:
            sig.strategy_id = ss.strategy_id  # type: ignore[attr-defined]
            sig.strategy_rationale = ss.rationale  # type: ignore[attr-defined]
            sig.suggested_size_mult = ss.suggested_size_mult  # type: ignore[attr-defined]
            sig.side = ss.side  # type: ignore[attr-defined]
        except Exception:
            pass
        out.append(sig)
    return out


def only_momentum_enabled(cfg: StrategyConfig) -> bool:
    """True when no other *entry* strategies are enabled (vol_target overlay ok)."""
    enabled = _enabled_map(cfg)
    entry_ids = [
        sid for sid, on in enabled.items()
        if on and sid not in ("vol_target",)
    ]
    return entry_ids == ["momentum"] or entry_ids == []

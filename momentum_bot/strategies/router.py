"""
Strategy router / allocator.

Chooses which strategies are active this cycle and assigns weights / size
multipliers from regime, optional news tilt, and recent journal performance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..config import StrategyConfig


# Tunable priors (overridable via cfg.strategy_router_priors)
DEFAULT_PRIORS: Dict[str, Dict[str, float]] = {
    # trend / vol label → strategy_id → prior weight
    "bull": {
        "momentum": 1.0,
        "breakout": 0.9,
        "relative_strength": 0.7,
        "mean_reversion": 0.25,
        "pairs": 0.3,
        "earnings_drift": 0.5,
        "fx_mean_reversion": 0.35,
        "vol_target": 1.0,
    },
    "bear": {
        "momentum": 0.35,
        "breakout": 0.2,
        "relative_strength": 0.55,
        "mean_reversion": 0.45,
        "pairs": 0.6,
        "earnings_drift": 0.3,
        "fx_mean_reversion": 0.5,
        "vol_target": 1.0,
    },
    "sideways": {
        "momentum": 0.35,
        "breakout": 0.3,
        "relative_strength": 0.45,
        "mean_reversion": 1.0,
        "pairs": 0.85,
        "earnings_drift": 0.4,
        "fx_mean_reversion": 0.55,
        "vol_target": 1.0,
    },
    "high_vol": {
        "momentum": 0.4,
        "breakout": 0.25,
        "relative_strength": 0.75,  # prefer quality RS
        "mean_reversion": 0.35,
        "pairs": 0.5,
        "earnings_drift": 0.25,
        "fx_mean_reversion": 0.45,
        "vol_target": 1.0,  # shrink via overlay
    },
}

# Minimum weight to consider a strategy "active" in auto mode
ACTIVE_FLOOR = 0.35


@dataclass
class RouterDecision:
    mode: str
    regime_label: str
    trend: str
    vol_regime: str
    active: List[str]
    weights: Dict[str, float]
    size_mults: Dict[str, float]
    reasons: Dict[str, str] = field(default_factory=dict)
    news_tilt: Optional[float] = None
    performance_tilt: Dict[str, float] = field(default_factory=dict)
    vol_target: Optional[Dict[str, Any]] = None
    crash_mode: Optional[Dict[str, Any]] = None
    scoreboard_tilt: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_LAST_DECISION: Optional[RouterDecision] = None


def get_last_router_decision() -> Optional[RouterDecision]:
    return _LAST_DECISION


def _regime_key(regime: Any) -> str:
    if regime is None:
        return "sideways"
    if isinstance(regime, dict):
        label = str(regime.get("label") or "")
        trend = str(regime.get("trend") or "")
        vol = str(regime.get("vol_regime") or "")
    else:
        label = str(getattr(regime, "label", "") or "")
        trend = str(getattr(regime, "trend", "") or "")
        vol = str(getattr(regime, "vol_regime", "") or "")
    if label == "high_vol" or vol == "high":
        return "high_vol"
    if trend in DEFAULT_PRIORS:
        return trend
    if label in DEFAULT_PRIORS:
        return label
    return "sideways"


def _journal_performance_tilt() -> Dict[str, float]:
    """Mild boost/penalty from recent journal by strategy_id (if tagged)."""
    try:
        from ..learning import load_journal
        entries = load_journal() or []
    except Exception:
        return {}
    stats: Dict[str, Dict[str, float]] = {}
    for e in entries[-80:]:
        if not isinstance(e, dict):
            continue
        sid = (
            e.get("strategy_id")
            or (e.get("context") or {}).get("strategy_id")
            or (e.get("signal") or {}).get("strategy_id")
        )
        if not sid:
            continue
        pnl = e.get("realized_pnl")
        if pnl is None:
            pnl = e.get("pnl")
        if pnl is None:
            continue
        bucket = stats.setdefault(str(sid), {"n": 0.0, "pnl": 0.0})
        bucket["n"] += 1
        bucket["pnl"] += float(pnl)
    tilt: Dict[str, float] = {}
    for sid, b in stats.items():
        if b["n"] < 3:
            continue
        avg = b["pnl"] / b["n"]
        # Soft tilt ±0.15
        tilt[sid] = max(-0.15, min(0.15, avg / 500.0))
    return tilt


def route_strategies(
    cfg: StrategyConfig,
    *,
    regime: Any = None,
    news_tilt: Optional[float] = None,
    enabled_ids: Optional[Sequence[str]] = None,
    fx_available: bool = False,
    earnings_available: bool = False,
    performance_tilt: Optional[Mapping[str, float]] = None,
) -> RouterDecision:
    """
    Select active strategies + weights for this cycle.

    router_mode:
      auto   — regime priors + news/performance tilts
      manual — all enabled strategies at weight 1.0
    """
    global _LAST_DECISION
    mode = str(getattr(cfg, "router_mode", "auto") or "auto").lower()
    enabled_map = getattr(cfg, "strategy_enabled", None) or {}
    if not isinstance(enabled_map, dict):
        enabled_map = {}

    from . import all_strategy_ids, get_strategy

    all_ids = list(enabled_ids) if enabled_ids is not None else all_strategy_ids()
    # Respect config toggles
    candidates = []
    for sid in all_ids:
        if sid in enabled_map and not enabled_map[sid]:
            continue
        if sid not in enabled_map:
            # default: use plugin default via Strategy.enabled
            strat = get_strategy(sid)
            if strat and not strat.enabled(cfg):
                continue
        candidates.append(sid)

    priors_cfg = getattr(cfg, "strategy_router_priors", None) or {}
    rkey = _regime_key(regime)
    base = dict(DEFAULT_PRIORS.get(rkey, DEFAULT_PRIORS["sideways"]))
    if isinstance(priors_cfg, dict) and rkey in priors_cfg and isinstance(priors_cfg[rkey], dict):
        base.update({k: float(v) for k, v in priors_cfg[rkey].items()})

    perf = dict(performance_tilt) if performance_tilt is not None else _journal_performance_tilt()
    scoreboard_tilt: Dict[str, float] = {}
    try:
        from ..scoreboard import scoreboard_performance_tilt
        scoreboard_tilt = scoreboard_performance_tilt(cfg)
        for sid, t in scoreboard_tilt.items():
            perf[sid] = float(perf.get(sid, 0.0)) + float(t)
    except Exception:
        scoreboard_tilt = {}
    news = float(news_tilt) if news_tilt is not None else 0.0

    weights: Dict[str, float] = {}
    reasons: Dict[str, str] = {}
    size_mults: Dict[str, float] = {}

    if mode == "manual":
        for sid in candidates:
            weights[sid] = 1.0
            size_mults[sid] = 1.0
            reasons[sid] = "manual mode — all enabled strategies active"
        active = list(candidates)
    else:
        for sid in candidates:
            w = float(base.get(sid, 0.4))
            # Data availability gates
            if sid == "fx_mean_reversion" and not fx_available:
                if not bool(getattr(cfg, "use_currency_panel", True)):
                    reasons[sid] = "FX panel disabled"
                    continue
                # Still allow attempt; runner may no-op
                reasons[sid] = "FX panel on — may no-op if quotes thin"
            if sid == "earnings_drift" and not earnings_available:
                reasons[sid] = "no earnings events this cycle — may no-op"
                # keep low weight but allow
                w *= 0.5

            # News tilt: positive news slightly favors momentum/breakout/RS
            if news > 0.15 and sid in ("momentum", "breakout", "relative_strength"):
                w += 0.1
                reasons[sid] = (reasons.get(sid) or "") + f" news tilt +{news:.2f};"
            elif news < -0.15 and sid in ("mean_reversion", "pairs"):
                w += 0.1
                reasons[sid] = (reasons.get(sid) or "") + f" defensive news tilt;"

            # Performance tilt
            if sid in perf:
                w += float(perf[sid])
                reasons[sid] = (reasons.get(sid) or "") + f" journal tilt {perf[sid]:+.2f};"

            # Regime explanation
            if sid not in reasons:
                reasons[sid] = f"prior for regime={rkey}"

            weights[sid] = round(max(0.0, w), 4)
            size_mults[sid] = round(max(0.0, min(1.5, w)), 4)

        # High-vol: shrink non-overlay via size (vol_target also applies later)
        if rkey == "high_vol":
            for sid in list(size_mults.keys()):
                if sid != "vol_target":
                    size_mults[sid] = round(size_mults[sid] * 0.7, 4)

        active = [
            sid for sid, w in weights.items()
            if sid == "vol_target" or w >= ACTIVE_FLOOR
        ]
        # Always keep at least momentum if enabled
        if "momentum" in candidates and "momentum" not in active:
            active.append("momentum")
            weights["momentum"] = max(weights.get("momentum", 0.0), ACTIVE_FLOOR)
            size_mults["momentum"] = max(size_mults.get("momentum", 0.0), 0.5)
            reasons["momentum"] = (reasons.get("momentum") or "") + " floor keep;"

    if isinstance(regime, dict):
        trend = str(regime.get("trend") or rkey)
        vol = str(regime.get("vol_regime") or "")
        label = str(regime.get("label") or rkey)
    else:
        trend = str(getattr(regime, "trend", rkey) if regime else rkey)
        vol = str(getattr(regime, "vol_regime", "") if regime else "")
        label = str(getattr(regime, "label", rkey) if regime else rkey)

    decision = RouterDecision(
        mode=mode,
        regime_label=label,
        trend=trend,
        vol_regime=vol,
        active=active,
        weights=weights,
        size_mults=size_mults,
        reasons={k: v.strip() for k, v in reasons.items()},
        news_tilt=news_tilt,
        performance_tilt=dict(perf),
        scoreboard_tilt=dict(scoreboard_tilt),
    )
    # Crash / regime-shock overlay (cuts momentum/breakout; prefers defensive)
    try:
        from ..crash_mode import apply_crash_to_router, get_crash_status
        crash = get_crash_status(cfg)
        decision = apply_crash_to_router(decision, crash=crash, cfg=cfg)
        decision.crash_mode = crash.to_dict()
    except Exception as exc:  # noqa: BLE001
        decision.crash_mode = {"error": str(exc), "active": False}
    _LAST_DECISION = decision
    return decision


def explain_choice(strategy_id: str, decision: Optional[RouterDecision] = None) -> str:
    """Human-readable why a strategy was chosen (for co-pilot / UI)."""
    decision = decision or _LAST_DECISION
    if decision is None:
        return f"{strategy_id}: no router decision yet this process."
    if strategy_id not in decision.active and strategy_id != "vol_target":
        return (
            f"{strategy_id} was not active "
            f"(regime={decision.regime_label}, weight={decision.weights.get(strategy_id, 0):.2f}). "
            f"Reason: {decision.reasons.get(strategy_id, 'below active floor')}"
        )
    return (
        f"{strategy_id} active under regime={decision.regime_label} "
        f"(trend={decision.trend}, vol={decision.vol_regime}), "
        f"weight={decision.weights.get(strategy_id, 0):.2f}, "
        f"size_mult={decision.size_mults.get(strategy_id, 1):.2f}. "
        f"Why: {decision.reasons.get(strategy_id, 'regime prior')}"
    )

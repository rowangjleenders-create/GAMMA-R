"""
Trade confidence score (0–1) for signals / journal / auto-trade.

Combines momentum strength, volume surge, forward estimate, and ensemble
agreement into one visible score. Used to prefer high-confidence entries.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .config import StrategyConfig, get_runtime_config


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def compute_confidence(
    *,
    momentum_pct: float = 0.0,
    volume_ratio: float = 1.0,
    forward_probability: Optional[float] = None,
    forward_confidence: Optional[float] = None,
    ensemble_votes: Optional[Dict[str, float]] = None,
    cfg: Optional[StrategyConfig] = None,
) -> float:
    """
    Weighted blend → 0..1.

    Components (when available):
      - momentum vs min_return (stronger = higher)
      - volume_ratio vs volume_multiple
      - forward_probability / forward_confidence
      - ensemble vote agreement
    """
    cfg = cfg or get_runtime_config()
    parts: list[tuple[float, float]] = []  # (weight, score)

    # Momentum: 0 at min_return, ~1 at ~3x min_return (or 15% abs)
    mr = float(cfg.min_return or 0.05)
    mom_span = max(mr * 2.0, 0.10)
    mom_score = _clamp01((float(momentum_pct) - mr) / mom_span) if mom_span else 0.5
    parts.append((0.30, mom_score))

    # Volume: 0 at threshold, 1 at 2x threshold
    vm = float(cfg.volume_multiple or 1.5)
    vol_score = _clamp01((float(volume_ratio) - vm) / max(vm, 0.5))
    parts.append((0.20, vol_score))

    if forward_probability is not None:
        thr = float(cfg.forward_estimate_threshold or 0.55)
        # Map [thr-0.15, thr+0.25] → [0, 1]
        fp = float(forward_probability)
        fwd = _clamp01((fp - (thr - 0.15)) / 0.40)
        parts.append((0.30, fwd))
        if forward_confidence is not None:
            parts.append((0.10, _clamp01(float(forward_confidence))))

    if ensemble_votes and isinstance(ensemble_votes, dict) and len(ensemble_votes) >= 2:
        vals = [float(v) for v in ensemble_votes.values() if v is not None]
        if vals:
            # Agreement: how many votes are above threshold
            thr = float(cfg.forward_estimate_threshold or 0.55)
            agree = sum(1 for v in vals if v >= thr) / len(vals)
            parts.append((0.15, agree))

    if not parts:
        return 0.5
    wsum = sum(w for w, _ in parts)
    score = sum(w * s for w, s in parts) / wsum if wsum else 0.5
    return round(_clamp01(score), 4)


def confidence_from_signal(sig: Any, cfg: Optional[StrategyConfig] = None) -> float:
    """Extract fields from a Signal dataclass or dict."""
    cfg = cfg or get_runtime_config()
    if isinstance(sig, dict):
        return compute_confidence(
            momentum_pct=float(sig.get("momentum_pct") or 0),
            volume_ratio=float(sig.get("volume_ratio") or 1),
            forward_probability=sig.get("forward_probability"),
            forward_confidence=sig.get("forward_confidence"),
            ensemble_votes=sig.get("ensemble_votes"),
            cfg=cfg,
        )
    return compute_confidence(
        momentum_pct=float(getattr(sig, "momentum_pct", 0) or 0),
        volume_ratio=float(getattr(sig, "volume_ratio", 1) or 1),
        forward_probability=getattr(sig, "forward_probability", None),
        forward_confidence=getattr(sig, "forward_confidence", None),
        ensemble_votes=getattr(sig, "ensemble_votes", None),
        cfg=cfg,
    )

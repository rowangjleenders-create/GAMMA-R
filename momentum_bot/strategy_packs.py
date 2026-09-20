"""
One-tap strategy packs (StockHero-style templates).

Applying a pack updates strategy_enabled (+ light router hints) and persists
the runtime overlay. Paper-first; does not unlock live trading.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

# Canonical strategy ids used by the router / suite
_ALL = (
    "momentum",
    "mean_reversion",
    "breakout",
    "relative_strength",
    "vol_target",
    "pairs",
    "fx_mean_reversion",
    "earnings_drift",
)


def _map(enabled: Dict[str, bool]) -> Dict[str, bool]:
    out = {sid: False for sid in _ALL}
    out.update({k: bool(v) for k, v in enabled.items() if k in out})
    return out


PACKS: Dict[str, Dict[str, Any]] = {
    "classic_momentum_12_1": {
        "id": "classic_momentum_12_1",
        "name": "Classic Momentum 12-1",
        "description": "12–1 momentum core + vol-target overlay. Best in trending bull regimes.",
        "beats_at": "Beats mean-reversion in sustained bull trends (classic 12-1 paper path).",
        "strategy_enabled": _map({
            "momentum": True,
            "vol_target": True,
            "relative_strength": True,
        }),
        "router_hints": {
            "router_mode": "auto",
            "prefer": ["momentum", "relative_strength"],
            "size_note": "Vol-target scales size; momentum drives entries.",
        },
        "config_tweaks": {
            "momentum_lookback_days": 252,
            "momentum_skip_days": 21,
        },
    },
    "sideways_mean_reversion": {
        "id": "sideways_mean_reversion",
        "name": "Sideways Mean-Reversion",
        "description": "Mean-reversion + pairs for range-bound / choppy markets. Momentum/breakout off.",
        "beats_at": "Beats momentum in sideways / chop regimes (paper).",
        "strategy_enabled": _map({
            "mean_reversion": True,
            "pairs": True,
            "vol_target": True,
            "fx_mean_reversion": True,
        }),
        "router_hints": {
            "router_mode": "auto",
            "prefer": ["mean_reversion", "pairs"],
            "size_note": "Defensive sizing via vol-target; no trend chasing.",
        },
        "config_tweaks": {},
    },
    "global_rs_rotation": {
        "id": "global_rs_rotation",
        "name": "Global RS Rotation",
        "description": "Relative strength + momentum across the multi-region universe.",
        "beats_at": "Beats US-only lists when international RS leads (paper).",
        "strategy_enabled": _map({
            "relative_strength": True,
            "momentum": True,
            "vol_target": True,
            "earnings_drift": True,
        }),
        "router_hints": {
            "router_mode": "auto",
            "prefer": ["relative_strength", "momentum"],
            "size_note": "RS leads; earnings drift as satellite.",
        },
        "config_tweaks": {
            "universe": "combined",
        },
    },
    "conservative_vol_target": {
        "id": "conservative_vol_target",
        "name": "Conservative Vol-Target",
        "description": "Lower risk: vol-target + mean-reversion + RS only. Smaller crash exposure.",
        "beats_at": "Beats aggressive packs on max DD in risk-off stretches (paper).",
        "strategy_enabled": _map({
            "vol_target": True,
            "mean_reversion": True,
            "relative_strength": True,
        }),
        "router_hints": {
            "router_mode": "auto",
            "prefer": ["mean_reversion", "relative_strength"],
            "size_note": "Conservative — trend breakouts disabled.",
        },
        "config_tweaks": {
            "vol_target_annual": 0.10,
            "max_position_pct": 0.06,
            "risk_per_trade": 0.005,
        },
    },

    "crash_defensive": {
        "id": "crash_defensive",
        "name": "Crash-Defensive",
        "description": "Defensive sleeve when markets shock: mean-reversion + pairs + vol-target; momentum/breakout off.",
        "beats_at": "Beats trend-chasing in crash / high-vol regimes (paper context).",
        "strategy_enabled": _map({
            "mean_reversion": True,
            "pairs": True,
            "vol_target": True,
            "fx_mean_reversion": True,
            "relative_strength": True,
        }),
        "router_hints": {
            "router_mode": "auto",
            "prefer": ["mean_reversion", "pairs", "vol_target"],
            "size_note": "Crash-aware sizing; aggressive trend entries disabled.",
        },
        "config_tweaks": {
            "crash_mode_enabled": True,
            "vol_target_annual": 0.10,
            "max_position_pct": 0.05,
            "risk_per_trade": 0.005,
        },
    },
    "earnings_drift_focus": {
        "id": "earnings_drift_focus",
        "name": "Earnings Drift Focus",
        "description": "PEAD / post-earnings drift core with RS + momentum satellite.",
        "beats_at": "Beats pure momentum around earnings windows when surprise data is available (paper).",
        "strategy_enabled": _map({
            "earnings_drift": True,
            "relative_strength": True,
            "momentum": True,
            "vol_target": True,
        }),
        "router_hints": {
            "router_mode": "auto",
            "prefer": ["earnings_drift", "relative_strength"],
            "size_note": "Earnings drift leads; vol-target caps size.",
        },
        "config_tweaks": {
            "pead_min_surprise": 0.03,
        },
    },
    "fx_mean_reversion_overlay": {
        "id": "fx_mean_reversion_overlay",
        "name": "FX Mean-Reversion Overlay",
        "description": "FX mean-reversion + equity mean-reversion/pairs overlay; trend strategies muted.",
        "beats_at": "Beats equity-only sleeves in FX-driven chop (informational FX panel + paper).",
        "strategy_enabled": _map({
            "fx_mean_reversion": True,
            "mean_reversion": True,
            "pairs": True,
            "vol_target": True,
        }),
        "router_hints": {
            "router_mode": "auto",
            "prefer": ["fx_mean_reversion", "mean_reversion"],
            "size_note": "FX overlay; use_currency_panel stays on.",
        },
        "config_tweaks": {
            "use_currency_panel": True,
        },
    },
    "multi_strategy_auto": {
        "id": "multi_strategy_auto",
        "name": "Multi-Strategy Auto",
        "description": "Router default: all seeded strategies on, router_mode=auto (regime picks the sleeve).",
        "beats_at": "Beats single-strategy lock-in across regime shifts (paper scoreboard).",
        "strategy_enabled": _map({
            "momentum": True,
            "mean_reversion": True,
            "breakout": True,
            "relative_strength": True,
            "vol_target": True,
            "pairs": True,
            "fx_mean_reversion": True,
            "earnings_drift": True,
        }),
        "router_hints": {
            "router_mode": "auto",
            "prefer": [],
            "size_note": "Full suite; router weights by regime + scoreboard tilt.",
        },
        "config_tweaks": {
            "router_mode": "auto",
            "scoreboard_router_downweight": True,
        },
    },
    "high_conviction_top_n": {
        "id": "high_conviction_top_n",
        "name": "High-Conviction Top-N",
        "description": "Fewer, higher-conviction names: tighter top_pct, higher min_confidence, momentum+RS+breakout.",
        "beats_at": "Beats scattershot universes when you want concentrated paper book.",
        "strategy_enabled": _map({
            "momentum": True,
            "relative_strength": True,
            "breakout": True,
            "vol_target": True,
        }),
        "router_hints": {
            "router_mode": "auto",
            "prefer": ["momentum", "relative_strength", "breakout"],
            "size_note": "High bar to enter; size still vol-capped.",
        },
        "config_tweaks": {
            "top_pct": 0.05,
            "top_n": 8,
            "min_confidence": 0.60,
            "max_concurrent_positions": 3,
            "max_position_pct": 0.12,
        },
    },

    "defaults": {
        "id": "defaults",
        "name": "Reset defaults (all seeded strategies)",
        "description": "Re-enable the day-one strategy_enabled map from SEED (all suite strategies on).",
        "beats_at": "Baseline restore — not a performance claim.",
        "strategy_enabled": None,  # filled from seed at apply time
        "router_hints": {
            "router_mode": "auto",
            "prefer": [],
            "size_note": "Seed defaults restored for strategy toggles.",
        },
        "config_tweaks": {},
        "reset_strategy_enabled": True,
    },
}


def list_packs() -> List[Dict[str, Any]]:
    out = []
    for p in PACKS.values():
        out.append({
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
            "beats_at": p.get("beats_at") or "",
            "strategy_enabled": p.get("strategy_enabled"),
            "router_hints": p.get("router_hints") or {},
            "config_tweaks": p.get("config_tweaks") or {},
            "reset": bool(p.get("reset_strategy_enabled")),
        })
    return out


def get_pack(pack_id: str) -> Optional[Dict[str, Any]]:
    return PACKS.get((pack_id or "").strip().lower())



def preview_pack(pack_id: str, cfg: Any = None) -> Dict[str, Any]:
    """
    Preview what applying a pack would change (no persist).
    Returns current vs proposed strategy_enabled + config tweaks.
    """
    from .config import SEED_DEFAULTS, get_runtime_config

    pid = (pack_id or "").strip().lower()
    pack = get_pack(pid)
    if not pack:
        return {"ok": False, "error": f"unknown pack: {pack_id}", "known": list(PACKS.keys())}

    cfg = cfg or get_runtime_config()
    current = dict(getattr(cfg, "strategy_enabled", None) or {})
    if pack.get("reset_strategy_enabled"):
        proposed = dict(SEED_DEFAULTS.get("strategy_enabled") or {})
    else:
        proposed = dict(pack.get("strategy_enabled") or {})

    toggles_on = sorted(k for k, v in proposed.items() if v and not current.get(k))
    toggles_off = sorted(k for k, v in current.items() if v and not proposed.get(k))
    unchanged_on = sorted(k for k, v in proposed.items() if v and current.get(k))

    return {
        "ok": True,
        "pack": {
            "id": pack["id"],
            "name": pack["name"],
            "description": pack["description"],
            "beats_at": pack.get("beats_at") or "",
        },
        "current_strategy_enabled": current,
        "proposed_strategy_enabled": proposed,
        "toggles_on": toggles_on,
        "toggles_off": toggles_off,
        "unchanged_on": unchanged_on,
        "config_tweaks": dict(pack.get("config_tweaks") or {}),
        "router_hints": pack.get("router_hints") or {},
        "note": "Preview only — POST .../apply to commit. Paper-first; does not unlock live.",
        "label": "PAPER — pack preview",
    }

def apply_pack(pack_id: str, cfg: Any = None) -> Dict[str, Any]:
    """
    Apply pack to runtime config and persist overlay.
    Returns {ok, pack, strategy_enabled, config_tweaks_applied, note}.
    """
    from .config import (
        SEED_DEFAULTS,
        get_runtime_config,
        save_runtime_overlay,
        set_runtime_config,
    )

    pid = (pack_id or "").strip().lower()
    pack = get_pack(pid)
    if not pack:
        return {"ok": False, "error": f"unknown pack: {pack_id}", "known": list(PACKS.keys())}

    cfg = cfg or get_runtime_config()
    updates: Dict[str, Any] = {}

    if pack.get("reset_strategy_enabled"):
        seed_map = dict(SEED_DEFAULTS.get("strategy_enabled") or {})
        updates["strategy_enabled"] = seed_map
    else:
        updates["strategy_enabled"] = dict(pack.get("strategy_enabled") or {})

    hints = pack.get("router_hints") or {}
    if hints.get("router_mode"):
        updates["router_mode"] = hints["router_mode"]

    tweaks = dict(pack.get("config_tweaks") or {})
    # Map friendly tweak aliases → live StrategyConfig fields
    alias = {
        "vol_target_annual": "vol_target_annual",
        "max_position_pct": "max_position_pct",
        "risk_per_trade": "risk_per_trade",
        "universe": "universe",
        "momentum_lookback_days": "momentum_lookback_days",
        "momentum_skip_days": "momentum_skip_days",
        "crash_mode_enabled": "crash_mode_enabled",
        "pead_min_surprise": "pead_min_surprise",
        "use_currency_panel": "use_currency_panel",
        "router_mode": "router_mode",
        "scoreboard_router_downweight": "scoreboard_router_downweight",
        "top_pct": "top_pct",
        "top_n": "top_n",
        "min_confidence": "min_confidence",
        "max_concurrent_positions": "max_concurrent_positions",
    }
    applied_tweaks = {}
    cfg_dict = cfg.to_dict() if hasattr(cfg, "to_dict") else {}
    for k, v in tweaks.items():
        field = alias.get(k, k)
        if field in cfg_dict or hasattr(cfg, field):
            updates[field] = v
            applied_tweaks[field] = v

    # Soft router prior hint — store prefer list on a dedicated overlay key if present,
    # otherwise skip (router_mode still applied).
    prefer = list(hints.get("prefer") or [])
    if prefer and "strategy_router_priors" in cfg_dict:
        existing = getattr(cfg, "strategy_router_priors", None)
        if isinstance(existing, dict):
            priors = dict(existing)
            for i, sid in enumerate(prefer):
                priors[sid] = max(float(priors.get(sid) or 0), 0.55 - 0.05 * i)
            updates["strategy_router_priors"] = priors
        # if list/other — leave untouched to avoid type fights with parallel workers

    new_cfg = cfg.update(updates) if hasattr(cfg, "update") else cfg
    set_runtime_config(new_cfg)
    try:
        save_runtime_overlay(new_cfg)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": True,
            "pack": {k: pack[k] for k in ("id", "name", "description") if k in pack},
            "strategy_enabled": updates.get("strategy_enabled"),
            "config_tweaks_applied": applied_tweaks,
            "router_hints": hints,
            "persist_warning": str(exc),
            "note": "Pack applied in memory; overlay persist failed.",
            "label": "PAPER — pack does not enable live trading",
        }

    return {
        "ok": True,
        "pack": {k: pack[k] for k in ("id", "name", "description") if k in pack},
        "strategy_enabled": updates.get("strategy_enabled"),
        "config_tweaks_applied": applied_tweaks,
        "router_hints": hints,
        "note": f"Applied pack '{pack['name']}'. Paper-first; live trading unchanged.",
        "label": "PAPER — pack does not enable live trading",
    }

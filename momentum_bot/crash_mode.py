"""
Crash / regime-shock mode.

Detects sharp short-window drops/rebounds + vol spikes on SPY/QQQ (or a
broad proxy). When active: cut momentum + breakout size (or pause new
entries for those strategies), prefer mean-reversion / defensive / cash.
Exits always remain allowed.

State: data/crash_mode_state.json
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_PATH = DATA_DIR / "crash_mode_state.json"

# Strategies whose NEW entries are cut / paused in crash mode
AGGRESSIVE_STRATEGIES = frozenset({"momentum", "breakout"})
DEFENSIVE_STRATEGIES = frozenset({"mean_reversion", "pairs", "fx_mean_reversion", "vol_target"})

_lock = threading.RLock()
_STATE: Optional[Dict[str, Any]] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or _utc_now()
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        raw = str(s).replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


@dataclass
class CrashStatus:
    enabled: bool
    active: bool
    until: Optional[str] = None
    triggered_at: Optional[str] = None
    reason: str = ""
    proxies: Dict[str, Any] = field(default_factory=dict)
    size_mult: float = 1.0
    pause_aggressive_entries: bool = False
    cooldown_days: int = 3
    lookback: int = 5
    threshold_pct: float = -0.03
    vol_mult: float = 2.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.active and self.until:
            d["label"] = f"Crash mode: ON until {self.until}"
        elif self.enabled:
            d["label"] = "Crash mode: OFF (armed)"
        else:
            d["label"] = "Crash mode: disabled"
        return d


def _default_state() -> Dict[str, Any]:
    return {
        "active": False,
        "until": None,
        "triggered_at": None,
        "reason": "",
        "proxies": {},
        "history": [],
        "updated_at": _utc_iso(),
    }


def load_state() -> Dict[str, Any]:
    global _STATE
    with _lock:
        if _STATE is not None:
            return dict(_STATE)
        if STATE_PATH.exists():
            try:
                raw = json.loads(STATE_PATH.read_text())
                if isinstance(raw, dict):
                    base = _default_state()
                    base.update(raw)
                    _STATE = base
                    return dict(_STATE)
            except (json.JSONDecodeError, OSError):
                pass
        _STATE = _default_state()
        return dict(_STATE)


def save_state(st: Dict[str, Any]) -> None:
    global _STATE
    with _lock:
        st = dict(st)
        st["updated_at"] = _utc_iso()
        hist = list(st.get("history") or [])
        st["history"] = hist[-40:]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, indent=2, default=str))
        _STATE = st


def clear_crash_mode(reason: str = "manual clear") -> Dict[str, Any]:
    st = load_state()
    st["active"] = False
    st["until"] = None
    st["reason"] = reason
    st.setdefault("history", []).append({"at": _utc_iso(), "event": "cleared", "reason": reason})
    save_state(st)
    logger.info("[crash_mode] cleared: %s", reason)
    return st


def activate_crash_mode(
    *,
    reason: str,
    cooldown_days: int = 3,
    proxies: Optional[Dict[str, Any]] = None,
    until: Optional[datetime] = None,
) -> Dict[str, Any]:
    st = load_state()
    end = until or (_utc_now() + timedelta(days=max(1, int(cooldown_days))))
    st["active"] = True
    st["until"] = _utc_iso(end)
    st["triggered_at"] = _utc_iso()
    st["reason"] = reason
    st["proxies"] = proxies or {}
    st.setdefault("history", []).append({
        "at": st["triggered_at"],
        "event": "activated",
        "reason": reason,
        "until": st["until"],
        "proxies": st["proxies"],
    })
    save_state(st)
    print(f"[crash_mode] ACTIVATED until {st['until']} — {reason}", flush=True)
    return st


def _expire_if_needed(st: Dict[str, Any]) -> Dict[str, Any]:
    if not st.get("active"):
        return st
    until = _parse_iso(st.get("until"))
    if until is None:
        return st
    if _utc_now() >= until:
        st["active"] = False
        st["reason"] = f"cooldown expired at {st.get('until')}"
        st.setdefault("history", []).append({
            "at": _utc_iso(),
            "event": "expired",
            "until": st.get("until"),
        })
        save_state(st)
        print(f"[crash_mode] expired — was until {st.get('until')}", flush=True)
    return st


def _cfg_vals(cfg: Any) -> Dict[str, Any]:
    return {
        "enabled": bool(getattr(cfg, "crash_mode_enabled", True)),
        "lookback": int(getattr(cfg, "crash_lookback", 5) or 5),
        "threshold_pct": float(getattr(cfg, "crash_threshold_pct", -0.03) or -0.03),
        "vol_mult": float(getattr(cfg, "crash_vol_mult", 2.0) or 2.0),
        "cooldown_days": int(getattr(cfg, "crash_cooldown_days", 3) or 3),
        "size_mult": float(getattr(cfg, "crash_size_mult", 0.25) or 0.25),
    }


def _realized_vol(closes: Sequence[float], window: int = 20) -> Optional[float]:
    if len(closes) < window + 1:
        return None
    import math
    rets = []
    for i in range(-window, 0):
        a, b = float(closes[i - 1]), float(closes[i])
        if a <= 0:
            continue
        rets.append(b / a - 1.0)
    if len(rets) < max(5, window // 2):
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def evaluate_proxy_frame(
    closes: Sequence[float],
    *,
    lookback: int,
    threshold_pct: float,
    vol_mult: float,
) -> Dict[str, Any]:
    """
    Evaluate one price series for crash/shock.

    Triggers when:
      - short-window return <= threshold_pct (large drop), OR
      - short-window rebound from an intermediate low >= |threshold| after a drop, AND
      - short-window vol spiked vs longer baseline (vol_mult), OR drop alone is severe.
    """
    out: Dict[str, Any] = {"ok": False, "triggered": False}
    n = len(closes)
    lb = max(2, int(lookback))
    if n < lb + 5:
        out["reason"] = "insufficient bars"
        return out
    c_now = float(closes[-1])
    c_prev = float(closes[-(lb + 1)])
    if c_prev <= 0:
        out["reason"] = "bad prior close"
        return out
    ret = c_now / c_prev - 1.0
    # Rebound: drop within window then bounce
    window = [float(x) for x in closes[-(lb + 1) :]]
    lo = min(window)
    hi_before_lo_idx = window.index(lo)
    rebound = (c_now / lo - 1.0) if lo > 0 else 0.0
    drop_to_low = (lo / window[0] - 1.0) if window[0] > 0 else 0.0

    short_vol = _realized_vol(closes, window=min(lb, 10))
    long_vol = _realized_vol(closes, window=min(60, max(20, lb * 4)))
    vol_ratio = None
    if short_vol is not None and long_vol is not None and long_vol > 1e-9:
        vol_ratio = short_vol / long_vol

    thr = float(threshold_pct)
    # threshold is typically negative (e.g. -0.03)
    drop_hit = ret <= thr
    # Rebound shock: intermediate drop at least thr, then rebound >= |thr|
    rebound_hit = drop_to_low <= thr and rebound >= abs(thr) and hi_before_lo_idx < len(window) - 1
    vol_hit = vol_ratio is not None and vol_ratio >= float(vol_mult)
    # Severe drop alone (>= 1.5x threshold magnitude) triggers without vol
    severe = ret <= thr * 1.5 if thr < 0 else ret <= thr

    triggered = False
    reasons: List[str] = []
    if drop_hit and (vol_hit or severe):
        triggered = True
        reasons.append(f"drop {ret:.2%} over {lb}d")
        if vol_hit:
            reasons.append(f"vol_ratio={vol_ratio:.2f}x")
        if severe and not vol_hit:
            reasons.append("severe drop")
    elif rebound_hit and (vol_hit or abs(drop_to_low) >= abs(thr) * 1.25):
        triggered = True
        reasons.append(f"rebound {rebound:.2%} after {drop_to_low:.2%} dip")
        if vol_hit:
            reasons.append(f"vol_ratio={vol_ratio:.2f}x")

    out.update({
        "ok": True,
        "triggered": triggered,
        "ret": round(ret, 6),
        "rebound": round(rebound, 6),
        "drop_to_low": round(drop_to_low, 6),
        "short_vol": round(short_vol, 6) if short_vol is not None else None,
        "long_vol": round(long_vol, 6) if long_vol is not None else None,
        "vol_ratio": round(vol_ratio, 4) if vol_ratio is not None else None,
        "reason": "; ".join(reasons) if reasons else "no shock",
    })
    return out


def _fetch_closes(ticker: str, period: str = "6mo") -> List[float]:
    try:
        from .data import download_ohlcv
        df = download_ohlcv([ticker], period=period, batch_size=1).get(ticker)
        if df is None or df.empty:
            return []
        return [float(x) for x in df["Close"].astype(float).tolist()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("crash_mode fetch %s failed: %s", ticker, exc)
        return []


def detect_crash(
    cfg: Any = None,
    *,
    frames: Optional[Dict[str, Sequence[float]]] = None,
    force_check: bool = True,
) -> CrashStatus:
    """
    Check proxies and (re)activate crash mode if shock detected.
    If already active and not expired, keep active without re-triggering.
    """
    from .config import get_runtime_config

    cfg = cfg or get_runtime_config()
    vals = _cfg_vals(cfg)
    st = _expire_if_needed(load_state())

    status = CrashStatus(
        enabled=vals["enabled"],
        active=bool(st.get("active")),
        until=st.get("until"),
        triggered_at=st.get("triggered_at"),
        reason=str(st.get("reason") or ""),
        proxies=dict(st.get("proxies") or {}),
        size_mult=vals["size_mult"],
        pause_aggressive_entries=True,
        cooldown_days=vals["cooldown_days"],
        lookback=vals["lookback"],
        threshold_pct=vals["threshold_pct"],
        vol_mult=vals["vol_mult"],
    )

    if not vals["enabled"]:
        status.active = False
        status.reason = "crash_mode_enabled=false"
        return status

    if status.active and not force_check:
        return status

    # Always refresh expiry; optionally re-evaluate market
    proxies_cfg = ["SPY", "QQQ"]
    proxy_results: Dict[str, Any] = {}
    any_trigger = False
    reasons: List[str] = []

    for t in proxies_cfg:
        closes: Sequence[float]
        if frames and t in frames:
            closes = frames[t]
        else:
            closes = _fetch_closes(t)
        res = evaluate_proxy_frame(
            closes,
            lookback=vals["lookback"],
            threshold_pct=vals["threshold_pct"],
            vol_mult=vals["vol_mult"],
        )
        proxy_results[t] = res
        if res.get("triggered"):
            any_trigger = True
            reasons.append(f"{t}: {res.get('reason')}")

    status.proxies = proxy_results

    if any_trigger and not status.active:
        reason = "regime shock — " + "; ".join(reasons)
        activate_crash_mode(
            reason=reason,
            cooldown_days=vals["cooldown_days"],
            proxies=proxy_results,
        )
        st = load_state()
        status.active = True
        status.until = st.get("until")
        status.triggered_at = st.get("triggered_at")
        status.reason = reason
        status.proxies = proxy_results
    elif any_trigger and status.active:
        # Already in cooldown — refresh proxy snapshot but do not reset the timer
        status.proxies = proxy_results
        status.reason = status.reason or ("regime shock — " + "; ".join(reasons))
        st = load_state()
        st["proxies"] = proxy_results
        save_state(st)
    elif status.active:
        # Keep existing reason/proxies
        status.proxies = dict(st.get("proxies") or proxy_results)
    else:
        status.reason = status.reason or "no shock detected"
        status.proxies = proxy_results

    return status


def get_crash_status(cfg: Any = None, *, refresh: bool = False) -> CrashStatus:
    """Read status; optionally run detect_crash (network). Default: cheap state read."""
    from .config import get_runtime_config

    cfg = cfg or get_runtime_config()
    vals = _cfg_vals(cfg)
    if refresh and vals["enabled"]:
        return detect_crash(cfg, force_check=True)

    st = _expire_if_needed(load_state())
    return CrashStatus(
        enabled=vals["enabled"],
        active=bool(st.get("active")) and vals["enabled"],
        until=st.get("until") if vals["enabled"] else None,
        triggered_at=st.get("triggered_at"),
        reason=str(st.get("reason") or ("disabled" if not vals["enabled"] else "")),
        proxies=dict(st.get("proxies") or {}),
        size_mult=vals["size_mult"],
        pause_aggressive_entries=True,
        cooldown_days=vals["cooldown_days"],
        lookback=vals["lookback"],
        threshold_pct=vals["threshold_pct"],
        vol_mult=vals["vol_mult"],
    )


def apply_crash_to_router(
    decision: Any,
    crash: Optional[CrashStatus] = None,
    cfg: Any = None,
) -> Any:
    """
    Mutate / return router decision with crash overlays:
      - cut momentum/breakout size_mult (or remove from active if size→0)
      - boost mean_reversion / pairs mildly
    Exits are unaffected (router only gates new entries).
    """
    from .config import get_runtime_config

    cfg = cfg or get_runtime_config()
    crash = crash or get_crash_status(cfg)
    if not crash.active:
        return decision

    size_mult = float(crash.size_mult)
    pause = bool(crash.pause_aggressive_entries)

    weights = dict(getattr(decision, "weights", {}) or {})
    size_mults = dict(getattr(decision, "size_mults", {}) or {})
    reasons = dict(getattr(decision, "reasons", {}) or {})
    active = list(getattr(decision, "active", []) or [])

    for sid in list(weights.keys()):
        if sid in AGGRESSIVE_STRATEGIES:
            if pause or size_mult <= 0:
                size_mults[sid] = 0.0
                weights[sid] = min(weights.get(sid, 0.0), 0.15)
                reasons[sid] = (
                    (reasons.get(sid) or "") + f" crash_mode pause/cut (until {crash.until});"
                ).strip()
                if sid in active:
                    active = [x for x in active if x != sid]
            else:
                size_mults[sid] = round(float(size_mults.get(sid, 1.0)) * size_mult, 4)
                weights[sid] = round(float(weights.get(sid, 0.0)) * max(size_mult, 0.1), 4)
                reasons[sid] = (
                    (reasons.get(sid) or "") + f" crash_mode size×{size_mult};"
                ).strip()
        elif sid in DEFENSIVE_STRATEGIES and sid != "vol_target":
            boost = 1.15
            weights[sid] = round(float(weights.get(sid, 0.4)) * boost, 4)
            size_mults[sid] = round(min(1.5, float(size_mults.get(sid, 1.0)) * 1.1), 4)
            reasons[sid] = ((reasons.get(sid) or "") + " crash_mode defensive prefer;").strip()
            if sid not in active and weights[sid] >= 0.35:
                active.append(sid)

    # Prefer at least one defensive if we stripped aggressive
    if not any(s in active for s in ("mean_reversion", "pairs", "relative_strength")):
        for sid in ("mean_reversion", "pairs", "relative_strength"):
            if sid in weights:
                active.append(sid)
                size_mults[sid] = max(size_mults.get(sid, 0.5), 0.6)
                reasons[sid] = ((reasons.get(sid) or "") + " crash_mode floor defensive;").strip()
                break

    decision.active = active
    decision.weights = weights
    decision.size_mults = size_mults
    decision.reasons = {k: v.strip() for k, v in reasons.items()}
    # Attach for audit / UI
    try:
        decision.crash_mode = crash.to_dict()  # type: ignore[attr-defined]
    except Exception:
        pass
    return decision


def entry_allowed_for_strategy(strategy_id: Optional[str], cfg: Any = None) -> tuple[bool, str]:
    """Gate NEW entries for aggressive strategies when crash mode is on."""
    crash = get_crash_status(cfg)
    if not crash.active:
        return True, "crash_mode off"
    sid = (strategy_id or "").strip().lower()
    if sid in AGGRESSIVE_STRATEGIES:
        if crash.pause_aggressive_entries or crash.size_mult <= 0:
            return False, f"crash_mode: {sid} new entries paused until {crash.until}"
        return True, f"crash_mode: {sid} size×{crash.size_mult}"
    return True, "crash_mode: defensive/other ok"


def size_multiplier_for_strategy(strategy_id: Optional[str], cfg: Any = None) -> float:
    crash = get_crash_status(cfg)
    if not crash.active:
        return 1.0
    sid = (strategy_id or "").strip().lower()
    if sid in AGGRESSIVE_STRATEGIES:
        return float(crash.size_mult) if crash.size_mult > 0 and not crash.pause_aggressive_entries else 0.0
    if sid in DEFENSIVE_STRATEGIES:
        return 1.1
    return 1.0

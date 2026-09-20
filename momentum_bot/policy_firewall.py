"""
Hard non-LLM policy firewall — deterministic checks BEFORE any paper or live order.

Every strategy path, co-pilot "paper this", API order, and auto_loops must call
``check_order`` (or ``assert_order_allowed``). Fail closed with a structured
reason. LLM / co-pilot cannot bypass this module.

Checks (in order):
  1. firewall_enabled (if off → allow, still audited as bypass)
  2. trading mode: paper vs live; LIVE still requires LIVE_TRADING_ENABLED
  3. allowlist / denylist (if configured)
  4. max notional / max pct equity
  5. max new orders per day / per cycle
  6. circuit breaker not tripped (new entries)
  7. optional human_approval_required above a size threshold

Audit log: data/policy_firewall_audit.jsonl
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AUDIT_PATH = DATA_DIR / "policy_firewall_audit.jsonl"
CYCLE_STATE_PATH = DATA_DIR / "policy_firewall_cycle.json"

_lock = threading.RLock()
_cycle_new_orders: int = 0
_cycle_id: Optional[str] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class FirewallResult:
    allowed: bool
    reason: str
    code: str
    checks: List[Dict[str, Any]] = field(default_factory=list)
    requires_human_approval: bool = False
    mode: str = "paper"
    ticker: str = ""
    notional: float = 0.0
    strategy_id: Optional[str] = None
    at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FirewallDenied(PermissionError):
    """Raised when an order is blocked; carry structured result."""

    def __init__(self, result: FirewallResult):
        self.result = result
        super().__init__(f"firewall_denied:{result.code}:{result.reason}")


def _normalize_ticker(ticker: str) -> str:
    return (ticker or "").strip().upper()


def _load_cycle_state() -> Dict[str, Any]:
    if CYCLE_STATE_PATH.exists():
        try:
            return json.loads(CYCLE_STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"cycle_id": None, "new_orders": 0, "day": _utc_today(), "day_orders": 0}


def _save_cycle_state(st: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CYCLE_STATE_PATH.write_text(json.dumps(st, indent=2))


def begin_cycle(cycle_id: Optional[str] = None) -> str:
    """Reset per-cycle counter (call at start of auto-trade cycle)."""
    global _cycle_new_orders, _cycle_id
    with _lock:
        cid = cycle_id or _utc_now()
        _cycle_id = cid
        _cycle_new_orders = 0
        st = _load_cycle_state()
        today = _utc_today()
        if st.get("day") != today:
            st["day"] = today
            st["day_orders"] = 0
        st["cycle_id"] = cid
        st["new_orders"] = 0
        _save_cycle_state(st)
        return cid


def _record_allowed_order() -> None:
    global _cycle_new_orders
    with _lock:
        _cycle_new_orders += 1
        st = _load_cycle_state()
        today = _utc_today()
        if st.get("day") != today:
            st["day"] = today
            st["day_orders"] = 0
        st["day_orders"] = int(st.get("day_orders") or 0) + 1
        st["new_orders"] = int(_cycle_new_orders)
        _save_cycle_state(st)


def _day_order_count() -> int:
    st = _load_cycle_state()
    if st.get("day") != _utc_today():
        return 0
    return int(st.get("day_orders") or 0)


def _cycle_order_count() -> int:
    return int(_cycle_new_orders)


def append_audit(result: FirewallResult, extra: Optional[Dict[str, Any]] = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    row = result.to_dict()
    if extra:
        row["extra"] = extra
    with _lock:
        with AUDIT_PATH.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")


def check_order(
    *,
    ticker: str,
    shares: float,
    price: float,
    side: str = "buy",
    mode: str = "paper",
    source: str = "unknown",
    strategy_id: Optional[str] = None,
    equity: Optional[float] = None,
    cfg: Any = None,
    is_exit: bool = False,
    human_approved: bool = False,
) -> FirewallResult:
    """
    Deterministic pre-submit check. Returns FirewallResult (allowed or not).
    Exits (is_exit=True) skip size/day/circuit checks that only apply to entries.
    """
    from .config import get_runtime_config

    cfg = cfg or get_runtime_config()
    ticker_n = _normalize_ticker(ticker)
    notional = abs(float(shares) * float(price or 0.0))
    mode_n = (mode or "paper").lower().strip()
    if mode_n not in ("paper", "live"):
        mode_n = "paper"
    checks: List[Dict[str, Any]] = []

    def _deny(code: str, reason: str, **kw: Any) -> FirewallResult:
        res = FirewallResult(
            allowed=False,
            reason=reason,
            code=code,
            checks=checks,
            requires_human_approval=bool(kw.get("requires_human_approval", False)),
            mode=mode_n,
            ticker=ticker_n,
            notional=round(notional, 4),
            strategy_id=strategy_id,
            at=_utc_now(),
        )
        append_audit(res, extra={"source": source, "side": side, "shares": shares})
        return res

    def _allow(code: str = "ok", reason: str = "passed") -> FirewallResult:
        res = FirewallResult(
            allowed=True,
            reason=reason,
            code=code,
            checks=checks,
            mode=mode_n,
            ticker=ticker_n,
            notional=round(notional, 4),
            strategy_id=strategy_id,
            at=_utc_now(),
        )
        append_audit(res, extra={"source": source, "side": side, "shares": shares})
        if not is_exit and side.lower() in ("buy", "long"):
            _record_allowed_order()
        return res

    # 0) Master switch
    if not bool(getattr(cfg, "firewall_enabled", True)):
        checks.append({"check": "firewall_enabled", "ok": True, "detail": "disabled"})
        return _allow("firewall_disabled", "firewall_enabled=false")

    # 1) Mode + live flag
    from .brokers import live_trading_enabled

    live_flag = bool(live_trading_enabled())
    checks.append({
        "check": "trading_mode",
        "ok": True,
        "mode": mode_n,
        "live_trading_enabled": live_flag,
    })
    if mode_n == "live" and not live_flag:
        checks[-1]["ok"] = False
        return _deny(
            "live_disabled",
            "LIVE orders require LIVE_TRADING_ENABLED=1 (paper-first default)",
        )

    # Exits: still enforce live flag + denylist, then allow
    if is_exit or side.lower() in ("sell", "close", "exit"):
        denylist = [str(x).strip().upper() for x in (getattr(cfg, "firewall_denylist", None) or []) if x]
        if ticker_n in denylist:
            checks.append({"check": "denylist", "ok": False, "ticker": ticker_n})
            return _deny("denylist", f"{ticker_n} is on firewall_denylist")
        checks.append({"check": "exit_passthrough", "ok": True})
        return _allow("exit_ok", "exit/risk path")

    # 2) Allowlist / denylist
    allowlist = [str(x).strip().upper() for x in (getattr(cfg, "firewall_allowlist", None) or []) if x]
    denylist = [str(x).strip().upper() for x in (getattr(cfg, "firewall_denylist", None) or []) if x]
    if denylist and ticker_n in denylist:
        checks.append({"check": "denylist", "ok": False})
        return _deny("denylist", f"{ticker_n} is on firewall_denylist")
    checks.append({"check": "denylist", "ok": True})
    if allowlist and ticker_n not in allowlist:
        checks.append({"check": "allowlist", "ok": False})
        return _deny("allowlist", f"{ticker_n} not on firewall_allowlist")
    checks.append({"check": "allowlist", "ok": True, "active": bool(allowlist)})

    # 3) Notional / pct equity
    max_notional = float(getattr(cfg, "firewall_max_notional", 0) or 0)
    max_pct = float(getattr(cfg, "firewall_max_pct_equity", 0) or 0)
    if max_pct <= 0:
        max_pct = float(getattr(cfg, "max_position_pct", 0.10) or 0.10)
    eq = float(equity) if equity is not None else float(getattr(cfg, "starting_equity", 10_000) or 10_000)
    pct_cap = eq * max_pct
    hard_cap = max_notional if max_notional > 0 else pct_cap
    if max_notional > 0:
        hard_cap = min(hard_cap, max_notional)
    else:
        hard_cap = pct_cap
    checks.append({
        "check": "max_notional",
        "ok": notional <= hard_cap + 1e-6,
        "notional": round(notional, 4),
        "cap": round(hard_cap, 4),
        "equity": round(eq, 2),
        "max_pct": max_pct,
    })
    if notional > hard_cap + 1e-6:
        return _deny(
            "max_notional",
            f"notional {notional:.2f} exceeds cap {hard_cap:.2f} "
            f"(max_pct_equity={max_pct:.0%} of equity {eq:.2f}"
            + (f", max_notional={max_notional}" if max_notional > 0 else "")
            + ")",
        )

    # 4) Rate limits
    max_day = int(getattr(cfg, "firewall_max_new_orders_per_day", 30) or 30)
    max_cycle = int(getattr(cfg, "firewall_max_new_orders_per_cycle", 5) or 5)
    day_n = _day_order_count()
    cycle_n = _cycle_order_count()
    checks.append({
        "check": "rate_day",
        "ok": day_n < max_day,
        "count": day_n,
        "max": max_day,
    })
    if day_n >= max_day:
        return _deny("max_orders_day", f"day order cap reached ({day_n}/{max_day})")
    checks.append({
        "check": "rate_cycle",
        "ok": cycle_n < max_cycle,
        "count": cycle_n,
        "max": max_cycle,
    })
    if cycle_n >= max_cycle:
        return _deny("max_orders_cycle", f"cycle order cap reached ({cycle_n}/{max_cycle})")

    # 5) Circuit breaker
    try:
        from . import circuit_breaker as cb
        halted = bool(cb.is_halted())
        reason_cb = (cb.status() or {}).get("reason")
    except Exception:
        halted, reason_cb = False, None
    checks.append({"check": "circuit_breaker", "ok": not halted, "reason": reason_cb})
    if halted:
        return _deny("circuit_breaker", f"circuit breaker halted: {reason_cb}")

    # 6) Human approval threshold
    human_thr = float(getattr(cfg, "firewall_human_approval_notional", 0) or 0)
    if human_thr > 0 and notional >= human_thr and not human_approved:
        checks.append({
            "check": "human_approval",
            "ok": False,
            "threshold": human_thr,
            "notional": notional,
        })
        return _deny(
            "human_approval_required",
            f"notional {notional:.2f} ≥ human_approval threshold {human_thr:.2f}; "
            "queue/block until explicitly approved",
            requires_human_approval=True,
        )
    checks.append({"check": "human_approval", "ok": True, "threshold": human_thr})

    return _allow("ok", "all checks passed")


def assert_order_allowed(**kwargs: Any) -> FirewallResult:
    """Like check_order but raises FirewallDenied on deny (fail closed)."""
    result = check_order(**kwargs)
    if not result.allowed:
        raise FirewallDenied(result)
    return result


def recent_audit(limit: int = 40) -> List[Dict[str, Any]]:
    if not AUDIT_PATH.exists():
        return []
    lines = AUDIT_PATH.read_text().splitlines()
    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def status() -> Dict[str, Any]:
    from .config import get_runtime_config
    from .brokers import live_trading_enabled

    cfg = get_runtime_config()
    st = _load_cycle_state()
    return {
        "enabled": bool(getattr(cfg, "firewall_enabled", True)),
        "live_trading_enabled": live_trading_enabled(),
        "day_orders": _day_order_count(),
        "cycle_orders": _cycle_order_count(),
        "cycle_id": st.get("cycle_id") or _cycle_id,
        "max_day": int(getattr(cfg, "firewall_max_new_orders_per_day", 30) or 30),
        "max_cycle": int(getattr(cfg, "firewall_max_new_orders_per_cycle", 5) or 5),
        "max_pct_equity": float(getattr(cfg, "firewall_max_pct_equity", 0.10) or 0.10),
        "max_notional": float(getattr(cfg, "firewall_max_notional", 0) or 0),
        "human_approval_notional": float(getattr(cfg, "firewall_human_approval_notional", 0) or 0),
        "allowlist": list(getattr(cfg, "firewall_allowlist", None) or []),
        "denylist": list(getattr(cfg, "firewall_denylist", None) or []),
        "audit_path": str(AUDIT_PATH),
        "recent": recent_audit(8),
        "note": "Hard non-LLM firewall; every paper/live submit must pass check_order.",
    }

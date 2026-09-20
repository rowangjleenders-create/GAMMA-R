"""
Append-only decision audit trail.

Every auto / co-pilot decision cycle can persist a row to
data/decision_audit.jsonl with regime, crash_mode, router, signals,
firewall, session gate, and order/skip outcome.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AUDIT_PATH = DATA_DIR / "decision_audit.jsonl"

_lock = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_decision(row: Dict[str, Any]) -> Dict[str, Any]:
    """Append one decision cycle row. Returns the written payload."""
    payload = dict(row)
    payload.setdefault("timestamp", _utc_now())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, default=str)
    with _lock:
        with AUDIT_PATH.open("a") as f:
            f.write(line + "\n")
    return payload


def log_decision_cycle(
    *,
    source: str = "auto",
    regime: Any = None,
    crash_mode: Any = None,
    router_decision: Any = None,
    signals_considered: Optional[List[Any]] = None,
    strategy_id: Optional[str] = None,
    firewall: Any = None,
    order_id: Optional[str] = None,
    skip_reason: Optional[str] = None,
    session_gate: Any = None,
    ticker: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    def _as(obj: Any) -> Any:
        if obj is None:
            return None
        if hasattr(obj, "to_dict"):
            try:
                return obj.to_dict()
            except Exception:
                pass
        if isinstance(obj, dict):
            return obj
        return obj

    signals_out: List[Any] = []
    for s in (signals_considered or [])[:20]:
        if hasattr(s, "ticker"):
            signals_out.append({
                "ticker": getattr(s, "ticker", None),
                "strategy_id": getattr(s, "strategy_id", None),
                "confidence": getattr(s, "confidence", None),
                "entry": getattr(s, "entry", None),
            })
        elif isinstance(s, dict):
            signals_out.append({
                k: s.get(k) for k in ("ticker", "strategy_id", "confidence", "entry", "skip_reason")
                if k in s or k == "ticker"
            })
        else:
            signals_out.append(str(s)[:120])

    fw = _as(firewall)
    fw_allow = None
    fw_reason = None
    if isinstance(fw, dict):
        fw_allow = fw.get("allowed")
        fw_reason = fw.get("reason") or fw.get("code")

    row = {
        "timestamp": _utc_now(),
        "source": source,
        "ticker": ticker,
        "regime": _as(regime),
        "crash_mode": _as(crash_mode),
        "router_decision": _as(router_decision),
        "signals_considered": signals_out,
        "strategy_id": strategy_id,
        "firewall": fw,
        "firewall_allow": fw_allow,
        "firewall_reason": fw_reason,
        "order_id": order_id,
        "skip_reason": skip_reason,
        "session_gate": _as(session_gate) if not isinstance(session_gate, str) else {"result": session_gate},
    }
    if extra:
        row["extra"] = extra
    return append_decision(row)


def read_decisions(limit: int = 50) -> List[Dict[str, Any]]:
    """Read the most recent decision rows (tail of JSONL)."""
    limit = max(1, min(500, int(limit)))
    if not AUDIT_PATH.exists():
        return []
    with _lock:
        try:
            lines = AUDIT_PATH.read_text().splitlines()
        except OSError:
            return []
    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    out.reverse()  # newest first
    return out


def recent_decisions_summary(limit: int = 10) -> Dict[str, Any]:
    rows = read_decisions(limit=limit)
    return {
        "count": len(rows),
        "path": str(AUDIT_PATH),
        "decisions": rows,
    }

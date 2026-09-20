"""
Autonomous data-health circuit breaker.

Trips when the live feed looks stale/broken (old quotes, repeated fetch
failures, empty scans, SIP disconnect without healthy fallback, zero/unrealistic
prices). While OPEN: auto-trade halts new entries; learning continues.
Resumes automatically when the feed looks healthy again.

Thresholds start from sensible seeds and adapt (rule-based) from false trips /
missed bad data; persisted to data/circuit_breaker_state.json.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_PATH = DATA_DIR / "circuit_breaker_state.json"

SEED_THRESHOLDS: Dict[str, Any] = {
    "max_quote_age_sec": 900,          # 15 min — delayed free data tolerant
    "max_consecutive_fetch_failures": 3,
    "max_empty_scans": 2,
    "min_healthy_signals": 0,          # empty can be valid; trip on repeated empties
    "unrealistic_zero_price_count": 2,
    "resume_healthy_cycles": 2,        # need N healthy checks to resume
    "cooldown_sec_after_trip": 120,
}

_lock = threading.RLock()
_state: Dict[str, Any] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _default_state() -> Dict[str, Any]:
    return {
        "label": "circuit_breaker",
        "halted": False,
        "reason": None,
        "halted_since": None,
        "last_check_at": None,
        "last_resume_at": None,
        "consecutive_fetch_failures": 0,
        "consecutive_empty_scans": 0,
        "consecutive_healthy": 0,
        "zero_price_hits": 0,
        "last_quote_age_sec": None,
        "last_scan_count": None,
        "last_data_source": None,
        "events": [],
        "thresholds": dict(SEED_THRESHOLDS),
        "adapt_history": [],
        "false_trip_count": 0,
        "missed_bad_count": 0,
        "updated_at": _utc_now(),
    }


def load_state() -> Dict[str, Any]:
    global _state
    with _lock:
        if _state:
            return dict(_state)
        if STATE_PATH.exists():
            try:
                raw = json.loads(STATE_PATH.read_text())
                base = _default_state()
                base.update({k: v for k, v in raw.items() if k != "thresholds"})
                thr = dict(SEED_THRESHOLDS)
                thr.update(raw.get("thresholds") or {})
                base["thresholds"] = thr
                _state = base
                return dict(_state)
            except (json.JSONDecodeError, OSError):
                pass
        _state = _default_state()
        return dict(_state)


def save_state(st: Optional[Dict[str, Any]] = None) -> None:
    global _state
    with _lock:
        if st is not None:
            _state = st
        _ensure()
        _state["updated_at"] = _utc_now()
        # trim events
        ev = list(_state.get("events") or [])
        _state["events"] = ev[-80:]
        STATE_PATH.write_text(json.dumps(_state, indent=2))


def _append_event(st: Dict[str, Any], kind: str, detail: str) -> None:
    st.setdefault("events", []).append({"at": _utc_now(), "kind": kind, "detail": detail})


def is_halted() -> bool:
    return bool(load_state().get("halted"))


def status() -> Dict[str, Any]:
    st = load_state()
    return {
        "halted": bool(st.get("halted")),
        "reason": st.get("reason"),
        "halted_since": st.get("halted_since"),
        "last_check_at": st.get("last_check_at"),
        "last_resume_at": st.get("last_resume_at"),
        "thresholds": dict(st.get("thresholds") or SEED_THRESHOLDS),
        "seed_thresholds": dict(SEED_THRESHOLDS),
        "consecutive_fetch_failures": st.get("consecutive_fetch_failures", 0),
        "consecutive_empty_scans": st.get("consecutive_empty_scans", 0),
        "consecutive_healthy": st.get("consecutive_healthy", 0),
        "last_quote_age_sec": st.get("last_quote_age_sec"),
        "last_scan_count": st.get("last_scan_count"),
        "last_data_source": st.get("last_data_source"),
        "false_trip_count": st.get("false_trip_count", 0),
        "missed_bad_count": st.get("missed_bad_count", 0),
        "recent_events": list(st.get("events") or [])[-10:],
        "explanation": _explain(st),
        "updated_at": st.get("updated_at"),
    }


def _explain(st: Dict[str, Any]) -> str:
    if not st.get("halted"):
        return (
            "Data-health circuit closed — auto-trade may enter when other gates allow. "
            f"Thresholds adapted from seed (false_trips={st.get('false_trip_count', 0)})."
        )
    return (
        f"HALTED since {st.get('halted_since')}: {st.get('reason')}. "
        "No new auto-trade entries until feed looks healthy again. Learning continues."
    )


def _trip(st: Dict[str, Any], reason: str) -> None:
    if not st.get("halted"):
        st["halted"] = True
        st["halted_since"] = _utc_now()
        st["consecutive_healthy"] = 0
        _append_event(st, "trip", reason)
        print(f"[circuit_breaker] TRIP — {reason}")
    st["reason"] = reason


def _resume(st: Dict[str, Any], detail: str = "feed healthy") -> None:
    if st.get("halted"):
        st["halted"] = False
        st["reason"] = None
        st["last_resume_at"] = _utc_now()
        st["halted_since"] = None
        _append_event(st, "resume", detail)
        print(f"[circuit_breaker] RESUME — {detail}")


def record_fetch_failure(error: str = "fetch failed") -> Dict[str, Any]:
    st = load_state()
    thr = st["thresholds"]
    st["consecutive_fetch_failures"] = int(st.get("consecutive_fetch_failures") or 0) + 1
    st["consecutive_healthy"] = 0
    st["last_check_at"] = _utc_now()
    _append_event(st, "fetch_failure", error[:200])
    if st["consecutive_fetch_failures"] >= int(thr["max_consecutive_fetch_failures"]):
        _trip(st, f"repeated fetch failures ({st['consecutive_fetch_failures']}): {error[:120]}")
    save_state(st)
    return status()


def record_fetch_success() -> None:
    st = load_state()
    st["consecutive_fetch_failures"] = 0
    save_state(st)


def evaluate_after_scan(
    *,
    signal_count: int,
    quote_age_sec: Optional[float] = None,
    zero_price_count: int = 0,
    data_source: Optional[str] = None,
    sip_fallback: bool = False,
    sip_wanted: bool = False,
) -> Dict[str, Any]:
    """Call after each auto/manual scan to update breaker state."""
    st = load_state()
    thr = st["thresholds"]
    st["last_check_at"] = _utc_now()
    st["last_scan_count"] = int(signal_count)
    st["last_quote_age_sec"] = quote_age_sec
    st["last_data_source"] = data_source

    bad_reasons: List[str] = []

    if quote_age_sec is not None and quote_age_sec > float(thr["max_quote_age_sec"]):
        bad_reasons.append(f"stale quotes age={quote_age_sec:.0f}s > {thr['max_quote_age_sec']}s")

    if int(signal_count) <= int(thr.get("min_healthy_signals") or 0):
        st["consecutive_empty_scans"] = int(st.get("consecutive_empty_scans") or 0) + 1
        if st["consecutive_empty_scans"] >= int(thr["max_empty_scans"]):
            bad_reasons.append(f"empty/near-empty scans x{st['consecutive_empty_scans']}")
    else:
        st["consecutive_empty_scans"] = 0

    if zero_price_count >= int(thr["unrealistic_zero_price_count"]):
        st["zero_price_hits"] = int(st.get("zero_price_hits") or 0) + 1
        bad_reasons.append(f"unrealistic zero prices ({zero_price_count})")
    else:
        st["zero_price_hits"] = 0

    if sip_wanted and sip_fallback and data_source in ("free", "yfinance", None):
        # SIP wanted but fell back — not instant trip; count as soft failure
        st["consecutive_fetch_failures"] = int(st.get("consecutive_fetch_failures") or 0) + 1
        if st["consecutive_fetch_failures"] >= int(thr["max_consecutive_fetch_failures"]):
            bad_reasons.append("SIP disconnect without healthy SIP recovery")

    if bad_reasons:
        st["consecutive_healthy"] = 0
        _trip(st, "; ".join(bad_reasons))
    else:
        # healthy observation
        st["consecutive_fetch_failures"] = 0
        st["consecutive_healthy"] = int(st.get("consecutive_healthy") or 0) + 1
        need = int(thr["resume_healthy_cycles"])
        if st.get("halted") and st["consecutive_healthy"] >= need:
            _resume(st, f"{need} consecutive healthy checks")
        elif not st.get("halted"):
            st["reason"] = None

    save_state(st)
    return status()


def mark_false_trip(note: str = "manual false trip") -> Dict[str, Any]:
    """Owner feedback: halt was wrong → loosen thresholds slightly."""
    st = load_state()
    st["false_trip_count"] = int(st.get("false_trip_count") or 0) + 1
    thr = dict(st["thresholds"])
    thr["max_quote_age_sec"] = int(min(3600, thr["max_quote_age_sec"] * 1.15 + 30))
    thr["max_consecutive_fetch_failures"] = int(min(10, thr["max_consecutive_fetch_failures"] + 1))
    thr["max_empty_scans"] = int(min(6, thr["max_empty_scans"] + 1))
    st["thresholds"] = thr
    st.setdefault("adapt_history", []).append({
        "at": _utc_now(), "kind": "loosen", "note": note, "thresholds": dict(thr),
    })
    _append_event(st, "adapt_loosen", note)
    if st.get("halted"):
        _resume(st, f"false trip acknowledged: {note}")
    save_state(st)
    return status()


def mark_missed_bad(note: str = "missed bad data") -> Dict[str, Any]:
    """Owner feedback: should have halted → tighten thresholds."""
    st = load_state()
    st["missed_bad_count"] = int(st.get("missed_bad_count") or 0) + 1
    thr = dict(st["thresholds"])
    thr["max_quote_age_sec"] = int(max(120, thr["max_quote_age_sec"] * 0.85))
    thr["max_consecutive_fetch_failures"] = int(max(1, thr["max_consecutive_fetch_failures"] - 1))
    thr["max_empty_scans"] = int(max(1, thr["max_empty_scans"] - 1))
    st["thresholds"] = thr
    st.setdefault("adapt_history", []).append({
        "at": _utc_now(), "kind": "tighten", "note": note, "thresholds": dict(thr),
    })
    _append_event(st, "adapt_tighten", note)
    save_state(st)
    return status()


def force_resume(note: str = "manual resume") -> Dict[str, Any]:
    st = load_state()
    _resume(st, note)
    st["consecutive_healthy"] = int(st["thresholds"].get("resume_healthy_cycles") or 2)
    save_state(st)
    return status()


def force_halt(reason: str = "manual halt") -> Dict[str, Any]:
    st = load_state()
    _trip(st, reason)
    save_state(st)
    return status()


def reset_thresholds_to_seed() -> Dict[str, Any]:
    st = load_state()
    st["thresholds"] = dict(SEED_THRESHOLDS)
    _append_event(st, "reset_thresholds", "restored seed")
    save_state(st)
    return status()

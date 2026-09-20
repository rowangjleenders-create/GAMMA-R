"""
In-app / push alert hooks (paper-first).

Fires on: crash mode ON, intraday heat spike, strategy cut on scoreboard,
firewall deny streak. Settings toggles gate each channel. Uses existing
notify stub (Expo push tokens) — never claims delivery guarantees.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_PATH = DATA_DIR / "alerts_state.json"
LOG_PATH = DATA_DIR / "alerts.jsonl"

_lock = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "last_crash_alert_at": None,
        "last_heat_alert_at": None,
        "last_cut_alert_at": None,
        "last_firewall_alert_at": None,
        "last_fired": [],
        "updated_at": None,
    }


def _save_state(st: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    st["updated_at"] = _utc_now()
    STATE_PATH.write_text(json.dumps(st, indent=2), encoding="utf-8")


def _append_log(entry: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _cooldown_ok(last_at: Optional[str], minutes: float = 30.0) -> bool:
    if not last_at:
        return True
    try:
        # Parse Zulu
        ts = last_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        age = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
        return age >= minutes * 60.0
    except Exception:
        return True


def alert_settings(cfg: Any = None) -> Dict[str, bool]:
    from .config import get_runtime_config

    cfg = cfg or get_runtime_config()
    return {
        "alerts_enabled": bool(getattr(cfg, "alerts_enabled", True)),
        "alert_crash_mode": bool(getattr(cfg, "alert_crash_mode", True)),
        "alert_intraday_heat": bool(getattr(cfg, "alert_intraday_heat", True)),
        "alert_strategy_cut": bool(getattr(cfg, "alert_strategy_cut", True)),
        "alert_firewall_deny_streak": bool(getattr(cfg, "alert_firewall_deny_streak", True)),
    }


def _dispatch(title: str, body: str, kind: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {
        "ts": _utc_now(),
        "kind": kind,
        "title": title,
        "body": body,
        "extra": extra or {},
    }
    _append_log(payload)
    # Hook into API notify stub when available
    try:
        from .api import _stub_notify  # type: ignore

        _stub_notify({"title": title, "body": body, "kind": kind, **(extra or {})})
    except Exception:
        print(f"[alerts] {kind}: {title} — {body}")
    return payload


def evaluate_alerts(cfg: Any = None, *, force: bool = False) -> Dict[str, Any]:
    """Scan conditions and fire alerts subject to Settings toggles + cooldown."""
    from .config import get_runtime_config

    cfg = cfg or get_runtime_config()
    toggles = alert_settings(cfg)
    fired: List[Dict[str, Any]] = []
    checked: List[str] = []

    if not toggles["alerts_enabled"] and not force:
        return {
            "ok": True,
            "fired": [],
            "checked": [],
            "skipped": "alerts_enabled=false",
            "settings": toggles,
        }

    with _lock:
        st = _load_state()

        # 1) Crash mode ON
        checked.append("crash_mode")
        if toggles["alert_crash_mode"] or force:
            try:
                from .crash_mode import get_crash_status

                crash = get_crash_status(cfg).to_dict()
                if crash.get("active") and (_cooldown_ok(st.get("last_crash_alert_at"), 45) or force):
                    ev = _dispatch(
                        "Crash mode ON",
                        str(crash.get("reason") or crash.get("label") or "Regime shock active")[:200],
                        "crash_mode",
                        {"until": crash.get("until")},
                    )
                    fired.append(ev)
                    st["last_crash_alert_at"] = _utc_now()
            except Exception as exc:  # noqa: BLE001
                checked.append(f"crash_err:{exc}")

        # 2) Intraday heat spike
        checked.append("intraday_heat")
        if toggles["alert_intraday_heat"] or force:
            try:
                from .intraday_heat import scan_intraday_heat

                heat = scan_intraday_heat(cfg, force=False)
                hits = heat.get("hits") or []
                top = hits[0] if hits else None
                score = float((top or {}).get("score") or (top or {}).get("heat") or 0)
                if top and score >= 1.5 and (_cooldown_ok(st.get("last_heat_alert_at"), 20) or force):
                    ev = _dispatch(
                        "Intraday heat spike",
                        f"{top.get('ticker')}: score={score:.2f} — {(top.get('reason') or top.get('label') or '')[:120]}",
                        "intraday_heat",
                        {"ticker": top.get("ticker"), "score": score},
                    )
                    fired.append(ev)
                    st["last_heat_alert_at"] = _utc_now()
            except Exception as exc:  # noqa: BLE001
                checked.append(f"heat_err:{exc}")

        # 3) Strategy cut on scoreboard
        checked.append("strategy_cut")
        if toggles["alert_strategy_cut"] or force:
            try:
                from .scoreboard import build_scoreboard

                board = build_scoreboard(cfg)
                cuts = [
                    s
                    for s in (board.get("strategies") or [])
                    if str(s.get("status") or "").lower() == "cut"
                ]
                if cuts and (_cooldown_ok(st.get("last_cut_alert_at"), 120) or force):
                    names = ", ".join(str(c.get("strategy_id")) for c in cuts[:4])
                    ev = _dispatch(
                        "Strategy cut on scoreboard",
                        f"Cut: {names}. Router may down-weight — review Learning.",
                        "strategy_cut",
                        {"cuts": [c.get("strategy_id") for c in cuts]},
                    )
                    fired.append(ev)
                    st["last_cut_alert_at"] = _utc_now()
            except Exception as exc:  # noqa: BLE001
                checked.append(f"cut_err:{exc}")

        # 4) Firewall deny streak
        checked.append("firewall_deny_streak")
        if toggles["alert_firewall_deny_streak"] or force:
            try:
                from .policy_firewall import recent_audit

                recent = recent_audit(20)
                denies = [r for r in recent if not r.get("allowed", True)]
                streak = 0
                for r in reversed(recent):
                    if not r.get("allowed", True):
                        streak += 1
                    else:
                        break
                threshold = int(getattr(cfg, "alert_firewall_deny_threshold", 3) or 3)
                if streak >= threshold and (_cooldown_ok(st.get("last_firewall_alert_at"), 30) or force):
                    last = denies[-1] if denies else {}
                    ev = _dispatch(
                        "Firewall deny streak",
                        f"{streak} consecutive denies. Last: {last.get('code') or last.get('reason') or 'deny'}",
                        "firewall_deny_streak",
                        {"streak": streak, "last_code": last.get("code")},
                    )
                    fired.append(ev)
                    st["last_firewall_alert_at"] = _utc_now()
            except Exception as exc:  # noqa: BLE001
                checked.append(f"fw_err:{exc}")

        if fired:
            prev = list(st.get("last_fired") or [])
            prev.extend(fired)
            st["last_fired"] = prev[-20:]
        _save_state(st)

    return {
        "ok": True,
        "fired": fired,
        "fired_count": len(fired),
        "checked": checked,
        "settings": toggles,
        "ts": _utc_now(),
    }


def recent_alerts(limit: int = 30) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if LOG_PATH.exists():
        try:
            lines = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-max(1, min(100, int(limit or 30))) :]:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        except OSError:
            rows = []
    rows.reverse()
    return {"ok": True, "count": len(rows), "alerts": rows, "path": str(LOG_PATH)}

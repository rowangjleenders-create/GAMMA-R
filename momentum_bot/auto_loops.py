"""
Background auto-learn + auto-trade loops (paper-first).

Started with the API server lifespan. Uses learned runtime thresholds,
risk budgeting, confidence gates, maintenance windows, and the data-health
circuit breaker. LIVE orders only if LIVE_TRADING_ENABLED is already set.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_PATH = DATA_DIR / "auto_loop_state.json"

_tasks: List[asyncio.Task] = []
_stop = asyncio.Event()
_trade_lock = asyncio.Lock()
_state_lock = threading.RLock()
_state: Dict[str, Any] = {}
_journal_count_seen: int = 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_state() -> Dict[str, Any]:
    return {
        "learn_running": False,
        "trade_running": False,
        "exit_running": False,
        "started_at": None,
        "last_scan_at": None,
        "last_scan_count": 0,
        "last_trade_at": None,
        "last_trade_summary": None,
        "last_learn_at": None,
        "last_learn_summary": None,
        "last_exit_at": None,
        "last_exit_summary": None,
        "last_error": None,
        "recent_actions": [],
        "updated_at": _utc_now(),
    }


def load_loop_state() -> Dict[str, Any]:
    global _state
    with _state_lock:
        if _state:
            return dict(_state)
        if STATE_PATH.exists():
            try:
                raw = json.loads(STATE_PATH.read_text())
                base = _default_state()
                base.update(raw if isinstance(raw, dict) else {})
                _state = base
                return dict(_state)
            except (json.JSONDecodeError, OSError):
                pass
        _state = _default_state()
        return dict(_state)


def _save_loop_state() -> None:
    with _state_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _state["updated_at"] = _utc_now()
        acts = list(_state.get("recent_actions") or [])
        _state["recent_actions"] = acts[-40:]
        STATE_PATH.write_text(json.dumps(_state, indent=2, default=str))


def _patch_state(**kwargs: Any) -> None:
    with _state_lock:
        if not _state:
            load_loop_state()
        _state.update(kwargs)
        if "action" in kwargs:
            _state.setdefault("recent_actions", []).append({
                "at": _utc_now(), **{k: kwargs[k] for k in ("action", "detail") if k in kwargs},
            })
        _save_loop_state()


def _log(msg: str) -> None:
    print(f"[auto_loops] {msg}")



def _firewall_brief() -> Dict[str, Any]:
    try:
        from . import policy_firewall as fw
        return fw.status() if hasattr(fw, "status") else {"enabled": True}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}



def _crash_brief(cfg=None) -> Dict[str, Any]:
    try:
        from .crash_mode import get_crash_status
        return get_crash_status(cfg).to_dict()
    except Exception as exc:  # noqa: BLE001
        return {"active": False, "error": str(exc)}


def _scoreboard_brief(cfg=None) -> Dict[str, Any]:
    try:
        from .scoreboard import build_scoreboard
        board = build_scoreboard(cfg)
        top = []
        for s in (board.get("strategies") or [])[:8]:
            top.append({
                "strategy_id": s.get("strategy_id"),
                "status": s.get("status"),
                "trades": s.get("sample_size"),
                "expectancy": (s.get("primary") or {}).get("expectancy"),
            })
        return {
            "label": board.get("label"),
            "min_trades": board.get("min_trades"),
            "top": top,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def get_status() -> Dict[str, Any]:
    from .config import get_runtime_config
    from . import circuit_breaker as cb
    from .timezone_util import maintenance_window_status
    from .brokers import live_trading_enabled

    cfg = get_runtime_config()
    st = load_loop_state()
    maint = maintenance_window_status(
        exchange=getattr(cfg, "market_exchange", "NYSE") or "NYSE",
        open_buffer_minutes=int(cfg.maintenance_open_buffer_minutes or 0),
        close_buffer_minutes=int(cfg.maintenance_close_buffer_minutes or 0),
        enabled=bool(cfg.maintenance_windows_enabled),
    )
    breaker = cb.status()
    strategies_cycle = {}
    try:
        from .strategies.runner import get_last_cycle
        from .strategies import get_last_router_decision
        strategies_cycle = get_last_cycle() or {}
        router = get_last_router_decision()
        router_d = router.to_dict() if router else strategies_cycle.get("router")
    except Exception:
        strategies_cycle, router_d = {}, None

    return {
        **st,
        "auto_learn_enabled": bool(cfg.auto_learn_enabled),
        "auto_trade_enabled": bool(cfg.auto_trade_enabled),
        "auto_learn_interval_minutes": int(cfg.auto_learn_interval_minutes),
        "auto_trade_interval_minutes": int(cfg.auto_trade_interval_minutes),
        "auto_scan_interval_minutes": int(getattr(cfg, "auto_scan_interval_minutes", 5) or 5),
        "scan_cache_ttl_sec": int(getattr(cfg, "scan_cache_ttl_sec", 60) or 60),
        "auto_exit_interval_seconds": int(cfg.auto_exit_interval_seconds),
        "max_concurrent_positions": int(cfg.max_concurrent_positions),
        "min_confidence": float(cfg.min_confidence),
        "max_position_pct": float(cfg.max_position_pct),
        "maintenance": maint,
        "circuit_breaker": breaker,
        "trading_halted": bool(breaker.get("halted")),
        "live_trading_enabled": live_trading_enabled(),
        "use_per_ticker_sessions": bool(getattr(cfg, "use_per_ticker_sessions", True)),
        "session_gate_entries": bool(getattr(cfg, "session_gate_entries", True)),
        "firewall": _firewall_brief(),
        "loops_started": bool(st.get("started_at")) and any(not t.done() for t in _tasks),
        "router_mode": getattr(cfg, "router_mode", "auto"),
        "strategy_enabled": getattr(cfg, "strategy_enabled", {}) or {},
        "strategies_last_cycle": {
            "fired": strategies_cycle.get("fired") or [],
            "signal_count": strategies_cycle.get("signal_count"),
            "by_strategy": strategies_cycle.get("by_strategy") or {},
            "at": strategies_cycle.get("at"),
            "top": (strategies_cycle.get("top") or [])[:6],
        },
        "router": router_d,
        "crash_mode": _crash_brief(cfg),
        "scoreboard_summary": _scoreboard_brief(cfg),
        "note": (
            "Paper auto-trade by default. Live broker orders only if "
            "LIVE_TRADING_ENABLED is already set by the owner."
        ),
    }


# ---------------------------------------------------------------------------
# Learning cycle
# ---------------------------------------------------------------------------

def run_learn_once(reason: str = "auto interval") -> Dict[str, Any]:
    from .learning import load_journal, run_learning
    from .config import get_runtime_config

    global _journal_count_seen
    cfg = get_runtime_config()
    if not cfg.auto_learn_enabled:
        return {"ran": False, "reason": "auto_learn_enabled=false"}

    entries = load_journal()
    n = len(entries)
    force = False
    if n > _journal_count_seen:
        reason = f"journal grew {_journal_count_seen}→{n}"
        force = False  # still respect min_trades unless enough unlearned
    _journal_count_seen = n

    result = run_learning(force=False, reason=reason)
    # Periodic full pass even if under min: still call without force so stats update
    _patch_state(
        last_learn_at=_utc_now(),
        last_learn_summary={
            "ran": result.get("ran"),
            "reason": result.get("reason"),
            "adjustments": len(result.get("adjustments") or []),
            "sample_size": result.get("sample_size"),
        },
        learn_running=True,
        action="learn",
        detail=str(result.get("reason") or result.get("ran")),
    )
    if result.get("ran"):
        _log(f"learning applied {len(result.get('adjustments') or [])} adjustments")
    return result


# ---------------------------------------------------------------------------
# Exit cycle
# ---------------------------------------------------------------------------

def run_exits_once() -> Dict[str, Any]:
    from .config import get_runtime_config
    from . import paper as paper_mod
    from .timezone_util import maintenance_window_status

    cfg = get_runtime_config()
    if not cfg.auto_trade_enabled:
        return {"skipped": True, "reason": "auto_trade_enabled=false"}

    maint = maintenance_window_status(
        exchange=getattr(cfg, "market_exchange", "NYSE") or "NYSE",
        open_buffer_minutes=int(cfg.maintenance_open_buffer_minutes or 0),
        close_buffer_minutes=int(cfg.maintenance_close_buffer_minutes or 0),
        enabled=bool(cfg.maintenance_windows_enabled),
    )
    # Prefer halt new entries only; exits still run unless maintenance_allow_exits=False
    if maint.get("active") and not bool(cfg.maintenance_allow_exits):
        return {"skipped": True, "reason": "maintenance_window_blocks_exits", "maintenance": maint}

    result = paper_mod.manage_exits(cfg=cfg)
    _patch_state(
        last_exit_at=_utc_now(),
        last_exit_summary={"checked": result.get("checked"), "actions": len(result.get("actions") or [])},
        exit_running=True,
        action="exits",
        detail=f"{len(result.get('actions') or [])} actions",
    )
    for a in result.get("actions") or []:
        if a.get("action") not in ("skip",):
            _log(f"exit {a.get('action')} {a.get('ticker')} @ {a.get('price')}")
    return result


# ---------------------------------------------------------------------------
# Trade cycle (scan → decide → act)
# ---------------------------------------------------------------------------

def run_trade_once(*, force_scan: bool = True) -> Dict[str, Any]:
    from .config import get_runtime_config
    from . import paper as paper_mod
    from .scanner import run_scan, signals_to_dicts
    from .watchlist import load_watchlist
    from .timezone_util import maintenance_window_status, get_session, should_allow_new_entry
    from . import policy_firewall as fw
    from .brokers import live_trading_enabled, get_broker
    from . import circuit_breaker as cb
    from .risk import budget_shares
    from .confidence import confidence_from_signal
    from .data_sources import get_data_source_status, realtime_sip_enabled

    cfg = get_runtime_config()
    summary: Dict[str, Any] = {
        "at": _utc_now(),
        "scanned": 0,
        "orders": [],
        "skipped": [],
        "exits": None,
    }

    if not cfg.auto_trade_enabled:
        summary["skipped"].append("auto_trade_enabled=false")
        return summary

    fw.begin_cycle(summary["at"])

    # Crash / regime-shock detection (cheap state + optional market check)
    crash_status = None
    try:
        from .crash_mode import detect_crash, get_crash_status
        crash_status = detect_crash(cfg, force_check=True)
        summary["crash_mode"] = crash_status.to_dict()
        if crash_status.active:
            _log(f"CRASH MODE ON until {crash_status.until}: {crash_status.reason}")
    except Exception as exc:  # noqa: BLE001
        summary["crash_mode"] = {"error": str(exc), "active": False}
        try:
            from .crash_mode import get_crash_status
            crash_status = get_crash_status(cfg)
        except Exception:
            crash_status = None

    # Circuit breaker: halt new entries (exits still managed separately)
    breaker = cb.status()
    if breaker.get("halted"):
        summary["skipped"].append(f"circuit_breaker: {breaker.get('reason')}")
        summary["circuit_breaker"] = breaker
        _patch_state(last_trade_at=_utc_now(), last_trade_summary=summary, last_error=None)
        return summary

    maint = maintenance_window_status(
        exchange=getattr(cfg, "market_exchange", "NYSE") or "NYSE",
        open_buffer_minutes=int(cfg.maintenance_open_buffer_minutes or 0),
        close_buffer_minutes=int(cfg.maintenance_close_buffer_minutes or 0),
        enabled=bool(cfg.maintenance_windows_enabled),
    )
    if maint.get("active"):
        summary["skipped"].append(f"maintenance: {maint.get('reason')}")
        summary["maintenance"] = maint
        _patch_state(last_trade_at=_utc_now(), last_trade_summary=summary)
        return summary

    session = get_session(
        exchange=getattr(cfg, "market_exchange", "NYSE") or "NYSE",
        user_tz=getattr(cfg, "user_timezone", "America/Chicago") or "America/Chicago",
        allow_after_hours_signals=bool(cfg.allow_after_hours_signals),
    )
    summary["session"] = session.to_dict()
    # Legacy: only_act_during_open without per-ticker → block whole cycle if default exchange closed
    use_per = bool(getattr(cfg, "use_per_ticker_sessions", True))
    if cfg.only_act_during_open and not use_per and not session.is_open:
        summary["skipped"].append(f"market {session.session} — only_act_during_open")
        _patch_state(last_trade_at=_utc_now(), last_trade_summary=summary)
        return summary

    # Exits first
    try:
        summary["exits"] = run_exits_once()
    except Exception as exc:  # noqa: BLE001
        summary["exits"] = {"error": str(exc)}

    # Scan with learned thresholds (runtime config)
    if force_scan:
        try:
            from . import scanner as scanner_mod
            scanner_mod._CACHE_AT = 0.0
        except Exception:
            pass

    snap = paper_mod.mark_to_market()
    equity = float(snap.get("equity") or cfg.starting_equity)
    open_pos = list(snap.get("open_positions") or [])
    held = {p["ticker"] for p in open_pos}
    max_pos = int(cfg.max_concurrent_positions or 5)
    slots = max(0, max_pos - len(open_pos))
    if slots <= 0:
        summary["skipped"].append(f"max_concurrent_positions={max_pos}")
        _patch_state(last_trade_at=_utc_now(), last_trade_summary=summary, last_scan_at=_utc_now())
        return summary

    try:
        signals = run_scan(cfg, watchlist=load_watchlist(), equity=equity)
    except Exception as exc:  # noqa: BLE001
        cb.record_fetch_failure(str(exc))
        summary["error"] = str(exc)
        _patch_state(last_error=str(exc), last_trade_at=_utc_now(), last_trade_summary=summary)
        _log(f"scan failed: {exc}")
        return summary

    summary["scanned"] = len(signals)
    _patch_state(last_scan_at=_utc_now(), last_scan_count=len(signals))

    # Data-health evaluation
    zero_px = sum(1 for s in signals if not s.entry or s.entry <= 0)
    ds = get_data_source_status()
    quote_age = None
    try:
        age = ds.get("cache_age_sec") or ds.get("last_bar_age_sec")
        if age is not None:
            quote_age = float(age)
    except Exception:
        pass
    sip_wanted = bool(realtime_sip_enabled())
    sip_fallback = bool(ds.get("fallback_active") or ds.get("using_fallback"))
    cb.evaluate_after_scan(
        signal_count=len(signals),
        quote_age_sec=quote_age,
        zero_price_count=zero_px,
        data_source=ds.get("data_source") or ds.get("live_source"),
        sip_fallback=sip_fallback,
        sip_wanted=sip_wanted,
    )
    if cb.is_halted():
        summary["skipped"].append("circuit_breaker tripped after scan")
        summary["circuit_breaker"] = cb.status()
        _patch_state(last_trade_at=_utc_now(), last_trade_summary=summary)
        return summary

    # Rank by confidence (prefer strong entries)
    scored = []
    for s in signals:
        conf = s.confidence if s.confidence is not None else confidence_from_signal(s, cfg)
        scored.append((conf, s))
    scored.sort(key=lambda x: x[0], reverse=True)

    max_new = int(cfg.auto_trade_max_new_per_cycle or 2)
    placed = 0
    min_conf = float(cfg.min_confidence or 0.0)
    require_fwd = bool(cfg.auto_trade_require_forward_pass)

    for conf, sig in scored:
        if placed >= max_new or placed >= slots:
            break
        if sig.ticker in held:
            summary["skipped"].append(f"{sig.ticker}: already held")
            continue
        if conf < min_conf:
            summary["skipped"].append(f"{sig.ticker}: confidence {conf:.2f} < {min_conf:.2f}")
            continue
        if require_fwd and cfg.use_forward_estimate and sig.forward_pass is False:
            summary["skipped"].append(f"{sig.ticker}: forward_pass=false")
            continue

        allow_sess, sess_reason, sess_info = should_allow_new_entry(sig.ticker, cfg)
        if not allow_sess:
            summary["skipped"].append(f"{sig.ticker}: {sess_reason}")
            _audit_skip(
                cfg, source="auto", ticker=sig.ticker, strategy_id=getattr(sig, "strategy_id", None),
                skip_reason=sess_reason, session_gate={"allowed": False, "reason": sess_reason},
                crash_mode=crash_status, signal=sig,
            )
            continue

        strat_id_pre = getattr(sig, "strategy_id", None) or "momentum"
        try:
            from .crash_mode import entry_allowed_for_strategy, size_multiplier_for_strategy
            ok_crash, crash_reason = entry_allowed_for_strategy(strat_id_pre, cfg)
            if not ok_crash:
                summary["skipped"].append(f"{sig.ticker}: {crash_reason}")
                _audit_skip(
                    cfg, source="auto", ticker=sig.ticker, strategy_id=strat_id_pre,
                    skip_reason=crash_reason, session_gate={"allowed": True, "reason": sess_reason},
                    crash_mode=crash_status, signal=sig,
                )
                continue
            c_mult = size_multiplier_for_strategy(strat_id_pre, cfg)
        except Exception:
            c_mult = 1.0

        if sig.shares <= 0 and sig.entry:
            # re-size with book budget
            pass

        existing_notional = sum(
            float(p.get("entry") or 0) * int(p.get("shares") or 0)
            for p in open_pos if p.get("ticker") == sig.ticker
        )
        # Honor strategy/router/vol-target size multiplier when present (+ crash overlay)
        size_mult = float(getattr(sig, "suggested_size_mult", None) or sig.regime_size_mult or 1.0)
        size_mult *= float(c_mult or 1.0)
        sized_eq = float(equity) * max(0.05, min(1.5, size_mult))
        plan = budget_shares(sig.ticker, float(sig.entry), sized_eq, cfg, existing_notional=existing_notional)
        if plan.shares <= 0:
            summary["skipped"].append(f"{sig.ticker}: risk budget / size=0")
            continue

        use_live = live_trading_enabled() and paper_mod.load_portfolio().mode == "live"
        strat_id = getattr(sig, "strategy_id", None) or "momentum"
        try:
            if use_live:
                # Live path — owner already set LIVE_TRADING_ENABLED; firewall still mandatory
                fw.assert_order_allowed(
                    ticker=sig.ticker,
                    shares=float(plan.shares),
                    price=float(sig.entry),
                    side="buy",
                    mode="live",
                    source="auto",
                    strategy_id=strat_id,
                    equity=float(equity),
                    cfg=cfg,
                )
                order = get_broker().place_market_order(sig.ticker, float(plan.shares), side="buy")
                fill = {
                    "ticker": sig.ticker,
                    "shares": plan.shares,
                    "mode": "live",
                    "order": order.to_dict() if hasattr(order, "to_dict") else order,
                    "confidence": conf,
                    "strategy_id": strat_id,
                }
                _log(f"LIVE auto buy {sig.ticker} x{plan.shares} conf={conf:.2f}")
            else:
                from .feedback import build_entry_context
                # stamp confidence onto signal for context builder
                try:
                    sig.confidence = conf
                except Exception:
                    pass
                ctx = build_entry_context(ticker=sig.ticker, signal=sig, cfg=cfg)
                fill = paper_mod.place_order(
                    ticker=sig.ticker,
                    shares=int(plan.shares),
                    entry=float(sig.entry),
                    stop=float(sig.stop),
                    take_profit=float(sig.take_profit),
                    source="auto",
                    forward_probability=sig.forward_probability,
                    forward_threshold=float(cfg.forward_estimate_threshold),
                    ensemble_votes=sig.ensemble_votes,
                    confidence=conf,
                    context=ctx,
                    signal=sig,
                    cfg=cfg,
                    strategy_id=strat_id,
                )
                _log(f"PAPER auto buy {sig.ticker} x{plan.shares} conf={conf:.2f} @ {sig.entry}")
            summary["orders"].append({
                "ticker": sig.ticker,
                "shares": plan.shares,
                "entry": sig.entry,
                "confidence": conf,
                "mode": "live" if use_live else "paper",
                "id": fill.get("id"),
                "strategy_id": getattr(sig, "strategy_id", None) or "momentum",
            })
            _audit_fill(
                cfg, source="auto", ticker=sig.ticker, strategy_id=strat_id,
                order_id=fill.get("id"), session_gate={"allowed": True, "reason": sess_reason},
                crash_mode=crash_status, signal=sig, firewall=fill.get("firewall"),
            )
            placed += 1
            held.add(sig.ticker)
            open_pos.append({"ticker": sig.ticker, "entry": sig.entry, "shares": plan.shares})
        except fw.FirewallDenied as exc:
            summary["skipped"].append(f"{sig.ticker}: firewall {exc.result.code}: {exc.result.reason}")
            _log(f"firewall denied {sig.ticker}: {exc.result.reason}")
            _audit_skip(
                cfg, source="auto", ticker=sig.ticker, strategy_id=strat_id,
                skip_reason=f"firewall:{exc.result.code}:{exc.result.reason}",
                session_gate={"allowed": True, "reason": sess_reason},
                crash_mode=crash_status, signal=sig, firewall=exc.result,
            )
        except Exception as exc:  # noqa: BLE001
            summary["skipped"].append(f"{sig.ticker}: order error {exc}")
            _log(f"order failed {sig.ticker}: {exc}")
            _audit_skip(
                cfg, source="auto", ticker=sig.ticker, strategy_id=getattr(sig, "strategy_id", None),
                skip_reason=f"order_error:{exc}",
                session_gate={"allowed": True, "reason": sess_reason},
                crash_mode=crash_status, signal=sig,
            )

    summary["signals"] = signals_to_dicts(signals)[:10]
    _patch_state(
        last_trade_at=_utc_now(),
        last_trade_summary={
            "orders": len(summary["orders"]),
            "scanned": summary["scanned"],
            "skipped": len(summary["skipped"]),
            "tickers": [o["ticker"] for o in summary["orders"]],
        },
        trade_running=True,
        last_error=None,
        action="trade",
        detail=f"orders={len(summary['orders'])} scanned={summary['scanned']}",
    )
    return summary


# ---------------------------------------------------------------------------
# Async loops
# ---------------------------------------------------------------------------

async def _learn_loop() -> None:
    from .config import get_runtime_config
    await asyncio.sleep(5)  # brief startup delay
    while not _stop.is_set():
        cfg = get_runtime_config()
        interval = max(60, int(cfg.auto_learn_interval_minutes or 10) * 60)
        try:
            if cfg.auto_learn_enabled:
                await asyncio.to_thread(run_learn_once, "auto interval")
        except Exception as exc:  # noqa: BLE001
            _log(f"learn loop error: {exc}")
            _patch_state(last_error=f"learn: {exc}")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def _trade_loop() -> None:
    from .config import get_runtime_config
    await asyncio.sleep(8)
    while not _stop.is_set():
        cfg = get_runtime_config()
        # Prefer shorter auto_scan_interval when set (freshness); floor 60s; soft backoff on errors via state
        scan_mins = getattr(cfg, "auto_scan_interval_minutes", None)
        trade_mins = getattr(cfg, "auto_trade_interval_minutes", 15)
        base_mins = float(scan_mins if scan_mins is not None else trade_mins or 15)
        # Soft backoff when last cycle errored / circuit open
        backoff = float((_STATE or {}).get("scan_backoff_mult") or 1.0)
        interval = max(60, int(base_mins * 60 * max(1.0, backoff)))
        try:
            if cfg.auto_trade_enabled:
                async with _trade_lock:
                    await asyncio.to_thread(run_trade_once)
        except Exception as exc:  # noqa: BLE001
            _log(f"trade loop error: {exc}")
            _patch_state(last_error=f"trade: {exc}")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def _exit_loop() -> None:
    from .config import get_runtime_config
    await asyncio.sleep(12)
    while not _stop.is_set():
        cfg = get_runtime_config()
        interval = max(15, int(cfg.auto_exit_interval_seconds or 60))
        try:
            if cfg.auto_trade_enabled:
                async with _trade_lock:
                    await asyncio.to_thread(run_exits_once)
        except Exception as exc:  # noqa: BLE001
            _log(f"exit loop error: {exc}")
            _patch_state(last_error=f"exit: {exc}")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass



# ---------------------------------------------------------------------------
# Scheduled allowlisted web learning + alerts
# ---------------------------------------------------------------------------

async def _web_learn_loop() -> None:
    """Periodic learn_from_web on macro topics + open position/watchlist tickers."""
    await asyncio.sleep(20)
    while not _stop.is_set():
        cfg = None
        interval_min = 360
        try:
            from .config import get_runtime_config
            cfg = get_runtime_config()
            interval_min = max(30, int(getattr(cfg, "auto_web_learn_interval_minutes", 360) or 360))
            if bool(getattr(cfg, "auto_web_learn_enabled", False)):
                summary = run_web_learn_once(reason="auto interval")
                try:
                    from .edge import run_daily_self_critique
                    critique = run_daily_self_critique(persist=True)
                    summary = dict(summary or {})
                    summary["self_critique"] = {
                        "summary": (critique.get("summary") or "")[:200],
                        "degraded": (critique.get("score") or {}).get("degraded_count"),
                    }
                except Exception:
                    pass
                _patch_state(
                    last_web_learn_at=_utc_now(),
                    last_web_learn_summary=summary,
                    action="web_learn",
                    detail=str((summary or {}).get("topics_tried") or "")[:120],
                )
        except Exception as exc:  # noqa: BLE001
            _log(f"web learn loop error: {exc}")
            _patch_state(last_error=f"web_learn: {exc}")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval_min * 60)
        except asyncio.TimeoutError:
            pass


def run_web_learn_once(reason: str = "manual") -> Dict[str, Any]:
    """One-shot allowlisted web learning for macro + open/watchlist tickers."""
    from .config import get_runtime_config
    from .copilot_web import learn_from_web, web_enabled

    cfg = get_runtime_config()
    if not web_enabled() or not bool(getattr(cfg, "copilot_web_enabled", True)):
        return {"ran": False, "reason": "copilot_web_disabled"}
    topics = list(getattr(cfg, "auto_web_learn_macro_topics", None) or ["macro", "fed"])
    # Add open position + watchlist tickers
    try:
        from .paper import load_portfolio
        from .watchlist import load_watchlist
        for pos in load_portfolio().positions:
            if pos.get("status", "open") == "open" and pos.get("ticker"):
                topics.append(str(pos["ticker"]))
        for t in (load_watchlist() or [])[:8]:
            topics.append(str(t))
    except Exception:
        pass
    # Dedupe preserve order
    seen = set()
    uniq = []
    for t in topics:
        k = str(t).strip().lower()
        if k and k not in seen:
            seen.add(k)
            uniq.append(str(t).strip())
    uniq = uniq[:6]
    results = []
    for topic in uniq:
        try:
            r = learn_from_web(topic, max_sources=2)
            results.append({"topic": topic, "ok": bool(r.get("ok", True)), "stored": r.get("stored") or r.get("path")})
        except Exception as exc:  # noqa: BLE001
            results.append({"topic": topic, "ok": False, "error": str(exc)[:120]})
    out = {
        "ran": True,
        "reason": reason,
        "topics_tried": uniq,
        "results": results,
        "at": _utc_now(),
        "label": "Scheduled allowlisted web learning — educational",
    }
    try:
        from .edge import ingest_overnight_into_learning, log_ai_process
        digest = ingest_overnight_into_learning(reason=f"web_learn:{reason}")
        out["overnight_ingest"] = {
            "ok": bool(digest.get("ok")),
            "note_count": digest.get("note_count"),
            "topics": (digest.get("topics") or [])[:6],
        }
        log_ai_process("web_learn_cycle", {"topics": uniq, "reason": reason, "ingest": out["overnight_ingest"]})
    except Exception:
        try:
            from .edge import log_ai_process
            log_ai_process("web_learn_cycle", {"topics": uniq, "reason": reason})
        except Exception:
            pass
    return out


async def _alerts_loop() -> None:
    await asyncio.sleep(35)
    while not _stop.is_set():
        try:
            from .config import get_runtime_config
            from .alerts import evaluate_alerts
            cfg = get_runtime_config()
            if bool(getattr(cfg, "alerts_enabled", True)):
                res = evaluate_alerts(cfg)
                if res.get("fired_count"):
                    _patch_state(
                        last_alerts_at=_utc_now(),
                        last_alerts_summary={"fired_count": res.get("fired_count"), "kinds": [f.get("kind") for f in (res.get("fired") or [])]},
                        action="alerts",
                        detail=f"fired={res.get('fired_count')}",
                    )
        except Exception as exc:  # noqa: BLE001
            _log(f"alerts loop error: {exc}")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=90)
        except asyncio.TimeoutError:
            pass


def start_auto_loops() -> List[asyncio.Task]:
    """Schedule background tasks on the running event loop."""
    global _tasks
    _stop.clear()
    load_loop_state()
    _patch_state(
        started_at=_utc_now(),
        learn_running=True,
        trade_running=True,
        exit_running=True,
    )
    _tasks = [
        asyncio.create_task(_learn_loop(), name="auto_learn"),
        asyncio.create_task(_trade_loop(), name="auto_trade"),
        asyncio.create_task(_exit_loop(), name="auto_exits"),
        asyncio.create_task(_web_learn_loop(), name="auto_web_learn"),
        asyncio.create_task(_alerts_loop(), name="auto_alerts"),
    ]
    _log("started learn + trade + exit + web_learn + alerts loops")
    return _tasks


async def stop_auto_loops() -> None:
    _stop.set()
    for t in list(_tasks):
        t.cancel()
    for t in list(_tasks):
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    _tasks.clear()
    _patch_state(learn_running=False, trade_running=False, exit_running=False)
    _log("stopped auto loops")


def _audit_enabled(cfg) -> bool:
    return bool(getattr(cfg, "decision_audit_enabled", True))


def _audit_skip(cfg, *, source, ticker, strategy_id, skip_reason, session_gate=None,
                crash_mode=None, signal=None, firewall=None) -> None:
    if not _audit_enabled(cfg):
        return
    try:
        from .decision_audit import log_decision_cycle
        from .strategies import get_last_router_decision
        from .optimization import get_last_regime
        log_decision_cycle(
            source=source,
            regime=get_last_regime(),
            crash_mode=crash_mode.to_dict() if crash_mode and hasattr(crash_mode, "to_dict") else crash_mode,
            router_decision=get_last_router_decision(),
            signals_considered=[signal] if signal is not None else None,
            strategy_id=strategy_id,
            firewall=firewall.to_dict() if firewall and hasattr(firewall, "to_dict") else firewall,
            skip_reason=skip_reason,
            session_gate=session_gate,
            ticker=ticker,
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"audit skip write failed: {exc}")


def _audit_fill(cfg, *, source, ticker, strategy_id, order_id, session_gate=None,
                crash_mode=None, signal=None, firewall=None) -> None:
    if not _audit_enabled(cfg):
        return
    try:
        from .decision_audit import log_decision_cycle
        from .strategies import get_last_router_decision
        from .optimization import get_last_regime
        log_decision_cycle(
            source=source,
            regime=get_last_regime(),
            crash_mode=crash_mode.to_dict() if crash_mode and hasattr(crash_mode, "to_dict") else crash_mode,
            router_decision=get_last_router_decision(),
            signals_considered=[signal] if signal is not None else None,
            strategy_id=strategy_id,
            firewall=firewall if isinstance(firewall, dict) else (
                firewall.to_dict() if firewall and hasattr(firewall, "to_dict") else {"allowed": True}
            ),
            order_id=order_id,
            session_gate=session_gate,
            ticker=ticker,
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"audit fill write failed: {exc}")


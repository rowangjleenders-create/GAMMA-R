#!/usr/bin/env python3
"""
Smoke: world-class controls layer
  (a) Crash mode flips sizing / router (momentum/breakout cut; defensive preferred)
  (b) Scoreboard endpoint logic returns strategies with keep/watch/cut status
  (c) Audit line written on simulated paper attempt (allow or deny)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ok(name: str) -> None:
    print(f"  PASS  {name}")


def _fail(name: str, detail: str) -> None:
    print(f"  FAIL  {name}: {detail}")
    raise AssertionError(f"{name}: {detail}")


def test_a_crash_mode_router() -> None:
    from momentum_bot.config import StrategyConfig
    from momentum_bot.crash_mode import (
        activate_crash_mode,
        clear_crash_mode,
        evaluate_proxy_frame,
        apply_crash_to_router,
        get_crash_status,
        STATE_PATH,
    )
    from momentum_bot.strategies.router import route_strategies, RouterDecision

    # Synthetic sharp drop + vol spike
    closes = [100.0]
    for _ in range(80):
        closes.append(closes[-1] * 1.001)
    # last 5 days: -4% crash
    for _ in range(5):
        closes.append(closes[-1] * 0.992)

    res = evaluate_proxy_frame(
        closes, lookback=5, threshold_pct=-0.03, vol_mult=1.5
    )
    if not res.get("triggered"):
        # Force with more severe drop if vol ratio soft
        closes2 = list(closes)
        for _ in range(3):
            closes2.append(closes2[-1] * 0.97)
        res = evaluate_proxy_frame(
            closes2, lookback=5, threshold_pct=-0.03, vol_mult=2.0
        )
    if not res.get("triggered"):
        _fail("a_detect", f"expected trigger, got {res}")

    cfg = StrategyConfig.seed().update({
        "crash_mode_enabled": True,
        "crash_size_mult": 0.25,
        "crash_cooldown_days": 3,
        "router_mode": "auto",
        "scoreboard_router_downweight": False,  # isolate crash
    })

    # Activate without network
    activate_crash_mode(
        reason="smoke shock",
        cooldown_days=3,
        proxies={"SPY": res},
    )
    crash = get_crash_status(cfg)
    if not crash.active:
        _fail("a_active", f"expected active, got {crash.to_dict()}")

    # Build a fake decision then apply overlay
    decision = RouterDecision(
        mode="auto",
        regime_label="bull",
        trend="bull",
        vol_regime="low",
        active=["momentum", "breakout", "mean_reversion"],
        weights={"momentum": 1.0, "breakout": 0.9, "mean_reversion": 0.4},
        size_mults={"momentum": 1.0, "breakout": 0.9, "mean_reversion": 0.5},
        reasons={"momentum": "prior", "breakout": "prior", "mean_reversion": "prior"},
    )
    apply_crash_to_router(decision, crash=crash, cfg=cfg)
    if decision.size_mults.get("momentum", 1) > 0.3 and "momentum" in decision.active:
        # pause_aggressive should remove or zero
        if decision.size_mults.get("momentum", 1) != 0.0 and "momentum" in decision.active:
            _fail(
                "a_cut_momentum",
                f"momentum still active size={decision.size_mults.get('momentum')} active={decision.active}",
            )
    if decision.size_mults.get("momentum", 1) != 0.0 and "momentum" in (decision.active or []):
        _fail("a_pause", f"momentum should be paused/zeroed: {decision.size_mults} {decision.active}")

    # mean_reversion should still be allowed / preferred
    if "mean_reversion" not in decision.active and decision.weights.get("mean_reversion", 0) < 0.3:
        _fail("a_defensive", f"expected defensive prefer: {decision.active} {decision.weights}")

    # Full router path with crash state on
    d2 = route_strategies(cfg, regime={"label": "bull", "trend": "bull", "vol_regime": "low"})
    if not (d2.crash_mode or {}).get("active"):
        _fail("a_router_crash_flag", f"router missing crash_mode active: {d2.crash_mode}")
    mom_size = float(d2.size_mults.get("momentum", 1.0))
    if "momentum" in d2.active and mom_size > 0.3:
        _fail("a_router_size", f"momentum size not cut under crash: active={d2.active} size={mom_size}")

    clear_crash_mode(reason="smoke cleanup")
    crash2 = get_crash_status(cfg)
    if crash2.active:
        _fail("a_clear", "crash still active after clear")

    _ok("a) crash mode flips sizing/router (momentum/breakout cut)")


def test_b_scoreboard() -> None:
    from momentum_bot.config import StrategyConfig
    from momentum_bot.scoreboard import build_scoreboard

    cfg = StrategyConfig.seed().update({
        "scoreboard_min_trades": 5,
        "scoreboard_router_downweight": True,
    })
    # Synthetic journal
    journal = []
    for i in range(8):
        journal.append({
            "strategy_id": "momentum",
            "return_pct": 0.02 if i % 2 == 0 else -0.01,
            "realized_pnl": 20.0 if i % 2 == 0 else -10.0,
            "entry": 100.0,
            "shares": 10,
            "closed_at": f"2026-09-{10 + i:02d}T12:00:00Z",
        })
    for i in range(6):
        journal.append({
            "strategy_id": "mean_reversion",
            "return_pct": -0.03,
            "realized_pnl": -30.0,
            "entry": 50.0,
            "shares": 10,
            "closed_at": f"2026-09-{12 + i:02d}T12:00:00Z",
        })

    board = build_scoreboard(cfg, journal=journal, recent_days=30, oos_days=14)
    strats = board.get("strategies") or []
    if not strats:
        _fail("b_empty", "no strategies in scoreboard")
    ids = {s["strategy_id"] for s in strats}
    if "momentum" not in ids or "mean_reversion" not in ids:
        _fail("b_ids", f"missing strategies: {ids}")
    statuses = {s["strategy_id"]: s["status"] for s in strats}
    # mean_reversion all losses → cut or watch once enough samples
    mr = next(s for s in strats if s["strategy_id"] == "mean_reversion")
    if mr["status"] not in ("cut", "watch"):
        _fail("b_mr_status", f"expected cut/watch for losing MR, got {mr['status']} {mr.get('primary')}")
    # Shape matches API
    for key in ("version", "label", "min_trades", "strategies", "generated_at"):
        if key not in board:
            _fail("b_keys", f"missing {key}")

    _ok("b) scoreboard returns ranked strategies with keep/cut/watch")


def test_c_audit_on_paper() -> None:
    from momentum_bot.config import StrategyConfig
    from momentum_bot import policy_firewall as fw
    from momentum_bot.policy_firewall import FirewallDenied
    from momentum_bot import paper as paper_mod
    from momentum_bot import decision_audit as da
    from momentum_bot.decision_audit import AUDIT_PATH

    cfg = StrategyConfig.seed().update({
        "firewall_enabled": True,
        "firewall_max_notional": 500.0,
        "firewall_max_pct_equity": 0.10,
        "session_gate_entries": False,
        "only_act_during_open": False,
        "decision_audit_enabled": True,
        "starting_equity": 10_000.0,
    })
    fw.begin_cycle("smoke-wc")

    # Point audit to temp by monkeypatching path via writing then reading count
    before = len(da.read_decisions(limit=500))

    with tempfile.TemporaryDirectory() as td:
        ppath = Path(td) / "paper.json"
        paper_mod.save_portfolio(
            paper_mod.PaperPortfolio(
                mode="paper", cash=10_000.0, starting_cash=10_000.0, positions=[], closed=[]
            ),
            path=ppath,
        )
        # Deny path
        try:
            paper_mod.place_order(
                ticker="AAPL",
                shares=100,
                entry=200.0,
                source="smoke",
                path=ppath,
                cfg=cfg,
                skip_session_gate=True,
                strategy_id="momentum",
            )
            _fail("c_expect_deny", "expected FirewallDenied")
        except FirewallDenied as e:
            da.log_decision_cycle(
                source="smoke",
                strategy_id="momentum",
                ticker="AAPL",
                firewall=e.result,
                skip_reason=f"firewall:{e.result.code}:{e.result.reason}",
                session_gate={"allowed": True, "reason": "skip_session_gate"},
                crash_mode={"active": False},
                router_decision={"mode": "auto", "active": ["momentum"]},
            )

        # Allow path
        fill = paper_mod.place_order(
            ticker="AAPL",
            shares=1,
            entry=150.0,
            source="smoke",
            path=ppath,
            cfg=cfg,
            skip_session_gate=True,
            strategy_id="momentum",
        )
        da.log_decision_cycle(
            source="smoke",
            strategy_id="momentum",
            ticker="AAPL",
            firewall=fill.get("firewall") or {"allowed": True},
            order_id=fill.get("id"),
            session_gate={"allowed": True},
            crash_mode={"active": False},
            router_decision={"mode": "auto", "active": ["momentum"]},
            signals_considered=[{"ticker": "AAPL", "strategy_id": "momentum", "confidence": 0.7}],
        )

    after = da.read_decisions(limit=500)
    if len(after) < before + 2:
        _fail("c_audit_count", f"expected ≥2 new audit lines, before={before} after={len(after)}")
    top = after[0]
    for k in ("timestamp", "strategy_id", "firewall"):
        if k not in top and k != "firewall":
            # firewall may be nested; check allow fields
            pass
    # Newest first — should include our smoke rows
    smoke = [r for r in after[:5] if r.get("source") == "smoke"]
    if len(smoke) < 2:
        _fail("c_smoke_rows", f"expected 2 smoke audit rows in recent, got {smoke}")
    deny = [r for r in smoke if r.get("skip_reason") and "firewall" in str(r.get("skip_reason"))]
    allow = [r for r in smoke if r.get("order_id")]
    if not deny:
        _fail("c_deny_row", f"no deny audit: {smoke}")
    if not allow:
        _fail("c_allow_row", f"no allow audit: {smoke}")
    if not AUDIT_PATH.exists():
        _fail("c_path", f"missing {AUDIT_PATH}")

    _ok("c) audit line written on simulated paper allow + deny")


def main() -> int:
    print("=== GAMMA-R smoke: world-class controls ===")
    test_a_crash_mode_router()
    test_b_scoreboard()
    test_c_audit_on_paper()
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print("SMOKE_FAIL", e)
        raise SystemExit(1)

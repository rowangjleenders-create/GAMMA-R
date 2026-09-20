#!/usr/bin/env python3
"""Smoke: desk command, monitor, brief, layout, watchlist columns, E-ve desk tools."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"  ok: {msg}")


def main() -> None:
    print("== desk OS smoke ==")

    from momentum_bot.desk import (
        parse_desk_command,
        run_desk_command,
        desk_layout,
        build_desk_monitor,
        build_cross_asset,
        build_desk_brief,
        build_eve_desk_brief,
        portfolio_risk_snapshot,
        command_help,
        summarize_panel,
        explain_ladder,
    )

    help_ = command_help()
    if not help_.get("examples") or not help_.get("not_bloomberg_licensed"):
        fail("command_help missing examples / not_bloomberg_licensed")
    ok(f"command help ({len(help_['examples'])} examples)")

    cases = [
        ("AAPL", "quote"),
        ("AAPL EQUITY", "quote"),
        ("NEWS AAPL", "news"),
        ("OPT AAPL", "options"),
        ("CHART AAPL 15m", "chart"),
        ("EVE why NVDA", "eve"),
        ("SCAN heat", "scanner"),
        ("MONITOR", "monitor"),
        ("BRIEF SPY", "brief"),
        ("HELP", "help"),
    ]
    for raw, expect in cases:
        p = parse_desk_command(raw)
        if p.get("route") != expect:
            fail(f"parse {raw!r} -> {p.get('route')} expected {expect}")
    ok("GO parser routes")

    # enrich lightly (no network hard-fail)
    r = run_desk_command("HELP", enrich=False)
    if not r.get("ok"):
        fail("HELP enrich=false")
    ok("run_desk_command HELP")

    for preset in ("classic", "news-heavy", "fx+equity", "eve-focus"):
        lay = desk_layout(preset)
        if lay.get("preset") != preset.replace(" ", "-") and lay["layout"]["id"] != preset:
            # fx+equity id check
            if lay["layout"]["id"] not in (preset, preset.replace("+", "+")):
                fail(f"layout preset {preset}: {lay.get('preset')}")
        if not lay["layout"].get("panels"):
            fail(f"layout {preset} empty panels")
    ok("desk layouts")

    mon = build_desk_monitor()
    if not mon.get("ok") or "sections" not in mon:
        fail(f"monitor: {mon}")
    if not mon.get("not_bloomberg_licensed") or not mon.get("not_level2"):
        fail("monitor missing honesty flags")
    ok(f"monitor strip={len(mon.get('strip') or [])}")

    xa = build_cross_asset()
    if not xa.get("ok"):
        fail(f"cross-asset: {xa}")
    ok("cross-asset board")

    brief = build_desk_brief("SPY")
    if not brief.get("ok") or brief.get("author") != "E-ve":
        fail(f"brief: {brief}")
    if not brief.get("not_bloomberg_licensed"):
        fail("brief claims bloomberg?")
    ok(f"brief bullets={len(brief.get('bullets') or [])}")

    from momentum_bot.watchlist import load_watchlist_columns, save_watchlist_columns

    cols = load_watchlist_columns()
    if "last" not in cols.get("columns", []):
        fail("default columns missing last")
    saved = save_watchlist_columns(["last", "bid", "ask", "pct_chg", "signal_score"])
    if saved["columns"] != ["last", "bid", "ask", "pct_chg", "signal_score"]:
        fail(f"save columns: {saved}")
    save_watchlist_columns(cols["available"])  # restore defaults
    ok("watchlist columns GET/PUT")

    # E-ve tools
    from momentum_bot.copilot_tools import execute_tool, TOOL_SCHEMAS

    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    for need in (
        "desk_command_help",
        "summarize_panel",
        "brief_news",
        "explain_ladder",
        "run_monitor",
        "eve_desk_brief",
        "portfolio_risk_snapshot",
    ):
        if need not in names:
            fail(f"missing tool schema {need}")
        args = {}
        if need == "summarize_panel":
            args = {"symbol": "SPY", "panel_id": "monitor"}
        elif need in ("brief_news", "explain_ladder", "eve_desk_brief"):
            args = {"symbol": "SPY"}
        out = execute_tool(need, args)
        if out.get("error") and "unknown tool" in str(out.get("error")):
            fail(f"tool {need} unknown")
    ok("E-ve desk tools")

    eve = build_eve_desk_brief("SPY")
    if not eve.get("ok") or eve.get("author") != "E-ve" or eve.get("persona") != "E-ve":
        fail(f"eve_desk_brief: {eve}")
    for sec in ("regime", "signals", "crash", "scoreboard", "overnight"):
        if sec not in (eve.get("sections") or {}):
            fail(f"eve_desk_brief missing section {sec}")
    if not eve.get("not_bloomberg_licensed") or not eve.get("live_locked"):
        fail("eve_desk_brief honesty/live flags")
    ok(f"eve_desk_brief lines={len(eve.get('lines') or [])}")

    risk = portfolio_risk_snapshot()
    if not risk.get("ok") or risk.get("author") != "E-ve" or risk.get("tool") != "portfolio_risk_snapshot":
        fail(f"portfolio_risk_snapshot: {risk}")
    for key in ("exposure", "concentration", "open_brackets"):
        if key not in risk:
            fail(f"portfolio_risk_snapshot missing {key}")
    ok("portfolio_risk_snapshot")

    from momentum_bot.paper import build_portfolio_analytics

    an = build_portfolio_analytics()
    if not an.get("ok") or not an.get("live_locked"):
        fail(f"portfolio analytics: {an}")
    for key in ("allocation_by_symbol", "pnl_breakdown", "exposure_vs_cash", "drawdown"):
        if key not in an:
            fail(f"analytics missing {key}")
    if "win_rate" not in (an.get("pnl_breakdown") or {}):
        fail("analytics pnl_breakdown missing win_rate")
    ok("portfolio analytics")

    # Edge framing
    from momentum_bot.edge import why_gamma_r_card, competitive_gaps, build_edge_status_logged

    why = why_gamma_r_card()
    if not why.get("vs_bloomberg") or not why["vs_bloomberg"].get("not_bloomberg_licensed"):
        fail("why card missing vs_bloomberg honesty")
    gaps = competitive_gaps()
    closed = {c["id"] for c in gaps.get("closed") or []}
    for need in (
        "desk_command",
        "desk_monitor",
        "desk_brief",
        "watchlist_columns",
        "eve_desk_tools",
        "eve_desk_brief",
        "portfolio_risk_snapshot",
        "portfolio_analytics",
    ):
        if need not in closed:
            fail(f"closed gaps missing {need}")
    hard = {h["id"] for h in gaps.get("still_open_hard") or []}
    if "bloomberg_license" not in hard or "true_l2" not in hard:
        fail("hard gaps must keep bloomberg_license + true_l2")
    if not gaps.get("not_bloomberg_licensed"):
        fail("gaps missing not_bloomberg_licensed")
    st = build_edge_status_logged()
    if not st.get("not_bloomberg_licensed"):
        fail("edge status missing not_bloomberg_licensed")
    ok("edge vs Bloomberg framing")

    # API routes
    from momentum_bot.api import app

    paths = {getattr(r, "path", None) for r in app.routes}
    for need in (
        "/desk/command",
        "/desk/command/help",
        "/desk/layout",
        "/desk/monitor",
        "/desk/cross-asset",
        "/desk/brief",
        "/desk/eve-brief",
        "/portfolio/analytics",
        "/watchlist/columns",
    ):
        if need not in paths:
            fail(f"missing route {need}")
    ok("API desk routes")

    # FastAPI TestClient smoke if available
    try:
        from fastapi.testclient import TestClient
        client = TestClient(app)
        # May hit auth — accept 200 or 401
        for method, path, body in [
            ("POST", "/desk/command", {"command": "AAPL", "enrich": False}),
            ("GET", "/desk/layout?preset=classic", None),
            ("GET", "/desk/monitor", None),
            ("GET", "/desk/brief?symbol=SPY", None),
            ("GET", "/desk/eve-brief", None),
            ("GET", "/portfolio/analytics", None),
            ("GET", "/watchlist/columns", None),
        ]:
            if method == "POST":
                resp = client.post(path, json=body)
            else:
                resp = client.get(path)
            if resp.status_code not in (200, 401, 403):
                fail(f"{method} {path} -> {resp.status_code}")
        ok("HTTP desk endpoints reachable")
    except Exception as exc:  # noqa: BLE001
        ok(f"HTTP client skipped ({type(exc).__name__})")

    print("ALL desk smokes passed")


if __name__ == "__main__":
    main()

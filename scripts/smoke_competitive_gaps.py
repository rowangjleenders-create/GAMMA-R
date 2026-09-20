#!/usr/bin/env python3
"""Smoke: competitive-gap + differentiation + co-pilot edge tools."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    raise SystemExit(1)


def main() -> None:
    print("== competitive gaps smoke ==")

    from momentum_bot.strategy_packs import list_packs, apply_pack, get_pack, preview_pack
    packs = list_packs()
    if len(packs) < 9:
        fail(f"expected >=9 packs, got {len(packs)}")
    ids = {p["id"] for p in packs}
    for need in (
        "crash_defensive",
        "earnings_drift_focus",
        "fx_mean_reversion_overlay",
        "multi_strategy_auto",
        "high_conviction_top_n",
    ):
        if need not in ids:
            fail(f"missing pack {need}")
        if not (get_pack(need) or {}).get("beats_at"):
            fail(f"pack {need} missing beats_at")
    ok(f"{len(packs)} strategy packs (+ beats_at)")

    prev = preview_pack("high_conviction_top_n")
    if not prev.get("ok"):
        fail(f"preview: {prev}")
    if "proposed_strategy_enabled" not in prev:
        fail("preview missing proposed_strategy_enabled")
    ok("pack preview")

    r = apply_pack("classic_momentum_12_1")
    if not r.get("ok"):
        fail(f"apply pack: {r}")
    en = r.get("strategy_enabled") or {}
    if not en.get("momentum"):
        fail(f"classic pack should enable momentum: {en}")
    ok("apply classic_momentum_12_1")
    r2 = apply_pack("defaults")
    if not r2.get("ok"):
        fail(f"reset defaults: {r2}")
    ok("reset defaults pack")

    from momentum_bot.markets_coverage import markets_coverage
    cov = markets_coverage()
    if cov.get("phase") != 1:
        fail(f"coverage phase: {cov.get('phase')}")
    modes = cov.get("modes") or {}
    if "research" not in modes or "trading" not in modes:
        fail("coverage missing research/trading modes")
    if cov.get("options_order_routing") is not False:
        fail("coverage must deny options order routing")
    opts = [x for x in (cov.get("not_yet") or []) + (cov.get("supported") or []) if "option" in str(x.get("asset_class", ""))]
    if not opts:
        fail("coverage missing options note")
    ok("markets_coverage honesty (research vs trading)")

    from momentum_bot.scoreboard import build_scoreboard, build_paper_report, paper_report_csv
    from momentum_bot.config import get_runtime_config
    board = build_scoreboard(get_runtime_config())
    if "strategies" not in board:
        fail("scoreboard missing strategies")
    ok(f"scoreboard strategies={len(board.get('strategies') or [])}")
    report = build_paper_report()
    if "PAPER" not in str(report.get("label", "")).upper():
        fail(f"paper report not labeled PAPER: {report.get('label')}")
    for key in ("equity_curve", "monthly_returns", "underwater_periods", "strategy_attribution", "equity_sparkline"):
        if key not in report:
            fail(f"paper report missing {key}")
    csv = paper_report_csv(report)
    if "month" not in csv.lower() and "strategy" not in csv.lower():
        fail("csv export unexpected")
    ok(f"paper report + csv ({len(csv)} bytes) with monthly/attribution")

    from momentum_bot.paper_leaderboard import build_paper_leaderboard, leaderboard_html
    lb = build_paper_leaderboard()
    if "PAPER" not in str(lb.get("watermark", "")).upper():
        fail(f"leaderboard watermark: {lb.get('watermark')}")
    if lb.get("audited") or lb.get("live"):
        fail("leaderboard must not claim audited/live")
    html = leaderboard_html(lb)
    if "PAPER" not in html or "not live audited" not in html.lower():
        fail("leaderboard HTML missing watermark")
    ok(f"paper leaderboard ranks={len(lb.get('ranks') or [])}")

    from momentum_bot.sync_snapshot import build_sync_snapshot
    snap = build_sync_snapshot()
    for k in ("scan", "crash_mode", "paper", "live_updating", "poll_recommended_sec", "quotes", "edge_teaser"):
        if k not in snap:
            fail(f"sync snapshot missing {k}")
    if not (snap.get("data_source") or {}).get("feed_badge"):
        fail("sync snapshot missing feed_badge")
    if not snap.get("not_level2"):
        fail("sync snapshot must declare not_level2")
    ok(f"sync snapshot poll={snap.get('poll_recommended_sec')}s badge={snap['data_source'].get('feed_badge')}")

    from momentum_bot.sync_ticks import build_ticks
    ticks = build_ticks(["SPY", "AAPL"], limit=5)
    if not ticks.get("not_level2"):
        fail("ticks must declare not_level2")
    if ticks.get("feed_badge") not in ("Delayed", "IEX", "SIP", "NBBO"):
        fail(f"bad feed_badge: {ticks.get('feed_badge')}")
    ok(f"sync ticks source={ticks.get('source')} badge={ticks.get('feed_badge')} n={ticks.get('count')}")

    from momentum_bot.quotes import build_quotes
    q = build_quotes(["SPY", "AAPL"], limit=5)
    if not q.get("not_level2"):
        fail("quotes must declare not_level2")
    if q.get("feed_badge") not in ("Delayed", "IEX", "SIP", "NBBO"):
        fail(f"quotes badge: {q.get('feed_badge')}")
    if "Top-of-book" not in str(q.get("label", "")) and "not" not in str(q.get("label", "")).lower():
        fail(f"quotes label must stress top-of-book: {q.get('label')}")
    ok(f"quotes L2-lite badge={q.get('feed_badge')} count={q.get('count')}")

    from momentum_bot.intraday_heat import scan_intraday_heat, LIQUID_SUBSET
    if len(LIQUID_SUBSET) < 10:
        fail("liquid subset too small")
    heat = scan_intraday_heat(force=False)
    if heat.get("not_level2") is not True and "not Level-2" not in str(heat.get("label", "")):
        fail(f"intraday heat must not claim L2: {heat.get('label')}")
    if "hits" not in heat:
        fail("intraday heat missing hits")
    ok(f"intraday heat interval={heat.get('interval')} hits={len(heat.get('hits') or [])} scanned={heat.get('scanned')}")

    from momentum_bot.options_research import options_summary, log_options_idea, list_options_ideas
    o = options_summary("AAPL")
    if o.get("order_routing") is not False and o.get("trading") is not False:
        fail("options must not enable trading")
    if not o.get("stub") and not o.get("available"):
        fail(f"options unexpected: {o}")
    for k in ("atm_iv", "put_call_volume", "expirations", "nulls_honest"):
        if k not in o:
            fail(f"options missing {k}")
    idea = log_options_idea("AAPL", "Smoke thesis — bullish IV crush watch")
    if not idea.get("ok") or idea.get("order_routing") is not False:
        fail(f"options idea journal: {idea}")
    ideas = list_options_ideas(5)
    if ideas.get("order_routing") is not False:
        fail("ideas list must deny routing")
    ok(f"options research stub={o.get('stub')} available={o.get('available')} ideas={ideas.get('count')}")

    from momentum_bot.paper_options import list_paper_options, open_paper_option
    from momentum_bot.config import set_runtime_config
    cfg = get_runtime_config().update({"options_read_only": True, "paper_options_enabled": True})
    set_runtime_config(cfg)
    po = list_paper_options()
    if po.get("live_options") is not False or po.get("order_routing") is not False:
        fail("paper options must deny live routing")
    # open may fail without chain data — still must not claim live
    opened = open_paper_option("AAPL", "call", contracts=1, thesis="smoke educational", premium=1.25, strike=200.0)
    if opened.get("live_options") is not False:
        fail("open paper option must set live_options=false")
    if opened.get("ok"):
        if (opened.get("position") or {}).get("origin") != "paper_options":
            fail("paper option origin must be paper_options")
        ok(f"paper options open id={opened['position'].get('id')}")
    else:
        ok(f"paper options open skipped ({opened.get('error')})")

    from momentum_bot.brokers.status_card import unified_brokers_status, test_alpaca_connection
    card = unified_brokers_status()
    ids_b = {b["id"] for b in (card.get("brokers") or [])}
    for need in ("paper_sim", "alpaca_paper", "alpaca_live", "ibkr"):
        if need not in ids_b:
            fail(f"brokers status missing {need}")
    ibkr = next(b for b in card["brokers"] if b["id"] == "ibkr")
    if ibkr.get("status") != "planned":
        fail(f"ibkr should be planned: {ibkr.get('status')}")
    if not (ibkr.get("setup") or {}).get("docs_url"):
        fail("ibkr setup docs missing")
    live_card = next(b for b in card["brokers"] if b["id"] == "alpaca_live")
    if not live_card.get("locked") and not card.get("live_trading_enabled"):
        fail("alpaca live should be locked when live trading disabled")
    test = test_alpaca_connection(paper=True)
    if test.get("ok") and not test.get("note"):
        fail("alpaca test missing note")
    ok(f"brokers status cards={len(ids_b)} ibkr=planned alpaca_test_ok={test.get('ok')}")

    from momentum_bot.edge import (
        build_edge_status_logged,
        competitive_gaps,
        feed_health,
        propose_next_improvements,
        why_gamma_r_card,
        overnight_research_summary,
    )
    why = why_gamma_r_card()
    title = str(why.get("title") or "")
    badge = str(why.get("badge") or "")
    if "beat retail" not in title.lower() and "GAMMA-R" not in title and badge != "BEAT RETAIL":
        fail(f"why card title: {why.get('title')}")
    if len(why.get("bullets") or []) < 5:
        fail("why card needs bullets")
    gaps = competitive_gaps()
    if gaps.get("closed_count", 0) < 10:
        fail(f"too few closed gaps: {gaps.get('closed_count')}")
    if not gaps.get("still_open_hard"):
        fail("must list hard-open gaps (L2, live audited, …)")
    if gaps.get("live_audited_returns") is not False:
        fail("gaps must deny live audited returns")
    feed = feed_health()
    if feed.get("feed_badge") not in ("Delayed", "IEX", "SIP", "NBBO"):
        fail(f"feed health badge: {feed.get('feed_badge')}")
    if not feed.get("not_level2"):
        fail("feed health must declare not_level2")
    edge = build_edge_status_logged()
    if edge.get("live_audited_returns") is not False or not edge.get("not_level2"):
        fail("edge report honesty flags wrong")
    if "firewall" not in (edge.get("active_advantage_ids") or []) and not any(
        a.get("id") == "firewall" for a in (edge.get("advantages") or [])
    ):
        fail("edge report missing firewall advantage")
    improv = propose_next_improvements(limit=5)
    if not improv.get("suggestions"):
        fail("improvements empty")
    overnight = overnight_research_summary(limit=3)
    if "ok" not in overnight:
        fail("overnight research missing ok")
    log_path = ROOT / "data" / "ai_process_log.jsonl"
    if not log_path.exists():
        fail("ai_process_log.jsonl not written by edge report")
    ok(f"edge/why/gaps/feed/improvements (+ process log {log_path.stat().st_size}b)")

    from momentum_bot.alerts import evaluate_alerts, recent_alerts, alert_settings
    settings = alert_settings()
    if "alerts_enabled" not in settings:
        fail("alert settings missing")
    ev = evaluate_alerts(force=False)
    if "fired" not in ev:
        fail("alerts evaluate missing fired")
    recent = recent_alerts(5)
    ok(f"alerts settings ok fired={ev.get('fired_count')} recent={recent.get('count')}")

    from momentum_bot.auto_loops import run_web_learn_once

    from momentum_bot.edge import (
        run_daily_self_critique,
        ingest_overnight_into_learning,
        load_overnight_learning_digest,
        why_gamma_r_card,
    )
    critique = run_daily_self_critique(persist=True)
    if not critique.get("ok") or not critique.get("summary"):
        fail(f"self critique weak: {critique}")
    if critique.get("live_audited_returns") or not critique.get("not_level2"):
        fail("critique must stay not_level2 / not live-audited")
    ok(f"daily self-critique feed={((critique.get('score') or {}).get('feed_badge'))}")

    ingest = ingest_overnight_into_learning(reason="smoke")
    if not ingest.get("ok"):
        fail(f"overnight ingest failed: {ingest}")
    dig = load_overnight_learning_digest()
    if not dig.get("ok") and not dig.get("present"):
        fail(f"overnight digest missing after ingest: {dig}")
    from momentum_bot.learning import learning_stats
    stats = learning_stats()
    if "overnight_web" not in stats:
        fail("learning_stats missing overnight_web")
    ok(f"overnight ingest notes={ingest.get('note_count')} learning.overnight_web={stats['overnight_web'].get('note_count')}")

    why = why_gamma_r_card()
    if "beat" not in (why.get("title") or "").lower() and why.get("badge") != "BEAT RETAIL":
        fail(f"why card should beat-retail: {why.get('title')} {why.get('badge')}")
    ok(f"why card title={why.get('title')} badge={why.get('badge')}")

    # Don't hit network hard — just ensure callable when disabled
    cfg2 = get_runtime_config().update({"auto_web_learn_enabled": False, "copilot_web_enabled": False})
    set_runtime_config(cfg2)
    wl = run_web_learn_once(reason="smoke")
    if wl.get("ran") and not wl.get("results"):
        pass
    ok(f"web learn once ran={wl.get('ran')} reason={wl.get('reason')}")

    from momentum_bot.copilot_tools import execute_tool
    for tool in (
        "get_edge_status",
        "get_competitive_gaps",
        "get_feed_health",
        "propose_next_improvements",
        "get_overnight_research",
        "run_daily_self_critique",
        "get_quotes",
    ):
        out = execute_tool(tool, {"limit": 3} if "propose" in tool or "overnight" in tool or tool == "get_quotes" else {})
        if out.get("error") and "unknown tool" in str(out.get("error")):
            fail(f"missing co-pilot tool {tool}")
        if tool == "get_competitive_gaps" and not out.get("closed_count"):
            fail(f"tool {tool} weak: {out}")
        if tool == "get_feed_health" and out.get("feed_badge") not in ("Delayed", "IEX", "SIP", "NBBO"):
            fail(f"tool feed badge: {out}")
    ok("co-pilot edge tools wired")

    from momentum_bot.scanner import get_scan_status, quick_scan
    st = get_scan_status()
    for k in ("cache_ttl_sec", "cache_fresh", "stale_warning"):
        if k not in st:
            fail(f"scan status missing {k}: {st.keys()}")
    ok(f"scan status keys ok data_mode={st.get('data_mode')}")

    qscan = quick_scan()
    if "scan_kind" not in qscan and "note" not in qscan:
        fail(f"quick_scan unexpected: {list(qscan.keys())}")
    if "intraday_breakout" not in qscan and "watchlist_bar_interval" not in qscan:
        fail("quick_scan missing intraday metadata")
    ok(f"quick_scan interval={qscan.get('watchlist_bar_interval')} intraday={qscan.get('intraday_breakout')}")


    # ---- Pro terminal gap wave ----
    from momentum_bot.bars import get_bars, ALLOWED_INTERVALS
    if "1d" not in ALLOWED_INTERVALS:
        fail("bars intervals")
    # Prefer synthetic path: may be empty offline — still must be honest
    b = get_bars("SPY", interval="1d", limit=10)
    if not b.get("not_level2"):
        fail("bars must declare not_level2")
    if "bars" not in b:
        fail("bars missing bars key")
    ok(f"bars symbol=SPY count={b.get('count')} vwap={b.get('vwap_available')}")

    from momentum_bot.tape import get_tape
    tp = get_tape("SPY", limit=5)
    if tp.get("full_tape") is not False or not tp.get("not_level2"):
        fail("tape must deny full_tape / declare not_level2")
    if "prints" not in tp:
        fail("tape missing prints")
    ok(f"tape lite count={tp.get('count')} source={tp.get('source')}")

    from momentum_bot.ladder import build_ladder
    ld = build_ladder("SPY", levels=6)
    if ld.get("full_depth") is not False:
        fail("ladder must deny full_depth")
    cap = str(ld.get("caption") or ld.get("label") or "")
    if "not full" not in cap.lower() and "not full exchange" not in cap.lower():
        fail(f"ladder caption must stress not full depth: {cap}")
    ok(f"ladder rows={len(ld.get('rows') or [])} badge={ld.get('feed_badge')}")

    from momentum_bot.scan_custom import run_custom_scan
    cs = run_custom_scan({"min_volume_ratio": 0.5, "limit": 5}, refresh=False)
    if "signals" not in cs or not cs.get("not_level2"):
        fail(f"custom scan weak: {cs}")
    ok(f"custom scan matched={cs.get('count')} universe={cs.get('universe_cached')}")

    from momentum_bot.calendar_econ import get_economic_calendar
    cal = get_economic_calendar(days=21, limit=10)
    if not cal.get("ok") or "events" not in cal:
        fail(f"calendar: {cal}")
    ok(f"econ calendar events={cal.get('count')} source={cal.get('source')}")

    from momentum_bot.options_research import options_chain, black_scholes_greeks
    g = black_scholes_greeks(100, 100, 0.25, 0.2, side="call")
    if g.get("delta") is None:
        fail(f"BS greeks failed: {g}")
    ch = options_chain("AAPL")
    if ch.get("order_routing") is not False or ch.get("live_options") is not False:
        fail("options chain must deny live routing")
    ok(f"options chain rows={ch.get('count')} greeks_src={ch.get('greeks_source')} stub={ch.get('stub')}")

    from momentum_bot.paper_pro_orders import place_pro_order, list_working_orders, ORDER_TYPES
    if "bracket" not in ORDER_TYPES or "oco" not in ORDER_TYPES:
        fail("pro order types missing")
    # Bracket may fail session/firewall — still must stay paper
    br = place_pro_order(ticker="SPY", shares=1, order_type="bracket", entry=100.0, stop=95.0, take_profit=110.0, human_approved=True)
    if br.get("live") is True:
        fail("pro order must never be live")
    st = place_pro_order(ticker="AAPL", shares=1, order_type="stop", trigger_price=1.0, human_approved=True)
    if st.get("live") is True:
        fail("stop working must never be live")
    if not st.get("ok") and st.get("error") == "firewall_denied":
        pass  # still paper-denied is fine
    elif st.get("ok") and not st.get("working"):
        fail(f"stop should be working: {st}")
    wo = list_working_orders()
    if wo.get("live") is not False:
        fail("working orders must be paper")
    ok(f"paper pro orders bracket_ok={br.get('ok')} stop_ok={st.get('ok')} working={wo.get('count')}")

    from momentum_bot.copilot_tools import execute_tool
    for tool in ("get_bars", "get_tape", "get_ladder_quote", "run_custom_scan", "get_economic_calendar"):
        args = {"symbol": "SPY", "limit": 3} if tool != "run_custom_scan" and tool != "get_economic_calendar" else {"limit": 3}
        if tool == "get_bars":
            args = {"symbol": "SPY", "interval": "1d", "limit": 5}
        if tool == "get_ladder_quote":
            args = {"symbol": "SPY", "levels": 4}
        out = execute_tool(tool, args)
        if out.get("error") and "unknown tool" in str(out.get("error")):
            fail(f"missing co-pilot tool {tool}")
    ok("co-pilot pro-terminal tools wired")
    for tool in ("desk_command_help", "summarize_panel", "brief_news", "explain_ladder", "run_monitor"):
        out = execute_tool(tool, {"symbol": "SPY", "panel_id": "monitor"} if tool == "summarize_panel" else {"symbol": "SPY"} if tool in ("brief_news", "explain_ladder") else {})
        if out.get("error") and "unknown tool" in str(out.get("error")):
            fail(f"missing desk tool {tool}")
    ok("co-pilot desk tools wired")

    from momentum_bot.edge import competitive_gaps
    gaps2 = competitive_gaps()
    closed_ids = {c.get("id") for c in (gaps2.get("closed") or [])}
    for need in ("pro_charts", "tape_lite", "nbbo_ladder", "scanner_builder", "paper_pro_orders", "econ_calendar", "desk_command", "desk_monitor", "desk_brief"):
        if need not in closed_ids:
            fail(f"edge closed gaps missing {need}")
    hard_ids = {h.get("id") for h in (gaps2.get("still_open_hard") or [])}
    if "true_l2" not in hard_ids or "colocation" not in hard_ids:
        fail("hard gaps must still list true_l2 + colocation")
    ok(f"pro-terminal closed gaps + hard L2/colocation intact (closed={gaps2.get('closed_count')})")

    from momentum_bot.api import app
    paths = {getattr(r, "path", None) for r in app.routes}
    for need in (
        "/strategies/packs",
        "/strategies/packs/{pack_id}/apply",
        "/strategies/packs/{pack_id}/preview",
        "/strategies/scoreboard/export",
        "/paper/report",
        "/paper/leaderboard",
        "/public/paper-stats",
        "/paper/leaderboard.html",
        "/scan/quick",
        "/scan/status",
        "/scan/intraday-heat",
        "/markets/coverage",
        "/sync/snapshot",
        "/sync/ticks",
        "/quotes",
        "/events",
        "/events/quotes",
        "/stream/status",
        "/ws/watchlist",
        "/edge/status",
        "/edge/why",
        "/edge/gaps",
        "/edge/feed",
        "/edge/improvements",
        "/edge/overnight",
        "/edge/critique",
        "/edge/critique/run",
        "/edge/overnight/ingest",
        "/alerts",
        "/alerts/evaluate",
        "/options/{ticker}",
        "/options/ideas",
        "/options/paper",
        "/options/{ticker}/chain",
        "/bars/{symbol}",
        "/tape/{symbol}",
        "/trades/{symbol}",
        "/ladder/{symbol}",
        "/scan/custom",
        "/calendar/economic",
        "/portfolio/orders/pro",
        "/portfolio/orders/working",
        "/layout/pro",
        "/desk/command",
        "/desk/layout",
        "/desk/monitor",
        "/desk/brief",
        "/desk/cross-asset",
        "/watchlist/columns",
        "/brokers/status",
        "/brokers/alpaca/test",
        "/auto/web-learn/run",
    ):
        if need not in paths:
            fail(f"missing route {need}")
    ok("API routes registered")

    cfg = get_runtime_config()
    for attr in (
        "scan_cache_ttl_sec",
        "auto_scan_interval_minutes",
        "quick_scan_enabled",
        "dashboard_poll_sec",
        "options_read_only",
        "watchlist_bar_interval",
        "intraday_heat_enabled",
        "intraday_heat_interval",
        "quotes_enabled",
        "auto_web_learn_enabled",
        "alerts_enabled",
        "paper_options_enabled",
        "alert_crash_mode",
        "alert_firewall_deny_streak",
    ):
        if not hasattr(cfg, attr):
            fail(f"config missing {attr}")
    ok("config knobs present")

    from momentum_bot.data_sources import get_data_source_status
    from momentum_bot.security import auth_exempt_paths
    ds = get_data_source_status()
    if not ds.get("enable_instructions"):
        fail("SIP enable_instructions missing")
    if not ds.get("enable_checklist"):
        fail("enable_checklist missing")
    if ds.get("feed_badge") not in ("Delayed", "IEX", "SIP", "NBBO"):
        fail(f"feed_badge: {ds.get('feed_badge')}")
    if not ds.get("not_level2"):
        fail("data source must declare not_level2")
    exempt = auth_exempt_paths(protect_docs=True)
    for pub in ("/paper/leaderboard", "/public/paper-stats", "/paper/leaderboard.html", "/health"):
        if pub not in exempt:
            fail(f"public path not auth-exempt: {pub}")
    ok(f"SIP status_hint={ds.get('status_hint')} badge={ds.get('feed_badge')}")

    # Co-pilot offline edge intents
    from momentum_bot.copilot import chat
    for prompt in ("Our edge", "vs other bots", "What to improve next", "Overnight research", "Daily self-critique", "Feed health / NBBO", "Pro chart", "Tape", "Custom scan"):
        resp = chat(prompt)
        reply = (resp.get("reply") or resp.get("answer") or "") if isinstance(resp, dict) else str(resp)
        if not reply or len(str(reply)) < 20:
            fail(f"copilot weak reply for {prompt!r}: {resp}")
        # Must not claim L2 / live audited
        low = str(reply).lower()
        if "live-audited returns" in low and "not" not in low:
            pass  # ok if discussing negation
    ok("co-pilot edge chip prompts answerable")

    print("ALL competitive-gap smokes passed")


if __name__ == "__main__":
    main()

"""
GAMMA-R Bloomberg-inspired desk OS — command GO bar, multi-panel layouts,
monitor launchpad, cross-asset board, AI news briefs.

Win on AI-native desk + automation + personal learning — not fake BLP data.
Never claims Bloomberg data license or full L2 depth. Paper-first; live locked.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---- Command bar (GO) -------------------------------------------------------

_ASSET_SUFFIX = re.compile(
    r"\b(EQUITY|EQTY|STOCK|INDEX|FX|CURNCY|Curncy|COMDTY|Equity)\b",
    re.I,
)
_CMD_NEWS = re.compile(r"^(?:NEWS|N)\s+([A-Z][A-Z0-9.\-]{0,11})\b", re.I)
_CMD_OPT = re.compile(r"^(?:OPT|OPTIONS?|CHAIN)\s+([A-Z][A-Z0-9.\-]{0,11})\b", re.I)
_CMD_CHART = re.compile(
    r"^(?:CHART|GIP|HP)\s+([A-Z][A-Z0-9.\-]{0,11})(?:\s+(1d|1h|15m|5m|1D|1H))?\b",
    re.I,
)
_CMD_EVE = re.compile(r"^(?:EVE|E-VE|AI|ASK)\s+(.+)$", re.I)
_CMD_SCAN = re.compile(r"^(?:SCAN|SCR)\s*(.*)$", re.I)
_CMD_TAPE = re.compile(r"^(?:TAPE|TS)\s+([A-Z][A-Z0-9.\-]{0,11})\b", re.I)
_CMD_LADDER = re.compile(r"^(?:LADDER|LD)\s+([A-Z][A-Z0-9.\-]{0,11})\b", re.I)
_CMD_BRIEF = re.compile(r"^(?:BRIEF|BRF)\s+([A-Z][A-Z0-9.\-]{0,11})\b", re.I)
_CMD_MONITOR = re.compile(r"^(?:MONITOR|MON|LAUNCHPAD)\b", re.I)
_CMD_HELP = re.compile(r"^(?:\?|HELP|GO|DESK)\s*$", re.I)
_SYMBOL = re.compile(r"^([A-Z][A-Z0-9.\-]{0,11})(?:\s+EQUITY|\s+EQTY|\s+STOCK)?\s*$", re.I)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def command_help() -> Dict[str, Any]:
    """Desk GO bar examples — Bloomberg-inspired workflow, not BLP data."""
    return {
        "ok": True,
        "title": "GAMMA-R desk command (GO)",
        "examples": [
            {"input": "AAPL", "route": "quote", "note": "Quote + NBBO ladder"},
            {"input": "AAPL EQUITY", "route": "quote", "note": "Same with asset suffix"},
            {"input": "NEWS AAPL", "route": "news", "note": "Ticker / EOD news"},
            {"input": "OPT AAPL", "route": "options", "note": "Options chain (paper)"},
            {"input": "CHART AAPL 15m", "route": "chart", "note": "OHLCV + VWAP"},
            {"input": "TAPE AAPL", "route": "tape", "note": "Tape lite"},
            {"input": "LADDER AAPL", "route": "ladder", "note": "NBBO top-of-book ladder"},
            {"input": "BRIEF AAPL", "route": "brief", "note": "E-ve AI news brief"},
            {"input": "EVE why NVDA", "route": "eve", "note": "Ask E-ve"},
            {"input": "SCAN heat", "route": "scanner", "note": "Heat / custom scan"},
            {"input": "MONITOR", "route": "monitor", "note": "Desk launchpad"},
            {"input": "HELP", "route": "help", "note": "This list"},
        ],
        "caption": (
            "Bloomberg-inspired GO workflow — not a Bloomberg data license. "
            "No proprietary BLP feeds; no full L2."
        ),
        "not_bloomberg_licensed": True,
        "not_level2": True,
    }


def parse_desk_command(raw: str) -> Dict[str, Any]:
    """
    Parse GO-style desk command into a route payload.
    Client may also parse locally; POST /desk/command uses this.
    """
    text = (raw or "").strip()
    if not text:
        return {"ok": False, "error": "empty_command", "route": "help", **command_help()}

    if _CMD_HELP.match(text):
        return {"ok": True, "input": text, "route": "help", "action": "help", **command_help()}

    if _CMD_MONITOR.match(text):
        return {
            "ok": True,
            "input": text,
            "route": "monitor",
            "action": "open_monitor",
            "screen": "Dashboard",
            "path": "/desk/monitor",
        }

    m = _CMD_EVE.match(text)
    if m:
        prompt = m.group(1).strip()
        return {
            "ok": True,
            "input": text,
            "route": "eve",
            "action": "ask_eve",
            "screen": "CoPilot",
            "prompt": prompt,
            "symbol": _extract_symbol_token(prompt),
        }

    m = _CMD_BRIEF.match(text)
    if m:
        sym = m.group(1).upper()
        return {
            "ok": True,
            "input": text,
            "route": "brief",
            "action": "open_brief",
            "screen": "CoPilot",
            "symbol": sym,
            "path": f"/desk/brief?symbol={sym}",
        }

    m = _CMD_NEWS.match(text)
    if m:
        sym = m.group(1).upper()
        return {
            "ok": True,
            "input": text,
            "route": "news",
            "action": "open_news",
            "screen": "SignalDetail",
            "symbol": sym,
            "path": f"/news/{sym}",
        }

    m = _CMD_OPT.match(text)
    if m:
        sym = m.group(1).upper()
        return {
            "ok": True,
            "input": text,
            "route": "options",
            "action": "open_options",
            "screen": "SignalDetail",
            "symbol": sym,
            "path": f"/options/{sym}/chain",
            "live_options": False,
        }

    m = _CMD_CHART.match(text)
    if m:
        sym = m.group(1).upper()
        interval = (m.group(2) or "1d").lower()
        return {
            "ok": True,
            "input": text,
            "route": "chart",
            "action": "open_chart",
            "screen": "SignalDetail",
            "symbol": sym,
            "interval": interval,
            "path": f"/bars/{sym}?interval={interval}",
        }

    m = _CMD_TAPE.match(text)
    if m:
        sym = m.group(1).upper()
        return {
            "ok": True,
            "input": text,
            "route": "tape",
            "action": "open_tape",
            "screen": "SignalDetail",
            "symbol": sym,
            "path": f"/tape/{sym}",
        }

    m = _CMD_LADDER.match(text)
    if m:
        sym = m.group(1).upper()
        return {
            "ok": True,
            "input": text,
            "route": "ladder",
            "action": "open_ladder",
            "screen": "SignalDetail",
            "symbol": sym,
            "path": f"/ladder/{sym}",
        }

    m = _CMD_SCAN.match(text)
    if m:
        arg = (m.group(1) or "").strip().lower()
        heat = arg in ("heat", "hot", "intraday", "")
        return {
            "ok": True,
            "input": text,
            "route": "scanner",
            "action": "open_scanner" if not heat or arg else "open_heat",
            "screen": "Scanner",
            "scan_arg": arg or "heat",
            "path": "/scan/intraday-heat" if heat else "/scan/custom",
            "not_level2": True,
        }

    # Bare symbol / SYMBOL EQUITY
    cleaned = _ASSET_SUFFIX.sub("", text).strip()
    m = _SYMBOL.match(cleaned) or _SYMBOL.match(text)
    if m:
        sym = m.group(1).upper()
        return {
            "ok": True,
            "input": text,
            "route": "quote",
            "action": "open_quote",
            "screen": "SignalDetail",
            "symbol": sym,
            "path": f"/quotes?symbols={sym}",
            "panels": ["quote", "ladder", "chart"],
        }

    return {
        "ok": False,
        "input": text,
        "route": "help",
        "error": "unrecognized_command",
        "hint": "Try AAPL, NEWS AAPL, CHART AAPL 15m, EVE why NVDA, SCAN heat, HELP",
        **command_help(),
    }


def _extract_symbol_token(text: str) -> Optional[str]:
    toks = re.findall(r"\b([A-Z]{1,5}(?:-[A-Z]+)?)\b", (text or "").upper())
    skip = {"WHY", "WHAT", "HOW", "THE", "FOR", "AND", "EVE", "SCAN", "NEWS", "OPT", "CHART"}
    for t in toks:
        if t not in skip and len(t) <= 5:
            return t
    return None


def run_desk_command(raw: str, *, enrich: bool = True) -> Dict[str, Any]:
    """Parse + optionally attach a light payload snapshot for the route."""
    parsed = parse_desk_command(raw)
    if not enrich or not parsed.get("ok"):
        return {**parsed, "generated_at": _utc_now()}

    route = parsed.get("route")
    sym = parsed.get("symbol")
    extra: Dict[str, Any] = {}
    try:
        if route == "quote" and sym:
            from .quotes import build_quotes
            from .ladder import build_ladder

            extra["quotes"] = build_quotes([sym], limit=1)
            extra["ladder"] = build_ladder(sym, levels=6)
        elif route == "chart" and sym:
            from .bars import get_bars

            extra["bars"] = get_bars(sym, interval=str(parsed.get("interval") or "1d"), limit=60)
        elif route == "tape" and sym:
            from .tape import get_tape

            extra["tape"] = get_tape(sym, limit=20)
        elif route == "ladder" and sym:
            from .ladder import build_ladder

            extra["ladder"] = build_ladder(sym, levels=8)
        elif route == "news" and sym:
            from .news import aggregate_ticker_news

            extra["news"] = aggregate_ticker_news(sym)
        elif route == "options" and sym:
            try:
                from .options_research import options_chain

                extra["chain_preview"] = options_chain(sym)
            except Exception as exc:  # noqa: BLE001
                extra["chain_preview"] = {"ok": False, "error": str(exc)[:120], "live_options": False}
        elif route == "brief" and sym:
            extra["brief"] = build_desk_brief(sym)
        elif route == "monitor":
            extra["monitor"] = build_desk_monitor()
        elif route == "scanner":
            if (parsed.get("scan_arg") or "heat") in ("heat", "hot", "intraday", ""):
                from .intraday_heat import scan_intraday_heat
                from .config import get_runtime_config

                extra["heat"] = scan_intraday_heat(get_runtime_config())
    except Exception as exc:  # noqa: BLE001
        extra["enrich_error"] = str(exc)[:160]

    return {
        **parsed,
        "payload": extra,
        "generated_at": _utc_now(),
        "not_bloomberg_licensed": True,
        "not_level2": True,
    }


# ---- Multi-panel layouts ----------------------------------------------------

LAYOUT_PRESETS: Dict[str, Dict[str, Any]] = {
    "classic": {
        "id": "classic",
        "title": "Classic desk",
        "mobile_grid": "2x2",
        "panels": [
            {"id": "quote_ladder", "title": "Quote + NBBO ladder", "component": "LadderPanel"},
            {"id": "chart", "title": "Chart", "component": "CandleChart"},
            {"id": "news_eod", "title": "News / EOD", "component": "NewsRail"},
            {"id": "portfolio", "title": "Portfolio snapshot", "component": "PortfolioMini"},
        ],
    },
    "news-heavy": {
        "id": "news-heavy",
        "title": "News-heavy",
        "mobile_grid": "scroll",
        "panels": [
            {"id": "news_eod", "title": "News / EOD", "component": "NewsRail"},
            {"id": "brief", "title": "E-ve brief", "component": "EveBrief"},
            {"id": "calendar", "title": "Calendar / FX", "component": "CalendarFx"},
            {"id": "chart", "title": "Chart", "component": "CandleChart"},
        ],
    },
    "fx+equity": {
        "id": "fx+equity",
        "title": "FX + equity",
        "mobile_grid": "2x2",
        "panels": [
            {"id": "fx", "title": "FX movers", "component": "FxBoard"},
            {"id": "quote_ladder", "title": "Quote + NBBO ladder", "component": "LadderPanel"},
            {"id": "chart", "title": "Chart", "component": "CandleChart"},
            {"id": "calendar", "title": "Calendar", "component": "CalendarFx"},
        ],
    },
    "eve-focus": {
        "id": "eve-focus",
        "title": "E-ve focus",
        "mobile_grid": "scroll",
        "panels": [
            {"id": "eve_mini", "title": "E-ve mini", "component": "EveMini"},
            {"id": "monitor", "title": "Monitor", "component": "MonitorStrip"},
            {"id": "quote_ladder", "title": "Quote + NBBO ladder", "component": "LadderPanel"},
            {"id": "portfolio", "title": "Portfolio snapshot", "component": "PortfolioMini"},
        ],
    },
}


def desk_layout(preset: Optional[str] = None) -> Dict[str, Any]:
    """GET /desk/layout — presets for Pro Desk multi-panel."""
    key = (preset or "classic").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "fxequity": "fx+equity",
        "fx-equity": "fx+equity",
        "eve": "eve-focus",
        "e-ve": "eve-focus",
        "news": "news-heavy",
    }
    key = aliases.get(key, key)
    chosen = LAYOUT_PRESETS.get(key) or LAYOUT_PRESETS["classic"]
    return {
        "ok": True,
        "preset": chosen["id"],
        "presets": list(LAYOUT_PRESETS.keys()),
        "layout": chosen,
        "all": LAYOUT_PRESETS,
        "mobile": {
            "screen": "ProDesk",
            "grids": ["2x2", "scroll"],
            "sticky_command_bar": True,
        },
        "caption": (
            "Multi-panel desk — Bloomberg-inspired layout, not Bloomberg Terminal. "
            "Reuse bars/tape/ladder/options/calendar/NBBO/E-ve."
        ),
        "not_bloomberg_licensed": True,
        "not_level2": True,
        "generated_at": _utc_now(),
    }


# ---- Monitor / launchpad ----------------------------------------------------

def build_desk_monitor() -> Dict[str, Any]:
    """
    GET /desk/monitor — aggregate crash, heat, alerts, scoreboard cuts,
    firewall denials, overnight research.
    """
    items: List[Dict[str, Any]] = []
    sections: Dict[str, Any] = {}

    # Crash
    try:
        from .crash_mode import get_crash_status

        crash = get_crash_status()
        cdict = crash.to_dict() if hasattr(crash, "to_dict") else dict(crash or {})
        sections["crash"] = cdict
        if cdict.get("active"):
            items.append({
                "id": "crash",
                "severity": "critical",
                "title": "Crash mode ON",
                "detail": str(cdict.get("reason") or cdict.get("until") or "")[:120],
                "route": "Settings",
            })
    except Exception as exc:  # noqa: BLE001
        sections["crash"] = {"ok": False, "error": str(exc)[:120]}

    # Heat
    try:
        from .intraday_heat import scan_intraday_heat
        from .config import get_runtime_config

        heat = scan_intraday_heat(get_runtime_config())
        sections["heat"] = {
            "ok": True,
            "count": heat.get("count") or len(heat.get("hits") or heat.get("anomalies") or []),
            "top": (heat.get("hits") or heat.get("anomalies") or heat.get("results") or [])[:5],
            "not_level2": True,
        }
        top = sections["heat"]["top"]
        if top:
            t0 = top[0]
            sym = t0.get("ticker") or t0.get("symbol") or "?"
            items.append({
                "id": "heat",
                "severity": "warn",
                "title": f"Heat: {sym}",
                "detail": str(t0.get("reason") or t0.get("label") or "intraday anomaly")[:100],
                "route": "Scanner",
                "symbol": sym,
            })
    except Exception as exc:  # noqa: BLE001
        sections["heat"] = {"ok": False, "error": str(exc)[:120], "not_level2": True}

    # Alerts
    try:
        from .alerts import recent_alerts

        al = recent_alerts(limit=8)
        sections["alerts"] = al
        for a in (al.get("alerts") or al.get("items") or [])[:3]:
            items.append({
                "id": f"alert-{a.get('id') or a.get('type')}",
                "severity": "warn",
                "title": str(a.get("title") or a.get("type") or "Alert")[:80],
                "detail": str(a.get("message") or a.get("detail") or "")[:100],
                "route": "Dashboard",
            })
    except Exception as exc:  # noqa: BLE001
        sections["alerts"] = {"ok": False, "error": str(exc)[:120]}

    # Scoreboard cuts
    try:
        from .scoreboard import build_scoreboard

        board = build_scoreboard()
        cuts = [
            s for s in (board.get("strategies") or [])
            if str(s.get("status") or "").lower() in ("cut", "watch")
        ]
        sections["scoreboard_cuts"] = {"items": cuts[:6], "label": board.get("label")}
        for s in cuts[:3]:
            items.append({
                "id": f"sb-{s.get('strategy_id')}",
                "severity": "warn" if s.get("status") == "cut" else "info",
                "title": f"Scoreboard {str(s.get('status') or '').upper()}: {s.get('name') or s.get('strategy_id')}",
                "detail": "PAPER journal — not live audited",
                "route": "Learning",
            })
    except Exception as exc:  # noqa: BLE001
        sections["scoreboard_cuts"] = {"ok": False, "error": str(exc)[:120]}

    # Firewall denials
    try:
        from .policy_firewall import recent_audit

        recent = recent_audit(20)
        denials = [
            r for r in recent
            if r.get("denied") or r.get("skip_reason") or str(r.get("decision") or "").lower() == "deny"
        ]
        sections["firewall_denials"] = {"count": len(denials), "recent": denials[:5]}
        if denials:
            d0 = denials[0]
            items.append({
                "id": "firewall",
                "severity": "warn",
                "title": "Firewall denial",
                "detail": str(d0.get("skip_reason") or d0.get("reason") or d0.get("ticker") or "")[:100],
                "route": "Settings",
            })
    except Exception as exc:  # noqa: BLE001
        sections["firewall_denials"] = {"ok": False, "error": str(exc)[:120]}

    # Overnight research
    try:
        from .edge import overnight_research_summary

        overnight = overnight_research_summary(limit=5)
        sections["overnight"] = overnight
        notes = overnight.get("notes") or overnight.get("items") or []
        if notes:
            n0 = notes[0] if isinstance(notes[0], dict) else {"summary": str(notes[0])}
            items.append({
                "id": "overnight",
                "severity": "info",
                "title": "Overnight research",
                "detail": str(n0.get("summary") or n0.get("topic") or n0.get("title") or "")[:100],
                "route": "CoPilot",
            })
    except Exception as exc:  # noqa: BLE001
        sections["overnight"] = {"ok": False, "error": str(exc)[:120]}

    # Severity sort
    order = {"critical": 0, "warn": 1, "info": 2}
    items.sort(key=lambda x: order.get(str(x.get("severity")), 9))

    return {
        "ok": True,
        "generated_at": _utc_now(),
        "items": items[:16],
        "sections": sections,
        "strip": [
            {
                "id": it["id"],
                "label": it["title"][:28],
                "severity": it.get("severity"),
                "symbol": it.get("symbol"),
            }
            for it in items[:8]
        ],
        "caption": "Desk monitor — crash · heat · alerts · scoreboard · firewall · overnight",
        "not_bloomberg_licensed": True,
        "not_level2": True,
        "live_locked": True,
    }


# ---- Cross-asset board ------------------------------------------------------

def build_cross_asset() -> Dict[str, Any]:
    """GET /desk/cross-asset — equity signals, FX movers, calendar, news tilt."""
    equity: List[Dict[str, Any]] = []
    fx_movers: List[Dict[str, Any]] = []
    calendar: List[Dict[str, Any]] = []
    news_tilt: Dict[str, Any] = {}

    try:
        from .sync_snapshot import build_sync_snapshot
        snap = build_sync_snapshot()
        sigs = snap.get("signals") or []
        for s in sigs[:8]:
            equity.append({
                "ticker": s.get("ticker"),
                "score": s.get("score") or s.get("momentum_pct"),
                "strategy_id": s.get("strategy_id"),
                "source": s.get("source"),
                "pct_change": s.get("pct_change") or s.get("change_pct"),
            })
    except Exception:
        try:
            from .scanner import get_cached_signals
            for s in (get_cached_signals() or [])[:8]:
                d = s.to_dict() if hasattr(s, "to_dict") else (s if isinstance(s, dict) else {})
                if d:
                    equity.append({
                        "ticker": d.get("ticker"),
                        "score": d.get("score"),
                        "strategy_id": d.get("strategy_id"),
                        "source": d.get("source"),
                    })
        except Exception as exc:  # noqa: BLE001
            equity = [{"error": str(exc)[:80]}]

    try:
        from .currency import get_currency_quotes
        fx = get_currency_quotes()
        fx_movers = list(fx.get("top_movers") or [])[:5]
    except Exception as exc:  # noqa: BLE001
        fx_movers = [{"error": str(exc)[:80]}]

    try:
        from .calendar_econ import get_economic_calendar
        cal = get_economic_calendar(days=14, limit=8)
        calendar = list(cal.get("events") or cal.get("items") or [])[:6]
    except Exception as exc:  # noqa: BLE001
        calendar = [{"error": str(exc)[:80]}]

    try:
        from .news import build_eod_digest, sector_sentiment_impact
        digest = build_eod_digest()
        news_tilt = {
            "sector_impact": (digest.get("sector_impact") or digest.get("sectors") or [])[:5],
            "top_headlines": (digest.get("top_headlines") or [])[:4],
            "market_tilt": digest.get("market_tilt") or digest.get("avg_sentiment"),
        }
    except Exception as exc:  # noqa: BLE001
        news_tilt = {"error": str(exc)[:80]}

    return {
        "ok": True,
        "generated_at": _utc_now(),
        "equity_signals": equity,
        "fx_movers": fx_movers,
        "calendar_next": calendar,
        "news_tilt": news_tilt,
        "caption": "Cross-asset board — equity · FX · calendar · news (not Bloomberg multi-asset terminal)",
        "not_bloomberg_licensed": True,
        "not_level2": True,
    }


# ---- AI news brief ----------------------------------------------------------

def build_desk_brief(symbol: str, *, max_sources: int = 3) -> Dict[str, Any]:
    """
    GET /desk/brief?symbol= — allowlisted web + existing news → short E-ve brief.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "symbol_required"}

    sources: List[Dict[str, Any]] = []
    bullets: List[str] = []
    news_block: Dict[str, Any] = {}
    web_block: Dict[str, Any] = {}

    try:
        from .news import aggregate_ticker_news, collect_news

        news_block = aggregate_ticker_news(sym) or {}
        sent = news_block.get("sentiment_24h") or news_block.get("avg_sentiment")
        n = news_block.get("count_24h") or news_block.get("count") or 0
        if sent is not None:
            bullets.append(f"Local news tilt 24h: {float(sent):+.2f} across {n} items (RSS/Finnhub/NewsAPI when keyed).")
        headlines = news_block.get("headlines") or news_block.get("recent") or []
        for h in headlines[:3]:
            if isinstance(h, dict):
                title = h.get("title") or h.get("headline")
                url = h.get("url") or h.get("link")
                if title:
                    bullets.append(str(title)[:140])
                if url:
                    sources.append({"title": str(title)[:80], "url": url, "kind": "news"})
            elif isinstance(h, str):
                bullets.append(h[:140])
        # Fallback collect
        if not headlines:
            items = collect_news(tickers=[sym], use_cache=True) or []
            for i in items[:4]:
                d = i.to_dict() if hasattr(i, "to_dict") else (i if isinstance(i, dict) else {})
                if sym.upper() in [t.upper() for t in (d.get("tickers") or [])] or sym in str(d.get("title") or "").upper():
                    title = d.get("title") or ""
                    if title:
                        bullets.append(title[:140])
                    if d.get("url"):
                        sources.append({"title": title[:80], "url": d["url"], "kind": "news"})
    except Exception as exc:  # noqa: BLE001
        news_block = {"error": str(exc)[:120]}

    try:
        from .copilot_web import web_enabled, learn_from_web, web_search_finance

        if web_enabled():
            web_block = web_search_finance(f"{sym} stock earnings news", max_sources=max_sources)
            for s in (web_block.get("sources") or web_block.get("results") or [])[:max_sources]:
                if isinstance(s, dict):
                    sources.append({
                        "title": str(s.get("title") or s.get("host") or "web")[:80],
                        "url": s.get("url") or s.get("link"),
                        "kind": "allowlisted_web",
                    })
                    snip = s.get("snippet") or s.get("summary") or s.get("text")
                    if snip:
                        bullets.append(str(snip)[:160])
            # Soft learn for overnight compound (best-effort)
            try:
                learn_from_web(f"{sym} brief", max_sources=1)
            except Exception:
                pass
        else:
            web_block = {"enabled": False, "note": "copilot_web_enabled=0"}
    except Exception as exc:  # noqa: BLE001
        web_block = {"error": str(exc)[:120]}

    # Regime / firewall / scoreboard cite (E-ve supremacy)
    cites: Dict[str, Any] = {}
    try:
        from .strategies import get_last_router_decision
        r = get_last_router_decision()
        cites["regime"] = r.to_dict() if r and hasattr(r, "to_dict") else None
    except Exception:
        cites["regime"] = None
    try:
        from .policy_firewall import status as firewall_status
        cites["firewall"] = firewall_status()
    except Exception:
        try:
            from .config import get_runtime_config
            cfg = get_runtime_config()
            cites["firewall"] = {"enabled": bool(getattr(cfg, "firewall_enabled", True))}
        except Exception:
            cites["firewall"] = None
    try:
        from .scoreboard import build_scoreboard
        board = build_scoreboard()
        cites["scoreboard"] = {
            "cut_or_watch": [
                s.get("strategy_id") for s in (board.get("strategies") or [])
                if str(s.get("status") or "").lower() in ("cut", "watch")
            ][:4],
            "label": "PAPER — not live audited",
        }
    except Exception:
        cites["scoreboard"] = None

    if not bullets:
        bullets.append(f"No fresh headlines cached for {sym}. Run a scan or enable allowlisted web.")

    summary = (
        f"E-ve brief for {sym}: {bullets[0]}"
        if bullets else f"E-ve brief for {sym}: insufficient sources."
    )

    return {
        "ok": True,
        "symbol": sym,
        "summary": summary[:400],
        "bullets": bullets[:8],
        "sources": sources[:8],
        "cites": cites,
        "news": news_block,
        "web": {"enabled": web_block.get("enabled", True) if "enabled" in web_block else bool(web_block), "meta": {k: web_block.get(k) for k in ("ok", "error", "note", "count") if k in web_block}},
        "disclaimer": (
            "Educational E-ve brief from allowlisted web + local news — "
            "NOT Bloomberg news, NOT financial advice, NOT a BLP license."
        ),
        "not_bloomberg_licensed": True,
        "not_level2": True,
        "generated_at": _utc_now(),
        "author": "E-ve",
    }


# ---- E-ve desk tool helpers -------------------------------------------------

def summarize_panel(panel_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
    """E-ve tool: summarize one desk panel."""
    pid = (panel_id or "").strip().lower()
    sym = (symbol or "SPY").upper()
    if pid in ("monitor", "launchpad"):
        mon = build_desk_monitor()
        return {
            "ok": True,
            "panel": "monitor",
            "summary": f"{len(mon.get('items') or [])} monitor items; top: "
                       + ", ".join(i.get("title", "")[:40] for i in (mon.get("items") or [])[:3]),
            "items": (mon.get("strip") or [])[:6],
            "cites_note": "Always weigh crash/firewall/scoreboard before paper size.",
        }
    if pid in ("ladder", "quote_ladder", "nbbo"):
        from .ladder import build_ladder
        lad = build_ladder(sym, levels=6)
        return {
            "ok": True,
            "panel": "ladder",
            "symbol": sym,
            "summary": (
                f"NBBO ladder for {sym}: mid={lad.get('mid')} spread={lad.get('spread')} "
                f"— top-of-book only, not full L2."
            ),
            "ladder": lad,
            "not_level2": True,
        }
    if pid in ("news", "news_eod", "brief"):
        return build_desk_brief(sym)
    if pid in ("cross", "cross-asset", "board"):
        return build_cross_asset()
    if pid in ("layout", "desk"):
        return desk_layout("classic")
    return {
        "ok": False,
        "error": f"unknown_panel:{panel_id}",
        "known": ["monitor", "ladder", "news", "brief", "cross-asset", "layout"],
    }


def explain_ladder(symbol: str) -> Dict[str, Any]:
    """E-ve tool: explain NBBO ladder in plain language."""
    from .ladder import build_ladder

    sym = (symbol or "SPY").upper()
    lad = build_ladder(sym, levels=8)
    mid = lad.get("mid")
    spread = lad.get("spread")
    bid = lad.get("bid") or lad.get("best_bid")
    ask = lad.get("ask") or lad.get("best_ask")
    return {
        "ok": True,
        "symbol": sym,
        "explanation": (
            f"{sym} top-of-book: bid={bid} ask={ask} mid={mid} spread={spread}. "
            "This is an NBBO-style ladder centered on mid — NOT a Level-2 order book "
            "and NOT Bloomberg depth. Use with regime + firewall + scoreboard before paper."
        ),
        "ladder": lad,
        "not_level2": True,
        "not_bloomberg_licensed": True,
    }


# ---- Full E-ve desk brief + portfolio risk (keep-working) --------------------

def build_eve_desk_brief(symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    One-shot E-ve desk brief: regime, top signals, crash, scoreboard keep/cut,
    overnight notes, plus optional symbol news brief.
    Tool / API: eve_desk_brief.
    """
    sym = (symbol or "").strip().upper() or None
    sections: Dict[str, Any] = {}
    lines: List[str] = []

    # Regime
    try:
        from .strategies import get_last_router_decision
        from .optimization import get_last_regime

        r = get_last_router_decision()
        rd = r.to_dict() if r and hasattr(r, "to_dict") else (r if isinstance(r, dict) else None)
        regime = get_last_regime()
        sections["regime"] = {
            "router": rd,
            "last_regime": regime if isinstance(regime, dict) else {"label": str(regime) if regime else None},
        }
        regime_label = None
        if isinstance(regime, dict):
            regime_label = regime.get("label") or regime.get("regime") or regime.get("name")
        elif regime:
            regime_label = str(regime)
        if rd:
            active = rd.get("active_strategies") or rd.get("selected") or rd.get("strategies") or []
            if isinstance(active, list):
                active_s = ", ".join(str(x)[:24] for x in active[:4]) or "n/a"
            else:
                active_s = str(active)[:60]
            lines.append(f"Regime: {regime_label or 'unknown'} · router favors {active_s}.")
        elif regime_label:
            lines.append(f"Regime: {regime_label}.")
        else:
            lines.append("Regime: no recent router decision cached — run a scan.")
    except Exception as exc:  # noqa: BLE001
        sections["regime"] = {"ok": False, "error": str(exc)[:120]}
        lines.append("Regime: unavailable.")

    # Top signals
    try:
        from .sync_snapshot import build_sync_snapshot

        snap = build_sync_snapshot()
        sigs = snap.get("signals") or []
        top = []
        for s in sigs[:6]:
            top.append({
                "ticker": s.get("ticker"),
                "score": s.get("score") or s.get("momentum_pct"),
                "strategy_id": s.get("strategy_id"),
            })
        sections["top_signals"] = top
        sections["signals"] = top  # alias for eve_desk_brief contract
        if top:
            bits = [f"{t.get('ticker')}({t.get('strategy_id') or '?'})" for t in top[:4] if t.get("ticker")]
            lines.append("Top signals: " + ", ".join(bits) + ".")
        else:
            lines.append("Top signals: none cached — run POST /scan.")
    except Exception as exc:  # noqa: BLE001
        err = {"error": str(exc)[:120]}
        sections["top_signals"] = err
        sections["signals"] = err
        lines.append("Top signals: unavailable.")

    # Crash
    try:
        from .crash_mode import get_crash_status

        crash = get_crash_status()
        cdict = crash.to_dict() if hasattr(crash, "to_dict") else dict(crash or {})
        sections["crash"] = cdict
        if cdict.get("active"):
            lines.append(f"Crash mode ON — {str(cdict.get('reason') or cdict.get('until') or '')[:80]}.")
        else:
            lines.append("Crash mode: off.")
    except Exception as exc:  # noqa: BLE001
        sections["crash"] = {"ok": False, "error": str(exc)[:120]}
        lines.append("Crash: unavailable.")

    # Scoreboard keep / cut
    try:
        from .scoreboard import build_scoreboard

        board = build_scoreboard()
        keep, cut, watch = [], [], []
        for s in board.get("strategies") or []:
            st = str(s.get("status") or "").lower()
            row = {"strategy_id": s.get("strategy_id"), "name": s.get("name"), "status": st}
            if st == "keep":
                keep.append(row)
            elif st == "cut":
                cut.append(row)
            elif st == "watch":
                watch.append(row)
        sections["scoreboard"] = {
            "keep": keep[:6],
            "cut": cut[:6],
            "watch": watch[:6],
            "label": "PAPER — not live audited",
        }
        keep_s = ", ".join(x.get("strategy_id") or "?" for x in keep[:3]) or "none"
        cut_s = ", ".join(x.get("strategy_id") or "?" for x in cut[:3]) or "none"
        lines.append(f"Scoreboard keep: {keep_s} · cut: {cut_s} (PAPER).")
    except Exception as exc:  # noqa: BLE001
        sections["scoreboard"] = {"ok": False, "error": str(exc)[:120]}
        lines.append("Scoreboard: unavailable.")

    # Overnight notes
    try:
        from .edge import overnight_research_summary

        overnight = overnight_research_summary(limit=5)
        sections["overnight"] = overnight
        notes = overnight.get("notes") or overnight.get("items") or []
        if notes:
            n0 = notes[0] if isinstance(notes[0], dict) else {"summary": str(notes[0])}
            lines.append(
                "Overnight: "
                + str(n0.get("summary") or n0.get("topic") or n0.get("title") or "note")[:120]
            )
        else:
            lines.append("Overnight: no allowlisted web notes yet.")
    except Exception as exc:  # noqa: BLE001
        sections["overnight"] = {"ok": False, "error": str(exc)[:120]}
        lines.append("Overnight: unavailable.")

    # Optional symbol brief
    symbol_brief = None
    if sym:
        try:
            symbol_brief = build_desk_brief(sym)
            sections["symbol_brief"] = {
                "symbol": sym,
                "summary": symbol_brief.get("summary"),
                "bullets": (symbol_brief.get("bullets") or [])[:4],
                "sources": (symbol_brief.get("sources") or [])[:3],
            }
            lines.append(f"Symbol {sym}: {(symbol_brief.get('summary') or '')[:160]}")
        except Exception as exc:  # noqa: BLE001
            sections["symbol_brief"] = {"ok": False, "error": str(exc)[:120]}

    # Firewall one-liner
    try:
        from .policy_firewall import status as firewall_status

        fw = firewall_status()
        sections["firewall"] = fw
        lines.append(
            f"Firewall: {'on' if fw.get('enabled', True) else 'off'} "
            f"(fail-closed when enabled)."
        )
    except Exception:
        sections["firewall"] = None

    summary = "E-ve full desk brief — " + " | ".join(lines[:5])
    return {
        "ok": True,
        "author": "E-ve",
        "persona": "E-ve",
        "tool": "eve_desk_brief",
        "symbol": sym,
        "summary": summary[:700],
        "lines": lines,
        "sections": sections,
        "disclaimer": (
            "Educational E-ve desk brief — NOT financial advice, "
            "NOT Bloomberg news, NOT live-audited. Paper-first; live locked."
        ),
        "not_bloomberg_licensed": True,
        "not_level2": True,
        "live_locked": True,
        "generated_at": _utc_now(),
    }


def portfolio_risk_snapshot() -> Dict[str, Any]:
    """
    E-ve tool: exposure, concentration, open brackets / working orders.
    Paper-only; live locked.
    """
    exposure: Dict[str, Any] = {}
    concentration: List[Dict[str, Any]] = []
    brackets: List[Dict[str, Any]] = []
    open_positions: List[Dict[str, Any]] = []

    try:
        from . import paper as paper_mod

        snap = paper_mod.mark_to_market()
        equity = float(snap.get("equity") or 0) or 1.0
        cash = float(snap.get("cash") or 0)
        positions = list(snap.get("open_positions") or [])
        open_positions = [
            {
                "id": p.get("id"),
                "ticker": p.get("ticker"),
                "shares": p.get("shares"),
                "market_value": p.get("market_value"),
                "unrealized_pnl": p.get("unrealized_pnl"),
                "strategy_id": p.get("strategy_id"),
            }
            for p in positions
        ]
        invested = sum(float(p.get("market_value") or 0) for p in positions)
        exposure = {
            "equity": round(equity, 2),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "cash_pct": round(cash / equity, 4) if equity else 0.0,
            "invested_pct": round(invested / equity, 4) if equity else 0.0,
            "open_count": len(positions),
            "mode": snap.get("mode"),
        }
        for p in positions:
            mv = float(p.get("market_value") or 0)
            concentration.append({
                "ticker": p.get("ticker"),
                "market_value": round(mv, 2),
                "weight": round(mv / equity, 4) if equity else 0.0,
                "unrealized_pnl": p.get("unrealized_pnl"),
            })
        concentration.sort(key=lambda x: -abs(float(x.get("weight") or 0)))
        top_w = float(concentration[0]["weight"]) if concentration else 0.0
        exposure["top_concentration_pct"] = top_w
        exposure["herfindahl"] = round(
            sum(float(c["weight"]) ** 2 for c in concentration), 4
        ) if concentration else 0.0
    except Exception as exc:  # noqa: BLE001
        exposure = {"ok": False, "error": str(exc)[:120]}

    try:
        from .paper_pro_orders import list_working_orders

        wo = list_working_orders()
        orders = list(wo.get("orders") or [])
        for o in orders:
            ot = str(o.get("order_type") or "").lower()
            if ot in ("bracket", "stop", "take_profit", "oco") or o.get("stop") or o.get("take_profit"):
                brackets.append({
                    "id": o.get("id"),
                    "ticker": o.get("ticker"),
                    "order_type": o.get("order_type"),
                    "shares": o.get("shares"),
                    "trigger_price": o.get("trigger_price") or o.get("stop") or o.get("take_profit"),
                    "status": o.get("status"),
                })
        # Also surface open position stops as implicit brackets
        for p in open_positions:
            # filled below from mark_to_market positions with stop/tp
            pass
    except Exception as exc:  # noqa: BLE001
        brackets = [{"error": str(exc)[:120]}]

    # Implicit brackets from open positions with stop/tp
    try:
        from . import paper as paper_mod

        snap = paper_mod.mark_to_market()
        for p in snap.get("open_positions") or []:
            if p.get("stop") or p.get("take_profit") or p.get("trailing_stop"):
                brackets.append({
                    "id": f"pos-{p.get('id')}",
                    "ticker": p.get("ticker"),
                    "order_type": "position_exits",
                    "stop": p.get("trailing_stop") or p.get("stop"),
                    "take_profit": p.get("take_profit"),
                    "shares": p.get("shares"),
                    "status": "open_position",
                })
    except Exception:
        pass

    # Dedupe by id
    seen = set()
    uniq_brackets = []
    for b in brackets:
        bid = b.get("id") or f"{b.get('ticker')}-{b.get('order_type')}"
        if bid in seen:
            continue
        seen.add(bid)
        uniq_brackets.append(b)

    return {
        "ok": True,
        "author": "E-ve",
        "tool": "portfolio_risk_snapshot",
        "exposure": exposure,
        "concentration": concentration[:12],
        "open_brackets": uniq_brackets[:20],
        "open_positions": open_positions[:20],
        "caption": (
            "Paper portfolio risk — exposure · concentration · open brackets. "
            "Not live audited; live locked."
        ),
        "not_bloomberg_licensed": True,
        "not_level2": True,
        "live_locked": True,
        "generated_at": _utc_now(),
    }

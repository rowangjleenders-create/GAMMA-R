"""
E-ve assistant for strategy & app Q&A (private single-user).

Offline rule/template brain + optional OpenAI tool-calling loop
(regime, signals, portfolio, news, FX, strategy router, memory).
Never logs secrets. Educational only — not financial advice.
Paper-first; refuses buy/sell advice.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _safe_to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def _redact(d: Any) -> Any:
    """Strip anything that looks like a secret before sending to optional OpenAI."""
    from .security import redact_obj

    return redact_obj(d, list_cap=30)


def _ctx() -> Dict[str, Any]:
    cfg_d: Dict[str, Any] = {}
    seed: Dict[str, Any] = {}
    signals: List[Any] = []
    portfolio: Dict[str, Any] = {}
    stats: Dict[str, Any] = {}
    regime = None
    session: Dict[str, Any] = {}
    watchlist: List[str] = []
    live_enabled = False
    hist = None
    fees: Dict[str, Any] = {}
    data_source: Dict[str, Any] = {}
    scan_status: Dict[str, Any] = {}

    try:
        from .config import SEED_DEFAULTS, get_runtime_config

        seed = dict(SEED_DEFAULTS)
        cfg = get_runtime_config()
        cfg_d = cfg.to_dict() if hasattr(cfg, "to_dict") else dict(cfg.__dict__)
        fees = {
            "fees_enabled": cfg_d.get("fees_enabled", True),
            "commission_mode": cfg_d.get("commission_mode", "per_share"),
            "commission_per_share": cfg_d.get("commission_per_share", 0.005),
            "commission_flat": cfg_d.get("commission_flat", 1.0),
            "slippage_pct": cfg_d.get("slippage_pct", 0.001),
        }
    except Exception:
        seed = {
            "lookback_days": 10,
            "volume_multiple": 1.5,
            "volume_avg_days": 20,
            "top_pct": 0.10,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.15,
        }

    try:
        from .scanner import get_cached_signals, get_scan_status

        raw = get_cached_signals() or []
        signals = [_safe_to_dict(s) for s in raw[:15]]
        scan_status = get_scan_status() or {}
    except Exception:
        signals = []
        scan_status = {}

    try:
        from . import paper as paper_mod

        portfolio = paper_mod.mark_to_market()
    except Exception:
        try:
            from . import paper as paper_mod

            portfolio = _safe_to_dict(paper_mod.load_portfolio()) or {}
        except Exception:
            portfolio = {}

    try:
        from .learning import learning_stats, load_historical_baseline

        stats = learning_stats() or {}
        hist = load_historical_baseline()
    except Exception:
        stats, hist = {}, None

    try:
        from .optimization import get_last_regime

        regime = _safe_to_dict(get_last_regime())
    except Exception:
        regime = None

    try:
        from .timezone_util import get_session

        session = _safe_to_dict(
            get_session(
                exchange=cfg_d.get("market_exchange", "NYSE"),
                user_tz=cfg_d.get("user_timezone", "America/Chicago"),
            )
        ) or {}
    except Exception:
        session = {}

    try:
        from .watchlist import load_watchlist

        watchlist = load_watchlist() or []
    except Exception:
        watchlist = []

    try:
        from .brokers import live_trading_enabled

        live_enabled = bool(live_trading_enabled())
    except Exception:
        live_enabled = False

    try:
        from .data_sources import get_data_source_status

        data_source = get_data_source_status() or {}
    except Exception:
        data_source = {}

    strategies = {}
    try:
        from .strategies import list_strategies, get_last_router_decision, explain_choice
        from .strategies.runner import get_last_cycle
        decision = get_last_router_decision()
        cycle = get_last_cycle() or {}
        strategies = {
            "list": list_strategies(),
            "enabled": cfg_d.get("strategy_enabled") or {},
            "router_mode": cfg_d.get("router_mode", "auto"),
            "router": decision.to_dict() if decision else cycle.get("router"),
            "last_fired": cycle.get("fired") or [],
            "explanations": {
                s["id"]: explain_choice(s["id"], decision) for s in list_strategies()
            },
        }
    except Exception:
        strategies = {}

    return {
        "config": cfg_d,
        "seed": seed,
        "signals": signals,
        "portfolio": portfolio,
        "learning": stats,
        "regime": regime,
        "session": session,
        "watchlist": watchlist,
        "live_enabled": live_enabled,
        "historical": hist,
        "fees": fees,
        "data_source": data_source,
        "scan_status": scan_status,
        "strategies": strategies,
    }


def _match(q: str, *needles: str) -> bool:
    return any(n in q for n in needles)


def _advice_refusal(q: str) -> Optional[str]:
    """Clear refusals for personal financial-advice asks."""
    if _match(
        q,
        "should i buy",
        "should i sell",
        "what should i buy",
        "what should i sell",
        "pick a stock",
        "recommend a stock",
        "best stock",
        "which stock",
        "which one should",
        "will it go up",
        "will it go down",
        "guaranteed",
        "make me money",
        "invest my",
        "is it safe to buy",
        "tell me what to trade",
        "buy now",
        "sell now",
        "go all in",
        "all-in",
        "put my money",
        "give me a tip",
        "hot tip",
        "what to buy today",
    ):
        return (
            "I can't give personal financial advice or tell you what to buy/sell. "
            "This bot is an educational paper-trading tool for you (private install). "
            "I can explain how a signal was scored, what fees do to P&L, or how paper vs live works — "
            "but decisions (and real-money risk) stay with you. Live trading stays OFF unless you unlock it. "
            "Try: Scan status · Learning summary · Explain SIP · How do fees work?"
        )
    return None


def _crash_badge() -> Dict[str, Any]:
    try:
        from .crash_mode import get_crash_status
        from .config import get_runtime_config
        st = get_crash_status(get_runtime_config())
        d = st.to_dict() if hasattr(st, "to_dict") else {}
        return {
            "active": bool(d.get("active") or d.get("on")),
            "label": d.get("label") or ("Crash ON" if d.get("active") else "Crash OFF"),
            "detail": d,
        }
    except Exception:
        return {"active": False, "label": "Crash n/a", "detail": {}}


def _scoreboard_snippet(limit: int = 4) -> Dict[str, Any]:
    try:
        from .scoreboard import build_scoreboard
        board = build_scoreboard()
        rows = []
        for s in (board.get("strategies") or [])[:limit]:
            if isinstance(s, dict):
                rows.append({
                    "strategy_id": s.get("strategy_id") or s.get("id"),
                    "status": s.get("status"),
                    "sample_size": s.get("sample_size") or s.get("trades"),
                })
        return {"label": board.get("label"), "strategies": rows, "sample_counts": board.get("sample_counts")}
    except Exception:
        return {}


def _outcome_blurb(strategy_id: Optional[str] = None, limit: int = 10) -> str:
    """Paper + external WR blurbs for memory-aware answers."""
    bits = []
    try:
        from .learning import load_journal
        rows = [e for e in load_journal() if isinstance(e, dict)]
        if strategy_id:
            sid = strategy_id.lower()
            rows = [
                e for e in rows
                if sid in str(
                    e.get("strategy_id")
                    or (e.get("context") or {}).get("strategy_id")
                    or (e.get("signal_params") or {}).get("strategy_id")
                    or ""
                ).lower()
            ]
        paper = [e for e in rows if (e.get("origin") or "paper") != "external"][-limit:]
        if paper:
            wins = sum(1 for e in paper if float(e.get("return_pct") or 0) > 0)
            tag = f" {strategy_id}" if strategy_id else ""
            bits.append(f"your last {len(paper)} paper{tag} trades WR={wins/len(paper)*100:.0f}%")
    except Exception:
        pass
    try:
        from .external_trades import external_performance_blurb
        bits.append(external_performance_blurb(limit=limit, strategy_id=strategy_id))
    except Exception:
        try:
            from .external_trades import learning_stats_by_origin
            ext = (learning_stats_by_origin().get("external") or {})
            n = int(ext.get("count") or 0)
            if n:
                bits.append(f"external trades n={n} WR={float(ext.get('win_rate') or 0)*100:.0f}%")
        except Exception:
            pass
    return " · ".join(b for b in bits if b and "no external" not in b)


def _build_proposals(message: str, strategy_plan: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Structured trade idea cards — never auto-execute; user must confirm paper."""
    q = _norm(message)
    if not any(k in q for k in ("propos", "idea", "paper trade", "candidate", "setup", "what looks")):
        return []
    if _advice_refusal(q):
        return []
    proposals: List[Dict[str, Any]] = []
    active = list((strategy_plan or {}).get("active") or [])[:4]
    try:
        from .scanner import get_cached_signals
        raw = get_cached_signals() or []
    except Exception:
        raw = []
    if not raw:
        try:
            from .watchlist import load_watchlist
            raw = [
                {
                    "ticker": t,
                    "strategy_id": (active[0] if active else "momentum"),
                    "momentum_pct": None,
                    "source": "watchlist",
                }
                for t in (load_watchlist() or [])[:5]
            ]
        except Exception:
            raw = []
    if not raw:
        # Illustrative placeholders only — clearly labeled; user must confirm paper.
        sid0 = active[0] if active else "momentum"
        raw = [
            {"ticker": "SPY", "strategy_id": sid0, "source": "illustrative"},
            {"ticker": "QQQ", "strategy_id": sid0, "source": "illustrative"},
            {"ticker": "IWM", "strategy_id": sid0, "source": "illustrative"},
        ]
    crash = _crash_badge()
    try:
        from .copilot_memory import compact_memory
        mem = compact_memory()
    except Exception:
        mem = {}
    prefer = set(mem.get("prefer_sectors") or [])
    avoid = set(mem.get("avoid_sectors") or [])
    for s in raw[:8]:
        d = _safe_to_dict(s) if not isinstance(s, dict) else s
        if not isinstance(d, dict):
            continue
        ticker = str(d.get("ticker") or "").upper()
        if not ticker:
            continue
        sector = str(d.get("sector") or "").lower()
        if avoid and any(a in sector for a in avoid):
            continue
        sid = d.get("strategy_id") or (active[0] if active else "momentum")
        if active and sid not in active and len(proposals) >= 1:
            # prefer router-active strategies
            if not prefer:
                continue
        size_hint = "half-size" if crash.get("active") else "standard paper size"
        risks = ["educational only — not advice", "session/firewall/crash gates still apply"]
        if crash.get("active"):
            risks.append("crash mode ON — aggressive entries may be paused")
        src_lbl = "Illustrative (no scan cache; not a live signal)" if d.get("source") == "illustrative" else "Cached scan"
        thesis = (
            f"{src_lbl} candidate; mom={d.get('momentum_pct')}; "
            f"forward={d.get('forward_probability')}; strategy={sid}."
        )
        if prefer and any(p in sector for p in prefer):
            thesis += f" Aligns with your preferred sectors ({', '.join(prefer)})."
        proposals.append({
            "symbol": ticker,
            "strategy_id": sid,
            "thesis": thesis[:240],
            "risks": risks,
            "size_hint": size_hint,
            "entry": d.get("entry"),
            "stop": d.get("stop"),
            "take_profit": d.get("take_profit"),
            "shares_hint": d.get("shares"),
            "requires_confirm": True,
            "paper_path": "firewall",
        })
        if len(proposals) >= 3:
            break
    return proposals



def _fmt_signal(s: Dict[str, Any]) -> str:
    t = s.get("ticker") or "?"
    sid = s.get("strategy_id")
    sid_s = f" [{sid}]" if sid else ""
    mom = s.get("momentum_pct")
    mom_s = f"{mom * 100:.1f}%" if isinstance(mom, (int, float)) else "?"
    fwd = s.get("forward_probability")
    fwd_s = f", forward {fwd * 100:.0f}%" if isinstance(fwd, (int, float)) else ""
    conf = s.get("forward_confidence")
    conf_s = f" (conf {conf * 100:.0f}%)" if isinstance(conf, (int, float)) else ""
    passed = s.get("forward_pass")
    pass_s = " pass" if passed else (" fail" if passed is False else "")
    votes = s.get("ensemble_votes") or {}
    vote_s = ""
    if isinstance(votes, dict) and votes:
        vote_s = " · votes " + ", ".join(f"{k}={float(v)*100:.0f}%" for k, v in list(votes.items())[:4])
    return f"{t}{sid_s} mom {mom_s}{fwd_s}{conf_s}{pass_s}{vote_s}"


def _extract_ticker(q: str, message: str) -> Optional[str]:
    """Pull a ticker from 'signal for AAPL', 'about TSLA', or a lone symbol."""
    patterns = (
        r"signal\s+(?:for|on|about)?\s*([a-z]{1,5}(?:-[a-z])?)\b",
        r"ticker\s+([a-z]{1,5}(?:-[a-z])?)\b",
        r"(?:about|explain)\s+([a-z]{1,5}(?:-[a-z])?)\b",
        r"\bfor\s+([a-z]{1,5}(?:-[a-z])?)\b",
    )
    skip = {
        "for", "on", "about", "the", "a", "an", "my", "to", "of",
        "sip", "fee", "fees", "scan", "help", "live", "risk", "news",
        "data", "paper", "mode", "stop", "seed",
    }
    for pat in patterns:
        m = re.search(pat, q)
        if not m:
            continue
        cand = m.group(1).upper().replace(".", "-")
        if cand.lower() in skip:
            continue
        return cand
    tokens = re.findall(r"\b([A-Za-z]{1,5}(?:[.-][A-Za-z])?)\b", message or "")
    stop = {
        "what", "how", "why", "when", "where", "who", "the", "my", "a", "an", "is",
        "are", "do", "does", "can", "you", "me", "i", "it", "to", "of", "in", "on",
        "for", "and", "or", "help", "fees", "fee", "paper", "live", "scan", "signal",
        "signals", "install", "iphone", "portfolio", "position", "positions", "stock",
        "stocks", "trade", "trading", "buy", "sell", "news", "sip", "api", "url",
        "seed", "risk", "stop", "mode", "open", "close", "show", "tell", "about",
        "explain", "work", "works", "with", "from", "this", "that", "your", "bot",
        "top", "cached", "estimate", "forward", "learning", "journal",
        "prefer", "strategy", "strategies", "router", "regime", "currency", "fx",
    }
    for t in tokens:
        up = t.upper().replace(".", "-")
        if up.lower() in stop:
            continue
        if re.fullmatch(r"[A-Z]{1,5}(?:-[A-Z])?", up):
            return up
    return None


def _find_signal(ctx: Dict[str, Any], ticker: str) -> Optional[Dict[str, Any]]:
    t = (ticker or "").upper()
    for s in ctx.get("signals") or []:
        if isinstance(s, dict) and str(s.get("ticker", "")).upper() == t:
            return s
    return None


def _answer_local(message: str, history: Optional[List[Dict[str, str]]] = None) -> Tuple[str, str]:
    """Return (reply, intent_tag)."""
    q = _norm(message)
    ctx = _ctx()
    cfg = ctx["config"]
    seed = ctx["seed"]

    refused = _advice_refusal(q)
    if refused:
        return refused, "advice_refusal"


    # --- v2 early intents (before ticker extraction) ---
    if _match(
        q,
        "scoreboard", "score board", "keep/watch/cut", "keep watch cut",
        "walk-forward", "walk forward", "which strategies keep", "strategy scoreboard",
    ) or ("keep" in q and "cut" in q):
        snip = _scoreboard_snippet(8)
        lines = [
            f"{s.get('strategy_id')}: {s.get('status')} (n={s.get('sample_size')})"
            for s in (snip.get("strategies") or [])
            if isinstance(s, dict)
        ]
        counts = snip.get("sample_counts") or {}
        return (
            f"Scoreboard ({snip.get('label') or 'rolling paper+external'}): "
            + ("; ".join(lines) if lines else "no scored strategies yet")
            + f". Samples paper={counts.get('paper')} external={counts.get('external')} "
              f"combined={counts.get('combined')}. "
            "Statuses keep / watch / cut. Cite when choosing sleeves. Not advice.",
            "scoreboard",
        )

    if _match(
        q,
        "strategy pack", "strategy packs", "list packs", "list strategy packs",
        "one-tap pack", "apply pack", "preview pack",
    ):
        try:
            from .strategy_packs import list_packs
            packs = list_packs() or []
            names = [f"{p.get('id')} — {p.get('name')}" for p in packs[:8] if isinstance(p, dict)]
        except Exception:
            names = []
        return (
            "Strategy packs (paper toggles; preview before apply): "
            + ("; ".join(names) if names else "none loaded")
            + ". Say “preview pack <id>” or explicitly confirm to apply. "
            "Apply never unlocks live. Not advice.",
            "strategy_packs",
        )

    if _match(q, "propos", "paper idea", "trade idea", "setup card", "candidate trade", "what looks"):
        # Prefer structured proposals; chat() attaches proposals[] for UI cards.
        blurb = _outcome_blurb(limit=10)
        crash = _crash_badge()
        snip = _scoreboard_snippet(3)
        keep = [s.get("strategy_id") for s in (snip.get("strategies") or []) if s.get("status") == "keep"]
        return (
            "I can outline educational PAPER idea cards (symbol, strategy_id, thesis, risks, size_hint). "
            "They are not advice and never auto-submit — confirm → Paper (firewall). "
            f"Crash: {crash.get('label')}. "
            f"Scoreboard keep sleeve: {keep or 'n/a'}. "
            f"Outcomes: {blurb or 'n/a'}. "
            "Ask “propose paper ideas” after a fresh scan for cards.",
            "proposals",
        )


    # Preference ack only (ingest happens once in chat()). Detect statements vs questions.
    pref_statement = bool(
        re.search(
            r"\b(prefer|avoid|no biotech|low risk|high risk|medium risk|risk averse|"
            r"interested in|focus on|please remember that|remember that|note that|note:)\b",
            q,
        )
    ) and not q.strip().startswith(("what ", "how ", "do you ", "can you ", "tell me "))
    if pref_statement and not _match(
        q, "help", "scan", "signal", "strateg", "router", "portfolio", "paper", "learn",
        "fee", "regime", "news", "currency", "fx", "watchlist", "session", "market",
        "memory", "remember about", "what do you remember",
    ):
        try:
            from .copilot_memory import memory_prompt_block
            block = memory_prompt_block()
        except Exception:
            block = ""
        return (
            f"Got it — preference noted. Memory now: {block}. "
            "I still will not tell you what to buy/sell; I will bias explanations toward your prefs.",
            "memory_update",
        )

    if _match(q, "help", "what can you", "topics", "commands", "getting started", "get started", "how do i start"):
        return (
            "Private E-ve topics: paper trading walkthrough, scan status, scan signals (or a ticker), "
            "strategies / router (why momentum vs mean-reversion), FX panel, EOD news, memory prefs, learning summary, fees/slippage, "
            "allowlisted web research (macro/earnings — not open browsing), SIP vs free data, seed defaults, "
            "forward-estimate & ensemble, paper vs live (live stays OFF by default), watchlist, market hours, "
            "Settings/API URL, exports, iPhone install. "
            "Try: Scan status · Research web · What did you learn about the Fed · Which strategies · FX panel · "
            "Learning summary · How do fees work? · How does paper trading work? · Market hours. "
            "I never give buy/sell advice. Disable web: copilot_web_enabled=0.",
            "help",
        )

    if _match(q, "disclaimer", "advice", "financial advice", "guarantee", "not advice"):
        return (
            "Educational paper-trading tool for your private use — not financial advice. "
            "Signals are statistical heuristics; past patterns do not guarantee future returns. "
            "Live brokerage stays locked until you set LIVE_TRADING_ENABLED and unlock in Settings.",
            "disclaimer",
        )

    if _match(q, "seed", "default", "day one", "day-one", "baseline param"):
        return (
            f"Day-one SEED (learning never starts from zeros): "
            f"lookback={seed.get('lookback_days', 10)} days, "
            f"volume ≥{seed.get('volume_multiple', 1.5)}× the {seed.get('volume_avg_days', 20)}-day avg, "
            f"top {float(seed.get('top_pct', 0.10)) * 100:.0f}% gainers, "
            f"stop {float(seed.get('stop_loss_pct', 0.05)) * 100:.0f}%, "
            f"take-profit {float(seed.get('take_profit_pct', 0.15)) * 100:.0f}%. "
            f"Runtime now: lookback={cfg.get('lookback_days')}, "
            f"vol×{cfg.get('volume_multiple')}, stop={cfg.get('stop_loss_pct')}, "
            f"TP={cfg.get('take_profit_pct')}. Reset Learning restores SEED.",
            "seed",
        )

    if _match(q, "forward", "ensemble", "probability", "p(continue)", "model vote"):
        n = len(ctx["signals"])
        samples = [_fmt_signal(s) for s in ctx["signals"][:3] if isinstance(s, dict)]
        thr = cfg.get("forward_estimate_threshold", 0.55)
        votes_need = cfg.get("ensemble_min_votes")
        return (
            f"Forward estimate = probability the momentum continues over the horizon "
            f"(default ~3 days), from models fit only on past bars (no look-ahead). "
            f"Ensemble blends logistic + gradient boosting + a rule scorer; "
            f"a pass means P(continue) cleared your threshold ({thr})"
            f"{f' and vote count ≥{votes_need}' if votes_need else ''}. "
            f"Confidence reflects model agreement — not a guarantee. "
            f"Cached signals: {n}."
            + ((" Examples: " + "; ".join(samples) + ".") if samples else "")
            + " Toggle use_forward_estimate / use_ensemble in Settings.",
            "forward",
        )

    if _match(q, "install", "expo go", "apk", "ipa", "iphone", "testflight", "sideload", "qr", "how to install"):
        return (
            "Install GAMMA-R on your iPhone (private / single-user — not public App Store):\n"
            "1) Fastest (dev): on a Mac/PC in mobile/, run `npx expo start`, open Expo Go, scan the QR. "
            "In the app: Settings → API server = your LAN IP (http://192.168.x.x:8000), not localhost.\n"
            "2) Standalone app: you enroll Apple Developer ($99/yr) yourself → "
            "`eas build --platform ios --profile preview` → TestFlight or cable install. "
            "Mic/STT needs this native build; text + TTS work in Expo Go.\n"
            "3) Settings → Install shows a QR for mobile/web/install.html "
            "(host with `npm run install-page` on port 3333). Full steps: mobile/IOS_INSTALL.md.",
            "install",
        )

    if _match(q, "voice", "speech", "microphone", "mic", "speak", "hands-free", "tts", "stt"):
        return (
            "E-ve voice: mic = on-device STT (needs your EAS/iOS build, not plain Expo Go); "
            "replies speak via device TTS. Hands-free keeps listening after each answer. "
            "Tap mic or a message to interrupt. Permissions: Microphone + Speech Recognition.",
            "voice",
        )

    if _match(
        q,
        "fee",
        "commission",
        "slippage",
        "transaction cost",
        "cost of trade",
        "how do fees",
        "explain fees",
        "fees explain",
        "what do fees",
    ):
        f = ctx["fees"] or {}
        p = ctx["portfolio"] or {}
        paid = p.get("total_fees_paid")
        mode = str(f.get("commission_mode", "per_share") or "per_share")
        per = float(f.get("commission_per_share", 0.005) or 0.005)
        flat = float(f.get("commission_flat", 1.0) or 1.0)
        slip = float(f.get("slippage_pct", 0.001) or 0.001)
        # Worked example: 100 shares @ $50
        ex_shares, ex_px = 100, 50.0
        notional = ex_shares * ex_px
        if mode == "flat":
            leg_comm = flat
        else:
            leg_comm = per * ex_shares
        leg_slip = notional * slip
        round_trip = 2 * (leg_comm + leg_slip)
        return (
            f"Fees are {'ON' if f.get('fees_enabled', True) else 'OFF'} so paper P&L stays realistic. "
            f"Settings: mode={mode}, per_share=${per}, flat=${flat}, "
            f"slippage={slip * 100:.2f}% of notional — applied on entry AND exit.\n"
            f"Example round-trip ({ex_shares} sh @ ${ex_px:.0f}): "
            f"~${leg_comm:.2f} commission + ~${leg_slip:.2f} slippage per leg "
            f"→ about ${round_trip:.2f} total drag before any price move.\n"
            f"Your portfolio fees paid so far: "
            f"{('$' + format(float(paid), '.2f')) if isinstance(paid, (int, float)) else 'n/a'}. "
            "Learning tab shows gross vs net return. Toggle fees_enabled in Settings anytime.",
            "fees",
        )

    if _match(
        q,
        "sip",
        "real-time",
        "realtime",
        "market data",
        "yfinance",
        "delayed",
        "explain sip",
        "what is sip",
        "alpaca data",
        "data source",
    ):
        ds = ctx["data_source"] or {}
        f = ctx.get("fees") or {}
        return (
            "Market data (owner explainer — not trading advice):\n"
            f"• Current live path: {ds.get('data_source', 'free')} "
            f"(SIP flag={ds.get('realtime_sip_enabled', False)}; "
            f"fallback_active={ds.get('fallback_active', False)}).\n"
            "• Free default = delayed yfinance. Fine for paper study; quotes can lag.\n"
            "• Optional SIP = Alpaca Algo Trader Plus (~$99/mo) for live scans only. "
            "Historical training + backtests always stay on free data — SIP never contaminates research.\n"
            "• Toggle: Settings → Real-time data (Alpaca SIP) or PUT /data-source. "
            "If the SIP socket dies, the bot auto-falls back to free and logs it.\n"
            f"Fees (separate from SIP): fees_enabled={f.get('fees_enabled', True)}, "
            f"mode={f.get('commission_mode', 'per_share')}, "
            f"slippage={float(f.get('slippage_pct', 0.001) or 0.001)*100:.2f}% — "
            "ask “how do fees work?” for a round-trip example. Live brokerage still stays OFF by default.",
            "data",
        )

    # Prior allowlisted web learning (offline store)
    if _match(
        q,
        "what did you learn",
        "what have you learned",
        "web learning",
        "learned about",
        "research notes",
        "from the web about",
    ) or ( "learn" in q and "about" in q and _match(q, "web", "macro", "fed", "earnings", "news") ):
        topic = ""
        m = re.search(
            r"(?:learn(?:ed|ing)?(?:\s+from\s+(?:the\s+)?web)?\s+about|about)\s+(.+)$",
            q,
        )
        if m:
            topic = m.group(1).strip(" ?.!")[:80]
        try:
            from .copilot_web import query_web_learning, web_enabled
            notes = query_web_learning(topic, limit=6)
            rows = notes.get("notes") or []
            if not rows:
                en = "on" if web_enabled() else "off (copilot_web_enabled=0)"
                return (
                    f"No stored web-learning notes yet"
                    + (f" matching «{topic}»" if topic else "")
                    + f". Web tools are {en}. "
                    "Ask “Research web: <topic>” or use learn_from_web to distill allowlisted sources "
                    "into data/web_learning.jsonl. Educational only — not advice.",
                    "web_learning",
                )
            bits = []
            srcs = []
            for r in rows:
                bits.append(
                    f"[{r.get('date')}] {r.get('topic')}: {(r.get('summary') or '')[:220]}"
                )
                for u in (r.get("urls") or [])[:2]:
                    srcs.append(u)
            return (
                "Prior allowlisted web learning"
                + (f" (filter «{topic}»)" if topic else "")
                + ": "
                + " || ".join(bits)
                + (f" Sources: {', '.join(srcs[:6])}." if srcs else ".")
                + " Educational context only — not financial advice.",
                "web_learning",
            )
        except Exception as e:
            return (f"Web learning store unavailable ({type(e).__name__}).", "web_learning")

    if _match(
        q,
        "research web",
        "search the web",
        "web search",
        "look up online",
        "fetch from web",
        "allowlisted web",
    ):
        topic = message.strip()
        for prefix in (
            "research web:", "research web", "search the web for", "search the web:",
            "web search:", "look up online:", "fetch from web:",
        ):
            if topic.lower().startswith(prefix):
                topic = topic[len(prefix):].strip()
                break
        topic = topic[:160] or "recent macro markets news"
        try:
            from .copilot_web import learn_from_web, web_enabled, web_status
            if not web_enabled():
                st = web_status()
                return (
                    "E-ve web is disabled. Enable with copilot_web_enabled=1 "
                    "(or COPILOT_WEB_ENABLED=1). Allowlist stays enforced when on. "
                    f"Current allowlist sample: {', '.join((st.get('allowlist') or [])[:6])}.",
                    "web_disabled",
                )
            result = learn_from_web(topic, max_sources=3)
            if not result.get("ok"):
                return (
                    f"Web research blocked/failed: {result.get('error') or result.get('reason')}. "
                    f"{result.get('hint') or ''} Educational only.",
                    "web_research",
                )
            srcs = result.get("sources") or []
            return (
                f"Allowlisted web notes on «{topic}»: {result.get('summary') or ''} "
                + (f"Sources: {', '.join(srcs[:6])}. " if srcs else "")
                + "Stored in data/web_learning.jsonl for later “what did you learn about …”. "
                "Educational context only — not buy/sell advice.",
                "web_research",
            )
        except Exception as e:
            return (f"Web research unavailable ({type(e).__name__}: {str(e)[:80]}).", "web_research")

    # Ticker-specific signal lookup before general scan intent
    ticker_ask = _extract_ticker(q, message)
    wants_ticker = bool(ticker_ask) and _match(
        q, "signal", "about", "ticker", "explain", "how did", "score", "signal for", "ticker "
    )
    if wants_ticker:
        hit = _find_signal(ctx, ticker_ask)
        if hit:
            return (
                f"{ticker_ask} (cached scan — educational, not advice): {_fmt_signal(hit)}. "
                f"Entry≈{hit.get('entry')}, stop≈{hit.get('stop')}, TP≈{hit.get('take_profit')}, "
                f"shares≈{hit.get('shares')}, source={hit.get('source', 'scan')}. "
                "Open Signal detail in the app for full ensemble/news fields, or Execute Paper Trade to simulate.",
                "signal_ticker",
            )
        return (
            f"No cached signal for {ticker_ask} right now. "
            f"Pull to refresh on Scan, or add {ticker_ask} to Watchlist so it is scored every run. "
            f"Universe is S&P 500 ∪ Nasdaq-100 (+ watchlist). Not a buy/sell call.",
            "signal_ticker",
        )

    # Dedicated scan-status before general scan/signals
    if _match(
        q,
        "scan status",
        "status of scan",
        "last scan",
        "when did i scan",
        "when was the last scan",
        "is the scan fresh",
        "cache status",
        "scan cache",
        "how fresh",
        "signals stale",
    ) or ( _match(q, "status") and _match(q, "scan", "signal", "cache") ):
        st = ctx.get("scan_status") or {}
        sess = ctx.get("session") or {}
        ds = ctx.get("data_source") or {}
        age = st.get("cache_age_sec")
        if age is None:
            age_s = "never scanned this process"
        elif age < 60:
            age_s = f"{age:.0f}s ago"
        elif age < 3600:
            age_s = f"{age/60:.1f}m ago"
        else:
            age_s = f"{age/3600:.1f}h ago"
        fresh = st.get("cache_fresh")
        fresh_s = "fresh (within TTL)" if fresh else ("stale / expired TTL" if st.get("has_cache") else "empty")
        tops = st.get("top_tickers") or []
        top_s = (", ".join(tops) if tops else "none")
        sess_s = sess.get("session") or sess.get("label") or sess.get("dual_label") or "n/a"
        return (
            f"Scan status: {st.get('cached_count', 0)} cached "
            f"({st.get('market_signals', 0)} market + {st.get('watchlist_signals', 0)} watchlist). "
            f"Cache {fresh_s}; last fill {age_s}"
            f"{f' (as_of {st.get("as_of")})' if st.get('as_of') else ''}. "
            f"TTL≈{st.get('cache_ttl_sec', 60):.0f}s — pull-to-refresh on Scan forces a new run. "
            f"Session={sess_s}. Data={ds.get('data_source', 'free')} "
            f"(SIP={ds.get('realtime_sip_enabled', False)}"
            f"{', fallback active' if ds.get('fallback_active') else ''}). "
            f"Top tickers: {top_s}. Educational cache only — not advice.",
            "scan_status",
        )

    if _match(q, "scan", "signal", "momentum", "how does scan", "universe", "my signals", "top signals"):
        n = len(ctx["signals"])
        lines = [_fmt_signal(s) for s in ctx["signals"][:5] if isinstance(s, dict)]
        top = ("\nTop cached: " + " | ".join(lines) + ".") if lines else ""
        st = ctx.get("scan_status") or {}
        age = st.get("cache_age_sec")
        age_bit = ""
        if age is not None:
            age_bit = f" Cache age≈{age:.0f}s ({'fresh' if st.get('cache_fresh') else 'stale'})."
        elif not st.get("has_cache"):
            age_bit = " No scan yet this process — pull to refresh on Scan."
        return (
            f"Scan ranks momentum + volume over S&P 500 ∪ Nasdaq-100 "
            f"(lookback {cfg.get('lookback_days')}d, vol ≥{cfg.get('volume_multiple')}× "
            f"{cfg.get('volume_avg_days')}d avg), then optional ADX/MA/regime/ensemble/news gates. "
            f"{n} cached signal(s).{age_bit}{top}\n"
            "Ask “scan status” for cache/session/data-source detail, or “signal for TICKER” for one name. "
            "These are study candidates for paper trading — not recommendations.",
            "scan",
        )

    if _match(
        q,
        "export",
        "/owner/export",
        "/owner/import",
        "import watchlist",
        "import config",
        "download journal",
        "download paper",
        "backup journal",
        "how do i export",
        "how to export",
    ):
        return (
            "Owner export/import (private LAN API — educational data only):\n"
            "• GET /owner/export/watchlist | paper | journal | config | learning_history\n"
            "• PUT /owner/import/watchlist | config (JSON body)\n"
            "Files live under data/. Back up the whole data/ folder anytime. "
            "Ask “watchlist” for symbols, or “how does paper trading work?” for the paper loop.",
            "export",
        )

    if _match(
        q,
        "paper",
        "portfolio",
        "position",
        "equity",
        "p&l",
        "pnl",
        "cash",
        "buying power",
        "how does paper",
        "paper trade",
        "paper trading",
        "execute paper",
        "open a trade",
        "close a trade",
        "how to trade",
        "my money",
        "account value",
    ):
        p = ctx["portfolio"] or {}
        mode = p.get("mode", "paper")
        equity = p.get("equity", p.get("cash"))
        cash = p.get("cash")
        positions = p.get("open_positions") or p.get("positions") or []
        npos = len(positions) if isinstance(positions, list) else 0
        names = []
        if isinstance(positions, list):
            for pos in positions[:6]:
                if isinstance(pos, dict) and pos.get("ticker"):
                    names.append(str(pos.get("ticker")))
        names_s = (", ".join(names) + ("…" if npos > 6 else "")) if names else "none"
        fees_paid = p.get("total_fees_paid")
        return (
            f"Paper trading is the safe default (mode={mode}; live brokerage stays off unless you unlock it).\n"
            f"Snapshot: cash≈{cash}, equity≈{equity}, open={npos} ({names_s}), "
            f"realized(net)={p.get('realized_pnl')}, unrealized={p.get('unrealized_pnl')}, "
            f"fees paid={fees_paid}.\n"
            "How to use it: (1) Scan → open a signal → Execute Paper Trade (one tap, no nag). "
            "(2) Paper tab → Close when done. (3) Learning uses closed trades to nudge params from SEED. "
            "Fees/slippage apply on entry & exit for realism. "
            "Export: GET /owner/export/paper or /owner/export/journal. "
            "I will not tell you what to buy — only how the paper loop works.",
            "portfolio",
        )

    if _match(q, "live", "alpaca", "broker", "real money", "kill switch", "unlock"):
        on = ctx["live_enabled"]
        return (
            f"Live brokerage is {'ENABLED on server' if on else 'DISABLED (safe default)'}. "
            "Your Settings live unlock only exposes the UI; server still needs LIVE_TRADING_ENABLED=1. "
            "Keys stay in SecureStore/Keychain — never logged. "
            "Kill switch: Settings → KILL SWITCH / POST /broker/kill. "
            "Keep a confirm for live/kill — paper actions stay one-tap.",
            "live",
        )

    if _match(
        q,
        "learn",
        "learning",
        "journal",
        "nudge",
        "historical train",
        "learning summary",
        "how am i doing",
        "how am i perform",
        "performance summary",
        "trade stats",
        "am i learning",
        "what did i learn",
        "external trade",
        "imported trade",
        "outside trade",
        "brokerage import",
        "import trade",
    ):
        st = ctx["learning"] or {}
        jr = st.get("journal_count", 0)
        wr = st.get("win_rate")
        wr_s = f"{wr * 100:.1f}%" if isinstance(wr, (int, float)) else "?"
        wins = st.get("wins")
        unlearned = st.get("unlearned")
        hist = ctx["historical"]
        hist_meta = (st.get("historical_baseline") or {}) if isinstance(st, dict) else {}
        if hist_meta.get("present") or hist:
            years = hist_meta.get("years") or (hist.get("years") if isinstance(hist, dict) else None)
            hist_s = f"present{f' ({years}y)' if years else ''}"
        else:
            hist_s = "not trained yet"
        fee_imp = st.get("fee_impact") or {}
        gross = st.get("gross_return_pct", fee_imp.get("gross_return_pct"))
        net = st.get("net_return_pct", fee_imp.get("net_return_pct"))
        fees_paid = st.get("total_fees_paid", fee_imp.get("total_fees_paid"))
        def _pct(x):
            return f"{float(x)*100:.2f}%" if isinstance(x, (int, float)) else "—"
        evolved = st.get("evolved_vs_baseline") or {}
        changed = [k for k, v in evolved.items() if isinstance(v, dict) and v.get("changed_from_seed")]
        changed_s = (", ".join(changed[:6]) + ("…" if len(changed) > 6 else "")) if changed else "none yet (still on SEED)"
        by_o = st.get("by_origin") or {}
        try:
            from .external_trades import learning_stats_by_origin
            by_o = learning_stats_by_origin() or by_o
        except Exception:
            pass
        paper_n = (by_o.get("paper") or {}).get("count")
        ext_n = (by_o.get("external") or {}).get("count")
        comb_wr = (by_o.get("combined") or {}).get("win_rate")
        comb_s = f"{comb_wr * 100:.1f}%" if isinstance(comb_wr, (int, float)) else wr_s
        origin_line = (
            f"• Origins: paper={paper_n if paper_n is not None else '?'}, "
            f"external/imported={ext_n if ext_n is not None else 0}, "
            f"combined WR={comb_s}. Paper portfolio equity excludes external P&L.\n"
        )
        return (
            "Learning summary (paper + optional external imports — educational, not advice):\n"
            f"• Closed trades={jr}"
            f"{f' (wins={wins})' if wins is not None else ''}, win rate={wr_s}, "
            f"unlearned={unlearned if unlearned is not None else '?'}.\n"
            + origin_line +
            f"• Gross→net return (paper fees): {_pct(gross)} → {_pct(net)}; "
            f"fees paid={('$' + format(float(fees_paid), '.2f')) if isinstance(fees_paid, (int, float)) else 'n/a'}.\n"
            f"• Params changed from day-one SEED: {changed_s}.\n"
            f"• Historical baseline: {hist_s}.\n"
            "Loop: close paper trades or Learning → Import outside trades → Run learning. "
            "Imports never auto-live-trade. Reset restores SEED, not zeros.",
            "learning",
        )

    if _match(q, "eod digest", "news digest", "eod news", "end of day news", "end-of-day news"):
        try:
            from .news import build_eod_digest
            dig = build_eod_digest() or {}
            heads = dig.get("top_headlines") or dig.get("headlines") or []
            titles = []
            for h in heads[:4]:
                if isinstance(h, dict):
                    titles.append(str(h.get("title") or h.get("headline") or "")[:80])
                else:
                    titles.append(str(h)[:80])
            tilt = dig.get("tilt") or dig.get("summary") or dig.get("news_tilt") or "n/a"
            return (
                f"EOD news digest (educational): tilt={tilt}. "
                + (("Headlines: " + " · ".join(t for t in titles if t) + ". ") if titles else "No headlines cached. ")
                + "Ask a ticker for get_news_ticker-style detail. Not advice.",
                "news_eod",
            )
        except Exception:
            return (
                "EOD digest unavailable right now. News still blends via RSS when enabled "
                f"(blend={cfg.get('news_blend_mode', '70_30')}).",
                "news_eod",
            )

    if _match(q, "currency", "fx panel", "forex", "eurusd", "gbpusd", "fx quote", "dollar index"):
        try:
            from .currency import get_currency_quotes
            panel = get_currency_quotes() or {}
            quotes = panel.get("quotes") or panel.get("pairs") or []
            bits = []
            if isinstance(quotes, list):
                for row in quotes[:6]:
                    if not isinstance(row, dict):
                        continue
                    pair = row.get("pair") or row.get("symbol") or "?"
                    px = row.get("price") or row.get("last")
                    ch = row.get("change_pct")
                    ch_s = f" ({ch:+.2f}%)" if isinstance(ch, (int, float)) else ""
                    bits.append(f"{pair}={px}{ch_s}" if px is not None else str(pair))
            note = panel.get("session_note") or panel.get("note") or ""
            return (
                f"FX panel (informational; use_currency_panel={cfg.get('use_currency_panel', True)}): "
                + (", ".join(bits) if bits else "no quotes right now")
                + (f". {note}" if note else "")
                + ". Not wired to live orders. Not advice.",
                "currency",
            )
        except Exception:
            return (
                f"Currency panel toggle use_currency_panel={cfg.get('use_currency_panel', True)}. "
                "Quotes unavailable offline/network. FX mean-reversion strategy may no-op when thin.",
                "currency",
            )

    if _match(q, "memory", "what do you remember", "my preference", "my preferences", "what did i say", "remember about"):
        try:
            from .copilot_memory import memory_prompt_block
            return (
                f"E-ve memory: {memory_prompt_block()}. "
                "Say “prefer tech”, “no biotech”, “low risk”, or “remember that …” to update. "
                "Stored under data/copilot_memory.json (no secrets).",
                "memory",
            )
        except Exception:
            return ("Memory module unavailable.", "memory")

    if _match(q, "news", "sentiment", "vader", "finbert"):
        tilt = ""
        try:
            from .news import build_eod_digest
            dig = build_eod_digest() or {}
            t = dig.get("tilt") or dig.get("news_tilt")
            if t is not None:
                tilt = f" Latest EOD tilt≈{t}."
        except Exception:
            pass
        return (
            f"News: free RSS (+ optional API keys). Blend={cfg.get('news_blend_mode', '70_30')}, "
            f"news_weight={cfg.get('news_weight')}.{tilt} "
            "Positive spikes can boost priority; sharp negatives can warn/block new entries. "
            "Ask “eod digest” for headlines.",
            "news",
        )

    if _match(
        q,
        "timezone",
        "session",
        "market hours",
        "after hours",
        "rth",
        "market open",
        "market closed",
        "is the market",
        "is market",
        "when does the market",
        "when is the market",
        "trading hours",
    ):
        sess = ctx["session"] or {}
        open_s = "OPEN" if sess.get("is_open") else "CLOSED"
        act_s = "entries allowed" if sess.get("allow_act") else "entries paused / after-hours policy"
        return (
            f"Market session: {sess.get('session', 'n/a')} ({open_s}; {act_s}). "
            f"Clock {sess.get('dual_label') or 'n/a'}. "
            f"User TZ={cfg.get('user_timezone', sess.get('user_tz') or 'America/Chicago')}, "
            f"exchange={cfg.get('market_exchange', sess.get('exchange') or 'NYSE')}. "
            "Scans still work when closed; paper fills use last quotes.",
            "session",
        )

    if _match(
        q,
        "strateg",
        "router",
        "mean reversion",
        "mean-reversion",
        "breakout",
        "relative strength",
        "sector rotation",
        "pairs",
        "pead",
        "earnings drift",
        "vol-target",
        "vol target",
        "fx mean",
        "which strateg",
        "why momentum",
        "why breakout",
        "why mean",
        "multi-strateg",
        "multi strateg",
    ):
        st = ctx.get("strategies") or {}
        names = []
        for s in st.get("list") or []:
            if isinstance(s, dict):
                on = (st.get("enabled") or {}).get(s.get("id"), True)
                names.append(f"{s.get('id')}({'on' if on else 'off'})")
        fired = st.get("last_fired") or []
        router = st.get("router") or {}
        active = router.get("active") or fired
        # If user named a specific strategy, explain it
        explanations = st.get("explanations") or {}
        picked = None
        for sid in explanations:
            if sid.replace("_", " ") in q or sid in q.replace("-", "_"):
                picked = sid
                break
        if "momentum" in q and "why" in q:
            picked = picked or "momentum"
        explain = explanations.get(picked) if picked else None
        if not explain and active:
            explain = explanations.get(active[0]) if active else None
        plugin_s = ", ".join(names) if names else (
            "momentum, mean_reversion, breakout, relative_strength, "
            "earnings_drift, pairs, fx_mean_reversion, vol_target"
        )
        lines = [
            "GAMMA-R multi-strategy suite (paper-first; momentum is one of several):",
            f"• Plugins: {plugin_s}.",
            f"• Router mode={st.get('router_mode') or cfg.get('router_mode', 'auto')}; "
            f"regime active subset={active}.",
            f"• Last cycle fired: {fired or 'n/a'}.",
        ]
        if explain:
            lines.append(f"• Why chosen: {explain}")
        lines.append(
            "Priors (tunable): bull→momentum+breakout; sideways/low-vol→mean reversion+pairs; "
            "high-vol→vol-target shrink + quality RS; FX MR when FX panel on; PEAD when earnings events exist. "
            "Toggle in Settings / strategy_enabled. Not advice."
        )
        return ("\n".join(lines), "strategies")

    if _match(q, "regime", "bear", "bull", "vix", "volatility"):
        return (
            f"Last regime: {ctx['regime']}. "
            f"use_regime_filter={cfg.get('use_regime_filter')} — can shrink/pause size in bear/high-vol. "
            "The strategy router also uses regime to pick momentum/breakout vs mean-reversion/pairs.",
            "regime",
        )

    if _match(q, "watchlist", "watch list", "my watchlist", "add to watch"):
        wl = ctx["watchlist"] or []
        return (
            f"Watchlist ({len(wl)}): {', '.join(wl) if wl else '(empty)'}. "
            "Scored even outside top 10%. "
            "In the app: Watch tab to add/remove. Owner file API: GET/PUT /owner/export|import/watchlist.",
            "watchlist",
        )

    if _match(
        q,
        "settings",
        "configure",
        "configuration",
        "preferences",
        "app settings",
        "bot settings",
        "change settings",
    ):
        return (
            "Settings tab (owner app): API server URL, risk/seed params, fees & slippage, "
            "forward-estimate / ensemble toggles, SIP real-time data, paper vs live mode label, "
            "and Install QR. Save writes PUT /config. "
            "Live brokerage stays OFF unless LIVE_TRADING_ENABLED=1 on the server + unlock. "
            "Ask “API URL” for connection tips, or “how do fees work?” for cost knobs.",
            "settings",
        )

    if _match(q, "api", "server", "localhost", "base url", "connect", "owner secret", "api url"):
        return (
            "Settings → API server: use your LAN IP (http://192.168.x.x:8000) on a physical iPhone, "
            "or localhost on Simulator. Private API is open by default (no login). "
            "Optional: set OWNER_SHARED_SECRET on the server and X-Owner-Secret on clients if exposing beyond LAN. "
            "GET /health and GET /owner/status for a quick check.",
            "api",
        )

    if _match(q, "stop", "take profit", "position size", "risk per", "risk settings", "risk params") or (
        _match(q, "risk") and not _match(q, "prefer", "low risk", "high risk", "medium risk", "risk averse", "risk comfort")
    ):
        return (
            f"Risk now: stop={cfg.get('stop_loss_pct')}, TP={cfg.get('take_profit_pct')}, "
            f"risk_per_trade={cfg.get('risk_per_trade')}, max_position={cfg.get('max_position_pct')}. "
            f"Trailing={cfg.get('use_trailing_stop')}, partials={cfg.get('use_partial_profits')}. "
            "Paper sizing uses these; live still needs explicit enable.",
            "risk",
        )

    if _match(q, "owner", "private", "single user", "data dir", "backup"):
        return (
            "This is your private single-user install — no multi-tenant login. "
            "Owner conveniences: open LAN API, /owner/export|import for watchlist/config/journal/paper, "
            "paper actions without nagging confirms, live/kill still confirmed. "
            "Back up the data/ folder anytime.",
            "owner",
        )


    if _match(q, "crash mode", "crash-mode", "is crash", "crash on", "crash off", "shock mode"):
        badge = _crash_badge()
        d = badge.get("detail") or {}
        return (
            f"{badge.get('label')}. "
            f"enabled={d.get('enabled')}, active={d.get('active')}, "
            f"size_mult={d.get('size_mult')}, pause_aggressive={d.get('pause_aggressive_entries')}, "
            f"reason={d.get('reason') or 'n/a'}. "
            "When ON, momentum/breakout new entries are cut or paused; exits always allowed. "
            "Not advice.",
            "crash_mode",
        )

    if _match(q, "scoreboard", "score board", "keep watch cut", "walk-forward", "walk forward", "which strategies keep"):
        snip = _scoreboard_snippet(6)
        lines = []
        for s in snip.get("strategies") or []:
            lines.append(f"{s.get('strategy_id')}: {s.get('status')} (n={s.get('sample_size')})")
        body = "; ".join(lines) if lines else "no scored strategies yet"
        counts = snip.get("sample_counts") or {}
        return (
            f"Scoreboard ({snip.get('label') or 'rolling paper+external'}): {body}. "
            f"Samples paper={counts.get('paper')} external={counts.get('external')} combined={counts.get('combined')}. "
            "Statuses: keep / watch / cut. Cite these when choosing sleeves. Not advice.",
            "scoreboard",
        )

    if _match(q, "strategy pack", "strategy packs", "list packs", "apply pack", "preview pack", "one-tap pack"):
        try:
            from .strategy_packs import list_packs
            packs = list_packs() or []
            names = [f"{p.get('id')} — {p.get('name')}" for p in packs[:8] if isinstance(p, dict)]
        except Exception:
            names = []
        return (
            "Strategy packs (paper toggles; preview before apply): "
            + ("; ".join(names) if names else "none loaded")
            + ". Say “preview pack classic_momentum_12_1” or confirm explicitly to apply. "
            "Apply never unlocks live trading. Not advice.",
            "strategy_packs",
        )


    if _match(q, "our edge", "why gamma", "why gamma-r", "differentiation", "edge report", "edge status", "beat retail"):
        try:
            from .edge import build_edge_status_logged, why_gamma_r_card
            card = why_gamma_r_card()
            rep = build_edge_status_logged()
            bullets = "; ".join(
                f"{b.get('title')}" for b in (card.get("bullets") or [])[:6]
            )
            deg = rep.get("degraded_count")
            win_col = "; ".join((rep.get("vs_signal_bots") or {}).get("win_column") or [])[:320]
            return (
                f"{card.get('badge') or 'BEAT RETAIL'}: {card.get('tagline')} "
                f"Core edges: {bullets}. "
                f"Active now={', '.join(rep.get('active_advantage_ids') or [])}. "
                f"Degraded={deg}. Win column: {win_col}. "
                f"{card.get('vs_bots_one_liner') or ''} "
                "Not L2; not live-audited. Not advice.",
                "edge",
            )
        except Exception as e:
            return (f"Edge report unavailable ({type(e).__name__}).", "edge")

    if _match(q, "vs other bots", "versus other", "compare to trade ideas", "competitive gaps", "how do we compare", "better than", "beat other bots"):
        try:
            from .edge import competitive_gaps
            g = competitive_gaps()
            closed = ", ".join(
                (c.get("title") or c.get("id") or "") for c in (g.get("closed") or [])[:8]
            )
            win = "; ".join((g.get("vs_signal_bots") or {}).get("we_win") or [])[:420]
            lose = "; ".join((g.get("vs_signal_bots") or {}).get("they_still_win") or [])[:280]
            hard = ", ".join(
                (h.get("title") or "") for h in (g.get("still_open_hard") or [])[:4]
            )
            return (
                f"Closed gaps ({g.get('closed_count')}): {closed}. "
                f"We win on: {win}. They still win on: {lose}. "
                f"Hard-open (intentional): {hard}. "
                "Honest — no fake L2 or live-audited returns. Not advice.",
                "competitive_gaps",
            )
        except Exception as e:
            return (f"Competitive gaps unavailable ({type(e).__name__}).", "competitive_gaps")

    if _match(q, "what to improve", "improve next", "next improvement", "roadmap", "propose next"):
        try:
            from .edge import propose_next_improvements
            sug = propose_next_improvements(limit=5).get("suggestions") or []
            lines = [f"{s.get('rank')}. {s.get('title')} — {s.get('why')}" for s in sug]
            return (
                "Next improvements (ranked): " + (" | ".join(lines) if lines else "none")
                + ". Prefer process/intelligence over fake L2. Not advice.",
                "improvements",
            )
        except Exception as e:
            return (f"Improvements unavailable ({type(e).__name__}).", "improvements")

    if _match(q, "overnight research", "overnight notes", "what did we learn overnight", "web overnight"):
        try:
            from .edge import overnight_research_summary
            o = overnight_research_summary(limit=6)
            return (
                (o.get("summary") or "No overnight notes.")
                + " Allowlisted web only. Not advice.",
                "overnight_research",
            )
        except Exception as e:
            return (f"Overnight research unavailable ({type(e).__name__}).", "overnight_research")


    if _match(q, "self critique", "self-critique", "daily critique", "daily self", "critique today", "how are we doing vs bots"):
        try:
            from .edge import run_daily_self_critique
            c = run_daily_self_critique(persist=True)
            score = c.get("score") or {}
            strengths = ", ".join(c.get("strengths") or [])[:280]
            weak = "; ".join(c.get("weaknesses") or [])[:320]
            acts = "; ".join(c.get("next_actions") or [])[:320]
            return (
                f"Daily self-critique: {c.get('summary')} "
                f"Strengths: {strengths}. Weaknesses: {weak}. "
                f"Next: {acts}. "
                f"Feed={score.get('feed_badge')} overnight_notes={score.get('overnight_notes')}. "
                "Not L2; not live-audited. Not advice.",
                "self_critique",
            )
        except Exception as e:
            return (f"Self-critique unavailable ({type(e).__name__}).", "self_critique")

    if _match(q, "feed health", "nbbo", "feed badge", "top of book", "top-of-book"):
        try:
            from .edge import feed_health
            f = feed_health()
            return (
                f"Feed badge={f.get('feed_badge')} (allowed Delayed|IEX|SIP|NBBO). "
                f"keys={f.get('keys_present')} degraded={f.get('degraded')} "
                f"health={f.get('connection_health')}. Top-of-book only — not Level-2 depth. Not advice.",
                "feed_health",
            )
        except Exception as e:
            return (f"Feed health unavailable ({type(e).__name__}).", "feed_health")

    if _match(q, "pro chart", "pro charts", "candle chart", "ohlcv", "show bars"):
        try:
            from .bars import get_bars
            # Default SPY demo if no ticker parsed simply
            sym = "SPY"
            for tok in q.replace(",", " ").split():
                t = tok.strip().upper().replace(".", "-")
                if t.isalpha() and 1 < len(t) <= 5 and t not in ("PRO", "CHART", "CHARTS", "CANDLE", "OHLCV", "SHOW", "BARS", "THE"):
                    sym = t
                    break
            b = get_bars(sym, interval="1d", limit=30)
            return (
                f"Pro chart {sym}: {b.get('count')} bars interval={b.get('interval')} "
                f"vwap={b.get('vwap_available')} source={b.get('source')}. "
                f"{b.get('label')}. Not L2. Not advice.",
                "pro_chart",
            )
        except Exception as e:
            return (f"Pro chart unavailable ({type(e).__name__}).", "pro_chart")

    if _match(q, "tape lite", "time and sales", "time & sales", "show tape", "tape"):
        try:
            from .tape import get_tape
            sym = "SPY"
            for tok in q.replace(",", " ").split():
                t = tok.strip().upper().replace(".", "-")
                if t.isalpha() and 1 < len(t) <= 5 and t not in ("TAPE", "LITE", "TIME", "AND", "SALES", "SHOW", "THE"):
                    sym = t
                    break
            tp = get_tape(sym, limit=10)
            return (
                f"Tape lite {sym}: {tp.get('count')} prints source={tp.get('source')}. "
                f"{tp.get('label')}. {tp.get('note') or ''} Not advice.",
                "tape",
            )
        except Exception as e:
            return (f"Tape unavailable ({type(e).__name__}).", "tape")

    if _match(q, "custom scan", "scanner builder", "pro scan", "scan filters"):
        try:
            from .scan_custom import run_custom_scan
            r = run_custom_scan({"min_volume_ratio": 1.2, "limit": 10}, refresh=False)
            tickers = ", ".join(s.get("ticker") for s in (r.get("signals") or [])[:8] if s.get("ticker"))
            return (
                f"Custom scan matched {r.get('count')}/{r.get('universe_cached')}: {tickers or 'none'}. "
                f"{r.get('label')}. Not advice.",
                "custom_scan",
            )
        except Exception as e:
            return (f"Custom scan unavailable ({type(e).__name__}).", "custom_scan")

    if _match(q, "economic calendar", "econ calendar", "calendar rail", "fomc", "cpi calendar"):
        try:
            from .calendar_econ import get_economic_calendar
            cal = get_economic_calendar(days=14, limit=8)
            ev = "; ".join(
                f"{e.get('when','')[:10]} {e.get('title')}" for e in (cal.get("events") or [])[:6]
            )
            return (
                f"Economic calendar ({cal.get('count')}): {ev}. {cal.get('note')} Not advice.",
                "econ_calendar",
            )
        except Exception as e:
            return (f"Calendar unavailable ({type(e).__name__}).", "econ_calendar")


    if _match(q, "firewall status", "policy firewall", "firewall"):
        try:
            from .policy_firewall import status as fw_status
            fw = fw_status() or {}
        except Exception:
            fw = {}
        return (
            f"Policy firewall: enabled={fw.get('enabled')}, live={fw.get('live_trading_enabled')}, "
            f"day_orders={fw.get('day_orders')}/{fw.get('max_day')}, "
            f"cycle={fw.get('cycle_orders')}/{fw.get('max_cycle')}, "
            f"max_pct_equity={fw.get('max_pct_equity')}. "
            "Every paper_this path must pass the firewall. Not advice.",
            "firewall",
        )

    if _match(q, "external trade", "external trades", "imported trade", "broker import", "outside the app", "my external"):
        blurb = _outcome_blurb(limit=10)
        try:
            from .external_trades import load_external_trades, learning_stats_by_origin
            rows = load_external_trades(limit=5)
            stats = learning_stats_by_origin().get("external") or {}
            tickers = [str(r.get("ticker")) for r in rows if isinstance(r, dict)][:5]
        except Exception:
            stats, tickers = {}, []
        return (
            f"External (brokerage) imports: n={stats.get('count', 0)}, "
            f"WR={float(stats.get('win_rate') or 0)*100:.0f}%. "
            f"Recent: {', '.join(tickers) if tickers else 'none'}. "
            f"Outcomes: {blurb or 'n/a'}. "
            "Import via Learning → Import trades (CSV/JSON/Alpaca). "
            "Counted in learning/scoreboard; paper cash unchanged; never auto-live. Not advice.",
            "external_trades",
        )

    if _match(q, "paper report", "performance report", "equity curve"):
        try:
            from .scoreboard import build_paper_report
            rep = build_paper_report() or {}
            sm = rep.get("summary") or {}
        except Exception:
            rep, sm = {}, {}
        return (
            f"Paper report ({rep.get('label') or 'PAPER'}): "
            f"return={sm.get('return_pct')}, maxDD={sm.get('max_drawdown_pct')}, "
            f"WR={sm.get('win_rate')}, closed={sm.get('closed_trades')}. "
            "External imports are excluded from paper equity. Not advice.",
            "paper_report",
        )


    nsig = len(ctx["signals"])
    # Soft ticker ping even without "signal for" phrasing
    if ticker_ask:
        hit = _find_signal(ctx, ticker_ask)
        if hit:
            return (
                f"Found cached signal for {ticker_ask}: {_fmt_signal(hit)}. "
                "Ask “how does paper trading work?” to simulate, or “how do fees work?” for cost drag. "
                "Not advice — educational snapshot only.",
                "signal_ticker",
            )

    return (
        f"Local E-ve assistant (offline OK). Cached signals: {nsig}. "
        f"You said: «{message.strip()[:160]}». "
        "Try: Scan status · Research web · What did you learn about the Fed · Learning summary · "
        "How do fees work? · How does paper trading work? · Market hours · Settings · help.",
        "fallback",
    )


def _copilot_flags() -> Tuple[bool, bool, int]:
    """(tools_enabled, memory_enabled, max_rounds)."""
    tools_on, mem_on, rounds = True, True, 4
    try:
        from .config import get_runtime_config

        cfg = get_runtime_config()
        tools_on = bool(getattr(cfg, "copilot_tools_enabled", True))
        mem_on = bool(getattr(cfg, "copilot_memory_enabled", True))
        rounds = int(getattr(cfg, "copilot_max_tool_rounds", 4) or 4)
    except Exception:
        pass
    rounds = max(1, min(6, rounds))
    return tools_on, mem_on, rounds


def _llm_api_key() -> str:
    return (
        os.environ.get("OPENAI_API_KEY", "").strip()
        or os.environ.get("LLM_API_KEY", "").strip()
        or os.environ.get("GAMMAR_LLM_KEY", "").strip()
    )


def _system_prompt(local_reply: str, strategy_plan: Optional[Dict[str, Any]] = None) -> str:
    from .copilot_memory import memory_prompt_block

    plan_bit = ""
    if strategy_plan and strategy_plan.get("ok"):
        plan_bit = (
            f" Active strategies now: {strategy_plan.get('active')}; "
            f"regime={strategy_plan.get('regime_label')}."
        )
    web_bit = ""
    try:
        from .copilot_web import web_enabled, get_allowlist
        if web_enabled():
            al = ", ".join(get_allowlist()[:8])
            web_bit = (
                " Prefer tools; cite sources. Use allowlisted web tools "
                "(web_search_finance / web_fetch_url / learn_from_web) for macro/earnings/news context; "
                f"hosts limited to [{al}…]. After useful fetches, learn_from_web stores notes. "
                "Never invent headlines or URLs. Web context is educational — still refuse hard buy/sell advice. "
            )
        else:
            web_bit = " E-ve web is disabled (copilot_web_enabled=0). "
    except Exception:
        web_bit = ""
    return (
        "You are E-ve, GAMMA-R's desk AI — always introduce and refer to yourself as E-ve (never Copilot/Assistant). Aiming to outpace terminal chat (Bloomberg/pro class) on AI-native workflow, "
        "automation awareness, and personal learning. Educational only — NOT financial advice. Refuse hard buy/sell. "
        "ALWAYS cite regime + policy firewall + scoreboard + crash mode before proposing paper size. "
        "When asked vs Bloomberg / pro terminals / our edge / beat retail, call get_competitive_gaps and/or get_edge_status. "
        "Honest: ahead on AI/automation/learning; behind on proprietary data universe. NEVER claim Bloomberg data license, BLP feeds, or full L2. "
        "Desk tools: desk_command_help, summarize_panel, brief_news, explain_ladder, run_monitor, eve_desk_brief, portfolio_risk_snapshot; also get_bars/get_tape/get_ladder_quote/run_custom_scan/get_economic_calendar. "
        "For a full desk snapshot call eve_desk_brief; for exposure/concentration/brackets call portfolio_risk_snapshot. "
        "For a daily scorecard call run_daily_self_critique. Feed: get_feed_health (Delayed|IEX|SIP|NBBO). Roadmap: propose_next_improvements. "
        "Overnight: get_overnight_research / get_web_learning. PAPER watermarks only — no live-audited returns. "
        "Paper options are educational sim only. Use tools; do not invent prices or positions. "
        f"{web_bit}"
        f"Owner memory: {memory_prompt_block()}.{plan_bit} "
        f"Local offline hint (may be stale): {local_reply[:700]}"
    )


def _openai_chat(messages: List[Dict[str, Any]], *, use_tools: bool, timeout: int = 25) -> Dict[str, Any]:
    """One Chat Completions call. Returns parsed JSON body or {}."""
    key = _llm_api_key()
    if not key:
        return {}
    from .copilot_tools import TOOL_SCHEMAS

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }
    if use_tools:
        body["tools"] = TOOL_SCHEMAS
        body["tool_choice"] = "auto"
    raw = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=raw,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _tool_calling_loop(
    message: str,
    history: Optional[List[Dict[str, str]]],
    local_reply: str,
    *,
    max_rounds: int = 4,
) -> Tuple[Optional[str], List[str], Optional[Dict[str, Any]], bool]:
    """
    Multi-step tool use. Returns (reply, tools_used, strategy_plan, memory_updated, sources).
    """
    from .copilot_tools import build_strategy_plan, execute_tool, tools_json_dumps

    if not _llm_api_key():
        return None, [], None, False, []

    tools_used: List[str] = []
    memory_updated = False
    sources: List[str] = []
    strategy_plan: Optional[Dict[str, Any]] = None
    try:
        strategy_plan = build_strategy_plan()
    except Exception:
        strategy_plan = None

    msgs: List[Dict[str, Any]] = [{"role": "system", "content": _system_prompt(local_reply, strategy_plan)}]
    for h in (history or [])[-6:]:
        role = h.get("role") or "user"
        if role not in ("user", "assistant"):
            role = "user"
        msgs.append({"role": role, "content": h.get("content") or ""})
    msgs.append({"role": "user", "content": message})

    try:
        for _round in range(max_rounds):
            data = _openai_chat(msgs, use_tools=True)
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            tool_calls = msg.get("tool_calls") or []
            content = (msg.get("content") or "").strip()

            if tool_calls:
                # Append assistant message with tool_calls
                msgs.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or "",
                        "tool_calls": tool_calls,
                    }
                )
                for tc in tool_calls:
                    fn = (tc.get("function") or {})
                    name = fn.get("name") or ""
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except json.JSONDecodeError:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}
                    result = execute_tool(name, args)
                    if name == "get_strategy_plan" and isinstance(result, dict) and result.get("ok"):
                        strategy_plan = result
                    if name in ("remember_fact", "learn_from_web"):
                        memory_updated = True
                    if isinstance(result, dict):
                        for u in (result.get("sources") or []):
                            if isinstance(u, str) and u.startswith("http") and u not in sources:
                                sources.append(u)
                        u1 = result.get("url")
                        if isinstance(u1, str) and u1.startswith("http") and u1 not in sources:
                            sources.append(u1)
                        stored = result.get("stored")
                        if isinstance(stored, dict):
                            for u in (stored.get("urls") or []):
                                if isinstance(u, str) and u.startswith("http") and u not in sources:
                                    sources.append(u)
                    if name and name not in tools_used:
                        tools_used.append(name)
                    msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id") or name,
                            "content": tools_json_dumps(result),
                        }
                    )
                continue

            if content:
                return content, tools_used, strategy_plan, memory_updated, sources
            break

        # Final no-tools polish if we exhausted rounds with only tool chatter
        data = _openai_chat(msgs + [{"role": "user", "content": "Reply now with a concise answer; no more tools."}], use_tools=False)
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        content = content.strip()
        return (content or None), tools_used, strategy_plan, memory_updated, sources
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError, OSError):
        return None, tools_used, strategy_plan, memory_updated, sources
    except Exception:
        return None, tools_used, strategy_plan, memory_updated, sources


def _optional_openai(message: str, history: Optional[List[Dict[str, str]]], local_reply: str) -> Optional[str]:
    """Backward-compatible single-shot rewrite (no tools). Prefer _tool_calling_loop."""
    key = _llm_api_key()
    if not key:
        return None
    try:
        from .copilot_memory import memory_prompt_block

        ctx_hint = local_reply[:500]
        system = (
            "You are E-ve, GAMMA-R's private trading assistant — always say you are E-ve. Educational only — NOT financial advice. "
            "Refuse buy/sell recommendations. Prefer concise plain English. "
            f"Owner memory: {memory_prompt_block()}. Local hint: {ctx_hint}"
        )
        msgs: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        for h in (history or [])[-6:]:
            role = h.get("role") or "user"
            if role not in ("user", "assistant"):
                role = "user"
            msgs.append({"role": role, "content": h.get("content") or ""})
        msgs.append({"role": "user", "content": message})
        data = _openai_chat(msgs, use_tools=False)
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip() or None
    except Exception:
        return None


def chat(message: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """
    Main E-ve assistant entry. Backward-compatible keys + optional:
      tools_used, memory_updated, strategy_plan
    """
    tools_on, mem_on, max_rounds = _copilot_flags()
    memory_updated = False
    tools_used: List[str] = []
    strategy_plan: Optional[Dict[str, Any]] = None

    if mem_on:
        try:
            from .copilot_memory import ingest_chat_preferences, touch_ticker
            updates = ingest_chat_preferences(message or "")
            memory_updated = bool(updates)
        except Exception:
            pass

    local, intent = _answer_local(message, history)

    # Cite / remember ticker from signal intents
    if intent == "signal_ticker" and mem_on:
        try:
            from .copilot_memory import touch_ticker
            t = _extract_ticker(_norm(message), message)
            if t:
                touch_ticker(t)
                memory_updated = True
        except Exception:
            pass

    llm_reply = None
    sources: List[str] = []
    if intent != "advice_refusal" and _llm_api_key():
        if tools_on:
            llm_reply, tools_used, strategy_plan, mem2, sources = _tool_calling_loop(
                message, history, local, max_rounds=max_rounds
            )
            memory_updated = memory_updated or mem2
        if not llm_reply:
            llm_reply = _optional_openai(message, history, local)

    # Local web research / learning paths — attach sources from store when present
    if intent in ("web_research", "web_learning") and not sources:
        try:
            from .copilot_web import query_web_learning
            topic_guess = ""
            m = re.search(r"about\s+(.+)$", _norm(message))
            if m:
                topic_guess = m.group(1).strip(" ?.!")[:80]
            for note in (query_web_learning(topic_guess, limit=3).get("notes") or []):
                for u in (note.get("urls") or []):
                    if isinstance(u, str) and u.startswith("http") and u not in sources:
                        sources.append(u)
        except Exception:
            pass

    # Local path: attach strategy_plan when relevant
    if strategy_plan is None and intent in ("strategies", "regime", "scan", "help", "memory_update"):
        try:
            from .copilot_tools import build_strategy_plan
            strategy_plan = build_strategy_plan()
        except Exception:
            strategy_plan = None

    reply = llm_reply or local
    if llm_reply and tools_used:
        source = "llm+tools"
    elif llm_reply:
        source = "openai"
    else:
        source = "local"

    out: Dict[str, Any] = {
        "reply": reply,
        "intent": intent,
        "source": source,
        "disclaimer": "Educational only — not financial advice.",
        "tools_used": tools_used,
        "memory_updated": bool(memory_updated),
        "sources": sources[:12],
    }
    if strategy_plan and isinstance(strategy_plan, dict):
        # Compact for clients
        out["strategy_plan"] = {
            "ok": strategy_plan.get("ok"),
            "active": strategy_plan.get("active"),
            "regime_label": strategy_plan.get("regime_label"),
            "mode": strategy_plan.get("mode"),
            "weights": strategy_plan.get("weights"),
        }

    # v2 UI extras
    try:
        out["crash"] = _crash_badge()
    except Exception:
        out["crash"] = {"active": False}
    try:
        out["scoreboard_snippet"] = _scoreboard_snippet(4)
    except Exception:
        out["scoreboard_snippet"] = {}
    try:
        out["outcome_blurb"] = _outcome_blurb(limit=10)
    except Exception:
        out["outcome_blurb"] = ""
    try:
        props = _build_proposals(message, strategy_plan)
        if not props and intent == "proposals":
            props = _build_proposals("propose paper idea " + (message or ""), strategy_plan)
        if props:
            out["proposals"] = props
    except Exception:
        pass
    # Inject constraints into strategy_plan answers
    if out.get("strategy_plan") and isinstance(out["strategy_plan"], dict):
        try:
            from .copilot_memory import compact_memory
            mem = compact_memory()
            out["strategy_plan"]["user_constraints"] = {
                "prefer_sectors": mem.get("prefer_sectors"),
                "avoid_sectors": mem.get("avoid_sectors"),
                "risk_comfort": mem.get("risk_comfort"),
                "strategy_interest": mem.get("strategy_interest"),
            }
        except Exception:
            pass
    return out

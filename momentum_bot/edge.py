"""
GAMMA-R differentiation / edge report.

Summarizes process & intelligence advantages retail signal bots usually lack:
multi-strategy regime router, policy firewall, crash mode, external-trade
learning, allowlisted web research, decision audit, paper leaderboard watermark.

Honest: never claims L2 book or live-audited returns.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


EDGE_BULLETS: List[Dict[str, str]] = [
    {
        "id": "router",
        "title": "Multi-strategy regime router",
        "blurb": "Auto-weights momentum, mean-reversion, breakout, RS, vol-target, pairs, FX, PEAD by regime — not a single signal spam feed.",
    },
    {
        "id": "firewall",
        "title": "Hard policy firewall",
        "blurb": "Non-LLM pre-submit checks (size, denylist, daily/cycle caps, circuit breaker). Fail closed. Audited.",
    },
    {
        "id": "crash",
        "title": "Crash / regime-shock mode",
        "blurb": "Cuts momentum/breakout size on sharp drops; exits still allowed. Visible until-date on Dashboard.",
    },
    {
        "id": "external",
        "title": "External-trade learning",
        "blurb": "Import brokerage CSV/Alpaca history with origin=external — learn from fills outside the app without mixing paper equity.",
    },
    {
        "id": "web",
        "title": "Allowlisted web research",
        "blurb": "E-ve fetches only finance/macro allowlist hosts; distills overnight notes — not open browsing.",
    },
    {
        "id": "audit",
        "title": "Decision audit trail",
        "blurb": "Append-only JSONL: regime, crash, router, firewall allow/deny, order or skip — replayable.",
    },
    {
        "id": "leaderboard",
        "title": "PAPER leaderboard watermark",
        "blurb": "Public paper stats clearly labeled PAPER — not live audited. Refuses fake track records.",
    },
    {
        "id": "nbbo",
        "title": "NBBO / top-of-book (L2-lite)",
        "blurb": "Best bid/ask/mid/spread when keys exist. Explicitly not a Level-2 order book.",
    },
]


def why_gamma_r_card(cfg: Any = None) -> Dict[str, Any]:
    """Short in-app card — beat retail + ahead of pro terminals on AI desk (honest)."""
    desk_bullets = list(EDGE_BULLETS) + [
        {
            "id": "desk_go",
            "title": "Command bar (GO) + multi-panel desk",
            "blurb": "Bloomberg-inspired workflow (AAPL, NEWS, CHART, EVE) — not a BLP data license.",
        },
        {
            "id": "eve_desk",
            "title": "E-ve desk supremacy",
            "blurb": "Desk AI that cites regime/firewall/scoreboard; briefs, monitor, ladder explain.",
        },
    ]
    return {
        "ok": True,
        "title": "Ahead of pro terminals (AI desk)",
        "badge": "AHEAD ON AI",
        "subtitle": "AI-native desk + automation + personal learning — not fake BLP data",
        "bullets": desk_bullets,
        "honest_limits": [
            "Not a Bloomberg data license / proprietary BLP universe",
            "Not a Trade Ideas–class Level-2 / full tape scanner",
            "Does not market live-audited returns (PAPER only)",
            "No full options/futures live execution yet",
        ],
        "tagline": (
            "Ahead of pro terminals on AI co-pilot, automation, and personal learning; "
            "behind on proprietary data universe. Never fake Bloomberg feeds or full L2."
        ),
        "vs_bots_one_liner": (
            "We win on AI desk / process / risk OS; Bloomberg-class terminals still win on "
            "licensed data breadth — we do not claim a BLP license."
        ),
        "vs_bloomberg": {
            "ahead": [
                "E-ve desk AI with regime/firewall/scoreboard citation",
                "Personal learning loops (external fills, overnight web, self-critique)",
                "Paper-first automation with hard policy firewall",
                "GO command bar + monitor launchpad + cross-asset board (inspired UX)",
            ],
            "behind": [
                "Proprietary Bloomberg data universe / BLP fields",
                "Full multi-asset licensed news + analytics catalog",
                "True Level-2 / exchange depth",
            ],
            "not_bloomberg_licensed": True,
            "not_level2": True,
        },
        "generated_at": _utc_now(),
    }


def build_edge_status(cfg: Any = None) -> Dict[str, Any]:
    """
    On-demand / nightly edge report: active advantages + degraded feeds.
    GET /edge/status
    """
    from .config import get_runtime_config

    cfg = cfg or get_runtime_config()
    advantages: List[Dict[str, Any]] = []
    degraded: List[Dict[str, Any]] = []

    # Router
    try:
        from .strategies import get_last_router_decision
        from .strategies.runner import get_last_cycle

        router = get_last_router_decision()
        cycle = get_last_cycle() or {}
        advantages.append({
            "id": "router",
            "active": True,
            "detail": {
                "mode": getattr(cfg, "router_mode", "auto"),
                "last_fired": (cycle.get("fired") or [])[:6],
                "router": router.to_dict() if router and hasattr(router, "to_dict") else None,
            },
        })
    except Exception as exc:  # noqa: BLE001
        degraded.append({"id": "router", "reason": str(exc)})

    # Firewall
    try:
        from . import policy_firewall as fw

        st = fw.status()
        advantages.append({
            "id": "firewall",
            "active": bool(st.get("enabled")),
            "detail": {
                "day_orders": st.get("day_orders"),
                "recent_denies": sum(1 for r in (st.get("recent") or []) if not r.get("allowed", True)),
            },
        })
        if not st.get("enabled"):
            degraded.append({"id": "firewall", "reason": "firewall_enabled=false"})
    except Exception as exc:  # noqa: BLE001
        degraded.append({"id": "firewall", "reason": str(exc)})

    # Crash mode
    try:
        from .crash_mode import get_crash_status

        crash = get_crash_status(cfg).to_dict()
        advantages.append({
            "id": "crash",
            "active": bool(getattr(cfg, "crash_mode_enabled", True)),
            "detail": {
                "crash_active": bool(crash.get("active")),
                "until": crash.get("until"),
                "reason": (str(crash.get("reason") or ""))[:120] or None,
            },
        })
    except Exception as exc:  # noqa: BLE001
        degraded.append({"id": "crash", "reason": str(exc)})

    # External learning
    try:
        from .learning import learning_stats

        stats = learning_stats()
        ext_n = int(stats.get("journal_count_external") or 0)
        advantages.append({
            "id": "external",
            "active": True,
            "detail": {"external_journal_trades": ext_n, "paper_journal_trades": stats.get("journal_count_paper")},
        })
    except Exception as exc:  # noqa: BLE001
        degraded.append({"id": "external", "reason": str(exc)})

    # Web research
    try:
        from .copilot_web import web_enabled, query_web_learning

        on = bool(web_enabled())
        notes = query_web_learning("", limit=3) if on else {"notes": []}
        advantages.append({
            "id": "web",
            "active": on and bool(getattr(cfg, "copilot_web_enabled", True)),
            "detail": {
                "recent_notes": len(notes.get("notes") or []),
                "scheduled": bool(getattr(cfg, "auto_web_learn_enabled", False)),
            },
        })
        if not on:
            degraded.append({"id": "web", "reason": "copilot_web_enabled=false"})
    except Exception as exc:  # noqa: BLE001
        degraded.append({"id": "web", "reason": str(exc)})

    # Decision audit
    try:
        from .decision_audit import read_decisions

        rows = read_decisions(limit=5)
        advantages.append({
            "id": "audit",
            "active": bool(getattr(cfg, "decision_audit_enabled", True)),
            "detail": {"recent": len(rows), "last_ts": (rows[0].get("timestamp") if rows else None)},
        })
    except Exception as exc:  # noqa: BLE001
        degraded.append({"id": "audit", "reason": str(exc)})

    # Paper leaderboard honesty
    advantages.append({
        "id": "leaderboard",
        "active": True,
        "detail": {"watermark": "PAPER — not live audited", "audited": False, "live": False},
    })

    # Feed / NBBO
    try:
        from .data_sources import get_data_source_status
        from .quotes import build_quotes

        ds = get_data_source_status() or {}
        q = build_quotes(limit=5)
        badge = q.get("feed_badge") or ds.get("feed_badge") or "Delayed"
        advantages.append({
            "id": "nbbo",
            "active": badge in ("NBBO", "SIP", "IEX"),
            "detail": {
                "feed_badge": badge,
                "not_level2": True,
                "keys_present": q.get("keys_present"),
                "quote_count": q.get("count"),
                "connection_health": ds.get("connection_health"),
                "fallback_active": ds.get("fallback_active"),
            },
        })
        if ds.get("fallback_active") or badge == "Delayed":
            degraded.append({
                "id": "feed",
                "reason": "Delayed or fallback feed — top-of-book NBBO needs Alpaca keys / healthy SIP|IEX",
            })
    except Exception as exc:  # noqa: BLE001
        degraded.append({"id": "nbbo", "reason": str(exc)})

    # Scoreboard keep/watch/cut
    try:
        from .scoreboard import build_scoreboard

        board = build_scoreboard(cfg)
        by_status: Dict[str, int] = {}
        for s in board.get("strategies") or []:
            st = str(s.get("status") or "watch").lower()
            by_status[st] = by_status.get(st, 0) + 1
        advantages.append({
            "id": "scoreboard",
            "active": True,
            "detail": {"by_status": by_status, "label": board.get("label")},
        })
    except Exception as exc:  # noqa: BLE001
        degraded.append({"id": "scoreboard", "reason": str(exc)})

    active_ids = [a["id"] for a in advantages if a.get("active")]
    return {
        "ok": True,
        "generated_at": _utc_now(),
        "label": "GAMMA-R edge report — process/intelligence/risk (not L2 / not live-audited)",
        "tagline": "Better than signal bots on routing, firewall, crash mode, learning, audit — honest about limits.",
        "why": why_gamma_r_card(cfg),
        "advantages": advantages,
        "active_advantage_ids": active_ids,
        "degraded": degraded,
        "degraded_count": len(degraded),
        "not_level2": True,
        "live_audited_returns": False,
        "paper_first": True,
        "vs_signal_bots": {
            "win_column": [
                "Regime-aware multi-strategy router vs single-indicator spam",
                "Deterministic policy firewall + decision audit",
                "Crash mode + scoreboard keep/watch/cut",
                "External fill learning + allowlisted overnight research",
                "Honest PAPER watermark (no fake live track record)",
            ],
            "they_still_win_on": [
                "True Level-2 / full tape day-trade scanners (Trade Ideas class)",
                "Marketed live-audited return dashboards",
                "Full options/futures order routing",
            ],
        },
    }


def overnight_research_summary(limit: int = 8) -> Dict[str, Any]:
    """E-ve helper: summarize recent web_learning notes."""
    try:
        from .copilot_web import query_web_learning

        notes = query_web_learning("", limit=limit)
        rows = notes.get("notes") or []
        lines = []
        for n in rows[:limit]:
            topic = n.get("topic") or "note"
            summary = (n.get("summary") or n.get("text") or "")[:220]
            lines.append(f"• {topic}: {summary}")
        text = "\n".join(lines) if lines else "No overnight web notes yet. Enable auto_web_learn or ask learn_from_web."
        try:
            log_ai_process("overnight_research", {"count": len(rows)})
        except Exception:
            pass
        return {
            "ok": True,
            "count": len(rows),
            "summary": text,
            "notes": rows,
            "label": "Overnight research (allowlisted web) — educational",
            "continuous_improvement": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "summary": "", "notes": []}


# ---- Competitive gaps + feed health + next improvements (E-ve) ----

CLOSED_GAPS: List[Dict[str, str]] = [
    {"id": "multi_strategy", "title": "Multi-strategy regime router"},
    {"id": "firewall", "title": "Policy firewall (fail closed)"},
    {"id": "crash", "title": "Crash / regime-shock mode"},
    {"id": "copilot_web", "title": "E-ve allowlisted web + learning"},
    {"id": "paper_leaderboard", "title": "PAPER leaderboard watermark"},
    {"id": "intraday_heat", "title": "Intraday heat (not L2)"},
    {"id": "sip_badge", "title": "Feed badge Delayed|IEX|SIP|NBBO"},
    {"id": "options_research", "title": "Options research read-only"},
    {"id": "broker_status", "title": "Broker status lite (paper / alpaca / ibkr planned)"},
    {"id": "nbbo", "title": "NBBO / top-of-book quotes (L2-lite)"},
    {"id": "watchlist_push", "title": "Watchlist WS/SSE quote push"},
    {"id": "paper_options", "title": "Paper options simulator (long call/put)"},
    {"id": "scheduled_web", "title": "Scheduled web learning loop"},
    {"id": "alerts", "title": "Alerts: crash / heat / cut / firewall streak"},
    {"id": "edge_report", "title": "Edge report + Why GAMMA-R card"},
    {"id": "external_trades", "title": "External-trade learning"},
    {"id": "decision_audit", "title": "Decision audit JSONL"},
    {"id": "self_critique", "title": "Daily E-ve self-critique"},
    {"id": "overnight_ingest", "title": "Overnight web notes → learning summary"},
    {"id": "pro_charts", "title": "Pro candle charts (OHLCV + VWAP)"},
    {"id": "tape_lite", "title": "Tape lite (recent prints)"},
    {"id": "nbbo_ladder", "title": "NBBO top-of-book ladder UI"},
    {"id": "scanner_builder", "title": "Pro scanner builder (/scan/custom)"},
    {"id": "options_chain_greeks", "title": "Options chain + BS greeks (paper)"},
    {"id": "paper_pro_orders", "title": "Paper pro orders (stop/TP/bracket/OCO)"},
    {"id": "econ_calendar", "title": "Economic calendar rail"},
    {"id": "pro_layout", "title": "Pro layout denser Dashboard + hotkeys"},
    {"id": "desk_command", "title": "Desk GO command bar (Bloomberg-inspired)"},
    {"id": "desk_layout", "title": "Multi-panel desk presets"},
    {"id": "desk_monitor", "title": "Monitor / launchpad strip"},
    {"id": "desk_cross_asset", "title": "Cross-asset board"},
    {"id": "watchlist_columns", "title": "Configurable watchlist columns"},
    {"id": "desk_brief", "title": "E-ve AI news brief"},
    {"id": "eve_desk_tools", "title": "E-ve desk tools (command/monitor/brief/ladder)"},
    {"id": "eve_desk_brief", "title": "Full E-ve desk brief (regime/signals/crash/scoreboard/overnight)"},
    {"id": "portfolio_risk_snapshot", "title": "Portfolio risk snapshot tool"},
    {"id": "portfolio_analytics", "title": "GET /portfolio/analytics terminal-lite"},
]


OPEN_SOFT: List[Dict[str, str]] = [
    {"id": "ibkr_full", "title": "Full IBKR TWS/Client Portal trading (stub/planned only)"},
    {"id": "denser_mobile_ticks", "title": "Even denser mobile tick fan-out under load"},
    {"id": "iv_surface_3d", "title": "Full IV surface / vol smile 3D UI"},
]

HARD_OPEN: List[Dict[str, str]] = [
    {"id": "true_l2", "title": "True Level-2 order book / full tape (Trade Ideas class)"},
    {"id": "live_audited", "title": "Marketed live-audited returns"},
    {"id": "full_options_exec", "title": "Full live options order routing"},
    {"id": "futures", "title": "Futures execution"},
    {"id": "colocation", "title": "Colocation / exchange-proximate infra"},
    {"id": "bloomberg_license", "title": "Bloomberg proprietary data license / BLP universe"},
]


def competitive_gaps() -> Dict[str, Any]:
    """Honest closed vs open vs hard — for E-ve get_competitive_gaps."""
    return {
        "ok": True,
        "generated_at": _utc_now(),
        "label": "Competitive gaps — honest; never claim L2 or live-audited returns",
        "closed": CLOSED_GAPS,
        "open_soft": OPEN_SOFT,
        "still_open_hard": HARD_OPEN,
        "closed_count": len(CLOSED_GAPS),
        "vs_signal_bots": {
            "we_win": [
                "Regime-aware multi-strategy router vs single-indicator spam",
                "Deterministic policy firewall + decision audit",
                "Crash mode + scoreboard keep/watch/cut",
                "External fill learning + allowlisted overnight research",
                "Honest PAPER watermark (no fake live track record)",
                "NBBO top-of-book when keys exist — labeled not L2",
                "Pro charts / tape-lite / NBBO ladder / scanner builder / paper brackets",
                "E-ve that cites firewall/regime/scoreboard before proposing",
                "Desk GO + multi-panel + monitor + cross-asset + AI briefs",
            ],
            "they_still_win": [
                "True Level-2 / full tape day-trade scanners",
                "Marketed live-audited return dashboards",
                "Full options/futures order routing",
            ],
        },
        "vs_bloomberg_pro_terminals": {
            "ahead": [
                "AI-native E-ve desk co-pilot (briefs, monitor, ladder explain, GO help)",
                "Personal learning + overnight research compound",
                "Automation with fail-closed firewall (paper-first)",
            ],
            "behind": [
                "Proprietary Bloomberg / BLP data universe",
                "Licensed full news + analytics catalog",
                "True L2 depth and co-lo infra",
            ],
            "honest": (
                "Close the UX gap with Bloomberg-inspired workflow; "
                "win on AI/automation/learning — never claim a Bloomberg data license or full L2."
            ),
        },
        "not_level2": True,
        "not_bloomberg_licensed": True,
        "live_audited_returns": False,
    }


def feed_health() -> Dict[str, Any]:
    """Delayed | IEX | SIP | NBBO — for E-ve get_feed_health."""
    try:
        from .data_sources import get_data_source_status, realtime_sip_enabled
        from .quotes import build_quotes

        ds = get_data_source_status() or {}
        q = build_quotes(["SPY", "QQQ", "AAPL"], limit=5)
        badge = q.get("feed_badge") or ds.get("feed_badge") or "Delayed"
        return {
            "ok": True,
            "feed_badge": badge,
            "allowed_badges": ["Delayed", "IEX", "SIP", "NBBO"],
            "not_level2": True,
            "label": "Top-of-book / last trade — not full depth",
            "realtime_sip_enabled": bool(realtime_sip_enabled()),
            "keys_present": q.get("keys_present"),
            "fallback_active": ds.get("fallback_active"),
            "connection_health": ds.get("connection_health"),
            "last_tick_age_sec": ds.get("last_tick_age_sec"),
            "data_label": ds.get("data_label"),
            "quote_sample_count": q.get("count"),
            "degraded": bool(ds.get("fallback_active") or badge == "Delayed"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "feed_badge": "Delayed",
            "not_level2": True,
            "error": str(exc),
        }


def propose_next_improvements(limit: int = 8) -> Dict[str, Any]:
    """Ranked suggestions from live health + learning stats."""
    from .config import get_runtime_config

    cfg = get_runtime_config()
    suggestions: List[Dict[str, Any]] = []

    feed = feed_health()
    if feed.get("degraded") or feed.get("feed_badge") == "Delayed":
        suggestions.append({
            "rank": 1,
            "id": "enable_nbbo",
            "title": "Enable Alpaca keys / SIP|IEX for NBBO top-of-book",
            "why": "Feed is Delayed — competitors feel faster without you claiming fake L2.",
            "action": "Set ALPACA_API_KEY/SECRET; Settings → realtime SIP or GET /quotes",
        })

    if not bool(getattr(cfg, "auto_web_learn_enabled", False)):
        suggestions.append({
            "rank": 2,
            "id": "schedule_web",
            "title": "Turn on scheduled web learning",
            "why": "Overnight allowlisted research compounds E-ve edge vs mute signal bots.",
            "action": 'PUT /config {"auto_web_learn_enabled": true}',
        })

    if not bool(getattr(cfg, "options_read_only", False)):
        suggestions.append({
            "rank": 3,
            "id": "options_research",
            "title": "Enable options research + paper options sim",
            "why": "Educational options foothold without live routing risk.",
            "action": 'PUT /config {"options_read_only": true, "paper_options_enabled": true}',
        })

    try:
        from .learning import learning_stats

        stats = learning_stats()
        if int(stats.get("journal_count_external") or 0) < 5:
            suggestions.append({
                "rank": 4,
                "id": "import_external",
                "title": "Import external brokerage fills",
                "why": "Learn from real fills outside the app — rare among retail scanners.",
                "action": "Learning → paste CSV / POST /trades/import",
            })
    except Exception:
        pass

    try:
        from . import policy_firewall as fw

        st = fw.status()
        if not st.get("enabled"):
            suggestions.append({
                "rank": 1,
                "id": "enable_firewall",
                "title": "Re-enable policy firewall",
                "why": "Fail-closed risk OS is a core differentiator — do not run without it.",
                "action": 'PUT /config {"firewall_enabled": true}',
            })
    except Exception:
        pass

    if not bool(getattr(cfg, "alerts_enabled", True)):
        suggestions.append({
            "rank": 5,
            "id": "alerts",
            "title": "Enable alert hooks",
            "why": "Crash / heat / cut / firewall streak awareness without staring at charts.",
            "action": 'PUT /config {"alerts_enabled": true}',
        })

    suggestions.append({
        "rank": 9,
        "id": "hard_l2",
        "title": "(Hard) True L2 book — intentionally open",
        "why": "We refuse to fake depth. Partner/data later if you need Trade Ideas–class tape.",
        "action": "Keep not_level2 honesty; use NBBO + intraday heat instead",
    })

    suggestions.sort(key=lambda x: int(x.get("rank") or 99))
    out = {
        "ok": True,
        "generated_at": _utc_now(),
        "suggestions": suggestions[: max(1, min(15, int(limit or 8)))],
        "feed": {"badge": feed.get("feed_badge"), "degraded": feed.get("degraded")},
        "not_level2": True,
        "label": "Ranked next improvements — process/intelligence, not fake L2",
        "continuous_improvement": True,
    }
    try:
        log_ai_process(
            "propose_next_improvements",
            {"top": [s.get("id") for s in out["suggestions"][:5]], "feed": out["feed"]},
        )
    except Exception:
        pass
    return out


def log_ai_process(event: str, detail: Optional[Dict[str, Any]] = None) -> None:
    """Append short journey note for E-ve memory of improvement process."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "ai_process_log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _utc_now(),
        "event": event,
        "detail": detail or {},
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except OSError:
        pass


def build_edge_status_logged(cfg: Any = None) -> Dict[str, Any]:
    """Edge status + process log breadcrumb."""
    report = build_edge_status(cfg)
    report["vs_bloomberg_pro_terminals"] = competitive_gaps().get("vs_bloomberg_pro_terminals")
    report["not_bloomberg_licensed"] = True
    try:
        log_ai_process(
            "edge_report",
            {
                "active": report.get("active_advantage_ids"),
                "degraded_count": report.get("degraded_count"),
                "feed": next(
                    (a.get("detail", {}).get("feed_badge") for a in (report.get("advantages") or []) if a.get("id") == "nbbo"),
                    None,
                ),
            },
        )
    except Exception:
        pass
    return report


def ingest_overnight_into_learning(*, limit: int = 12, reason: str = "auto") -> Dict[str, Any]:
    """
    Distill recent allowlisted web_learning notes into data/overnight_learning_digest.json
    so Learning stats / E-ve can surface overnight research without re-fetching the web.
    Paper-first / educational only.
    """
    import json
    from pathlib import Path

    from .learning import DATA_DIR

    digest_path = DATA_DIR / "overnight_learning_digest.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    overnight = overnight_research_summary(limit=limit)
    notes = overnight.get("notes") or []
    topics: List[str] = []
    bullets: List[str] = []
    for n in notes[:limit]:
        topic = str(n.get("topic") or "note").strip()
        summary = (n.get("summary") or n.get("text") or "").strip()[:280]
        if topic and topic not in topics:
            topics.append(topic)
        if summary:
            bullets.append(f"{topic}: {summary}")

    digest = {
        "ok": True,
        "updated_at": _utc_now(),
        "reason": reason,
        "note_count": len(notes),
        "topics": topics[:20],
        "bullets": bullets[:12],
        "summary_text": overnight.get("summary") or "",
        "label": "Overnight web notes ingested into learning summary — educational",
        "paper_first": True,
        "not_advice": True,
    }
    try:
        digest_path.write_text(json.dumps(digest, indent=2, default=str), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc), "digest": digest}

    try:
        log_ai_process(
            "overnight_ingest",
            {"note_count": len(notes), "topics": topics[:8], "reason": reason},
        )
    except Exception:
        pass
    return digest


def load_overnight_learning_digest() -> Dict[str, Any]:
    """Read last overnight→learning digest (empty dict if missing)."""
    import json
    from pathlib import Path

    try:
        from .learning import DATA_DIR
        path = DATA_DIR / "overnight_learning_digest.json"
        if not path.exists():
            return {"ok": False, "present": False, "note_count": 0}
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("present", True)
            data.setdefault("ok", True)
            return data
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "present": False, "error": str(exc), "note_count": 0}
    return {"ok": False, "present": False, "note_count": 0}


def run_daily_self_critique(*, persist: bool = True) -> Dict[str, Any]:
    """
    E-ve daily self-critique: honest scorecard of edge health, gaps, and next moves.
    Writes data/daily_self_critique.json + ai_process_log breadcrumb. Never claims L2/live-audited.
    """
    import json
    from pathlib import Path

    report = build_edge_status()
    gaps = competitive_gaps()
    improv = propose_next_improvements(limit=5)
    feed = feed_health()
    overnight = load_overnight_learning_digest()

    active = list(report.get("active_advantage_ids") or [])
    degraded = list(report.get("degraded") or [])
    closed_n = int(gaps.get("closed_count") or len(gaps.get("closed") or []))
    hard_n = len(gaps.get("still_open_hard") or [])

    strengths: List[str] = []
    weaknesses: List[str] = []
    actions: List[str] = []

    for a in report.get("advantages") or []:
        if a.get("active"):
            strengths.append(str(a.get("id")))
    for d in degraded:
        weaknesses.append(f"{d.get('id')}: {d.get('reason')}")

    badge = feed.get("feed_badge") or "Delayed"
    if badge == "Delayed":
        weaknesses.append("Feed Delayed — competitors feel snappier without us faking L2")
        actions.append("Enable Alpaca keys for NBBO/SIP|IEX top-of-book")
    else:
        strengths.append(f"feed:{badge}")

    if int(overnight.get("note_count") or 0) == 0:
        weaknesses.append("No overnight web digest yet — mute vs research-compounding bots")
        actions.append("Enable auto_web_learn_enabled or POST /auto/web-learn/run")
    else:
        strengths.append(f"overnight_notes={overnight.get('note_count')}")

    for s in (improv.get("suggestions") or [])[:4]:
        title = s.get("title") or s.get("id")
        if title:
            actions.append(str(title))

    # Keep hard gaps visible as intentional — not failures
    intentional = [h.get("title") for h in (gaps.get("still_open_hard") or []) if h.get("title")]

    critique = {
        "ok": True,
        "generated_at": _utc_now(),
        "label": "Daily self-critique — beat retail bots on process, stay honest on limits",
        "score": {
            "active_advantages": len(active),
            "degraded_count": len(degraded),
            "closed_gaps": closed_n,
            "hard_open_gaps": hard_n,
            "feed_badge": badge,
            "overnight_notes": int(overnight.get("note_count") or 0),
        },
        "strengths": strengths[:12],
        "weaknesses": weaknesses[:12],
        "next_actions": actions[:8],
        "intentional_limits": intentional,
        "not_level2": True,
        "live_audited_returns": False,
        "paper_first": True,
        "summary": (
            f"Active edges={len(active)} degraded={len(degraded)} closed_gaps={closed_n}. "
            f"Feed={badge}. Overnight notes={overnight.get('note_count') or 0}. "
            "Refuse fake L2 / live-audited claims."
        ),
        "improvements_top": [
            {"id": s.get("id"), "title": s.get("title")} for s in (improv.get("suggestions") or [])[:5]
        ],
    }

    if persist:
        try:
            from .learning import DATA_DIR
            path = DATA_DIR / "daily_self_critique.json"
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(critique, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass
        try:
            log_ai_process(
                "daily_self_critique",
                {
                    "active": len(active),
                    "degraded": len(degraded),
                    "feed": badge,
                    "top_actions": [a[:60] for a in actions[:3]],
                },
            )
        except Exception:
            pass
    return critique


def load_daily_self_critique() -> Dict[str, Any]:
    """Last persisted daily critique, or fresh run if missing."""
    import json
    from pathlib import Path

    try:
        from .learning import DATA_DIR
        path = DATA_DIR / "daily_self_critique.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("ok"):
                data["cached"] = True
                return data
    except Exception:
        pass
    return run_daily_self_critique(persist=True)

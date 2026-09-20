"""
Co-pilot tool schemas + compact JSON executors for LLM tool-calling.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_regime",
            "description": "Current market regime (bull/bear/sideways/high_vol) if available.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session",
            "description": "Market session / hours for configured exchange and user timezone.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_signals",
            "description": "Top cached scan signals (educational, not advice).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max signals (1-15)", "default": 5},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_signal",
            "description": "Cached signal detail for one ticker.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_paper",
            "description": "Paper portfolio snapshot (cash, equity, open positions).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_watchlist",
            "description": "Owner watchlist tickers.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news_eod",
            "description": "End-of-day news digest (headlines, sector tilt).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news_ticker",
            "description": "News/sentiment aggregate for one ticker.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_currency",
            "description": "FX / currency panel quotes (informational).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_strategy_plan",
            "description": "Active strategies from the router for current regime + why.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_performance",
            "description": "Learning / journal performance summary.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_external_learning_stats",
            "description": (
                "Paper vs external (imported brokerage) vs combined learning stats. "
                "External imports do not change paper portfolio cash."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_config_summary",
            "description": "Redacted strategy config summary (no secrets).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_memory",
            "description": "Stored co-pilot preferences, strategy interest, recent tickers/outcomes.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Persist a short user preference or fact for future chats.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Short fact (no secrets)"},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_decisions",
            "description": "Recent auto/copilot decision audit rows (regime, crash mode, router, firewall, session gate).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max rows (default 10)"},
                },
                "additionalProperties": False,
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_crash_mode",
            "description": "Crash / shock mode status (active, size mult, aggressive entries paused).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scoreboard",
            "description": "Walk-forward / rolling paper+external scoreboard (keep/watch/cut per strategy).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_paper_report",
            "description": "PAPER performance report (equity, WR, max DD, vs buy-hold). Excludes live.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_decision_audit",
            "description": "Recent decision-audit rows (regime, crash, router, firewall, session).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 10}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_strategy_packs",
            "description": "List one-tap strategy packs (templates). Preview before apply.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_strategy_pack",
            "description": "Dry-run preview of a strategy pack (toggles / tweaks). Does not apply.",
            "parameters": {
                "type": "object",
                "properties": {"pack_id": {"type": "string"}},
                "required": ["pack_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_strategy_pack",
            "description": (
                "Apply a strategy pack ONLY when confirm=true (user explicitly confirmed). "
                "Otherwise returns preview. Paper-first; does not unlock live."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pack_id": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["pack_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scan_status",
            "description": "Scan cache freshness / counts / top tickers.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_for_ticker",
            "description": "Per-ticker session gate (exchange hours, allow new entries).",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_firewall_status",
            "description": "Policy firewall status (limits, day/cycle counts, recent denials).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_external_trades",
            "description": "List imported external (brokerage) fills used for learning. Never live.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 20}},
                "additionalProperties": False,
            },
        },
    },


    {
        "type": "function",
        "function": {
            "name": "web_search_finance",
            "description": (
                "Allowlisted finance/macro web search (multi-fetch). "
                "Only reuters/bloomberg/cnbc/marketwatch/ft/wsj/fed/sec/investing/yahoo/bbc "
                "(+ coindesk if crypto on). Educational context — NOT buy/sell advice."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Macro/earnings/news query"},
                    "max_sources": {"type": "integer", "default": 3},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch_url",
            "description": (
                "Fetch + extract text from a URL ONLY if its host is on the co-pilot web allowlist. "
                "Blocks localhost, IPs, file://, shorteners, and non-allowlisted domains."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "https URL on an allowlisted host"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_from_web",
            "description": (
                "Research an educational topic via allowlisted sources and store a short distilled "
                "note in data/web_learning.jsonl (dated, sourced, tagged) for future citation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "max_sources": {"type": "integer", "default": 3},
                },
                "required": ["topic"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_web_learning",
            "description": (
                "Read prior allowlisted web-learning notes (offline). "
                "Use when user asks what you learned about a topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Optional filter substring"},
                    "limit": {"type": "integer", "default": 8},
                },
                "additionalProperties": False,
            },
        },
    },


    {
        "type": "function",
        "function": {
            "name": "get_edge_status",
            "description": (
                "GAMMA-R edge report: active advantages (router, firewall, crash, web, audit, NBBO) "
                "plus degraded feeds. Use when asked how we stay ahead of retail signal bots. "
                "Never claim L2 or live-audited returns."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_competitive_gaps",
            "description": (
                "Honest closed vs open vs hard competitive gaps vs Trade Ideas / signal-bot class. "
                "Use for 'how do we compare' / 'vs other bots'."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_feed_health",
            "description": (
                "Feed badge health: Delayed | IEX | SIP | NBBO. Top-of-book only — not Level-2 depth."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_next_improvements",
            "description": (
                "Ranked next improvements from live feed health + learning stats + config. "
                "Prefer process/intelligence/risk over fake L2."
            ),
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 8}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overnight_research",
            "description": "Summarize allowlisted overnight web_learning notes for the owner.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 8}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quotes",
            "description": "Top-of-book NBBO/L2-lite quotes (bid/ask/mid/spread). Not full depth.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbols": {"type": "string", "description": "Comma-separated tickers"},
                    "limit": {"type": "integer", "default": 20},
                },
                "additionalProperties": False,
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "run_daily_self_critique",
            "description": (
                "Daily self-critique scorecard: strengths, weaknesses, next actions vs retail signal bots. "
                "Uses live edge/gaps/feed/overnight digest. Never claims L2 or live-audited returns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fresh": {
                        "type": "boolean",
                        "default": True,
                        "description": "If true, recompute; if false, return last cached critique",
                    }
                },
                "additionalProperties": False,
            },
        },
    },



    {
        "type": "function",
        "function": {
            "name": "desk_command_help",
            "description": "GO command bar help — Bloomberg-inspired desk commands (not a BLP license).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_panel",
            "description": "Summarize a desk panel: monitor, ladder, news/brief, cross-asset, layout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "panel_id": {"type": "string", "description": "monitor|ladder|news|brief|cross-asset|layout"},
                    "symbol": {"type": "string", "description": "Optional symbol for ladder/news/brief"},
                },
                "required": ["panel_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "brief_news",
            "description": "E-ve AI news brief for a symbol from allowlisted web + local news. Not Bloomberg news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_ladder",
            "description": "Explain NBBO top-of-book ladder for a symbol. Never claim full L2.",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_monitor",
            "description": "Run desk monitor/launchpad: crash, heat, alerts, scoreboard cuts, firewall denials, overnight.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eve_desk_brief",
            "description": (
                "Full E-ve desk brief in one shot: regime, top signals, crash, "
                "scoreboard keep/cut, overnight notes, optional symbol news. "
                "Always identify as E-ve. Not Bloomberg news."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Optional symbol for nested news brief"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "portfolio_risk_snapshot",
            "description": (
                "Paper portfolio risk: exposure vs cash, concentration by ticker, "
                "open brackets / working exits. Not live audited."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_bars",
            "description": "OHLCV bars for pro candle charts (1d/1h/15m/5m) with VWAP when computable. Not L2.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "interval": {"type": "string", "enum": ["1d", "1h", "15m", "5m"], "default": "1d"},
                    "limit": {"type": "integer", "default": 120},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tape",
            "description": "Tape lite — recent prints if available; else honest empty. Not full exchange Time & Sales.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "limit": {"type": "integer", "default": 40},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ladder_quote",
            "description": "NBBO top-of-book price ladder centered on mid. Caption: not full exchange depth.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "levels": {"type": "integer", "default": 8},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_custom_scan",
            "description": "Pro scanner builder filters: min volume, % change, RS, news tilt, strategy, region, price range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_volume_ratio": {"type": "number"},
                    "min_pct_change": {"type": "number"},
                    "news_tilt": {"type": "string"},
                    "strategy_id": {"type": "string"},
                    "region": {"type": "string"},
                    "price_min": {"type": "number"},
                    "price_max": {"type": "number"},
                    "limit": {"type": "integer", "default": 30},
                    "refresh": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_economic_calendar",
            "description": "Curated economic calendar for Dashboard rail (CPI, FOMC, NFP approx).",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "default": 21},
                    "limit": {"type": "integer", "default": 20},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "paper_option_order",
            "description": (
                "Open a PAPER long call or put (educational simulator). Goes through policy firewall. "
                "Never live options. origin=paper_options."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "side": {"type": "string", "enum": ["call", "put"]},
                    "contracts": {"type": "integer", "default": 1},
                    "thesis": {"type": "string"},
                },
                "required": ["ticker", "side"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "paper_this_order",
            "description": (
                "Submit a PAPER order for a ticker (educational). Always goes through "
                "the hard policy firewall — cannot bypass session/risk/circuit checks. "
                "Not live trading."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "shares": {"type": "integer", "description": "Share count (positive)"},
                    "entry": {"type": "number", "description": "Optional limit/entry price"},
                    "strategy_id": {"type": "string", "description": "Optional strategy tag"},
                },
                "required": ["ticker", "shares"],
                "additionalProperties": False,
            },
        },
    },
]


def _safe(obj: Any) -> Any:
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
    from .security import redact_obj

    return redact_obj(d, list_cap=40)


def _compact_signal(s: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "ticker", "momentum_pct", "forward_probability", "forward_confidence",
        "forward_pass", "entry", "stop", "take_profit", "shares", "source",
        "strategy_id", "sector",
    )
    return {k: s.get(k) for k in keys if k in s or k in ("ticker", "strategy_id")}


def build_strategy_plan() -> Dict[str, Any]:
    """Call strategies.router (feature-detect) and return compact plan."""
    out: Dict[str, Any] = {"ok": False}
    try:
        from .config import get_runtime_config
        from .strategies import (
            explain_choice,
            get_last_router_decision,
            list_strategies,
            route_strategies,
        )

        cfg = get_runtime_config()
        regime = None
        try:
            from .optimization import get_last_regime

            regime = get_last_regime()
        except Exception:
            regime = None

        decision = get_last_router_decision()
        if decision is None:
            try:
                decision = route_strategies(cfg, regime=_safe(regime) or regime)
            except TypeError:
                decision = route_strategies(cfg, regime=regime)

        enabled = getattr(cfg, "strategy_enabled", None) or {}
        plugins = list_strategies() if callable(list_strategies) else []
        active = list(getattr(decision, "active", None) or [])
        weights = dict(getattr(decision, "weights", None) or {})
        reasons = {}
        for sid in active[:12]:
            try:
                reasons[sid] = explain_choice(sid, decision)
            except Exception:
                reasons[sid] = (getattr(decision, "reasons", {}) or {}).get(sid, "")

        out = {
            "ok": True,
            "mode": getattr(decision, "mode", getattr(cfg, "router_mode", "auto")),
            "regime_label": getattr(decision, "regime_label", None),
            "trend": getattr(decision, "trend", None),
            "vol_regime": getattr(decision, "vol_regime", None),
            "active": active,
            "weights": {k: weights[k] for k in list(weights)[:16]},
            "reasons": reasons,
            "enabled": enabled,
            "plugins": [
                {"id": p.get("id"), "name": p.get("name"), "overlay": p.get("is_overlay")}
                for p in plugins
                if isinstance(p, dict)
            ],
        }
        try:
            from .strategies.runner import get_last_cycle

            cycle = get_last_cycle() or {}
            out["last_fired"] = cycle.get("fired") or []
        except Exception:
            out["last_fired"] = []
    except Exception as e:
        out = {"ok": False, "error": f"strategies unavailable: {type(e).__name__}"}
    return out


def execute_tool(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run one tool; always returns a JSON-serializable dict."""
    args = arguments if isinstance(arguments, dict) else {}
    name = (name or "").strip()

    try:
        if name == "get_regime":
            try:
                from .optimization import get_last_regime

                return {"regime": _safe(get_last_regime())}
            except Exception as e:
                return {"regime": None, "error": str(e)[:120]}

        if name == "get_session":
            from .config import get_runtime_config
            from .timezone_util import get_session, get_ticker_session, exchange_for_ticker

            cfg = get_runtime_config()
            ticker = str(args.get("ticker") or "").strip()
            if ticker:
                sess = get_ticker_session(
                    ticker,
                    user_tz=getattr(cfg, "user_timezone", "America/Chicago"),
                    default_exchange=getattr(cfg, "market_exchange", "NYSE"),
                )
                return {
                    "session": _safe(sess),
                    "resolved_exchange": exchange_for_ticker(ticker),
                }
            sess = get_session(
                exchange=getattr(cfg, "market_exchange", "NYSE"),
                user_tz=getattr(cfg, "user_timezone", "America/Chicago"),
            )
            return {"session": _safe(sess)}

        if name == "get_top_signals":
            from .scanner import get_cached_signals

            limit = int(args.get("limit") or 5)
            limit = max(1, min(15, limit))
            raw = get_cached_signals() or []
            signals = []
            for s in raw[:limit]:
                d = _safe(s)
                if isinstance(d, dict):
                    signals.append(_compact_signal(d))
            return {"count": len(raw), "signals": signals}

        if name == "get_signal":
            from .scanner import get_cached_signals

            ticker = str(args.get("ticker") or "").upper().replace(".", "-")
            for s in get_cached_signals() or []:
                d = _safe(s)
                if isinstance(d, dict) and str(d.get("ticker", "")).upper() == ticker:
                    return {"found": True, "signal": _compact_signal(d)}
            return {"found": False, "ticker": ticker}

        if name == "get_portfolio_paper":
            from . import paper as paper_mod

            try:
                p = paper_mod.mark_to_market()
            except Exception:
                p = _safe(paper_mod.load_portfolio()) or {}
            if not isinstance(p, dict):
                p = _safe(p) or {}
            positions = p.get("open_positions") or p.get("positions") or []
            compact_pos = []
            if isinstance(positions, list):
                for pos in positions[:12]:
                    if isinstance(pos, dict):
                        compact_pos.append(
                            {
                                k: pos.get(k)
                                for k in (
                                    "id", "ticker", "shares", "entry", "strategy_id",
                                    "unrealized_pnl", "status",
                                )
                                if k in pos or k in ("ticker", "shares")
                            }
                        )
            return {
                "mode": p.get("mode", "paper"),
                "cash": p.get("cash"),
                "equity": p.get("equity"),
                "realized_pnl": p.get("realized_pnl"),
                "unrealized_pnl": p.get("unrealized_pnl"),
                "total_fees_paid": p.get("total_fees_paid"),
                "open_count": len(compact_pos),
                "positions": compact_pos,
            }

        if name == "get_watchlist":
            from .watchlist import load_watchlist

            wl = load_watchlist() or []
            return {"watchlist": list(wl)[:80], "count": len(wl)}

        if name == "get_news_eod":
            from .news import build_eod_digest

            dig = build_eod_digest() or {}
            # Compact
            headlines = dig.get("top_headlines") or dig.get("headlines") or []
            if isinstance(headlines, list):
                headlines = headlines[:6]
            return {
                "tilt": dig.get("tilt") or dig.get("summary") or dig.get("news_tilt"),
                "top_headlines": headlines,
                "sector_impacts": (dig.get("sector_impacts") or dig.get("sectors") or [])[:8],
                "ticker_mentions": (dig.get("ticker_mentions") or [])[:10],
                "generated_at": dig.get("generated_at"),
            }

        if name == "get_news_ticker":
            from .news import aggregate_ticker_news, collect_news

            ticker = str(args.get("ticker") or "").upper().replace(".", "-")
            items = collect_news(tickers=[ticker], use_cache=True)
            agg = aggregate_ticker_news(items, ticker)
            d = agg.to_dict() if hasattr(agg, "to_dict") else _safe(agg)
            if isinstance(d, dict) and isinstance(d.get("headlines"), list):
                d["headlines"] = d["headlines"][:5]
            return {"ticker": ticker, "news": d}

        if name == "get_currency":
            from .currency import get_currency_quotes

            q = get_currency_quotes() or {}
            quotes = q.get("quotes") or q.get("pairs") or q
            if isinstance(quotes, list):
                compact = []
                for row in quotes[:12]:
                    if isinstance(row, dict):
                        compact.append(
                            {
                                k: row.get(k)
                                for k in ("pair", "symbol", "price", "change_pct", "name")
                                if k in row
                            }
                        )
                return {"quotes": compact, "note": q.get("session_note") or q.get("note")}
            return {"quotes": _redact(q)}

        if name == "get_strategy_plan":
            return build_strategy_plan()

        if name == "get_recent_performance":
            from .learning import learning_stats

            st = learning_stats() or {}
            keys = (
                "journal_count", "journal_count_paper", "journal_count_external",
                "wins", "win_rate", "unlearned",
                "gross_return_pct", "net_return_pct", "total_fees_paid",
                "fee_impact", "evolved_vs_baseline", "historical_baseline",
                "by_origin",
            )
            out = {k: st.get(k) for k in keys if k in st}
            try:
                from .external_trades import learning_stats_by_origin
                out["by_origin"] = learning_stats_by_origin()
            except Exception:
                pass
            return out

        if name == "get_external_learning_stats":
            try:
                from .external_trades import learning_stats_by_origin, load_import_meta, feature_info
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc), "available": False}
            return {
                "ok": True,
                "available": True,
                "stats": learning_stats_by_origin(),
                "last_import": load_import_meta().get("last_import"),
                "feature": feature_info(),
                "note": "Import via POST /trades/import — learning only, no live trading.",
            }

        if name == "get_config_summary":
            from .config import SEED_DEFAULTS, get_runtime_config

            cfg = get_runtime_config()
            d = _redact(cfg.to_dict() if hasattr(cfg, "to_dict") else {})
            keep = (
                "lookback_days", "volume_multiple", "stop_loss_pct", "take_profit_pct",
                "risk_per_trade", "max_position_pct", "use_forward_estimate", "use_ensemble",
                "use_regime_filter", "use_news_sentiment", "use_currency_panel",
                "router_mode", "strategy_enabled", "fees_enabled", "commission_mode",
                "slippage_pct", "realtime_sip_enabled", "user_timezone", "market_exchange",
                "auto_trade_enabled", "auto_learn_enabled", "copilot_tools_enabled",
                "copilot_memory_enabled", "copilot_max_tool_rounds",
                "copilot_web_enabled", "copilot_web_crypto_enabled", "copilot_web_rate_limit",
            )
            return {
                "config": {k: d.get(k) for k in keep if k in d},
                "seed_keys": list(SEED_DEFAULTS.keys())[:20],
            }

        if name == "get_memory":
            from .copilot_memory import compact_memory

            return compact_memory()

        if name == "remember_fact":
            from .copilot_memory import remember_fact

            text = str(args.get("text") or "").strip()
            return {"ok": True, "memory": remember_fact(text)}

        if name == "get_recent_decisions":
            from .decision_audit import recent_decisions_summary
            lim = int(args.get("limit") or 10)
            return recent_decisions_summary(limit=lim)

        if name == "paper_this_order":
            from . import paper as paper_mod
            from .config import get_runtime_config
            from .policy_firewall import FirewallDenied
            from .timezone_util import should_allow_new_entry
            from .crash_mode import get_crash_status, entry_allowed_for_strategy

            cfg = get_runtime_config()
            ticker = str(args.get("ticker") or "").strip().upper()
            shares = int(args.get("shares") or 0)
            entry = args.get("entry")
            strategy_id = str(args.get("strategy_id") or "momentum")
            if not ticker or shares <= 0:
                return {"ok": False, "error": "ticker and positive shares required"}

            allow_sess, sess_reason, _ = should_allow_new_entry(ticker, cfg)
            crash = get_crash_status(cfg)
            ok_crash, crash_reason = entry_allowed_for_strategy(strategy_id, cfg)
            cite = {
                "strategy_id": strategy_id,
                "session_gate": {"allowed": allow_sess, "reason": sess_reason},
                "crash_mode": crash.to_dict(),
            }
            if not allow_sess:
                return {
                    "ok": False,
                    "error": "session_gate",
                    "reason": sess_reason,
                    **cite,
                    "note": f"Propose cites strategy_id={strategy_id}; session blocked.",
                }
            if not ok_crash:
                return {
                    "ok": False,
                    "error": "crash_mode",
                    "reason": crash_reason,
                    **cite,
                    "note": f"Propose cites strategy_id={strategy_id}; crash mode blocked.",
                }
            try:
                fill = paper_mod.place_order(
                    ticker=ticker,
                    shares=shares,
                    entry=float(entry) if entry is not None else None,
                    source="copilot",
                    cfg=cfg,
                    strategy_id=strategy_id,
                )
                try:
                    if getattr(cfg, "decision_audit_enabled", True):
                        from .decision_audit import log_decision_cycle
                        from .strategies import get_last_router_decision
                        from .optimization import get_last_regime
                        log_decision_cycle(
                            source="copilot",
                            regime=get_last_regime(),
                            crash_mode=crash,
                            router_decision=get_last_router_decision(),
                            strategy_id=strategy_id,
                            firewall=fill.get("firewall") or {"allowed": True},
                            order_id=fill.get("id"),
                            ticker=ticker,
                            session_gate=cite["session_gate"],
                        )
                except Exception:
                    pass
                return {
                    "ok": True,
                    "mode": "paper",
                    "fill": {
                        "id": fill.get("id"),
                        "ticker": fill.get("ticker"),
                        "shares": fill.get("shares"),
                        "entry": fill.get("entry"),
                        "strategy_id": fill.get("strategy_id") or strategy_id,
                        "firewall": fill.get("firewall"),
                    },
                    **cite,
                    "note": (
                        f"Paper fill only; firewall enforced. "
                        f"Cited strategy_id={strategy_id}; session OK. Not live."
                    ),
                }
            except FirewallDenied as e:
                try:
                    if getattr(cfg, "decision_audit_enabled", True):
                        from .decision_audit import log_decision_cycle
                        from .strategies import get_last_router_decision
                        from .optimization import get_last_regime
                        log_decision_cycle(
                            source="copilot",
                            regime=get_last_regime(),
                            crash_mode=crash,
                            router_decision=get_last_router_decision(),
                            strategy_id=strategy_id,
                            firewall=e.result,
                            skip_reason=f"firewall:{e.result.code}:{e.result.reason}",
                            ticker=ticker,
                            session_gate=cite["session_gate"],
                        )
                except Exception:
                    pass
                return {
                    "ok": False,
                    "error": "firewall_denied",
                    "code": e.result.code,
                    "reason": e.result.reason,
                    "firewall": e.result.to_dict(),
                    **cite,
                    "note": (
                        f"Firewall denied ({e.result.code}): {e.result.reason}. "
                        f"Cited strategy_id={strategy_id}."
                    ),
                }
            except ValueError as e:
                return {"ok": False, "error": str(e), **cite}


        if name == "get_crash_mode":
            try:
                from .crash_mode import get_crash_status
                from .config import get_runtime_config
                st = get_crash_status(get_runtime_config())
                d = st.to_dict() if hasattr(st, "to_dict") else _safe(st)
                return {"ok": True, "crash_mode": d}
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "get_scoreboard":
            try:
                from .scoreboard import build_scoreboard
                board = build_scoreboard()
                # Compact for LLM
                rows = []
                for s in (board.get("strategies") or [])[:12]:
                    if not isinstance(s, dict):
                        continue
                    prim = s.get("primary") or {}
                    rows.append({
                        "strategy_id": s.get("strategy_id") or s.get("id"),
                        "status": s.get("status"),
                        "sample_size": s.get("sample_size") or s.get("trades"),
                        "win_rate": prim.get("win_rate"),
                        "expectancy": prim.get("expectancy"),
                        "router_tilt": s.get("router_tilt"),
                    })
                return {
                    "ok": True,
                    "label": board.get("label"),
                    "sample_counts": board.get("sample_counts"),
                    "strategies": rows,
                    "note": "keep/watch/cut from rolling paper+external journal — not live audited.",
                }
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "get_paper_report":
            try:
                from .scoreboard import build_paper_report
                rep = build_paper_report()
                summary = rep.get("summary") or {}
                return {
                    "ok": True,
                    "label": rep.get("label") or "PAPER",
                    "summary": {
                        k: summary.get(k)
                        for k in (
                            "return_pct", "max_drawdown_pct", "win_rate", "closed_trades",
                            "vs_buy_hold", "sharpe_ish",
                        )
                        if k in summary or k == "vs_buy_hold"
                    } or summary,
                    "note": "Paper report only — external learning fills do not move paper equity.",
                }
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "get_decision_audit":
            try:
                from .decision_audit import recent_decisions_summary
                lim = int(args.get("limit") or 10)
                return recent_decisions_summary(limit=lim)
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "list_strategy_packs":
            try:
                from .strategy_packs import list_packs
                packs = list_packs()
                return {
                    "ok": True,
                    "packs": [
                        {
                            "id": p.get("id"),
                            "name": p.get("name"),
                            "description": (p.get("description") or "")[:160],
                        }
                        for p in packs
                        if isinstance(p, dict)
                    ],
                    "note": "Use preview_strategy_pack before apply_strategy_pack(confirm=true).",
                }
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "preview_strategy_pack":
            try:
                from .strategy_packs import preview_pack
                pack_id = str(args.get("pack_id") or "").strip()
                if not pack_id:
                    return {"ok": False, "error": "pack_id required"}
                return preview_pack(pack_id)
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "apply_strategy_pack":
            try:
                from .strategy_packs import preview_pack, apply_pack
                pack_id = str(args.get("pack_id") or "").strip()
                confirm = bool(args.get("confirm"))
                if not pack_id:
                    return {"ok": False, "error": "pack_id required"}
                if not confirm:
                    prev = preview_pack(pack_id)
                    prev["applied"] = False
                    prev["note"] = (
                        "Dry-run only. Re-call apply_strategy_pack with confirm=true "
                        "after explicit user confirmation. Does not unlock live."
                    )
                    return prev
                result = apply_pack(pack_id)
                if isinstance(result, dict):
                    result["applied"] = bool(result.get("ok", True))
                    result.setdefault(
                        "note",
                        "Pack applied to paper strategy toggles — live trading unchanged.",
                    )
                return result
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "get_scan_status":
            try:
                from .scanner import get_scan_status
                return {"ok": True, "scan_status": get_scan_status()}
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "get_session_for_ticker":
            try:
                from .timezone_util import get_ticker_session
                from .config import get_runtime_config
                ticker = str(args.get("ticker") or "").strip().upper()
                if not ticker:
                    return {"ok": False, "error": "ticker required"}
                cfg = get_runtime_config()
                user_tz = getattr(cfg, "user_timezone", None) or getattr(cfg, "user_tz", None) or "America/Chicago"
                sess = get_ticker_session(ticker, user_tz=user_tz)
                return {
                    "ok": True,
                    "ticker": ticker,
                    "session": sess.to_dict() if hasattr(sess, "to_dict") else _safe(sess),
                }
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "get_firewall_status":
            try:
                from .policy_firewall import status as fw_status
                return {"ok": True, "firewall": fw_status()}
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if name == "get_external_trades":
            try:
                from .external_trades import load_external_trades, load_import_meta, learning_stats_by_origin
                lim = int(args.get("limit") or 20)
                rows = load_external_trades(limit=lim)
                compact = []
                for e in rows[:lim]:
                    if not isinstance(e, dict):
                        continue
                    compact.append({
                        k: e.get(k)
                        for k in (
                            "id", "ticker", "shares", "entry", "exit", "return_pct",
                            "strategy_id", "origin", "source", "closed_at", "net_pnl",
                            "broker_id", "dedupe_key",
                        )
                        if k in e or k in ("ticker", "origin")
                    })
                return {
                    "ok": True,
                    "count": len(compact),
                    "trades": compact,
                    "stats": learning_stats_by_origin().get("external"),
                    "last_import": load_import_meta().get("last_import"),
                    "note": "External fills are learning-only; never auto-trade live.",
                }
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}



        if name == "web_search_finance":
            from .copilot_web import web_search_finance, web_enabled
            if not web_enabled():
                return {
                    "ok": False,
                    "error": "copilot_web_disabled",
                    "hint": "Set copilot_web_enabled=0 is active — enable with =1 or COPILOT_WEB_ENABLED=1.",
                }
            q = str(args.get("query") or "").strip()
            max_sources = int(args.get("max_sources") or 3)
            return _redact(web_search_finance(q, max_sources=max_sources))

        if name == "web_fetch_url":
            from .copilot_web import fetch_url, web_enabled, append_web_learning
            if not web_enabled():
                return {"ok": False, "error": "copilot_web_disabled"}
            url = str(args.get("url") or "").strip()
            out = fetch_url(url)
            # Auto-path: distill short notes after useful allowlisted fetches
            if isinstance(out, dict) and out.get("ok") and len(str(out.get("text") or "")) >= 120:
                try:
                    host = str(out.get("host") or "")
                    snippet = str(out.get("text") or "")[:500]
                    topic = host or "web_fetch"
                    append_web_learning(
                        topic,
                        snippet,
                        urls=[str(out.get("url") or url)],
                        tags=["web", "fetch", "auto"],
                    )
                    out = dict(out)
                    out["learned"] = True
                except Exception:
                    pass
            # Cap text for LLM tool payload
            if isinstance(out, dict) and isinstance(out.get("text"), str) and len(out["text"]) > 3500:
                out = dict(out)
                out["text"] = out["text"][:3500] + " …[truncated]"
            return _redact(out)

        if name == "learn_from_web":
            from .copilot_web import learn_from_web, web_enabled
            if not web_enabled():
                return {"ok": False, "error": "copilot_web_disabled"}
            topic = str(args.get("topic") or "").strip()
            max_sources = int(args.get("max_sources") or 3)
            return _redact(learn_from_web(topic, max_sources=max_sources))

        if name == "get_web_learning":
            from .copilot_web import query_web_learning
            topic = str(args.get("topic") or "").strip()
            lim = int(args.get("limit") or 8)
            return _redact(query_web_learning(topic, limit=lim))



        if name == "run_daily_self_critique":
            from .edge import load_daily_self_critique, run_daily_self_critique
            fresh = args.get("fresh", True)
            if fresh is False or str(fresh).lower() in ("0", "false", "no"):
                return _redact(load_daily_self_critique())
            return _redact(run_daily_self_critique(persist=True))

        if name == "get_edge_status":
            from .edge import build_edge_status_logged
            return _redact(build_edge_status_logged())

        if name == "get_competitive_gaps":
            from .edge import competitive_gaps
            return _redact(competitive_gaps())

        if name == "get_feed_health":
            from .edge import feed_health
            return _redact(feed_health())

        if name == "propose_next_improvements":
            from .edge import propose_next_improvements
            lim = int(args.get("limit") or 8)
            return _redact(propose_next_improvements(limit=lim))

        if name == "get_overnight_research":
            from .edge import overnight_research_summary
            lim = int(args.get("limit") or 8)
            return _redact(overnight_research_summary(limit=lim))

        if name == "get_quotes":
            from .quotes import build_quotes
            raw = str(args.get("symbols") or "").strip()
            syms = [s.strip() for s in raw.split(",") if s.strip()] or None
            lim = int(args.get("limit") or 20)
            return _redact(build_quotes(syms, limit=lim))


        if name == "desk_command_help":
            from .desk import command_help
            return command_help()
        if name == "summarize_panel":
            from .desk import summarize_panel
            return _redact(summarize_panel(str(args.get("panel_id") or ""), symbol=args.get("symbol")))
        if name == "brief_news":
            from .desk import build_desk_brief
            return _redact(build_desk_brief(str(args.get("symbol") or "")))
        if name == "explain_ladder":
            from .desk import explain_ladder
            return _redact(explain_ladder(str(args.get("symbol") or "")))
        if name == "run_monitor":
            from .desk import build_desk_monitor
            return _redact(build_desk_monitor())
        if name == "eve_desk_brief":
            from .desk import build_eve_desk_brief
            sym = args.get("symbol")
            return _redact(build_eve_desk_brief(str(sym) if sym else None))
        if name == "portfolio_risk_snapshot":
            from .desk import portfolio_risk_snapshot
            return _redact(portfolio_risk_snapshot())

        if name == "get_bars":
            from .bars import get_bars
            return get_bars(
                str(args.get("symbol") or ""),
                interval=str(args.get("interval") or "1d"),
                limit=int(args.get("limit") or 120),
            )
        if name == "get_tape":
            from .tape import get_tape
            return get_tape(str(args.get("symbol") or ""), limit=int(args.get("limit") or 40))
        if name == "get_ladder_quote":
            from .ladder import build_ladder
            return build_ladder(str(args.get("symbol") or ""), levels=int(args.get("levels") or 8))
        if name == "run_custom_scan":
            from .scan_custom import run_custom_scan
            filt = {k: v for k, v in args.items() if k != "refresh" and v is not None}
            return run_custom_scan(filt, refresh=bool(args.get("refresh")))
        if name == "get_economic_calendar":
            from .calendar_econ import get_economic_calendar
            return get_economic_calendar(
                days=int(args.get("days") or 21),
                limit=int(args.get("limit") or 20),
            )
        if name == "paper_option_order":
            from .paper_options import open_paper_option
            from .config import get_runtime_config
            from .policy_firewall import FirewallDenied
            try:
                return _redact(open_paper_option(
                    str(args.get("ticker") or ""),
                    str(args.get("side") or ""),
                    contracts=int(args.get("contracts") or 1),
                    thesis=str(args.get("thesis") or ""),
                    cfg=get_runtime_config(),
                ))
            except FirewallDenied as e:
                return {"ok": False, "error": "firewall_denied", "firewall": e.result.to_dict(), "live_options": False}

        return {"error": f"unknown tool: {name}"}
    except Exception as e:
        return {"error": f"{name} failed: {type(e).__name__}: {str(e)[:160]}"}


def tools_json_dumps(payload: Any) -> str:
    return json.dumps(payload, default=str)[:4000]

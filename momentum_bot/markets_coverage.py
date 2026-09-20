"""
Honest market coverage — what GAMMA-R supports now vs Phase 2.

Closes the trust gap vs SaaS that imply options/futures without shipping them.
"""

from __future__ import annotations

from typing import Any, Dict, List


def markets_coverage(cfg: Any = None) -> Dict[str, Any]:
    options_ro = False
    try:
        if cfg is None:
            from .config import get_runtime_config
            cfg = get_runtime_config()
        options_ro = bool(getattr(cfg, "options_read_only", False))
    except Exception:
        options_ro = False

    supported: List[Dict[str, Any]] = [
        {
            "asset_class": "us_equities",
            "status": "supported",
            "phase": 1,
            "mode": "trading",
            "notes": "S&P 500 ∪ Nasdaq-100 core; paper + optional live broker gate.",
        },
        {
            "asset_class": "canada_equities",
            "status": "supported",
            "phase": 1,
            "mode": "trading",
            "notes": "TSX 60 (.TO) with per-ticker session gates.",
        },
        {
            "asset_class": "uk_equities",
            "status": "supported",
            "phase": 1,
            "mode": "trading",
            "notes": "FTSE 100 (.L) with LSE session gates.",
        },
        {
            "asset_class": "europe_equities",
            "status": "supported",
            "phase": 1,
            "mode": "trading",
            "notes": "EURO STOXX 50 names; home-exchange sessions.",
        },
        {
            "asset_class": "fx_spot_info",
            "status": "supported_informational",
            "phase": 1,
            "mode": "research",
            "notes": "Major FX panel + fx_mean_reversion strategy (paper context).",
        },
    ]

    if options_ro:
        supported.append({
            "asset_class": "equity_options",
            "status": "read_only_research",
            "phase": 2,
            "mode": "research",
            "notes": (
                "Read-only options: nearest expiries, ATM IV, put/call volume via "
                "GET /options/{ticker}; paper idea journal (thesis only). No options order routing."
            ),
        })

    not_yet: List[Dict[str, Any]] = []
    if not options_ro:
        not_yet.append({
            "asset_class": "equity_options",
            "status": "phase_2_foothold",
            "phase": 2,
            "mode": "research_flag_off",
            "notes": (
                "Enable options_read_only for research sketches. "
                "No options chain trading / Greeks / order path yet."
            ),
        })
    else:
        not_yet.append({
            "asset_class": "equity_options_trading",
            "status": "phase_2",
            "phase": 2,
            "mode": "trading",
            "notes": "Options order routing, full chains, and Greeks trading — not built.",
        })

    not_yet.extend([
        {
            "asset_class": "index_options",
            "status": "phase_2",
            "phase": 2,
            "mode": "trading",
            "notes": "Roadmap only — not tradeable in v1.",
        },
        {
            "asset_class": "futures",
            "status": "phase_2",
            "phase": 2,
            "mode": "trading",
            "notes": "No futures data or order routing in v1.",
        },
        {
            "asset_class": "crypto",
            "status": "not_planned_v1",
            "phase": None,
            "mode": None,
            "notes": "Out of scope for GAMMA-R equity/FX focus.",
        },
    ])

    return {
        "product": "GAMMA-R",
        "phase": 1,
        "phase_2_started": (["options_read_only", "options_idea_journal"] if options_ro else []),
        "summary": (
            "Phase 1 = equities (multi-region) + FX info/paper. "
            "Options: read-only research foothold when options_read_only=true; "
            "full options trading still Phase 2."
        ),
        "supported": supported,
        "not_yet": not_yet,
        "modes": {
            "trading": "Equities paper (+ optional live broker gate). No options/futures orders.",
            "research": "Read-only sketches (options IV / FX panel) — not order routing.",
        },
        "roadmap_note": (
            "Options trading / futures remain Phase 2. Read-only options research is an "
            "optional foothold behind options_read_only — we do not pretend to trade derivatives."
        ),
        "options_read_only": options_ro,
        "options_idea_journal": True,
        "options_order_routing": False,
        "paper_options_simulator": True,
        "paper_options_note": "Educational long call/put sim (origin=paper_options); never live options routing.",
        "trading_default": "paper",
        "live_unlocked_by_default": False,
    }

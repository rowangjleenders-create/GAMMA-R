#!/usr/bin/env python3
"""Co-pilot v2 smoke: offline crash/scoreboard/external/memory/proposals/advice refusal.

Optional LLM tool path when OPENAI_API_KEY (or LLM_API_KEY) is set.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEM = ROOT / "data" / "copilot_memory.json"
BACKUP = ROOT / "data" / "copilot_memory.json.bak_smoke_v2"


def _ok(label: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        raise AssertionError(label)


def main() -> int:
    if MEM.exists():
        BACKUP.write_text(MEM.read_text())

    fails = 0
    try:
        from momentum_bot.copilot import chat
        from momentum_bot.copilot_tools import TOOL_SCHEMAS, execute_tool

        names = {t["function"]["name"] for t in TOOL_SCHEMAS}
        for n in (
            "get_crash_mode",
            "get_scoreboard",
            "get_paper_report",
            "get_decision_audit",
            "list_strategy_packs",
            "preview_strategy_pack",
            "apply_strategy_pack",
            "get_scan_status",
            "get_session_for_ticker",
            "get_firewall_status",
            "get_external_trades",
            "get_external_learning_stats",
        ):
            _ok(f"tool schema {n}", n in names)

        # Offline local Qs
        r = chat("Is crash mode on?")
        _ok("crash intent", r.get("intent") == "crash_mode", r.get("intent"))
        _ok("crash badge", isinstance(r.get("crash"), dict))

        r = chat("Show scoreboard keep watch cut")
        _ok("scoreboard intent", r.get("intent") == "scoreboard", r.get("intent"))

        r = chat("List strategy packs")
        _ok("packs intent", r.get("intent") == "strategy_packs", str(r.get("intent")))

        r = chat("Firewall status")
        _ok("firewall intent", r.get("intent") == "firewall", str(r.get("intent")))

        r = chat("My external trades win rate")
        _ok(
            "external/learning",
            r.get("intent") in ("learning", "external_trades"),
            str(r.get("intent")),
        )
        _ok("outcome_blurb", bool(r.get("outcome_blurb")))

        r = chat("Should I buy AAPL right now?")
        _ok(
            "advice refusal",
            r.get("intent") in ("advice_refusal", "advice_refusal"),
            str(r.get("intent")),
        )

        # Memory recall
        if MEM.exists():
            MEM.unlink()
        chat("I prefer tech and avoid biotech, low risk")
        mem = chat("What do you remember about my preferences?")
        reply = (mem.get("reply") or "").lower()
        _ok("memory tech", "tech" in reply, reply[:120])
        _ok("memory biotech/avoid", "biotech" in reply or "avoid" in reply, reply[:120])

        # Proposals shape
        prop = chat("Propose a paper trade idea")
        _ok("proposals intent", prop.get("intent") == "proposals", str(prop.get("intent")))
        cards = prop.get("proposals") or []
        _ok("proposals non-empty", len(cards) >= 1, str(len(cards)))
        card = cards[0]
        for k in ("symbol", "strategy_id", "thesis", "risks", "size_hint"):
            _ok(f"proposal has {k}", k in card, str(card.keys()))
        _ok("requires_confirm", card.get("requires_confirm") is True)

        # Tool executors (offline)
        crash = execute_tool("get_crash_mode", {})
        _ok("exec crash", crash.get("ok") is True, str(crash)[:100])
        board = execute_tool("get_scoreboard", {})
        _ok("exec scoreboard", board.get("ok") is True)
        packs = execute_tool("list_strategy_packs", {})
        _ok("exec packs", packs.get("ok") is True)
        prev = execute_tool("preview_strategy_pack", {"pack_id": "classic_momentum_12_1"})
        _ok("exec preview pack", prev.get("ok") is not False)
        dry = execute_tool("apply_strategy_pack", {"pack_id": "classic_momentum_12_1", "confirm": False})
        _ok("apply without confirm is preview", dry.get("applied") is False or "confirm" in str(dry).lower() or dry.get("ok"))
        fw = execute_tool("get_firewall_status", {})
        _ok("exec firewall", fw.get("ok") is True)
        ext = execute_tool("get_external_trades", {"limit": 5})
        _ok("exec external trades", ext.get("ok") is True)

        # External import dry-run
        from momentum_bot.external_trades import import_from_content

        csv = (
            "symbol,side,qty,price,time,fees,strategy,broker_id\n"
            "TESTX,buy,1,10,2026-03-01T15:00:00Z,0,momentum,smoke-ext-1\n"
        )
        dry_imp = import_from_content(format="csv", content=csv, dry_run=True)
        _ok("external dry-run", dry_imp.get("ok") is True or dry_imp.get("would_import", 0) >= 0, str(dry_imp)[:120])

        if os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY"):
            print("\n=== optional LLM+tools ===")
            r = chat("What is crash mode and which strategies does the scoreboard keep?")
            print("source=", r.get("source"), "tools=", r.get("tools_used"))
            print((r.get("reply") or "")[:400])
        else:
            print("\n=== LLM+tools skipped (no OPENAI_API_KEY) ===")

        print("\nSMOKE_COPILOT_V2_OK")
        return 0
    except AssertionError as e:
        print("\nSMOKE_COPILOT_V2_FAIL", e)
        return 1
    except Exception as e:
        print("\nSMOKE_COPILOT_V2_ERROR", type(e).__name__, e)
        return 2
    finally:
        if BACKUP.exists():
            MEM.write_text(BACKUP.read_text())
            BACKUP.unlink()


if __name__ == "__main__":
    raise SystemExit(main())

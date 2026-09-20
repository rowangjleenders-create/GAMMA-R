#!/usr/bin/env python3
"""Smoke test: local co-pilot + memory round-trip (+ optional tool loop if key set)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolate memory file for smoke
MEM = ROOT / "data" / "copilot_memory.json"
BACKUP = ROOT / "data" / "copilot_memory.json.bak_smoke"


def main() -> int:
    if MEM.exists():
        BACKUP.write_text(MEM.read_text())
    elif BACKUP.exists():
        BACKUP.unlink()

    try:
        from momentum_bot.copilot import chat
        from momentum_bot.copilot_tools import build_strategy_plan, execute_tool

        print("=== strategy plan ===")
        plan = build_strategy_plan()
        print(json.dumps({k: plan.get(k) for k in ("ok", "active", "regime_label", "mode")}, default=str))

        print("\n=== local: which strategies ===")
        r1 = chat("Which strategies are active and why?")
        print("source=", r1.get("source"), "intent=", r1.get("intent"))
        print("plan.active=", (r1.get("strategy_plan") or {}).get("active"))
        print((r1.get("reply") or "")[:500])

        print("\n=== local: FX panel ===")
        rfx = chat("Show me the FX panel")
        print("intent=", rfx.get("intent"), "→", (rfx.get("reply") or "")[:280])

        print("\n=== advice refusal ===")
        ref = chat("Should I buy AAPL right now?")
        assert ref.get("intent") == "advice_refusal", ref
        print("ok refusal:", (ref.get("reply") or "")[:120])

        print("\n=== memory round-trip ===")
        if MEM.exists():
            MEM.unlink()
        a = chat("I prefer tech and no biotech, low risk")
        print("call1 source=", a.get("source"), "memory_updated=", a.get("memory_updated"))
        print((a.get("reply") or "")[:240])
        b = chat("What do you remember about my preferences?")
        print("call2 intent=", b.get("intent"))
        reply = (b.get("reply") or "").lower()
        print((b.get("reply") or "")[:360])
        ok_mem = ("tech" in reply) and ("biotech" in reply or "avoid" in reply)
        print("memory_roundtrip=", ok_mem)

        print("\n=== tool execute sample ===")
        print("get_config_summary keys:", list((execute_tool("get_config_summary").get("config") or {}).keys())[:8])
        print("get_memory:", execute_tool("get_memory"))

        if os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY"):
            print("\n=== LLM+tools sample (key present) ===")
            r = chat("What is the current regime and which strategies should be active?")
            print("source=", r.get("source"), "tools_used=", r.get("tools_used"))
            print((r.get("reply") or "")[:500])
        else:
            print("\n=== LLM+tools skipped (no OPENAI_API_KEY) ===")

        print("\nSMOKE_OK" if ok_mem else "\nSMOKE_MEMORY_FAIL")
        return 0 if ok_mem else 1
    finally:
        if BACKUP.exists():
            MEM.write_text(BACKUP.read_text())
            BACKUP.unlink()
        elif MEM.exists() and not BACKUP.exists():
            # leave smoke memory if no prior — or remove for cleanliness
            pass


if __name__ == "__main__":
    raise SystemExit(main())

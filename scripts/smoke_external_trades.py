#!/usr/bin/env python3
"""Smoke test: external trade import → journal → learning-stats (no live trading)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLE = ROOT / "scripts" / "fixtures" / "external_trades_sample.csv"


def main() -> int:
    from momentum_bot import external_trades as et
    from momentum_bot.learning import load_journal, learning_stats, save_journal

    tmp = Path(tempfile.mkdtemp(prefix="gamma_ext_"))
    et.DATA_DIR = tmp
    et.EXTERNAL_MIRROR_PATH = tmp / "external_trades.jsonl"
    et.EXTERNAL_PATH = et.EXTERNAL_MIRROR_PATH
    et.IMPORT_META_PATH = tmp / "external_import_meta.json"

    import momentum_bot.learning as learning
    learning.DATA_DIR = tmp
    learning.JOURNAL_PATH = tmp / "trade_journal.json"
    learning.LEARNED_PATH = tmp / "learned_config.json"
    learning.HISTORY_PATH = tmp / "learning_history.json"
    learning.HISTORICAL_PATH = tmp / "historical_baseline.json"
    save_journal([])

    print("=== parse sample CSV ===")
    assert SAMPLE.exists(), SAMPLE
    content = SAMPLE.read_text()
    parse_fn = getattr(et, "parse_csv_trades", None) or getattr(et, "parse_csv")
    trades, errors = parse_fn(content)
    print(f"fills={len(trades)} errors={errors[:3]}")
    assert len(trades) >= 6, trades

    print("=== dry_run import ===")
    dry = et.import_from_content(format="csv", content=content, dry_run=True)
    print(json.dumps({k: dry.get(k) for k in (
        "ok", "dry_run", "parsed", "would_import", "new_fills", "closed_round_trips",
        "journaled", "duplicate_fills", "live_trading"
    )}, indent=2))
    assert dry.get("ok") and dry.get("dry_run")
    assert dry.get("live_trading") is False
    would = dry.get("would_import") or dry.get("journaled") or dry.get("closed_round_trips") or 0
    assert would >= 3, dry
    assert not et.EXTERNAL_MIRROR_PATH.exists(), "dry_run must not persist mirror"
    assert load_journal() == []

    print("=== confirm import ===")
    real = et.import_from_content(format="csv", content=content, dry_run=False)
    print(json.dumps({k: real.get(k) for k in (
        "ok", "parsed", "imported", "journaled", "new_fills", "closed_round_trips",
        "duplicates", "live_trading"
    )}, indent=2))
    imported = real.get("journaled") or real.get("imported") or 0
    assert imported >= 3, real
    journal = load_journal()
    ext = [e for e in journal if e.get("origin") == "external" or e.get("source") == "external"]
    assert len(ext) >= 3, journal
    # At least one round-trip should have non-zero return (AAPL / NVDA winners)
    nonzero = [e for e in ext if abs(float(e.get("return_pct") or 0)) > 1e-6]
    assert nonzero, f"expected nonzero returns after FIFO pairing: {ext}"

    print("=== dedupe re-import ===")
    again = et.import_from_content(format="csv", content=content, dry_run=False)
    dups = again.get("duplicate_fills") or again.get("duplicates") or 0
    assert dups >= 6, again
    assert (again.get("journaled") or again.get("imported") or 0) == 0

    print("=== JSON closed-trade style ===")
    js = json.dumps([
        {
            "ticker": "SPY",
            "entry_price": 500,
            "exit_price": 510,
            "qty": 3,
            "side": "sell",
            "datetime": "2026-07-10T14:00:00Z",
            "order_id": "ext-spy-closed-1",
            "strategy": "relative_strength",
        }
    ])
    jres = et.import_from_content(format="json", content=js, dry_run=False)
    assert (jres.get("journaled") or jres.get("imported") or 0) == 1, jres

    print("=== learning-stats by origin ===")
    stats = et.learning_stats_by_origin()
    print(json.dumps({
        "paper": stats["paper"]["count"],
        "external": stats["external"]["count"],
        "combined": stats["combined"]["count"],
    }))
    assert stats["external"]["count"] >= 4
    assert stats["paper"]["count"] == 0

    print("=== learning_stats() includes by_origin ===")
    ls = learning_stats()
    assert "by_origin" in ls
    assert ls.get("journal_count_external", 0) >= 4

    print("=== scoreboard includes external; paper equity excludes ===")
    from momentum_bot.scoreboard import build_scoreboard, build_paper_report
    board = build_scoreboard(include_external=True)
    assert board.get("sample_counts", {}).get("external", 0) >= 1
    report = build_paper_report()
    assert report["summary"].get("external_closed_excluded", 0) >= 4

    print("=== feature_info / alpaca absent ===")
    fi = et.feature_info()
    assert fi.get("external_trades_import") is True
    assert fi.get("live_trading_from_import") is False or fi.get("live_from_import") is False
    alp = et.import_from_alpaca(dry_run=True)
    assert alp.get("ok") is False
    assert alp.get("live_trading") is False

    print("=== copilot tool ===")
    from momentum_bot.copilot_tools import execute_tool
    tool = execute_tool("get_external_learning_stats")
    assert tool.get("ok") or tool.get("available") is not False
    print("tool keys:", list(tool.keys())[:8])

    print("\nSMOKE_OK")
    print(f"(temp data dir {tmp})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("SMOKE_FAIL:", exc)
        raise

"""
Paper options simulator (educational).

Open/close simple long call/put positions from the options research chain.
Tracked in the paper journal with origin=paper_options.
Never places live options orders. Firewall size caps apply.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PORTFOLIO_PATH = DATA_DIR / "paper_options_portfolio.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load() -> Dict[str, Any]:
    if not PORTFOLIO_PATH.exists():
        return {"positions": [], "closed": [], "updated_at": _utc_now()}
    try:
        raw = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("positions", [])
            raw.setdefault("closed", [])
            return raw
    except (json.JSONDecodeError, OSError):
        pass
    return {"positions": [], "closed": [], "updated_at": _utc_now()}


def _save(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _utc_now()
    PORTFOLIO_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _estimate_premium(summary: Dict[str, Any], side: str, strike: Optional[float]) -> Optional[float]:
    sketch = summary.get("nearest_sketch") or {}
    rows = sketch.get("calls" if side == "call" else "puts") or []
    if strike is not None:
        for r in rows:
            try:
                if abs(float(r.get("strike") or 0) - float(strike)) < 1e-6 and r.get("last"):
                    return float(r["last"])
            except (TypeError, ValueError):
                continue
    for r in rows:
        if r.get("last"):
            try:
                return float(r["last"])
            except (TypeError, ValueError):
                continue
    # Rough fallback from ATM IV * spot * 0.05 (educational stub)
    spot = summary.get("spot")
    atm_iv = summary.get("atm_iv")
    if spot and atm_iv:
        try:
            return max(0.05, round(float(spot) * float(atm_iv) * 0.05, 4))
        except (TypeError, ValueError):
            pass
    return None


def open_paper_option(
    ticker: str,
    side: str,
    *,
    contracts: int = 1,
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
    premium: Optional[float] = None,
    thesis: str = "",
    cfg: Any = None,
    human_approved: bool = False,
) -> Dict[str, Any]:
    """
    Open a paper long call or put. Educational only — no live broker routing.
    """
    from .config import get_runtime_config
    from .options_research import options_summary, log_options_idea
    from . import policy_firewall as fw
    from .paper import load_portfolio

    cfg = cfg or get_runtime_config()
    t = (ticker or "").strip().upper().replace(".", "-")
    side_n = (side or "").strip().lower()
    if side_n not in ("call", "put"):
        return {"ok": False, "error": "side must be call or put", "live_options": False}
    contracts = max(1, min(20, int(contracts or 1)))
    if not t:
        return {"ok": False, "error": "ticker required", "live_options": False}

    summary = options_summary(t, cfg=cfg)
    exp = expiry or summary.get("nearest_expiry")
    strike_v = strike
    if strike_v is None:
        strike_v = summary.get("atm_strike")
    prem = premium
    if prem is None:
        prem = _estimate_premium(summary, side_n, float(strike_v) if strike_v else None)
    if prem is None or float(prem) <= 0:
        return {
            "ok": False,
            "error": "Could not estimate option premium — enable options_read_only and retry",
            "live_options": False,
            "options_summary": {
                "available": summary.get("available"),
                "stub": summary.get("stub"),
                "note": summary.get("note"),
            },
        }

    # Notional = premium * 100 * contracts (US equity options multiplier)
    notional = float(prem) * 100.0 * contracts
    paper = load_portfolio()
    equity = float(paper.cash)
    for op in paper.positions:
        if op.get("status", "open") == "open":
            equity += float(op.get("entry", 0)) * int(op.get("shares") or 0)

    fw_result = fw.assert_order_allowed(
        ticker=t,
        shares=float(contracts),
        price=float(prem) * 100.0,  # per-contract notional for firewall
        side="buy",
        mode="paper",
        source="paper_options",
        strategy_id="paper_options",
        equity=float(equity),
        cfg=cfg,
        human_approved=human_approved,
    )

    # Debit cash from main paper portfolio for shared risk budget
    if notional > paper.cash + 1e-6:
        return {
            "ok": False,
            "error": f"insufficient paper cash for options premium: need {notional:.2f}, have {paper.cash:.2f}",
            "live_options": False,
            "firewall": fw_result.to_dict() if hasattr(fw_result, "to_dict") else {},
        }

    paper.cash -= notional
    from .paper import save_portfolio
    save_portfolio(paper)

    pos = {
        "id": str(uuid.uuid4())[:8],
        "ticker": t,
        "side": side_n,
        "option_type": side_n,
        "contracts": contracts,
        "strike": round(float(strike_v), 4) if strike_v is not None else None,
        "expiry": exp,
        "premium": round(float(prem), 4),
        "multiplier": 100,
        "notional": round(notional, 2),
        "opened_at": _utc_now(),
        "status": "open",
        "origin": "paper_options",
        "thesis": (thesis or "")[:500],
        "source": "paper_options",
        "strategy_id": "paper_options",
        "live_options": False,
        "order_routing": False,
        "label": "PAPER long option — educational simulator, not live",
        "firewall": {
            "allowed": True,
            "code": fw_result.code,
            "reason": fw_result.reason,
            "notional": fw_result.notional,
        },
    }
    book = _load()
    book["positions"].append(pos)
    _save(book)

    if thesis:
        try:
            log_options_idea(
                t,
                thesis,
                side=side_n,
                expiry=exp,
                strike=float(strike_v) if strike_v is not None else None,
                tags=["paper_options", "sim"],
            )
        except Exception:
            pass

    return {
        "ok": True,
        "position": pos,
        "cash_remaining": round(paper.cash, 2),
        "live_options": False,
        "order_routing": False,
        "label": "PAPER options fill — educational only",
    }


def close_paper_option(
    position_id: str,
    *,
    exit_premium: Optional[float] = None,
    reason: str = "manual",
) -> Dict[str, Any]:
    """Close a paper options position; journal with origin=paper_options."""
    from .paper import load_portfolio, save_portfolio
    from .learning import record_closed_trade
    from .options_research import options_summary

    book = _load()
    idx = None
    for i, p in enumerate(book.get("positions") or []):
        if p.get("id") == position_id and p.get("status", "open") == "open":
            idx = i
            break
    if idx is None:
        return {"ok": False, "error": f"open paper option {position_id} not found", "live_options": False}

    pos = book["positions"][idx]
    prem_exit = exit_premium
    if prem_exit is None:
        try:
            summary = options_summary(pos["ticker"])
            prem_exit = _estimate_premium(summary, pos.get("side") or "call", pos.get("strike"))
        except Exception:
            prem_exit = None
    if prem_exit is None:
        prem_exit = float(pos.get("premium") or 0)

    contracts = int(pos.get("contracts") or 1)
    mult = int(pos.get("multiplier") or 100)
    proceeds = float(prem_exit) * mult * contracts
    entry_cost = float(pos.get("notional") or (float(pos.get("premium") or 0) * mult * contracts))
    pnl = proceeds - entry_cost
    ret_pct = (pnl / entry_cost) if entry_cost else 0.0

    paper = load_portfolio()
    paper.cash += proceeds
    save_portfolio(paper)

    pos["status"] = "closed"
    pos["exit_premium"] = round(float(prem_exit), 4)
    pos["closed_at"] = _utc_now()
    pos["close_reason"] = reason
    pos["realized_pnl"] = round(pnl, 2)
    pos["return_pct"] = round(ret_pct, 6)
    book["closed"].append(pos)
    book["positions"].pop(idx)
    _save(book)

    try:
        record_closed_trade(
            ticker=pos["ticker"],
            entry=float(pos.get("premium") or 0),
            exit=float(prem_exit),
            shares=contracts,
            return_pct=ret_pct,
            exit_reason=reason,
            opened_at=pos.get("opened_at"),
            closed_at=pos.get("closed_at"),
            source="paper_options",
            signal_params={
                "side": pos.get("side"),
                "strike": pos.get("strike"),
                "expiry": pos.get("expiry"),
                "strategy_id": "paper_options",
            },
            position_id=pos.get("id"),
            fees={"gross_pnl": pnl, "net_pnl": pnl, "total_fees": 0},
            context={
                "origin": "paper_options",
                "strategy_id": "paper_options",
                "option_type": pos.get("side"),
                "strike": pos.get("strike"),
                "expiry": pos.get("expiry"),
                "thesis": pos.get("thesis"),
            },
            origin="paper_options",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: paper_options journal failed: {exc}")

    return {
        "ok": True,
        "position": pos,
        "cash_remaining": round(paper.cash, 2),
        "live_options": False,
        "order_routing": False,
    }


def list_paper_options() -> Dict[str, Any]:
    book = _load()
    open_pos = [p for p in (book.get("positions") or []) if p.get("status", "open") == "open"]
    return {
        "ok": True,
        "open": open_pos,
        "closed": list(book.get("closed") or [])[-30:],
        "open_count": len(open_pos),
        "closed_count": len(book.get("closed") or []),
        "live_options": False,
        "order_routing": False,
        "label": "PAPER options simulator — educational, not live brokerage",
        "path": str(PORTFOLIO_PATH),
    }

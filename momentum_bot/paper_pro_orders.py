"""
Paper pro order types — stop, take-profit, bracket, OCO.

Paper only; every path goes through policy_firewall.
Live remains locked by firewall / LIVE_TRADING_ENABLED.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WORKING_PATH = DATA_DIR / "paper_working_orders.json"

ORDER_TYPES = ("market", "limit", "stop", "take_profit", "bracket", "oco")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_working() -> Dict[str, Any]:
    try:
        if WORKING_PATH.exists():
            return json.loads(WORKING_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"orders": [], "updated_at": _utc_now()}


def _save_working(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _utc_now()
    WORKING_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_working_orders() -> Dict[str, Any]:
    data = _load_working()
    open_ones = [o for o in data.get("orders") or [] if o.get("status") == "working"]
    return {
        "ok": True,
        "count": len(open_ones),
        "orders": open_ones,
        "all_count": len(data.get("orders") or []),
        "mode": "paper",
        "live": False,
        "label": "Paper working orders (stop / TP / bracket / OCO) — not live",
        "updated_at": data.get("updated_at"),
    }


def cancel_working_order(order_id: str) -> Dict[str, Any]:
    data = _load_working()
    found = None
    for o in data.get("orders") or []:
        if o.get("id") == order_id and o.get("status") == "working":
            o["status"] = "cancelled"
            o["cancelled_at"] = _utc_now()
            found = o
            # Cancel OCO sibling
            sib = o.get("oco_group")
            if sib:
                for other in data["orders"]:
                    if (
                        other.get("oco_group") == sib
                        and other.get("id") != order_id
                        and other.get("status") == "working"
                    ):
                        other["status"] = "cancelled"
                        other["cancelled_at"] = _utc_now()
                        other["cancel_reason"] = "oco_sibling_cancelled"
            break
    if not found:
        return {"ok": False, "error": "working order not found", "id": order_id}
    _save_working(data)
    return {"ok": True, "order": found, "mode": "paper", "live": False}


def place_pro_order(
    *,
    ticker: str,
    shares: int,
    order_type: str = "market",
    entry: Optional[float] = None,
    stop: Optional[float] = None,
    take_profit: Optional[float] = None,
    trigger_price: Optional[float] = None,
    limit_price: Optional[float] = None,
    source: str = "pro_ui",
    strategy_id: Optional[str] = None,
    human_approved: bool = False,
    cfg: Any = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Paper pro order entrypoint.

    - market / limit / bracket → immediate paper fill via place_order (bracket = entry+stop+tp)
    - stop → working buy-stop until trigger
    - take_profit → working sell at target (requires open position) OR attach tp
    - oco → two linked working exits (stop + target) on an open position, or
            bracket-style entry then OCO exits
    """
    from .config import get_runtime_config
    from . import paper as paper_mod
    from . import policy_firewall as fw

    cfg = cfg or get_runtime_config()
    ot = (order_type or "market").strip().lower().replace("-", "_")
    if ot == "takeprofit":
        ot = "take_profit"
    if ot not in ORDER_TYPES:
        return {
            "ok": False,
            "error": f"order_type must be one of {ORDER_TYPES}",
            "mode": "paper",
            "live": False,
        }

    t = ticker.strip().upper().replace(".", "-")
    if shares <= 0:
        return {"ok": False, "error": "shares must be positive", "mode": "paper", "live": False}

    # Mode must be paper for pro types that aren't simple market (firewall still runs on fill)
    port = paper_mod.load_portfolio()
    if (port.mode or "paper") != "paper" and ot != "market":
        # Still allow but firewall will block live without LIVE_TRADING_ENABLED
        pass

    sid = strategy_id or "momentum"

    if ot in ("market", "limit", "bracket"):
        fill_entry = limit_price if ot == "limit" and limit_price else entry
        try:
            fill = paper_mod.place_order(
                ticker=t,
                shares=int(shares),
                entry=fill_entry,
                stop=stop,
                take_profit=take_profit,
                source=source or f"pro_{ot}",
                cfg=cfg,
                strategy_id=sid,
                human_approved=human_approved,
                context={**(context or {}), "order_type": ot},
            )
            fill["ok"] = True
            fill["order_type"] = ot
            fill["mode"] = "paper"
            fill["live"] = False
            fill["pro"] = True
            if ot == "bracket":
                fill["bracket"] = {
                    "entry": fill.get("entry"),
                    "stop": fill.get("stop"),
                    "take_profit": fill.get("take_profit"),
                }
            return fill
        except fw.FirewallDenied as e:
            return {
                "ok": False,
                "error": "firewall_denied",
                "firewall": e.result.to_dict(),
                "mode": "paper",
                "live": False,
                "order_type": ot,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "mode": "paper", "live": False, "order_type": ot}

    # Working-order types
    if ot == "stop":
        trig = trigger_price or stop or entry
        if trig is None:
            return {"ok": False, "error": "trigger_price (or stop) required for stop order", "order_type": ot}
        # Pre-check firewall with notional
        px = float(trig)
        try:
            fw.assert_order_allowed(
                ticker=t,
                shares=float(shares),
                price=px,
                side="buy",
                mode=port.mode or "paper",
                source=source or "pro_stop",
                strategy_id=sid,
                equity=float(port.cash),
                cfg=cfg,
                human_approved=human_approved,
            )
        except fw.FirewallDenied as e:
            return {
                "ok": False,
                "error": "firewall_denied",
                "firewall": e.result.to_dict(),
                "mode": "paper",
                "live": False,
                "order_type": ot,
            }
        order = {
            "id": str(uuid.uuid4())[:8],
            "order_type": "stop",
            "side": "buy",
            "ticker": t,
            "shares": int(shares),
            "trigger_price": round(px, 4),
            "limit_price": float(limit_price) if limit_price else None,
            "stop": round(float(stop), 4) if stop else None,
            "take_profit": round(float(take_profit), 4) if take_profit else None,
            "status": "working",
            "strategy_id": sid,
            "source": source or "pro_stop",
            "created_at": _utc_now(),
            "mode": "paper",
            "live": False,
        }
        data = _load_working()
        data.setdefault("orders", []).append(order)
        _save_working(data)
        return {"ok": True, "order": order, "mode": "paper", "live": False, "working": True}

    if ot == "take_profit":
        target = take_profit or trigger_price or limit_price
        if target is None:
            return {"ok": False, "error": "take_profit price required", "order_type": ot}
        # Attach to open position if present
        open_pos = [
            p for p in port.positions
            if p.get("status", "open") == "open" and p.get("ticker") == t
        ]
        if open_pos:
            pos = open_pos[0]
            pos["take_profit"] = round(float(target), 4)
            paper_mod.save_portfolio(port)
            return {
                "ok": True,
                "attached": True,
                "position_id": pos.get("id"),
                "take_profit": pos["take_profit"],
                "order_type": ot,
                "mode": "paper",
                "live": False,
            }
        order = {
            "id": str(uuid.uuid4())[:8],
            "order_type": "take_profit",
            "side": "sell",
            "ticker": t,
            "shares": int(shares),
            "trigger_price": round(float(target), 4),
            "status": "working",
            "strategy_id": sid,
            "source": source or "pro_tp",
            "created_at": _utc_now(),
            "mode": "paper",
            "live": False,
            "note": "No open position — working sell TP waits for long then triggers",
        }
        data = _load_working()
        data.setdefault("orders", []).append(order)
        _save_working(data)
        return {"ok": True, "order": order, "mode": "paper", "live": False, "working": True}

    if ot == "oco":
        # Need stop + take_profit; preferably an open position
        if stop is None or take_profit is None:
            return {
                "ok": False,
                "error": "oco requires stop and take_profit",
                "order_type": ot,
            }
        open_pos = [
            p for p in port.positions
            if p.get("status", "open") == "open" and p.get("ticker") == t
        ]
        group = str(uuid.uuid4())[:8]
        if open_pos:
            pos = open_pos[0]
            pos["stop"] = round(float(stop), 4)
            pos["take_profit"] = round(float(take_profit), 4)
            pos["oco_group"] = group
            paper_mod.save_portfolio(port)
        data = _load_working()
        stop_leg = {
            "id": str(uuid.uuid4())[:8],
            "order_type": "oco_stop",
            "side": "sell",
            "ticker": t,
            "shares": int(shares),
            "trigger_price": round(float(stop), 4),
            "status": "working",
            "oco_group": group,
            "position_id": open_pos[0].get("id") if open_pos else None,
            "strategy_id": sid,
            "source": source or "pro_oco",
            "created_at": _utc_now(),
            "mode": "paper",
            "live": False,
        }
        tp_leg = {
            "id": str(uuid.uuid4())[:8],
            "order_type": "oco_take_profit",
            "side": "sell",
            "ticker": t,
            "shares": int(shares),
            "trigger_price": round(float(take_profit), 4),
            "status": "working",
            "oco_group": group,
            "position_id": open_pos[0].get("id") if open_pos else None,
            "strategy_id": sid,
            "source": source or "pro_oco",
            "created_at": _utc_now(),
            "mode": "paper",
            "live": False,
        }
        data.setdefault("orders", []).extend([stop_leg, tp_leg])
        _save_working(data)
        return {
            "ok": True,
            "order_type": "oco",
            "oco_group": group,
            "legs": [stop_leg, tp_leg],
            "position_updated": bool(open_pos),
            "mode": "paper",
            "live": False,
            "note": "OCO paper exits — first trigger cancels sibling (via manage_working_orders)",
        }

    return {"ok": False, "error": f"unhandled order_type {ot}", "mode": "paper", "live": False}


def manage_working_orders(cfg: Any = None) -> Dict[str, Any]:
    """
    Evaluate working stop/OCO/TP vs latest prices. Paper fills go through place_order / close.
    """
    from .config import get_runtime_config
    from . import paper as paper_mod
    from . import policy_firewall as fw

    cfg = cfg or get_runtime_config()
    data = _load_working()
    actions: List[Dict[str, Any]] = []
    changed = False

    for o in list(data.get("orders") or []):
        if o.get("status") != "working":
            continue
        ticker = o.get("ticker")
        try:
            px = paper_mod._latest_price(ticker)  # noqa: SLF001
        except Exception:
            px = None
        if px is None:
            continue
        trig = o.get("trigger_price")
        if trig is None:
            continue
        ot = o.get("order_type")
        side = o.get("side")
        hit = False
        try:
            if side == "buy" and float(px) >= float(trig):
                hit = True
            elif side == "sell" and ot in ("oco_stop", "stop"):
                if float(px) <= float(trig):
                    hit = True
            elif side == "sell" and ot in ("oco_take_profit", "take_profit"):
                if float(px) >= float(trig):
                    hit = True
        except (TypeError, ValueError):
            continue
        if not hit:
            continue

        try:
            if side == "buy":
                fill = paper_mod.place_order(
                    ticker=ticker,
                    shares=int(o.get("shares") or 0),
                    entry=float(px),
                    stop=o.get("stop"),
                    take_profit=o.get("take_profit"),
                    source=o.get("source") or "pro_working_fill",
                    cfg=cfg,
                    strategy_id=o.get("strategy_id") or "momentum",
                    human_approved=True,  # already firewall-checked at submit
                    context={"order_type": ot, "working_id": o.get("id")},
                )
                o["status"] = "filled"
                o["filled_at"] = _utc_now()
                o["fill_price"] = float(px)
                o["fill"] = {"id": fill.get("id"), "entry": fill.get("entry")}
                actions.append({"id": o.get("id"), "action": "buy_fill", "price": px})
            else:
                # Sell exit — close matching position
                port = paper_mod.load_portfolio()
                pos_id = o.get("position_id")
                pos = None
                if pos_id:
                    pos = next((p for p in port.positions if p.get("id") == pos_id), None)
                if pos is None:
                    pos = next(
                        (
                            p for p in port.positions
                            if p.get("status", "open") == "open" and p.get("ticker") == ticker
                        ),
                        None,
                    )
                if pos:
                    closed = paper_mod.close_position(
                        pos["id"],
                        exit_price=float(px),
                        reason=f"pro_{ot}",
                    )
                    o["status"] = "filled"
                    o["filled_at"] = _utc_now()
                    o["fill_price"] = float(px)
                    actions.append({"id": o.get("id"), "action": "sell_fill", "price": px, "closed": closed.get("id") if isinstance(closed, dict) else pos.get("id")})
                else:
                    o["status"] = "expired"
                    o["note"] = "no open position to exit"
                    actions.append({"id": o.get("id"), "action": "expired_no_pos"})

            # Cancel OCO sibling
            group = o.get("oco_group")
            if group:
                for other in data["orders"]:
                    if (
                        other.get("oco_group") == group
                        and other.get("id") != o.get("id")
                        and other.get("status") == "working"
                    ):
                        other["status"] = "cancelled"
                        other["cancelled_at"] = _utc_now()
                        other["cancel_reason"] = "oco_filled"
                        actions.append({"id": other.get("id"), "action": "oco_cancel"})
            changed = True
        except fw.FirewallDenied as e:
            actions.append({"id": o.get("id"), "action": "firewall_denied", "firewall": e.result.to_dict()})
        except Exception as exc:  # noqa: BLE001
            actions.append({"id": o.get("id"), "action": "error", "error": str(exc)})

    if changed:
        _save_working(data)
    return {
        "ok": True,
        "actions": actions,
        "count": len(actions),
        "mode": "paper",
        "live": False,
    }

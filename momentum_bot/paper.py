"""
Paper trading portfolio — simulated fills with fake money.

Persists to data/paper_portfolio.json. Live mode is a stub: never sends
broker orders. Closing a trade journals outcomes for self-learning and
forward-estimate accuracy tracking.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import StrategyConfig, get_runtime_config
from .fees import compute_trade_fees, fee_impact_summary
from .data_sources import get_data_source
from .forward_estimate import adjust_from_prediction_accuracy, record_prediction_outcome
from .learning import record_closed_trade
from .optimization import learn_ensemble_and_filters

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "paper_portfolio.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class Position:
    id: str
    ticker: str
    shares: int
    entry: float
    stop: float
    take_profit: float
    opened_at: str
    source: str = "scan"
    status: str = "open"
    exit: Optional[float] = None
    closed_at: Optional[str] = None
    realized_pnl: Optional[float] = None
    close_reason: Optional[str] = None


@dataclass
class PaperPortfolio:
    mode: str = "paper"
    cash: float = 10_000.0
    starting_cash: float = 10_000.0
    positions: List[Dict[str, Any]] = field(default_factory=list)
    closed: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _default_portfolio(cfg: Optional[StrategyConfig] = None) -> PaperPortfolio:
    cfg = cfg or get_runtime_config()
    return PaperPortfolio(
        mode="paper",
        cash=float(cfg.starting_equity),
        starting_cash=float(cfg.starting_equity),
        positions=[],
        closed=[],
        updated_at=_utc_now(),
    )


def load_portfolio(path: Path = DEFAULT_PATH) -> PaperPortfolio:
    if not path.exists():
        p = _default_portfolio()
        save_portfolio(p, path)
        return p
    try:
        raw = json.loads(path.read_text())
        return PaperPortfolio(
            mode=raw.get("mode", "paper"),
            cash=float(raw.get("cash", 10_000)),
            starting_cash=float(raw.get("starting_cash", raw.get("cash", 10_000))),
            positions=list(raw.get("positions", [])),
            closed=list(raw.get("closed", [])),
            updated_at=raw.get("updated_at", _utc_now()),
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return _default_portfolio()


def save_portfolio(portfolio: PaperPortfolio, path: Path = DEFAULT_PATH) -> None:
    _ensure_parent(path)
    portfolio.updated_at = _utc_now()
    path.write_text(json.dumps(portfolio.to_dict(), indent=2))


def set_mode(mode: str, path: Path = DEFAULT_PATH) -> PaperPortfolio:
    p = load_portfolio(path)
    mode = (mode or "paper").lower().strip()
    if mode not in ("paper", "live"):
        mode = "paper"
    p.mode = mode
    save_portfolio(p, path)
    return p


def _latest_price(ticker: str) -> Optional[float]:
    src = get_data_source(purpose="live")
    # Prefer SIP last trade when available
    trade = src.get_latest_trade(ticker) if hasattr(src, "get_latest_trade") else None
    if trade is not None and trade.price > 0:
        return float(trade.price)
    data = src.download_ohlcv([ticker], period="5d", batch_size=1)
    df = data.get(ticker)
    if df is None or df.empty or "Close" not in df.columns:
        return None
    return float(df["Close"].dropna().iloc[-1])


def mark_to_market(path: Path = DEFAULT_PATH) -> Dict[str, Any]:
    p = load_portfolio(path)
    open_pos = [x for x in p.positions if x.get("status", "open") == "open"]
    tickers = list({x["ticker"] for x in open_pos})
    prices: Dict[str, float] = {}
    if tickers:
        src = get_data_source(purpose="live")
        for t in tickers:
            trade = src.get_latest_trade(t) if hasattr(src, "get_latest_trade") else None
            if trade is not None and trade.price > 0:
                prices[t] = float(trade.price)
        missing = [t for t in tickers if t not in prices]
        if missing:
            data = src.download_ohlcv(missing, period="5d", batch_size=50)
            for t, df in data.items():
                if df is not None and not df.empty and "Close" in df.columns:
                    prices[t] = float(df["Close"].dropna().iloc[-1])

    enriched = []
    unrealized = 0.0
    market_value = 0.0
    for pos in open_pos:
        t = pos["ticker"]
        px = prices.get(t, float(pos["entry"]))
        mv = px * int(pos["shares"])
        upnl = (px - float(pos["entry"])) * int(pos["shares"])
        unrealized += upnl
        market_value += mv
        # Trailing stop mark (informational)
        trail = float(pos.get("trailing_stop") or pos["stop"])
        enriched.append({
            **pos,
            "last_price": round(px, 4),
            "market_value": round(mv, 2),
            "unrealized_pnl": round(upnl, 2),
            "unrealized_pct": round((px - float(pos["entry"])) / float(pos["entry"]), 6) if pos["entry"] else 0.0,
            "trailing_stop": trail,
        })

    realized = sum(float(c.get("realized_pnl") or 0) for c in p.closed)
    total_fees_closed = sum(float(c.get("total_fees") or 0) for c in p.closed)
    # Open positions have already paid entry fees (cash reduced); include those too
    open_entry_fees = sum(float(x.get("entry_fees") or 0) for x in open_pos)
    gross_realized = sum(
        float(c.get("gross_pnl") if c.get("gross_pnl") is not None else (c.get("realized_pnl") or 0))
        for c in p.closed
    )
    equity = p.cash + market_value
    fee_impact = fee_impact_summary(p.closed, starting_equity=p.starting_cash)
    return {
        "mode": p.mode,
        "live_broker_connected": False,
        "live_note": "Live mode is not connected to a broker — paper only for now. Orders are always simulated.",
        "cash": round(p.cash, 2),
        "starting_cash": round(p.starting_cash, 2),
        "equity": round(equity, 2),
        "market_value": round(market_value, 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized, 2),
        "gross_realized_pnl": round(gross_realized, 2),
        "total_pnl": round(unrealized + realized, 2),
        "return_pct": round((equity - p.starting_cash) / p.starting_cash, 6) if p.starting_cash else 0.0,
        "total_fees_paid": round(total_fees_closed + open_entry_fees, 2),
        "fees_on_open": round(open_entry_fees, 2),
        "fee_impact": fee_impact,
        "open_positions": enriched,
        "closed_count": len(p.closed),
        "updated_at": p.updated_at,
    }


def place_order(
    ticker: str,
    shares: int,
    entry: Optional[float] = None,
    stop: Optional[float] = None,
    take_profit: Optional[float] = None,
    source: str = "manual",
    path: Path = DEFAULT_PATH,
    cfg: Optional[StrategyConfig] = None,
    forward_probability: Optional[float] = None,
    forward_threshold: Optional[float] = None,
    ensemble_votes: Optional[Dict[str, float]] = None,
    confidence: Optional[float] = None,
    context: Optional[Dict[str, Any]] = None,
    signal: Optional[Any] = None,
    strategy_id: Optional[str] = None,
    human_approved: bool = False,
    skip_session_gate: bool = False,
) -> Dict[str, Any]:
    cfg = cfg or get_runtime_config()
    p = load_portfolio(path)
    # Preserve exchange suffixes (.L/.TO) as -L/-TO for internal keys; map still works
    ticker = ticker.strip().upper().replace(".", "-")
    if shares <= 0:
        raise ValueError("shares must be positive")
    if entry is None:
        entry = _latest_price(ticker)
    if entry is None or entry <= 0:
        raise ValueError(f"could not determine entry price for {ticker}")
    if stop is None:
        stop = entry * (1.0 - cfg.stop_loss_pct)
    if take_profit is None:
        take_profit = entry * (1.0 + cfg.take_profit_pct)

    sid = strategy_id
    if sid is None and signal is not None:
        sid = getattr(signal, "strategy_id", None) or (
            signal.get("strategy_id") if isinstance(signal, dict) else None
        )
    if sid is None and isinstance(context, dict):
        sid = context.get("strategy_id")
    sid = sid or "momentum"

    # Home-session gate for NEW entries (exits use close_position)
    if not skip_session_gate:
        from .timezone_util import should_allow_new_entry
        allow, gate_reason, _info = should_allow_new_entry(ticker, cfg)
        if not allow:
            raise ValueError(f"session_gate: {gate_reason} — home market closed for new entries")

    # Hard non-LLM policy firewall (fail closed)
    from . import policy_firewall as fw
    open_pos_pre = [x for x in p.positions if x.get("status", "open") == "open"]
    mtm_eq = p.cash + sum(
        float(op.get("entry", 0)) * int(op.get("shares") or 0) for op in open_pos_pre
    )
    fw_result = fw.assert_order_allowed(
        ticker=ticker,
        shares=float(shares),
        price=float(entry),
        side="buy",
        mode=p.mode or "paper",
        source=source,
        strategy_id=sid,
        equity=float(mtm_eq),
        cfg=cfg,
        human_approved=human_approved,
    )

    # Risk budget: no single ticker may exceed equity * max_position_pct
    open_pos = [x for x in p.positions if x.get("status", "open") == "open"]
    mtm_equity = p.cash
    for op in open_pos:
        mtm_equity += float(op.get("entry", 0)) * int(op.get("shares") or 0)
    existing_notional = sum(
        float(op.get("entry", 0)) * int(op.get("shares") or 0)
        for op in open_pos if op.get("ticker") == ticker
    )
    cap = float(mtm_equity) * float(cfg.max_position_pct)
    room = max(0.0, cap - existing_notional)
    max_shares = int(room // float(entry)) if entry else 0
    if shares > max_shares:
        if max_shares <= 0:
            raise ValueError(
                f"risk budget: {ticker} already at/over max_position_pct="
                f"{cfg.max_position_pct:.0%} of equity ({cap:.2f})"
            )
        shares = max_shares

    notional = shares * float(entry)
    entry_fee = compute_trade_fees(shares, float(entry), side="buy", cfg=cfg)
    cost = notional + entry_fee.total
    if cost > p.cash + 1e-6:
        raise ValueError(
            f"insufficient paper cash: need {cost:.2f} "
            f"(notional {notional:.2f} + fees {entry_fee.total:.2f}), have {p.cash:.2f}"
        )

    note = (
        "LIVE STUB: no broker connected; filled as paper simulation"
        if p.mode == "live"
        else "paper fill"
    )
    p.cash -= cost
    cfg_snap = cfg.to_dict()
    pos = Position(
        id=str(uuid.uuid4())[:8],
        ticker=ticker,
        shares=int(shares),
        entry=round(float(entry), 4),
        stop=round(float(stop), 4),
        take_profit=round(float(take_profit), 4),
        opened_at=_utc_now(),
        source=source,
        status="open",
    )
    pos_dict = asdict(pos)
    pos_dict["entry_fees"] = round(entry_fee.total, 4)
    pos_dict["entry_commission"] = round(entry_fee.commission, 4)
    pos_dict["entry_slippage"] = round(entry_fee.slippage, 4)
    pos_dict["fees_enabled"] = entry_fee.enabled
    pos_dict["signal_params"] = {
        k: cfg_snap.get(k)
        for k in (
            "lookback_days", "volume_multiple", "min_return",
            "stop_loss_pct", "take_profit_pct", "top_pct", "top_n",
            "forward_estimate_threshold", "max_realized_vol", "min_adx",
            "trailing_stop_pct", "ensemble_w_logreg", "ensemble_w_gbdt", "ensemble_w_rules",
        )
    }
    pos_dict["trailing_stop"] = pos_dict["stop"]
    pos_dict["high_water"] = float(entry)
    pos_dict["partial_taken"] = False
    pos_dict["use_trailing_stop"] = cfg.use_trailing_stop
    pos_dict["use_partial_profits"] = cfg.use_partial_profits
    pos_dict["partial_take_pct"] = cfg.partial_take_pct
    pos_dict["partial_fraction"] = cfg.partial_fraction
    pos_dict["time_exit_days"] = cfg.time_exit_days
    if forward_probability is not None:
        pos_dict["forward_probability"] = float(forward_probability)
    if forward_threshold is not None:
        pos_dict["forward_threshold"] = float(forward_threshold)
    if ensemble_votes is not None:
        pos_dict["ensemble_votes"] = ensemble_votes
    if confidence is not None:
        pos_dict["confidence"] = round(float(confidence), 4)
    # Structured entry context for richer learning
    try:
        from .feedback import build_entry_context
        if context is not None:
            pos_dict["context"] = context
        else:
            pos_dict["context"] = build_entry_context(
                ticker=ticker,
                signal=signal,
                cfg=cfg,
                extra={
                    "momentum_pct": None,
                    "volume_ratio": None,
                    "forward_probability": forward_probability,
                    "ensemble_votes": ensemble_votes,
                    "confidence": confidence,
                } if signal is None else None,
            )
            if signal is None and confidence is not None:
                pos_dict["context"]["confidence"] = round(float(confidence), 4)
                if forward_probability is not None:
                    pos_dict["context"]["forward_probability"] = float(forward_probability)
                if ensemble_votes is not None:
                    pos_dict["context"]["ensemble_votes"] = ensemble_votes
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: entry context tag failed: {exc}")
        pos_dict["context"] = context or {}
    pos_dict["strategy_id"] = sid
    pos_dict["firewall"] = {
        "allowed": True,
        "code": fw_result.code,
        "reason": fw_result.reason,
        "notional": fw_result.notional,
    }
    if isinstance(pos_dict.get("context"), dict):
        pos_dict["context"]["strategy_id"] = sid
        pos_dict["context"]["firewall"] = pos_dict["firewall"]
    p.positions.append(pos_dict)
    save_portfolio(p, path)
    return {
        **pos_dict,
        "fill_note": note,
        "mode": p.mode,
        "cash_remaining": round(p.cash, 2),
        "fees": entry_fee.to_dict(),
        "total_cost": round(cost, 2),
        "strategy_id": sid,
        "firewall": pos_dict["firewall"],
    }


def close_position(
    position_id: str,
    exit_price: Optional[float] = None,
    reason: str = "manual",
    path: Path = DEFAULT_PATH,
    shares_to_close: Optional[int] = None,
) -> Dict[str, Any]:
    p = load_portfolio(path)
    idx = None
    for i, pos in enumerate(p.positions):
        if pos.get("id") == position_id and pos.get("status", "open") == "open":
            idx = i
            break
    if idx is None:
        raise KeyError(f"open position {position_id} not found")

    pos = p.positions[idx]
    if exit_price is None:
        exit_price = _latest_price(pos["ticker"])
    if exit_price is None:
        exit_price = float(pos["entry"])

    total_shares = int(pos["shares"])
    close_shares = int(shares_to_close) if shares_to_close else total_shares
    close_shares = max(1, min(close_shares, total_shares))

    cfg = get_runtime_config()
    exit_fee = compute_trade_fees(close_shares, float(exit_price), side="sell", cfg=cfg)
    # Pro-rate entry fees if partial close
    prior_entry_fees = float(pos.get("entry_fees") or 0.0)
    entry_fees_alloc = prior_entry_fees * (close_shares / total_shares) if total_shares else 0.0
    # Remaining entry fees stay on open position after partial
    if close_shares < total_shares and prior_entry_fees:
        pos["entry_fees"] = round(prior_entry_fees - entry_fees_alloc, 4)

    proceeds = float(exit_price) * close_shares - exit_fee.total
    gross_pnl = (float(exit_price) - float(pos["entry"])) * close_shares
    total_fees = entry_fees_alloc + exit_fee.total
    pnl = gross_pnl - total_fees  # net realized
    p.cash += proceeds

    fee_fields = {
        "entry_fees": round(entry_fees_alloc, 4),
        "exit_fees": round(exit_fee.total, 4),
        "exit_commission": round(exit_fee.commission, 4),
        "exit_slippage": round(exit_fee.slippage, 4),
        "total_fees": round(total_fees, 4),
        "gross_pnl": round(gross_pnl, 2),
        "realized_pnl": round(pnl, 2),  # net of fees
    }

    if close_shares < total_shares:
        # Partial close
        pos["shares"] = total_shares - close_shares
        pos["partial_taken"] = True
        partial_rec = {
            **{k: v for k, v in pos.items() if k not in ("shares", "status", "entry_fees")},
            "id": pos["id"] + "-p",
            "shares": close_shares,
            "status": "closed",
            "exit": round(float(exit_price), 4),
            "closed_at": _utc_now(),
            "close_reason": reason or "partial",
            **fee_fields,
        }
        p.closed.append(partial_rec)
        save_portfolio(p, path)
        return partial_rec

    pos["status"] = "closed"
    pos["exit"] = round(float(exit_price), 4)
    pos["closed_at"] = _utc_now()
    pos["close_reason"] = reason
    pos.update(fee_fields)
    p.closed.append(pos)
    p.positions.pop(idx)
    save_portfolio(p, path)

    try:
        # Net return after fees (for learning)
        ret_pct = (
            pnl / (float(pos["entry"]) * close_shares)
            if float(pos["entry"]) and close_shares
            else 0.0
        )
        record_closed_trade(
            ticker=pos["ticker"],
            entry=float(pos["entry"]),
            exit=float(exit_price),
            shares=close_shares,
            return_pct=ret_pct,
            exit_reason=reason,
            opened_at=pos.get("opened_at"),
            closed_at=pos.get("closed_at"),
            source=pos.get("source", "manual"),
            signal_params=pos.get("signal_params"),
            position_id=pos.get("id"),
            fees={
                "entry_fees": entry_fees_alloc,
                "exit_fees": exit_fee.total,
                "total_fees": total_fees,
                "gross_pnl": gross_pnl,
                "net_pnl": pnl,
            },
            context=pos.get("context"),
            confidence=pos.get("confidence"),
        )
        if pos.get("forward_probability") is not None:
            record_prediction_outcome(
                ticker=pos["ticker"],
                probability=float(pos["forward_probability"]),
                actual_positive=ret_pct > 0,
                threshold=float(
                    pos.get("forward_threshold")
                    or get_runtime_config().forward_estimate_threshold
                ),
            )
            # Attach votes for ensemble learning if present
            outcomes = [{
                "votes": pos.get("ensemble_votes") or {},
                "actual_positive": ret_pct > 0,
            }]
            learn_ensemble_and_filters(outcomes, get_runtime_config())
            adjust_from_prediction_accuracy()
    except Exception as exc:
        print(f"Warning: learning journal failed: {exc}")


    try:
        from .copilot_memory import note_outcome
        note_outcome(
            pos.get("ticker") or "",
            pnl=round(pnl, 2),
            reason=reason or "",
            strategy_id=pos.get("strategy_id"),
        )
    except Exception:
        pass

    return pos


def performance(path: Path = DEFAULT_PATH) -> Dict[str, Any]:
    snap = mark_to_market(path)
    p = load_portfolio(path)
    closed = p.closed
    wins = [c for c in closed if float(c.get("realized_pnl") or 0) > 0]
    losses = [c for c in closed if float(c.get("realized_pnl") or 0) <= 0]
    return {
        **{k: snap[k] for k in (
            "mode", "cash", "equity", "starting_cash", "unrealized_pnl",
            "realized_pnl", "gross_realized_pnl", "total_pnl", "return_pct",
            "total_fees_paid", "fees_on_open", "fee_impact",
            "live_broker_connected", "live_note",
        )},
        "closed_trades": len(closed),
        "open_trades": len(snap["open_positions"]),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 4) if closed else 0.0,
        "avg_realized_pnl": round(
            sum(float(c.get("realized_pnl") or 0) for c in closed) / len(closed), 2
        ) if closed else 0.0,
        "recent_closed": closed[-20:],
        "updated_at": snap["updated_at"],
    }


def reset_portfolio(path: Path = DEFAULT_PATH, cfg: Optional[StrategyConfig] = None) -> PaperPortfolio:
    p = _default_portfolio(cfg)
    save_portfolio(p, path)
    return p


def manage_exits(path: Path = DEFAULT_PATH, cfg: Optional[StrategyConfig] = None) -> Dict[str, Any]:
    """
    Auto-manage open paper positions: trailing stop, stop, take-profit,
    partial profits, time exit. Returns actions taken.
    """
    from datetime import datetime, timezone, timedelta
    from .optimization import update_trailing_stop

    cfg = cfg or get_runtime_config()
    p = load_portfolio(path)
    open_pos = [x for x in p.positions if x.get("status", "open") == "open"]
    actions: List[Dict[str, Any]] = []

    for pos in list(open_pos):
        ticker = pos["ticker"]
        px = _latest_price(ticker)
        if px is None or px <= 0:
            actions.append({"id": pos.get("id"), "ticker": ticker, "action": "skip", "why": "no_price"})
            continue
        entry = float(pos["entry"])
        shares = int(pos["shares"])
        stop = float(pos.get("trailing_stop") or pos.get("stop") or entry * (1 - cfg.stop_loss_pct))
        tp = float(pos.get("take_profit") or entry * (1 + cfg.take_profit_pct))
        high_water = max(float(pos.get("high_water") or entry), px)

        # Update trailing
        if pos.get("use_trailing_stop", cfg.use_trailing_stop):
            trail_pct = float(pos.get("trailing_stop_pct") or cfg.trailing_stop_pct)
            new_trail = update_trailing_stop(entry, high_water, stop, trail_pct)
            stop = new_trail
            # persist high_water / trailing on open book
            for i, op in enumerate(p.positions):
                if op.get("id") == pos.get("id") and op.get("status", "open") == "open":
                    p.positions[i]["high_water"] = high_water
                    p.positions[i]["trailing_stop"] = round(stop, 4)
                    break
            save_portfolio(p, path)

        # Partial take
        use_partial = pos.get("use_partial_profits", cfg.use_partial_profits)
        partial_pct = float(pos.get("partial_take_pct") or cfg.partial_take_pct)
        partial_frac = float(pos.get("partial_fraction") or cfg.partial_fraction)
        if use_partial and not pos.get("partial_taken") and entry > 0:
            if (px - entry) / entry >= partial_pct and shares >= 2:
                n_close = max(1, int(shares * partial_frac))
                try:
                    rec = close_position(pos["id"], exit_price=px, reason="partial", path=path, shares_to_close=n_close)
                    actions.append({"id": pos.get("id"), "ticker": ticker, "action": "partial", "price": px, "shares": n_close})
                    p = load_portfolio(path)
                    continue
                except Exception as exc:  # noqa: BLE001
                    actions.append({"id": pos.get("id"), "ticker": ticker, "action": "partial_error", "why": str(exc)})

        # Stop
        if px <= stop:
            try:
                close_position(pos["id"], exit_price=px, reason="stop_loss", path=path)
                actions.append({"id": pos.get("id"), "ticker": ticker, "action": "stop_loss", "price": px, "stop": stop})
            except Exception as exc:  # noqa: BLE001
                actions.append({"id": pos.get("id"), "ticker": ticker, "action": "stop_error", "why": str(exc)})
            continue

        # Take profit
        if px >= tp:
            try:
                close_position(pos["id"], exit_price=px, reason="take_profit", path=path)
                actions.append({"id": pos.get("id"), "ticker": ticker, "action": "take_profit", "price": px, "tp": tp})
            except Exception as exc:  # noqa: BLE001
                actions.append({"id": pos.get("id"), "ticker": ticker, "action": "tp_error", "why": str(exc)})
            continue

        # Time exit
        time_days = int(pos.get("time_exit_days") or cfg.time_exit_days or 0)
        min_move = float(cfg.time_exit_min_move or 0.03)
        if time_days > 0 and pos.get("opened_at"):
            try:
                opened = datetime.strptime(pos["opened_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - opened
                move = abs(px - entry) / entry if entry else 0
                if age >= timedelta(days=time_days) and move < min_move:
                    close_position(pos["id"], exit_price=px, reason="time", path=path)
                    actions.append({
                        "id": pos.get("id"), "ticker": ticker, "action": "time_exit",
                        "price": px, "age_days": round(age.total_seconds() / 86400, 2),
                    })
                    continue
            except Exception as exc:  # noqa: BLE001
                actions.append({"id": pos.get("id"), "ticker": ticker, "action": "time_error", "why": str(exc)})


    # Paper pro working orders (stop / OCO / TP triggers)
    try:
        from .paper_pro_orders import manage_working_orders
        wr = manage_working_orders(cfg=cfg)
        for a in (wr.get("actions") or []):
            actions.append(a)
    except Exception as exc:  # noqa: BLE001
        actions.append({"action": "working_error", "error": str(exc)})

    return {"checked": len(open_pos), "actions": actions, "at": _utc_now()}


def set_position_feedback(
    position_id: str,
    *,
    rating: Optional[str] = None,
    note: Optional[str] = None,
    path: Path = DEFAULT_PATH,
) -> Dict[str, Any]:
    """Like/dislike + free-text on an open or recently closed paper position."""
    from .feedback import apply_user_feedback

    p = load_portfolio(path)
    target = None
    where = None
    for i, pos in enumerate(p.positions):
        if pos.get("id") == position_id:
            target, where = pos, ("positions", i)
            break
    if target is None:
        for i, pos in enumerate(p.closed):
            if pos.get("id") == position_id or pos.get("id", "").startswith(position_id):
                target, where = pos, ("closed", i)
                break
    if target is None:
        raise KeyError(f"position {position_id} not found")
    ctx = apply_user_feedback(target, rating=rating, note=note)
    if where[0] == "positions":
        p.positions[where[1]] = target
    else:
        p.closed[where[1]] = target
    save_portfolio(p, path)
    # Mirror into journal if closed
    try:
        from .learning import load_journal, save_journal
        entries = load_journal()
        changed = False
        for e in entries:
            if e.get("id") == position_id or e.get("id") == target.get("id"):
                apply_user_feedback(e, rating=rating, note=note)
                # keep top-level mirrors
                e["context"] = e.get("context") or ctx
                changed = True
        if changed:
            save_journal(entries)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: journal feedback mirror failed: {exc}")
    return {"id": position_id, "context": ctx, "status": target.get("status")}



# ---- Portfolio analytics (terminal-lite) ------------------------------------

_SECTOR_ETF_NAME = {
    "XLK": "Technology",
    "XLC": "Communication",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLY": "Consumer Disc.",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
}


def _sector_for_ticker(ticker: str) -> str:
    t = (ticker or "").upper().replace(".", "-")
    try:
        from .strategies.relative_strength import TICKER_SECTOR

        etf = TICKER_SECTOR.get(t)
        if etf:
            return _SECTOR_ETF_NAME.get(etf, etf)
    except Exception:
        pass
    # lightweight static fallbacks beyond RS map
    extras = {
        "SPY": "Index", "QQQ": "Index", "IWM": "Index", "DIA": "Index",
        "VTI": "Index", "VOO": "Index",
    }
    return extras.get(t, "Unknown")


def build_portfolio_analytics(path: Path = DEFAULT_PATH) -> Dict[str, Any]:
    """
    GET /portfolio/analytics — allocation, P&L breakdown, win rate,
    exposure vs cash, drawdown from paper equity curve.
    """
    snap = mark_to_market(path)
    perf = performance(path)
    equity = float(snap.get("equity") or 0) or 1.0
    cash = float(snap.get("cash") or 0)
    positions = list(snap.get("open_positions") or [])

    by_symbol: List[Dict[str, Any]] = []
    by_sector: Dict[str, Dict[str, Any]] = {}
    for p in positions:
        ticker = str(p.get("ticker") or "?")
        mv = float(p.get("market_value") or 0)
        upnl = float(p.get("unrealized_pnl") or 0)
        weight = round(mv / equity, 4) if equity else 0.0
        sector = _sector_for_ticker(ticker)
        by_symbol.append({
            "ticker": ticker,
            "shares": p.get("shares"),
            "market_value": round(mv, 2),
            "weight": weight,
            "unrealized_pnl": round(upnl, 2),
            "sector": sector,
            "strategy_id": p.get("strategy_id"),
        })
        bucket = by_sector.setdefault(sector, {"sector": sector, "market_value": 0.0, "weight": 0.0, "count": 0})
        bucket["market_value"] += mv
        bucket["count"] += 1
    for b in by_sector.values():
        b["market_value"] = round(b["market_value"], 2)
        b["weight"] = round(b["market_value"] / equity, 4) if equity else 0.0
    by_symbol.sort(key=lambda x: -abs(float(x.get("weight") or 0)))
    sector_list = sorted(by_sector.values(), key=lambda x: -abs(float(x.get("weight") or 0)))

    invested = sum(float(p.get("market_value") or 0) for p in positions)
    exposure = {
        "equity": round(float(snap.get("equity") or 0), 2),
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "cash_pct": round(cash / equity, 4) if equity else 0.0,
        "invested_pct": round(invested / equity, 4) if equity else 0.0,
        "open_positions": len(positions),
    }

    pnl_breakdown = {
        "unrealized_pnl": round(float(snap.get("unrealized_pnl") or 0), 2),
        "realized_pnl": round(float(snap.get("realized_pnl") or 0), 2),
        "gross_realized_pnl": snap.get("gross_realized_pnl"),
        "total_pnl": round(float(snap.get("total_pnl") or 0), 2),
        "return_pct": snap.get("return_pct"),
        "total_fees_paid": snap.get("total_fees_paid"),
        "wins": perf.get("wins"),
        "losses": perf.get("losses"),
        "win_rate": perf.get("win_rate"),
        "closed_trades": perf.get("closed_trades"),
        "avg_realized_pnl": perf.get("avg_realized_pnl"),
    }

    # Drawdown from paper equity curve (journal-based)
    curve: List[Dict[str, Any]] = []
    max_dd = 0.0
    try:
        from .scoreboard import build_paper_report

        report = build_paper_report()
        curve = list(report.get("equity_curve") or [])[-80:]
        summary = report.get("summary") or {}
        max_dd = float(summary.get("max_drawdown_pct") or 0)
    except Exception as exc:  # noqa: BLE001
        curve = [{"error": str(exc)[:100]}]

    spark = [p.get("equity") for p in curve if isinstance(p, dict) and p.get("equity") is not None][-40:]

    return {
        "ok": True,
        "label": "PAPER / not live audited",
        "allocation_by_symbol": by_symbol[:20],
        "allocation_by_sector": sector_list[:12],
        "pnl_breakdown": pnl_breakdown,
        "exposure_vs_cash": exposure,
        "drawdown": {
            "max_drawdown_pct": round(max_dd, 6),
            "equity_curve_points": len(curve) if curve and not (isinstance(curve[0], dict) and curve[0].get("error")) else 0,
            "equity_sparkline": spark,
        },
        "mode": snap.get("mode"),
        "live_locked": True,
        "live_broker_connected": False,
        "disclaimer": (
            "Terminal-lite paper analytics — not live audited, not Bloomberg PORT. "
            "Sector tags from liquid-name map when available."
        ),
        "not_bloomberg_licensed": True,
        "not_level2": True,
        "generated_at": _utc_now(),
        "updated_at": snap.get("updated_at"),
    }

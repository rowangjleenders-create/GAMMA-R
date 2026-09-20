"""
Simple historical momentum backtest.

Walks forward on daily bars: every `rebalance_every` days, scan for
momentum+volume signals among the provided (or downloaded) universe,
enter risk-sized long positions, exit on stop / take-profit / time stop.
Applies configurable commissions + slippage (see fees.py). Still ignores shorting/borrow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .fees import compute_trade_fees, fee_impact_summary
from .data import download_ohlcv
from .risk import size_position
from .universe import load_universe


@dataclass
class TradeRecord:
    ticker: str
    entry_date: str
    exit_date: str
    entry: float
    exit: float
    shares: int
    pnl: float  # net of fees
    return_pct: float  # net return on notional
    reason: str  # stop | take_profit | time | end
    gross_pnl: float = 0.0
    entry_fees: float = 0.0
    exit_fees: float = 0.0
    total_fees: float = 0.0


@dataclass
class BacktestResult:
    starting_equity: float
    ending_equity: float
    total_return: float  # net of fees
    max_drawdown: float
    win_rate: float
    num_trades: int
    wins: int
    losses: int
    trades: List[TradeRecord] = field(default_factory=list)
    total_fees: float = 0.0
    gross_return: float = 0.0
    fee_impact: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def _max_drawdown(equity_curve: List[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)
    return max_dd


def run_backtest(
    cfg: Optional[StrategyConfig] = None,
    tickers: Optional[List[str]] = None,
    *,
    calendar_days: Optional[int] = None,
) -> BacktestResult:
    """
    Run a lightweight long-only momentum backtest.

    For speed/education we:
    - download ~backtest_years of daily data for the universe
    - on each rebalance day, pick top_n names by lookback return with volume filter
    - size with risk.py, hold until stop, take-profit, or next rebalance (time exit)
    """
    cfg = cfg or StrategyConfig()
    tickers = tickers or load_universe(cfg)

    end = datetime.utcnow()
    if calendar_days is not None and calendar_days > 0:
        start = end - timedelta(days=int(calendar_days))
    else:
        start = end - timedelta(days=int(cfg.backtest_years * 365.25))
    data = download_ohlcv(
        tickers,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        batch_size=50,
    )
    if not data:
        return BacktestResult(
            starting_equity=cfg.starting_equity,
            ending_equity=cfg.starting_equity,
            total_return=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            num_trades=0,
            wins=0,
            losses=0,
            trades=[],
        )

    # Align on a common calendar (union of dates, forward-fill closes carefully)
    all_dates = sorted({d for df in data.values() for d in df.index})
    if len(all_dates) < cfg.lookback_days + cfg.volume_avg_days + 5:
        return BacktestResult(
            starting_equity=cfg.starting_equity,
            ending_equity=cfg.starting_equity,
            total_return=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            num_trades=0,
            wins=0,
            losses=0,
            trades=[],
        )

    cash = float(cfg.starting_equity)
    # open: ticker -> dict
    open_pos: Dict[str, Dict[str, Any]] = {}
    trades: List[TradeRecord] = []
    equity_curve: List[float] = []

    need = max(cfg.lookback_days, cfg.volume_avg_days) + 1
    rebalance_every = max(1, cfg.rebalance_every)

    def mark_equity(i: int) -> float:
        total = cash
        dt = all_dates[i]
        for t, pos in open_pos.items():
            df = data.get(t)
            if df is None or dt not in df.index:
                total += pos["shares"] * pos["entry"]
            else:
                total += pos["shares"] * float(df.loc[dt, "Close"])
        return total

    def close_position(t: str, exit_px: float, exit_date, reason: str) -> None:
        nonlocal cash
        pos = open_pos.pop(t)
        shares = int(pos["shares"])
        entry_px = float(pos["entry"])
        entry_fees = float(pos.get("entry_fees") or 0.0)
        exit_fee = compute_trade_fees(shares, exit_px, side="sell", cfg=cfg)
        gross = (exit_px - entry_px) * shares
        total_fees = entry_fees + exit_fee.total
        pnl = gross - total_fees
        cash += exit_px * shares - exit_fee.total
        ret = pnl / (entry_px * shares) if entry_px and shares else 0.0
        trades.append(
            TradeRecord(
                ticker=t,
                entry_date=str(pos["entry_date"].date()),
                exit_date=str(pd.Timestamp(exit_date).date()),
                entry=round(entry_px, 4),
                exit=round(exit_px, 4),
                shares=shares,
                pnl=round(pnl, 2),
                return_pct=round(ret, 6),
                reason=reason,
                gross_pnl=round(gross, 2),
                entry_fees=round(entry_fees, 4),
                exit_fees=round(exit_fee.total, 4),
                total_fees=round(total_fees, 4),
            )
        )

    for i, dt in enumerate(all_dates):
        # Check stops / take-profits on open positions daily
        for t in list(open_pos.keys()):
            df = data.get(t)
            if df is None or dt not in df.index:
                continue
            row = df.loc[dt]
            low = float(row["Low"]) if "Low" in row and not pd.isna(row["Low"]) else float(row["Close"])
            high = float(row["High"]) if "High" in row and not pd.isna(row["High"]) else float(row["Close"])
            close = float(row["Close"])
            pos = open_pos[t]
            if low <= pos["stop"]:
                close_position(t, pos["stop"], dt, "stop")
            elif high >= pos["take_profit"]:
                close_position(t, pos["take_profit"], dt, "take_profit")

        # Rebalance / new entries
        if i >= need and (i - need) % rebalance_every == 0:
            # Time-exit existing positions on rebalance (simple rotation)
            for t in list(open_pos.keys()):
                df = data.get(t)
                if df is not None and dt in df.index:
                    close_position(t, float(df.loc[dt, "Close"]), dt, "time")

            candidates = []
            for t, df in data.items():
                hist = df.loc[:dt]
                if len(hist) < need:
                    continue
                closes = hist["Close"].dropna()
                volumes = hist["Volume"].dropna()
                if len(closes) < need or len(volumes) < cfg.volume_avg_days + 1:
                    continue
                entry = float(closes.iloc[-1])
                if entry < cfg.min_price:
                    continue
                past = float(closes.iloc[-(cfg.lookback_days + 1)])
                if past <= 0:
                    continue
                mom = (entry - past) / past
                if mom < cfg.min_return:
                    continue
                vol_avg = float(volumes.iloc[-(cfg.volume_avg_days + 1) : -1].mean())
                vol_today = float(volumes.iloc[-1])
                if vol_avg <= 0 or (vol_today / vol_avg) < cfg.volume_multiple:
                    continue
                candidates.append((t, mom, entry))

            candidates.sort(key=lambda x: x[1], reverse=True)
            equity_now = mark_equity(i)
            for t, mom, entry in candidates[: cfg.top_n]:
                if t in open_pos:
                    continue
                plan = size_position(t, entry, equity_now, cfg)
                if plan.shares <= 0:
                    continue
                entry_fee = compute_trade_fees(plan.shares, entry, side="buy", cfg=cfg)
                cost = plan.shares * entry + entry_fee.total
                if cost > cash:
                    continue
                cash -= cost
                open_pos[t] = {
                    "entry": entry,
                    "shares": plan.shares,
                    "stop": plan.stop,
                    "take_profit": plan.take_profit,
                    "entry_date": dt,
                    "entry_fees": entry_fee.total,
                }

        equity_curve.append(mark_equity(i))

    # Close leftovers at last price
    last_dt = all_dates[-1]
    for t in list(open_pos.keys()):
        df = data.get(t)
        px = float(df.loc[last_dt, "Close"]) if df is not None and last_dt in df.index else open_pos[t]["entry"]
        close_position(t, px, last_dt, "end")

    ending = cash
    wins = sum(1 for tr in trades if tr.pnl > 0)
    losses = sum(1 for tr in trades if tr.pnl <= 0)
    n = len(trades)
    total_fees = sum(tr.total_fees for tr in trades)
    gross_pnl = sum(tr.gross_pnl for tr in trades)
    net_ret = (ending - cfg.starting_equity) / cfg.starting_equity if cfg.starting_equity else 0.0
    gross_ret = (
        (ending - cfg.starting_equity + total_fees) / cfg.starting_equity
        if cfg.starting_equity
        else 0.0
    )
    trade_dicts = [
        {
            "entry": tr.entry,
            "exit": tr.exit,
            "shares": tr.shares,
            "realized_pnl": tr.pnl,
            "gross_pnl": tr.gross_pnl,
            "entry_fees": tr.entry_fees,
            "exit_fees": tr.exit_fees,
            "total_fees": tr.total_fees,
        }
        for tr in trades
    ]
    impact = fee_impact_summary(trade_dicts, starting_equity=cfg.starting_equity)
    return BacktestResult(
        starting_equity=cfg.starting_equity,
        ending_equity=round(ending, 2),
        total_return=round(net_ret, 6),
        max_drawdown=round(_max_drawdown(equity_curve), 6),
        win_rate=round(wins / n, 4) if n else 0.0,
        num_trades=n,
        wins=wins,
        losses=losses,
        trades=trades,
        total_fees=round(total_fees, 2),
        gross_return=round(gross_ret, 6),
        fee_impact=impact,
    )


def run_session_replay(
    *,
    days: int = 5,
    max_tickers: int = 40,
    cfg_current: Optional[StrategyConfig] = None,
) -> Dict[str, Any]:
    """
    Replay recent sessions with TODAY's learned logic vs prior params.

    Compares current runtime (learned) config against the previous learning
    snapshot (or day-one SEED) on the last `days` calendar days of data.
    """
    from .config import SEED_DEFAULTS, StrategyConfig, get_runtime_config
    from .learning import load_history, load_learned_config

    days = max(1, min(int(days), 30))
    current = cfg_current or get_runtime_config()

    # Prior params: last learning batch "before", else SEED learnable fields
    hist = load_history()
    prior_params: Dict[str, Any] = {}
    prior_label = "day_one_SEED"
    if hist:
        prior_params = dict(hist[-1].get("before") or {})
        prior_label = f"pre-learn @ {hist[-1].get('at', '?')}"
    if not prior_params:
        prior_params = {
            k: SEED_DEFAULTS.get(k)
            for k in (
                "lookback_days", "volume_multiple", "min_return",
                "stop_loss_pct", "take_profit_pct", "top_pct", "top_n",
                "max_position_pct", "risk_per_trade",
            )
        }
        prior_label = "day_one_SEED"

    # Shrink universe for speed
    tickers = load_universe(current)[:max_tickers]

    cfg_now = current.update({"backtest_years": max(1, days / 365.25)})
    # Need enough history for lookback indicators — pad download window
    pad_days = max(days + 60, current.lookback_days + current.volume_avg_days + 40)

    prior_cfg = current.update(prior_params)

    # Pad calendar so indicators warm up, but report focuses on recent window
    res_now = run_backtest(cfg_now, tickers=tickers, calendar_days=pad_days)
    res_prior = run_backtest(prior_cfg, tickers=tickers, calendar_days=pad_days)

    better = float(res_now.total_return) > float(res_prior.total_return)
    delta = float(res_now.total_return) - float(res_prior.total_return)
    learned = load_learned_config()

    return {
        "label": "session_replay",
        "days_requested": days,
        "pad_calendar_days": pad_days,
        "prior_label": prior_label,
        "current_label": "live-learned" if learned.get("params") else "runtime",
        "current": {
            "total_return": res_now.total_return,
            "ending_equity": res_now.ending_equity,
            "win_rate": res_now.win_rate,
            "num_trades": res_now.num_trades,
            "max_drawdown": res_now.max_drawdown,
            "params_snapshot": {
                k: current.to_dict().get(k)
                for k in (
                    "lookback_days", "volume_multiple", "min_return",
                    "stop_loss_pct", "take_profit_pct", "top_pct", "min_confidence",
                    "max_position_pct",
                )
            },
        },
        "prior": {
            "total_return": res_prior.total_return,
            "ending_equity": res_prior.ending_equity,
            "win_rate": res_prior.win_rate,
            "num_trades": res_prior.num_trades,
            "max_drawdown": res_prior.max_drawdown,
            "params_snapshot": prior_params,
        },
        "delta_return": round(delta, 6),
        "learned_better": better,
        "verdict": (
            f"TODAY's learned logic {'beat' if better else 'did not beat'} prior "
            f"by {delta:+.2%} over ~{days}d window (padded download {pad_days}d)."
        ),
        "at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Educational replay — not a guarantee of live performance.",
    }


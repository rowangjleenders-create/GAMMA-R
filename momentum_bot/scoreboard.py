"""
Walk-forward / rolling paper scoreboard per strategy.

v1: rolling paper journal metrics with clear labeling (not full OOS backtest).
When enough samples exist, optionally down-weight weak strategies in the router.

Statuses: keep | watch | cut | insufficient
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        raw = str(s).replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _strategy_id(entry: Dict[str, Any]) -> str:
    sid = (
        entry.get("strategy_id")
        or (entry.get("context") or {}).get("strategy_id")
        or (entry.get("signal") or {}).get("strategy_id")
        or (entry.get("signal_params") or {}).get("strategy_id")
    )
    return str(sid or "unknown")


def _pnl(entry: Dict[str, Any]) -> Optional[float]:
    for k in ("realized_pnl", "net_pnl", "pnl", "gross_pnl"):
        if entry.get(k) is not None:
            try:
                return float(entry[k])
            except (TypeError, ValueError):
                pass
    # Derive from return_pct * entry * shares
    try:
        rp = entry.get("return_pct")
        if rp is None:
            return None
        entry_px = float(entry.get("entry") or 0)
        shares = float(entry.get("shares") or 0)
        return float(rp) * entry_px * shares
    except (TypeError, ValueError):
        return None


def _return_pct(entry: Dict[str, Any]) -> Optional[float]:
    try:
        if entry.get("return_pct") is not None:
            return float(entry["return_pct"])
    except (TypeError, ValueError):
        pass
    return None


def _max_drawdown_from_pnls(pnls: Sequence[float]) -> float:
    if not pnls:
        return 0.0
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else (peak - eq)
        if peak <= 0:
            dd = min(0.0, eq)  # underwater from zero
            max_dd = min(max_dd, eq) if eq < max_dd else max_dd
            if eq < 0:
                max_dd = min(max_dd, eq)
        else:
            max_dd = min(max_dd, -dd if dd > 0 else 0.0)
    # Return as positive fraction of peak when possible
    if peak > 0:
        eq = 0.0
        peak = 0.0
        worst = 0.0
        for p in pnls:
            eq += p
            peak = max(peak, eq)
            if peak > 0:
                worst = max(worst, (peak - eq) / peak)
        return round(worst, 6)
    # All negative path: absolute loss magnitude as fraction of sum abs
    total = sum(abs(p) for p in pnls) or 1.0
    return round(abs(min(0.0, sum(pnls))) / total, 6)


def _sharpe_ish(returns: Sequence[float]) -> Optional[float]:
    """Simple mean/std of trade returns (not annualized calendar Sharpe)."""
    if len(returns) < 3:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
    std = math.sqrt(var)
    if std < 1e-12:
        return None
    return round(mean / std, 4)


def _profit_factor(pnls: Sequence[float]) -> Optional[float]:
    gains = sum(p for p in pnls if p > 0)
    losses = sum(-p for p in pnls if p < 0)
    if losses <= 1e-12:
        return None if gains <= 0 else 99.0
    return round(gains / losses, 4)


def _expectancy(pnls: Sequence[float]) -> Optional[float]:
    if not pnls:
        return None
    return round(sum(pnls) / len(pnls), 4)


def _classify(
    *,
    n: int,
    min_trades: int,
    win_rate: Optional[float],
    expectancy: Optional[float],
    profit_factor: Optional[float],
    max_dd: float,
    recent_return: Optional[float],
) -> str:
    if n < max(3, min_trades // 2):
        return "insufficient"
    if n < min_trades:
        # Soft watch until sample size
        bad = (
            (expectancy is not None and expectancy < 0)
            or (profit_factor is not None and profit_factor < 0.8)
            or (win_rate is not None and win_rate < 0.35)
        )
        return "watch" if bad else "insufficient"
    # Enough samples
    cut = False
    if expectancy is not None and expectancy < 0 and (profit_factor or 0) < 0.9:
        cut = True
    if profit_factor is not None and profit_factor < 0.75:
        cut = True
    if max_dd > 0.35 and (expectancy or 0) <= 0:
        cut = True
    if recent_return is not None and recent_return < -0.08 and (expectancy or 0) < 0:
        cut = True
    if cut:
        return "cut"
    keep = (
        (expectancy is not None and expectancy > 0)
        and (profit_factor is None or profit_factor >= 1.05)
        and (win_rate is None or win_rate >= 0.4)
    )
    if keep:
        return "keep"
    return "watch"


def _metrics_for_entries(
    entries: List[Dict[str, Any]],
    *,
    label: str,
    window_days: Optional[int] = None,
) -> Dict[str, Any]:
    rows = entries
    if window_days is not None:
        cutoff = _utc_now() - timedelta(days=int(window_days))
        rows = []
        for e in entries:
            ts = _parse_ts(e.get("closed_at") or e.get("recorded_at"))
            if ts is None or ts >= cutoff:
                rows.append(e)

    pnls: List[float] = []
    rets: List[float] = []
    wins = 0
    for e in rows:
        p = _pnl(e)
        r = _return_pct(e)
        if p is not None:
            pnls.append(p)
            if p > 0:
                wins += 1
        elif r is not None:
            rets_as_pnl = r  # unitless; still useful for wr
            if r > 0:
                wins += 1
            rets.append(r)
            pnls.append(r)  # fallback unit
        if r is not None and p is not None:
            rets.append(r)
        elif r is not None and p is None:
            pass

    n = len(rows)
    wr = (wins / n) if n else None
    exp = _expectancy(pnls) if pnls else None
    pf = _profit_factor(pnls) if pnls else None
    dd = _max_drawdown_from_pnls(pnls) if pnls else 0.0
    sharpe = _sharpe_ish(rets if rets else [p for p in pnls])
    total_pnl = round(sum(pnls), 4) if pnls else 0.0
    total_ret = round(sum(rets), 6) if rets else None

    return {
        "label": label,
        "trades": n,
        "wins": wins,
        "win_rate": round(wr, 4) if wr is not None else None,
        "expectancy": exp,
        "profit_factor": pf,
        "max_dd": dd,
        "sharpe_ish": sharpe,
        "total_pnl": total_pnl,
        "simple_return": total_ret,
        "window_days": window_days,
    }


def build_scoreboard(
    cfg: Any = None,
    *,
    journal: Optional[List[Dict[str, Any]]] = None,
    recent_days: int = 30,
    oos_days: int = 14,
    include_external: bool = True,
) -> Dict[str, Any]:
    """
    Per-strategy scoreboard from paper journal (+ optional external imports).

    Split labeling:
      - ``all`` — full journal (in-sample-ish / cumulative paper)
      - ``recent`` — last ``recent_days`` (rolling)
      - ``oos_proxy`` — last ``oos_days`` held out as walk-forward-style OOS proxy
      - ``is_proxy`` — trades before the OOS window

    External closed trades (origin=external) count toward learning/scoreboard
    when include_external=True. Paper portfolio equity curves stay separate.

    This is NOT a full historical walk-forward backtest; labeled clearly as
    rolling paper journal scoreboard v1.
    """
    from .config import get_runtime_config
    from .learning import load_journal
    from .strategies import all_strategy_ids, list_strategies

    cfg = cfg or get_runtime_config()
    entries = list(journal) if journal is not None else (load_journal() or [])
    if not include_external:
        entries = [e for e in entries if (e.get("origin") or "paper") != "external"]
    min_trades = int(getattr(cfg, "scoreboard_min_trades", None) or getattr(cfg, "learning_min_trades", 10) or 10)
    downweight = bool(getattr(cfg, "scoreboard_router_downweight", True))

    by_sid: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        sid = _strategy_id(e)
        by_sid.setdefault(sid, []).append(e)

    known = set(all_strategy_ids())
    names = {s["id"]: s["name"] for s in list_strategies()}

    strategies_out: List[Dict[str, Any]] = []
    for sid in sorted(set(list(known) + list(by_sid.keys()))):
        rows = by_sid.get(sid, [])
        # Time-ordered
        rows_sorted = sorted(
            rows,
            key=lambda e: _parse_ts(e.get("closed_at") or e.get("recorded_at")) or datetime.min.replace(tzinfo=timezone.utc),
        )
        cutoff = _utc_now() - timedelta(days=int(oos_days))
        is_rows = []
        oos_rows = []
        for e in rows_sorted:
            ts = _parse_ts(e.get("closed_at") or e.get("recorded_at"))
            if ts is not None and ts >= cutoff:
                oos_rows.append(e)
            else:
                is_rows.append(e)

        all_m = _metrics_for_entries(rows_sorted, label="all_paper")
        recent_m = _metrics_for_entries(rows_sorted, label="recent_paper", window_days=recent_days)
        oos_m = _metrics_for_entries(oos_rows, label="oos_proxy_rolling")
        is_m = _metrics_for_entries(is_rows, label="is_proxy_prior")

        # Prefer OOS proxy metrics for status when enough OOS trades; else recent; else all
        primary = oos_m if (oos_m["trades"] >= max(3, min_trades // 2)) else (
            recent_m if recent_m["trades"] >= 3 else all_m
        )
        status = _classify(
            n=int(primary["trades"]),
            min_trades=min_trades,
            win_rate=primary.get("win_rate"),
            expectancy=primary.get("expectancy"),
            profit_factor=primary.get("profit_factor"),
            max_dd=float(primary.get("max_dd") or 0),
            recent_return=recent_m.get("simple_return"),
        )

        # Soft tilt for router: negative for cut, mild negative for watch, positive for keep
        tilt = 0.0
        if downweight and primary["trades"] >= min_trades:
            if status == "cut":
                tilt = -0.25
            elif status == "watch":
                tilt = -0.08
            elif status == "keep":
                tilt = 0.08

        strategies_out.append({
            "strategy_id": sid,
            "name": names.get(sid, sid),
            "status": status,
            "sample_size": all_m["trades"],
            "min_trades": min_trades,
            "router_tilt": tilt,
            "metrics": {
                "all": all_m,
                "recent": recent_m,
                "oos_proxy": oos_m,
                "is_proxy": is_m,
            },
            "primary": primary,
        })

    # Rank: keep first, then watch, insufficient, cut last; within by expectancy
    order = {"keep": 0, "watch": 1, "insufficient": 2, "cut": 3}
    strategies_out.sort(
        key=lambda s: (
            order.get(s["status"], 9),
            -(s["primary"].get("expectancy") or -999),
            -s["sample_size"],
        )
    )

    n_ext = sum(1 for e in entries if isinstance(e, dict) and e.get("origin") == "external")
    n_paper = sum(1 for e in entries if isinstance(e, dict) and (e.get("origin") or "paper") != "external")
    return {
        "version": "paper_journal_scoreboard_v1",
        "label": "Rolling paper+external learning scoreboard (OOS proxy = last N days; not full walk-forward backtest)",
        "recent_days": recent_days,
        "oos_days": oos_days,
        "min_trades": min_trades,
        "router_downweight_enabled": downweight,
        "include_external": include_external,
        "sample_counts": {"paper": n_paper, "external": n_ext, "combined": n_paper + n_ext},
        "strategies": strategies_out,
        "generated_at": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def scoreboard_performance_tilt(cfg: Any = None) -> Dict[str, float]:
    """Map strategy_id → tilt for router (only when enough samples + flag on)."""
    board = build_scoreboard(cfg)
    if not board.get("router_downweight_enabled"):
        return {}
    min_trades = int(board.get("min_trades") or 10)
    tilt: Dict[str, float] = {}
    for s in board.get("strategies") or []:
        if int(s.get("sample_size") or 0) < min_trades:
            continue
        t = float(s.get("router_tilt") or 0)
        if abs(t) > 1e-9:
            tilt[str(s["strategy_id"])] = t
    return tilt


def _equity_curve_from_journal(entries: List[Dict[str, Any]], starting_equity: float) -> List[Dict[str, Any]]:
    """Cumulative paper equity points from closed journal rows (chronological)."""
    rows = sorted(
        [e for e in entries if isinstance(e, dict)],
        key=lambda e: _parse_ts(e.get("closed_at") or e.get("recorded_at") or e.get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    eq = float(starting_equity or 10_000.0)
    peak = eq
    curve: List[Dict[str, Any]] = [{"t": None, "equity": round(eq, 2), "drawdown_pct": 0.0}]
    for e in rows:
        pnl = _pnl(e)
        if pnl is None:
            continue
        eq += float(pnl)
        peak = max(peak, eq)
        dd = ((peak - eq) / peak) if peak > 0 else 0.0
        ts = _parse_ts(e.get("closed_at") or e.get("recorded_at") or e.get("timestamp"))
        curve.append({
            "t": ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None,
            "equity": round(eq, 2),
            "drawdown_pct": round(dd, 6),
            "strategy_id": _strategy_id(e),
        })
    return curve


def _buy_hold_spy(starting_equity: float, start_ts: Optional[datetime]) -> Dict[str, Any]:
    """Best-effort SPY buy-hold over the paper window (informational)."""
    out: Dict[str, Any] = {
        "benchmark": "SPY",
        "available": False,
        "return_pct": None,
        "end_equity": None,
        "note": "Buy-hold comparison unavailable",
    }
    try:
        from .data_sources import get_data_source
        src = get_data_source(purpose="historical")
        start = (start_ts or (_utc_now() - timedelta(days=365))).strftime("%Y-%m-%d")
        data = src.download_ohlcv(["SPY"], start=start, batch_size=1)
        df = (data or {}).get("SPY")
        if df is None or getattr(df, "empty", True) or len(df) < 2:
            out["note"] = "SPY history too short"
            return out
        close = df["Close"].astype(float)
        r = float(close.iloc[-1] / close.iloc[0] - 1.0)
        out.update({
            "available": True,
            "return_pct": round(r, 6),
            "end_equity": round(float(starting_equity) * (1.0 + r), 2),
            "start": str(close.index[0])[:10],
            "end": str(close.index[-1])[:10],
            "note": "PAPER vs SPY buy-hold (same window approx) — not live audited",
        })
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"buy-hold skipped: {exc}"
    return out



def _monthly_returns_table(curve: List[Dict[str, Any]], starting_equity: float) -> List[Dict[str, Any]]:
    """Month-end equity → monthly return rows from equity curve points."""
    if not curve or len(curve) < 2:
        return []
    # Pick last point per YYYY-MM
    by_month: Dict[str, float] = {}
    order: List[str] = []
    for p in curve:
        t = p.get("t")
        eq = p.get("equity")
        if t is None or eq is None:
            continue
        month = str(t)[:7]
        if month not in by_month:
            order.append(month)
        by_month[month] = float(eq)
    rows: List[Dict[str, Any]] = []
    prev = float(starting_equity)
    for m in order:
        eq = by_month[m]
        ret = (eq - prev) / prev if prev else None
        rows.append({
            "month": m,
            "end_equity": round(eq, 2),
            "return_pct": round(ret, 6) if ret is not None else None,
        })
        prev = eq
    return rows


def _underwater_periods(curve: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Max-DD underwater stretches: start, trough, recovery (or open)."""
    if not curve:
        return []
    periods: List[Dict[str, Any]] = []
    in_dd = False
    start_t = None
    start_eq = None
    peak_eq = None
    trough_eq = None
    trough_t = None
    max_dd = 0.0
    for p in curve:
        eq = float(p.get("equity") or 0)
        t = p.get("t")
        dd = float(p.get("drawdown_pct") or 0)
        if peak_eq is None:
            peak_eq = eq
        if eq >= peak_eq:
            if in_dd and start_t is not None:
                periods.append({
                    "start": start_t,
                    "trough": trough_t,
                    "trough_equity": round(trough_eq, 2) if trough_eq is not None else None,
                    "recovered": t,
                    "depth_pct": round(max_dd, 6),
                    "open": False,
                })
            in_dd = False
            peak_eq = eq
            start_t = None
            trough_eq = None
            trough_t = None
            max_dd = 0.0
            continue
        # underwater
        if not in_dd:
            in_dd = True
            start_t = t
            start_eq = peak_eq
            trough_eq = eq
            trough_t = t
            max_dd = dd
        else:
            if trough_eq is None or eq < trough_eq:
                trough_eq = eq
                trough_t = t
            max_dd = max(max_dd, dd)
    if in_dd and start_t is not None:
        periods.append({
            "start": start_t,
            "trough": trough_t,
            "trough_equity": round(trough_eq, 2) if trough_eq is not None else None,
            "recovered": None,
            "depth_pct": round(max_dd, 6),
            "open": True,
        })
    # Keep worst few + any open
    periods.sort(key=lambda x: -(x.get("depth_pct") or 0))
    return periods[:8]


def _strategy_attribution(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """PnL / win-rate contribution by strategy_id."""
    buckets: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        sid = _strategy_id(e)
        b = buckets.setdefault(sid, {"strategy_id": sid, "trades": 0, "wins": 0, "total_pnl": 0.0})
        pnl = _pnl(e)
        b["trades"] += 1
        if pnl is not None:
            b["total_pnl"] += float(pnl)
            if pnl > 0:
                b["wins"] += 1
        else:
            r = _return_pct(e)
            if r is not None and r > 0:
                b["wins"] += 1
    out = []
    for sid, b in buckets.items():
        n = b["trades"]
        out.append({
            "strategy_id": sid,
            "trades": n,
            "wins": b["wins"],
            "win_rate": round(b["wins"] / n, 4) if n else None,
            "total_pnl": round(b["total_pnl"], 4),
            "pct_of_pnl": None,  # filled below
        })
    total_abs = sum(abs(x["total_pnl"]) for x in out) or 1.0
    for x in out:
        x["pct_of_pnl"] = round(x["total_pnl"] / total_abs, 4)
    out.sort(key=lambda x: -abs(x["total_pnl"]))
    return out


def build_paper_report(cfg: Any = None) -> Dict[str, Any]:
    """
    Exportable PAPER performance report: scoreboard + equity curve + vs buy-hold.
    Labeled honestly as paper / not live audited.
    """
    from .config import get_runtime_config
    from .learning import load_journal
    from .paper import performance as paper_performance

    cfg = cfg or get_runtime_config()
    journal_all = load_journal() or []
    # Learning scoreboard may include external; paper equity curve must not.
    paper_journal = [e for e in journal_all if (e.get("origin") or "paper") != "external"]
    board = build_scoreboard(cfg, journal=journal_all, include_external=True)
    starting = float(getattr(cfg, "starting_equity", None) or getattr(cfg, "starting_cash", 10_000) or 10_000)
    try:
        perf = paper_performance()
        starting = float(perf.get("starting_cash") or starting)
    except Exception:
        perf = {}

    curve = _equity_curve_from_journal(paper_journal, starting)
    journal = paper_journal  # attribution / closed count for PAPER report
    first_ts = None
    for e in journal:
        first_ts = _parse_ts((e or {}).get("closed_at") or (e or {}).get("recorded_at"))
        if first_ts:
            break
    bh = _buy_hold_spy(starting, first_ts)

    paper_ret = None
    if curve:
        paper_ret = round((curve[-1]["equity"] - starting) / starting, 6) if starting else None
    max_dd = max((p.get("drawdown_pct") or 0) for p in curve) if curve else 0.0

    summary = {
        "label": "PAPER",
        "audited": False,
        "disclaimer": (
            "PAPER performance — not live audited. Simulated fills with configured fees/slippage. "
            "External brokerage imports are excluded from this equity curve."
        ),
        "starting_equity": starting,
        "ending_equity": curve[-1]["equity"] if curve else starting,
        "return_pct": paper_ret if paper_ret is not None else perf.get("return_pct"),
        "max_drawdown_pct": round(max_dd, 6),
        "win_rate": perf.get("win_rate"),
        "closed_trades": perf.get("closed_trades") or len(journal),
        "external_closed_excluded": sum(1 for e in journal_all if e.get("origin") == "external"),
        "vs_buy_hold": bh,
        "equity_curve_points": len(curve),
    }

    monthly = _monthly_returns_table(curve, starting)
    underwater = _underwater_periods(curve)
    attribution = _strategy_attribution(journal)

    summary["monthly_return_months"] = len(monthly)
    summary["underwater_periods"] = len(underwater)
    summary["strategy_count_attributed"] = len(attribution)
    # Sparkline-friendly compact equity series (last 60 points)
    spark = [p.get("equity") for p in curve[-60:] if p.get("equity") is not None]

    return {
        "label": "PAPER / not live audited",
        "generated_at": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
        "equity_curve": curve,
        "equity_sparkline": spark,
        "monthly_returns": monthly,
        "underwater_periods": underwater,
        "strategy_attribution": attribution,
        "scoreboard": board,
        "paper_snapshot": {k: perf.get(k) for k in (
            "mode", "cash", "equity", "starting_cash", "return_pct", "win_rate",
            "closed_trades", "open_trades", "total_fees_paid", "live_note",
        ) if k in (perf or {})},
    }


def paper_report_csv(report: Optional[Dict[str, Any]] = None) -> str:
    """CSV export of equity curve + per-strategy primary metrics."""
    import csv
    import io
    report = report or build_paper_report()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# GAMMA-R PAPER report — not live audited"])
    s = report.get("summary") or {}
    w.writerow(["summary_field", "value"])
    for k, v in s.items():
        if k == "vs_buy_hold":
            continue
        w.writerow([k, v])
    bh = s.get("vs_buy_hold") or {}
    w.writerow(["buy_hold_return_pct", bh.get("return_pct")])
    w.writerow([])
    w.writerow(["equity_t", "equity", "drawdown_pct", "strategy_id"])
    for p in report.get("equity_curve") or []:
        w.writerow([p.get("t"), p.get("equity"), p.get("drawdown_pct"), p.get("strategy_id")])
    w.writerow([])
    w.writerow(["strategy_id", "status", "trades", "win_rate", "expectancy", "profit_factor", "max_dd"])
    for st in (report.get("scoreboard") or {}).get("strategies") or []:
        prim = st.get("primary") or st.get("metrics", {}).get("all") or {}
        w.writerow([
            st.get("strategy_id") or st.get("id"),
            st.get("status"),
            prim.get("trades") or st.get("sample_size"),
            prim.get("win_rate"),
            prim.get("expectancy"),
            prim.get("profit_factor"),
            prim.get("max_dd") or prim.get("max_drawdown"),
        ])
    w.writerow([])
    w.writerow(["month", "end_equity", "return_pct"])
    for m in report.get("monthly_returns") or []:
        w.writerow([m.get("month"), m.get("end_equity"), m.get("return_pct")])
    w.writerow([])
    w.writerow(["underwater_start", "trough", "depth_pct", "recovered", "open"])
    for u in report.get("underwater_periods") or []:
        w.writerow([u.get("start"), u.get("trough"), u.get("depth_pct"), u.get("recovered"), u.get("open")])
    w.writerow([])
    w.writerow(["attr_strategy_id", "trades", "win_rate", "total_pnl", "pct_of_pnl"])
    for a in report.get("strategy_attribution") or []:
        w.writerow([a.get("strategy_id"), a.get("trades"), a.get("win_rate"), a.get("total_pnl"), a.get("pct_of_pnl")])
    return buf.getvalue()

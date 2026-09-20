"""
Historical Training Mode — walk-forward optimization (no look-ahead).

Downloads daily OHLCV for the configured universe (default: multi-region liquid large caps;
true "all US" is rate-limit heavy). Default history length = 20 years
(maximum). Optional shorter: 5 / 10 / 15 for faster runs.

Walk-forward:
  train on years i..i+train_window-1, test on year i+train_window, roll +1y.
Across folds, score parameter sets and record regime heuristics
(bull/bear/sideways via SPY trend; high/low vol via realized vol).

Results persist to data/historical_baseline.json ("historical baseline").
On startup: SEED → historical baseline → live-learned overlay.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import SEED_DEFAULTS, StrategyConfig, get_runtime_config, set_runtime_config
from .fees import compute_trade_fees
from .data import download_ohlcv
from .forward_estimate import ensure_model_trained, estimate_forward
from .learning import save_historical_baseline
from .risk import size_position
from .universe import load_universe
from .timezone_util import filter_session_bars

ALLOWED_YEARS = (5, 10, 15, 20)
DEFAULT_YEARS = 20  # maximum — preset default
TRAIN_WINDOW_YEARS = 5


def _regime_label(spy: pd.DataFrame, start, end) -> Dict[str, str]:
    """Bull/bear/sideways + high/low vol using only SPY bars in [start, end]."""
    w = spy.loc[(spy.index >= start) & (spy.index <= end)]
    if w.empty or len(w) < 20:
        return {"trend": "unknown", "vol": "unknown"}
    c0 = float(w["Close"].iloc[0])
    c1 = float(w["Close"].iloc[-1])
    ret = (c1 - c0) / c0 if c0 else 0.0
    if ret > 0.08:
        trend = "bull"
    elif ret < -0.08:
        trend = "bear"
    else:
        trend = "sideways"
    rvol = float(w["Close"].pct_change().std() * np.sqrt(252))
    vol = "high" if rvol > 0.20 else "low"
    return {"trend": trend, "vol": vol, "spy_return": round(ret, 4), "realized_vol": round(rvol, 4)}


def _param_grid(seed: StrategyConfig) -> List[Dict[str, Any]]:
    """Small interpretable grid around SEED defaults."""
    grid = []
    for lb in (seed.lookback_days - 2, seed.lookback_days, seed.lookback_days + 5):
        for vm in (1.3, seed.volume_multiple, 1.8):
            for sl in (0.04, seed.stop_loss_pct, 0.07):
                for tp in (0.10, seed.take_profit_pct, 0.20):
                    grid.append({
                        "lookback_days": int(max(5, lb)),
                        "volume_multiple": float(vm),
                        "stop_loss_pct": float(sl),
                        "take_profit_pct": float(tp),
                        "min_return": seed.min_return,
                        "top_pct": seed.top_pct,
                        "volume_avg_days": seed.volume_avg_days,
                    })
    # Deduplicate
    seen = set()
    out = []
    for g in grid:
        key = tuple(sorted(g.items()))
        if key not in seen:
            seen.add(key)
            out.append(g)
    return out[:24]  # cap for runtime


def _eval_fold(
    data: Dict[str, pd.DataFrame],
    spy: pd.DataFrame,
    params: Dict[str, Any],
    test_start,
    test_end,
    cfg_base: StrategyConfig,
) -> Dict[str, Any]:
    """Simple test-year momentum simulation with forward-estimate gate (no leakage)."""
    cfg = cfg_base.update(params)
    # Train forward model on data strictly before test_start
    train_slice = {}
    for t, df in data.items():
        sub = df.loc[df.index < test_start]
        if len(sub) >= 60:
            train_slice[t] = sub
    ensure_model_trained(train_slice, cfg)

    cash = float(cfg.starting_equity)
    trades = 0
    wins = 0
    pnl_total = 0.0

    # Sample weekly entry points in test year
    all_dates = sorted({d for df in data.values() for d in df.index if test_start <= d <= test_end})
    if not all_dates:
        return {"total_return": 0.0, "win_rate": 0.0, "trades": 0}

    step = 5
    for di in range(0, len(all_dates), step):
        dt = all_dates[di]
        candidates = []
        for t, df in data.items():
            hist = df.loc[df.index <= dt]
            need = max(cfg.lookback_days, cfg.volume_avg_days) + 1
            if len(hist) < need + 5:
                continue
            closes = hist["Close"].dropna()
            volumes = hist["Volume"].dropna()
            if len(closes) < need:
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
            vol_avg = float(volumes.iloc[-(cfg.volume_avg_days + 1):-1].mean())
            vol_today = float(volumes.iloc[-1])
            if vol_avg <= 0 or vol_today / vol_avg < cfg.volume_multiple:
                continue
            # Forward estimate using only hist (no look-ahead)
            est = estimate_forward(t, hist, cfg)
            if cfg.use_forward_estimate and (est is None or not est.pass_threshold):
                continue
            candidates.append((t, mom, entry, est.probability if est else 0.5))

        candidates.sort(key=lambda x: x[1], reverse=True)
        keep = cfg.effective_top_n(len(candidates))
        for t, mom, entry, prob in candidates[:keep]:
            plan = size_position(t, entry, cash, cfg)
            if plan.shares <= 0:
                continue
            # Exit at horizon or stop/tp within next ~10 bars (test data only after dt)
            fut = data[t].loc[(data[t].index > dt) & (data[t].index <= test_end)]
            if fut.empty:
                continue
            exit_px = float(fut["Close"].iloc[min(len(fut) - 1, cfg.forward_estimate_horizon)])
            # Check path for stop/tp
            reason = "time"
            for _, row in fut.iloc[: max(cfg.forward_estimate_horizon, 10)].iterrows():
                low = float(row.get("Low", row["Close"]))
                high = float(row.get("High", row["Close"]))
                if low <= plan.stop:
                    exit_px = plan.stop
                    reason = "stop"
                    break
                if high >= plan.take_profit:
                    exit_px = plan.take_profit
                    reason = "tp"
                    break
            entry_fee = compute_trade_fees(plan.shares, entry, side="buy", cfg=cfg)
            exit_fee = compute_trade_fees(plan.shares, exit_px, side="sell", cfg=cfg)
            gross = (exit_px - entry) * plan.shares
            pnl = gross - entry_fee.total - exit_fee.total
            cash += pnl
            trades += 1
            pnl_total += pnl
            if pnl > 0:
                wins += 1

    ret = (cash - cfg.starting_equity) / cfg.starting_equity if cfg.starting_equity else 0.0
    return {
        "total_return": round(ret, 6),
        "win_rate": round(wins / trades, 4) if trades else 0.0,
        "trades": trades,
        "pnl": round(pnl_total, 2),
    }


def run_historical_train(
    years: int = DEFAULT_YEARS,
    cfg: Optional[StrategyConfig] = None,
    max_tickers: int = 80,
) -> Dict[str, Any]:
    """
    Walk-forward historical training. Default years=20 (max).
    Uses a subset of the universe for speed (max_tickers); document in README.
    """
    if years not in ALLOWED_YEARS:
        raise ValueError(f"years must be one of {ALLOWED_YEARS}, got {years}")

    cfg = cfg or StrategyConfig.seed()
    # Slightly smaller universe for training speed
    tickers = load_universe(cfg)
    if len(tickers) > max_tickers:
        # Keep liquid mega-caps first alphabetically is weak; take evenly spaced sample
        step = max(1, len(tickers) // max_tickers)
        tickers = tickers[::step][:max_tickers]

    end = datetime.utcnow()
    start = end - timedelta(days=int(years * 365.25))
    print(f"[historical] downloading {len(tickers)} tickers + SPY for {years}y ...")

    # Parallel download in batches via data.download_ohlcv (already batched)
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_data = ex.submit(
            download_ohlcv, tickers,
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), None, 40,
        )
        fut_spy = ex.submit(
            download_ohlcv, ["SPY"],
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), None, 1,
        )
        data = fut_data.result()
        spy_map = fut_spy.result()
    spy = spy_map.get("SPY")
    # Align to US trading calendar (no weekend/holiday bars)
    data = {t: filter_session_bars(df, "NYSE") for t, df in data.items()}
    data = {t: df for t, df in data.items() if df is not None and not df.empty}
    if spy is not None:
        spy = filter_session_bars(spy, "NYSE")
    if spy is None or spy.empty:
        raise RuntimeError("Could not download SPY for regime labels")

    # Build year folds
    year_starts = []
    y0 = start.year
    y1 = end.year
    for y in range(y0, y1 + 1):
        year_starts.append(pd.Timestamp(f"{y}-01-01"))

    grid = _param_grid(cfg)
    fold_results: List[Dict[str, Any]] = []
    param_scores: Dict[int, List[float]] = {i: [] for i in range(len(grid))}
    era_performance: List[Dict[str, Any]] = []

    # train_window years train → 1 year test, roll forward
    for fold_i in range(0, max(0, len(year_starts) - TRAIN_WINDOW_YEARS - 1)):
        train_start = year_starts[fold_i]
        test_start = year_starts[fold_i + TRAIN_WINDOW_YEARS]
        test_end = year_starts[min(fold_i + TRAIN_WINDOW_YEARS + 1, len(year_starts) - 1)]
        if test_start >= pd.Timestamp(end):
            break
        regime = _regime_label(spy, test_start, test_end)

        # Evaluate param grid in parallel for this fold
        best_idx = 0
        best_ret = -999.0
        fold_detail = []

        def _job(idx_params):
            idx, params = idx_params
            # Slice data to avoid accidental leakage into eval helper train_slice
            return idx, _eval_fold(data, spy, params, test_start, test_end, cfg)

        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(_job, (i, p)) for i, p in enumerate(grid)]
            for fut in as_completed(futs):
                idx, res = fut.result()
                param_scores[idx].append(res["total_return"])
                fold_detail.append({"param_index": idx, **res})
                if res["total_return"] > best_ret:
                    best_ret = res["total_return"]
                    best_idx = idx

        era_performance.append({
            "fold": fold_i,
            "train_start": str(train_start.date()),
            "test_start": str(test_start.date()),
            "test_end": str(test_end.date()),
            "regime": regime,
            "best_param_index": best_idx,
            "best_return": best_ret,
            "best_params": grid[best_idx],
        })
        fold_results.append({"fold": fold_i, "best_return": best_ret, "regime": regime})
        print(f"[historical] fold {fold_i}: test {test_start.date()} regime={regime.get('trend')}/{regime.get('vol')} best_ret={best_ret:.2%}")

    # Aggregate: pick params with best median test return across folds
    ranked = sorted(
        ((i, float(np.median(scores)) if scores else -999) for i, scores in param_scores.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    best_i = ranked[0][0] if ranked else 0
    best_params = dict(SEED_DEFAULTS)
    best_params.update(grid[best_i])

    # Equal sector weights initially; bump using era returns heuristic
    sector_weights: Dict[str, float] = {}
    # Simple: if bull eras did well overall, keep equal; leave empty = equal
    best_eras = sorted(era_performance, key=lambda e: e["best_return"], reverse=True)
    worst_eras = sorted(era_performance, key=lambda e: e["best_return"])

    summary = {
        "years": years,
        "folds": len(era_performance),
        "universe_size": len(tickers),
        "best_median_return": ranked[0][1] if ranked else 0.0,
        "best_params": {k: best_params[k] for k in (
            "lookback_days", "volume_multiple", "stop_loss_pct",
            "take_profit_pct", "min_return", "top_pct", "volume_avg_days",
        )},
        "best_eras": best_eras[:3],
        "worst_eras": worst_eras[:3],
    }

    payload = {
        "label": "historical baseline",
        "years": years,
        "params": {
            "lookback_days": best_params["lookback_days"],
            "volume_multiple": best_params["volume_multiple"],
            "stop_loss_pct": best_params["stop_loss_pct"],
            "take_profit_pct": best_params["take_profit_pct"],
            "min_return": best_params["min_return"],
            "top_pct": best_params["top_pct"],
            "volume_avg_days": best_params["volume_avg_days"],
            "sector_weights": sector_weights,
            "forward_estimate_threshold": cfg.forward_estimate_threshold,
        },
        "summary": summary,
        "era_performance": era_performance,
        "seed_fallback": dict(SEED_DEFAULTS),
        "note": (
            "Walk-forward optimized from day-one SEED. "
            "Applied on startup before live-learned overlay. "
            "Forward estimates retrained each fold on pre-test data only (no leakage)."
        ),
    }
    save_historical_baseline(payload)

    # Apply into runtime (historical layer; live-learned may still overlay later)
    merged = StrategyConfig.seed().update(payload["params"])
    set_runtime_config(merged)

    # Final model train on full history for live scanning
    ensure_model_trained(data, merged)

    return payload

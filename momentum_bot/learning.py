"""
Rule-based self-learning loop (interpretable — NOT a neural net).

Day-one SEED baseline (informed momentum defaults, never zeros):
  lookback_days=10, volume_multiple=1.5 (of 20d avg), top_pct=0.10 (top 10%),
  stop_loss_pct=0.05, take_profit_pct=0.15, equal sector weights.

Merge order on startup:
  1) StrategyConfig.seed()  (day-one SEED)
  2) overlay data/historical_baseline.json if present  ("historical baseline")
  3) overlay data/learned_config.json if present       (live paper learning)

Reset restores SEED (and can wipe learned / optionally journal+history).
Historical baseline is separate — reset_learning does not delete it unless asked.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .timezone_util import session_bucket_for_learning
from .fees import fee_impact_summary, describe_defaults as fee_defaults
from .config import (
    SEED_DEFAULTS,
    StrategyConfig,
    get_runtime_config,
    reset_runtime_to_seed,
    set_runtime_config,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
JOURNAL_PATH = DATA_DIR / "trade_journal.json"
LEARNED_PATH = DATA_DIR / "learned_config.json"
HISTORY_PATH = DATA_DIR / "learning_history.json"
HISTORICAL_PATH = DATA_DIR / "historical_baseline.json"

LEARNABLE = (
    "lookback_days",
    "volume_multiple",
    "min_return",
    "stop_loss_pct",
    "take_profit_pct",
    "top_pct",
    "top_n",
)

CLAMPS = {
    "lookback_days": (5, 60),
    "volume_multiple": (1.0, 3.0),
    "min_return": (0.0, 0.25),
    "stop_loss_pct": (0.02, 0.12),
    "take_profit_pct": (0.05, 0.40),
    "top_pct": (0.05, 0.30),
    "top_n": (5, 50),
    "sector_weight": (0.25, 2.0),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, obj: Any) -> None:
    _ensure_dir()
    path.write_text(json.dumps(obj, indent=2))


def day_one_baseline() -> Dict[str, Any]:
    return {
        "label": "Day one baseline (SEED)",
        "description": (
            "Informed momentum defaults: 10-day lookback, 1.5x of 20-day volume, "
            "top 10% gainers, 5% stop / 15% take-profit, equal sector weights."
        ),
        "params": dict(SEED_DEFAULTS),
    }


def load_journal() -> List[Dict[str, Any]]:
    raw = _read_json(JOURNAL_PATH, {"entries": []})
    if isinstance(raw, list):
        return raw
    return list(raw.get("entries", []))


def save_journal(entries: List[Dict[str, Any]]) -> None:
    _write_json(JOURNAL_PATH, {"entries": entries, "updated_at": _utc_now()})


def record_closed_trade(
    *,
    ticker: str,
    entry: float,
    exit: float,
    shares: int,
    return_pct: float,
    exit_reason: str,
    opened_at: Optional[str] = None,
    closed_at: Optional[str] = None,
    source: str = "scan",
    sector: Optional[str] = None,
    signal_params: Optional[Dict[str, Any]] = None,
    position_id: Optional[str] = None,
    fees: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    confidence: Optional[float] = None,
    origin: str = "paper",
) -> Dict[str, Any]:
    cfg = get_runtime_config()
    params = dict(signal_params) if signal_params else {
        k: cfg.to_dict().get(k) for k in LEARNABLE
    }
    reason = (exit_reason or "manual").lower()
    if reason in ("stop", "sl"):
        reason = "stop_loss"
    elif reason in ("tp", "takeprofit", "take_profit"):
        reason = "take_profit"
    elif reason not in ("stop_loss", "take_profit", "manual", "time", "end"):
        reason = "manual"

    if sector is None:
        sector = _guess_sector(ticker)

    origin_tag = (origin or "paper").strip().lower() or "paper"
    if origin_tag not in ("paper", "external", "paper_options"):
        origin_tag = "paper"
    ctx = dict(context or {})
    ctx.setdefault("origin", origin_tag)

    entry_row = {
        "id": position_id or f"j-{len(load_journal()) + 1}",
        "ticker": ticker.upper().replace(".", "-"),
        "sector": sector or "Unknown",
        "entry": round(float(entry), 4),
        "exit": round(float(exit), 4),
        "shares": int(shares),
        "return_pct": round(float(return_pct), 6),
        "exit_reason": reason,
        "source": source,
        "origin": origin_tag,
        "opened_at": opened_at,
        "closed_at": closed_at or _utc_now(),
        "signal_params": params,
        "recorded_at": _utc_now(),
        "learned": False,
        "session_bucket": session_bucket_for_learning(
            ticker=ticker,
        ),
        "strategy_id": ctx.get("strategy_id") or (signal_params or {}).get("strategy_id"),
        "firewall": ctx.get("firewall"),
        "context": ctx,
        "confidence": round(float(confidence), 4) if confidence is not None else (
            round(float(ctx.get("confidence")), 4)
            if ctx.get("confidence") is not None else None
        ),
    }
    if fees:
        entry_row["entry_fees"] = round(float(fees.get("entry_fees") or 0), 4)
        entry_row["exit_fees"] = round(float(fees.get("exit_fees") or 0), 4)
        entry_row["total_fees"] = round(float(fees.get("total_fees") or 0), 4)
        if fees.get("gross_pnl") is not None:
            entry_row["gross_pnl"] = round(float(fees["gross_pnl"]), 2)
        if fees.get("net_pnl") is not None:
            entry_row["net_pnl"] = round(float(fees["net_pnl"]), 2)
            entry_row["realized_pnl"] = entry_row["net_pnl"]
    entries = load_journal()
    entries.append(entry_row)
    save_journal(entries)

    unlearned = [e for e in entries if not e.get("learned")]
    min_n = int(cfg.learning_min_trades or 10)
    auto = None
    if len(unlearned) >= min_n:
        auto = run_learning(force=True, reason=f"auto after {len(unlearned)} closed trades")
    return {"entry": entry_row, "auto_learning": auto}


def _guess_sector(ticker: str) -> str:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return info.get("sector") or info.get("industry") or "Unknown"
    except Exception:
        return "Unknown"


def load_learned_config() -> Dict[str, Any]:
    return _read_json(LEARNED_PATH, {})


def save_learned_config(params: Dict[str, Any]) -> None:
    _write_json(LEARNED_PATH, {
        "label": "live-learned",
        "params": params,
        "baseline": dict(SEED_DEFAULTS),
        "updated_at": _utc_now(),
        "note": "Evolved from paper-trade journal via rule-based learning",
    })


def load_historical_baseline() -> Dict[str, Any]:
    return _read_json(HISTORICAL_PATH, {})


def save_historical_baseline(payload: Dict[str, Any]) -> None:
    payload = dict(payload)
    payload.setdefault("label", "historical baseline")
    payload["updated_at"] = _utc_now()
    _write_json(HISTORICAL_PATH, payload)


def apply_learned_on_startup() -> StrategyConfig:
    """
    Merge order:
      seed -> historical_baseline (if any) -> learned_config (if any)
        -> runtime_config.json (user Settings + auto-loop flags)
    """
    from .config import load_runtime_overlay

    seed = StrategyConfig.seed()
    hist = load_historical_baseline()
    hist_params = hist.get("params") if isinstance(hist, dict) else None
    cfg = seed.update(hist_params) if hist_params else seed

    learned = load_learned_config()
    live_params = learned.get("params") if isinstance(learned, dict) else None
    if live_params:
        cfg = cfg.update(live_params)

    runtime_overlay = load_runtime_overlay()
    if runtime_overlay:
        cfg = cfg.update(runtime_overlay)

    set_runtime_config(cfg)
    return cfg


def load_history() -> List[Dict[str, Any]]:
    raw = _read_json(HISTORY_PATH, {"adjustments": []})
    if isinstance(raw, list):
        return raw
    return list(raw.get("adjustments", []))


def _append_history(batch: Dict[str, Any]) -> None:
    hist = load_history()
    hist.append(batch)
    _write_json(HISTORY_PATH, {"adjustments": hist, "updated_at": _utc_now()})


def _clamp(name: str, value: float) -> float:
    lo, hi = CLAMPS.get(name, (None, None))
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    if name in ("lookback_days", "top_n"):
        return int(round(value))
    return round(float(value), 6)


def run_learning(force: bool = False, reason: str = "manual") -> Dict[str, Any]:
    cfg = get_runtime_config()
    entries = load_journal()
    unlearned = [e for e in entries if not e.get("learned")]
    min_n = int(cfg.learning_min_trades or 10)

    if not force and len(unlearned) < min_n:
        return {
            "ran": False,
            "reason": f"need {min_n} unlearned closes, have {len(unlearned)}",
            "unlearned": len(unlearned),
            "min_trades": min_n,
        }

    sample = unlearned if unlearned else entries[-min_n:]
    if not sample:
        return {"ran": False, "reason": "no journal entries to learn from"}

    before = {k: cfg.to_dict().get(k) for k in list(LEARNABLE) + ["sector_weights"]}
    adjustments: List[Dict[str, Any]] = []
    new_vals = dict(before)

    n = len(sample)
    wins = [e for e in sample if float(e.get("return_pct") or 0) > 0]
    losses = [e for e in sample if float(e.get("return_pct") or 0) <= 0]
    win_rate = len(wins) / n if n else 0.0
    stops = [e for e in sample if e.get("exit_reason") == "stop_loss"]
    tps = [e for e in sample if e.get("exit_reason") == "take_profit"]
    stop_rate = len(stops) / n if n else 0.0
    tp_rate = len(tps) / n if n else 0.0

    short_lb_losses = [
        e for e in losses
        if int((e.get("signal_params") or {}).get("lookback_days") or cfg.lookback_days) <= 12
    ]

    if win_rate < 0.45 and (len(short_lb_losses) >= max(2, n // 4) or cfg.lookback_days <= 12):
        old = int(new_vals["lookback_days"])
        new = _clamp("lookback_days", old + 2)
        if new != old:
            new_vals["lookback_days"] = new
            adjustments.append({
                "param": "lookback_days", "before": old, "after": new,
                "why": (
                    f"Win rate {win_rate:.0%} on recent {n} trades with short lookback — "
                    f"increased lookback_days {old} → {new}."
                ),
            })

    if stop_rate >= 0.40:
        old_sl = float(new_vals["stop_loss_pct"])
        new_sl = _clamp("stop_loss_pct", old_sl + 0.005)
        if new_sl != old_sl:
            new_vals["stop_loss_pct"] = new_sl
            adjustments.append({
                "param": "stop_loss_pct", "before": old_sl, "after": new_sl,
                "why": f"Stops hit on {stop_rate:.0%} — widened stop {old_sl:.3f} → {new_sl:.3f}.",
            })
        old_mr = float(new_vals["min_return"])
        new_mr = _clamp("min_return", old_mr + 0.01)
        if new_mr != old_mr:
            new_vals["min_return"] = new_mr
            adjustments.append({
                "param": "min_return", "before": old_mr, "after": new_mr,
                "why": f"Frequent stops — raised min_return {old_mr:.3f} → {new_mr:.3f}.",
            })
        old_vm = float(new_vals["volume_multiple"])
        new_vm = _clamp("volume_multiple", old_vm + 0.1)
        if new_vm != old_vm:
            new_vals["volume_multiple"] = new_vm
            adjustments.append({
                "param": "volume_multiple", "before": old_vm, "after": new_vm,
                "why": f"Frequent stops — raised volume_multiple {old_vm:.2f} → {new_vm:.2f}.",
            })

    if tp_rate >= 0.35 and win_rate >= 0.5:
        old_tp = float(new_vals["take_profit_pct"])
        new_tp = _clamp("take_profit_pct", old_tp + 0.02)
        if new_tp != old_tp:
            new_vals["take_profit_pct"] = new_tp
            adjustments.append({
                "param": "take_profit_pct", "before": old_tp, "after": new_tp,
                "why": (
                    f"TPs hit on {tp_rate:.0%} with win rate {win_rate:.0%} — "
                    f"raised take_profit_pct {old_tp:.3f} → {new_tp:.3f}."
                ),
            })

    if win_rate >= 0.65 and n >= min_n:
        old_vm = float(new_vals["volume_multiple"])
        new_vm = _clamp("volume_multiple", old_vm + 0.05)
        if new_vm != old_vm and not any(a["param"] == "volume_multiple" for a in adjustments):
            new_vals["volume_multiple"] = new_vm
            adjustments.append({
                "param": "volume_multiple", "before": old_vm, "after": new_vm,
                "why": f"Strong win rate {win_rate:.0%} — nudged volume_multiple upward.",
            })

    # --- Richer context learning (news / volume proxy / user notes / confidence) ---
    try:
        from .feedback import learning_context_signals
        ctx_sig = learning_context_signals(sample)
    except Exception:
        ctx_sig = {}

    # User dislike on wins is rare; dislike-heavy losses → tighten filters
    dislike_n = int(ctx_sig.get("user_dislike_n") or 0)
    dislike_wr = ctx_sig.get("user_dislike_win_rate")
    if dislike_n >= 2 and dislike_wr is not None and dislike_wr < 0.40:
        old_vm = float(new_vals["volume_multiple"])
        new_vm = _clamp("volume_multiple", old_vm + 0.1)
        if new_vm != old_vm and not any(a["param"] == "volume_multiple" for a in adjustments):
            new_vals["volume_multiple"] = new_vm
            adjustments.append({
                "param": "volume_multiple", "before": old_vm, "after": new_vm,
                "why": (
                    f"User dislike notes on {dislike_n} trades with win rate {dislike_wr:.0%} — "
                    f"raised volume_multiple {old_vm:.2f} → {new_vm:.2f}."
                ),
            })
        old_mr = float(new_vals["min_return"])
        new_mr = _clamp("min_return", old_mr + 0.01)
        if new_mr != old_mr and not any(a["param"] == "min_return" for a in adjustments):
            new_vals["min_return"] = new_mr
            adjustments.append({
                "param": "min_return", "before": old_mr, "after": new_mr,
                "why": f"User dislikes correlated with weak outcomes — raised min_return.",
            })

    like_n = int(ctx_sig.get("user_like_n") or 0)
    like_wr = ctx_sig.get("user_like_win_rate")
    if like_n >= 3 and like_wr is not None and like_wr >= 0.60:
        # Liked winners → slightly relax volume gate if not already tightened this batch
        if not any(a["param"] == "volume_multiple" for a in adjustments):
            old_vm = float(new_vals["volume_multiple"])
            new_vm = _clamp("volume_multiple", max(1.0, old_vm - 0.05))
            if new_vm != old_vm:
                new_vals["volume_multiple"] = new_vm
                adjustments.append({
                    "param": "volume_multiple", "before": old_vm, "after": new_vm,
                    "why": (
                        f"User likes on {like_n} trades wr={like_wr:.0%} — "
                        f"nudged volume_multiple {old_vm:.2f} → {new_vm:.2f}."
                    ),
                })

    # Bearish news entries that lost → reinforce news_block / raise min_return
    bear_n = int(ctx_sig.get("news_bearish_n") or 0)
    bear_wr = ctx_sig.get("news_bearish_entry_win_rate")
    if bear_n >= 2 and bear_wr is not None and bear_wr < 0.35:
        old_mr = float(new_vals["min_return"])
        new_mr = _clamp("min_return", old_mr + 0.015)
        if new_mr != old_mr and not any(a["param"] == "min_return" for a in adjustments):
            new_vals["min_return"] = new_mr
            adjustments.append({
                "param": "min_return", "before": old_mr, "after": new_mr,
                "why": (
                    f"Bearish-news entries wr={bear_wr:.0%} on {bear_n} — "
                    f"raised min_return (prefer stronger momentum when news fights the tape)."
                ),
            })

    # Volume surge winners → trust volume_multiple slightly lower barrier already handled;
    # surge losers → raise volume quality bar
    surge_n = int(ctx_sig.get("volume_surge_n") or 0)
    surge_wr = ctx_sig.get("volume_surge_win_rate")
    if surge_n >= 3 and surge_wr is not None and surge_wr < 0.40:
        old_vm = float(new_vals["volume_multiple"])
        new_vm = _clamp("volume_multiple", old_vm + 0.15)
        if new_vm != old_vm:
            new_vals["volume_multiple"] = new_vm
            adjustments.append({
                "param": "volume_multiple", "before": old_vm, "after": new_vm,
                "why": f"Volume-surge proxy entries wr={surge_wr:.0%} — demand even stronger volume.",
            })

    # Bear regime poor outcomes → widen stops slightly (chop) or raise min_return
    bear_reg_n = int(ctx_sig.get("bear_regime_n") or 0)
    bear_reg_wr = ctx_sig.get("bear_regime_win_rate")
    if bear_reg_n >= 3 and bear_reg_wr is not None and bear_reg_wr < 0.40:
        old_sl = float(new_vals["stop_loss_pct"])
        new_sl = _clamp("stop_loss_pct", old_sl + 0.005)
        if new_sl != old_sl and not any(a["param"] == "stop_loss_pct" for a in adjustments):
            new_vals["stop_loss_pct"] = new_sl
            adjustments.append({
                "param": "stop_loss_pct", "before": old_sl, "after": new_sl,
                "why": f"Bear/high-vol regime entries wr={bear_reg_wr:.0%} — widened stop.",
            })

    # Persist min_confidence nudge from high-conf outcomes
    cfg_dict_extra = cfg.to_dict()
    if "min_confidence" in cfg_dict_extra:
        hc_n = int(ctx_sig.get("high_confidence_n") or 0)
        hc_wr = ctx_sig.get("high_confidence_win_rate")
        cur_mc = float(cfg_dict_extra.get("min_confidence") or 0.45)
        if hc_n >= 4 and hc_wr is not None and hc_wr >= 0.60:
            new_mc = round(min(0.75, cur_mc + 0.02), 4)
            if new_mc != cur_mc:
                new_vals["min_confidence"] = new_mc
                adjustments.append({
                    "param": "min_confidence", "before": cur_mc, "after": new_mc,
                    "why": f"High-confidence trades wr={hc_wr:.0%} — raised auto min_confidence gate.",
                })
        elif hc_n >= 4 and hc_wr is not None and hc_wr < 0.40:
            new_mc = round(max(0.25, cur_mc - 0.02), 4)
            if new_mc != cur_mc:
                new_vals["min_confidence"] = new_mc
                adjustments.append({
                    "param": "min_confidence", "before": cur_mc, "after": new_mc,
                    "why": f"High-confidence trades underperformed wr={hc_wr:.0%} — lowered gate to re-evaluate.",
                })

    sector_rets: Dict[str, List[float]] = {}
    for e in sample:
        sec = e.get("sector") or "Unknown"
        sector_rets.setdefault(sec, []).append(float(e.get("return_pct") or 0))
    weights = dict(cfg.sector_weights or {})
    for sec, rets in sector_rets.items():
        if sec == "Unknown" or len(rets) < 2:
            continue
        avg = sum(rets) / len(rets)
        cur = float(weights.get(sec, 1.0))
        if avg > 0.02:
            nxt = _clamp("sector_weight", cur + 0.1)
            why = f"Sector {sec} avg return {avg:.1%} — weight {cur:.2f} → {nxt:.2f}."
        elif avg < -0.02:
            nxt = _clamp("sector_weight", cur - 0.1)
            why = f"Sector {sec} avg return {avg:.1%} — weight {cur:.2f} → {nxt:.2f}."
        else:
            continue
        if nxt != cur:
            weights[sec] = nxt
            adjustments.append({
                "param": f"sector_weights.{sec}", "before": cur, "after": nxt, "why": why,
            })
    new_vals["sector_weights"] = weights

    updated = cfg.update({k: v for k, v in new_vals.items() if k in cfg.to_dict()})
    set_runtime_config(updated)
    save_learned_config(updated.to_dict())
    try:
        from .config import save_runtime_overlay
        save_runtime_overlay(updated)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: could not persist runtime_config.json: {exc}")

    ids = {e.get("id") for e in sample}
    for e in entries:
        if e.get("id") in ids:
            e["learned"] = True
    save_journal(entries)

    batch = {
        "at": _utc_now(),
        "trigger": reason,
        "sample_size": n,
        "win_rate": round(win_rate, 4),
        "stop_rate": round(stop_rate, 4),
        "take_profit_rate": round(tp_rate, 4),
        "context_signals": ctx_sig if isinstance(ctx_sig, dict) else {},
        "before": before,
        "after": {k: updated.to_dict().get(k) for k in list(LEARNABLE) + ["sector_weights"]},
        "baseline": {k: SEED_DEFAULTS.get(k) for k in list(LEARNABLE) + ["sector_weights"]},
        "adjustments": adjustments,
    }
    _append_history(batch)

    return {
        "ran": True,
        "reason": reason,
        "sample_size": n,
        "win_rate": round(win_rate, 4),
        "adjustments": adjustments,
        "before": before,
        "after": batch["after"],
        "baseline": batch["baseline"],
        "at": batch["at"],
    }


def learning_stats() -> Dict[str, Any]:
    cfg = get_runtime_config()
    entries = load_journal()
    hist = load_history()
    learned_file = load_learned_config()
    hist_base = load_historical_baseline()

    n = len(entries)
    wins = sum(1 for e in entries if float(e.get("return_pct") or 0) > 0)
    wr_series = []
    w = 0
    for i, e in enumerate(entries, 1):
        if float(e.get("return_pct") or 0) > 0:
            w += 1
        wr_series.append({"n": i, "win_rate": round(w / i, 4), "at": e.get("closed_at")})

    current = {
        k: cfg.to_dict().get(k)
        for k in list(LEARNABLE) + ["sector_weights", "volume_avg_days"]
    }
    baseline = {k: SEED_DEFAULTS.get(k) for k in current}
    hist_params = hist_base.get("params") or {}

    # Fee impact from journal (paper closes)
    fee_impact = fee_impact_summary(entries, starting_equity=float(cfg.starting_equity or 0))
    cfg_d = cfg.to_dict()
    fee_settings = {
        "fees_enabled": bool(cfg_d.get("fees_enabled", True)),
        "commission_mode": cfg_d.get("commission_mode", "per_share"),
        "commission_per_share": cfg_d.get("commission_per_share", 0.005),
        "commission_flat": cfg_d.get("commission_flat", 1.0),
        "slippage_pct": cfg_d.get("slippage_pct", 0.001),
        "defaults": fee_defaults(),
    }

    paper_entries = [e for e in entries if (e.get("origin") or "paper") != "external"]
    external_entries = [e for e in entries if e.get("origin") == "external"]
    def _bucket(ents):
        nn = len(ents)
        ww = sum(1 for e in ents if float(e.get("return_pct") or 0) > 0)
        return {
            "count": nn,
            "wins": ww,
            "losses": nn - ww,
            "win_rate": round(ww / nn, 4) if nn else 0.0,
            "unlearned": sum(1 for e in ents if not e.get("learned")),
        }
    origin_breakdown = {
        "paper": _bucket(paper_entries),
        "external": _bucket(external_entries),
        "combined": _bucket(entries),
        "note": (
            "Combined learning samples include external imports. "
            "Paper portfolio equity remains app-paper only."
        ),
    }
    try:
        from .external_trades import learning_stats_by_origin, load_import_meta
        origin_breakdown = learning_stats_by_origin()
    except Exception:
        pass

    # Fee impact on paper-only (keep paper money separate)
    fee_impact_paper = fee_impact_summary(
        paper_entries, starting_equity=float(cfg.starting_equity or 0),
    )

    return {
        "day_one_baseline": day_one_baseline(),
        "historical_baseline": {
            "label": hist_base.get("label", "historical baseline"),
            "present": bool(hist_params),
            "params": hist_params,
            "years": hist_base.get("years"),
            "summary": hist_base.get("summary"),
            "era_performance": hist_base.get("era_performance"),
            "updated_at": hist_base.get("updated_at"),
        },
        "live_learned": {
            "label": "live-learned",
            "present": bool(learned_file.get("params")),
            "params": learned_file.get("params") or {},
            "updated_at": learned_file.get("updated_at"),
        },
        "current_params": current,
        "evolved_vs_baseline": {
            k: {
                "day_one": baseline.get(k),
                "historical": hist_params.get(k, baseline.get(k)),
                "current": current[k],
                "changed_from_seed": baseline.get(k) != current[k],
            }
            for k in current
        },
        "merge_order": [
            "1. Day-one SEED defaults",
            "2. historical_baseline.json (if present)",
            "3. learned_config.json live overlay (if present)",
            "4. runtime_config.json (Settings + auto-loop flags)",
        ],
        "journal_count": n,
        "journal_count_paper": len(paper_entries),
        "journal_count_external": len(external_entries),
        "wins": wins,
        "losses": n - wins,
        "win_rate": round(wins / n, 4) if n else 0.0,
        "win_rate_over_time": wr_series[-50:],
        "unlearned": sum(1 for e in entries if not e.get("learned")),
        "learning_min_trades": cfg.learning_min_trades,
        "adjustment_batches": len(hist),
        "last_learning_at": hist[-1]["at"] if hist else None,
        "fee_impact": fee_impact_paper,
        "fee_settings": fee_settings,
        "total_fees_paid": fee_impact_paper.get("total_fees_paid"),
        "fees_as_pct_of_gross_profit": fee_impact_paper.get("fees_as_pct_of_gross_profit"),
        "gross_return_pct": fee_impact_paper.get("gross_return_pct"),
        "net_return_pct": fee_impact_paper.get("net_return_pct"),
        "by_origin": origin_breakdown,
        "external_import": True,
        "overnight_web": _overnight_web_block(),
        "updated_at": _utc_now(),
    }



def _overnight_web_block() -> Dict[str, Any]:
    """Surface overnight allowlisted web digest inside Learning stats."""
    try:
        from .edge import load_overnight_learning_digest
        dig = load_overnight_learning_digest() or {}
        return {
            "present": bool(dig.get("present") or dig.get("ok")),
            "note_count": int(dig.get("note_count") or 0),
            "topics": list(dig.get("topics") or [])[:12],
            "bullets": list(dig.get("bullets") or [])[:6],
            "updated_at": dig.get("updated_at"),
            "label": dig.get("label") or "Overnight web → learning summary",
            "educational": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {"present": False, "note_count": 0, "error": str(exc)[:120]}

def reset_learning(
    wipe_journal: bool = False,
    wipe_history: bool = True,
    wipe_historical: bool = False,
) -> Dict[str, Any]:
    """Restore day-one SEED defaults (not zeros)."""
    if LEARNED_PATH.exists():
        LEARNED_PATH.unlink()
    if wipe_history and HISTORY_PATH.exists():
        HISTORY_PATH.unlink()
    if wipe_journal and JOURNAL_PATH.exists():
        JOURNAL_PATH.unlink()
    if wipe_historical and HISTORICAL_PATH.exists():
        HISTORICAL_PATH.unlink()

    # Re-apply remaining layers (historical may still exist)
    cfg = apply_learned_on_startup()
    if wipe_historical or not load_historical_baseline().get("params"):
        cfg = reset_runtime_to_seed()

    return {
        "reset": True,
        "restored": "day_one_SEED" + (" + historical baseline" if load_historical_baseline().get("params") else ""),
        "params": cfg.to_dict(),
        "baseline": day_one_baseline(),
        "journal_wiped": wipe_journal,
        "history_wiped": wipe_history,
        "historical_wiped": wipe_historical,
        "at": _utc_now(),
    }


def set_journal_feedback(
    entry_id: str,
    *,
    rating: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach like/dislike + note to a journal entry (and mirror open/closed paper pos)."""
    from .feedback import apply_user_feedback

    entries = load_journal()
    found = None
    for e in entries:
        if e.get("id") == entry_id:
            apply_user_feedback(e, rating=rating, note=note)
            found = e
            break
    if found is None:
        raise KeyError(f"journal entry {entry_id} not found")
    save_journal(entries)
    return {"id": entry_id, "context": found.get("context"), "return_pct": found.get("return_pct")}


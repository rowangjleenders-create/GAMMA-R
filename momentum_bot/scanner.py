"""
Momentum scanner with watchlist, forward-estimate / ensemble gate,
advanced entry filters, and regime-aware sizing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from .config import StrategyConfig
from .data import required_history_days
from .data_sources import get_data_source
from .forward_estimate import compute_features_at, ensure_model_trained
from .optimization import detect_regime, entry_filters, ensemble_estimate, train_ensemble
from .risk import size_position
from .universe import load_universe
from .news import collect_news, aggregate_ticker_news, news_priority_boost, blend_score, sector_sentiment_impact
from .timezone_util import (
    exchange_for_ticker,
    get_session,
    get_ticker_session,
    session_bucket_for_learning,
    should_allow_new_entry,
)


@dataclass
class Signal:
    ticker: str
    momentum_pct: float
    entry: float
    volume: float
    volume_avg: float
    volume_ratio: float
    stop: float
    take_profit: float
    shares: int
    position_value: float
    dollar_risk: float
    source: str = "scan"
    as_of: str = ""
    forward_probability: Optional[float] = None
    forward_confidence: Optional[float] = None
    forward_horizon: Optional[int] = None
    forward_pass: Optional[bool] = None
    forward_model: Optional[str] = None
    ensemble_votes: Optional[Dict[str, float]] = None
    filter_metrics: Optional[Dict[str, float]] = None
    regime: Optional[str] = None
    regime_size_mult: Optional[float] = None
    news_score_24h: Optional[float] = None
    news_score_7d: Optional[float] = None
    news_spike: Optional[bool] = None
    news_warning: Optional[bool] = None
    news_boost: Optional[bool] = None
    news_headlines: Optional[list] = None
    blended_score: Optional[float] = None
    session_label: Optional[str] = None  # open|pre|after|closed|holiday
    after_hours: Optional[bool] = None
    time_display: Optional[str] = None  # dual TZ label
    time_utc: Optional[str] = None
    session_bucket: Optional[str] = None  # us_rth|us_extended|asia|...
    confidence: Optional[float] = None  # 0..1 combined trade confidence
    # Multi-strategy suite
    strategy_id: Optional[str] = None
    strategy_rationale: Optional[str] = None
    suggested_size_mult: Optional[float] = None
    side: Optional[str] = None  # long|short|flat

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_LAST_SIGNALS: List[Signal] = []
_LAST_NEWS_IMPACT: list = []
_CACHE_AT: float = 0.0
_CACHE_TTL_SEC: float = 60.0  # owner convenience: brief reuse


def get_cached_signals() -> List[Signal]:
    return list(_LAST_SIGNALS)


def _effective_cache_ttl(cfg=None) -> float:
    """TTL from runtime config when available; falls back to module default."""
    try:
        from .config import get_runtime_config
        cfg = cfg or get_runtime_config()
        ttl = float(
            getattr(cfg, "scan_cache_ttl_sec", None)
            or getattr(cfg, "scan_cache_ttl_sec", None)
            or _CACHE_TTL_SEC
        )
        return max(15.0, min(900.0, ttl))
    except Exception:
        return float(_CACHE_TTL_SEC)


def get_scan_status() -> Dict[str, Any]:
    """Owner-facing snapshot of the in-memory scan cache (no network)."""
    import time as _time

    now = _time.time()
    age = (now - _CACHE_AT) if _CACHE_AT else None
    signals = list(_LAST_SIGNALS)
    as_of = ""
    if signals:
        as_of = getattr(signals[0], "as_of", "") or ""
        if not as_of and getattr(signals[0], "time_utc", None):
            as_of = str(signals[0].time_utc)
    watch_n = sum(1 for s in signals if getattr(s, "source", "") == "watchlist")
    market_n = len(signals) - watch_n
    ttl = _effective_cache_ttl()
    fresh = bool(_CACHE_AT and age is not None and age < ttl)
    stale_warn = 180.0
    try:
        from .config import get_runtime_config
        stale_warn = float(
            getattr(get_runtime_config(), "scan_stale_warn_sec", None)
            or getattr(get_runtime_config(), "scan_stale_warn_sec", None)
            or 180
        )
    except Exception:
        pass
    stale_warning = bool(age is not None and age >= stale_warn)
    # Data source freshness label
    data_mode = "delayed"
    data_label = "DELAYED (free)"
    feed_badge = "Delayed"
    try:
        from .data_sources import get_data_source_status
        ds = get_data_source_status() or {}
        feed_badge = ds.get("feed_badge") or "Delayed"
        data_label = ds.get("data_label") or data_label
        if ds.get("realtime_sip_enabled") and not ds.get("fallback_active"):
            data_mode = "realtime_sip" if feed_badge == "SIP" else "realtime_iex"
        elif ds.get("fallback_active"):
            data_mode = "delayed_fallback"
            feed_badge = "Delayed"
            data_label = ds.get("data_label") or "DELAYED (fallback from realtime)"
        else:
            data_mode = "delayed_free"
    except Exception:
        pass
    last_scan_iso = None
    if _CACHE_AT:
        from datetime import datetime, timezone
        last_scan_iso = datetime.fromtimestamp(_CACHE_AT, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "cached_count": len(signals),
        "watchlist_signals": watch_n,
        "market_signals": market_n,
        "cache_at_epoch": _CACHE_AT or None,
        "cache_age_sec": round(age, 1) if age is not None else None,
        "cache_ttl_sec": ttl,
        "cache_fresh": fresh,
        "stale_warning": stale_warning,
        "stale_warn_sec": stale_warn,
        "last_scan_at": last_scan_iso,
        "data_mode": data_mode,
        "data_label": data_label,
        "feed_badge": feed_badge,
        "not_level2": True,
        "as_of": as_of or None,
        "top_tickers": [s.ticker for s in signals[:8]],
        "has_cache": bool(signals),
        "scan_kind": getattr(get_scan_status, "_last_kind", "full"),
    }


def get_news_impact() -> list:
    return list(_LAST_NEWS_IMPACT)


def _momentum_and_volume(df, cfg: StrategyConfig):
    """Classic 12–1 momentum ranking + volume confirmation."""
    from .strategies.base import classic_momentum_return

    if df is None or "Close" not in getattr(df, "columns", []) or "Volume" not in getattr(df, "columns", []):
        return None
    closes = df["Close"].dropna()
    volumes = df["Volume"].dropna()
    lookback = int(getattr(cfg, "momentum_lookback_days", 252) or 252)
    skip = int(getattr(cfg, "momentum_skip_days", 21) or 21)
    short_fb = int(getattr(cfg, "lookback_days", 10) or 10)
    vol_need = int(cfg.volume_avg_days) + 1
    if len(volumes) < vol_need:
        return None
    entry = float(closes.iloc[-1]) if len(closes) else None
    if entry is None or entry < cfg.min_price:
        return None
    cm = classic_momentum_return(
        df, lookback=lookback, skip=skip, short_fallback=short_fb
    )
    if cm is None:
        return None
    momentum, mom_meta = cm
    if momentum < cfg.min_return:
        return None
    vol_window = volumes.iloc[-(cfg.volume_avg_days + 1) : -1]
    if len(vol_window) < cfg.volume_avg_days:
        return None
    vol_avg = float(vol_window.mean())
    vol_today = float(volumes.iloc[-1])
    if vol_avg <= 0:
        return None
    vol_ratio = vol_today / vol_avg
    if vol_ratio < cfg.volume_multiple:
        return None
    return {
        "momentum_pct": momentum,
        "entry": entry,
        "volume": vol_today,
        "volume_avg": vol_avg,
        "volume_ratio": vol_ratio,
        "momentum_meta": mom_meta,
    }


def _score_ticker(ticker, df, cfg, equity, source, as_of, regime, news_items=None, session_info=None, *, apply_min_return=True):
    from dataclasses import replace

    # Per-ticker home-session gate for NEW scan entries (watchlist still labeled)
    if source != "watchlist":
        allow, gate_reason, t_sess = should_allow_new_entry(ticker, cfg)
        if not allow:
            return None
        if t_sess is not None:
            session_info = t_sess
    elif session_info and cfg.only_act_during_open and not session_info.is_open and source != "watchlist":
        return None
    local_cfg = cfg if apply_min_return else replace(cfg, min_return=-1.0)
    metrics = _momentum_and_volume(df, local_cfg)
    if metrics is None:
        return None

    # Advanced filters (vol / ADX / MA)
    filt = entry_filters(df, cfg)
    if not filt.ok and source != "watchlist":
        return None

    # Forward / ensemble estimate — features from last bar only (no look-ahead)
    feats = compute_features_at(df, len(df) - 1)
    ens = None
    if feats is not None and (cfg.use_forward_estimate or cfg.use_ensemble):
        if cfg.use_ensemble:
            ens = ensemble_estimate(feats, cfg)
            if cfg.use_forward_estimate and not ens.pass_consensus and source != "watchlist":
                return None
        else:
            from .forward_estimate import estimate_forward
            est = estimate_forward(ticker, df, cfg)
            if cfg.use_forward_estimate and (est is None or not est.pass_threshold) and source != "watchlist":
                return None
            if est:
                ens = type("E", (), {
                    "probability": est.probability,
                    "confidence": est.confidence,
                    "pass_consensus": est.pass_threshold,
                    "votes": {"single": est.probability},
                    "model": est.model,
                })()

    # News sentiment (no look-ahead: items already filtered by as_of)
    news_agg = None
    news_adj = 0.0
    if cfg.use_news_sentiment and news_items is not None:
        news_agg = aggregate_ticker_news(news_items, ticker, cfg=cfg)
        news_adj = news_priority_boost(news_agg, cfg)
        if news_agg.warning and source != "watchlist" and getattr(cfg, "news_block_on_negative", True):
            # Sudden negative → skip new entries (warning still shown on watchlist)
            return None

    # Regime sizing
    mult = regime.size_multiplier if regime else 1.0
    if regime and regime.pause_entries and source != "watchlist":
        return None
    sized_equity = equity * mult

    plan = size_position(ticker, metrics["entry"], sized_equity, cfg)
    blended = blend_score(metrics["momentum_pct"], news_adj, cfg)
    sig = Signal(
        ticker=ticker,
        momentum_pct=round(metrics["momentum_pct"], 6),
        entry=plan.entry,
        volume=round(metrics["volume"], 2),
        volume_avg=round(metrics["volume_avg"], 2),
        volume_ratio=round(metrics["volume_ratio"], 4),
        stop=plan.stop,
        take_profit=plan.take_profit,
        shares=plan.shares,
        position_value=plan.position_value,
        dollar_risk=plan.dollar_risk,
        source=source,
        as_of=as_of,
        forward_probability=getattr(ens, "probability", None) if ens else None,
        forward_confidence=getattr(ens, "confidence", None) if ens else None,
        forward_horizon=cfg.forward_estimate_horizon,
        forward_pass=getattr(ens, "pass_consensus", None) if ens else None,
        forward_model=getattr(ens, "model", "ensemble") if ens else None,
        ensemble_votes=getattr(ens, "votes", None) if ens else None,
        filter_metrics=filt.metrics,
        regime=regime.label if regime else None,
        regime_size_mult=mult,
        news_score_24h=news_agg.score_24h if news_agg else None,
        news_score_7d=news_agg.score_7d if news_agg else None,
        news_spike=news_agg.spike if news_agg else None,
        news_warning=news_agg.warning if news_agg else None,
        news_boost=news_agg.boost if news_agg else None,
        news_headlines=news_agg.headlines if news_agg else None,
        blended_score=round(blended, 6),
        session_label=session_info.session if session_info else None,
        after_hours=bool(session_info and session_info.session in ("pre", "after", "closed", "holiday")),
        time_display=session_info.dual_label if session_info else None,
        time_utc=session_info.utc_iso if session_info else as_of,
        session_bucket=session_bucket_for_learning(
            exchange_for_ticker(ticker, default=getattr(cfg, "market_exchange", "NYSE") or "NYSE"),
            ticker=ticker,
        ),
    )
    try:
        from .confidence import compute_confidence
        sig.confidence = compute_confidence(
            momentum_pct=sig.momentum_pct,
            volume_ratio=sig.volume_ratio,
            forward_probability=sig.forward_probability,
            forward_confidence=sig.forward_confidence,
            ensemble_votes=sig.ensemble_votes,
            cfg=cfg,
        )
    except Exception:
        sig.confidence = None
    sig.strategy_id = "momentum"
    mom_meta = (metrics.get("momentum_meta") or {}) if isinstance(metrics, dict) else {}
    mode = mom_meta.get("mode", "12_1")
    if mode == "12_1":
        sig.strategy_rationale = (
            f"12–1 momentum {sig.momentum_pct*100:.1f}% "
            f"(lookback {mom_meta.get('lookback_days', getattr(cfg, 'momentum_lookback_days', 252))}d "
            f"skip {mom_meta.get('skip_days', getattr(cfg, 'momentum_skip_days', 21))}d) "
            f"with volume {sig.volume_ratio:.2f}× avg"
        )
    else:
        sig.strategy_rationale = (
            f"Momentum {sig.momentum_pct*100:.1f}% ({mode}) with volume "
            f"{sig.volume_ratio:.2f}× avg"
        )
    sig.suggested_size_mult = float(mult or 1.0)
    sig.side = "long"
    return sig


def run_scan(cfg=None, watchlist=None, *, equity=None):
    global _LAST_SIGNALS, _LAST_NEWS_IMPACT, _CACHE_AT
    import time as _time
    # Brief cache (~45s) so owner pull-refresh / dashboard focus doesn't hammer Yahoo
    ttl = _effective_cache_ttl(cfg) if cfg is not None else _effective_cache_ttl()
    if _LAST_SIGNALS and (_time.time() - _CACHE_AT) < ttl:
        return list(_LAST_SIGNALS)
    cfg = cfg or StrategyConfig()
    equity = float(equity if equity is not None else cfg.starting_equity)
    watchlist = [t.strip().upper().replace(".", "-") for t in (watchlist or []) if t]

    universe = load_universe(cfg)
    tickers = list(dict.fromkeys(list(universe) + watchlist))

    mom_lb = int(getattr(cfg, 'momentum_lookback_days', 252) or 252)
    mom_skip = int(getattr(cfg, 'momentum_skip_days', 21) or 21)
    cal_days = max(
        required_history_days(mom_lb + mom_skip, cfg.volume_avg_days),
        required_history_days(cfg.lookback_days, cfg.volume_avg_days),
        450,
    )
    start = (datetime.utcnow() - timedelta(days=cal_days)).strftime("%Y-%m-%d")
    # Live path: free (default) or Alpaca SIP when enabled; historical training never uses SIP.
    src = get_data_source(purpose="live")
    data = src.download_ohlcv(tickers, start=start, batch_size=50)

    regime = None
    if cfg.use_regime_filter:
        try:
            regime = detect_regime(cfg=cfg)
        except Exception as exc:
            print(f"Warning: regime detect failed: {exc}")

    if cfg.use_ensemble:
        try:
            train_ensemble(data, horizon=int(cfg.forward_estimate_horizon or 3))
        except Exception as exc:
            print(f"Warning: ensemble train failed: {exc}")
            try:
                ensure_model_trained(data, cfg)
            except Exception:
                pass
    elif cfg.use_forward_estimate:
        try:
            ensure_model_trained(data, cfg)
        except Exception as exc:
            print(f"Warning: forward model train failed: {exc}")

    as_of = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    news_items = []
    news_impact = []
    if cfg.use_news_sentiment:
        try:
            news_items = collect_news(tickers=tickers)
            news_impact = sector_sentiment_impact(news_items)
        except Exception as exc:
            print(f"Warning: news collect failed: {exc}")
    session_info = get_session(
        exchange=getattr(cfg, "market_exchange", "NYSE") or "NYSE",
        user_tz=getattr(cfg, "user_timezone", "America/Chicago") or "America/Chicago",
        allow_after_hours_signals=bool(getattr(cfg, "allow_after_hours_signals", True)),
    )
    if bool(getattr(cfg, "session_gate_entries", True)) or cfg.only_act_during_open:
        print(
            f"Session gate on (per_ticker={bool(getattr(cfg, 'use_per_ticker_sessions', True))}); "
            f"default exchange {session_info.exchange} is {session_info.session} — "
            "new entries require home market open"
        )
    watch_set = set(watchlist)
    _LAST_NEWS_IMPACT.clear()
    _LAST_NEWS_IMPACT.extend(news_impact)
    market_signals: List[Signal] = []
    watch_signals: List[Signal] = []

    for ticker, df in data.items():
        if ticker in watch_set:
            sig = _score_ticker(ticker, df, cfg, equity, "watchlist", as_of, regime, news_items, session_info)
            if sig is None:
                sig = _score_ticker(
                    ticker, df, cfg, equity, "watchlist", as_of, regime, news_items, session_info, apply_min_return=False
                )
            if sig is not None:
                watch_signals.append(sig)
            continue
        sig = _score_ticker(ticker, df, cfg, equity, "scan", as_of, regime, news_items, session_info)
        if sig is not None:
            market_signals.append(sig)

    market_signals.sort(key=lambda s: (s.blended_score if s.blended_score is not None else s.momentum_pct), reverse=True)
    keep = cfg.effective_top_n(len(market_signals))
    market_signals = market_signals[:keep]
    watch_signals.sort(key=lambda s: s.momentum_pct, reverse=True)
    seen = {s.ticker for s in watch_signals}
    combined = list(watch_signals) + [s for s in market_signals if s.ticker not in seen]

    # Multi-strategy suite: merge non-momentum strategies when enabled.
    # Momentum-only (others off) keeps classic path unchanged aside from tags.
    try:
        from .strategies.runner import (
            generate_strategy_signals,
            only_momentum_enabled,
            strategy_signals_to_scanner_signals,
        )
        if not only_momentum_enabled(cfg):
            # Exclude momentum plugin duplicates — classic path already scored momentum
            strat_sigs, _decision, _cycle = generate_strategy_signals(
                list(data.keys()),
                data,
                cfg,
                regime=regime,
                news_items=news_items,
            )
            strat_sigs = [s for s in strat_sigs if s.strategy_id != "momentum"]
            extra = strategy_signals_to_scanner_signals(
                strat_sigs, cfg, equity=equity, regime=regime, as_of=as_of, source="scan",
            )
            # Apply vol-target / router size already baked into suggested_size_mult;
            # merge: prefer higher blended/confidence, keep watchlist first
            have = {s.ticker for s in combined}
            for s in extra:
                if s.ticker in have:
                    # Replace if multi-strategy score is stronger
                    for i, existing in enumerate(combined):
                        if existing.ticker != s.ticker:
                            continue
                        ex_score = existing.blended_score if existing.blended_score is not None else existing.momentum_pct
                        new_score = s.blended_score if s.blended_score is not None else s.momentum_pct
                        if (new_score or 0) > (ex_score or 0) and existing.source != "watchlist":
                            combined[i] = s
                        elif existing.source != "watchlist" and not getattr(existing, "strategy_id", None):
                            existing.strategy_id = getattr(s, "strategy_id", existing.strategy_id)
                        break
                else:
                    combined.append(s)
                    have.add(s.ticker)
            combined.sort(
                key=lambda s: (0 if s.source == "watchlist" else 1, -(s.blended_score if s.blended_score is not None else s.momentum_pct or 0)),
            )
        else:
            # Still record router cycle for dashboard (momentum + optional vol-target)
            generate_strategy_signals(
                list(data.keys())[:1] or ["SPY"],
                data if data else {},
                cfg,
                regime=regime,
                news_items=news_items,
            )
    except Exception as exc:
        print(f"Warning: multi-strategy merge failed: {exc}")

    _CACHE_AT = __import__("time").time()
    get_scan_status._last_kind = "full"  # type: ignore[attr-defined]

    _LAST_SIGNALS = combined
    return combined


def signals_to_dicts(signals):
    return [s.to_dict() for s in signals]




def _maybe_intraday_breakout_watchlist(cfg, watchlist, *, equity=None):
    """
    Optional shorter bars (15m/1h) for watchlist breakout when configured.
    Does NOT replace daily bars used by classic 12-1 momentum.
    Returns list of Signal-like dicts / Signal objects tagged with bar_interval.
    """
    iv = str(getattr(cfg, "watchlist_bar_interval", "1d") or "1d").strip().lower()
    if iv in ("1d", "d", "day", "daily", ""):
        return [], {"skipped": True, "reason": "daily_default", "interval": "1d"}
    if iv not in ("15m", "30m", "1h", "60m"):
        return [], {"skipped": True, "reason": f"unsupported_interval:{iv}", "interval": iv}
    if iv == "60m":
        iv = "1h"
    enabled = getattr(cfg, "strategy_enabled", None) or {}
    if isinstance(enabled, dict) and enabled.get("breakout") is False:
        return [], {"skipped": True, "reason": "breakout_disabled", "interval": iv}

    wl = [t.strip().upper().replace(".", "-") for t in (watchlist or []) if t]
    if not wl:
        return [], {"skipped": True, "reason": "empty_watchlist", "interval": iv}

    period = str(getattr(cfg, "watchlist_intraday_period", "5d") or "5d")
    try:
        from .data import download_ohlcv_intraday
        from .strategies.breakout import BreakoutStrategy
        bars = download_ohlcv_intraday(wl, interval=iv, period=period, batch_size=20)
    except Exception as exc:  # noqa: BLE001
        return [], {"skipped": True, "reason": f"download_failed:{exc}", "interval": iv}

    if not bars:
        return [], {"skipped": True, "reason": "no_intraday_bars", "interval": iv}

    try:
        strat = BreakoutStrategy()
        # Shorter lookback for intraday bars (e.g. 20 bars of 15m ≈ 5h)
        from copy import deepcopy
        # Use a lightweight shim: mutate lookback temporarily via a thin wrapper cfg
        class _CfgShim:
            def __init__(self, base, **over):
                self._base = base
                self._over = over
            def __getattr__(self, name):
                if name in self._over:
                    return self._over[name]
                return getattr(self._base, name)
        lookback = 20 if iv == "1h" else 16
        shim = _CfgShim(cfg, breakout_lookback=lookback)
        raw = strat.generate_signals(list(bars.keys()), bars, shim)
    except Exception as exc:  # noqa: BLE001
        return [], {"skipped": True, "reason": f"breakout_failed:{exc}", "interval": iv}

    # Convert StrategySignal → scanner Signal when possible
    out = []
    for ss in raw:
        meta = dict(getattr(ss, "meta", None) or {})
        meta["bar_interval"] = iv
        meta["intraday_watchlist"] = True
        try:
            ss.meta = meta
        except Exception:
            pass
        out.append(ss)

    return out, {
        "skipped": False,
        "interval": iv,
        "period": period,
        "tickers": len(wl),
        "bars": len(bars),
        "signals": len(out),
    }


def quick_scan(cfg=None, watchlist=None, *, equity=None, extra_tickers=None):
    """
    Fast path: refresh watchlist + optional hot names only (not full universe).

    Merges into the existing cache (watchlist/hot overwrite; other market
    signals retained until a full scan). Use for Dashboard "Quick scan".
    """
    global _LAST_SIGNALS, _CACHE_AT
    import time as _time

    cfg = cfg or StrategyConfig()
    equity = float(equity if equity is not None else cfg.starting_equity)
    try:
        from .watchlist import load_watchlist
        wl = list(watchlist) if watchlist is not None else load_watchlist()
    except Exception:
        wl = list(watchlist or [])
    wl = [t.strip().upper().replace(".", "-") for t in wl if t]
    hot = [t.strip().upper().replace(".", "-") for t in (extra_tickers or []) if t]
    if not hot:
        hot = [s.ticker for s in _LAST_SIGNALS if getattr(s, "source", "") != "watchlist"][:15]
    tickers = list(dict.fromkeys(wl + hot))
    if not tickers:
        return {
            "count": len(_LAST_SIGNALS),
            "signals": signals_to_dicts(_LAST_SIGNALS),
            "scan_status": get_scan_status(),
            "note": "Quick scan: empty watchlist and no hot names — add watchlist tickers or run a full scan first.",
            "scan_kind": "quick",
            "refreshed": [],
            "watchlist": wl,
            "watchlist_bar_interval": getattr(cfg, "watchlist_bar_interval", "1d"),
            "intraday_breakout": {"skipped": True, "reason": "empty_watchlist"},
        }

    mom_lb = int(getattr(cfg, "momentum_lookback_days", 252) or 252)
    mom_skip = int(getattr(cfg, "momentum_skip_days", 21) or 21)
    cal_days = max(
        required_history_days(mom_lb + mom_skip, cfg.volume_avg_days),
        required_history_days(cfg.lookback_days, cfg.volume_avg_days),
        450,
    )
    start = (datetime.utcnow() - timedelta(days=cal_days)).strftime("%Y-%m-%d")
    src = get_data_source(purpose="live")
    data = src.download_ohlcv(tickers, start=start, batch_size=50)

    regime = None
    if getattr(cfg, "use_regime_filter", True):
        try:
            regime = detect_regime(cfg=cfg)
        except Exception as exc:
            print(f"Warning: quick_scan regime detect failed: {exc}")

    as_of = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    news_items = []
    if getattr(cfg, "use_news_sentiment", False):
        try:
            news_items = collect_news(tickers=tickers)
        except Exception as exc:
            print(f"Warning: quick_scan news failed: {exc}")

    session_info = get_session(
        exchange=getattr(cfg, "market_exchange", "NYSE") or "NYSE",
        user_tz=getattr(cfg, "user_timezone", "America/Chicago") or "America/Chicago",
        allow_after_hours_signals=bool(getattr(cfg, "allow_after_hours_signals", True)),
    )

    watch_set = set(wl)
    refreshed = []
    new_by_ticker = {}
    for ticker, df in data.items():
        source = "watchlist" if ticker in watch_set else "scan"
        sig = _score_ticker(ticker, df, cfg, equity, source, as_of, regime, news_items, session_info)
        if sig is None and source == "watchlist":
            sig = _score_ticker(
                ticker, df, cfg, equity, source, as_of, regime, news_items, session_info,
                apply_min_return=False,
            )
        if sig is not None:
            new_by_ticker[ticker] = sig
            refreshed.append(ticker)

    merged = []
    seen = set()
    for t in wl:
        if t in new_by_ticker:
            merged.append(new_by_ticker[t])
            seen.add(t)
    for s in list(_LAST_SIGNALS):
        if s.ticker in seen:
            continue
        if s.ticker in new_by_ticker:
            merged.append(new_by_ticker[s.ticker])
            seen.add(s.ticker)
        else:
            merged.append(s)
            seen.add(s.ticker)
    for t, sig in new_by_ticker.items():
        if t not in seen:
            merged.append(sig)
            seen.add(t)

    _LAST_SIGNALS = merged
    _CACHE_AT = _time.time()
    get_scan_status._last_kind = "quick"  # type: ignore[attr-defined]
    intraday_sigs, intraday_meta = _maybe_intraday_breakout_watchlist(cfg, wl, equity=equity)
    intraday_note = ""
    if intraday_sigs and not intraday_meta.get("skipped"):
        # Tag matching watchlist signals with intraday breakout meta (non-destructive)
        by_t = {getattr(s, "ticker", None): s for s in intraday_sigs}
        for s in merged:
            if s.ticker in by_t:
                ss = by_t[s.ticker]
                try:
                    s.strategy_id = getattr(s, "strategy_id", None) or "breakout"
                    extra = dict(getattr(s, "meta", None) or {}) if hasattr(s, "meta") else {}
                    # Signal may not have meta — stash on rationale suffix
                    s.strategy_rationale = (
                        (getattr(s, "strategy_rationale", None) or "")
                        + f" | intraday {intraday_meta.get('interval')} breakout"
                    ).strip(" |")
                    if hasattr(s, "strategy_id"):
                        pass
                except Exception:
                    pass
        intraday_note = (
            f" Intraday {intraday_meta.get('interval')} breakout: "
            f"{intraday_meta.get('signals', 0)} hit(s) on watchlist."
        )
    elif intraday_meta and not intraday_meta.get("skipped"):
        intraday_note = f" Intraday path ran with 0 hits ({intraday_meta.get('interval')})."

    return {
        "count": len(merged),
        "signals": signals_to_dicts(merged),
        "scan_status": get_scan_status(),
        "refreshed": refreshed,
        "watchlist": wl,
        "scan_kind": "quick",
        "watchlist_bar_interval": getattr(cfg, "watchlist_bar_interval", "1d"),
        "intraday_breakout": intraday_meta,
        "note": (
            f"Quick scan refreshed {len(refreshed)} ticker(s) (watchlist+hot). "
            "Full universe unchanged until next full scan."
            + intraday_note
        ),
        "data_source": None,
    }

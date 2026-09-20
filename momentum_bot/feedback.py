"""
Structured feedback / context tags for richer learning.

At entry we tag trades with news sentiment, volume-pressure proxies
(honest — not Level 2), macro/regime/session context. Users can later
add like/dislike + free-text notes. Tags persist into the trade journal
and feed rule-based learning.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import StrategyConfig, get_runtime_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def volume_pressure_proxy(
    *,
    volume_ratio: Optional[float] = None,
    filter_metrics: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Honest volume/trade-intensity proxy from daily bars — NOT Level 2 order flow.

    Labels:
      surge | elevated | normal | light
    """
    vr = float(volume_ratio or 1.0)
    realized_vol = None
    if filter_metrics and isinstance(filter_metrics, dict):
        realized_vol = filter_metrics.get("realized_vol") or filter_metrics.get("vol")
    if vr >= 2.5:
        label = "surge"
        pressure = min(1.0, 0.5 + (vr - 2.5) * 0.15)
    elif vr >= 1.5:
        label = "elevated"
        pressure = 0.35 + (vr - 1.5) * 0.15
    elif vr >= 1.0:
        label = "normal"
        pressure = 0.2 + (vr - 1.0) * 0.3
    else:
        label = "light"
        pressure = max(0.0, vr * 0.2)
    return {
        "proxy": "volume_ratio_vs_avg",
        "not_level2": True,
        "note": "Bar volume intensity proxy only — no Level 2 / true order-flow feed",
        "volume_ratio": round(vr, 4),
        "label": label,
        "pressure_score": round(float(pressure), 4),
        "realized_vol": round(float(realized_vol), 4) if realized_vol is not None else None,
    }


def build_entry_context(
    *,
    ticker: str,
    signal: Optional[Any] = None,
    cfg: Optional[StrategyConfig] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build rich context tags at decision/entry time.
    Accepts a Signal dataclass, dict, or loose fields via extra.
    """
    cfg = cfg or get_runtime_config()
    sig = signal
    g = (lambda k, default=None: (
        (sig.get(k) if isinstance(sig, dict) else getattr(sig, k, default))
        if sig is not None else default
    ))

    news = {
        "score_24h": g("news_score_24h"),
        "score_7d": g("news_score_7d"),
        "spike": g("news_spike"),
        "warning": g("news_warning"),
        "boost": g("news_boost"),
        "headlines": (g("news_headlines") or [])[:3],
    }
    # Align label
    s24 = news["score_24h"]
    if s24 is None:
        news["alignment"] = "unknown"
    elif float(s24) >= float(getattr(cfg, "news_positive_threshold", 0.4) or 0.4):
        news["alignment"] = "bullish"
    elif float(s24) <= float(getattr(cfg, "news_negative_threshold", -0.4) or -0.4):
        news["alignment"] = "bearish"
    else:
        news["alignment"] = "neutral"

    vol_proxy = volume_pressure_proxy(
        volume_ratio=g("volume_ratio"),
        filter_metrics=g("filter_metrics"),
    )

    # Macro / regime / session
    regime = g("regime")
    session_label = g("session_label")
    after_hours = g("after_hours")
    try:
        from .optimization import get_last_regime
        last = get_last_regime()
        if last and not regime:
            regime = last.label
        macro_metrics = last.metrics if last else {}
    except Exception:
        macro_metrics = {}

    try:
        from .timezone_util import (
            exchange_for_ticker,
            get_session,
            get_ticker_session,
            maintenance_window_status,
        )
        tkr = ticker or g("ticker") or ""
        if bool(getattr(cfg, "use_per_ticker_sessions", True)) and tkr:
            sess = get_ticker_session(
                tkr,
                user_tz=getattr(cfg, "user_timezone", "America/Chicago") or "America/Chicago",
                default_exchange=getattr(cfg, "market_exchange", "NYSE") or "NYSE",
            )
        else:
            sess = get_session(
                exchange=getattr(cfg, "market_exchange", "NYSE") or "NYSE",
                user_tz=getattr(cfg, "user_timezone", "America/Chicago") or "America/Chicago",
            )
        if not session_label:
            session_label = sess.session
            after_hours = not sess.is_open
        maint = maintenance_window_status(
            exchange=exchange_for_ticker(tkr) if tkr else (getattr(cfg, "market_exchange", "NYSE") or "NYSE"),
            open_buffer_minutes=int(getattr(cfg, "maintenance_open_buffer_minutes", 15) or 15),
            close_buffer_minutes=int(getattr(cfg, "maintenance_close_buffer_minutes", 15) or 15),
            enabled=bool(getattr(cfg, "maintenance_windows_enabled", True)),
            ticker=tkr or None,
        )
    except Exception:
        maint = {}
        sess = None

    home_ex = None
    try:
        from .timezone_util import exchange_for_ticker as _ex_for
        home_ex = _ex_for(ticker or g("ticker") or "")
    except Exception:
        home_ex = None
    macro = {
        "regime": regime,
        "regime_size_mult": g("regime_size_mult"),
        "session": session_label,
        "after_hours": bool(after_hours) if after_hours is not None else None,
        "session_bucket": g("session_bucket"),
        "home_exchange": home_ex or (sess.exchange if sess else None),
        "maintenance_active": bool(maint.get("active")) if maint else None,
        "index_trend": (macro_metrics or {}).get("trend") or (macro_metrics or {}).get("spy_trend"),
        "vix": (macro_metrics or {}).get("vix"),
        "spy_return_20d": (macro_metrics or {}).get("spy_ret_20") or (macro_metrics or {}).get("ret_20"),
        "note": "Regime from SPY/VIX heuristics when available",
    }

    confidence = g("confidence")
    ctx: Dict[str, Any] = {
        "ticker": (ticker or g("ticker") or "").upper().replace(".", "-"),
        "tagged_at": _utc_now(),
        "news": news,
        "volume_pressure": vol_proxy,
        "macro": macro,
        "momentum_pct": g("momentum_pct"),
        "volume_ratio": g("volume_ratio"),
        "forward_probability": g("forward_probability"),
        "forward_pass": g("forward_pass"),
        "ensemble_votes": g("ensemble_votes"),
        "confidence": round(float(confidence), 4) if confidence is not None else None,
        "blended_score": g("blended_score"),
        "strategy_id": g("strategy_id") or "momentum",
        "strategy_rationale": g("strategy_rationale"),
        "suggested_size_mult": g("suggested_size_mult"),
        "side": g("side") or "long",
        "user_feedback": {
            "rating": None,  # like | dislike | null
            "note": "",
            "updated_at": None,
        },
    }
    if extra:
        # allow caller overrides (shallow)
        for k, v in extra.items():
            if k == "user_feedback" and isinstance(v, dict):
                ctx["user_feedback"].update(v)
            else:
                ctx[k] = v
    return ctx


def apply_user_feedback(
    target: Dict[str, Any],
    *,
    rating: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Mutate context/user_feedback on a position or journal entry."""
    ctx = dict(target.get("context") or {})
    fb = dict(ctx.get("user_feedback") or {"rating": None, "note": "", "updated_at": None})
    if rating is not None:
        r = (rating or "").strip().lower()
        if r in ("", "none", "clear", "null"):
            fb["rating"] = None
        elif r in ("like", "up", "thumbsup", "+1", "good"):
            fb["rating"] = "like"
        elif r in ("dislike", "down", "thumbsdown", "-1", "bad"):
            fb["rating"] = "dislike"
        else:
            raise ValueError("rating must be like, dislike, or null")
    if note is not None:
        fb["note"] = str(note)[:2000]
    fb["updated_at"] = _utc_now()
    ctx["user_feedback"] = fb
    target["context"] = ctx
    return ctx


def learning_context_signals(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate richer context from journal sample for rule-based learning.
    Returns hints the learner can act on.
    """
    n = len(entries) or 1
    likes_win = likes_loss = dislikes_win = dislikes_loss = 0
    news_aligned_wins = news_aligned_n = 0
    news_misaligned_wins = news_misaligned_n = 0
    surge_wins = surge_n = 0
    bear_regime_n = bear_regime_wins = 0
    high_conf_wins = high_conf_n = 0

    for e in entries:
        won = float(e.get("return_pct") or 0) > 0
        ctx = e.get("context") or {}
        fb = (ctx.get("user_feedback") or {}) if isinstance(ctx, dict) else {}
        rating = fb.get("rating")
        if rating == "like":
            likes_win += int(won)
            likes_loss += int(not won)
        elif rating == "dislike":
            dislikes_win += int(won)
            dislikes_loss += int(not won)

        news = ctx.get("news") or {}
        align = news.get("alignment")
        if align == "bullish":
            news_aligned_n += 1
            news_aligned_wins += int(won)
        elif align == "bearish":
            news_misaligned_n += 1
            news_misaligned_wins += int(won)

        vp = ctx.get("volume_pressure") or {}
        if vp.get("label") == "surge":
            surge_n += 1
            surge_wins += int(won)

        macro = ctx.get("macro") or {}
        if (macro.get("regime") or "").lower() in ("bear", "high_vol", "bear_highvol"):
            bear_regime_n += 1
            bear_regime_wins += int(won)

        conf = ctx.get("confidence")
        if conf is None:
            conf = e.get("confidence")
        if conf is not None and float(conf) >= 0.65:
            high_conf_n += 1
            high_conf_wins += int(won)

    def _rate(w: int, tot: int) -> Optional[float]:
        return round(w / tot, 4) if tot else None

    return {
        "sample_size": len(entries),
        "user_like_win_rate": _rate(likes_win, likes_win + likes_loss),
        "user_like_n": likes_win + likes_loss,
        "user_dislike_win_rate": _rate(dislikes_win, dislikes_win + dislikes_loss),
        "user_dislike_n": dislikes_win + dislikes_loss,
        "news_bullish_win_rate": _rate(news_aligned_wins, news_aligned_n),
        "news_bullish_n": news_aligned_n,
        "news_bearish_entry_win_rate": _rate(news_misaligned_wins, news_misaligned_n),
        "news_bearish_n": news_misaligned_n,
        "volume_surge_win_rate": _rate(surge_wins, surge_n),
        "volume_surge_n": surge_n,
        "bear_regime_win_rate": _rate(bear_regime_wins, bear_regime_n),
        "bear_regime_n": bear_regime_n,
        "high_confidence_win_rate": _rate(high_conf_wins, high_conf_n),
        "high_confidence_n": high_conf_n,
    }

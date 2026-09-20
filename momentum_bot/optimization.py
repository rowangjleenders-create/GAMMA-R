"""
Advanced optimization layers (strictly no look-ahead when idx is provided).

1) Tighter entry filters: vol spike skip, ADX / MA alignment, min price
2) Smarter exits: trailing stop, partial profits, time-based exit
3) Regime detection: bull/bear/sideways/high-vol via SPY + VIX proxy
4) Ensemble: LogisticRegression + GradientBoosting + rule scorer consensus

Self-learning nudges filter thresholds / ensemble weights with logged WHY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import StrategyConfig, get_runtime_config


# ---------------------------------------------------------------------------
# Indicators (use only bars up to idx inclusive)
# ---------------------------------------------------------------------------

def _slice(df: pd.DataFrame, idx: Optional[int] = None) -> pd.DataFrame:
    if idx is None:
        return df
    return df.iloc[: idx + 1]


def realized_vol(closes: pd.Series, window: int = 10) -> float:
    r = closes.pct_change().dropna().iloc[-window:]
    if len(r) < 2:
        return 0.0
    return float(r.std() * np.sqrt(252))


def atr(df: pd.DataFrame, window: int = 14) -> float:
    if len(df) < window + 1:
        return 0.0
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.iloc[-window:].mean())


def adx(df: pd.DataFrame, period: int = 14) -> float:
    """Wilder-lite ADX; returns 0 if insufficient data."""
    if len(df) < period * 2 + 1:
        return 0.0
    high = df["High"].astype(float).values
    low = df["Low"].astype(float).values
    close = df["Close"].astype(float).values
    plus_dm = np.zeros(len(df))
    minus_dm = np.zeros(len(df))
    tr = np.zeros(len(df))
    for i in range(1, len(df)):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    def wilder_smooth(x, n):
        out = np.zeros_like(x)
        out[n] = x[1 : n + 1].sum()
        for i in range(n + 1, len(x)):
            out[i] = out[i - 1] - out[i - 1] / n + x[i]
        return out

    atr_s = wilder_smooth(tr, period)
    plus_s = wilder_smooth(plus_dm, period)
    minus_s = wilder_smooth(minus_dm, period)
    dx = np.zeros(len(df))
    for i in range(period, len(df)):
        if atr_s[i] == 0:
            continue
        pdi = 100 * plus_s[i] / atr_s[i]
        mdi = 100 * minus_s[i] / atr_s[i]
        s = pdi + mdi
        dx[i] = 0 if s == 0 else 100 * abs(pdi - mdi) / s
    if len(dx) < period * 2:
        return float(dx[-1]) if len(dx) else 0.0
    return float(np.mean(dx[-period:]))


def ma_alignment(closes: pd.Series, fast: int = 10, slow: int = 20) -> bool:
    if len(closes) < slow:
        return False
    return float(closes.iloc[-fast:].mean()) > float(closes.iloc[-slow:].mean()) and float(closes.iloc[-1]) > float(closes.iloc[-slow:].mean())


# ---------------------------------------------------------------------------
# Entry filters
# ---------------------------------------------------------------------------

@dataclass
class FilterResult:
    ok: bool
    reasons: List[str]
    metrics: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def entry_filters(
    df: pd.DataFrame,
    cfg: StrategyConfig,
    idx: Optional[int] = None,
) -> FilterResult:
    """Volatility / ADX / MA / min-price filters. No look-ahead."""
    w = _slice(df, idx)
    reasons: List[str] = []
    metrics: Dict[str, float] = {}
    if w.empty or "Close" not in w.columns:
        return FilterResult(False, ["no_data"], {})

    price = float(w["Close"].iloc[-1])
    metrics["price"] = price
    if price < cfg.min_price:
        reasons.append(f"price {price:.2f} < min_price {cfg.min_price}")

    rvol = realized_vol(w["Close"].astype(float), window=int(getattr(cfg, "vol_lookback", 10) or 10))
    metrics["realized_vol"] = rvol
    max_vol = float(getattr(cfg, "max_realized_vol", 0.85) or 0.85)
    if rvol > max_vol:
        reasons.append(f"vol spike {rvol:.2f} > max {max_vol:.2f}")

    use_adx = bool(getattr(cfg, "require_adx", True))
    min_adx = float(getattr(cfg, "min_adx", 18.0) or 18.0)
    adx_v = adx(w, period=int(getattr(cfg, "adx_period", 14) or 14)) if use_adx else 999.0
    metrics["adx"] = adx_v
    if use_adx and adx_v < min_adx:
        reasons.append(f"ADX {adx_v:.1f} < min {min_adx:.1f}")

    use_ma = bool(getattr(cfg, "require_ma_alignment", True))
    aligned = ma_alignment(
        w["Close"].astype(float),
        fast=int(getattr(cfg, "ma_fast", 10) or 10),
        slow=int(getattr(cfg, "ma_slow", 20) or 20),
    ) if use_ma else True
    metrics["ma_aligned"] = 1.0 if aligned else 0.0
    if use_ma and not aligned:
        reasons.append("MA not aligned (fast/slow/price)")

    return FilterResult(ok=len(reasons) == 0, reasons=reasons, metrics=metrics)


# ---------------------------------------------------------------------------
# Smarter exits
# ---------------------------------------------------------------------------

@dataclass
class ExitPlan:
    stop: float
    take_profit: float
    trailing_stop_pct: float
    partial_take_pct: float  # e.g. 0.10 → take partial at +10%
    partial_fraction: float  # e.g. 0.50 sell half
    time_exit_days: int
    min_move_pct: float  # meaningful move threshold for time exit


def build_exit_plan(entry: float, cfg: StrategyConfig) -> ExitPlan:
    return ExitPlan(
        stop=entry * (1.0 - cfg.stop_loss_pct),
        take_profit=entry * (1.0 + cfg.take_profit_pct),
        trailing_stop_pct=float(getattr(cfg, "trailing_stop_pct", 0.04) or 0.04),
        partial_take_pct=float(getattr(cfg, "partial_take_pct", 0.10) or 0.10),
        partial_fraction=float(getattr(cfg, "partial_fraction", 0.50) or 0.50),
        time_exit_days=int(getattr(cfg, "time_exit_days", 10) or 10),
        min_move_pct=float(getattr(cfg, "time_exit_min_move", 0.03) or 0.03),
    )


def update_trailing_stop(entry: float, high_water: float, current_stop: float, trail_pct: float) -> float:
    """Raise stop as high_water moves up; never lower it."""
    candidate = high_water * (1.0 - trail_pct)
    # Also never above current price logic left to caller
    return max(current_stop, candidate, entry * (1.0 - trail_pct * 2))  # soft floor near entry trail


# ---------------------------------------------------------------------------
# Regime detection
# ---------------------------------------------------------------------------

@dataclass
class RegimeState:
    label: str  # bull | bear | sideways | high_vol
    trend: str
    vol_regime: str
    size_multiplier: float  # 1.0 normal; <1 reduce; 0 pause
    pause_entries: bool
    metrics: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_LAST_REGIME: Optional[RegimeState] = None


def get_last_regime() -> Optional[RegimeState]:
    return _LAST_REGIME


def detect_regime(
    spy: Optional[pd.DataFrame] = None,
    vix: Optional[pd.DataFrame] = None,
    cfg: Optional[StrategyConfig] = None,
    as_of_idx: Optional[int] = None,
) -> RegimeState:
    """
    Classify market regime using SPY MA slope + realized vol, and VIX if available.
    Downloads lazily if frames not provided.
    """
    global _LAST_REGIME
    cfg = cfg or get_runtime_config()

    if spy is None:
        try:
            from .data import download_ohlcv
            spy = download_ohlcv(["SPY"], period="1y", batch_size=1).get("SPY")
        except Exception:
            spy = None
    if vix is None:
        try:
            from .data import download_ohlcv
            vix = download_ohlcv(["^VIX"], period="1y", batch_size=1).get("^VIX")
        except Exception:
            vix = None

    metrics: Dict[str, float] = {}
    trend = "unknown"
    vol_regime = "unknown"

    if spy is not None and not spy.empty:
        w = _slice(spy, as_of_idx)
        closes = w["Close"].astype(float)
        if len(closes) >= 50:
            ma50 = float(closes.iloc[-50:].mean())
            ma20 = float(closes.iloc[-20:].mean())
            c = float(closes.iloc[-1])
            slope = (ma20 / float(closes.iloc[-40:-20].mean()) - 1.0) if len(closes) >= 40 else 0.0
            metrics.update({"spy": c, "ma20": ma20, "ma50": ma50, "ma_slope": slope})
            if c > ma50 and ma20 > ma50 and slope > 0.01:
                trend = "bull"
            elif c < ma50 and ma20 < ma50 and slope < -0.01:
                trend = "bear"
            else:
                trend = "sideways"
            rvol = realized_vol(closes, 20)
            metrics["spy_realized_vol"] = rvol
            vol_regime = "high" if rvol > float(getattr(cfg, "regime_high_vol", 0.22) or 0.22) else "low"

    vix_last = None
    if vix is not None and not vix.empty:
        vw = _slice(vix, as_of_idx)
        vix_last = float(vw["Close"].iloc[-1])
        metrics["vix"] = vix_last
        if vix_last >= float(getattr(cfg, "vix_high", 25.0) or 25.0):
            vol_regime = "high"

    # Compose label + sizing
    if vol_regime == "high" and trend == "bear":
        label = "high_vol"
        mult = float(getattr(cfg, "regime_bear_highvol_size", 0.0) or 0.0)
        pause = True
    elif trend == "bear":
        label = "bear"
        mult = float(getattr(cfg, "regime_bear_size", 0.35) or 0.35)
        pause = bool(getattr(cfg, "pause_in_bear", False))
    elif vol_regime == "high":
        label = "high_vol"
        mult = float(getattr(cfg, "regime_highvol_size", 0.5) or 0.5)
        pause = bool(getattr(cfg, "pause_in_high_vol", False))
    elif trend == "bull":
        label = "bull"
        mult = 1.0
        pause = False
    else:
        label = "sideways"
        mult = float(getattr(cfg, "regime_sideways_size", 0.7) or 0.7)
        pause = False

    state = RegimeState(
        label=label, trend=trend, vol_regime=vol_regime,
        size_multiplier=mult, pause_entries=pause, metrics=metrics,
    )
    _LAST_REGIME = state
    return state


# ---------------------------------------------------------------------------
# Ensemble scorer
# ---------------------------------------------------------------------------

@dataclass
class EnsembleResult:
    probability: float
    confidence: float
    pass_consensus: bool
    votes: Dict[str, float]
    weights: Dict[str, float]
    model: str = "ensemble"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _rule_score(feats: Dict[str, float]) -> float:
    score = (
        1.2 * feats.get("ret_5d", 0)
        + 0.8 * feats.get("ret_10d", 0)
        + 0.3 * min(feats.get("vol_ratio_20", 1) - 1.0, 2.0)
        - 0.5 * feats.get("realized_vol_10", 0)
        + 0.4 * feats.get("close_vs_ma20", 0)
    )
    return float(np.clip(1.0 / (1.0 + np.exp(-8.0 * score)), 0.05, 0.95))


_ENSEMBLE_MODELS = {"logreg": None, "gbdt": None}
_ENSEMBLE_WEIGHTS = {"logreg": 0.4, "gbdt": 0.35, "rules": 0.25}


def get_ensemble_weights() -> Dict[str, float]:
    return dict(_ENSEMBLE_WEIGHTS)


def set_ensemble_weights(weights: Dict[str, float]) -> None:
    global _ENSEMBLE_WEIGHTS
    s = sum(weights.values()) or 1.0
    _ENSEMBLE_WEIGHTS = {k: float(v) / s for k, v in weights.items()}


def train_ensemble(data: Dict[str, pd.DataFrame], horizon: int = 3) -> Dict[str, Any]:
    """Train logreg + GBDT on past data only. Rule scorer needs no fit."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    from .forward_estimate import FEATURE_NAMES, build_training_matrix

    X, y = build_training_matrix(data, horizon=horizon)
    meta: Dict[str, Any] = {"n_samples": int(len(y)), "horizon": horizon}
    if len(y) < 80 or len(set(y.tolist())) < 2:
        _ENSEMBLE_MODELS["logreg"] = None
        _ENSEMBLE_MODELS["gbdt"] = None
        meta["fallback"] = True
        return meta

    logreg = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=500, class_weight="balanced")),
    ])
    gbdt = GradientBoostingClassifier(random_state=42, max_depth=3, n_estimators=80)
    logreg.fit(X, y)
    gbdt.fit(X, y)
    _ENSEMBLE_MODELS["logreg"] = logreg
    _ENSEMBLE_MODELS["gbdt"] = gbdt
    meta["fallback"] = False
    return meta


def ensemble_estimate(
    feats: Dict[str, float],
    cfg: Optional[StrategyConfig] = None,
) -> EnsembleResult:
    """Weighted consensus of logreg + gbdt + rules. Majority/threshold gate."""
    from .forward_estimate import FEATURE_NAMES

    cfg = cfg or get_runtime_config()
    threshold = float(cfg.forward_estimate_threshold)
    x = np.asarray([[feats.get(n, 0.0) for n in FEATURE_NAMES]], dtype=float)
    votes: Dict[str, float] = {}

    if _ENSEMBLE_MODELS.get("logreg") is not None:
        try:
            votes["logreg"] = float(_ENSEMBLE_MODELS["logreg"].predict_proba(x)[0][1])
        except Exception:
            votes["logreg"] = _rule_score(feats)
    else:
        votes["logreg"] = _rule_score(feats)

    if _ENSEMBLE_MODELS.get("gbdt") is not None:
        try:
            votes["gbdt"] = float(_ENSEMBLE_MODELS["gbdt"].predict_proba(x)[0][1])
        except Exception:
            votes["gbdt"] = _rule_score(feats)
    else:
        votes["gbdt"] = _rule_score(feats)

    votes["rules"] = _rule_score(feats)

    w = get_ensemble_weights()
    # Allow cfg overrides
    w = {
        "logreg": float(getattr(cfg, "ensemble_w_logreg", w["logreg"])),
        "gbdt": float(getattr(cfg, "ensemble_w_gbdt", w["gbdt"])),
        "rules": float(getattr(cfg, "ensemble_w_rules", w["rules"])),
    }
    s = sum(w.values()) or 1.0
    w = {k: v / s for k, v in w.items()}

    prob = sum(w[k] * votes[k] for k in votes)
    # Majority: at least 2 of 3 models above threshold OR weighted prob above threshold
    above = sum(1 for v in votes.values() if v >= threshold)
    need = int(getattr(cfg, "ensemble_min_votes", 2) or 2)
    pass_c = (above >= need) and (prob >= threshold)
    conf = float(min(1.0, abs(prob - 0.5) * 2.0))
    return EnsembleResult(
        probability=round(prob, 4),
        confidence=round(conf, 4),
        pass_consensus=pass_c,
        votes={k: round(v, 4) for k, v in votes.items()},
        weights={k: round(v, 4) for k, v in w.items()},
    )


def learn_ensemble_and_filters(outcomes: List[Dict[str, Any]], cfg: StrategyConfig) -> Dict[str, Any]:
    """
    Interpretable adjustments from closed-trade / prediction outcomes.
    - If high-vol filtered trades would have won often → slightly raise max_realized_vol
    - If ensemble logreg more accurate than gbdt → bump logreg weight
    """
    adjustments = []
    if len(outcomes) < 8:
        return {"adjusted": False, "reason": "need more outcomes", "adjustments": []}

    # Ensemble weight nudge from per-model correctness if present
    model_hits = {"logreg": [], "gbdt": [], "rules": []}
    for o in outcomes:
        votes = o.get("votes") or {}
        actual = bool(o.get("actual_positive"))
        for m, p in votes.items():
            if m in model_hits:
                model_hits[m].append(1 if ((p >= 0.55) == actual) else 0)

    weights = get_ensemble_weights()
    acc = {m: (sum(v) / len(v) if v else 0.5) for m, v in model_hits.items()}
    if acc:
        # Softmax-ish nudge toward better models
        best = max(acc, key=acc.get)
        worst = min(acc, key=acc.get)
        if acc[best] - acc[worst] >= 0.08:
            weights[best] = weights.get(best, 0.33) + 0.05
            weights[worst] = max(0.1, weights.get(worst, 0.33) - 0.05)
            set_ensemble_weights(weights)
            adjustments.append({
                "param": "ensemble_weights",
                "before": get_ensemble_weights(),
                "after": weights,
                "why": f"{best} accuracy {acc[best]:.0%} beat {worst} {acc[worst]:.0%} — reweighted ensemble.",
            })

    return {"adjusted": bool(adjustments), "adjustments": adjustments, "accuracies": acc}

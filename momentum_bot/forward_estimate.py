"""
Forward-estimate prediction module (NO look-ahead bias).

At each point in time, uses ONLY data available up to that date:
  - recent price action (returns, RSI-like momentum)
  - volume trends
  - realized volatility
  - sector / cross-sectional momentum proxy

Simple interpretable model: sklearn LogisticRegression.
Trained only on past rows. Predicts P(close rises over next H trading days).

DISCLAIMER: statistical estimate, not a guarantee of future returns.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import StrategyConfig, get_runtime_config

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODEL_META_PATH = DATA_DIR / "forward_model_meta.json"
PRED_JOURNAL_PATH = DATA_DIR / "forward_estimate_journal.json"

FEATURE_NAMES = [
    "ret_1d",
    "ret_5d",
    "ret_10d",
    "vol_ratio_20",
    "realized_vol_10",
    "range_pct",
    "close_vs_ma10",
    "close_vs_ma20",
    "volume_trend_5",
]


@dataclass
class ForwardEstimate:
    ticker: str
    probability: float  # P(continue rising)
    confidence: float   # |prob - 0.5| * 2  → 0..1
    horizon_days: int
    threshold: float
    pass_threshold: bool
    features: Dict[str, float]
    as_of: str = ""
    model: str = "LogisticRegression"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def compute_features_at(df: pd.DataFrame, idx: int) -> Optional[Dict[str, float]]:
    """
    Features using ONLY bars [0 .. idx] inclusive. No future bars.
    idx is an integer position into df.
    """
    if idx < 21 or idx >= len(df):
        return None
    window = df.iloc[: idx + 1]
    closes = window["Close"].astype(float)
    volumes = window["Volume"].astype(float)
    highs = window["High"].astype(float) if "High" in window.columns else closes
    lows = window["Low"].astype(float) if "Low" in window.columns else closes

    c = float(closes.iloc[-1])
    if c <= 0:
        return None

    def ret(n: int) -> float:
        if len(closes) <= n:
            return 0.0
        past = float(closes.iloc[-(n + 1)])
        return (c - past) / past if past else 0.0

    vol_avg = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.mean())
    vol_ratio = float(volumes.iloc[-1]) / vol_avg if vol_avg > 0 else 1.0

    rets = closes.pct_change().dropna().iloc[-10:]
    realized_vol = float(rets.std()) if len(rets) else 0.0

    hi = float(highs.iloc[-1])
    lo = float(lows.iloc[-1])
    range_pct = (hi - lo) / c if c else 0.0

    ma10 = float(closes.iloc[-10:].mean())
    ma20 = float(closes.iloc[-20:].mean())
    vol_ma5 = float(volumes.iloc[-5:].mean())
    vol_ma10 = float(volumes.iloc[-10:].mean()) if len(volumes) >= 10 else vol_ma5
    volume_trend = (vol_ma5 / vol_ma10 - 1.0) if vol_ma10 > 0 else 0.0

    return {
        "ret_1d": ret(1),
        "ret_5d": ret(5),
        "ret_10d": ret(10),
        "vol_ratio_20": vol_ratio,
        "realized_vol_10": realized_vol,
        "range_pct": range_pct,
        "close_vs_ma10": (c / ma10 - 1.0) if ma10 else 0.0,
        "close_vs_ma20": (c / ma20 - 1.0) if ma20 else 0.0,
        "volume_trend_5": volume_trend,
    }


def _label_at(df: pd.DataFrame, idx: int, horizon: int) -> Optional[int]:
    """1 if close[idx+horizon] > close[idx], else 0. Needs future bars for TRAINING only."""
    if idx + horizon >= len(df):
        return None
    c0 = float(df["Close"].iloc[idx])
    c1 = float(df["Close"].iloc[idx + horizon])
    if c0 <= 0:
        return None
    return 1 if c1 > c0 else 0


def build_training_matrix(
    data: Dict[str, pd.DataFrame],
    horizon: int = 3,
    max_rows_per_ticker: int = 400,
) -> Tuple[np.ndarray, np.ndarray]:
    """Build X, y from historical panels. Labels use future within each series,
    but callers must only pass data available as-of the training cutoff."""
    xs: List[List[float]] = []
    ys: List[int] = []
    for ticker, df in data.items():
        if df is None or len(df) < 40 + horizon:
            continue
        # Sample evenly to keep matrix manageable
        start = 25
        end = len(df) - horizon
        if end <= start:
            continue
        step = max(1, (end - start) // max_rows_per_ticker)
        for i in range(start, end, step):
            feats = compute_features_at(df, i)
            lab = _label_at(df, i, horizon)
            if feats is None or lab is None:
                continue
            xs.append([feats[n] for n in FEATURE_NAMES])
            ys.append(lab)
    if not xs:
        return np.zeros((0, len(FEATURE_NAMES))), np.zeros((0,))
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=int)


def train_model(
    data: Dict[str, pd.DataFrame],
    horizon: int = 3,
    cfg: Optional[StrategyConfig] = None,
):
    """Fit LogisticRegression on past data only. Returns (model, meta)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    cfg = cfg or get_runtime_config()
    X, y = build_training_matrix(data, horizon=horizon)
    meta = {
        "n_samples": int(len(y)),
        "horizon": horizon,
        "feature_names": FEATURE_NAMES,
        "trained_at": _utc_now(),
        "pos_rate": float(y.mean()) if len(y) else None,
    }
    if len(y) < 50 or len(set(y.tolist())) < 2:
        meta["fallback"] = True
        return None, meta

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=500, class_weight="balanced")),
    ])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pipe.fit(X, y)
    meta["fallback"] = False
    # Interpretable coefficients
    try:
        coefs = pipe.named_steps["clf"].coef_[0]
        meta["coefficients"] = {FEATURE_NAMES[i]: round(float(coefs[i]), 4) for i in range(len(FEATURE_NAMES))}
    except Exception:
        pass
    _ensure_dir()
    MODEL_META_PATH.write_text(json.dumps(meta, indent=2))
    return pipe, meta


# Module-level cached model (retrained by historical / learning hooks)
_MODEL = None
_MODEL_META: Dict[str, Any] = {}
_THRESHOLD_OVERRIDE: Optional[float] = None


def get_threshold(cfg: Optional[StrategyConfig] = None) -> float:
    cfg = cfg or get_runtime_config()
    if _THRESHOLD_OVERRIDE is not None:
        return float(_THRESHOLD_OVERRIDE)
    return float(cfg.forward_estimate_threshold)


def set_threshold_override(value: Optional[float]) -> None:
    global _THRESHOLD_OVERRIDE
    _THRESHOLD_OVERRIDE = value


def set_model(model, meta: Optional[Dict[str, Any]] = None) -> None:
    global _MODEL, _MODEL_META
    _MODEL = model
    _MODEL_META = meta or {}


def get_model_meta() -> Dict[str, Any]:
    return dict(_MODEL_META)


def _heuristic_probability(feats: Dict[str, float]) -> float:
    """Fallback when model not trained: interpretable weighted score → sigmoid-ish."""
    score = (
        1.2 * feats.get("ret_5d", 0)
        + 0.8 * feats.get("ret_10d", 0)
        + 0.3 * min(feats.get("vol_ratio_20", 1) - 1.0, 2.0)
        - 0.5 * feats.get("realized_vol_10", 0)
        + 0.4 * feats.get("close_vs_ma20", 0)
    )
    # squash to (0,1)
    prob = 1.0 / (1.0 + np.exp(-8.0 * score))
    return float(np.clip(prob, 0.05, 0.95))


def estimate_forward(
    ticker: str,
    df: pd.DataFrame,
    cfg: Optional[StrategyConfig] = None,
    as_of_idx: Optional[int] = None,
) -> Optional[ForwardEstimate]:
    """
    Estimate P(continue rising) at as_of_idx (default: last bar).
    Uses only data up to that index — no look-ahead.
    """
    cfg = cfg or get_runtime_config()
    if df is None or df.empty:
        return None
    idx = as_of_idx if as_of_idx is not None else len(df) - 1
    feats = compute_features_at(df, idx)
    if feats is None:
        return None

    horizon = int(cfg.forward_estimate_horizon or 3)
    threshold = get_threshold(cfg)

    if _MODEL is not None:
        try:
            x = np.asarray([[feats[n] for n in FEATURE_NAMES]], dtype=float)
            prob = float(_MODEL.predict_proba(x)[0][1])
            model_name = "LogisticRegression"
        except Exception:
            prob = _heuristic_probability(feats)
            model_name = "heuristic_fallback"
    else:
        prob = _heuristic_probability(feats)
        model_name = "heuristic_untrained"

    conf = float(min(1.0, abs(prob - 0.5) * 2.0))
    as_of = ""
    try:
        as_of = str(pd.Timestamp(df.index[idx]).date())
    except Exception:
        as_of = _utc_now()

    return ForwardEstimate(
        ticker=ticker,
        probability=round(prob, 4),
        confidence=round(conf, 4),
        horizon_days=horizon,
        threshold=threshold,
        pass_threshold=prob >= threshold,
        features={k: round(float(v), 6) for k, v in feats.items()},
        as_of=as_of,
        model=model_name,
    )


def ensure_model_trained(
    data: Dict[str, pd.DataFrame],
    cfg: Optional[StrategyConfig] = None,
) -> Dict[str, Any]:
    """Train (or retrain) the global model on provided past data."""
    cfg = cfg or get_runtime_config()
    model, meta = train_model(data, horizon=int(cfg.forward_estimate_horizon or 3), cfg=cfg)
    set_model(model, meta)
    return meta


def record_prediction_outcome(
    ticker: str,
    probability: float,
    actual_positive: bool,
    threshold: float,
) -> None:
    """Track whether forward estimates were accurate (for learning adjustments)."""
    _ensure_dir()
    raw = {"outcomes": []}
    if PRED_JOURNAL_PATH.exists():
        try:
            raw = json.loads(PRED_JOURNAL_PATH.read_text())
        except Exception:
            raw = {"outcomes": []}
    predicted_pos = probability >= threshold
    correct = predicted_pos == actual_positive
    raw.setdefault("outcomes", []).append({
        "ticker": ticker,
        "probability": probability,
        "threshold": threshold,
        "predicted_positive": predicted_pos,
        "actual_positive": actual_positive,
        "correct": correct,
        "at": _utc_now(),
        "learned": False,
    })
    PRED_JOURNAL_PATH.write_text(json.dumps(raw, indent=2))


def load_prediction_outcomes() -> List[Dict[str, Any]]:
    if not PRED_JOURNAL_PATH.exists():
        return []
    try:
        return list(json.loads(PRED_JOURNAL_PATH.read_text()).get("outcomes", []))
    except Exception:
        return []


def adjust_from_prediction_accuracy(cfg: Optional[StrategyConfig] = None) -> Dict[str, Any]:
    """
    Simple interpretable rules on forward-estimate accuracy:
      - If precision low (many false positives) → raise threshold slightly
      - If many false negatives / low recall → lower threshold slightly
    Logs adjustment WHY. Clamped to [0.45, 0.75].
    """
    cfg = cfg or get_runtime_config()
    outcomes = [o for o in load_prediction_outcomes() if not o.get("learned")]
    if len(outcomes) < 10:
        return {"adjusted": False, "reason": f"need 10 outcomes, have {len(outcomes)}"}

    tp = sum(1 for o in outcomes if o["predicted_positive"] and o["actual_positive"])
    fp = sum(1 for o in outcomes if o["predicted_positive"] and not o["actual_positive"])
    fn = sum(1 for o in outcomes if not o["predicted_positive"] and o["actual_positive"])
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    old = get_threshold(cfg)
    new = old
    why = ""
    if precision < 0.45 and (tp + fp) >= 5:
        new = min(0.75, old + 0.02)
        why = f"Low precision {precision:.0%} on forward estimates — raised threshold {old:.2f} → {new:.2f}."
    elif recall < 0.40 and precision >= 0.50 and (tp + fn) >= 5:
        new = max(0.45, old - 0.02)
        why = f"Low recall {recall:.0%} — lowered threshold {old:.2f} → {new:.2f}."
    else:
        why = f"Precision {precision:.0%}, recall {recall:.0%} — no threshold change."

    set_threshold_override(new if new != old else _THRESHOLD_OVERRIDE)
    # Mark learned
    raw = {"outcomes": load_prediction_outcomes()}
    for o in raw["outcomes"]:
        o["learned"] = True
    _ensure_dir()
    PRED_JOURNAL_PATH.write_text(json.dumps(raw, indent=2))

    # Persist into learned config threshold field via runtime update
    from .config import set_runtime_config
    updated = cfg.update({"forward_estimate_threshold": new})
    set_runtime_config(updated)

    return {
        "adjusted": new != old,
        "before": old,
        "after": new,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "why": why,
        "sample": len(outcomes),
    }

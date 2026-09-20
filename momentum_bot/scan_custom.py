"""
Pro scanner builder — filter cached / quick-scan signals.

POST /scan/custom with min volume, % change, RS, news tilt, strategy id, region, price range.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _region_of(ticker: str) -> str:
    t = (ticker or "").upper()
    if t.endswith(".L") or t.endswith("-L"):
        return "UK"
    if t.endswith(".TO") or t.endswith("-TO") or t.endswith(".V"):
        return "CA"
    if t.endswith(".HK") or t.endswith("-HK"):
        return "HK"
    if t.endswith(".T") or t.endswith("-T"):
        return "JP"
    return "US"


def run_custom_scan(
    filters: Optional[Dict[str, Any]] = None,
    *,
    refresh: bool = False,
    cfg: Any = None,
) -> Dict[str, Any]:
    """
    Filter signals by builder criteria. Optionally run quick_scan first.
    Does not invent L2 heat — works on scanner Signal fields.
    """
    from .config import get_runtime_config
    from .scanner import get_cached_signals, quick_scan, signals_to_dicts

    cfg = cfg or get_runtime_config()
    f = dict(filters or {})
    note_parts: List[str] = []

    if refresh:
        try:
            quick_scan(cfg=cfg)
            note_parts.append("quick_scan refreshed before filter")
        except Exception as exc:  # noqa: BLE001
            note_parts.append(f"quick_scan skipped: {exc}")

    raw = get_cached_signals() or []
    rows = signals_to_dicts(raw) if raw and not isinstance(raw[0], dict) else [
        (s.to_dict() if hasattr(s, "to_dict") else dict(s)) for s in raw
    ]

    min_vol = f.get("min_volume")
    min_vol_ratio = f.get("min_volume_ratio")
    min_change = f.get("min_pct_change")  # as fraction or percent
    max_change = f.get("max_pct_change")
    min_rs = f.get("min_rs") or f.get("min_relative_strength")
    news_tilt = f.get("news_tilt")  # bullish|bearish|any
    strategy_id = (f.get("strategy_id") or "").strip() or None
    region = (f.get("region") or "").strip().upper() or None
    price_min = f.get("price_min")
    price_max = f.get("price_max")
    min_confidence = f.get("min_confidence")
    limit = max(1, min(int(f.get("limit") or 50), 200))

    def _pct(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        # Accept 5 for 5% or 0.05
        if abs(x) > 1.0:
            return x / 100.0
        return x

    min_change_f = _pct(min_change)
    max_change_f = _pct(max_change)

    matched: List[Dict[str, Any]] = []
    for s in rows:
        ticker = str(s.get("ticker") or "")
        entry = s.get("entry")
        mom = s.get("momentum_pct")
        vol_r = s.get("volume_ratio")
        conf = s.get("confidence")
        sid = s.get("strategy_id") or "momentum"
        news24 = s.get("news_score_24h")

        if strategy_id and sid != strategy_id and strategy_id.lower() != "any":
            continue
        if region and region != "ANY" and _region_of(ticker) != region:
            continue
        try:
            if price_min is not None and entry is not None and float(entry) < float(price_min):
                continue
            if price_max is not None and entry is not None and float(entry) > float(price_max):
                continue
        except (TypeError, ValueError):
            continue
        if min_vol_ratio is not None and vol_r is not None:
            try:
                if float(vol_r) < float(min_vol_ratio):
                    continue
            except (TypeError, ValueError):
                continue
        # min_volume: approximate via volume_ratio * proxy — use volume_ratio if raw volume absent
        if min_vol is not None:
            raw_vol = s.get("volume") or s.get("avg_volume")
            if raw_vol is not None:
                try:
                    if float(raw_vol) < float(min_vol):
                        continue
                except (TypeError, ValueError):
                    pass
            elif vol_r is not None and float(min_vol) > 0 and float(vol_r) < 1.0:
                # weak proxy: require at least average volume
                continue
        if min_change_f is not None and mom is not None:
            try:
                if float(mom) < float(min_change_f):
                    continue
            except (TypeError, ValueError):
                continue
        if max_change_f is not None and mom is not None:
            try:
                if float(mom) > float(max_change_f):
                    continue
            except (TypeError, ValueError):
                continue
        if min_rs is not None:
            rs = s.get("relative_strength") or s.get("rs") or mom
            if rs is not None:
                try:
                    rs_f = float(rs)
                    thr = float(min_rs)
                    if abs(thr) > 1:
                        thr = thr / 100.0
                    if rs_f < thr:
                        continue
                except (TypeError, ValueError):
                    continue
        if news_tilt and str(news_tilt).lower() not in ("any", "", "none"):
            tilt = str(news_tilt).lower()
            try:
                ns = float(news24) if news24 is not None else None
            except (TypeError, ValueError):
                ns = None
            if tilt == "bullish" and (ns is None or ns < 0.05):
                continue
            if tilt == "bearish" and (ns is None or ns > -0.05):
                continue
        if min_confidence is not None and conf is not None:
            try:
                if float(conf) < float(min_confidence):
                    continue
            except (TypeError, ValueError):
                continue
        matched.append(s)
        if len(matched) >= limit:
            break

    return {
        "ok": True,
        "filters": f,
        "count": len(matched),
        "signals": matched,
        "universe_cached": len(rows),
        "generated_at": _utc_now(),
        "note": "; ".join(note_parts) or "Filtered cached scan signals (pro scanner builder).",
        "not_level2": True,
        "label": "Custom scanner — filters on GAMMA-R signals, not Trade Ideas L2 heat",
    }

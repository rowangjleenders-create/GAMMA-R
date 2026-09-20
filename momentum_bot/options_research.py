"""
Read-only options research foothold (Phase 2).

Feature flag: options_read_only. No options order routing — research only.
Nearest expiries, ATM IV, put/call volume when yfinance allows; cache; honest nulls.
Optional paper options *idea* journal (thesis only) — never brokers options orders.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
IDEAS_PATH = DATA_DIR / "options_ideas.jsonl"

_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 300.0  # 5 minutes
_lock = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _lock:
        row = _CACHE.get(key)
        if not row:
            return None
        if time.time() - float(row.get("at") or 0) > _CACHE_TTL:
            return None
        payload = dict(row["data"])
        payload["cache_hit"] = True
        return payload


def _cache_set(key: str, data: Dict[str, Any]) -> None:
    with _lock:
        _CACHE[key] = {"at": time.time(), "data": dict(data)}


def options_summary(ticker: str, *, cfg: Any = None, force: bool = False) -> Dict[str, Any]:
    """
    Nearest expiries + ATM IV + put/call volume sketch.
    Always labeled read-only research. Never places orders. Honest nulls on failure.
    """
    from .config import get_runtime_config

    cfg = cfg or get_runtime_config()
    t = (ticker or "").strip().upper().replace(".", "-")
    base: Dict[str, Any] = {
        "ticker": t,
        "feature": "options_read_only",
        "trading": False,
        "order_routing": False,
        "label": "READ-ONLY research — not tradeable options",
        "generated_at": _utc_now(),
        "available": False,
        "iv_rank": None,
        "iv_approx": None,
        "atm_iv": None,
        "atm_strike": None,
        "spot": None,
        "nearest_expiry": None,
        "expirations": [],
        "put_call_volume": None,
        "call_volume": None,
        "put_volume": None,
        "nearest_sketch": None,
        "note": "",
        "stub": False,
        "cache_hit": False,
        "nulls_honest": True,
    }

    if not t:
        base["note"] = "Ticker required"
        base["stub"] = True
        return base

    if not bool(getattr(cfg, "options_read_only", False)):
        base["note"] = (
            "Feature flag options_read_only is off. Enable in Settings / PUT /config "
            "to attempt a yfinance options chain sketch. No options trading is available."
        )
        base["stub"] = True
        base["how_to_enable"] = [
            'PUT /config {"options_read_only": true}',
            "Or Settings → Options research (read-only)",
            "Then GET /options/{ticker}",
        ]
        return base

    cache_key = f"opt:{t}"
    if not force:
        hit = _cache_get(cache_key)
        if hit is not None:
            return hit

    try:
        import yfinance as yf
    except ImportError:
        base["note"] = "yfinance not installed — connect data later"
        base["stub"] = True
        return base

    try:
        stock = yf.Ticker(t)
        expirations: List[str] = []
        try:
            expirations = list(stock.options or [])
        except Exception as exc:  # noqa: BLE001
            base["note"] = f"Options chain unavailable: {exc}"
            base["stub"] = True
            return base

        if not expirations:
            base["note"] = (
                f"No option expirations returned for {t} (common for some non-US or thin names). "
                "Connect a dedicated options data feed later for reliable IV rank."
            )
            base["stub"] = True
            return base

        nearest = expirations[0]
        base["expirations"] = expirations[:12]
        base["nearest_expiry"] = nearest

        # Spot for ATM
        spot = None
        try:
            fi = getattr(stock, "fast_info", None)
            if fi is not None:
                spot = float(getattr(fi, "last_price", None) or getattr(fi, "lastPrice", None) or 0) or None
            if not spot:
                hist = stock.history(period="5d")
                if hist is not None and not hist.empty and "Close" in hist.columns:
                    spot = float(hist["Close"].dropna().iloc[-1])
        except Exception:
            spot = None
        base["spot"] = round(spot, 4) if spot else None

        chain = stock.option_chain(nearest)
        calls = getattr(chain, "calls", None)
        puts = getattr(chain, "puts", None)

        ivs: List[float] = []
        atm_iv = None
        atm_strike = None
        sketch_calls: List[Dict[str, Any]] = []
        sketch_puts: List[Dict[str, Any]] = []
        call_vol = 0.0
        put_vol = 0.0

        def _side_stats(df, out_list: List[Dict[str, Any]], side: str) -> float:
            nonlocal atm_iv, atm_strike
            vol_sum = 0.0
            if df is None or getattr(df, "empty", True):
                return 0.0
            cols = {c.lower(): c for c in df.columns}
            iv_col = cols.get("impliedvolatility") or cols.get("implied_volatility")
            strike_col = cols.get("strike")
            last_col = cols.get("lastprice") or cols.get("last_price")
            vol_col = cols.get("volume")
            best_diff = None
            # Volume sum
            if vol_col:
                try:
                    vol_sum = float(df[vol_col].fillna(0).astype(float).sum())
                except Exception:
                    vol_sum = 0.0
            # ATM = closest strike to spot (or mid-chain)
            rows = df.copy()
            if strike_col and spot:
                try:
                    rows = rows.assign(_diff=(rows[strike_col].astype(float) - float(spot)).abs())
                    rows = rows.sort_values("_diff")
                except Exception:
                    pass
            n = min(5, len(rows))
            for _, row in rows.iloc[:n].iterrows():
                iv = None
                if iv_col:
                    try:
                        iv = float(row[iv_col])
                        if iv == iv and iv > 0:
                            ivs.append(iv)
                    except (TypeError, ValueError):
                        iv = None
                try:
                    strike = float(row[strike_col]) if strike_col else None
                except (TypeError, ValueError):
                    strike = None
                try:
                    last = float(row[last_col]) if last_col else None
                except (TypeError, ValueError):
                    last = None
                try:
                    v = float(row[vol_col]) if vol_col else None
                except (TypeError, ValueError):
                    v = None
                out_list.append({
                    "side": side,
                    "strike": strike,
                    "last": last,
                    "iv": round(iv, 4) if iv is not None else None,
                    "volume": int(v) if v is not None and v == v else None,
                })
                if strike is not None and spot and iv is not None:
                    diff = abs(strike - spot)
                    if best_diff is None or diff < best_diff:
                        best_diff = diff
                        if side == "call" or atm_iv is None:
                            atm_iv = iv
                            atm_strike = strike
            return vol_sum

        call_vol = _side_stats(calls, sketch_calls, "call")
        put_vol = _side_stats(puts, sketch_puts, "put")
        # Prefer average of nearest call+put ATM IVs if both present
        call_atm = sketch_calls[0].get("iv") if sketch_calls else None
        put_atm = sketch_puts[0].get("iv") if sketch_puts else None
        if call_atm is not None and put_atm is not None:
            atm_iv = (float(call_atm) + float(put_atm)) / 2.0
            atm_strike = sketch_calls[0].get("strike") or sketch_puts[0].get("strike")
        elif call_atm is not None:
            atm_iv = float(call_atm)
            atm_strike = sketch_calls[0].get("strike")
        elif put_atm is not None:
            atm_iv = float(put_atm)
            atm_strike = sketch_puts[0].get("strike")

        iv_approx = round(sum(ivs) / len(ivs), 4) if ivs else None
        if atm_iv is not None:
            atm_iv = round(float(atm_iv), 4)

        pc_ratio = None
        if call_vol > 0:
            pc_ratio = round(put_vol / call_vol, 4)
        elif put_vol > 0:
            pc_ratio = None  # honest null when no call volume

        iv_rank = None
        try:
            hist = stock.history(period="1y")
            ref_iv = atm_iv or iv_approx
            if hist is not None and not hist.empty and "Close" in hist.columns and ref_iv:
                close = hist["Close"].astype(float).dropna()
                rets = close.pct_change().dropna()
                if len(rets) >= 20:
                    roll = rets.rolling(20).std() * (252 ** 0.5)
                    samples = [float(x) for x in roll.dropna().tolist() if x == x]
                    if samples:
                        below = sum(1 for s in samples if s <= ref_iv)
                        iv_rank = round(below / len(samples), 4)
        except Exception:
            iv_rank = None

        base.update({
            "available": True,
            "stub": False,
            "iv_approx": iv_approx,
            "atm_iv": atm_iv,
            "atm_strike": round(atm_strike, 4) if atm_strike is not None else None,
            "iv_rank": iv_rank,
            "iv_rank_note": (
                "Approximate vs 1y realized-vol distribution — not exchange IV percentile. "
                "For research only."
                if iv_rank is not None
                else "IV rank unavailable; showing nearest-expiry IV sketch only."
            ),
            "call_volume": int(call_vol) if call_vol else 0,
            "put_volume": int(put_vol) if put_vol else 0,
            "put_call_volume": pc_ratio,
            "nearest_sketch": {
                "expiry": nearest,
                "calls": sketch_calls,
                "puts": sketch_puts,
            },
            "note": (
                "Read-only yfinance options sketch (cached ~5m). Data can be delayed or incomplete. "
                "No options order path exists in GAMMA-R."
            ),
        })
        _cache_set(cache_key, base)
        return base
    except Exception as exc:  # noqa: BLE001
        base["note"] = f"Options research failed ({exc}). Connect dedicated data later."
        base["stub"] = True
        base["available"] = False
        return base


# ---- Paper options idea journal (thesis only; no orders) ----


def log_options_idea(
    ticker: str,
    thesis: str,
    *,
    side: Optional[str] = None,
    expiry: Optional[str] = None,
    strike: Optional[float] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Append a research thesis to the options idea journal.
    Explicitly does NOT place or route any options order.
    """
    t = (ticker or "").strip().upper().replace(".", "-")
    text = (thesis or "").strip()
    if not t or not text:
        return {"ok": False, "error": "ticker and thesis required", "order_routing": False}
    entry = {
        "id": f"idea-{int(time.time() * 1000)}",
        "ts": _utc_now(),
        "ticker": t,
        "thesis": text[:2000],
        "side": (side or "").strip().lower() or None,
        "expiry": expiry,
        "strike": strike,
        "tags": list(tags or [])[:8],
        "order_routing": False,
        "brokered": False,
        "label": "PAPER options idea — thesis only, not an order",
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(IDEAS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return {"ok": True, "idea": entry, "path": str(IDEAS_PATH), "order_routing": False}


def list_options_ideas(limit: int = 50) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if IDEAS_PATH.exists():
        try:
            lines = IDEAS_PATH.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-max(1, min(200, int(limit or 50))) :]:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            rows = []
    rows.reverse()
    return {
        "ok": True,
        "count": len(rows),
        "ideas": rows,
        "order_routing": False,
        "label": "PAPER options idea journal — thesis only",
        "path": str(IDEAS_PATH),
    }


# ---- Options chain + Black-Scholes greeks (paper education) ----


def _norm_cdf(x: float) -> float:
    import math
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    import math
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_greeks(
    spot: float,
    strike: float,
    t_years: float,
    iv: float,
    *,
    rate: float = 0.05,
    side: str = "call",
) -> Dict[str, Optional[float]]:
    """Black-Scholes approx greeks for paper education. Honest nulls on bad inputs."""
    import math

    out: Dict[str, Optional[float]] = {
        "delta": None,
        "gamma": None,
        "theta": None,
        "vega": None,
        "bs_price": None,
        "model": "black_scholes_approx",
    }
    try:
        S, K, T, sigma, r = float(spot), float(strike), float(t_years), float(iv), float(rate)
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return out
        sqrtT = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        pdf = _norm_pdf(d1)
        is_call = (side or "call").lower().startswith("c")
        if is_call:
            delta = _norm_cdf(d1)
            price = S * delta - K * math.exp(-r * T) * _norm_cdf(d2)
            theta = (
                -(S * pdf * sigma) / (2 * sqrtT)
                - r * K * math.exp(-r * T) * _norm_cdf(d2)
            ) / 365.0
        else:
            delta = _norm_cdf(d1) - 1.0
            price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
            theta = (
                -(S * pdf * sigma) / (2 * sqrtT)
                + r * K * math.exp(-r * T) * _norm_cdf(-d2)
            ) / 365.0
        gamma = pdf / (S * sigma * sqrtT)
        vega = S * pdf * sqrtT / 100.0
        out.update({
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "vega": round(vega, 4),
            "bs_price": round(price, 4),
        })
    except Exception:
        pass
    return out


def options_chain(
    ticker: str,
    *,
    expiry: Optional[str] = None,
    cfg: Any = None,
    force: bool = False,
    max_rows: int = 40,
) -> Dict[str, Any]:
    """
    Chain rows with strike, bid/ask, IV, delta/gamma/theta/vega.
    BS approx when vendor greeks missing. Read-only; wire to paper options.
    """
    summary = options_summary(ticker, cfg=cfg, force=force)
    t = summary.get("ticker") or (ticker or "").strip().upper().replace(".", "-")
    out: Dict[str, Any] = {
        "ok": True,
        "ticker": t,
        "trading": False,
        "order_routing": False,
        "live_options": False,
        "label": "Options chain + greeks (research / paper education) — no live routing",
        "generated_at": _utc_now(),
        "expiry": None,
        "expirations": summary.get("expirations") or [],
        "spot": summary.get("spot"),
        "rows": [],
        "count": 0,
        "greeks_source": None,
        "available": bool(summary.get("available")),
        "stub": bool(summary.get("stub")),
        "note": summary.get("note") or "",
        "nulls_honest": True,
    }
    if summary.get("stub") or not summary.get("available"):
        return out

    try:
        import yfinance as yf
    except ImportError:
        out["note"] = "yfinance not installed"
        out["stub"] = True
        return out

    try:
        stock = yf.Ticker(t.replace("-", "."))
        expirations = list(stock.options or [])
        if not expirations:
            out["stub"] = True
            out["note"] = "No expirations"
            return out
        chosen = expiry if expiry and expiry in expirations else (
            summary.get("nearest_expiry") or expirations[0]
        )
        out["expiry"] = chosen
        out["expirations"] = expirations[:12]
        chain = stock.option_chain(chosen)
        spot = summary.get("spot")
        t_years = None
        try:
            exp_dt = datetime.strptime(chosen, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            t_years = max(
                (exp_dt - datetime.now(timezone.utc)).total_seconds() / (365.25 * 24 * 3600),
                1 / 365.25,
            )
        except Exception:
            t_years = 30 / 365.25

        rows: List[Dict[str, Any]] = []
        greeks_src = "black_scholes_approx"

        def _colmap(df):
            return {c.lower(): c for c in df.columns}

        def _f(row, cols, name: str):
            c = cols.get(name)
            if not c:
                return None
            try:
                v = float(row[c])
                return v if v == v else None
            except Exception:
                return None

        def _ingest(df, side: str) -> None:
            nonlocal greeks_src
            if df is None or getattr(df, "empty", True):
                return
            cols = _colmap(df)
            for _, row in df.iterrows():
                strike = _f(row, cols, "strike")
                if strike is None:
                    continue
                if spot:
                    try:
                        if abs(float(strike) - float(spot)) / max(float(spot), 1e-9) > 0.20:
                            continue
                    except Exception:
                        pass
                bid = _f(row, cols, "bid")
                ask = _f(row, cols, "ask")
                last = _f(row, cols, "lastprice")
                iv = _f(row, cols, "impliedvolatility")
                vol = _f(row, cols, "volume")
                oi = _f(row, cols, "openinterest")
                delta = _f(row, cols, "delta")
                gamma = _f(row, cols, "gamma")
                theta = _f(row, cols, "theta")
                vega = _f(row, cols, "vega")
                gsrc = "vendor"
                bs_price = None
                if delta is None and spot and iv and t_years:
                    g = black_scholes_greeks(
                        float(spot), float(strike), float(t_years), float(iv), side=side
                    )
                    delta, gamma, theta, vega = (
                        g.get("delta"), g.get("gamma"), g.get("theta"), g.get("vega")
                    )
                    bs_price = g.get("bs_price")
                    gsrc = "black_scholes_approx"
                    greeks_src = "black_scholes_approx"
                rows.append({
                    "side": side,
                    "strike": round(strike, 4),
                    "bid": bid,
                    "ask": ask,
                    "last": last,
                    "iv": round(iv, 4) if iv is not None else None,
                    "volume": int(vol) if vol is not None else None,
                    "open_interest": int(oi) if oi is not None else None,
                    "delta": delta,
                    "gamma": gamma,
                    "theta": theta,
                    "vega": vega,
                    "bs_price": bs_price,
                    "greeks_source": gsrc,
                    "expiry": chosen,
                })

        _ingest(getattr(chain, "calls", None), "call")
        _ingest(getattr(chain, "puts", None), "put")
        lim = max(4, min(int(max_rows or 40), 120))
        if spot and len(rows) > lim:
            rows.sort(key=lambda r: abs((r.get("strike") or 0) - float(spot)))
            rows = rows[:lim]
        else:
            rows = rows[:lim]
        rows.sort(key=lambda r: (r.get("strike") or 0, 0 if r.get("side") == "call" else 1))

        out.update({
            "rows": rows,
            "count": len(rows),
            "greeks_source": greeks_src,
            "t_years": round(t_years, 4) if t_years else None,
            "note": (
                "Chain rows with bid/ask/IV; greeks from vendor when present else "
                "Black-Scholes approx (paper education). Wire to POST /options/paper. No live options."
            ),
            "paper_wire": {
                "endpoint": "POST /options/paper",
                "fields": ["ticker", "side", "strike", "expiry", "contracts", "thesis"],
            },
        })
        return out
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = str(exc)
        out["stub"] = True
        return out

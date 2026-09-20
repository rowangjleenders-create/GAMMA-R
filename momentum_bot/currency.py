"""
Major FX / currency pair quotes (informational, paper-first context).

Uses yfinance-style symbols (e.g. EURUSD=X). Hardened so one pair failing
does not break the panel. Not wired to live broker orders.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

# Practical majors + a couple EU/UK/CA crosses
MAJOR_PAIRS: List[Dict[str, str]] = [
    {"symbol": "EURUSD=X", "pair": "EURUSD", "name": "Euro / US Dollar"},
    {"symbol": "GBPUSD=X", "pair": "GBPUSD", "name": "Pound / US Dollar"},
    {"symbol": "USDJPY=X", "pair": "USDJPY", "name": "US Dollar / Yen"},
    {"symbol": "USDCHF=X", "pair": "USDCHF", "name": "US Dollar / Franc"},
    {"symbol": "AUDUSD=X", "pair": "AUDUSD", "name": "Aussie / US Dollar"},
    {"symbol": "USDCAD=X", "pair": "USDCAD", "name": "US Dollar / Loonie"},
    {"symbol": "NZDUSD=X", "pair": "NZDUSD", "name": "Kiwi / US Dollar"},
    {"symbol": "EURGBP=X", "pair": "EURGBP", "name": "Euro / Pound"},
    {"symbol": "EURCAD=X", "pair": "EURCAD", "name": "Euro / Loonie"},
]

_PAIR_BY_KEY = {}
for _p in MAJOR_PAIRS:
    _PAIR_BY_KEY[_p["pair"].upper()] = _p
    _PAIR_BY_KEY[_p["symbol"].upper()] = _p
    _PAIR_BY_KEY[_p["pair"].upper().replace("/", "")] = _p


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _session_note(now: Optional[datetime] = None) -> str:
    """Brief FX session label from UTC hour (24/5 market)."""
    now = now or _utc_now()
    h = now.hour
    # Overlaps approximate: Asia 0–7, London 7–16, NY 12–21 UTC
    if 0 <= h < 7:
        return "Asia session"
    if 7 <= h < 12:
        return "London session"
    if 12 <= h < 16:
        return "London/NY overlap"
    if 16 <= h < 21:
        return "NY session"
    return "Asia open soon"


def _normalize_pair_key(pair: str) -> str:
    return (
        str(pair or "")
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace("=X", "")
        .strip()
    )


def resolve_pair(pair: str) -> Optional[Dict[str, str]]:
    key = _normalize_pair_key(pair)
    if not key:
        return None
    if key in _PAIR_BY_KEY:
        return _PAIR_BY_KEY[key]
    # Allow EURUSD=X style already normalized
    with_x = f"{key}=X"
    return _PAIR_BY_KEY.get(with_x)


def _fetch_one(meta: Dict[str, str]) -> Dict[str, Any]:
    """Fetch last + daily % for one pair; never raises."""
    symbol = meta["symbol"]
    out: Dict[str, Any] = {
        "pair": meta["pair"],
        "symbol": symbol,
        "name": meta["name"],
        "last": None,
        "change_pct": None,
        "session_note": _session_note(),
        "ok": False,
        "error": None,
    }
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        hist = t.history(period="5d", auto_adjust=True)
        if hist is None or hist.empty or "Close" not in hist.columns:
            out["error"] = "no_data"
            return out
        closes = hist["Close"].dropna()
        if closes.empty:
            out["error"] = "no_close"
            return out
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) >= 2 else last
        change_pct = ((last - prev) / prev) if prev else 0.0
        out["last"] = round(last, 6 if last < 10 else 4)
        out["change_pct"] = round(change_pct, 6)
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:120]
    return out


def get_currency_quotes(
    pairs: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Return major FX quotes.

    Shape:
      {
        "pairs": [{pair, symbol, name, last, change_pct, session_note, ok, ...}],
        "top_movers": [...],  # by |change_pct|
        "generated_at": ISO UTC,
        "session_note": str,
        "note": "Informational only — not live FX trading."
      }
    """
    metas: List[Dict[str, str]]
    if pairs:
        metas = []
        for p in pairs:
            m = resolve_pair(p)
            if m and m not in metas:
                metas.append(m)
        if not metas:
            metas = list(MAJOR_PAIRS)
    else:
        metas = list(MAJOR_PAIRS)

    results = [_fetch_one(m) for m in metas]
    ok_rows = [r for r in results if r.get("ok") and r.get("change_pct") is not None]
    top = sorted(ok_rows, key=lambda r: abs(float(r["change_pct"] or 0)), reverse=True)[:5]
    now = _utc_now()
    return {
        "pairs": results,
        "top_movers": [
            {
                "pair": r["pair"],
                "last": r["last"],
                "change_pct": r["change_pct"],
                "name": r["name"],
            }
            for r in top
        ],
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_note": _session_note(now),
        "count": len(results),
        "ok_count": sum(1 for r in results if r.get("ok")),
        "note": "Informational FX quotes for equity context — paper-first; not live FX trading.",
    }


def get_currency_pair(pair: str) -> Optional[Dict[str, Any]]:
    meta = resolve_pair(pair)
    if not meta:
        return None
    return _fetch_one(meta)

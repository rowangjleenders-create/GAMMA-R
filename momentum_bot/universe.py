"""
Broad market universe loaders.

Pulls constituents from public index lists (Wikipedia) so the scanner
covers liquid large caps across the US, Canada, UK, and Eurozone — not a
hardcoded personal watchlist, and not every listed stock worldwide.
"""

from __future__ import annotations

import io
import re
from typing import Callable, List, Optional, Set

import pandas as pd
import requests

from .config import StrategyConfig

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_NASDAQ100 = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
WIKI_NASDAQ100_FALLBACK = "https://en.wikipedia.org/wiki/Nasdaq-100"
WIKI_TSX60 = "https://en.wikipedia.org/wiki/S%26P/TSX_60"
WIKI_FTSE100 = "https://en.wikipedia.org/wiki/FTSE_100_Index"
WIKI_EURO_STOXX50 = "https://en.wikipedia.org/wiki/EURO_STOXX_50"

HEADERS = {
    "User-Agent": (
        "GAMMA-R/0.1 (educational; contact: local-user) "
        "Python-requests"
    )
}

# Exchange suffixes commonly used by yfinance for these regions
_YF_EXCHANGE_SUFFIX = re.compile(
    r"\.(TO|V|L|DE|PA|AS|MI|MC|BR|HE|SW|VI|LS|ST|OL|CO|IR|AT)$",
    re.IGNORECASE,
)


def _read_wiki_tables(url: str) -> List[pd.DataFrame]:
    """Fetch HTML and parse tables with pandas."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text))


def _clean_raw(raw: object) -> str:
    t = str(raw).strip().upper().replace(" ", "")
    if not t or t in {"NAN", "NONE", "-", "—", "N/A"}:
        return ""
    return t


def _normalize_yf_ticker(raw: object, suffix: Optional[str] = None) -> str:
    """
    Normalize a Wikipedia / exchange symbol for yfinance.

    - Class shares / dual listings: dots → hyphens (BRK.B → BRK-B, BT.A → BT-A)
    - Preserve an existing exchange suffix (ADS.DE, NDA-FI.HE)
    - Optionally append an exchange suffix (.TO, .L, …)
    """
    t = _clean_raw(raw)
    if not t:
        return ""

    existing = ""
    m = _YF_EXCHANGE_SUFFIX.search(t)
    if m:
        existing = m.group(0).upper()
        t = t[: m.start()]

    # Remaining dots are usually share-class markers (CTC.A, BIP.UN)
    t = t.replace(".", "-")

    if suffix:
        want = suffix if suffix.startswith(".") else f".{suffix}"
        want = want.upper()
        return f"{t}{want}"
    if existing:
        return f"{t}{existing}"
    return t


def _series_to_tickers(
    series: pd.Series,
    *,
    suffix: Optional[str] = None,
) -> List[str]:
    out: Set[str] = set()
    for val in series.tolist():
        sym = _normalize_yf_ticker(val, suffix=suffix)
        if sym:
            out.add(sym)
    return sorted(out)


def _find_col(df: pd.DataFrame, *names: str) -> Optional[str]:
    lower = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _safe_load(name: str, loader: Callable[[], List[str]]) -> List[str]:
    """Load one region; on failure warn and return [] so other regions survive."""
    try:
        tickers = loader()
        print(f"Universe: loaded {len(tickers)} from {name}")
        return tickers
    except Exception as exc:  # noqa: BLE001 — regional fetch must not wipe others
        print(f"Warning: {name} load failed ({exc}); continuing without it")
        return []


def load_sp500() -> List[str]:
    """All current S&P 500 tickers (~500 names). US, no exchange suffix."""
    tables = _read_wiki_tables(WIKI_SP500)
    df = tables[0]
    col = _find_col(df, "Symbol") or df.columns[0]
    return _series_to_tickers(df[col])


def load_nasdaq100() -> List[str]:
    """Nasdaq-100 constituents (~100 names). US, no exchange suffix."""
    last_err: Optional[Exception] = None
    for url in (WIKI_NASDAQ100, WIKI_NASDAQ100_FALLBACK):
        try:
            tables = _read_wiki_tables(url)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
        for df in tables:
            col = _find_col(df, "Ticker", "Symbol")
            if col is not None and len(df) >= 50:
                return _series_to_tickers(df[col])
    raise RuntimeError(
        f"Could not parse Nasdaq-100 table from Wikipedia ({last_err})"
    )


def load_tsx60() -> List[str]:
    """S&P/TSX 60 — liquid Canadian large caps (yfinance: XXX.TO)."""
    tables = _read_wiki_tables(WIKI_TSX60)
    for df in tables:
        col = _find_col(df, "Symbol", "Ticker")
        if col is not None and len(df) >= 40:
            tickers = _series_to_tickers(df[col], suffix=".TO")
            if len(tickers) >= 40:
                return tickers
    raise RuntimeError("Could not parse S&P/TSX 60 table from Wikipedia")


def load_ftse100() -> List[str]:
    """FTSE 100 — UK / LSE large caps (yfinance: XXX.L)."""
    tables = _read_wiki_tables(WIKI_FTSE100)
    for df in tables:
        col = _find_col(df, "Ticker", "Symbol", "EPIC")
        if col is not None and len(df) >= 80:
            tickers = _series_to_tickers(df[col], suffix=".L")
            if len(tickers) >= 80:
                return tickers
    raise RuntimeError("Could not parse FTSE 100 table from Wikipedia")


def load_euro_stoxx50() -> List[str]:
    """
    EURO STOXX 50 — Eurozone blue chips.

    Wikipedia already lists yfinance-style symbols (ADS.DE, AIR.PA, ASML.AS, …).
    """
    tables = _read_wiki_tables(WIKI_EURO_STOXX50)
    for df in tables:
        col = _find_col(df, "Ticker", "Symbol")
        if col is not None and len(df) >= 40:
            tickers = _series_to_tickers(df[col])  # suffix already on ticker
            # Prefer tables that already look exchange-suffixed
            suffixed = sum(1 for t in tickers if _YF_EXCHANGE_SUFFIX.search(t))
            if suffixed >= 30:
                return tickers
    raise RuntimeError("Could not parse EURO STOXX 50 table from Wikipedia")


def load_europe() -> List[str]:
    """Practical liquid Europe set: EURO STOXX 50 (+ FTSE 100 when used via modes)."""
    return load_euro_stoxx50()


def load_universe(cfg: StrategyConfig) -> List[str]:
    """
    Build a broad ticker universe.

    Modes:
      - sp500 / nasdaq100: US only
      - tsx60: Canada S&P/TSX 60
      - ftse100: UK FTSE 100
      - europe / eurostoxx50: EURO STOXX 50
      - international: Canada + UK + Europe (no US)
      - combined / all: US (S&P 500 ∪ Nasdaq-100) + Canada + UK + Europe

    Default ``combined`` is multi-region liquid large caps — not every stock
    worldwide. Regional Wikipedia failures are logged and skipped so a bad
    fetch cannot empty the whole universe.
    """
    mode = (cfg.universe or "combined").lower().strip()
    tickers: Set[str] = set()

    want_us = mode in ("sp500", "nasdaq100", "combined", "all", "us")
    want_sp500 = mode in ("sp500", "combined", "all", "us")
    want_nasdaq = mode in ("nasdaq100", "combined", "all", "us")
    want_tsx = mode in ("tsx60", "combined", "all", "international", "canada")
    want_ftse = mode in ("ftse100", "combined", "all", "international", "uk", "england")
    want_eu = mode in (
        "europe",
        "eurostoxx50",
        "combined",
        "all",
        "international",
    )

    # Keep US-only modes precise
    if mode == "sp500":
        want_nasdaq = False
    if mode == "nasdaq100":
        want_sp500 = False
        want_us = True

    if want_sp500:
        tickers.update(_safe_load("S&P 500", load_sp500))
    if want_nasdaq:
        tickers.update(_safe_load("Nasdaq-100", load_nasdaq100))
    if want_tsx:
        tickers.update(_safe_load("S&P/TSX 60", load_tsx60))
    if want_ftse:
        tickers.update(_safe_load("FTSE 100", load_ftse100))
    if want_eu:
        tickers.update(_safe_load("EURO STOXX 50", load_euro_stoxx50))

    if not tickers and want_us:
        # Last-ditch: empty after total failure — still return [] rather than crash
        print("Warning: universe load produced zero tickers")

    for t in cfg.exclude:
        raw = str(t).strip()
        if not raw:
            continue
        tickers.discard(raw.upper())
        tickers.discard(_normalize_yf_ticker(raw))

    out = sorted(tickers)
    if cfg.max_download and len(out) > cfg.max_download:
        out = out[: cfg.max_download]
    return out

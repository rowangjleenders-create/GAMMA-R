"""
Manual watchlist persistence.

Stores tickers the user cares about so the scanner can score them
separately from the broad-market top-N cut.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "watchlist.json"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _normalize(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


def load_watchlist(path: Path = DEFAULT_PATH) -> List[str]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
        if isinstance(raw, dict):
            items = raw.get("tickers", [])
        else:
            items = raw
        return sorted({_normalize(t) for t in items if t})
    except (json.JSONDecodeError, OSError):
        return []


def save_watchlist(tickers: List[str], path: Path = DEFAULT_PATH) -> List[str]:
    _ensure_parent(path)
    cleaned = sorted({_normalize(t) for t in tickers if t and t.strip()})
    path.write_text(json.dumps({"tickers": cleaned}, indent=2))
    return cleaned


def add_ticker(ticker: str, path: Path = DEFAULT_PATH) -> List[str]:
    current = load_watchlist(path)
    t = _normalize(ticker)
    if t and t not in current:
        current.append(t)
    return save_watchlist(current, path)


def remove_ticker(ticker: str, path: Path = DEFAULT_PATH) -> List[str]:
    t = _normalize(ticker)
    current = [x for x in load_watchlist(path) if x != t]
    return save_watchlist(current, path)


def set_watchlist(tickers: List[str], path: Path = DEFAULT_PATH) -> List[str]:
    return save_watchlist(tickers, path)


# ---- Configurable watchlist columns (desk) ----------------------------------


COLUMNS_PATH = Path(__file__).resolve().parent.parent / "data" / "watchlist_columns.json"

DEFAULT_COLUMNS: List[str] = [
    "last",
    "bid",
    "ask",
    "spread",
    "pct_chg",
    "volume",
    "signal_score",
    "news_tilt",
]

COLUMN_META: Dict[str, Dict[str, str]] = {
    "last": {"label": "Last", "source": "quotes"},
    "bid": {"label": "Bid", "source": "quotes/nbbo"},
    "ask": {"label": "Ask", "source": "quotes/nbbo"},
    "spread": {"label": "Spread", "source": "quotes/nbbo"},
    "pct_chg": {"label": "% Chg", "source": "quotes"},
    "volume": {"label": "Volume", "source": "bars/quotes"},
    "signal_score": {"label": "Signal", "source": "scanner"},
    "news_tilt": {"label": "News", "source": "news"},
}


def load_watchlist_columns(path: Path = COLUMNS_PATH) -> Dict[str, Any]:
    cols = list(DEFAULT_COLUMNS)
    if path.exists():
        try:
            raw = json.loads(path.read_text())
            if isinstance(raw, dict) and isinstance(raw.get("columns"), list):
                cleaned = []
                for c in raw["columns"]:
                    key = str(c).strip().lower().replace("%", "pct_").replace(" ", "_")
                    aliases = {"pctchange": "pct_chg", "change": "pct_chg", "chg": "pct_chg",
                               "score": "signal_score", "signal": "signal_score", "news": "news_tilt"}
                    key = aliases.get(key, key)
                    if key in COLUMN_META and key not in cleaned:
                        cleaned.append(key)
                if cleaned:
                    cols = cleaned
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "ok": True,
        "columns": cols,
        "available": list(DEFAULT_COLUMNS),
        "meta": {k: COLUMN_META[k] for k in DEFAULT_COLUMNS},
        "caption": "Configurable watchlist columns — last/bid/ask/spread/%chg/volume/signal/news",
        "not_level2": True,
    }


def save_watchlist_columns(columns: List[str], path: Path = COLUMNS_PATH) -> Dict[str, Any]:
    cleaned: List[str] = []
    for c in columns or []:
        key = str(c).strip().lower().replace("%chg", "pct_chg").replace("%_chg", "pct_chg").replace(" ", "_")
        aliases = {"pctchange": "pct_chg", "change": "pct_chg", "chg": "pct_chg",
                   "score": "signal_score", "signal": "signal_score", "news": "news_tilt"}
        key = aliases.get(key, key)
        if key in COLUMN_META and key not in cleaned:
            cleaned.append(key)
    if not cleaned:
        cleaned = list(DEFAULT_COLUMNS)
    _ensure_parent(path)
    path.write_text(json.dumps({"columns": cleaned}, indent=2))
    return load_watchlist_columns(path)

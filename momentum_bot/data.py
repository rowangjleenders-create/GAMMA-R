"""
OHLCV download helpers via yfinance.

Downloads many tickers in batches to stay polite with Yahoo's rate limits.
No paid API keys required.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure standard OHLCV columns and a clean DatetimeIndex."""
    if df is None or df.empty:
        return pd.DataFrame()

    # yfinance sometimes returns MultiIndex columns for a single ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for want in ("open", "high", "low", "close", "volume"):
        if want in cols:
            rename[cols[want]] = want.capitalize() if want != "volume" else "Volume"
            # Prefer Title-case Open/High/Low/Close/Volume
    # Force consistent names
    mapping = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl == "open":
            mapping[c] = "Open"
        elif cl == "high":
            mapping[c] = "High"
        elif cl == "low":
            mapping[c] = "Low"
        elif cl == "close":
            mapping[c] = "Close"
        elif cl == "adj close":
            mapping[c] = "Adj Close"
        elif cl == "volume":
            mapping[c] = "Volume"
    df = df.rename(columns=mapping)

    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    if not keep:
        return pd.DataFrame()
    out = df[keep].copy()
    out = out.dropna(how="all")
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    return out


def download_ohlcv(
    tickers: List[str],
    start: Optional[str] = None,
    end: Optional[str] = None,
    period: Optional[str] = None,
    batch_size: int = 50,
    auto_adjust: bool = True,
    interval: str = "1d",
) -> Dict[str, pd.DataFrame]:
    """
    Download OHLCV for many tickers.

    Prefer either (start, end) or period (e.g. "3mo", "2y").
    ``interval`` defaults to daily (1d). Use 1h / 15m for optional
    watchlist breakout speed path — do not use for classic 12-1 momentum.
    Returns {ticker: DataFrame} for tickers that returned usable data.
    """
    if not tickers:
        return {}

    if start is None and period is None:
        # Default: enough history for lookback + volume avg + buffer
        start = (datetime.utcnow() - timedelta(days=120)).strftime("%Y-%m-%d")

    results: Dict[str, pd.DataFrame] = {}
    unique = list(dict.fromkeys(tickers))  # preserve order, dedupe

    for i in range(0, len(unique), batch_size):
        batch = unique[i : i + batch_size]
        if i > 0:
            time.sleep(0.35)  # be polite to Yahoo (owner LAN scans)
        kwargs = {
            "tickers": " ".join(batch),
            "group_by": "ticker",
            "threads": True,
            "progress": False,
            "auto_adjust": auto_adjust,
            "interval": interval or "1d",
        }
        if period:
            kwargs["period"] = period
        else:
            kwargs["start"] = start
            if end:
                kwargs["end"] = end

        try:
            raw = yf.download(**kwargs)
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: batch download failed ({exc}); trying one-by-one")
            for t in batch:
                try:
                    single = yf.download(
                        t,
                        start=start,
                        end=end,
                        period=period,
                        interval=interval or "1d",
                        progress=False,
                        auto_adjust=auto_adjust,
                    )
                    norm = _normalize_ohlcv(single)
                    if not norm.empty and "Close" in norm.columns:
                        results[t] = norm
                except Exception as e2:  # noqa: BLE001
                    print(f"  skip {t}: {e2}")
            continue

        if raw is None or raw.empty:
            continue

        # Single-ticker download has flat columns
        if len(batch) == 1:
            norm = _normalize_ohlcv(raw)
            if not norm.empty:
                results[batch[0]] = norm
            continue

        # Multi-ticker: columns are MultiIndex (ticker, field) when group_by=ticker
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = raw.columns.get_level_values(0)
            for t in batch:
                if t not in level0:
                    # Sometimes yfinance uses the ticker as returned from Yahoo
                    continue
                try:
                    sub = raw[t]
                except KeyError:
                    continue
                norm = _normalize_ohlcv(sub)
                if not norm.empty and "Close" in norm.columns and len(norm) >= 2:
                    results[t] = norm
        else:
            # Unexpected shape — attach to first ticker if it looks like OHLCV
            norm = _normalize_ohlcv(raw)
            if not norm.empty and batch:
                results[batch[0]] = norm

    return results


def required_history_days(lookback_days: int, volume_avg_days: int, buffer: int = 15) -> int:
    """Calendar-day estimate so we have enough trading bars."""
    trading = max(lookback_days, volume_avg_days) + buffer
    # Roughly convert trading days -> calendar days
    return int(trading * 1.6) + 30



def download_ohlcv_intraday(
    tickers: List[str],
    interval: str = "1h",
    period: str = "5d",
    batch_size: int = 20,
) -> Dict[str, pd.DataFrame]:
    """Short-bar download for watchlist breakout / intraday heat (1m–1h)."""
    iv = (interval or "1h").strip().lower()
    if iv not in ("1m", "2m", "5m", "15m", "30m", "1h", "60m"):
        iv = "1h"
    if iv == "60m":
        iv = "1h"
    # yfinance period caps: keep callers honest
    per = period or "5d"
    if iv in ("1m", "2m") and per not in ("1d", "2d", "5d", "7d"):
        per = "1d"
    return download_ohlcv(
        tickers,
        period=per,
        batch_size=batch_size,
        interval=iv,
    )

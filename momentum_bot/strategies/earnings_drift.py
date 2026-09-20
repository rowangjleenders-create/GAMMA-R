"""
Post-earnings announcement drift (PEAD) — best-effort with free data.

Without a reliable free earnings calendar, this strategy exposes a clean
interface and degrades gracefully (returns []). Optional env keys:
  FINNHUB_API_KEY, ALPHA_VANTAGE_API_KEY, EARNINGS_API_KEY
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from ..config import StrategyConfig
from .base import Strategy, StrategySignal, last_close, pct_change


def _have_earnings_key() -> Optional[str]:
    for k in ("FINNHUB_API_KEY", "EARNINGS_API_KEY", "ALPHA_VANTAGE_API_KEY"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return k
    return None


def fetch_recent_earnings(
    tickers: Sequence[str],
    *,
    lookback_days: int = 5,
) -> List[Dict[str, Any]]:
    """
    Best-effort earnings events. Returns [] when no key / fetch fails.

    Shape: [{ticker, report_date, surprise_pct, source}]
    """
    key_name = _have_earnings_key()
    if not key_name:
        return []
    key = os.environ.get(key_name, "").strip()
    events: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")

    if key_name == "FINNHUB_API_KEY":
        # Finnhub earnings calendar (free tier rate-limited)
        url = (
            "https://finnhub.io/api/v1/calendar/earnings?"
            + urllib.parse.urlencode({"from": start, "to": end, "token": key})
        )
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            rows = payload.get("earningsCalendar") or []
            want = {t.upper() for t in tickers}
            for row in rows:
                sym = str(row.get("symbol") or "").upper()
                if sym not in want:
                    continue
                actual = row.get("epsActual")
                estimate = row.get("epsEstimate")
                surprise = None
                if actual is not None and estimate not in (None, 0):
                    try:
                        surprise = (float(actual) - float(estimate)) / abs(float(estimate))
                    except (TypeError, ValueError, ZeroDivisionError):
                        surprise = None
                events.append({
                    "ticker": sym,
                    "report_date": row.get("date"),
                    "surprise_pct": surprise,
                    "source": "finnhub",
                })
        except Exception:
            return []
    else:
        # Other keys recognized but not fully wired — degrade cleanly
        return []
    return events


class EarningsDriftStrategy(Strategy):
    id = "earnings_drift"
    name = "Earnings drift (PEAD)"
    description = (
        "Post-earnings drift tilt when a calendar is available; "
        "no-ops safely without API keys."
    )

    def generate_signals(
        self,
        universe: Sequence[str],
        bars: Mapping[str, pd.DataFrame],
        cfg: StrategyConfig,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[StrategySignal]:
        context = context or {}
        events = context.get("earnings_events")
        if events is None:
            events = fetch_recent_earnings(universe, lookback_days=5)
        if not events:
            return []

        min_surprise = float(getattr(cfg, "pead_min_surprise", 0.05) or 0.05)
        out: List[StrategySignal] = []
        for ev in events:
            ticker = str(ev.get("ticker") or "").upper()
            if not ticker or ticker not in bars:
                continue
            surprise = ev.get("surprise_pct")
            if surprise is None or float(surprise) < min_surprise:
                continue
            df = bars[ticker]
            entry = last_close(df)
            if entry is None:
                continue
            # Mild positive drift confirmation after beat
            ret_3 = pct_change(df, 3)
            if ret_3 is not None and ret_3 < -0.05:
                continue  # already reversing hard
            score = float(surprise) + (float(ret_3) if ret_3 else 0.0) * 0.5
            out.append(
                StrategySignal(
                    ticker=ticker,
                    side="long",
                    score=round(score, 6),
                    strategy_id=self.id,
                    rationale=(
                        f"PEAD: earnings surprise {float(surprise)*100:.1f}% "
                        f"on {ev.get('report_date')} ({ev.get('source')})"
                    ),
                    suggested_size_mult=0.9,
                    entry=round(entry, 4),
                    momentum_pct=round(float(ret_3), 6) if ret_3 is not None else None,
                    meta={"surprise_pct": surprise, "report_date": ev.get("report_date")},
                )
            )
        out.sort(key=lambda s: s.score, reverse=True)
        return out[:10]


def earnings_provider_status() -> Dict[str, Any]:
    key = _have_earnings_key()
    return {
        "configured": bool(key),
        "env_key": key,
        "note": (
            "Set FINNHUB_API_KEY for a free-tier earnings calendar; "
            "without it PEAD returns no signals (safe no-op)."
            if not key
            else f"Using {key} for earnings calendar (best-effort)."
        ),
    }

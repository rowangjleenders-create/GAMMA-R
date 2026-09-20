"""
Economic calendar rail — static allowlisted events + light refresh.

GET /calendar/economic
No scrape of blocked sites; curated high-impact US/EU events with rolling dates.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_PATH = DATA_DIR / "economic_calendar.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _anchor_week_monday(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    d = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


def _default_events(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Curated recurring templates mapped onto the current / next few weeks."""
    mon = _anchor_week_monday(now)
    # Template: (weekday offset from Monday, hour UTC, title, country, impact, category)
    templates = [
        (2, 12, 30, "US CPI (YoY)", "US", "high", "inflation"),
        (3, 12, 30, "US Retail Sales", "US", "medium", "growth"),
        (4, 12, 30, "US Existing Home Sales", "US", "low", "housing"),
        (0, 13, 0, "ISM Manufacturing PMI", "US", "high", "activity"),
        (4, 12, 30, "US PCE Price Index", "US", "high", "inflation"),
        (1, 12, 30, "US PPI", "US", "medium", "inflation"),
        (2, 18, 0, "FOMC Rate Decision (approx)", "US", "high", "rates"),
        (3, 12, 15, "ECB Rate Decision (approx)", "EU", "high", "rates"),
        (2, 11, 0, "UK CPI", "UK", "medium", "inflation"),
        (4, 12, 30, "US Nonfarm Payrolls (approx week)", "US", "high", "labor"),
        (3, 14, 0, "Initial Jobless Claims", "US", "medium", "labor"),
        (1, 14, 0, "Consumer Confidence", "US", "medium", "sentiment"),
    ]
    events: List[Dict[str, Any]] = []
    for week in range(0, 4):
        base = mon + timedelta(weeks=week)
        for wd, hh, mm, title, country, impact, cat in templates:
            # Stagger: only include subset per week to avoid clutter
            if week == 0 and wd not in (0, 2, 3, 4):
                continue
            if week == 1 and cat not in ("inflation", "rates", "labor"):
                continue
            if week >= 2 and impact != "high":
                continue
            when = base + timedelta(days=wd, hours=hh, minutes=mm)
            events.append({
                "id": f"{title.lower().replace(' ', '-')}-w{week}",
                "title": title,
                "country": country,
                "impact": impact,
                "category": cat,
                "when": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "when_ts": int(when.timestamp()),
                "source": "curated_static",
            })
    events.sort(key=lambda e: e["when_ts"])
    return events


def _load_cache() -> Optional[Dict[str, Any]]:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _save_cache(payload: Dict[str, Any]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_economic_calendar(
    *,
    days: int = 21,
    refresh: bool = False,
    limit: int = 40,
) -> Dict[str, Any]:
    """
    Return upcoming economic events for Dashboard rail.
    refresh=True rebuilds from curated templates (no hostile scrape).
    """
    now = datetime.now(timezone.utc)
    cached = None if refresh else _load_cache()
    if cached and cached.get("events"):
        events = list(cached["events"])
        source = cached.get("source") or "cache"
    else:
        events = _default_events(now)
        source = "curated_static"
        payload = {
            "events": events,
            "source": source,
            "refreshed_at": _utc_now(),
        }
        _save_cache(payload)

    horizon = now + timedelta(days=max(1, min(int(days or 21), 60)))
    upcoming = [
        e for e in events
        if e.get("when_ts") and now.timestamp() - 3600 <= float(e["when_ts"]) <= horizon.timestamp()
    ]
    upcoming = upcoming[: max(1, min(int(limit or 40), 100))]

    return {
        "ok": True,
        "count": len(upcoming),
        "events": upcoming,
        "days": days,
        "source": source,
        "refreshed_at": (cached or {}).get("refreshed_at") if cached and not refresh else _utc_now(),
        "label": "Economic calendar (curated) — Dashboard rail",
        "note": (
            "Allowlisted/curated high-impact events. Not a live scrape of every bureau release. "
            "Times are approximate UTC anchors for education."
        ),
        "generated_at": _utc_now(),
    }

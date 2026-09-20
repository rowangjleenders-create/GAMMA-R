"""
Time zone & market-hours utilities.

- Store timestamps in UTC internally.
- Display as user local TZ + market TZ (e.g. US/Eastern for NYSE/NASDAQ).
- Gate or label signals by session: open / pre / after / closed.
- Historical bars: filter to exchange sessions (no weekend/holiday) via
  exchange_calendars when installed; else weekday+yfinance session filter.

Exchanges:
  US (NYSE/NASDAQ), TSX (Canada), LSE (UK), Xetra (Germany),
  Euronext Paris/Amsterdam/Brussels/Lisbon, plus Asia stubs (TSE, HKEX).

Per-ticker session gates map yfinance suffixes (.TO, .L, .DE, .PA, .AS, …)
to the home exchange so multi-region universes respect each name's hours.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

# Exchange metadata (hours in local market TZ; calendars for holidays)
EXCHANGES: Dict[str, Dict[str, Any]] = {
    "NYSE": {
        "tz": "America/New_York",
        "open": time(9, 30),
        "close": time(16, 0),
        "calendar": "XNYS",
        "label": "US/Eastern",
    },
    "NASDAQ": {
        "tz": "America/New_York",
        "open": time(9, 30),
        "close": time(16, 0),
        "calendar": "XNAS",
        "label": "US/Eastern",
    },
    "TSX": {
        "tz": "America/Toronto",
        "open": time(9, 30),
        "close": time(16, 0),
        "calendar": "XTSE",
        "label": "Canada/Toronto",
    },
    "LSE": {
        "tz": "Europe/London",
        "open": time(8, 0),
        "close": time(16, 30),
        "calendar": "XLON",
        "label": "UK/London",
    },
    "XETRA": {
        "tz": "Europe/Berlin",
        "open": time(9, 0),
        "close": time(17, 30),
        "calendar": "XFRA",
        "label": "Germany/Berlin",
    },
    "EURONEXT_PA": {
        "tz": "Europe/Paris",
        "open": time(9, 0),
        "close": time(17, 30),
        "calendar": "XPAR",
        "label": "France/Paris",
    },
    "EURONEXT_AS": {
        "tz": "Europe/Amsterdam",
        "open": time(9, 0),
        "close": time(17, 30),
        "calendar": "XAMS",
        "label": "Netherlands/Amsterdam",
    },
    "EURONEXT_BR": {
        "tz": "Europe/Brussels",
        "open": time(9, 0),
        "close": time(17, 30),
        "calendar": "XBRU",
        "label": "Belgium/Brussels",
    },
    "EURONEXT_LS": {
        "tz": "Europe/Lisbon",
        "open": time(8, 0),
        "close": time(16, 30),
        "calendar": "XLIS",
        "label": "Portugal/Lisbon",
    },
    "SIX": {
        "tz": "Europe/Zurich",
        "open": time(9, 0),
        "close": time(17, 30),
        "calendar": "XSWX",
        "label": "Switzerland/Zurich",
    },
    "MILAN": {
        "tz": "Europe/Rome",
        "open": time(9, 0),
        "close": time(17, 30),
        "calendar": "XMIL",
        "label": "Italy/Milan",
    },
    "BME": {
        "tz": "Europe/Madrid",
        "open": time(9, 0),
        "close": time(17, 30),
        "calendar": "XMAD",
        "label": "Spain/Madrid",
    },
    "OMX_STO": {
        "tz": "Europe/Stockholm",
        "open": time(9, 0),
        "close": time(17, 30),
        "calendar": "XSTO",
        "label": "Sweden/Stockholm",
    },
    "OMX_HEL": {
        "tz": "Europe/Helsinki",
        "open": time(10, 0),
        "close": time(18, 30),
        "calendar": "XHEL",
        "label": "Finland/Helsinki",
    },
    "OMX_CPH": {
        "tz": "Europe/Copenhagen",
        "open": time(9, 0),
        "close": time(17, 0),
        "calendar": "XCSE",
        "label": "Denmark/Copenhagen",
    },
    "OSE": {
        "tz": "Europe/Oslo",
        "open": time(9, 0),
        "close": time(16, 20),
        "calendar": "XOSL",
        "label": "Norway/Oslo",
    },
    "VIE": {
        "tz": "Europe/Vienna",
        "open": time(9, 0),
        "close": time(17, 30),
        "calendar": "XVIE",
        "label": "Austria/Vienna",
    },
    "TSE": {  # Tokyo stub
        "tz": "Asia/Tokyo",
        "open": time(9, 0),
        "close": time(15, 0),
        "calendar": "XTKS",
        "label": "Japan/Tokyo",
        "stub": True,
    },
    "HKEX": {  # stub
        "tz": "Asia/Hong_Kong",
        "open": time(9, 30),
        "close": time(16, 0),
        "calendar": "XHKG",
        "label": "Hong Kong",
        "stub": True,
    },
}

# yfinance exchange suffix → EXCHANGES key
# Handles both ".L" (universe) and "-L" (normalized watchlist/paper) forms.
_SUFFIX_TO_EXCHANGE: Dict[str, str] = {
    "TO": "TSX",
    "V": "TSX",  # TSX Venture — same Toronto hours
    "L": "LSE",
    "DE": "XETRA",
    "F": "XETRA",
    "PA": "EURONEXT_PA",
    "AS": "EURONEXT_AS",
    "BR": "EURONEXT_BR",
    "LS": "EURONEXT_LS",
    "SW": "SIX",
    "MI": "MILAN",
    "MC": "BME",
    "ST": "OMX_STO",
    "HE": "OMX_HEL",
    "CO": "OMX_CPH",
    "OL": "OSE",
    "VI": "VIE",
    "IR": "EURONEXT_PA",  # Irish — approximate with Paris hours
    "AT": "VIE",
    "T": "TSE",
    "HK": "HKEX",
}

_SUFFIX_RE = re.compile(
    r"[.\-](" + "|".join(sorted(_SUFFIX_TO_EXCHANGE.keys(), key=len, reverse=True)) + r")$",
    re.IGNORECASE,
)

DEFAULT_EXCHANGE = "NYSE"
DEFAULT_USER_TZ = "America/Chicago"  # US/Central — matches common US users; app overrides


@dataclass
class SessionInfo:
    exchange: str
    market_tz: str
    user_tz: str
    utc_iso: str
    market_local: str
    user_local: str
    dual_label: str  # e.g. "3:00 AM EST / 9:00 AM CEST"
    session: str  # open | pre | after | closed | holiday
    is_open: bool
    allow_act: bool  # whether bot should act (vs label-only)
    ticker: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def exchange_for_ticker(ticker: str, default: str = DEFAULT_EXCHANGE) -> str:
    """
    Map a yfinance-style ticker to its home exchange key in EXCHANGES.

    Examples:
      AAPL / BRK-B  → NYSE (default US)
      RY.TO / RY-TO → TSX
      VOD.L / VOD-L → LSE
      ADS.DE        → XETRA
      AIR.PA        → EURONEXT_PA
      ASML.AS       → EURONEXT_AS
    """
    if not ticker:
        return default
    t = str(ticker).strip().upper()
    m = _SUFFIX_RE.search(t)
    if not m:
        return default
    return _SUFFIX_TO_EXCHANGE.get(m.group(1).upper(), default)


def format_dual(dt_utc: datetime, user_tz: str, market_tz: str) -> Tuple[str, str, str]:
    """Return (market_local, user_local, dual_label)."""
    dt_utc = to_utc(dt_utc)
    m = dt_utc.astimezone(_tz(market_tz))
    u = dt_utc.astimezone(_tz(user_tz))
    # Use %Z for abbrev when available
    m_s = m.strftime("%I:%M %p %Z").lstrip("0")
    u_s = u.strftime("%I:%M %p %Z").lstrip("0")
    # Also include dates if different calendar days
    if m.date() != u.date():
        m_s = m.strftime("%Y-%m-%d %I:%M %p %Z").lstrip("0")
        u_s = u.strftime("%Y-%m-%d %I:%M %p %Z").lstrip("0")
    dual = f"{m_s} / {u_s}"
    return m.isoformat(), u.isoformat(), dual


def _is_holiday(exchange: str, d_local: datetime) -> bool:
    """Best-effort holiday check via exchange_calendars."""
    meta = EXCHANGES.get(exchange, EXCHANGES[DEFAULT_EXCHANGE])
    cal_name = meta.get("calendar")
    if not cal_name:
        return False
    try:
        import exchange_calendars as xcals

        cal = xcals.get_calendar(cal_name)
        # session date in calendar tz
        day = pd.Timestamp(d_local.date())
        return not cal.is_session(day)
    except Exception:
        # Weekends always closed
        return d_local.weekday() >= 5


def get_session(
    exchange: str = DEFAULT_EXCHANGE,
    user_tz: str = DEFAULT_USER_TZ,
    at: Optional[datetime] = None,
    allow_after_hours_signals: bool = True,
    ticker: Optional[str] = None,
) -> SessionInfo:
    """
    Classify market session at `at` (UTC). Signals may still be generated
    after-hours but must be labeled; allow_act is False unless open
    (or allow_after_hours_signals and pre/after with label).

    If `ticker` is provided and exchange is still the default, resolve the
    home exchange from the ticker suffix.
    """
    ex = (exchange or DEFAULT_EXCHANGE).upper()
    if ticker and (not exchange or ex == DEFAULT_EXCHANGE):
        # When caller left default exchange but passed a ticker, prefer home venue
        resolved = exchange_for_ticker(ticker, default=ex)
        if resolved != ex or not exchange:
            ex = resolved
    meta = EXCHANGES.get(ex, EXCHANGES[DEFAULT_EXCHANGE])
    if ex not in EXCHANGES:
        ex = DEFAULT_EXCHANGE
        meta = EXCHANGES[DEFAULT_EXCHANGE]
    market_tz = meta["tz"]
    at = to_utc(at or now_utc())
    local = at.astimezone(_tz(market_tz))
    holiday = _is_holiday(ex, local)

    open_t, close_t = meta["open"], meta["close"]
    t = local.time()
    if holiday or local.weekday() >= 5:
        session = "holiday" if holiday and local.weekday() < 5 else "closed"
        is_open = False
    elif open_t <= t < close_t:
        session = "open"
        is_open = True
    elif time(4, 0) <= t < open_t:  # pre-market window (US-centric start; OK as label)
        session = "pre"
        is_open = False
    elif close_t <= t < time(20, 0):
        session = "after"
        is_open = False
    else:
        session = "closed"
        is_open = False

    # Act only in open session unless after-hours explicitly allowed (label-only act=False for closed/holiday)
    if is_open:
        allow_act = True
    elif session in ("pre", "after") and allow_after_hours_signals:
        allow_act = False  # generate but label; caller decides
    else:
        allow_act = False

    m_iso, u_iso, dual = format_dual(at, user_tz, market_tz)
    return SessionInfo(
        exchange=ex,
        market_tz=market_tz,
        user_tz=user_tz,
        utc_iso=at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        market_local=m_iso,
        user_local=u_iso,
        dual_label=dual,
        session=session,
        is_open=is_open,
        allow_act=allow_act or is_open,
        ticker=ticker,
    )


def get_ticker_session(
    ticker: str,
    user_tz: str = DEFAULT_USER_TZ,
    at: Optional[datetime] = None,
    allow_after_hours_signals: bool = True,
    default_exchange: str = DEFAULT_EXCHANGE,
) -> SessionInfo:
    """Session for a ticker's home exchange (suffix-aware)."""
    ex = exchange_for_ticker(ticker, default=default_exchange)
    return get_session(
        exchange=ex,
        user_tz=user_tz,
        at=at,
        allow_after_hours_signals=allow_after_hours_signals,
        ticker=ticker,
    )


def is_home_session_open(
    ticker: str,
    *,
    at: Optional[datetime] = None,
    default_exchange: str = DEFAULT_EXCHANGE,
) -> bool:
    """True iff the ticker's home market is in regular trading hours."""
    return bool(get_ticker_session(ticker, at=at, default_exchange=default_exchange).is_open)


def should_allow_new_entry(
    ticker: str,
    cfg: Any,
    *,
    at: Optional[datetime] = None,
) -> Tuple[bool, str, Optional[SessionInfo]]:
    """
    Gate NEW entries by the ticker's home session.

    Config:
      use_per_ticker_sessions (default True) — map suffix → home exchange
      session_gate_entries    (default True) — skip NEW entries when home closed
      only_act_during_open    (legacy) — also enables the gate when True

    Gating is ON when session_gate_entries OR only_act_during_open.
    With use_per_ticker_sessions, each ticker uses its home calendar/hours
    (LSE for .L, TSX for .TO, Xetra for .DE, …); otherwise market_exchange.
    Exits / risk management are NOT gated here — callers still run those.
    """
    use_per = bool(getattr(cfg, "use_per_ticker_sessions", True))
    only_open = bool(getattr(cfg, "only_act_during_open", False))
    gate_entries = bool(getattr(cfg, "session_gate_entries", True))
    user_tz = getattr(cfg, "user_timezone", DEFAULT_USER_TZ) or DEFAULT_USER_TZ
    default_ex = getattr(cfg, "market_exchange", DEFAULT_EXCHANGE) or DEFAULT_EXCHANGE

    active_gate = bool(gate_entries or only_open)
    if not active_gate:
        return True, "session_gate_off", None

    if use_per:
        info = get_ticker_session(
            ticker,
            user_tz=user_tz,
            at=at,
            allow_after_hours_signals=bool(getattr(cfg, "allow_after_hours_signals", True)),
            default_exchange=default_ex,
        )
    else:
        info = get_session(
            exchange=default_ex,
            user_tz=user_tz,
            at=at,
            allow_after_hours_signals=bool(getattr(cfg, "allow_after_hours_signals", True)),
            ticker=ticker,
        )

    if info.is_open:
        return True, "home_session_open", info
    return False, f"home_session_{info.session}:{info.exchange}", info


def annotate_timestamp(dt_utc: datetime, user_tz: str, exchange: str = DEFAULT_EXCHANGE) -> Dict[str, str]:
    meta = EXCHANGES.get(exchange, EXCHANGES[DEFAULT_EXCHANGE])
    m_iso, u_iso, dual = format_dual(dt_utc, user_tz, meta["tz"])
    return {
        "utc": to_utc(dt_utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market_local": m_iso,
        "user_local": u_iso,
        "display": dual,
        "market_tz": meta["tz"],
        "user_tz": user_tz,
    }


def filter_session_bars(
    df: pd.DataFrame,
    exchange: str = DEFAULT_EXCHANGE,
) -> pd.DataFrame:
    """
    Drop weekend/holiday bars using exchange calendar when available.
    yfinance daily bars are already session-aligned for US; this removes
    any residual non-sessions for historical training safety.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    meta = EXCHANGES.get(exchange, EXCHANGES[DEFAULT_EXCHANGE])
    try:
        import exchange_calendars as xcals

        cal = xcals.get_calendar(meta["calendar"])
        # Normalize to date
        mask = [cal.is_session(pd.Timestamp(ts.date())) for ts in out.index]
        return out.loc[mask]
    except Exception:
        # Fallback: drop weekends only
        return out[out.index.dayofweek < 5]


def session_bucket_for_learning(
    exchange: str = DEFAULT_EXCHANGE,
    at: Optional[datetime] = None,
    ticker: Optional[str] = None,
) -> str:
    """
    Coarse session tag for self-learning logs: us_rth | us_extended | asia | europe | closed.
    """
    if ticker:
        exchange = exchange_for_ticker(ticker, default=exchange)
    info = get_session(exchange=exchange, at=at)
    ex = exchange.upper()
    if ex in ("TSE", "HKEX"):
        return "asia" if info.session == "open" else "asia_closed"
    if ex in (
        "LSE", "XETRA", "EURONEXT_PA", "EURONEXT_AS", "EURONEXT_BR", "EURONEXT_LS",
        "SIX", "MILAN", "BME", "OMX_STO", "OMX_HEL", "OMX_CPH", "OSE", "VIE",
    ):
        return "europe" if info.session == "open" else "europe_closed"
    if ex == "TSX":
        return "canada_rth" if info.session == "open" else "canada_closed"
    if info.session == "open":
        return "us_rth"
    if info.session in ("pre", "after"):
        return "us_extended"
    return "closed"


def maintenance_window_status(
    *,
    exchange: str = DEFAULT_EXCHANGE,
    open_buffer_minutes: int = 15,
    close_buffer_minutes: int = 15,
    enabled: bool = True,
    at: Optional[datetime] = None,
    ticker: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pause new entries during low-liquidity stretches:
      - first N minutes after the open
      - last N minutes before the close
    Times are in the exchange TZ.

    Learning is unaffected; callers decide whether exits still run.
    """
    if ticker:
        exchange = exchange_for_ticker(ticker, default=exchange)
    info = get_session(exchange=exchange, at=at)
    meta = EXCHANGES.get(exchange.upper(), EXCHANGES[DEFAULT_EXCHANGE])
    market_tz = meta["tz"]
    dt = to_utc(at or now_utc()).astimezone(_tz(market_tz))
    open_t: time = meta["open"]
    close_t: time = meta["close"]
    minutes_since_open = (dt.hour * 60 + dt.minute) - (open_t.hour * 60 + open_t.minute)
    minutes_to_close = (close_t.hour * 60 + close_t.minute) - (dt.hour * 60 + dt.minute)

    in_open_buf = bool(info.is_open and open_buffer_minutes > 0 and 0 <= minutes_since_open < open_buffer_minutes)
    in_close_buf = bool(info.is_open and close_buffer_minutes > 0 and 0 <= minutes_to_close < close_buffer_minutes)
    active = bool(enabled and (in_open_buf or in_close_buf))
    reason = None
    if in_open_buf:
        reason = f"open_buffer ({minutes_since_open}m < {open_buffer_minutes}m after open)"
    elif in_close_buf:
        reason = f"close_buffer ({minutes_to_close}m < {close_buffer_minutes}m before close)"

    return {
        "enabled": bool(enabled),
        "active": active,
        "reason": reason,
        "in_open_buffer": in_open_buf,
        "in_close_buffer": in_close_buf,
        "minutes_since_open": minutes_since_open if info.is_open else None,
        "minutes_to_close": minutes_to_close if info.is_open else None,
        "open_buffer_minutes": int(open_buffer_minutes),
        "close_buffer_minutes": int(close_buffer_minutes),
        "session": info.session,
        "is_open": info.is_open,
        "market_local": info.market_local,
        "exchange": exchange.upper(),
        "market_tz": market_tz,
        "ticker": ticker,
    }

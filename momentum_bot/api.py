"""
FastAPI app for the GAMMA-R API.

Endpoints cover health, config, scan/signals, backtest, paper portfolio,
watchlist, push-token registration, learning (live + historical), and E-ve assistant chat.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, JSONResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .backtest import run_backtest, run_session_replay
from .config import StrategyConfig, get_runtime_config, set_runtime_config, save_runtime_overlay
from .historical import ALLOWED_YEARS, DEFAULT_YEARS, run_historical_train
from .learning import (
    apply_learned_on_startup,
    day_one_baseline,
    learning_stats,
    load_historical_baseline,
    load_history,
    reset_learning,
    run_learning,
)
from .optimization import detect_regime, get_ensemble_weights, get_last_regime
from . import paper as paper_mod
from .scanner import get_cached_signals, get_news_impact, get_scan_status, run_scan, signals_to_dicts
from .news import (
    collect_news,
    aggregate_ticker_news,
    sector_sentiment_impact,
    enrich_news_display,
    build_eod_digest,
)
from .currency import get_currency_quotes, get_currency_pair
from .timezone_util import get_session, EXCHANGES
from .watchlist import add_ticker, load_watchlist, remove_ticker, set_watchlist, load_watchlist_columns, save_watchlist_columns
from .brokers import get_broker, live_trading_enabled, kill_switch
from .data_sources import (
    get_data_source_status,
    recent_events as data_source_events,
    realtime_sip_enabled,
    reset_fallback,
    set_realtime_sip_enabled,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PUSH_TOKENS_PATH = DATA_DIR / "push_tokens.json"

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup: merge config, start unattended learn/trade loops. Shutdown: stop loops."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    apply_learned_on_startup()
    try:
        sip_on = realtime_sip_enabled()
        cfg = get_runtime_config().update({"realtime_sip_enabled": sip_on})
        set_runtime_config(cfg)
        print(
            f"GAMMA-R API v{__version__} ready. "
            f"Config merge: SEED → historical → live-learned → runtime. "
            f"Data source live={'alpaca_sip' if sip_on else 'free'} (historical always free)."
        )
    except Exception as exc:  # noqa: BLE001
        print(f"GAMMA-R API v{__version__} ready. Data-source sync warning: {exc}")

    from .auto_loops import start_auto_loops, stop_auto_loops
    start_auto_loops()
    print("[auto] learn + trade + exit background loops started")
    try:
        yield
    finally:
        await stop_auto_loops()
        print("[auto] background loops stopped")


def _docs_off() -> bool:
    return os.environ.get("REQUIRE_API_SECRET", "").strip().lower() in ("1", "true", "yes", "on") or (
        os.environ.get("GAMMA_R_HARDENED", "").strip().lower() in ("1", "true", "yes", "on")
    )


app = FastAPI(
    title="GAMMA-R API",
    version=__version__,
    description="Educational momentum scanner + paper trading (not financial advice).",
    lifespan=_lifespan,
    docs_url=None if _docs_off() else "/docs",
    redoc_url=None if _docs_off() else "/redoc",
    openapi_url=None if _docs_off() else "/openapi.json",
)
# CORS: allowlist (never "*" with credentials). Override via CORS_ALLOW_ORIGINS.
from .security import cors_allow_origins as _cors_allow_origins

_CORS_ORIGINS = _cors_allow_origins()
_CORS_CREDENTIALS = "*" not in _CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=_CORS_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _security_response_headers(request, call_next):
    """API JSON hardening headers; strip verbose Server fingerprint when possible."""
    from .security import security_headers as _sec_headers

    response = await call_next(request)
    for k, v in _sec_headers().items():
        response.headers.setdefault(k, v)
    if "server" in response.headers:
        del response.headers["server"]
    return response


# ---- models ----

class ConfigUpdate(BaseModel):
    model_config = {"extra": "allow"}

    # Accept arbitrary strategy fields via extra

class BrokerOrderRequest(BaseModel):
    ticker: str
    shares: float
    side: str = "buy"
    strategy_id: Optional[str] = None
    human_approved: bool = False
    limit_price: Optional[float] = None

class BrokerEnableInfo(BaseModel):
    acknowledge_risk: bool = False


class BacktestRequest(BaseModel):
    years: Optional[int] = None


class OrderRequest(BaseModel):
    ticker: str
    shares: Optional[int] = None
    entry: Optional[float] = None
    stop: Optional[float] = None
    take_profit: Optional[float] = None
    source: str = "scan"
    forward_probability: Optional[float] = None
    forward_threshold: Optional[float] = None
    ensemble_votes: Optional[Dict[str, float]] = None
    confidence: Optional[float] = None
    context: Optional[Dict[str, Any]] = None
    strategy_id: Optional[str] = None
    human_approved: bool = False
    # Pro paper order types (paper-only through firewall)
    order_type: Optional[str] = None  # market|limit|stop|take_profit|bracket|oco
    trigger_price: Optional[float] = None
    limit_price: Optional[float] = None


class CustomScanBody(BaseModel):
    min_volume: Optional[float] = None
    min_volume_ratio: Optional[float] = None
    min_pct_change: Optional[float] = None
    max_pct_change: Optional[float] = None
    min_rs: Optional[float] = None
    news_tilt: Optional[str] = None  # bullish|bearish|any
    strategy_id: Optional[str] = None
    region: Optional[str] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    min_confidence: Optional[float] = None
    limit: int = 50
    refresh: bool = False


class ProOrderBody(BaseModel):
    ticker: str
    shares: int
    order_type: str = "bracket"  # market|limit|stop|take_profit|bracket|oco
    entry: Optional[float] = None
    stop: Optional[float] = None
    take_profit: Optional[float] = None
    trigger_price: Optional[float] = None
    limit_price: Optional[float] = None
    strategy_id: Optional[str] = None
    source: str = "pro_ui"
    human_approved: bool = False


class ModeRequest(BaseModel):
    mode: str = "paper"


class WatchlistBody(BaseModel):
    tickers: List[str] = Field(default_factory=list)


class WatchlistTicker(BaseModel):
    ticker: str


class DeskCommandBody(BaseModel):
    command: str = ""
    enrich: bool = True


class WatchlistColumnsBody(BaseModel):
    columns: List[str] = Field(default_factory=list)


class NotifyRegister(BaseModel):
    token: str
    platform: str = "expo"


class LearningReset(BaseModel):
    wipe_journal: bool = False
    wipe_history: bool = True
    wipe_historical: bool = False


class HistoricalTrainRequest(BaseModel):
    years: int = DEFAULT_YEARS  # default 20
    max_tickers: int = 80


class CopilotMessage(BaseModel):
    role: str = "user"
    content: str = ""


class CopilotRequest(BaseModel):
    message: str
    history: List[CopilotMessage] = Field(default_factory=list)


# ---- helpers ----

def _load_tokens() -> List[Dict[str, str]]:
    if not PUSH_TOKENS_PATH.exists():
        return []
    try:
        return list(json.loads(PUSH_TOKENS_PATH.read_text()).get("tokens", []))
    except Exception:
        return []


def _save_tokens(tokens: List[Dict[str, str]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PUSH_TOKENS_PATH.write_text(json.dumps({"tokens": tokens}, indent=2))


def _stub_notify(payload: Dict[str, Any]) -> None:
    """
    Stub: log notification payload. Hook Expo push / FCM here:
      POST https://exp.host/--/api/v2/push/send  with {to: token, title, body, data}
    """
    print(f"[notify stub] Would push to {len(_load_tokens())} device(s): keys={list(payload.keys())}")


# ---- health / config / security ----

from .security import (
    InMemoryRateLimiter,
    auth_exempt_paths,
    auth_status_label,
    client_ip,
    extract_provided_secret,
    hardened_mode,
    remote_access_enabled as _remote_access_enabled,
    bind_host as _bind_host,
    redact_obj,
    redact_text,
    scrub_url,
    secrets_equal,
    shared_secret as _security_shared_secret,
    should_rate_limit,
)

_rate_limiter = InMemoryRateLimiter()


def _owner_mode() -> bool:
    """Private single-user: open by default. Set OWNER_SHARED_SECRET to gate remote callers."""
    return os.environ.get("OWNER_MODE", "1").strip().lower() not in ("0", "false", "no")


def _shared_secret() -> str:
    return _security_shared_secret()


@app.middleware("http")
async def _security_gate(request, call_next):
    """
    Owner auth + rate limit + query-secret rejection.

    - Secret from OWNER_SHARED_SECRET / API_SHARED_SECRET / data/.owner_secret
    - Required when secret is set, or when hardened (non-loopback / REQUIRE_API_SECRET /
      GAMMA_R_HARDENED) — missing secret then → 503 with clear error
    - Accept only X-Owner-Secret or Authorization: Bearer … (reject ?owner_secret=)
    - Constant-time compare; /health always exempt; docs protected in hardened mode
    - In-memory rate limit on mutating routes and /copilot
    """
    from starlette.responses import JSONResponse

    path = request.url.path or ""
    method = request.method or "GET"
    secret = _shared_secret()
    hard = hardened_mode()
    protect_docs = hard or bool(secret)
    exempt = auth_exempt_paths(protect_docs=protect_docs)

    # Deprecate query param — never accept (avoids URL/proxy/access-log leaks)
    _got, query_present = extract_provided_secret(request.headers, request.query_params)
    if query_present:
        return JSONResponse(
            {
                "detail": (
                    "Query parameter owner_secret is no longer accepted "
                    "(leaks via logs/Referer). Use X-Owner-Secret or Authorization: Bearer."
                )
            },
            status_code=400,
        )

    if path not in exempt:
        if hard and not secret:
            return JSONResponse(
                {
                    "detail": (
                        "API secret required (non-loopback bind or REQUIRE_API_SECRET / "
                        "GAMMA_R_HARDENED). Set OWNER_SHARED_SECRET or restart serve to "
                        "generate data/.owner_secret."
                    )
                },
                status_code=503,
            )
        if secret:
            if not secrets_equal(_got, secret):
                return JSONResponse(
                    {"detail": "Invalid or missing X-Owner-Secret (or Bearer token)"},
                    status_code=401,
                )

    if should_rate_limit(method, path):
        ip = client_ip(request)
        if not _rate_limiter.allow(f"{ip}:{method}"):
            return JSONResponse(
                {"detail": "Rate limit exceeded — try again shortly"},
                status_code=429,
                headers={"Retry-After": "60"},
            )

    response = await call_next(request)
    # Scrubbed access breadcrumb (never log raw query secrets)
    try:
        safe = scrub_url(str(request.url))
        if response.status_code >= 400:
            print(f"[access] {method} {safe} → {response.status_code}")
    except Exception:
        pass
    return response


@app.exception_handler(HTTPException)
async def _redacting_http_exception_handler(request, exc: HTTPException):
    """Redact secret-shaped text from error details."""
    from starlette.responses import JSONResponse

    detail = exc.detail
    if isinstance(detail, str):
        detail = redact_text(detail)
    elif isinstance(detail, (dict, list)):
        detail = redact_obj(detail)
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def _redacting_unhandled_handler(request, exc):
    """Avoid echoing secrets in 500 bodies / logs."""
    from starlette.responses import JSONResponse

    if isinstance(exc, HTTPException):
        return await _redacting_http_exception_handler(request, exc)
    print(f"[error] {request.method} {scrub_url(str(request.url))}: {redact_text(str(exc))}")
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.get("/health")
def health():
    """Public probe: status + auth mode only (no secrets / inventory)."""
    from . import __version__

    features = {"external_trades_import": True}
    try:
        from .external_trades import feature_info
        features.update(feature_info())
    except Exception:
        pass

    return {
        "status": "ok",
        "version": __version__,
        "auth": auth_status_label(),
        "hardened": hardened_mode(),
        "live_trading_enabled": live_trading_enabled(),
        "owner_mode": _owner_mode(),
        "features": features,
    }


class RemoteSessionBody(BaseModel):
    """Optional client hint for POST /remote/session (no JWT minted — secret header is the session)."""
    client: Optional[str] = None
    note: Optional[str] = None


@app.get("/remote/status")
def remote_status():
    """
    Public probe for remote-access posture (no secrets).
    Prefer Tailscale / Cloudflare Tunnel / SSH over a naked public IP.
    """
    ra = _remote_access_enabled()
    hard = hardened_mode()
    secret_on = bool(_shared_secret())
    return {
        "remote_access_enabled": ra,
        "hardened": hard,
        "auth": auth_status_label(),
        "secret_required": hard or secret_on,
        "secret_configured": secret_on,
        "bind_host": _bind_host(),
        "live_trading_enabled": live_trading_enabled(),
        "live_locked": not live_trading_enabled(),
        "prefer_tunnel": True,
        "recommended_tunnels": ["tailscale", "cloudflare_tunnel", "ssh_tunnel"],
        "warnings": [
            "Do not expose 0.0.0.0 to the public internet without TLS + owner secret.",
            "Prefer Tailscale, Cloudflare Tunnel, or SSH reverse tunnel over a naked public IP.",
            "Live trading stays locked unless LIVE_TRADING_ENABLED=1 (fail-closed).",
            "Owner secret required for all non-exempt routes when remote or non-loopback.",
        ],
        "docs": "See docs/REMOTE_ACCESS.md or scripts/remote_access_setup.md",
    }


@app.post("/remote/session")
def remote_session(body: Optional[RemoteSessionBody] = None):
    """
    Validate owner secret for remote clients (middleware already enforced).
    Does not mint a separate JWT — keep sending X-Owner-Secret / Bearer.
    """
    ra = _remote_access_enabled()
    if not ra and not hardened_mode():
        # Still allow check on loopback open mode for mobile Test connection
        pass
    return {
        "ok": True,
        "remote_access_enabled": ra,
        "hardened": hardened_mode(),
        "auth": auth_status_label(),
        "live_locked": not live_trading_enabled(),
        "session": {
            "mode": "owner_secret_header",
            "header": "X-Owner-Secret",
            "alt": "Authorization: Bearer <secret>",
            "note": "No separate JWT. Reuse the owner secret on each request.",
            "client": (body.client if body else None),
        },
        "prefer_tunnel": True,
    }


@app.get("/config")
def get_config():
    return get_runtime_config().to_dict()


@app.put("/config")
def put_config(body: ConfigUpdate):
    data = body.dict(exclude_unset=False)
    # pydantic v2 compat
    if hasattr(body, "model_dump"):
        data = body.model_dump(exclude_unset=False)
    cfg = get_runtime_config().update(data)
    set_runtime_config(cfg)
    try:
        save_runtime_overlay(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: runtime_config persist failed: {redact_text(str(exc))}")
    # Keep data-source factory in sync when toggle present (default remains free/off)
    if "realtime_sip_enabled" in data:
        set_realtime_sip_enabled(bool(data.get("realtime_sip_enabled")), persist=True)
    return cfg.to_dict()


@app.get("/regime")
def regime():
    state = get_last_regime() or detect_regime(cfg=get_runtime_config())
    return state.to_dict()


@app.get("/strategies")
def strategies_list():
    """List strategy plugins + last router / cycle snapshot."""
    from .strategies import list_strategies, get_last_router_decision, earnings_provider_status
    from .strategies.runner import get_last_cycle
    from .strategies.router import explain_choice
    cfg = get_runtime_config()
    decision = get_last_router_decision()
    cycle = get_last_cycle()
    return {
        "strategies": list_strategies(),
        "strategy_enabled": getattr(cfg, "strategy_enabled", {}) or {},
        "router_mode": getattr(cfg, "router_mode", "auto"),
        "vol_target_annual": getattr(cfg, "vol_target_annual", 0.15),
        "router": decision.to_dict() if decision else cycle.get("router"),
        "last_cycle": {
            "fired": cycle.get("fired") or [],
            "signal_count": cycle.get("signal_count"),
            "by_strategy": cycle.get("by_strategy") or {},
            "at": cycle.get("at"),
            "top": (cycle.get("top") or [])[:10],
            "vol_target": cycle.get("vol_target"),
        },
        "earnings_provider": earnings_provider_status(),
        "explanations": {
            s["id"]: explain_choice(s["id"], decision) for s in list_strategies()
        },
        "crash_mode": (decision.crash_mode if decision and getattr(decision, "crash_mode", None) else None),
        "note": "Paper-first multi-strategy suite. Momentum remains one strategy among several.",
    }


@app.get("/strategies/scoreboard")
def strategies_scoreboard():
    """Walk-forward / rolling paper scoreboard per strategy."""
    from .scoreboard import build_scoreboard
    cfg = get_runtime_config()
    return build_scoreboard(
        cfg,
        recent_days=int(getattr(cfg, "scoreboard_recent_days", 30) or 30),
        oos_days=int(getattr(cfg, "scoreboard_oos_days", 14) or 14),
    )




@app.get("/strategies/packs")
def strategies_packs_list():
    """One-tap strategy packs (StockHero-style templates)."""
    from .strategy_packs import list_packs
    return {
        "packs": list_packs(),
        "note": "Applying a pack updates strategy_enabled + light router hints. Paper-first; does not unlock live.",
    }


@app.post("/strategies/packs/{pack_id}/apply")
def strategies_packs_apply(pack_id: str):
    from .strategy_packs import apply_pack
    result = apply_pack(pack_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error") or "unknown pack")
    return result


@app.get("/strategies/packs/{pack_id}/preview")
def strategies_packs_preview(pack_id: str):
    """Preview toggles/config a pack would change (no persist)."""
    from .strategy_packs import preview_pack
    result = preview_pack(pack_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error") or "unknown pack")
    return result


@app.get("/strategies/scoreboard/export")
def strategies_scoreboard_export(format: str = "json"):
    """Exportable PAPER scoreboard / performance report (JSON or CSV)."""
    from .scoreboard import build_paper_report, paper_report_csv
    report = build_paper_report()
    fmt = (format or "json").lower().strip()
    if fmt == "csv":
        return PlainTextResponse(
            paper_report_csv(report),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=gamma_r_paper_report.csv"},
        )
    return report


@app.get("/paper/report")
def paper_report(format: str = "json"):
    """PAPER performance report: equity curve, win rate, max DD, vs buy-hold, scoreboard."""
    from .scoreboard import build_paper_report, paper_report_csv
    report = build_paper_report()
    if (format or "json").lower().strip() == "csv":
        return PlainTextResponse(
            paper_report_csv(report),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=gamma_r_paper_report.csv"},
        )
    return report



@app.get("/paper/leaderboard")
@app.get("/public/paper-stats")
def paper_leaderboard(limit: int = 20):
    """Public PAPER strategy ranks — watermarked, never invents live returns."""
    from .paper_leaderboard import build_paper_leaderboard
    return build_paper_leaderboard(limit=limit)


@app.get("/paper/leaderboard.html", response_class=HTMLResponse)
def paper_leaderboard_html():
    """Static HTML share card for screenshots (PAPER — not live audited)."""
    from .paper_leaderboard import build_paper_leaderboard, leaderboard_html
    return HTMLResponse(leaderboard_html(build_paper_leaderboard()))

@app.get("/strategies/{strategy_id}")
def strategy_detail(strategy_id: str):
    from .strategies import get_strategy, get_last_router_decision
    from .strategies.router import explain_choice
    s = get_strategy(strategy_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy_id}")
    decision = get_last_router_decision()
    cfg = get_runtime_config()
    enabled = (getattr(cfg, "strategy_enabled", {}) or {}).get(strategy_id, True)
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "is_overlay": bool(s.is_overlay),
        "enabled": bool(enabled),
        "explanation": explain_choice(strategy_id, decision),
        "router": decision.to_dict() if decision else None,
    }


# ---- scan / signals ----

@app.post("/scan")
def scan(force: bool = True):
    """Owner default: force=True bypasses the ~45s in-memory cache for an explicit scan."""
    if force:
        try:
            from . import scanner as scanner_mod
            scanner_mod._CACHE_AT = 0.0
        except Exception:
            pass
    cfg = get_runtime_config()
    wl = load_watchlist()
    signals = run_scan(cfg, watchlist=wl)
    strategies_meta = {}
    try:
        from .strategies.runner import get_last_cycle
        from .strategies import get_last_router_decision
        cycle = get_last_cycle() or {}
        decision = get_last_router_decision()
        strategies_meta = {
            "fired": cycle.get("fired") or [],
            "signal_count": cycle.get("signal_count"),
            "by_strategy": cycle.get("by_strategy") or {},
            "at": cycle.get("at"),
            "router": decision.to_dict() if decision else cycle.get("router"),
            "top": (cycle.get("top") or [])[:6],
        }
    except Exception:
        strategies_meta = {}
    payload = {
        "count": len(signals),
        "signals": signals_to_dicts(signals),
        "watchlist": wl,
        "regime": (get_last_regime().to_dict() if get_last_regime() else None),
        "ensemble_weights": get_ensemble_weights(),
        "news_impact": get_news_impact(),
        "data_source": get_data_source_status(),
        "scan_status": get_scan_status(),
        "strategies_last_cycle": strategies_meta,
        "router_mode": getattr(cfg, "router_mode", "auto"),
        "strategy_enabled": getattr(cfg, "strategy_enabled", {}) or {},
    }
    if getattr(cfg, "use_currency_panel", True):
        try:
            fx = get_currency_quotes()
            payload["currency_top_movers"] = fx.get("top_movers") or []
            payload["currency_session_note"] = fx.get("session_note")
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: currency panel skipped: {exc}")
    if signals:
        _stub_notify({
            "title": "Momentum signals",
            "body": f"{len(signals)} new signal(s)",
            "data": {"tickers": [s.ticker for s in signals[:10]]},
        })
    return payload



@app.post("/scan/quick")
def scan_quick(extra: str = ""):
    """Watchlist-priority quick scan (hot names refresh faster than full universe)."""
    from .scanner import quick_scan
    from .watchlist import load_watchlist
    cfg = get_runtime_config()
    if not getattr(cfg, "quick_scan_enabled", True):
        raise HTTPException(status_code=400, detail="quick_scan_enabled=false in config")
    extras = [t.strip() for t in (extra or "").split(",") if t.strip()]
    result = quick_scan(cfg, watchlist=load_watchlist(), extra_tickers=extras or None)
    try:
        result["data_source"] = get_data_source_status()
    except Exception:
        pass
    result["label"] = "quick_scan"
    return result


@app.get("/scan/status")
def scan_status_ep():
    """Scan cache freshness: age, last scan time, stale warnings, realtime vs delayed."""
    st = get_scan_status()
    try:
        ds = get_data_source_status()
    except Exception:
        ds = {}
    cfg = get_runtime_config()
    return {
        **st,
        "data_source": ds,
        "realtime_sip_enabled": bool(
            getattr(cfg, "realtime_sip_enabled", False)
            or (ds or {}).get("realtime_sip_enabled")
        ),
        "data_label": (
            "REALTIME (Alpaca SIP)" if (ds or {}).get("realtime_sip_enabled") and not (ds or {}).get("fallback_active")
            else "DELAYED (free)"
        ),
        "auto_scan_interval_minutes": getattr(cfg, "auto_scan_interval_minutes", None),
        "scan_cache_ttl_sec": getattr(cfg, "scan_cache_ttl_sec", None),
        "hint": (
            "Enable SIP: Settings → Real-time data (Alpaca SIP) or PUT /data-source "
            "{realtime_sip_enabled:true} with ALPACA keys. Historical training stays free."
        ),
    }



@app.get("/sync/snapshot")
def sync_snapshot():
    """Compact status for 2–5s mobile poll: scan age, crash, paper equity, last audit."""
    from .sync_snapshot import build_sync_snapshot
    return build_sync_snapshot()


@app.get("/events")
@app.get("/stream/status")
async def stream_status(interval: float = 3.0):
    """
    Lightweight SSE push of /sync/snapshot (scan age, crash, paper equity, last audit).
    Not a Level-2 tape — live-*feeling* status only. Prefer GET /sync/snapshot for polling.
    """
    import asyncio
    from .sync_snapshot import build_sync_snapshot

    interval = max(2.0, min(30.0, float(interval or 3.0)))

    async def event_gen():
        # Initial hello
        yield "event: hello\ndata: {\"ok\": true, \"label\": \"GAMMA-R status stream\"}\n\n"
        while True:
            try:
                snap = build_sync_snapshot()
                payload = json.dumps(snap, default=str)
                yield f"event: status\ndata: {payload}\n\n"
            except Exception as exc:  # noqa: BLE001
                err = json.dumps({"ok": False, "error": str(exc)})
                yield f"event: error\ndata: {err}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



@app.get("/sync/ticks")
def sync_ticks(symbols: str = "", limit: int = 40):
    """
    Fast tick poll for watchlist (or ?symbols=AAPL,MSFT).
    Uses SIP/IEX cache when realtime healthy; else delayed last prices clearly labeled.
    Not a Level-2 order book.
    """
    from .sync_ticks import build_ticks
    syms = [s.strip() for s in (symbols or "").split(",") if s.strip()] or None
    return build_ticks(syms, limit=limit)




@app.get("/quotes")
def quotes_ep(symbols: str = "", limit: int = 40):
    """
    NBBO / top-of-book quotes (L2-lite): bid/ask/mid/spread/size.
    Not a Level-2 order book / full depth.
    """
    from .quotes import build_quotes
    syms = [s.strip() for s in (symbols or "").split(",") if s.strip()] or None
    return build_quotes(syms, limit=limit)


@app.get("/events/quotes")
async def events_quotes(symbols: str = "", interval: float = 2.0):
    """
    Dense SSE of top-of-book quotes for subscribed symbols.
    Not L2 depth — bid/ask/mid/spread only.
    """
    import asyncio
    from .quotes import build_quotes

    interval = max(1.0, min(15.0, float(interval or 2.0)))
    syms = [s.strip() for s in (symbols or "").split(",") if s.strip()] or None

    async def event_gen():
        yield 'event: hello\ndata: {"ok": true, "label": "GAMMA-R quotes stream (top-of-book, not L2)"}\n\n'
        while True:
            try:
                payload = json.dumps(build_quotes(syms, limit=40), default=str)
                yield f"event: quotes\ndata: {payload}\n\n"
            except Exception as exc:  # noqa: BLE001
                err = json.dumps({'ok': False, 'error': str(exc)})
                yield f"event: error\ndata: {err}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.websocket("/ws/watchlist")
async def ws_watchlist(websocket: WebSocket):
    """
    Watchlist quote push. Client may send {"subscribe":["AAPL","MSFT"]}.
    Reconnect with backoff on the client. Top-of-book only — not L2.
    """
    import asyncio
    from .quotes import build_quotes
    from .watchlist import load_watchlist

    await websocket.accept()
    subscribed = list(load_watchlist() or [])[:40] or ["SPY", "QQQ", "AAPL"]
    try:
        await websocket.send_json({
            "type": "hello",
            "ok": True,
            "not_level2": True,
            "label": "Watchlist WS — top-of-book, not full depth",
            "subscribed": subscribed,
        })
        backoff = 1.0
        while True:
            # Non-blocking receive for subscribe updates
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.05)
                if isinstance(msg, dict) and msg.get("subscribe"):
                    subscribed = [str(s).strip().upper().replace(".", "-") for s in msg["subscribe"] if s][:40]
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                raise
            except Exception:
                pass
            try:
                q = build_quotes(subscribed, limit=40)
                await websocket.send_json({"type": "quotes", **q})
                backoff = 1.0
            except Exception as exc:  # noqa: BLE001
                await websocket.send_json({"type": "error", "error": str(exc), "not_level2": True})
            await asyncio.sleep(max(1.0, min(5.0, backoff)))
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/edge/status")
@app.get("/edge")
def edge_status_ep():
    """Edge report: active advantages + degraded feeds. Logs AI process breadcrumb."""
    from .edge import build_edge_status_logged
    return build_edge_status_logged(get_runtime_config())


@app.get("/edge/why")
def edge_why_ep():
    from .edge import why_gamma_r_card
    return why_gamma_r_card(get_runtime_config())


@app.get("/edge/gaps")
def edge_gaps_ep():
    from .edge import competitive_gaps
    return competitive_gaps()


@app.get("/edge/feed")
def edge_feed_ep():
    from .edge import feed_health
    return feed_health()


@app.get("/edge/improvements")
def edge_improvements_ep(limit: int = 8):
    from .edge import propose_next_improvements
    return propose_next_improvements(limit=limit)


@app.get("/edge/overnight")
def edge_overnight_ep(limit: int = 8):
    from .edge import overnight_research_summary
    return overnight_research_summary(limit=limit)


@app.get("/edge/critique")
def edge_critique_ep():
    """Last or fresh daily self-critique scorecard."""
    from .edge import load_daily_self_critique
    return load_daily_self_critique()


@app.post("/edge/critique/run")
def edge_critique_run_ep():
    """Force a fresh daily self-critique (paper-first / educational)."""
    from .edge import run_daily_self_critique
    return run_daily_self_critique(persist=True)


@app.post("/edge/overnight/ingest")
def edge_overnight_ingest_ep():
    """Ingest latest web_learning notes into learning summary digest."""
    from .edge import ingest_overnight_into_learning
    return ingest_overnight_into_learning(reason="manual API")


# ---- Desk OS (Bloomberg-inspired UX; not BLP licensed; not L2) ----

@app.post("/desk/command")
def desk_command_ep(body: DeskCommandBody):
    """GO command bar — parse AAPL / NEWS / CHART / EVE / SCAN etc."""
    from .desk import run_desk_command
    return run_desk_command(body.command or "", enrich=bool(body.enrich))


@app.get("/desk/command/help")
def desk_command_help_ep():
    from .desk import command_help
    return command_help()


@app.get("/desk/layout")
def desk_layout_ep(preset: str = "classic"):
    """Multi-panel desk presets: classic, news-heavy, FX+equity, E-ve focus."""
    from .desk import desk_layout
    return desk_layout(preset)


@app.get("/desk/monitor")
def desk_monitor_ep():
    """Monitor / launchpad: crash, heat, alerts, scoreboard cuts, firewall, overnight."""
    from .desk import build_desk_monitor
    return build_desk_monitor()


@app.get("/desk/cross-asset")
def desk_cross_asset_ep():
    """Cross-asset board: equity signals, FX movers, calendar, news tilt."""
    from .desk import build_cross_asset
    return build_cross_asset()


@app.get("/desk/brief")
def desk_brief_ep(symbol: str = "SPY"):
    """E-ve AI news brief from allowlisted web + local news (not Bloomberg news)."""
    from .desk import build_desk_brief
    return build_desk_brief(symbol)


@app.get("/desk/eve-brief")
def desk_eve_brief_ep(symbol: str = ""):
    """Full E-ve desk brief: regime · signals · crash · scoreboard · overnight."""
    from .desk import build_eve_desk_brief
    return build_eve_desk_brief(symbol or None)



@app.get("/alerts")
def alerts_list(limit: int = 30):
    from .alerts import recent_alerts, alert_settings
    out = recent_alerts(limit=limit)
    out["settings"] = alert_settings(get_runtime_config())
    return out


@app.post("/alerts/evaluate")
def alerts_evaluate(force: int = 0):
    from .alerts import evaluate_alerts
    return evaluate_alerts(get_runtime_config(), force=bool(force))



@app.get("/scan/intraday-heat")
@app.get("/intraday/heat")
def intraday_heat(force: int = 0):
    """Intraday momentum/volume anomaly heat — bar-based, not L2."""
    from .intraday_heat import scan_intraday_heat
    return scan_intraday_heat(get_runtime_config(), force=bool(force))

@app.get("/signals")
def signals():
    cached = get_cached_signals()
    strategies_meta = {}
    try:
        from .strategies.runner import get_last_cycle
        strategies_meta = get_last_cycle() or {}
    except Exception:
        pass
    cfg = get_runtime_config()
    return {
        "count": len(cached),
        "signals": signals_to_dicts(cached),
        "scan_status": get_scan_status(),
        "strategies_last_cycle": {
            "fired": strategies_meta.get("fired") or [],
            "by_strategy": strategies_meta.get("by_strategy") or {},
            "at": strategies_meta.get("at"),
            "top": (strategies_meta.get("top") or [])[:6],
        },
        "router_mode": getattr(cfg, "router_mode", "auto"),
    }


@app.get("/signals/{ticker}")
def signal_detail(ticker: str):
    t = ticker.upper().replace(".", "-")
    for s in get_cached_signals():
        if s.ticker == t:
            return s.to_dict()
    raise HTTPException(404, f"No cached signal for {t}; run POST /scan first")


# ---- backtest ----

@app.post("/backtest")
def backtest(body: BacktestRequest = BacktestRequest()):
    cfg = get_runtime_config()
    if body.years:
        cfg = cfg.update({"backtest_years": body.years})
    result = run_backtest(cfg)
    return result.to_dict()


# ---- paper portfolio ----

@app.get("/portfolio")
def portfolio():
    return paper_mod.mark_to_market()


@app.post("/portfolio/orders")
def portfolio_order(body: OrderRequest):
    cfg = get_runtime_config()
    shares = body.shares
    if shares is None:
        # size from signal cache or risk helper
        from .risk import size_position
        entry = body.entry
        if entry is None:
            raise HTTPException(400, "shares or entry required")
        plan = size_position(body.ticker, entry, cfg.starting_equity, cfg)
        shares = plan.shares
        stop = body.stop or plan.stop
        tp = body.take_profit or plan.take_profit
    else:
        stop = body.stop
        tp = body.take_profit
    try:
        ctx = body.context
        if ctx is None:
            try:
                from .feedback import build_entry_context
                # Use cached signal if present for rich tags
                from .scanner import get_cached_signals
                sig = next((s for s in get_cached_signals() if s.ticker == body.ticker.upper().replace(".", "-")), None)
                if sig is not None and body.confidence is not None:
                    try:
                        sig.confidence = body.confidence
                    except Exception:
                        pass
                ctx = build_entry_context(ticker=body.ticker, signal=sig, cfg=cfg)
                if body.confidence is not None:
                    ctx["confidence"] = float(body.confidence)
            except Exception as exc:  # noqa: BLE001
                print(f"Warning: context build on order: {exc}")
                ctx = None
        sid = getattr(body, "strategy_id", None) or (ctx or {}).get("strategy_id")
        fill = paper_mod.place_order(
            ticker=body.ticker,
            shares=int(shares),
            entry=body.entry,
            stop=stop,
            take_profit=tp,
            source=body.source,
            forward_probability=body.forward_probability,
            forward_threshold=(
                body.forward_threshold
                if body.forward_threshold is not None
                else float(cfg.forward_estimate_threshold)
            ),
            ensemble_votes=body.ensemble_votes,
            confidence=body.confidence,
            context=ctx,
            cfg=cfg,
            strategy_id=sid,
            human_approved=bool(getattr(body, "human_approved", False)),
        )
        try:
            if getattr(cfg, "decision_audit_enabled", True):
                from .decision_audit import log_decision_cycle
                from .crash_mode import get_crash_status
                from .strategies import get_last_router_decision
                from .optimization import get_last_regime
                log_decision_cycle(
                    source=body.source or "api",
                    regime=get_last_regime(),
                    crash_mode=get_crash_status(cfg),
                    router_decision=get_last_router_decision(),
                    strategy_id=sid or fill.get("strategy_id"),
                    firewall=fill.get("firewall") or {"allowed": True},
                    order_id=fill.get("id"),
                    ticker=body.ticker,
                    session_gate={"allowed": True},
                )
        except Exception as audit_exc:  # noqa: BLE001
            print(f"Warning: decision audit on order: {audit_exc}")
        return fill
    except Exception as e:
        from .policy_firewall import FirewallDenied
        if isinstance(e, FirewallDenied):
            try:
                if getattr(cfg, "decision_audit_enabled", True):
                    from .decision_audit import log_decision_cycle
                    from .crash_mode import get_crash_status
                    from .strategies import get_last_router_decision
                    from .optimization import get_last_regime
                    log_decision_cycle(
                        source=getattr(body, "source", None) or "api",
                        regime=get_last_regime(),
                        crash_mode=get_crash_status(cfg),
                        router_decision=get_last_router_decision(),
                        strategy_id=getattr(body, "strategy_id", None),
                        firewall=e.result,
                        skip_reason=f"firewall:{e.result.code}:{e.result.reason}",
                        ticker=body.ticker,
                        session_gate={"allowed": True},
                    )
            except Exception:
                pass
            raise HTTPException(403, {
                "error": "firewall_denied",
                "code": e.result.code,
                "reason": e.result.reason,
                "firewall": e.result.to_dict(),
            })
        if isinstance(e, ValueError):
            raise HTTPException(400, str(e))
        raise


@app.post("/portfolio/close/{position_id}")
def portfolio_close(position_id: str, reason: str = "manual"):
    try:
        return paper_mod.close_position(position_id, reason=reason)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/portfolio/performance")
def portfolio_performance():
    return paper_mod.performance()


@app.get("/portfolio/analytics")
def portfolio_analytics_ep():
    """Terminal-lite paper analytics: allocation, P&L, win rate, exposure, drawdown."""
    return paper_mod.build_portfolio_analytics()


@app.post("/portfolio/mode")
def portfolio_mode(body: ModeRequest):
    p = paper_mod.set_mode(body.mode)
    return {
        "mode": p.mode,
        "live_broker_connected": False,
        "note": "Live is a stub — not connected to a broker; paper only for now.",
    }


@app.post("/portfolio/reset")
def portfolio_reset():
    p = paper_mod.reset_portfolio(cfg=get_runtime_config())
    return p.to_dict()


# ---- watchlist ----

@app.get("/watchlist")
def watchlist_get():
    return {"tickers": load_watchlist()}


@app.put("/watchlist")
def watchlist_put(body: WatchlistBody):
    return {"tickers": set_watchlist(body.tickers)}


@app.post("/watchlist")
def watchlist_add(body: WatchlistTicker):
    return {"tickers": add_ticker(body.ticker)}


@app.delete("/watchlist/{ticker}")
def watchlist_delete(ticker: str):
    return {"tickers": remove_ticker(ticker)}


@app.get("/watchlist/columns")
def watchlist_columns_get():
    return load_watchlist_columns()


@app.put("/watchlist/columns")
def watchlist_columns_put(body: WatchlistColumnsBody):
    return save_watchlist_columns(body.columns)



# ---- notify ----

@app.post("/notify/register")
def notify_register(body: NotifyRegister):
    tokens = _load_tokens()
    if not any(t.get("token") == body.token for t in tokens):
        tokens.append({"token": body.token, "platform": body.platform})
        _save_tokens(tokens)
    return {
        "registered": True,
        "count": len(tokens),
        "note": (
            "Tokens stored in data/push_tokens.json. "
            "Wire Expo Push (exp.host/--/api/v2/push/send) or FCM in _stub_notify."
        ),
    }


# ---- learning ----

@app.get("/learning/stats")
def learning_stats_ep():
    return learning_stats()


@app.get("/learning/history")
def learning_history_ep():
    return {"adjustments": load_history()}


@app.post("/learning/run")
def learning_run_ep():
    return run_learning(force=True, reason="manual API")


@app.post("/learning/reset")
def learning_reset_ep(body: LearningReset = LearningReset()):
    return reset_learning(
        wipe_journal=body.wipe_journal,
        wipe_history=body.wipe_history,
        wipe_historical=body.wipe_historical,
    )


@app.get("/learning/baseline")
def learning_baseline():
    return day_one_baseline()


@app.post("/learning/historical-train")
def historical_train(body: HistoricalTrainRequest = HistoricalTrainRequest()):
    years = body.years if body.years in ALLOWED_YEARS else DEFAULT_YEARS
    try:
        result = run_historical_train(years=years, cfg=get_runtime_config(), max_tickers=body.max_tickers)
    except Exception as e:
        raise HTTPException(500, str(e))
    # Re-apply merge order
    apply_learned_on_startup()
    return result


@app.get("/learning/historical-baseline")
def historical_baseline_ep():
    return load_historical_baseline() or {"present": False, "label": "historical baseline"}





@app.get("/session")
def market_session(ticker: str = ""):
    cfg = get_runtime_config()
    from .timezone_util import get_ticker_session, exchange_for_ticker
    if ticker:
        info = get_ticker_session(
            ticker,
            user_tz=cfg.user_timezone,
            allow_after_hours_signals=cfg.allow_after_hours_signals,
            default_exchange=cfg.market_exchange,
        )
        return {
            **info.to_dict(),
            "resolved_exchange": exchange_for_ticker(ticker, default=cfg.market_exchange),
            "use_per_ticker_sessions": bool(getattr(cfg, "use_per_ticker_sessions", True)),
            "session_gate_entries": bool(getattr(cfg, "session_gate_entries", True)),
            "exchanges": list(EXCHANGES.keys()),
        }
    info = get_session(
        exchange=cfg.market_exchange,
        user_tz=cfg.user_timezone,
        allow_after_hours_signals=cfg.allow_after_hours_signals,
    )
    return {
        **info.to_dict(),
        "use_per_ticker_sessions": bool(getattr(cfg, "use_per_ticker_sessions", True)),
        "session_gate_entries": bool(getattr(cfg, "session_gate_entries", True)),
        "exchanges": list(EXCHANGES.keys()),
    }


@app.get("/firewall/status")
def firewall_status():
    from . import policy_firewall as fw
    return fw.status()




@app.get("/markets/coverage")
def markets_coverage_ep():
    """Honest coverage: equities+FX trading; options read-only research vs trading."""
    from .markets_coverage import markets_coverage
    return markets_coverage(get_runtime_config())


class OptionsIdeaBody(BaseModel):
    ticker: str
    thesis: str
    side: Optional[str] = None
    expiry: Optional[str] = None
    strike: Optional[float] = None
    tags: Optional[List[str]] = None


@app.get("/options/ideas")
def options_ideas_list(limit: int = 50):
    """PAPER options idea journal — thesis only, never orders."""
    from .options_research import list_options_ideas
    return list_options_ideas(limit=limit)


@app.post("/options/ideas")
def options_ideas_log(body: OptionsIdeaBody):
    """Log a paper options research thesis. Does NOT broker any options order."""
    from .options_research import log_options_idea
    return log_options_idea(
        body.ticker,
        body.thesis,
        side=body.side,
        expiry=body.expiry,
        strike=body.strike,
        tags=body.tags,
    )




class PaperOptionBody(BaseModel):
    ticker: str
    side: str  # call | put
    contracts: int = 1
    strike: Optional[float] = None
    expiry: Optional[str] = None
    premium: Optional[float] = None
    thesis: str = ""
    human_approved: bool = False


@app.get("/options/paper")
def options_paper_list():
    """List paper options simulator positions. No live options routing."""
    from .paper_options import list_paper_options
    return list_paper_options()


@app.post("/options/paper")
def options_paper_open(body: PaperOptionBody):
    """Open paper long call/put (educational). Firewall applies. Never live options."""
    from .paper_options import open_paper_option
    from .policy_firewall import FirewallDenied
    if not bool(getattr(get_runtime_config(), "paper_options_enabled", True)):
        raise HTTPException(400, detail="paper_options_enabled=false")
    try:
        return open_paper_option(
            body.ticker,
            body.side,
            contracts=body.contracts,
            strike=body.strike,
            expiry=body.expiry,
            premium=body.premium,
            thesis=body.thesis,
            cfg=get_runtime_config(),
            human_approved=bool(body.human_approved),
        )
    except FirewallDenied as e:
        raise HTTPException(
            status_code=403,
            detail={"error": "firewall_denied", "firewall": e.result.to_dict(), "live_options": False},
        )


@app.post("/options/paper/close/{position_id}")
def options_paper_close(position_id: str, reason: str = "manual"):
    from .paper_options import close_paper_option
    return close_paper_option(position_id, reason=reason)


@app.get("/options/{ticker}")
def options_research_ep(ticker: str, force: int = 0):
    """
    Read-only options: nearest expiries, ATM IV, put/call volume (cached).
    No options order routing. Honest nulls when data missing.
    """
    from .options_research import options_summary
    return options_summary(ticker, cfg=get_runtime_config(), force=bool(force))


@app.get("/options/{ticker}/chain")
def options_chain_ep(ticker: str, expiry: str = "", force: int = 0, max_rows: int = 40):
    """Options chain rows with strike/bid/ask/IV + greeks (BS approx if needed). Paper-wireable."""
    from .options_research import options_chain
    return options_chain(
        ticker,
        expiry=expiry or None,
        cfg=get_runtime_config(),
        force=bool(force),
        max_rows=max_rows,
    )


# ---- Pro terminal: bars / tape / ladder / custom scan / calendar / pro orders ----


@app.get("/bars/{symbol}")
def bars_ep(symbol: str, interval: str = "1d", limit: int = 120):
    """OHLCV bars for candle charts. interval=1d|1h|15m|5m."""
    from .bars import get_bars
    return get_bars(symbol, interval=interval, limit=limit)


@app.get("/tape/{symbol}")
@app.get("/trades/{symbol}")
def tape_ep(symbol: str, limit: int = 40):
    """Tape lite — recent prints if Alpaca keys; else honest empty."""
    from .tape import get_tape
    return get_tape(symbol, limit=limit)


@app.get("/ladder/{symbol}")
def ladder_ep(symbol: str, levels: int = 8):
    """NBBO-driven top-of-book ladder — not full exchange depth."""
    from .ladder import build_ladder
    return build_ladder(symbol, levels=levels)


@app.post("/scan/custom")
def scan_custom_ep(body: CustomScanBody = CustomScanBody()):
    """Pro scanner builder — filter signals by volume/%chg/RS/news/strategy/region/price."""
    from .scan_custom import run_custom_scan
    filters = body.model_dump() if hasattr(body, "model_dump") else body.dict()
    refresh = bool(filters.pop("refresh", False))
    return run_custom_scan(filters, refresh=refresh, cfg=get_runtime_config())


@app.get("/calendar/economic")
def calendar_economic_ep(days: int = 21, refresh: int = 0, limit: int = 40):
    """Economic calendar rail (curated/allowlisted)."""
    from .calendar_econ import get_economic_calendar
    return get_economic_calendar(days=days, refresh=bool(refresh), limit=limit)


@app.post("/portfolio/orders/pro")
def portfolio_pro_order(body: ProOrderBody):
    """Paper pro order types: stop, take-profit, bracket, OCO. Firewall enforced. Never live."""
    from .paper_pro_orders import place_pro_order
    from .policy_firewall import FirewallDenied
    try:
        return place_pro_order(
            ticker=body.ticker,
            shares=int(body.shares),
            order_type=body.order_type,
            entry=body.entry,
            stop=body.stop,
            take_profit=body.take_profit,
            trigger_price=body.trigger_price,
            limit_price=body.limit_price,
            source=body.source,
            strategy_id=body.strategy_id,
            human_approved=bool(body.human_approved),
            cfg=get_runtime_config(),
        )
    except FirewallDenied as e:
        raise HTTPException(
            status_code=403,
            detail={"error": "firewall_denied", "firewall": e.result.to_dict(), "live": False},
        )


@app.get("/portfolio/orders/working")
def portfolio_working_orders():
    from .paper_pro_orders import list_working_orders
    return list_working_orders()


@app.post("/portfolio/orders/working/manage")
def portfolio_working_manage():
    from .paper_pro_orders import manage_working_orders
    return manage_working_orders(cfg=get_runtime_config())


@app.post("/portfolio/orders/working/{order_id}/cancel")
def portfolio_working_cancel(order_id: str):
    from .paper_pro_orders import cancel_working_order
    return cancel_working_order(order_id)


@app.get("/layout/pro")
def layout_pro_ep():
    """Pro layout denser Dashboard hints + keyboard shortcuts (web) / long-press (mobile)."""
    return {
        "ok": True,
        "pro_layout": True,
        "density": "compact",
        "sections": [
            "signals", "quotes_nbbo", "ladder", "tape", "chart",
            "scanner_builder", "calendar", "options_chain", "paper_pro_orders",
        ],
        "hotkeys_web": [
            {"key": "s", "action": "focus_scanner"},
            {"key": "c", "action": "toggle_chart_interval"},
            {"key": "t", "action": "toggle_tape"},
            {"key": "l", "action": "toggle_ladder"},
            {"key": "b", "action": "paper_bracket"},
            {"key": "/", "action": "copilot_focus"},
            {"key": "?", "action": "show_hotkeys"},
        ],
        "mobile": {
            "long_press": "paper_bracket on signal row / detail",
            "note": "Best-effort density; native mobile has no global hotkeys.",
        },
        "caption": "Pro layout — denser Dashboard; still not Thinkorswim L2.",
        "not_level2": True,
    }




@app.get("/crash-mode")
@app.get("/crash_mode")
def crash_mode_status(refresh: int = 0):
    """Crash / regime-shock mode status for Dashboard / Settings."""
    from .crash_mode import get_crash_status, detect_crash
    cfg = get_runtime_config()
    if refresh:
        st = detect_crash(cfg, force_check=True)
    else:
        st = get_crash_status(cfg, refresh=False)
    return st.to_dict()


@app.post("/crash-mode/clear")
@app.post("/crash_mode/clear")
def crash_mode_clear():
    from .crash_mode import clear_crash_mode
    return clear_crash_mode(reason="manual API clear")



@app.get("/audit/decisions")
def audit_decisions(limit: int = 50):
    """Recent auto/copilot decision audit trail (append-only JSONL)."""
    from .decision_audit import read_decisions, AUDIT_PATH
    rows = read_decisions(limit=limit)
    return {
        "count": len(rows),
        "path": str(AUDIT_PATH),
        "decisions": rows,
        "note": "Append-only decision audit; paper-first.",
    }


# ---- news sentiment ----

@app.get("/news")
def news_feed(limit: int = 50, eod: int = 0):
    items = collect_news()
    payload = {
        "count": len(items),
        "items": enrich_news_display(items[:limit]),
        "impact": sector_sentiment_impact(items),
        "note": "RSS default; optional FINNHUB_API_KEY / NEWSAPI_KEY. VADER sentiment.",
    }
    if eod:
        payload["eod"] = build_eod_digest()
    return payload


@app.get("/news/impact")
def news_impact():
    cached = get_news_impact()
    if cached:
        return {"impact": cached}
    items = collect_news()
    return {"impact": sector_sentiment_impact(items)}


@app.get("/news/eod")
def news_eod():
    """End-of-day digest: top headlines, sector/ticker impacts, bullish/bearish tilt."""
    return build_eod_digest()


@app.get("/news/{ticker}")
def news_ticker(ticker: str):
    items = collect_news(tickers=[ticker])
    agg = aggregate_ticker_news(items, ticker, cfg=get_runtime_config())
    return agg.to_dict()


# ---- currency / FX (informational) ----

@app.get("/currency")
@app.get("/fx")
def currency_quotes():
    """Major FX pairs via yfinance — informational context for equities."""
    cfg = get_runtime_config()
    if not getattr(cfg, "use_currency_panel", True):
        return {
            "pairs": [],
            "top_movers": [],
            "enabled": False,
            "note": "Currency panel disabled (use_currency_panel=false).",
        }
    data = get_currency_quotes()
    data["enabled"] = True
    return data


@app.get("/currency/{pair}")
@app.get("/fx/{pair}")
def currency_pair(pair: str):
    cfg = get_runtime_config()
    if not getattr(cfg, "use_currency_panel", True):
        raise HTTPException(400, "Currency panel disabled (use_currency_panel=false)")
    row = get_currency_pair(pair)
    if not row:
        raise HTTPException(404, f"Unknown FX pair: {pair}")
    return row


# ---- market data source (free default; SIP optional live-only) ----

class DataSourceUpdate(BaseModel):
    realtime_sip_enabled: bool = False


@app.get("/data-source/status")
def data_source_status():
    """Active live source, fallback flag, SIP connection details."""
    st = get_data_source_status()
    # Mirror into runtime config for mobile Settings
    cfg = get_runtime_config()
    st["config_realtime_sip_enabled"] = bool(getattr(cfg, "realtime_sip_enabled", False))
    return st


@app.put("/data-source")
@app.post("/data-source")
def data_source_set(body: DataSourceUpdate):
    """
    Toggle Alpaca SIP for live scans / forward-estimate.
    Off by default. Historical training/backtests always use free yfinance.
    Requires Alpaca API keys + Algo Trader Plus (~$99/mo).
    """
    st = set_realtime_sip_enabled(bool(body.realtime_sip_enabled), persist=True)
    # Persist on strategy config too
    cfg = get_runtime_config().update({"realtime_sip_enabled": bool(body.realtime_sip_enabled)})
    set_runtime_config(cfg)
    return st


@app.get("/data-source/events")
def data_source_events_ep(limit: int = 50):
    return {"events": data_source_events(limit=limit)}


@app.post("/data-source/reset-fallback")
def data_source_reset_fallback():
    """Clear SIP→free fallback and retry SIP on next live fetch (if still enabled)."""
    return reset_fallback()


# ---- broker (DISABLED by default) ----

@app.get("/broker/status")
@app.get("/brokers/status")
def broker_status():
    """Unified broker connect card: paper sim / alpaca paper / alpaca live(locked) / ibkr(planned)."""
    from .brokers.status_card import unified_brokers_status
    card = unified_brokers_status()
    # Backward-compatible flat fields
    card["live_trading_enabled"] = card.get("live_trading_enabled")
    card["default"] = "paper"
    card["kill_switch"] = "/broker/kill"
    card["note"] = (
        "Live brokerage is OFF by default. Paper mode remains active. "
        "Set LIVE_TRADING_ENABLED=1 and provide ALPACA_API_KEY / ALPACA_API_SECRET "
        "to activate. Keys must never be committed; use env or secure storage."
    )
    return card


@app.post("/brokers/alpaca/test")
@app.post("/broker/alpaca/test")
def broker_alpaca_test(paper: int = 1):
    """Test Alpaca connectivity (paper endpoint by default). No orders."""
    from .brokers.status_card import test_alpaca_connection
    return test_alpaca_connection(paper=bool(paper))


@app.get("/broker/balance")
def broker_balance():
    if not live_trading_enabled():
        raise HTTPException(403, "Live trading disabled. Paper mode only.")
    try:
        b = get_broker()
        return b.get_balance().to_dict()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/broker/positions")
def broker_positions():
    if not live_trading_enabled():
        raise HTTPException(403, "Live trading disabled. Paper mode only.")
    try:
        b = get_broker()
        return {"positions": [p.to_dict() for p in b.get_positions()]}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/broker/orders")
def broker_order(body: BrokerOrderRequest):
    """Route a live order through the adapter. Same risk sizing should be applied by caller."""
    if not live_trading_enabled():
        raise HTTPException(
            403,
            "Live trading DISABLED. Use POST /portfolio/orders for paper trades.",
        )
    cfg = get_runtime_config()
    from . import policy_firewall as fw
    from .policy_firewall import FirewallDenied
    # Enforce max position / risk caps server-side + hard firewall
    try:
        bal = get_broker().get_balance()
        max_dollars = bal.equity * cfg.max_position_pct
        # Price hint for notional — best-effort
        px = float(getattr(body, "limit_price", None) or 0) or 1.0
        try:
            from .paper import _latest_price
            got = _latest_price(body.ticker)
            if got:
                px = float(got)
        except Exception:
            pass
        fw_res = fw.assert_order_allowed(
            ticker=body.ticker,
            shares=float(body.shares),
            price=px,
            side=body.side or "buy",
            mode="live",
            source="broker_api",
            strategy_id=getattr(body, "strategy_id", None),
            equity=float(bal.equity),
            cfg=cfg,
            human_approved=bool(getattr(body, "human_approved", False)),
        )
        order = get_broker().place_market_order(body.ticker, body.shares, side=body.side)
        return {
            "order": order.to_dict(),
            "risk_note": f"max_position_pct={cfg.max_position_pct}, stop_loss_pct={cfg.stop_loss_pct}",
            "max_notional_hint": max_dollars,
            "firewall": fw_res.to_dict(),
        }
    except FirewallDenied as e:
        raise HTTPException(403, {
            "error": "firewall_denied",
            "code": e.result.code,
            "reason": e.result.reason,
            "firewall": e.result.to_dict(),
        })
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/broker/kill")
def broker_kill():
    """KILL SWITCH — cancel all open orders and close all positions immediately."""
    if not live_trading_enabled():
        raise HTTPException(403, "Live trading disabled — nothing to kill on broker.")
    try:
        return kill_switch()
    except Exception as e:
        raise HTTPException(400, str(e))



# ---- owner conveniences (private single-user) ----

_OWNER_FILES = {
    "watchlist": "watchlist.json",
    "config": "learned_config.json",
    "runtime_config": "runtime_config.json",
    "journal": "trade_journal.json",
    "paper": "paper_portfolio.json",
    "learning_history": "learning_history.json",
    "historical_baseline": "historical_baseline.json",
    "external_trades": "external_trades.jsonl",
    "external_import_meta": "external_import_meta.json",
}


class OwnerExportBody(BaseModel):
    name: str
    content: Any = None


@app.get("/owner/status")
def owner_status():
    """Quick snapshot for the owner dashboard / co-pilot."""
    files = {}
    for key, fname in _OWNER_FILES.items():
        path = DATA_DIR / fname
        files[key] = {
            "path": str(path),
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
        }
    auto = None
    try:
        from .auto_loops import get_status as _auto_status
        auto = _auto_status()
    except Exception as exc:  # noqa: BLE001
        auto = {"error": str(exc)}
    return {
        "owner_mode": _owner_mode(),
        "auth": auth_status_label(),
        "hardened": hardened_mode(),
        "data_dir": str(DATA_DIR),
        "files": files,
        "cached_signals": len(get_cached_signals()),
        "scan_status": get_scan_status(),
        "watchlist": load_watchlist(),
        "live_trading_enabled": live_trading_enabled(),
        "auto": auto,
        "note": "Private install. Use X-Owner-Secret / Bearer when OWNER_SHARED_SECRET is set. Never expose 0.0.0.0 publicly without TLS + secret.",
    }


@app.get("/owner/files")
def owner_list_files():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for path in sorted(DATA_DIR.glob("*")):
        if path.is_file() and not path.name.startswith("."):
            out.append({"name": path.name, "bytes": path.stat().st_size})
    return {"data_dir": str(DATA_DIR), "files": out}


@app.get("/owner/export/{name}")
def owner_export(name: str):
    """Export a known owner file (watchlist, journal, paper, config, …)."""
    key = name.strip().lower()
    fname = _OWNER_FILES.get(key, key if key.endswith(".json") else None)
    if not fname or "/" in fname or ".." in fname:
        raise HTTPException(400, f"Unknown export name. Allowed: {list(_OWNER_FILES)}")
    path = DATA_DIR / fname
    if not path.exists():
        raise HTTPException(404, f"{fname} not found under data/")
    try:
        content = json.loads(path.read_text())
        return {"name": key, "file": fname, "content": redact_obj(content)}
    except Exception as e:
        raise HTTPException(400, f"Could not read {fname}: {redact_text(str(e))}")


@app.put("/owner/import/{name}")
@app.post("/owner/import/{name}")
def owner_import(name: str, body: OwnerExportBody):
    """Import/overwrite a known owner JSON file under data/ (private convenience)."""
    key = name.strip().lower()
    fname = _OWNER_FILES.get(key)
    if not fname:
        raise HTTPException(400, f"Unknown import name. Allowed: {list(_OWNER_FILES)}")
    if body.content is None:
        raise HTTPException(400, "content required")
    # Never accept secrets blobs into any owner data file
    blob = json.dumps(body.content)
    low = blob.lower()
    if any(
        s in low
        for s in (
            "api_secret",
            "api_key",
            "private_key",
            "password",
            "owner_shared_secret",
            "openai_api_key",
            "sk-",
            "alpaca_api",
            "bearer ",
        )
    ):
        raise HTTPException(400, "Refusing to write secret-like content into data files")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / fname
    path.write_text(json.dumps(body.content, indent=2, default=str))
    # Hot-reload a few
    if key == "watchlist":
        try:
            tickers = body.content if isinstance(body.content, list) else body.content.get("tickers", [])
            set_watchlist([str(x).upper() for x in tickers])
        except Exception:
            pass
    return {"ok": True, "file": fname, "bytes": path.stat().st_size}



@app.post("/copilot")
@app.post("/copilot/chat")
@app.post("/chat")
def copilot_chat(body: CopilotRequest):
    """E-ve assistant: local brain + optional OpenAI tool loop. Educational only."""
    from .copilot import chat as copilot_chat_fn

    history = [{"role": m.role, "content": m.content} for m in body.history]
    try:
        return copilot_chat_fn(body.message, history)
    except Exception as e:
        raise HTTPException(500, redact_text(str(e)))



# ---- auto loops (unattended learn + paper trade) ----

class AutoUpdate(BaseModel):
    auto_learn_enabled: Optional[bool] = None
    auto_trade_enabled: Optional[bool] = None
    auto_learn_interval_minutes: Optional[int] = None
    auto_trade_interval_minutes: Optional[int] = None
    auto_exit_interval_seconds: Optional[int] = None
    max_concurrent_positions: Optional[int] = None
    auto_trade_max_new_per_cycle: Optional[int] = None
    auto_trade_require_forward_pass: Optional[bool] = None
    min_confidence: Optional[float] = None
    max_position_pct: Optional[float] = None
    maintenance_windows_enabled: Optional[bool] = None
    maintenance_open_buffer_minutes: Optional[int] = None
    maintenance_close_buffer_minutes: Optional[int] = None
    maintenance_allow_exits: Optional[bool] = None


@app.get("/auto/status")
def auto_status_ep():
    from .auto_loops import get_status
    return get_status()


@app.put("/auto")
@app.post("/auto")
def auto_update_ep(body: AutoUpdate):
    data = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else {
        k: v for k, v in body.dict().items() if v is not None
    }
    cfg = get_runtime_config().update(data)
    set_runtime_config(cfg)
    save_runtime_overlay(cfg)
    from .auto_loops import get_status
    return {"config": {k: cfg.to_dict().get(k) for k in data}, "status": get_status()}


@app.post("/auto/trade/run")
def auto_trade_run_ep():
    """Manual one-shot: scan → decide → paper act (same as background cycle)."""
    from .auto_loops import run_trade_once
    return run_trade_once(force_scan=True)


@app.post("/auto/web-learn/run")
def auto_web_learn_run():
    from .auto_loops import run_web_learn_once
    return run_web_learn_once(reason="manual API")


@app.post("/auto/learn/run")
def auto_learn_run_ep():
    from .auto_loops import run_learn_once
    return run_learn_once(reason="manual API /auto/learn/run")


@app.post("/auto/exits/run")
def auto_exits_run_ep():
    from .auto_loops import run_exits_once
    return run_exits_once()


# ---- circuit breaker (data health) ----

@app.get("/circuit-breaker")
@app.get("/auto/circuit-breaker")
def circuit_breaker_status_ep():
    from . import circuit_breaker as cb
    return cb.status()


class CircuitFeedback(BaseModel):
    note: str = ""


@app.post("/circuit-breaker/false-trip")
def circuit_false_trip(body: CircuitFeedback = CircuitFeedback()):
    from . import circuit_breaker as cb
    return cb.mark_false_trip(body.note or "owner marked false trip")


@app.post("/circuit-breaker/missed-bad")
def circuit_missed_bad(body: CircuitFeedback = CircuitFeedback()):
    from . import circuit_breaker as cb
    return cb.mark_missed_bad(body.note or "owner marked missed bad data")


@app.post("/circuit-breaker/resume")
def circuit_resume(body: CircuitFeedback = CircuitFeedback()):
    from . import circuit_breaker as cb
    return cb.force_resume(body.note or "manual resume")


@app.post("/circuit-breaker/halt")
def circuit_halt(body: CircuitFeedback = CircuitFeedback()):
    from . import circuit_breaker as cb
    return cb.force_halt(body.note or "manual halt")


@app.post("/circuit-breaker/reset-thresholds")
def circuit_reset_thr():
    from . import circuit_breaker as cb
    return cb.reset_thresholds_to_seed()


# ---- session replay (yesterday / last sessions vs learned) ----

class ReplayRequest(BaseModel):
    days: int = 5
    max_tickers: int = 40


@app.post("/learning/replay")
@app.post("/backtest/replay")
def learning_replay_ep(body: ReplayRequest = ReplayRequest()):
    try:
        return run_session_replay(days=body.days, max_tickers=body.max_tickers)
    except Exception as e:
        raise HTTPException(500, str(e))




# ---- structured feedback (like/dislike + notes) ----

class FeedbackBody(BaseModel):
    rating: Optional[str] = None  # like | dislike | null
    note: Optional[str] = None


class TradeImportBody(BaseModel):
    format: str = "csv"  # csv | json
    content: str = ""
    dry_run: bool = False


class AlpacaImportBody(BaseModel):
    dry_run: bool = False
    limit: int = 100


@app.post("/portfolio/feedback/{position_id}")
def portfolio_feedback(position_id: str, body: FeedbackBody):
    try:
        return paper_mod.set_position_feedback(
            position_id, rating=body.rating, note=body.note,
        )
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/learning/feedback/{entry_id}")
def learning_feedback(entry_id: str, body: FeedbackBody):
    from .learning import set_journal_feedback
    try:
        return set_journal_feedback(entry_id, rating=body.rating, note=body.note)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))




# ---- external / brokerage trade import (learn only — no live trading) ----

@app.post("/trades/import")
def trades_import(body: TradeImportBody):
    """Import CSV/JSON brokerage fills. Journals for learning; never auto-lives."""
    try:
        from .external_trades import import_from_content
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(501, f"external trades module unavailable: {exc}")
    content = body.content or ""
    if not content.strip():
        raise HTTPException(400, "content required")
    result = import_from_content(
        format=body.format or "csv",
        content=content,
        dry_run=bool(body.dry_run),
    )
    if not result.get("ok", True) and result.get("error"):
        raise HTTPException(400, result.get("error"))
    return result


@app.post("/trades/import/alpaca")
def trades_import_alpaca(body: AlpacaImportBody = AlpacaImportBody()):
    """Optional: pull Alpaca FILL history when ALPACA_* keys exist. Import only."""
    try:
        from .external_trades import alpaca_credentials_present, import_from_alpaca
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(501, f"external trades module unavailable: {exc}")
    if not alpaca_credentials_present():
        raise HTTPException(
            400,
            "ALPACA_API_KEY and ALPACA_API_SECRET required for Alpaca import "
            "(paper or live account history — import does not place orders).",
        )
    limit = max(1, min(500, int(body.limit or 100)))
    result = import_from_alpaca(dry_run=bool(body.dry_run), limit=limit)
    if not result.get("ok", True) and result.get("error"):
        raise HTTPException(400, result.get("error"))
    return result


@app.get("/trades/external")
def trades_external(limit: int = 50):
    """List stored external fills (newest last; truncated to limit)."""
    try:
        from .external_trades import load_external_trades, load_import_meta
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(501, f"external trades module unavailable: {exc}")
    lim = max(1, min(500, int(limit or 50)))
    rows = load_external_trades(limit=lim)
    return {
        "count": len(rows),
        "trades": rows,
        "last_import": load_import_meta().get("last_import"),
        "live_trading": False,
    }


@app.get("/trades/learning-stats")
def trades_learning_stats():
    """Paper vs external vs combined learning metrics (paper equity separate)."""
    try:
        from .external_trades import learning_stats_by_origin
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(501, f"external trades module unavailable: {exc}")
    return learning_stats_by_origin()


def create_app() -> FastAPI:
    return app

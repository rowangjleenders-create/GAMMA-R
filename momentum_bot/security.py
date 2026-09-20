"""
Practical private-trading-OS hardening for GAMMA-R (honest: not SOC2 / bank-grade).

Env knobs:
  OWNER_SHARED_SECRET / API_SHARED_SECRET — shared owner gate
  REQUIRE_API_SECRET=1 / GAMMA_R_HARDENED=1 — force secret even on loopback
  GAMMA_R_BIND_HOST — set by `serve` so hardened_mode matches CLI bind
  CORS_ALLOW_ORIGINS — comma-separated allowlist (never "*")
  API_RATE_LIMIT / API_RATE_WINDOW_SEC — mutating + /copilot limits

Secret file: data/.owner_secret (0600), auto-created on hardened serve if unset.
Auth: X-Owner-Secret or Authorization: Bearer only (query owner_secret= rejected).
"""

from __future__ import annotations

import hmac
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OWNER_SECRET_PATH = DATA_DIR / ".owner_secret"

_DEFAULT_CORS_ORIGINS = (
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "http://localhost:19000",
    "http://127.0.0.1:19000",
    "http://localhost:19006",
    "http://127.0.0.1:19006",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "exp://127.0.0.1:8081",
    "exp://localhost:8081",
)

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"})

_SECRET_KEY_RE = re.compile(
    r"(secret|api[_-]?key|apikey|password|passwd|token|private[_-]?key|"
    r"authorization|bearer|openai|alpaca|owner_shared)",
    re.I,
)
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}"
    r"|Bearer\s+\S+"
    r"|(?:ALPACA|OPENAI|OWNER|API)_[A-Z0-9_]*=\S+"
    r"|(?:api[_-]?secret|api[_-]?key|owner_secret)=[^\s&\"']+)",
    re.I,
)

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})

_secret_cache: Optional[str] = None
_secret_lock = threading.Lock()
_logged_secret_path = False


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def bind_host(host: Optional[str] = None) -> str:
    return (
        (host or "").strip()
        or os.environ.get("GAMMA_R_BIND_HOST", "").strip()
        or os.environ.get("API_BIND_HOST", "").strip()
        or "127.0.0.1"
    )


def is_loopback_host(host: Optional[str] = None) -> bool:
    h = bind_host(host).lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    return h in _LOOPBACK


def hardened_mode(host: Optional[str] = None) -> bool:
    """True when secret must be enforced for non-exempt routes."""
    if _truthy("REQUIRE_API_SECRET") or _truthy("GAMMA_R_HARDENED"):
        return True
    return not is_loopback_host(host)


def cors_allow_origins() -> List[str]:
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]
    else:
        origins = list(_DEFAULT_CORS_ORIGINS)
    return origins or list(_DEFAULT_CORS_ORIGINS)


def _env_secret() -> str:
    return (
        os.environ.get("OWNER_SHARED_SECRET")
        or os.environ.get("API_SHARED_SECRET")
        or ""
    ).strip()


def _read_file_secret() -> str:
    try:
        if OWNER_SECRET_PATH.is_file():
            return OWNER_SECRET_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def _write_file_secret(value: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OWNER_SECRET_PATH.write_text(value + "\n", encoding="utf-8")
    try:
        os.chmod(OWNER_SECRET_PATH, 0o600)
    except OSError:
        pass


def clear_secret_cache() -> None:
    global _secret_cache
    with _secret_lock:
        _secret_cache = None


def shared_secret(*, auto_create: bool = False) -> str:
    """
    Resolve owner secret: env → data/.owner_secret → optional auto-create.
    Never logs the value; may log the file path once.
    """
    global _secret_cache, _logged_secret_path
    with _secret_lock:
        if _secret_cache is not None:
            return _secret_cache

        secret = _env_secret()
        source = "env" if secret else ""
        if not secret:
            secret = _read_file_secret()
            source = "file" if secret else ""

        if not secret and auto_create:
            secret = secrets.token_urlsafe(32)
            _write_file_secret(secret)
            source = "auto"
            if not _logged_secret_path:
                print(
                    f"[security] Auto-created owner secret at {OWNER_SECRET_PATH} (0600). "
                    "Send via X-Owner-Secret or Authorization: Bearer. "
                    "Or set OWNER_SHARED_SECRET / API_SHARED_SECRET."
                )
                _logged_secret_path = True
        elif secret and source == "file" and not _logged_secret_path:
            print(f"[security] Using owner secret from {OWNER_SECRET_PATH}")
            _logged_secret_path = True

        _secret_cache = secret
        return secret


def ensure_owner_secret_for_serve(host: Optional[str] = None) -> str:
    """
    Called from `serve` before uvicorn starts.
    Hardened bind → require secret; auto-provision data/.owner_secret if missing.
    Raises SystemExit if hardened and secret cannot be obtained.
    """
    os.environ["GAMMA_R_BIND_HOST"] = bind_host(host)
    clear_secret_cache()
    hard = hardened_mode(host)
    secret = shared_secret(auto_create=hard)
    if hard and not secret:
        raise SystemExit(
            "[security] Hardened mode requires OWNER_SHARED_SECRET / API_SHARED_SECRET "
            f"or a writable {OWNER_SECRET_PATH}"
        )
    if hard:
        print(
            f"[security] Hardened mode ON (bind={bind_host(host)!r}). "
            "All non-/health routes require X-Owner-Secret or Bearer. /docs locked."
        )
    elif secret:
        print("[security] Owner secret configured — auth enforced (except /health).")
    else:
        print("[security] Open loopback mode (no secret). Prefer localhost / Tailscale.")
    return secret


def auth_status_label() -> str:
    if shared_secret(auto_create=False):
        return "shared_secret"
    if hardened_mode():
        return "required_missing"
    return "open"


# Public PAPER leaderboard / share card — sanitized metrics only (no secrets, no live claims)
_PUBLIC_PAPER_PATHS = {
    "/paper/leaderboard",
    "/public/paper-stats",
    "/paper/leaderboard.html",
}


def auth_exempt_paths(*, protect_docs: bool = False) -> Set[str]:
    """Paths that skip owner-secret auth. /health + public PAPER leaderboard always exempt."""
    exempt = {"/health"} | set(_PUBLIC_PAPER_PATHS)
    if not protect_docs:
        exempt |= set(_DOCS_PATHS)
    return exempt


def extract_provided_secret(headers: Any, query_params: Any = None) -> Tuple[Optional[str], bool]:
    """
    Returns (presented_secret_or_None, query_secret_present).
    Query owner_secret= is never accepted as auth — caller should 400 when True.
    """
    query_present = False
    try:
        if query_params is not None and "owner_secret" in query_params:
            query_present = True
    except Exception:
        pass

    got: Optional[str] = None
    try:
        raw = headers.get("x-owner-secret") or headers.get("X-Owner-Secret")
        if raw:
            got = str(raw).strip()
    except Exception:
        pass

    if not got:
        try:
            auth = headers.get("authorization") or headers.get("Authorization")
        except Exception:
            auth = None
        if auth:
            s = str(auth).strip()
            if s.lower().startswith("bearer "):
                got = s[7:].strip() or None

    return got, query_present


def secrets_equal(presented: Optional[str], expected: str) -> bool:
    if not presented or not expected:
        return False
    a = presented.encode("utf-8")
    b = expected.encode("utf-8")
    if len(a) != len(b):
        # Equal-length dummy compare to reduce trivial timing signal
        hmac.compare_digest(a, a)
        return False
    return hmac.compare_digest(a, b)


def client_ip(request: Any) -> str:
    headers = getattr(request, "headers", None) or {}
    try:
        xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
        if xff:
            return str(xff).split(",")[0].strip() or "unknown"
    except Exception:
        pass
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return (host or "unknown").strip() or "unknown"


def should_rate_limit(method: str, path: str) -> bool:
    m = (method or "").upper()
    p = (path or "").rstrip("/") or "/"
    if p in ("/copilot", "/copilot/chat", "/chat") or p.startswith("/copilot"):
        return True
    return m in _MUTATING


class InMemoryRateLimiter:
    """Sliding-window per-key limiter (typically ip:METHOD)."""

    def __init__(
        self,
        limit: Optional[int] = None,
        window_sec: Optional[float] = None,
    ) -> None:
        self.limit = max(
            1, int(limit if limit is not None else os.environ.get("API_RATE_LIMIT", "60"))
        )
        self.window = float(
            window_sec
            if window_sec is not None
            else os.environ.get("API_RATE_WINDOW_SEC", "60")
        )
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            cutoff = now - self.window
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def redact_text(s: str) -> str:
    if not s:
        return s
    return _SECRET_VALUE_RE.sub("***", s)


def redact_obj(obj: Any, depth: int = 0, *, list_cap: int = 250) -> Any:
    if depth > 14:
        return "***"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _SECRET_KEY_RE.search(str(k)):
                out[k] = "***"
            else:
                out[k] = redact_obj(v, depth + 1, list_cap=list_cap)
        return out
    if isinstance(obj, list):
        return [redact_obj(x, depth + 1, list_cap=list_cap) for x in obj[:list_cap]]
    if isinstance(obj, tuple):
        return tuple(redact_obj(x, depth + 1, list_cap=list_cap) for x in obj[:list_cap])
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def scrub_url(url: str) -> str:
    """Strip secret-bearing query params before logging."""
    try:
        parts = urlsplit(url)
        q = [
            (
                k,
                "***"
                if k.lower()
                in ("owner_secret", "token", "api_key", "api_secret", "secret", "password")
                else v,
            )
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment)
        )
    except Exception:
        return redact_text(url or "")


def security_headers() -> Dict[str, str]:
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    }


def live_unlock_allowed() -> Tuple[bool, str]:
    """
    Extra fail-closed gate: LIVE_TRADING_ENABLED alone is not enough when hardened —
    require an owner secret AND firewall enabled.
    """
    live = os.environ.get("LIVE_TRADING_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not live:
        return False, "LIVE_TRADING_ENABLED!=1"
    if hardened_mode() and not shared_secret(auto_create=False):
        return False, "hardened mode requires owner secret before live"
    try:
        from .config import get_runtime_config

        cfg = get_runtime_config()
        if not bool(getattr(cfg, "firewall_enabled", True)):
            return False, "firewall_enabled must be true for live"
    except Exception:
        return False, "firewall status unavailable"
    return True, "ok"


# Aliases for call sites / smoke tests
RateLimiter = InMemoryRateLimiter
ensure_owner_secret = ensure_owner_secret_for_serve
is_hardened = hardened_mode
# Back-compat names used in earlier patches
cors_allow_origins_alias = cors_allow_origins

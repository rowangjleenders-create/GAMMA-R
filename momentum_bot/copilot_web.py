"""
Allowlisted web access for GAMMA-R's E-ve assistant (educational only).

NOT open browsing: hosts must match copilot_web_allowlist (or defaults).
Blocks file://, localhost, private IPs, link shorteners, and non-allowlisted domains.
Fetches are size/time capped, credential-free, HTML→text only, rate-limited.
Useful extracts are distilled into data/web_learning.jsonl for offline recall.
"""

from __future__ import annotations

import html as html_lib
import ipaddress
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LEARNING_PATH = DATA_DIR / "web_learning.jsonl"
WEB_AUDIT_PATH = DATA_DIR / "web_audit.jsonl"

DEFAULT_ALLOWLIST: Tuple[str, ...] = (
    "reuters.com",
    "bloomberg.com",
    "cnbc.com",
    "marketwatch.com",
    "ft.com",
    "wsj.com",
    "federalreserve.gov",
    "sec.gov",
    "investing.com",
    "yahoo.com",
    "finance.yahoo.com",
    "bbc.com",
    "bbc.co.uk",
)

CRYPTO_ALLOWLIST: Tuple[str, ...] = ("coindesk.com",)

# Common URL shorteners — always blocked (open redirect / opaque hop).
_SHORTENERS = frozenset(
    {
        "bit.ly",
        "t.co",
        "tinyurl.com",
        "goo.gl",
        "ow.ly",
        "is.gd",
        "buff.ly",
        "rebrand.ly",
        "cutt.ly",
        "tiny.cc",
        "rb.gy",
        "shorturl.at",
        "lnkd.in",
        "trib.al",
    }
)

_BLOCKED_SCHEMES = frozenset({"file", "ftp", "data", "javascript", "blob", "about"})
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "local"})

_SECRET_RE = re.compile(
    r"(api[_-]?key|apikey|secret|password|token|private[_-]?key|bearer\s+\S+|sk-[A-Za-z0-9]+)",
    re.I,
)

_TAG_RE = re.compile(r"<[^>]+>", re.S)
_SCRIPT_RE = re.compile(r"<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>", re.I | re.S)
_WS_RE = re.compile(r"[ \t\f\v]+")
_NL_RE = re.compile(r"\n{3,}")

_lock = threading.RLock()
_fetch_times: List[float] = []

# Search / hub templates (host must still pass allowlist at fetch time).
_SEARCH_TEMPLATES: Tuple[Tuple[str, str], ...] = (
    ("reuters.com", "https://www.reuters.com/site-search/?query={q}"),
    ("cnbc.com", "https://www.cnbc.com/search/?query={q}"),
    ("marketwatch.com", "https://www.marketwatch.com/search?q={q}"),
    ("investing.com", "https://www.investing.com/search/?q={q}"),
    ("yahoo.com", "https://finance.yahoo.com/lookup?s={q}"),
    ("bbc.com", "https://www.bbc.com/search?q={q}"),
    ("federalreserve.gov", "https://www.federalreserve.gov/search.htm?query={q}"),
    ("sec.gov", "https://www.sec.gov/search-results.html?keywords={q}"),
)

_TOPIC_HUBS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    (
        "macro",
        "https://www.federalreserve.gov/newsevents.htm",
        ("fed", "fomc", "rates", "macro", "inflation", "cpi", "powell"),
    ),
    (
        "sec",
        "https://www.sec.gov/news/pressreleases",
        ("sec", "edgar", "filing", "enforcement"),
    ),
    (
        "markets",
        "https://www.cnbc.com/markets/",
        ("market", "earnings", "stocks", "equity", "nasdaq", "s&p"),
    ),
)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truthy_env(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def web_enabled() -> bool:
    env = _truthy_env("COPILOT_WEB_ENABLED")
    if env is not None:
        return env
    try:
        from .config import get_runtime_config

        return bool(getattr(get_runtime_config(), "copilot_web_enabled", True))
    except Exception:
        return True


def crypto_web_enabled() -> bool:
    env = _truthy_env("COPILOT_WEB_CRYPTO")
    if env is not None:
        return env
    try:
        from .config import get_runtime_config

        return bool(getattr(get_runtime_config(), "copilot_web_crypto_enabled", False))
    except Exception:
        return False


def _cfg_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        from .config import get_runtime_config

        v = int(getattr(get_runtime_config(), name, default) or default)
    except Exception:
        v = default
    return max(lo, min(hi, v))


def get_allowlist() -> List[str]:
    """Resolved allowlist (config / env / defaults + optional crypto)."""
    env_raw = os.environ.get("COPILOT_WEB_ALLOWLIST", "").strip()
    hosts: List[str] = []
    if env_raw:
        hosts = [h.strip().lower().lstrip(".") for h in env_raw.split(",") if h.strip()]
    else:
        try:
            from .config import get_runtime_config

            cfg_list = getattr(get_runtime_config(), "copilot_web_allowlist", None) or []
            if isinstance(cfg_list, list) and cfg_list:
                hosts = [str(h).strip().lower().lstrip(".") for h in cfg_list if h]
        except Exception:
            hosts = []
    if not hosts:
        hosts = list(DEFAULT_ALLOWLIST)
    if crypto_web_enabled():
        for h in CRYPTO_ALLOWLIST:
            if h not in hosts:
                hosts.append(h)
    # De-dupe preserving order
    seen = set()
    out: List[str] = []
    for h in hosts:
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _is_private_or_loopback_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        return False


def host_allowed(url_or_host: str, allowlist: Optional[Sequence[str]] = None) -> Tuple[bool, str]:
    """
    Return (ok, reason). reason is 'ok' or a short denial code.
    """
    raw = (url_or_host or "").strip()
    if not raw:
        return False, "empty"

    # If bare host (no scheme), normalize for parse
    if "://" not in raw and not raw.startswith("//"):
        candidate = "https://" + raw
    else:
        candidate = raw

    try:
        parts = urllib.parse.urlsplit(candidate)
    except ValueError:
        return False, "bad_url"

    scheme = (parts.scheme or "").lower()
    if scheme in _BLOCKED_SCHEMES:
        return False, f"blocked_scheme:{scheme or 'none'}"
    if scheme and scheme not in ("http", "https"):
        return False, f"blocked_scheme:{scheme}"

    host = (parts.hostname or "").lower().strip(".")
    if not host:
        return False, "no_host"
    if host in _LOOPBACK_HOSTS or host.endswith(".localhost") or host.endswith(".local"):
        return False, "localhost"
    if _is_ip_literal(host):
        if _is_private_or_loopback_ip(host):
            return False, "private_ip"
        return False, "ip_literal"  # block arbitrary public IPs too

    # Shorteners (exact or subdomain)
    for s in _SHORTENERS:
        if host == s or host.endswith("." + s):
            return False, "shortener"

    allowed = [a.lower().lstrip(".") for a in (allowlist if allowlist is not None else get_allowlist())]
    for a in allowed:
        if host == a or host.endswith("." + a):
            # Prefer equity/macro: bbc paths are soft-preferred but not hard-required
            return True, "ok"
    return False, "not_allowlisted"


def _scrub(text: str) -> str:
    return _SECRET_RE.sub("***", text or "")


def html_to_text(raw: str, *, max_chars: int = 12000) -> str:
    """Strip tags/scripts; return plain text (no execution)."""
    if not raw:
        return ""
    s = _SCRIPT_RE.sub(" ", raw)
    s = _TAG_RE.sub(" ", s)
    s = html_lib.unescape(s)
    s = _WS_RE.sub(" ", s)
    s = _NL_RE.sub("\n\n", s.replace("\r", "\n"))
    s = _scrub(s).strip()
    if len(s) > max_chars:
        s = s[: max_chars - 20] + " …[truncated]"
    return s


def _rate_limit_ok() -> Tuple[bool, str]:
    limit = _cfg_int("copilot_web_rate_limit", 8, 1, 60)
    window = 60.0
    now = time.monotonic()
    with _lock:
        # Drop old
        while _fetch_times and now - _fetch_times[0] > window:
            _fetch_times.pop(0)
        if len(_fetch_times) >= limit:
            return False, f"rate_limited ({limit}/{int(window)}s)"
        _fetch_times.append(now)
    return True, "ok"


def _audit(event: str, **fields: Any) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        row = {"ts": _utc(), "event": event, **fields}
        # Light audit — no bodies / secrets
        line = json.dumps(row, default=str)
        if _SECRET_RE.search(line):
            line = _SECRET_RE.sub("***", line)
        with _lock:
            with WEB_AUDIT_PATH.open("a") as f:
                f.write(line + "\n")
        # Also a light decision_audit breadcrumb when enabled
        try:
            from .config import get_runtime_config
            from .decision_audit import append_decision

            if getattr(get_runtime_config(), "decision_audit_enabled", True):
                append_decision(
                    {
                        "source": "copilot_web",
                        "event": event,
                        "url": fields.get("url"),
                        "host": fields.get("host"),
                        "ok": fields.get("ok"),
                        "reason": fields.get("reason"),
                        "bytes": fields.get("bytes"),
                    }
                )
        except Exception:
            pass
    except Exception:
        pass


def _user_agent() -> str:
    return "GAMMA-R-Copilot/1.0 (+educational; allowlisted-finance-only; no-credentials)"


def fetch_url(
    url: str,
    *,
    timeout: Optional[float] = None,
    max_bytes: Optional[int] = None,
    for_learning: bool = False,
) -> Dict[str, Any]:
    """
    Fetch + extract text ONLY if URL host is allowlisted.
    Never follows to non-allowlisted redirects (we disable auto-redirect hop abuse
    by re-checking final URL host).
    """
    if not web_enabled():
        return {
            "ok": False,
            "error": "copilot_web_disabled",
            "hint": "Set copilot_web_enabled=1 or COPILOT_WEB_ENABLED=1 to enable allowlisted fetches.",
        }

    url = (url or "").strip()
    allow = get_allowlist()
    ok, reason = host_allowed(url, allow)
    if not ok:
        _audit("fetch_reject", url=url[:240], reason=reason, ok=False)
        return {"ok": False, "error": "allowlist_reject", "reason": reason, "url": url[:240]}

    rl_ok, rl_reason = _rate_limit_ok()
    if not rl_ok:
        _audit("fetch_rate_limit", url=url[:240], reason=rl_reason, ok=False)
        return {"ok": False, "error": "rate_limited", "reason": rl_reason}

    timeout = float(timeout if timeout is not None else _cfg_int("copilot_web_timeout_sec", 8, 2, 30))
    max_bytes = int(max_bytes if max_bytes is not None else _cfg_int("copilot_web_max_bytes", 400_000, 20_000, 2_000_000))

    try:
        parts = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
        # Force https when scheme missing; never attach cookies / auth
        final_url = urllib.parse.urlunsplit(
            (parts.scheme or "https", parts.netloc, parts.path or "/", parts.query, "")
        )
        req = urllib.request.Request(
            final_url,
            headers={
                "User-Agent": _user_agent(),
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
                "Accept-Language": "en-US,en;q=0.8",
                # Explicitly no credentials / cookies
            },
            method="GET",
        )

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
                # Only allow redirects that stay on allowlist
                ok2, reason2 = host_allowed(newurl, allow)
                if not ok2:
                    raise urllib.error.HTTPError(
                        newurl, code, f"redirect_blocked:{reason2}", headers, None
                    )
                return urllib.request.HTTPRedirectHandler.redirect_request(
                    self, req, fp, code, msg, headers, newurl
                )

        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=timeout) as resp:
            # Re-check final URL after redirects
            final = resp.geturl() or final_url
            ok_f, reason_f = host_allowed(final, allow)
            if not ok_f:
                _audit("fetch_reject", url=final[:240], reason=f"final:{reason_f}", ok=False)
                return {
                    "ok": False,
                    "error": "allowlist_reject",
                    "reason": f"final:{reason_f}",
                    "url": final[:240],
                }
            ctype = (resp.headers.get("Content-Type") or "").lower()
            # Read with hard cap
            chunks: List[bytes] = []
            total = 0
            truncated = False
            while True:
                block = resp.read(min(64_000, max_bytes - total + 1))
                if not block:
                    break
                total += len(block)
                if total > max_bytes:
                    chunks.append(block[: max(0, max_bytes - (total - len(block)))])
                    truncated = True
                    break
                chunks.append(block)
            raw_bytes = b"".join(chunks)

        # Soft paywall / content-type handling
        if "json" in ctype and "html" not in ctype:
            try:
                text = raw_bytes.decode("utf-8", errors="replace")
                text = _scrub(text)[:8000]
            except Exception:
                text = ""
            note = "json_body"
        else:
            try:
                decoded = raw_bytes.decode("utf-8", errors="replace")
            except Exception:
                decoded = raw_bytes.decode("latin-1", errors="replace")
            text = html_to_text(decoded)
            note = None
            # Heuristic paywall / soft-block messages
            low = text.lower()[:2000]
            if any(
                x in low
                for x in (
                    "subscribe to continue",
                    "subscription required",
                    "create a free account",
                    "sign in to read",
                    "paywall",
                    "for subscribers",
                )
            ):
                note = "possible_paywall"
                text = (
                    text[:2500]
                    + "\n\n[Note: page may be paywalled — excerpt only; educational context.]"
                )

        host = urllib.parse.urlsplit(final).hostname or ""
        out = {
            "ok": True,
            "url": final[:400],
            "host": host,
            "bytes": len(raw_bytes),
            "truncated": truncated,
            "content_type": ctype[:80],
            "text": text,
            "chars": len(text),
            "note": note,
            "educational": True,
            "disclaimer": "Educational context only — not financial advice. Do not treat as buy/sell signal.",
        }
        _audit(
            "fetch_ok",
            url=final[:240],
            host=host,
            ok=True,
            bytes=len(raw_bytes),
            truncated=truncated,
            note=note,
            for_learning=for_learning,
        )
        return out
    except urllib.error.HTTPError as e:
        code = getattr(e, "code", None)
        reason_s = str(getattr(e, "reason", e))[:120]
        if "redirect_blocked" in reason_s:
            _audit("fetch_reject", url=url[:240], reason=reason_s, ok=False)
            return {"ok": False, "error": "allowlist_reject", "reason": reason_s, "url": url[:240]}
        # Soft-handle paywalls / forbidden
        if code in (401, 403, 402, 451):
            _audit("fetch_paywall", url=url[:240], reason=f"http_{code}", ok=False)
            return {
                "ok": False,
                "error": "paywall_or_forbidden",
                "http_status": code,
                "url": url[:240],
                "hint": "Source may require subscription; try another allowlisted outlet.",
            }
        _audit("fetch_error", url=url[:240], reason=f"http_{code}", ok=False)
        return {"ok": False, "error": f"http_{code}", "reason": reason_s, "url": url[:240]}
    except urllib.error.URLError as e:
        _audit("fetch_error", url=url[:240], reason=f"url:{type(e.reason).__name__}", ok=False)
        return {"ok": False, "error": "network_error", "reason": str(e.reason)[:120], "url": url[:240]}
    except TimeoutError:
        _audit("fetch_error", url=url[:240], reason="timeout", ok=False)
        return {"ok": False, "error": "timeout", "url": url[:240]}
    except Exception as e:
        _audit("fetch_error", url=url[:240], reason=type(e).__name__, ok=False)
        return {"ok": False, "error": f"{type(e).__name__}", "reason": str(e)[:120], "url": url[:240]}


def _extract_links(text_htmlish: str, base_host_hint: str = "") -> List[str]:
    """Pull http(s) hrefs from raw HTML/text; keep allowlisted only."""
    urls = re.findall(r"https?://[^\s\"'<>]+", text_htmlish or "", flags=re.I)
    # Also relative-looking paths won't have scheme — skip those
    out: List[str] = []
    seen = set()
    allow = get_allowlist()
    for u in urls:
        u = u.rstrip(").,];}'\"")
        ok, _ = host_allowed(u, allow)
        if not ok:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= 12:
            break
    return out


def web_search_finance(query: str, *, max_sources: int = 3) -> Dict[str, Any]:
    """
    Multi-fetch allowlisted search/hub pages for a finance query.
    Does not use unrestricted web search engines.
    """
    if not web_enabled():
        return {
            "ok": False,
            "error": "copilot_web_disabled",
            "hint": "Enable with copilot_web_enabled=1 (or COPILOT_WEB_ENABLED=1).",
        }

    q = _scrub((query or "").strip())[:180]
    if not q:
        return {"ok": False, "error": "empty_query"}

    # Soft refuse advice-shaped queries
    ql = q.lower()
    if any(x in ql for x in ("should i buy", "should i sell", "what to buy", "pick a stock for me")):
        return {
            "ok": False,
            "error": "advice_refusal",
            "hint": "Web tools are educational macro/news context only — no buy/sell recommendations.",
        }

    max_sources = max(1, min(5, int(max_sources)))
    allow = set(get_allowlist())
    q_enc = urllib.parse.quote_plus(q)
    targets: List[str] = []

    # Topic hubs first when keywords match
    for _name, hub_url, keys in _TOPIC_HUBS:
        if any(k in ql for k in keys):
            ok, _ = host_allowed(hub_url, allow)
            if ok:
                targets.append(hub_url)

    for host, tmpl in _SEARCH_TEMPLATES:
        if host not in allow and not any(host == a or host.endswith("." + a) or a.endswith("." + host) for a in allow):
            # host token must be covered by allowlist entry
            covered = any(host == a or host.endswith("." + a) or a == host for a in allow)
            if not covered:
                # also allow if allowlist has parent (yahoo.com covers finance.yahoo via template host yahoo.com)
                covered = any(host == a or host.endswith("." + a) for a in allow)
            if not covered:
                continue
        url = tmpl.format(q=q_enc)
        ok, _ = host_allowed(url, allow)
        if ok and url not in targets:
            targets.append(url)
        if len(targets) >= max_sources + 2:
            break

    results: List[Dict[str, Any]] = []
    sources: List[str] = []
    for url in targets[: max_sources + 1]:
        fetched = fetch_url(url)
        if not fetched.get("ok"):
            results.append(
                {
                    "url": url,
                    "ok": False,
                    "error": fetched.get("error"),
                    "reason": fetched.get("reason"),
                }
            )
            continue
        text = fetched.get("text") or ""
        # Keep a short snippet for the model
        snippet = text[:1800]
        link_candidates = _extract_links(text)
        # Prefer article-like paths over pure search pages
        article_links = [
            u
            for u in link_candidates
            if not any(x in u.lower() for x in ("/search", "lookup?", "site-search"))
        ][:5]
        entry = {
            "url": fetched.get("url"),
            "host": fetched.get("host"),
            "ok": True,
            "snippet": snippet,
            "note": fetched.get("note"),
            "related": article_links,
        }
        results.append(entry)
        sources.append(str(fetched.get("url")))
        # Optionally deepen one related allowlisted article
        if article_links and len(results) < max_sources + 2:
            deep = fetch_url(article_links[0])
            if deep.get("ok"):
                results.append(
                    {
                        "url": deep.get("url"),
                        "host": deep.get("host"),
                        "ok": True,
                        "snippet": (deep.get("text") or "")[:2000],
                        "note": deep.get("note"),
                        "related": [],
                    }
                )
                sources.append(str(deep.get("url")))

    # Offline prior learning hits
    prior = query_web_learning(q, limit=3)

    return {
        "ok": True,
        "query": q,
        "results": results[: max_sources + 2],
        "sources": sources[:8],
        "prior_learning": prior.get("notes") or [],
        "allowlist": sorted(allow)[:20],
        "educational": True,
        "disclaimer": "Allowlisted educational context only — not financial advice; refuse hard buy/sell.",
    }


def append_web_learning(
    topic: str,
    summary: str,
    *,
    urls: Optional[Sequence[str]] = None,
    tags: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Append one distilled learning row (dated, sourced, tagged)."""
    topic_s = _scrub((topic or "").strip())[:120]
    summary_s = _scrub((summary or "").strip())[:1200]
    if not topic_s or not summary_s:
        return {"ok": False, "error": "topic_and_summary_required"}
    urls_l = []
    allow = get_allowlist()
    for u in urls or []:
        u = str(u).strip()
        ok, _ = host_allowed(u, allow)
        if ok and u not in urls_l:
            urls_l.append(u[:400])
        if len(urls_l) >= 8:
            break
    tags_l = []
    for t in tags or []:
        t = re.sub(r"[^a-z0-9_\-]+", "", str(t).lower().strip())[:32]
        if t and t not in tags_l:
            tags_l.append(t)
        if len(tags_l) >= 10:
            break
    if not tags_l:
        tags_l = ["web", "macro"]

    row = {
        "ts": _utc(),
        "date": _utc()[:10],
        "topic": topic_s,
        "summary": summary_s,
        "urls": urls_l,
        "tags": tags_l,
        "educational": True,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        with LEARNING_PATH.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")
    _audit("learn_write", topic=topic_s, urls=urls_l[:4], ok=True)

    # Mirror a short fact into co-pilot memory (optional, redacted)
    try:
        from .copilot_memory import remember_fact

        remember_fact(
            f"Web learn ({row['date']}): {topic_s} — {summary_s[:220]}",
            kind="web_learning",
        )
    except Exception:
        pass

    return {"ok": True, "stored": row, "path": str(LEARNING_PATH)}


def query_web_learning(topic: str = "", *, limit: int = 8) -> Dict[str, Any]:
    """Read distilled notes (offline). Filter by topic/tag substring when provided."""
    limit = max(1, min(40, int(limit)))
    needle = (topic or "").strip().lower()
    if not LEARNING_PATH.exists():
        return {"ok": True, "notes": [], "count": 0, "path": str(LEARNING_PATH)}
    rows: List[Dict[str, Any]] = []
    try:
        with _lock:
            lines = LEARNING_PATH.read_text().splitlines()
    except OSError:
        return {"ok": False, "error": "read_failed", "notes": []}
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if needle:
            blob = " ".join(
                [
                    str(row.get("topic") or ""),
                    str(row.get("summary") or ""),
                    " ".join(row.get("tags") or []),
                ]
            ).lower()
            if needle not in blob and not any(needle in str(t).lower() for t in (row.get("tags") or [])):
                continue
        rows.append(
            {
                "date": row.get("date") or (str(row.get("ts") or "")[:10]),
                "topic": row.get("topic"),
                "summary": row.get("summary"),
                "urls": row.get("urls") or [],
                "tags": row.get("tags") or [],
            }
        )
        if len(rows) >= limit:
            break
    return {"ok": True, "notes": rows, "count": len(rows), "path": str(LEARNING_PATH), "query": topic}


def _distill_summary(topic: str, snippets: Sequence[str]) -> str:
    """Heuristic offline distill — short, sourced later by caller."""
    parts: List[str] = []
    for s in snippets:
        s = (s or "").strip()
        if not s:
            continue
        # First ~2 sentences-ish
        cut = re.split(r"(?<=[.!?])\s+", s)
        bit = " ".join(cut[:3])[:420]
        if bit and bit not in parts:
            parts.append(bit)
        if len(parts) >= 3:
            break
    if not parts:
        return f"No extractable text for «{topic}» from allowlisted fetches."
    body = " | ".join(parts)
    return f"{topic}: {body}"[:1100]


def learn_from_web(topic: str, *, max_sources: int = 3) -> Dict[str, Any]:
    """Search allowlisted sources, distill notes into web_learning store."""
    if not web_enabled():
        return {
            "ok": False,
            "error": "copilot_web_disabled",
            "hint": "Enable with copilot_web_enabled=1 (or COPILOT_WEB_ENABLED=1).",
        }
    topic_s = _scrub((topic or "").strip())[:160]
    if not topic_s:
        return {"ok": False, "error": "empty_topic"}

    search = web_search_finance(topic_s, max_sources=max_sources)
    if not search.get("ok"):
        return search

    snippets: List[str] = []
    urls: List[str] = []
    tags = ["web", "macro"]
    tl = topic_s.lower()
    if any(k in tl for k in ("earn", "eps", "guidance")):
        tags.append("earnings")
    if any(k in tl for k in ("fed", "fomc", "rate", "inflation", "cpi")):
        tags.append("macro")
    if any(k in tl for k in ("sec", "filing", "10-k", "10-q")):
        tags.append("sec")
    if crypto_web_enabled() and any(k in tl for k in ("bitcoin", "crypto", "eth")):
        tags.append("crypto")

    for r in search.get("results") or []:
        if isinstance(r, dict) and r.get("ok") and r.get("snippet"):
            snippets.append(str(r["snippet"]))
            if r.get("url"):
                urls.append(str(r["url"]))

    if not snippets:
        # Still record a soft miss so local brain can say we tried
        summary = (
            f"{topic_s}: allowlisted fetch returned little usable text "
            "(paywall, block, or empty). Prefer equity/macro outlets; educational only."
        )
        stored = append_web_learning(topic_s, summary, urls=urls, tags=tags + ["sparse"])
        return {
            "ok": True,
            "sparse": True,
            "summary": summary,
            "sources": urls,
            "stored": stored.get("stored"),
            "search": {"result_count": len(search.get("results") or [])},
            "disclaimer": search.get("disclaimer"),
        }

    summary = _distill_summary(topic_s, snippets)
    stored = append_web_learning(topic_s, summary, urls=urls, tags=tags)
    return {
        "ok": True,
        "sparse": False,
        "summary": summary,
        "sources": urls[:8],
        "stored": stored.get("stored"),
        "prior_learning": search.get("prior_learning") or [],
        "disclaimer": "Distilled allowlisted notes for education — not financial advice.",
    }


def web_status() -> Dict[str, Any]:
    return {
        "enabled": web_enabled(),
        "crypto_enabled": crypto_web_enabled(),
        "allowlist": get_allowlist(),
        "rate_limit": _cfg_int("copilot_web_rate_limit", 8, 1, 60),
        "timeout_sec": _cfg_int("copilot_web_timeout_sec", 8, 2, 30),
        "max_bytes": _cfg_int("copilot_web_max_bytes", 400_000, 20_000, 2_000_000),
        "learning_path": str(LEARNING_PATH),
        "audit_path": str(WEB_AUDIT_PATH),
        "note": "Allowlisted finance/macro only — not open browsing. Disable: copilot_web_enabled=0 or COPILOT_WEB_ENABLED=0.",
    }

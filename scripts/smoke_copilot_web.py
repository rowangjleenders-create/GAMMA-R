#!/usr/bin/env python3
"""Smoke: allowlisted co-pilot web — reject + mock accept + learning store."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _FakeResp:
    def __init__(self, body: bytes, url: str = "https://www.reuters.com/markets/", ctype: str = "text/html"):
        self._body = body
        self._url = url
        self.headers = {"Content-Type": ctype}

    def geturl(self) -> str:
        return self._url

    def read(self, n: int = -1) -> bytes:
        if not self._body:
            return b""
        if n < 0 or n >= len(self._body):
            out, self._body = self._body, b""
            return out
        out, self._body = self._body[:n], self._body[n:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def main() -> int:
    os.environ.pop("COPILOT_WEB_ENABLED", None)
    os.environ.pop("COPILOT_WEB_ALLOWLIST", None)
    os.environ.pop("COPILOT_WEB_CRYPTO", None)

    from momentum_bot import copilot_web as cw
    from momentum_bot.copilot_tools import TOOL_SCHEMAS, execute_tool
    from momentum_bot.config import get_runtime_config, set_runtime_config

    cfg = get_runtime_config()
    cfg = cfg.update({"copilot_web_enabled": True, "copilot_web_crypto_enabled": False})
    set_runtime_config(cfg)

    # Isolate learning/audit paths
    td = tempfile.TemporaryDirectory()
    tmp = Path(td.name)
    cw.LEARNING_PATH = tmp / "web_learning.jsonl"
    cw.WEB_AUDIT_PATH = tmp / "web_audit.jsonl"
    cw.DATA_DIR = tmp

    names = {
        (t.get("function") or {}).get("name")
        for t in TOOL_SCHEMAS
        if isinstance(t, dict)
    }
    for need in ("web_search_finance", "web_fetch_url", "learn_from_web", "get_web_learning"):
        assert need in names, f"missing schema {need}"
    print("schemas_ok")

    # --- allowlist rejects ---
    rejects = [
        ("file:///etc/passwd", "blocked_scheme"),
        ("http://127.0.0.1/secret", "localhost"),
        ("http://localhost:8000/admin", "localhost"),
        ("https://192.168.1.10/x", "private_ip"),
        ("https://8.8.8.8/", "ip_literal"),
        ("https://bit.ly/abc", "shortener"),
        ("https://evil.example.com/markets", "not_allowlisted"),
        ("https://coindesk.com/markets", "not_allowlisted"),  # crypto off
    ]
    for url, expect in rejects:
        ok, reason = cw.host_allowed(url)
        assert not ok, f"should reject {url}"
        assert expect in reason or reason.startswith(expect) or expect in reason, (
            f"{url}: got reason={reason}, expect~{expect}"
        )
        out = execute_tool("web_fetch_url", {"url": url})
        assert out.get("ok") is False, out
        assert out.get("error") in ("allowlist_reject", "copilot_web_disabled"), out
        print(f"reject_ok {url} -> {reason}")

    # Direct API reject path
    r = cw.fetch_url("https://not-on-list.example/news")
    assert r.get("error") == "allowlist_reject"
    print("fetch_reject_ok")

    # --- mock allowlist accept ---
    html = b"""<!doctype html><html><body>
    <script>evil()</script>
    <h1>Fed holds rates</h1>
    <p>The Federal Reserve left the policy rate unchanged amid cooling inflation.</p>
    <a href="https://www.reuters.com/markets/fed-holds-rates">more</a>
    <a href="https://evil.example.com/nope">bad</a>
    </body></html>"""

    def fake_open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        return _FakeResp(html, url=url)

    with patch("urllib.request.build_opener") as bo:
        opener = MagicMock()
        opener.open.side_effect = lambda req, timeout=None: fake_open(req, timeout)
        bo.return_value = opener
        # clear rate window
        cw._fetch_times.clear()
        got = cw.fetch_url("https://www.reuters.com/markets/")
        assert got.get("ok") is True, got
        assert "Federal Reserve" in (got.get("text") or ""), got.get("text")
        assert "evil()" not in (got.get("text") or "")
        print("mock_fetch_ok chars=", got.get("chars"))

        cw._fetch_times.clear()
        learned = cw.learn_from_web("Fed rates", max_sources=2)
        assert learned.get("ok") is True, learned
        assert learned.get("summary"), learned
        print("learn_ok", (learned.get("summary") or "")[:120])

    # Offline recall
    q = cw.query_web_learning("Fed", limit=5)
    assert q.get("ok") and (q.get("notes") or []), q
    print("recall_ok count=", q.get("count"))

    # Tool execute path with mock
    with patch.object(cw, "fetch_url", return_value={
        "ok": True,
        "url": "https://www.cnbc.com/markets/",
        "host": "www.cnbc.com",
        "text": "Markets steady as yields ease. Educational excerpt.",
        "sources": ["https://www.cnbc.com/markets/"],
    }):
        # web_search still calls real fetch_url inside — patch at module used by search
        pass

    with patch("momentum_bot.copilot_web.fetch_url") as fu:
        fu.return_value = {
            "ok": True,
            "url": "https://www.cnbc.com/search/?query=cpi",
            "host": "www.cnbc.com",
            "text": "CPI cools; markets react. <b>ignore</b>",
            "note": None,
        }
        cw._fetch_times.clear()
        # Patch extract to avoid deeper fetches needing more mocks
        with patch.object(cw, "_extract_links", return_value=[]):
            s = execute_tool("web_search_finance", {"query": "CPI inflation", "max_sources": 2})
        assert s.get("ok") is True, s
        print("tool_search_ok results=", len(s.get("results") or []))

    # Disable flag
    set_runtime_config(get_runtime_config().update({"copilot_web_enabled": False}))
    assert cw.web_enabled() is False
    d = execute_tool("web_fetch_url", {"url": "https://www.reuters.com/"})
    assert d.get("error") == "copilot_web_disabled", d
    print("disable_ok")

    # Re-enable via env override
    set_runtime_config(get_runtime_config().update({"copilot_web_enabled": True}))
    os.environ["COPILOT_WEB_ENABLED"] = "0"
    assert cw.web_enabled() is False
    os.environ["COPILOT_WEB_ENABLED"] = "1"
    assert cw.web_enabled() is True
    print("env_override_ok")

    # Local brain path
    from momentum_bot.copilot import chat
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("LLM_API_KEY", None)
    os.environ.pop("GAMMAR_LLM_KEY", None)
    # Point learning path still to tmp with notes
    r = chat("What did you learn about Fed?")
    assert r.get("intent") == "web_learning", r
    assert "Fed" in (r.get("reply") or "") or "fed" in (r.get("reply") or "").lower() or "web learning" in (r.get("reply") or "").lower()
    print("local_brain_ok intent=", r.get("intent"))
    print("sources=", r.get("sources"))

    # Crypto still blocked by default
    ok_c, reason_c = cw.host_allowed("https://www.coindesk.com/markets")
    assert not ok_c and "not_allowlisted" in reason_c
    os.environ["COPILOT_WEB_CRYPTO"] = "1"
    ok_c2, _ = cw.host_allowed("https://www.coindesk.com/markets")
    assert ok_c2
    print("crypto_gate_ok")

    print("\nSMOKE_OK")
    td.cleanup()
    return 0


if __name__ == "__main__":
    _saved = {k: os.environ.get(k) for k in ("COPILOT_WEB_ENABLED", "COPILOT_WEB_CRYPTO", "COPILOT_WEB_ALLOWLIST")}
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print("SMOKE_FAIL", e)
        raise SystemExit(1)
    finally:
        for k, v in _saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

#!/usr/bin/env python3
"""Smoke: API auth, query-secret rejection, rate limit, redaction, compare_digest."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _clean_env() -> None:
    for k in list(os.environ):
        if any(
            x in k
            for x in (
                "OWNER_SHARED_SECRET",
                "API_SHARED_SECRET",
                "REQUIRE_API_SECRET",
                "GAMMA_R_HARDENED",
                "GAMMA_R_BIND_HOST",
                "API_RATE_LIMIT",
            )
        ):
            os.environ.pop(k, None)


def main() -> int:
    from fastapi.testclient import TestClient

    from momentum_bot.security import (
        clear_secret_cache,
        redact_obj,
        redact_text,
        scrub_url,
        secrets_equal,
    )

    failures: list[str] = []

    # --- compare_digest / secrets_equal ---
    if not secrets_equal("same-secret-value", "same-secret-value"):
        failures.append("secrets_equal true case")
    if secrets_equal("same-secret-value", "other-secret-value"):
        failures.append("secrets_equal false case")
    if secrets_equal(None, "x") or secrets_equal("", "x"):
        failures.append("secrets_equal empty")

    # --- redaction ---
    red = redact_obj(
        {
            "alpaca_api_key": "AKIAEXAMPLE",
            "nested": {"owner_shared_secret": "supersecret", "ok": 1},
            "note": "token=Bearer sk-abcdefghijklmnopqrstuvwxyz",
        }
    )
    if red.get("alpaca_api_key") != "***":
        failures.append(f"redact key: {red}")
    if red["nested"].get("owner_shared_secret") != "***" or red["nested"].get("ok") != 1:
        failures.append(f"redact nested: {red}")
    if "sk-abcdef" in str(red) or "supersecret" in str(red):
        failures.append(f"redact leaked: {red}")
    if "sk-abcdef" in redact_text("Bearer sk-abcdefghijklmnopqrstuvwxyz"):
        failures.append("redact_text failed")
    scrubbed = scrub_url("http://127.0.0.1:8000/x?owner_secret=leak&a=1")
    if "leak" in scrubbed or "owner_secret=leak" in scrubbed:
        failures.append(f"scrub_url leaked: {scrubbed}")

    # --- open loopback ---
    _clean_env()
    os.environ["GAMMA_R_BIND_HOST"] = "127.0.0.1"
    clear_secret_cache()
    # Avoid picking up a real data/.owner_secret during open-mode test
    import momentum_bot.security as sec

    real_path = sec.OWNER_SECRET_PATH
    tmp = Path(tempfile.mkdtemp()) / ".owner_secret"
    sec.OWNER_SECRET_PATH = tmp
    clear_secret_cache()

    from importlib import reload
    import momentum_bot.api as api_mod

    reload(api_mod)
    client = TestClient(api_mod.app)

    h = client.get("/health")
    if h.status_code != 200 or h.json().get("auth") not in ("open", "shared_secret"):
        # if file existed elsewhere may be shared_secret — for open we forced empty path
        if h.json().get("auth") != "open":
            failures.append(f"expected open health auth, got {h.json()}")
    c = client.get("/config")
    if c.status_code != 200:
        failures.append(f"open /config expected 200, got {c.status_code}")

    # --- secret required ---
    os.environ["OWNER_SHARED_SECRET"] = "smoke-test-secret-value-32chars!!"
    os.environ["REQUIRE_API_SECRET"] = "1"
    clear_secret_cache()
    reload(api_mod)
    client = TestClient(api_mod.app)

    h2 = client.get("/health")
    if h2.status_code != 200:
        failures.append(f"health should stay open, got {h2.status_code}")

    noauth = client.get("/config")
    if noauth.status_code != 401:
        failures.append(f"missing secret expected 401, got {noauth.status_code} {noauth.text}")

    bad = client.get("/config", headers={"X-Owner-Secret": "wrong"})
    if bad.status_code != 401:
        failures.append(f"bad secret expected 401, got {bad.status_code}")

    ok = client.get("/config", headers={"X-Owner-Secret": "smoke-test-secret-value-32chars!!"})
    if ok.status_code != 200:
        failures.append(f"good X-Owner-Secret expected 200, got {ok.status_code}")

    okb = client.get(
        "/config",
        headers={"Authorization": "Bearer smoke-test-secret-value-32chars!!"},
    )
    if okb.status_code != 200:
        failures.append(f"Bearer expected 200, got {okb.status_code}")

    # query param rejected
    q = client.get("/config?owner_secret=smoke-test-secret-value-32chars!!")
    if q.status_code != 400:
        failures.append(f"query owner_secret expected 400, got {q.status_code} {q.text}")

    # docs protected when secret set
    docs = client.get("/docs")
    if docs.status_code not in (401, 404):  # 404 if docs disabled entirely
        # may be 401 from middleware
        if docs.status_code != 401:
            failures.append(f"docs expected 401/404 when secured, got {docs.status_code}")

    # rate limit (tight)
    os.environ["API_RATE_LIMIT"] = "5"
    clear_secret_cache()
    # rebuild limiter on module
    reload(api_mod)
    client = TestClient(api_mod.app)
    hdr = {"X-Owner-Secret": "smoke-test-secret-value-32chars!!"}
    codes = []
    for _ in range(8):
        codes.append(client.post("/copilot", headers=hdr, json={"message": "ping", "history": []}).status_code)
    if 429 not in codes:
        # copilot may 500 without openai — still should rate-limit before handler sometimes
        # Try mutating config
        codes2 = []
        for i in range(10):
            codes2.append(
                client.put("/config", headers=hdr, json={"lookback_days": 10 + i}).status_code
            )
        if 429 not in codes2:
            failures.append(f"rate limit expected 429, got {codes} / {codes2}")

    # restore
    sec.OWNER_SECRET_PATH = real_path
    _clean_env()
    clear_secret_cache()

    if failures:
        print("SMOKE SECURITY FAIL:")
        for f in failures:
            print(" -", f)
        return 1
    print("SMOKE SECURITY OK")
    print("  secrets_equal (compare_digest)")
    print("  redaction + scrub_url")
    print("  open loopback /config")
    print("  secret required → 401; header/Bearer OK; query → 400")
    print("  rate limit → 429")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

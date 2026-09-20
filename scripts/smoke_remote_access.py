#!/usr/bin/env python3
"""Smoke: remote_access_enabled, GET /remote/status, POST /remote/session, secret when remote."""

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
                "REMOTE_ACCESS_ENABLED",
                "LIVE_TRADING_ENABLED",
                "API_RATE_LIMIT",
            )
        ):
            os.environ.pop(k, None)


def main() -> int:
    from importlib import reload
    from fastapi.testclient import TestClient

    from momentum_bot.security import clear_secret_cache, remote_access_enabled, hardened_mode
    import momentum_bot.security as sec
    import momentum_bot.api as api_mod
    from momentum_bot.config import get_runtime_config, set_runtime_config, StrategyConfig

    failures: list[str] = []

    _clean_env()
    os.environ["GAMMA_R_BIND_HOST"] = "127.0.0.1"
    real_path = sec.OWNER_SECRET_PATH
    tmp = Path(tempfile.mkdtemp()) / ".owner_secret"
    sec.OWNER_SECRET_PATH = tmp
    clear_secret_cache()

    # Reset runtime config to seed (remote off)
    set_runtime_config(StrategyConfig.seed())
    reload(api_mod)
    client = TestClient(api_mod.app)

    # --- /remote/status public ---
    r = client.get("/remote/status")
    if r.status_code != 200:
        failures.append(f"/remote/status expected 200, got {r.status_code}")
    else:
        body = r.json()
        if body.get("prefer_tunnel") is not True:
            failures.append(f"prefer_tunnel missing: {body}")
        if body.get("live_locked") is not True:
            failures.append(f"live should be locked by default: {body}")
        if body.get("remote_access_enabled") is not False:
            failures.append(f"remote_access default false: {body}")
        if "tailscale" not in str(body.get("recommended_tunnels", [])).lower():
            failures.append(f"recommended_tunnels: {body.get('recommended_tunnels')}")

    # --- open loopback: /config ok without secret ---
    c = client.get("/config")
    if c.status_code != 200:
        failures.append(f"open /config expected 200, got {c.status_code}")

    # --- enable remote via env → hardened ---
    os.environ["REMOTE_ACCESS_ENABLED"] = "1"
    clear_secret_cache()
    if not remote_access_enabled():
        failures.append("REMOTE_ACCESS_ENABLED=1 should enable remote_access_enabled()")
    if not hardened_mode():
        failures.append("remote access should force hardened_mode()")

    # Without secret while remote → 503 on /config
    clear_secret_cache()
    bad = client.get("/config")
    if bad.status_code != 503:
        failures.append(f"remote without secret expected 503, got {bad.status_code} {bad.text}")

    # With secret → ok
    os.environ["OWNER_SHARED_SECRET"] = "smoke-remote-secret-value-32chars!!"
    clear_secret_cache()
    hdr = {"X-Owner-Secret": "smoke-remote-secret-value-32chars!!"}
    ok = client.get("/config", headers=hdr)
    if ok.status_code != 200:
        failures.append(f"remote with secret expected 200, got {ok.status_code}")

    st = client.get("/remote/status")
    if st.status_code != 200 or st.json().get("secret_required") is not True:
        failures.append(f"/remote/status secret_required: {st.status_code} {st.text}")

    # --- POST /remote/session ---
    sess_bad = client.post("/remote/session")
    if sess_bad.status_code != 401:
        failures.append(f"session without secret expected 401, got {sess_bad.status_code}")

    sess = client.post("/remote/session", headers=hdr, json={"client": "smoke"})
    if sess.status_code != 200 or not sess.json().get("ok"):
        failures.append(f"/remote/session failed: {sess.status_code} {sess.text}")
    else:
        mode = (sess.json().get("session") or {}).get("mode")
        if mode != "owner_secret_header":
            failures.append(f"session mode: {sess.json()}")
        if sess.json().get("live_locked") is not True:
            failures.append("session should report live_locked")

    # --- config flag path ---
    os.environ.pop("REMOTE_ACCESS_ENABLED", None)
    os.environ.pop("OWNER_SHARED_SECRET", None)
    clear_secret_cache()
    set_runtime_config(StrategyConfig.seed())
    cfg = get_runtime_config().update({"remote_access_enabled": True})
    set_runtime_config(cfg)
    if not remote_access_enabled():
        failures.append("config.remote_access_enabled=True should enable")
    if not hardened_mode("127.0.0.1"):
        failures.append("config remote should harden loopback")

    # restore
    set_runtime_config(StrategyConfig.seed())
    sec.OWNER_SECRET_PATH = real_path
    clear_secret_cache()
    _clean_env()

    if failures:
        print("FAIL smoke_remote_access:")
        for f in failures:
            print(" -", f)
        return 1
    print("OK smoke_remote_access")
    print("  GET /remote/status (public)")
    print("  REMOTE_ACCESS_ENABLED → secret required")
    print("  POST /remote/session with X-Owner-Secret")
    print("  config.remote_access_enabled hardens loopback")
    print("  live stays locked; prefer_tunnel=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

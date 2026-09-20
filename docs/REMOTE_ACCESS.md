# Remote access (secure)

GAMMA-R is a **private single-owner** paper-first API. Prefer a **tunnel / mesh VPN** over exposing a naked public IP.

## Enable (server)

```bash
# 1) Owner secret (required when remote / non-loopback)
export OWNER_SHARED_SECRET='long-random-string'   # or let serve auto-create data/.owner_secret

# 2) Opt into remote posture (forces hardened / secret-required)
export REMOTE_ACCESS_ENABLED=1
# or: PUT /config {"remote_access_enabled": true}

# 3) Bind loopback and reach via tunnel (recommended)
python -m momentum_bot serve --host 127.0.0.1 --port 8000

# LAN-only alternative (auto-requires secret):
# python -m momentum_bot serve --host 0.0.0.0 --port 8000
```

Check: `GET /remote/status` · validate: `POST /remote/session` with `X-Owner-Secret`.

Live trading stays **locked** unless you explicitly set `LIVE_TRADING_ENABLED=1`.

## Option A — Tailscale (recommended)

1. Install Tailscale on the API host and your phone: https://tailscale.com/download
2. Join the same tailnet; note the host’s Tailscale IP (`100.x.y.z`) or MagicDNS name.
3. Keep the API on `127.0.0.1:8000`. Use Tailscale Serve / subnet router **or** bind `0.0.0.0` only on the tailnet interface if you know what you are doing.
4. Mobile Settings → **Remote access** → URL `http://100.x.y.z:8000` (or `https://…` if you terminate TLS) + the same owner secret.

```bash
# On the API host (example)
tailscale up
tailscale ip -4
# Point phone at http://<tailscale-ip>:8000 with X-Owner-Secret
```

## Option B — Cloudflare Tunnel

1. Install `cloudflared` and authenticate.
2. Create a tunnel that maps a hostname to `http://127.0.0.1:8000`.
3. Keep `REMOTE_ACCESS_ENABLED=1` + owner secret; do **not** skip the secret because Cloudflare is in front.
4. Mobile Remote URL = `https://your-tunnel-host.example`.

```bash
cloudflared tunnel login
cloudflared tunnel create gamma-r
cloudflared tunnel route dns gamma-r api.example.com
# config.yml ingress → http://127.0.0.1:8000
cloudflared tunnel run gamma-r
```

## Option C — SSH tunnel

From your laptop (or a jump host you can reach from the phone via another hop):

```bash
ssh -N -L 8000:127.0.0.1:8000 user@api-host
# Mobile / Simulator → http://127.0.0.1:8000 + owner secret
```

For a phone, prefer Tailscale; SSH local forward is best for desktop/simulator.

## Mobile

Settings → **Remote access**:

- Toggle **Use remote URL**
- Set **Remote API URL** (Tailscale / Cloudflare / tunnel)
- Set **Owner secret** (SecureStore; sent as `X-Owner-Secret` only)
- **Test connection** → `GET /remote/status` + `POST /remote/session`

When remote is enabled, all API calls use the remote base URL.

## Security rules

| Rule | Behavior |
|------|----------|
| No remote without secret | Non-loopback bind **or** `REMOTE_ACCESS_ENABLED` / `remote_access_enabled` → secret required |
| Live stays locked | `LIVE_TRADING_ENABLED` still fail-closed |
| Prefer tunnel | Avoid naked public IP + open port |
| Auth headers only | `X-Owner-Secret` or `Authorization: Bearer` — never `?owner_secret=` |

Smoke: `python scripts/smoke_remote_access.py`

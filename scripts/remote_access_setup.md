# Remote access setup (quick)

Full guide: [`docs/REMOTE_ACCESS.md`](../docs/REMOTE_ACCESS.md)

```bash
export OWNER_SHARED_SECRET='long-random-string'
export REMOTE_ACCESS_ENABLED=1
python -m momentum_bot serve --host 127.0.0.1 --port 8000
```

Then pick one:

1. **Tailscale** — install on host + phone; use `http://100.x.y.z:8000`
2. **Cloudflare Tunnel** — `cloudflared` → `https://your-host` → `127.0.0.1:8000`
3. **SSH** — `ssh -N -L 8000:127.0.0.1:8000 user@host` (desktop/simulator)

Mobile: Settings → Remote access → remote URL + owner secret → Test connection.

Never expose a naked public IP without TLS + owner secret. Live stays locked.

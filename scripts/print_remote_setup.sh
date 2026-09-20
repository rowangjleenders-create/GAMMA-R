#!/usr/bin/env bash
# Print remote-access enable steps (no network changes).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "=== GAMMA-R remote access ==="
echo "Docs: $ROOT/docs/REMOTE_ACCESS.md"
echo
echo "1) export OWNER_SHARED_SECRET='long-random-string'"
echo "2) export REMOTE_ACCESS_ENABLED=1"
echo "3) python -m momentum_bot serve --host 127.0.0.1 --port 8000"
echo "4) Tunnel: Tailscale | Cloudflare Tunnel | SSH -L (prefer tunnel over public IP)"
echo "5) Mobile Settings → Remote access → URL + owner secret → Test connection"
echo
echo "Check: curl -s http://127.0.0.1:8000/remote/status | python -m json.tool"
echo "Session: curl -s -X POST -H \"X-Owner-Secret: \$OWNER_SHARED_SECRET\" http://127.0.0.1:8000/remote/session"

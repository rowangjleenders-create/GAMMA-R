# Host the GAMMA-R backend: comparison + DigitalOcean setup

Signup: https://www.digitalocean.com  
Create a Droplet: DigitalOcean control panel → Create → Droplets  
(Direct: https://cloud.digitalocean.com/droplets/new )

## Comparison (always-on Python bot reachable by phone)

| Option | Monthly cost | Difficulty (1–5) | Free tier? | Always-on background? | Notes |
|--------|--------------|------------------|------------|----------------------|-------|
| **DigitalOcean Droplet** | **~$6** (1 GB / 1 vCPU; $4 is tight) | **2** | New-account credits sometimes | **Yes** | Public IP, full Linux, systemd — best balance |
| **Oracle Cloud Always Free** | **$0** | **4** | Yes (Always Free ARM or 2× AMD micro) | **Yes**, if you get capacity | Hard to provision; idle reclaim risk; more console friction |
| **Render free web service** | $0 | 1 | Yes | **No** — sleeps ~15 min idle, ~1 min wake | Bad for continuous scan/train |
| **Render paid Starter** | ~$7+ | 1–2 | — | Yes | Easy deploy, less OS control |
| **Railway Hobby** | ~$5 usage credit / month | 2 | Limited trial/hobby | Usually yes if not set to sleep | Usage can exceed credit; less ideal for long heavy trains |
| **Home Raspberry Pi + port forward** | ~$0 power (Pi cost upfront) | **4–5** | N/A | Yes on your LAN | CGNAT, dynamic IP, HTTPS/cert, uptime, security on you |

**Recommendation: DigitalOcean Basic Droplet (~$6/mo, 1 GB RAM).** Cheapest *reliable* always-on path with a public IP, firewall UI, and systemd so the bot keeps running. Oracle is the free alternative if you’ll fight the signup/capacity lottery. Avoid Render free for this bot.

---

## Setup guide (DigitalOcean)

### 1) Create the server
1. Sign up at https://www.digitalocean.com → Create → Droplets (or https://cloud.digitalocean.com/droplets/new ).
2. Region near you. Image: **Ubuntu 24.04 LTS**.
3. Size: **Basic → Regular → $6/mo (1 GB / 1 vCPU)**.
4. Auth: SSH key (preferred) or strong password.
5. Create Droplet. Note the **public IPv4** on the Droplet page (e.g. `167.99.x.x`) — that is what the phone will hit (or via a domain).

### 2) Firewall
1. Networking → Firewalls → Create.
2. Inbound: **SSH 22** (your IP only if possible), **HTTP 80**, **HTTPS 443**. Do **not** expose 8000 publicly long-term.
3. Outbound: allow all. Attach firewall to the Droplet.

### 3) SSH in and install Python
```bash
ssh root@YOUR_DROPLET_IP
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git ufw
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable
```

### 4) Upload the bot
From your machine (path may be `/workspace/momentum-bot` on the build box, or your copy):
```bash
scp -r /path/to/momentum-bot root@YOUR_DROPLET_IP:/opt/momentum-bot
```
Or `git clone` if you pushed it to a repo.

On the server:
```bash
cd /opt/momentum-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5) Run as a background service (systemd)
Create `/etc/systemd/system/momentum-bot.service`:
```ini
[Unit]
Description=GAMMA-R API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/momentum-bot
Environment=PATH=/opt/momentum-bot/.venv/bin
ExecStart=/opt/momentum-bot/.venv/bin/python -m momentum_bot serve --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload
systemctl enable --now momentum-bot
systemctl status momentum-bot
```

### 6) HTTPS with Caddy (reverse proxy)
```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
# Install Caddy from official docs, then:
```
Point a domain (optional but best): buy/cheap DNS → A record → Droplet IP.

`/etc/caddy/Caddyfile`:
```
api.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```
Or for IP-only testing without domain, use HTTP on a high port temporarily — **prefer a free domain + Caddy for Let’s Encrypt**.

```bash
systemctl reload caddy
```

### 7) Point the phone app
- With domain: Settings → API base URL = `https://api.yourdomain.com`
- Without domain (dev only): `http://YOUR_DROPLET_IP:8000` only if you open that port in the firewall (weaker). Prefer HTTPS + domain.

### 8) Gotchas
- **Render free sleeps** — phone calls wake it slowly; scanners stop while asleep.
- **Oracle free** — often “out of capacity”; idle VMs can be reclaimed; ARM is fine for Python.
- **Home Pi** — many ISPs use CGNAT (no inbound); you’ll need Tailscale/Cloudflare Tunnel instead of raw port forward.
- **DO $4 (512 MB)** — may OOM during scans/trains; **$6 / 1 GB** is safer.
- **Long historical train** — heavy CPU/RAM/disk; run overnight; checkpoints help if you enabled them.
- **Secrets** — never commit Alpaca keys; use env vars in the systemd unit (`Environment=ALPACA_API_KEY=...`) only when you intentionally enable live later.
- **Cost surprise** — snapshots/backups on DO are extra; turn on only if you want them.

When you’re ready, I can turn this into a one-shot deploy script for the Droplet.

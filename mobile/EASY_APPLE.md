# Easiest way onto your iPhone

Pick **one** path.

> Product name: **GAMMA-R**.

---

## Path A — Today (no $99, 2 minutes)

Best while you’re still setting things up.

1. Install **Expo Go** on your iPhone (App Store).
2. On a computer in the same Wi‑Fi (or with tunnel):
   ```bash
   cd mobile
   npm install
   npx expo start
   ```
3. Scan the QR with your Camera / Expo Go.
4. In the app → **Settings** → paste your API URL (e.g. `http://YOUR_COMPUTER_IP:8000`).

That’s it. Paper automation works once the API is running (`python -m momentum_bot serve`).

---

## Path B — Real app icon (needs Apple Developer ~$99/year)

Only after you’ve enrolled at https://developer.apple.com/programs/enroll/

On a Mac/PC with Node installed:

```bash
cd mobile
npm install
npx eas-cli login
npx eas-cli init          # copy projectId into app.json when asked
./scripts/eas-ios-preview.sh
```

Or one-liner after login/init:

```bash
npx eas-cli build --platform ios --profile preview
```

When the build finishes → open the Expo link → **Install** via TestFlight (EAS will guide you).

Then: open **GAMMA-R** → Settings → API URL.

---

## You only ever flip these yourself

| Flip | When |
|------|------|
| Apple enroll ($99) | Only for Path B |
| `LIVE_TRADING_ENABLED=1` | Only if you want real-money trades (leave off for paper) |
| Alpaca keys | Only if you want SIP / live broker |

Everything else (auto-learn, auto paper-trade) starts when the API server is running.

# Install GAMMA-R on iPhone (private — your device only)

> **Want the short version?** See [EASY_APPLE.md](./EASY_APPLE.md).


This app is built as a real iOS app named **GAMMA-R** (`com.momentumbot.app`) for **you** (single-user / never public App Store distribution required).  
Apple will **not** let an unsigned IPA run on a normal iPhone. You need your own Apple Developer membership to sign and install it.

---

## What you must have (you do this — we do **not** enroll for you)

1. **Apple ID** (the one on your iPhone).
2. **Apple Developer Program** membership — **US$99 / year**  
   Enroll yourself at: https://developer.apple.com/programs/enroll/  
   Approval can take from a few hours up to a couple of days.
3. After enrollment: **App Store Connect** + signing certificates (EAS can create these when you log in).

We will **not** start or pay for that enrollment from this environment.

---

## Build config (already in the project)

| Setting | Value |
|--------|--------|
| Display name | GAMMA-R (`CFBundleDisplayName`) |
| Bundle ID | `com.momentumbot.app` |
| Version | `1.0.0` |
| Scheme | `momentum-bot` |
| Icon / splash | `assets/icon.png`, `assets/splash.png` |
| Mic / speech | `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription` + `expo-speech-recognition` plugin |
| Face ID / Keychain | `NSFaceIDUsageDescription` (SecureStore may prompt) |
| Export compliance | `ITSAppUsesNonExemptEncryption=false` (no custom crypto) |
| Push (optional) | `UIBackgroundModes` includes `remote-notification` |
| SecureStore | `expo-secure-store` plugin (API keys in Keychain) |
| EAS profiles | `development` (sim), `preview` / `production` (device IPA). Android is optional (`preview-android` only). |

---

## Build the IPA (on your Mac/PC, after you enroll)

```bash
cd mobile
npm install
npx eas-cli login          # your Expo account
npx eas-cli init           # paste projectId into app.json → extra.eas.projectId
npx eas-cli build --platform ios --profile preview
```

EAS will ask to manage Apple credentials — use the Apple ID with the $99 membership.  
When finished, download the **.ipa** from the Expo build page.

Optional TestFlight upload:

```bash
npx eas-cli submit --platform ios --profile production --latest
```

---

## Install on your iPhone

### Option A — TestFlight (recommended for you)

1. App Store Connect: create app **GAMMA-R**, bundle ID `com.momentumbot.app` (internal / your account only).
2. Upload IPA (EAS Submit or Transporter).
3. TestFlight → Internal Testing: add **yourself**.
4. iPhone: install **TestFlight** → Install **GAMMA-R**.
5. Open app → **Settings** → set **API server** to your LAN/VPS URL (remembered). Optional `OWNER_SHARED_SECRET` → enter the same secret in Settings.

### Option B — Direct install (Mac + cable)

1. Mac: Xcode or Apple Configurator 2.
2. Connect iPhone, trust computer; register UDID if needed.
3. Install signed IPA; trust your developer certificate under Settings → General → VPN & Device Management.

### Option C — Expo Go (fastest while developing)

No Apple Developer needed. `npx expo start` → scan QR. On-device STT needs a native/EAS build; TTS + E-ve text chat work in Expo Go.

---

## Cost / reality check

| Item | Cost | Who pays |
|------|------|----------|
| Apple Developer Program | ~$99 / year | You |
| Expo EAS free tier | Limited builds | You |
| TestFlight | Included | — |
| Public App Store listing | **Not required** for private use | — |

Without the $99 membership you **cannot** install a standalone IPA on a physical iPhone. Expo Go remains the zero-cost path until you enroll.

---

## After install

1. Run your API: `python -m momentum_bot serve --host 0.0.0.0 --port 8000` (open on LAN; optional `OWNER_SHARED_SECRET`).
2. Settings → **API server** (+ optional owner secret).
3. Paper trading is the default. Live stays locked until you unlock UI **and** set `LIVE_TRADING_ENABLED=1`.

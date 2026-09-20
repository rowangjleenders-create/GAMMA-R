# GAMMA-R — Mobile (Expo)

Dark-mode React Native app (Expo SDK 51) for the GAMMA-R API.

Tabs: **Scan · Paper · Watchlist · Learning · E-ve · Settings**

## End-user install (no terminal)

See **[INSTALL.md](./INSTALL.md)** and the one-tap landing page:

- [`web/install.html`](./web/install.html) — detects iOS vs Android, deep-links to Expo Go stores, placeholders for standalone APK/IPA, `exp://` project open.

### Try the install page locally

```bash
cd mobile
# Option A — open the file directly in a browser
xdg-open web/install.html   # or open web/install.html on macOS / double-click

# Option B — serve statically so phones on your LAN can open it
npx --yes serve web -p 3333
# then visit http://YOUR_LAN_IP:3333/install.html on the phone
# (or: npm run install-page)
```

Paste that URL into the app **Settings → Install** field so the QR code points at it.

---

## Developer setup

```bash
cd mobile
npm install
npx expo start
```

- Default API: `http://localhost:8000`
- Physical device: set API base to your LAN IP in Settings
- Scheme / slug: `momentum-bot` (see `app.json`) — works with Expo Go for JS/TTS; **on-device STT needs a native/EAS build**

### Dependencies of note

| Package | Role |
|---------|------|
| `react-native-qrcode-svg` + `react-native-svg` | Install QR modal in Settings |
| `expo-speech` | E-ve text-to-speech (AVSpeechSynthesizer / Android TTS) |
| `expo-speech-recognition` | E-ve speech-to-text (iOS Speech / Android SpeechRecognizer) |
| `expo-secure-store` | Alpaca keys |
| `expo-notifications` | Push token stub |

---

## E-ve voice mode

- **Mic button** → on-device STT via `expo-speech-recognition` (`requiresOnDeviceRecognition: true` when supported).
- **Replies** → read aloud with `expo-speech`; full transcript always visible.
- **Hands-free** toggle keeps listening after each spoken reply.
- **Interrupt** playback by tapping the mic, tapping a message, or speaking again (`Speech.stop()`).
- Text chat works even when STT native module is missing (e.g. plain Expo Go).

### Permissions (Info.plist / AndroidManifest)

Configured in `app.json`:

| Platform | Keys |
|----------|------|
| **iOS** | `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription` |
| **Android** | `RECORD_AUDIO` |
| **Plugin** | `expo-speech-recognition` config plugin (mic + speech recognition copy) |

Backend: `POST /copilot` (alias `POST /chat`) — local rule/template answers + optional `OPENAI_API_KEY`.
Suggestion chips: scan status · learning summary · explain SIP · fees · paper trading. Buy/sell advice is refused.

---

## EAS Build (private iOS IPA — primary path)

Requires Expo account + **your** Apple Developer membership for device/TestFlight.  
This app is for **you only** — no public store listing required.

```bash
cd mobile
# one-time: eas init   # fills extra.eas.projectId in app.json

eas build --platform ios --profile development   # simulator / dev client (STT)
eas build --platform ios --profile preview       # device IPA → TestFlight
eas build --platform ios --profile production

# Optional Android only if you want it:
eas build --platform android --profile preview-android
```

See **[IOS_INSTALL.md](./IOS_INSTALL.md)**. Profiles in [`eas.json`](./eas.json) are iOS-first.

---

## Settings → Install

Opens a modal with a QR code for `installPageUrl` (editable; stored on device). Default suggestion: your LAN `serve` URL for `install.html`.

## Standalone iOS (no Expo Go)

See **[IOS_INSTALL.md](./IOS_INSTALL.md)** for Apple Developer ($99/yr), EAS IPA build, and TestFlight steps. Android APK is not part of the current release path.

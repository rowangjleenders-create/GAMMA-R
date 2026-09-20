# Install GAMMA-R on your phone

No computer terminal needed. Pick **one** path below.

---

## Quick path (try the app in minutes)

Best when someone already has the project open in Expo on a computer.

1. On your phone, install **Expo Go**
   - iPhone: App Store → search “Expo Go”
   - Android: Play Store → search “Expo Go”
   - Or open the [install landing page](web/install.html) on your phone and tap the store button
2. Ask the person running the project to show the Expo QR code (or open the install page and use the Expo project link).
3. In Expo Go, scan that QR code (or tap the `exp://` link from the install page).
4. When the app opens, go to **Settings**.
5. Set **API** to the address of the GAMMA-R server, for example:
   - Same Wi‑Fi as the computer: `http://192.168.1.10:8000` (use *their* computer’s IP)
   - Cloud / VPS: the `https://…` URL they give you
6. Tap **Save settings**. You’re done.

You can share the install page itself via the in-app **Install** button (QR code) in Settings.

---

## Permanent path (standalone app icon)

Best when you want GAMMA-R like a normal app, without Expo Go.

1. Open the [install landing page](web/install.html) on your phone (link or QR from Settings → Install).
2. Under **Permanent path**, download:
   - **Android:** APK file → open the download → Allow install from this source if asked → Install
   - **iPhone:** IPA / TestFlight link (only available after a developer builds with an Apple Developer account)
3. Open **GAMMA-R** from your home screen.
4. Go to **Settings** and enter the API server address (same as step 5 above).
5. Tap **Save settings**. You’re done.

> If the APK/IPA buttons say “coming soon”, the standalone build has not been published yet — use the **Quick path** until your admin pastes EAS download links into the install page.

---

## What you need from your admin

| Item | Example |
|------|---------|
| Install page link | `http://192.168.1.10:3333/install.html` or a hosted HTTPS URL |
| API server address | `http://192.168.1.10:8000` |
| (Optional) Expo project link | `exp://192.168.1.10:8081` |
| (Optional) APK / IPA | From the install page after EAS publish |

---

## Troubleshooting (still no terminal)

- **App can’t reach the server** — Phone and computer must be on the same Wi‑Fi (or use a public HTTPS API URL). Turn off VPN if it blocks local network.
- **Expo Go won’t open the project** — Confirm the computer’s Expo session is still running; rescan the QR.
- **Android blocks the APK** — Settings → allow installs from that browser/file manager, then try again.
- **iPhone IPA won’t install** — Standalone iOS installs need Apple signing (TestFlight or Ad Hoc). Use Expo Go until that’s set up.

This app is for **educational paper trading**. It is not financial advice.


---

## E-ve voice assistant (optional)

The **E-ve** tab can listen and speak using your phone’s built-in speech engines (no cloud STT/TTS required).

1. Open **E-ve**.
2. Tap the **microphone** and allow mic / speech recognition when asked.
3. Ask a question out loud — you’ll see the transcript and hear the reply.
4. Turn on **Hands-free** to keep listening after each answer.
5. Tap the mic, tap a message, or speak again to **stop** the voice reply.

If the mic says it needs a native build, text chat and spoken replies (text-to-speech) still work; full speech-to-text needs an app build that includes the speech-recognition module (your admin’s EAS / development build).

**Permissions (set by the app):**
- iPhone: Microphone + Speech Recognition
- Android: Microphone (RECORD_AUDIO)

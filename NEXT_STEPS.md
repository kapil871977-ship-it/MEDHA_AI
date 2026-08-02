# Where things stand — 3 Aug 2026

Everything from the audit is **done, verified and pushed** (`origin/master` @ `228be6a`).
This file is the short version of what's finished and what's waiting on you.
The long version is in `AUDIT_REPORT_2026-08-02.md`.

---

## Done

- Backend correctness, security and provider handling — 15+ bugs fixed
- Real native **Android** project (Capacitor 8, targetSdk 36) with branded icons and splash
- Saved-reports feature (`/history`), KP cusp table now rendered, Tezi-Mandi pricing corrected
- Test coverage: **8 → 72 backend**, **1 failing → 8 passing frontend**
- Gemini key verified working end to end (billing enabled, no OpenAI or Claude key needed)

**A debug APK is built and on your Desktop:**

```
C:\Users\Asus\OneDrive\Desktop\FortuneGuru-debug.apk      9.9 MB
```

It has never been run on a real device — that's step 1 below.

---

## 1. Make the APK work (5 minutes)

The app is hard-wired to reach this PC at `http://192.168.1.102:8010`.
Your firewall currently blocks that: the Wi-Fi `BBNL-Sharma_5G 2` is classified
**Public**, and there are two `python.exe` block rules scoped to Public.
Block rules override allow rules, so reclassifying the network is the fix.

Open PowerShell **as Administrator**:

```powershell
Set-NetConnectionProfile -Name "BBNL-Sharma_5G 2" -NetworkCategory Private
New-NetFirewallRule -DisplayName "MEDHA AI backend 8010" -Direction Inbound `
  -LocalPort 8010 -Protocol TCP -Action Allow -Profile Private
```

Then:

1. Start the backend — `start_backend.bat` (leave it running)
2. On your phone, same Wi-Fi, open `http://192.168.1.102:8010/health`
   - JSON returned → you're good
   - Times out → firewall still blocking
3. Copy the APK to the phone and tap it; allow "install from unknown sources"

If your PC's IP changes, update it in
`frontend/android/app/src/debug/res/xml/network_security_config.xml`
and rebuild.

---

## 2. Deploy the backend

Until this is done there is **no shareable APK**, because the server address is
baked in at build time — the current one only works on your Wi-Fi.

You have never deployed (verified: no Render or Vercel service exists). The repo
is already deploy-ready and now on GitHub, which is all Render needs.
Follow `DEPLOYMENT.md` — roughly: Render → New → Blueprint → pick the repo →
set `GOOGLE_API_KEY` and `ALLOWED_ORIGINS` in the dashboard.

Then rebuild the app against it:

```bat
cd C:\Projects\MEDHA_AI\frontend
set REACT_APP_API_URL=https://your-backend.onrender.com
npm run cap:sync
```

---

## 3. Replace the placeholder media

These are **0-byte files** — the app handles them gracefully (avatars fall back to
the logo, voice buttons show a notice) but they do nothing until replaced:

- `frontend/public/guruji/guruji1..10.jpeg` — avatar images
- `frontend/public/guruji/guruji_original.mpeg`, `guruji_cloned.mpeg` — voice clips
- `frontend/public/jagdacharya-swami-akhileshji-maharaj.jpg` and the other
  login-page deity images (absent entirely)

---

## 4. Release build for Play Store

Needs a signing keystore you own and back up **outside** this repo. Losing it means
never being able to update the app again. Full walkthrough in `MOBILE_APP.md`.

```bat
npm run android:bundle     # after creating android/keystore.properties
```

---

## Build environment notes

Set up on 2 Aug 2026 — no Android Studio needed:

| | |
|---|---|
| JDK | `C:\Users\Asus\.jdks\jdk-21.0.12_8` (portable; set `JAVA_HOME`) |
| Android SDK | `%LOCALAPPDATA%\Android\Sdk` — platforms 34 + 36, build-tools 34 + 36 |
| Python | use the **system** `python` (3.11.9); the checked-in venvs point at a path that no longer exists |

Two traps that will bite if you rebuild by hand:
`local.properties` must use forward slashes (it's a Java properties file, so a
single `\` is an escape character), and the JDK folder must not contain a `+`.

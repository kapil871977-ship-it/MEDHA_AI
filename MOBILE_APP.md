# Building the native mobile app (Android & iOS)

Fortune Guru is a React web app. **Capacitor 8** wraps that same web app in a real native
Android and iOS shell you can publish to the **Google Play Store** and **Apple App Store** —
no rewrite.

**The native Android project already exists** at `frontend/android/`. It was generated with
`npx cap add android` and is committed to the repo, so you do not need to create it — just
open it and build.

> Reality check on your setup:
> - You're on **Windows**, so you can build and publish the **Android** app yourself.
> - The **iOS** app can only be *built and submitted from a Mac* with Xcode (Apple's rule).
>   Everything here is iOS-ready, but you'll need a Mac (or a cloud-Mac service) for that step.
> - Publishing costs money: **Google Play** is a one-time **$25**; **Apple** is **$99/year**.

The app is a native shell around your web app, so its screens call your **live backend**.
That means you must deploy the backend (Render) first and build the app pointing at that HTTPS URL —
a phone cannot reach `localhost`.

---

## Prerequisites (install once)

- **Node.js 20+** — you have v24. ✔
- **JDK 21** — required by Capacitor 8 / Android Gradle Plugin.
  Easiest route: install **Android Studio**, which bundles a JDK (JetBrains Runtime).
  Standalone alternative: [Eclipse Temurin JDK 21](https://adoptium.net/temurin/releases/?version=21).
- **Android Studio** (Narwhal or newer) — https://developer.android.com/studio
  Inside its SDK Manager, install **Android SDK Platform 36** and **Build-Tools 36.x**.
  (This machine currently has only SDK 34 installed; the project targets 36.)
- A **physical Android phone** with USB debugging on, or the built-in emulator.
- For iOS only: a **Mac** with **Xcode**.

### Current SDK targets

| Setting | Value | Why |
|---------|-------|-----|
| `minSdkVersion` | 24 (Android 7.0) | Capacitor 8 baseline |
| `targetSdkVersion` | 36 (Android 16) | Google Play requires a recent target API for new releases |
| `compileSdkVersion` | 36 | matches target |

These live in `frontend/android/variables.gradle`.

---

## Build & run the Android app

1. **Build the web app pointing at your live backend**, then copy it into the native project.
   Replace the URL with your Render URL:

   ```bat
   cd C:\Projects\MEDHA_AI\frontend
   set REACT_APP_API_URL=https://medha-ai-backend.onrender.com
   npm run cap:sync
   ```

   `npm run cap:sync` runs the production build **and** `cap sync` in one step.
   Re-run it whenever you change the React code.

   > **The API URL is baked in at build time.** If `REACT_APP_API_URL` is not set, the
   > native app has no server address at all and every screen will report
   > "Server address configure nahi hai". (The `127.0.0.1` fallback is deliberately
   > disabled on device — a phone can never reach your PC's loopback address.)

2. **Open it in Android Studio:**

   ```bat
   npm run cap:android
   ```

   The first open downloads Gradle components — let it finish.

3. **Run it:** click the green ▶ **Run** button and pick the emulator or your phone.

   Or straight from the command line:

   ```bat
   npm run android:run
   ```

---

## Make an installable file / publish to Play Store

### Quick shareable APK

```bat
npm run android:apk
```

Output: `frontend/android/app/build/outputs/apk/release/app-release.apk`
(unsigned unless you set up signing below — Android Studio's
**Build → Build Bundle(s) / APK(s) → Build APK(s)** produces a debug-signed one you can sideload).

### Signed App Bundle for the Play Store

1. **Create a keystore** (once). In Android Studio:
   **Build → Generate Signed Bundle / APK → Android App Bundle → Create new…**

   **Back this file up somewhere safe and outside the repo.** Every future update must be
   signed with the same key; losing it means you can never update the app again.

2. **Wire it up for command-line builds.** Create `frontend/android/keystore.properties`:

   ```properties
   storeFile=C:/keys/fortune-guru-release.jks
   storePassword=your-store-password
   keyAlias=fortuneguru
   keyPassword=your-key-password
   ```

   This file is git-ignored, as are `*.jks` / `*.keystore`. `app/build.gradle` picks it up
   automatically; without it the release build simply stays unsigned.

3. **Build the bundle:**

   ```bat
   npm run android:bundle
   ```

   Output: `frontend/android/app/build/outputs/bundle/release/app-release.aab`

4. **Upload** the `.aab` at the [Google Play Console](https://play.google.com/console)
   (one-time $25), fill in the store listing (name, description, screenshots, privacy
   policy), and submit for review.

---

## App icon & splash screen

Both are already generated and committed. They are produced from a single source image:

```bat
cd C:\Projects\MEDHA_AI\frontend
npm run cap:assets
```

That runs two steps:

1. `python brand-assets/generate_icons.py` — rebuilds the web logo, PWA icons (including
   maskable variants), the favicon, and the native `assets/icon*.png` + `assets/splash*.png`
   sources from `brand-assets/fortune-guru-logo-original.png`.
   Requires Pillow: `pip install Pillow`.
2. `capacitor-assets generate` — expands those into every Android/iOS density.

To rebrand, drop a new high-resolution logo at
`frontend/brand-assets/fortune-guru-logo-original.png` and re-run the command.

---

## What the native shell adds over the plain web app

These are wired up in `frontend/src/App.js` and only activate inside the native app:

- **Hardware back button** — goes back to the home screen instead of instantly closing the app.
- **Status bar** — themed to the app background instead of a clashing default.
- **Splash screen** — branded, hidden automatically once React mounts.
- **Safe-area insets** — content stays clear of the status bar and gesture bar.
- **No service worker** — assets are already on the device; a service worker there would
  serve stale files after an app update.
- **No `window.open`** — a WebView has no tabs, so the kundli opens in place.

---

## iOS (needs a Mac)

```bash
cd frontend
REACT_APP_API_URL=https://medha-ai-backend.onrender.com npm run build
npx cap add ios       # first time only — the ios/ folder is not generated yet
npx cap sync
npm run cap:ios       # opens Xcode
```

In Xcode: set your Apple Developer team, pick a simulator or device, and press ▶.
To publish: **Product → Archive**, then upload to **App Store Connect**.

---

## Updating the app

1. Change your React code.
2. `set REACT_APP_API_URL=... && npm run cap:sync`
3. Bump `versionCode` (must increase every upload) and `versionName` in
   `frontend/android/app/build.gradle`.
4. Rebuild the signed bundle and upload the new version.

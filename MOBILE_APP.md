# Building the native mobile app (Android & iOS)

Fortune Guru is a React web app. **Capacitor** wraps that same web app in a real native
Android and iOS shell you can publish to the **Google Play Store** and **Apple App Store** —
no rewrite. The config is already in the repo (`frontend/capacitor.config.json` and the
Capacitor packages in `frontend/package.json`).

> Reality check on your setup:
> - You're on **Windows**, so you can build and publish the **Android** app yourself.
> - The **iOS** app can only be *built and submitted from a Mac* with Xcode (Apple's rule).
>   Everything here is iOS-ready, but you'll need a Mac (or a cloud-Mac service) for that step.
> - Publishing costs money: **Google Play** is a one-time **$25**; **Apple** is **$99/year**.

The app is a thin native shell around your website, so its screens call your **live backend**.
That means you must deploy the backend (Render) first and build the app pointing at that HTTPS URL —
a phone can't reach `localhost`.

---

## Prerequisites (install once)

- **Node.js 18+** (you likely have this already).
- **Android Studio** — https://developer.android.com/studio (includes the Android SDK + an emulator).
- A **physical Android phone** (optional) with USB debugging on, or use the built-in emulator.
- For iOS only: a **Mac** with **Xcode** from the Mac App Store.

---

## One-time project setup

Open **Command Prompt** and run:

```bat
cd C:\Projects\MEDHA_AI\frontend
npm install
```

This installs Capacitor. Then create the native Android project (and iOS if you're on a Mac):

```bat
npx cap add android
```

(On a Mac, also: `npx cap add ios`)

This generates an `android/` folder — that's your real native project.

---

## Build & run the Android app

1. **Build the web app pointing at your live backend.** Replace the URL with your Render URL:

   ```bat
   set REACT_APP_API_URL=https://medha-ai-backend.onrender.com
   npm run build
   npx cap sync
   ```

   (`cap sync` copies the fresh `build/` into the native project. Re-run these three lines
   whenever you change the app.)

   > Tip: the repo also has a shortcut — `npm run cap:sync` does the build + sync in one step
   > (set `REACT_APP_API_URL` first so it's baked in).

2. **Open it in Android Studio:**

   ```bat
   npm run cap:android
   ```

   Android Studio launches with your project. The first open downloads some components — let it finish (the status bar at the bottom shows progress).

3. **Run it:** click the green ▶ **Run** button and pick the emulator or your connected phone.
   The app launches — this is your real native app.

---

## Make an installable file / publish to Play Store

- **Quick shareable APK** (to sideload on any Android phone): in Android Studio,
  **Build → Build Bundle(s) / APK(s) → Build APK(s)**. It produces an `.apk` you can send to people.
- **For the Play Store**, you need a signed **App Bundle (.aab)**:
  1. **Build → Generate Signed Bundle / APK → Android App Bundle**.
  2. Create a **keystore** (Android Studio walks you through it) — **back this file up safely**;
     you need the same key for every future update.
  3. Upload the `.aab` at the **Google Play Console** (https://play.google.com/console,
     one-time $25), fill in the store listing (name, description, screenshots, privacy policy),
     and submit for review.

---

## iOS (needs a Mac)

On a Mac with Xcode:

```bash
cd frontend
REACT_APP_API_URL=https://medha-ai-backend.onrender.com npm run build
npx cap add ios       # first time only
npx cap sync
npm run cap:ios       # opens Xcode
```

In Xcode: set your Apple Developer team, pick a simulator or device, and press ▶ to run.
To publish: **Product → Archive**, then upload to **App Store Connect** (requires the
$99/year Apple Developer Program).

---

## App icon & splash screen (optional but recommended)

Generate all icon/splash sizes from one image:

```bat
cd frontend
npm install --save-dev @capacitor/assets
```

Put a 1024×1024 PNG at `frontend/assets/icon.png` (and optionally `assets/splash.png` at 2732×2732), then:

```bat
npx capacitor-assets generate
```

It fills in every Android/iOS icon and splash size automatically.

---

## Important notes

- **API URL is baked in at build time.** Always `npm run build` with `REACT_APP_API_URL` set to
  your deployed HTTPS backend before `cap sync`, or the app will try localhost and fail.
- **HTTPS required.** Your Render backend is HTTPS, which Android/iOS require by default — good.
- **Updating the app:** change your React code → rebuild → `cap sync` → rebuild in Android Studio/Xcode
  → upload a new version (bump the version number in the store).
- The `android/` (and `ios/`) folders are part of your project once generated; commit them so the
  native setup is saved.

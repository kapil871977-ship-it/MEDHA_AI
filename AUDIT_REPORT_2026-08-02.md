# MEDHA AI — Audit & Fix Report

_Date: 2026-08-02_ (supersedes the 2026-07-25 report in `AUDIT_REPORT.md`)

## What this app is

**MEDHA AI / Fortune Guru** is an AI-powered Vedic astrology (Jyotish) application. It computes
**real sidereal birth charts** with the Swiss Ephemeris (Lahiri ayanamsa) and uses an LLM to
narrate them in Hindi, Hinglish or English. The astrology maths happens in code; the LLM is
explicitly forbidden from inventing planetary placements.

- **Backend:** Python, FastAPI + Uvicorn, `pyswisseph`, `timezonefinder`, `httpx` — `backend/main.py`
- **Frontend:** React 19 (Create React App) — `frontend/src/App.js`
- **Mobile:** Capacitor 8 native Android project — `frontend/android/`
- **LLM:** OpenAI `gpt-4o-mini` primary, Google Gemini fallback
- **Storage:** SQLite (accounts + saved readings)

### What a user gets

| Feature | Description |
|---------|-------------|
| Kundli analysis | Janam (natal), Gochar (transit) and Prashna (horary) readings, each with all 12 houses — sign, lord, occupants, degrees, nakshatra + pada, dignity |
| Dasha timeline | Vimshottari maha/antar/pratyantar dasha plus a decade-by-decade life map |
| Multi-system engine | Weighted blend of Parashar, KP (cusp sub-lords), Jaimini (Atmakaraka/Karakamsa) and Bhrigu into a confidence score |
| KP cusp table | Per-house nakshatra, nakshatra lord, sub-lord, linked houses, event window |
| Health mapping | Kalpurush body-part mapping and issue tendencies per house, with Dusthana warnings |
| Remedies (Upay) | Mantra / ratan / daan / devata per house |
| Section Q&A | Free-text horary questions; the answer's language auto-matches the question (Hindi / Hinglish / English) |
| Tezi-Mandi | Astrology-driven market signal for commodities & indices, with real historical closes from Yahoo Finance and per-unit price breakdowns |
| Saved reports | Every reading stored server-side per account, readable from any device |
| Accounts | Email/mobile + password, PBKDF2-hashed, HMAC-signed bearer tokens |

### Is it a web app *and* a native Android app?

**Both — as of this session.**

- **Web app:** yes, and it is an installable **PWA** (manifest, icons, offline service worker).
- **Native Android:** yes, now genuinely. Previously the repo had Capacitor *config* and
  dependencies but **`frontend/android/` did not exist and `@capacitor/*` was not installed** —
  so there was no native app, only a claim of one. This session generated the real native
  project, upgraded Capacitor 6 → 8, added the native plugins, and generated branded icons
  and splash screens.
- **iOS:** ready but not generated (`npx cap add ios` requires a Mac).

---

## Critical bugs fixed

### 1. Chart computation crashed on Windows — missing `tzdata`

`zoneinfo` ships no timezone database on Windows (or on slim Linux images). Every call to
`_compute_vedic_chart` raised `ZoneInfoNotFoundError: 'No time zone found with key Asia/Kolkata'`.
**All 8 existing tests errored out** on a clean install.

**Fix:** added `tzdata` to `requirements.txt`, plus a fixed-offset IST fallback so a missing
tz database degrades instead of crashing. Tests: 0 → 8 passing.

### 2. Hindi readings were thrown away and replaced with canned text

`_kundli_payload_has_hinglish()` rejected the payload if it contained **a single Latin
character**. But the prompt *mandates* the Latin self-reference "Guru Ji" and echoes Latin
planet names from the computed chart, and the remedies field is formatted as
`Mantra: … Ratan: … Daan: …`. So for Hindi users the good AI reading was almost always
discarded in favour of the generic fallback — which is why readings looked canned.

**Fix:** the check is now ratio-based (≥60% Devanagari after removing an allow-list of
expected proper nouns). Verified against live Gemini output: the AI response is now kept
(`system_note` empty) where it was previously always replaced.

The same over-strict rule in `_answer_matches_style()` forced a redundant second LLM call
on nearly every Hindi Q&A answer; fixed the same way.

### 3. Self-reference normalizer corrupted ordinary text

`_normalize_self_reference` replaced `\bmodel\b`, `\bAI\b`, `\bassistant\b`, `\bpandit\b` etc.
anywhere in the output — turning "role model" into "role Guru Ji" — and ran over computed
chart data too.

**Fix:** narrowed to actual self-disclosure phrases ("as an AI language model", "main ek AI")
plus honorific aliases, and added a skip-list so `chart_summary` and engine output are never rewritten.

### 4. Gemini fallback was broken — model retired

The configured model `gemini-2.5-flash` returns
`NotFound: no longer available to new users`, even though `list_models()` still lists it.
The preference list was stale, and `list_models()` also returns image/TTS/robotics/music
models that cannot do this work.

**Fix:** refreshed the preference list, added a denylist for non-text models, and made
generation **self-healing** — on a "model unavailable" error it advances to the next
candidate instead of failing the request. Now selects `gemini-flash-latest`.

### 5. `/kundli-analysis` refused to work without an LLM key

It returned `{"error": …}`, even though the chart, 12 houses, dasha timeline and KP/Jaimini
analysis are all computed locally and need no LLM at all.

**Fix:** the endpoint now returns the complete computed reading with an explanatory note.
Verified: 12 houses, correct lagna and dasha, with both LLM keys unset.

### 6. Server timeouts exceeded the client's — fallbacks never delivered

`MODEL_TIMEOUT_SECONDS` defaulted to 150s while the browser aborts at 70s, so the server's
graceful fallback could never reach the user.

**Fix:** defaults are now 60s general / 70s kundli, both under the client limits, and
`.env.example` documents the constraint. (`.env.example` had also advertised 300s, and
described Gemini as the primary provider when the code uses OpenAI.)

### 7. Frontend smoke test asserted an element that never existed

`App.test.js` asserted `container.querySelector('h1')` is non-null, but `LoginPage` renders
only `h2`. **The one frontend test was failing.**

**Fix:** the "Fortune Guru" banner is now a real `<h1>` (one per page, correct heading
order), and the suite was expanded from 1 test to 8 covering login, sign-up, session
validation, 401 handling and form validation.

---

## Security fixes

| Issue | Fix |
|-------|-----|
| `/auth/login` and `/auth/signup` had **no rate limit** — passwords were freely brute-forceable | Separate auth bucket, `AUTH_RATE_LIMIT_PER_MINUTE` (default 10). Verified: 3 allowed → 429 |
| `/auth/me` took the token as a **URL query parameter**, leaking it into server logs, proxy logs and browser history | Now reads `Authorization: Bearer`; query param retained only for backwards compatibility |
| Expired/invalid sessions showed the full app until the first API call failed | Session is verified against `/auth/me` on start-up; invalid sessions are cleared and redirected to login |
| Rate-limit map grew without bound (memory leak) | Expired keys are pruned once the map passes 10k entries |
| Android signing keystores were **not git-ignored** (Capacitor leaves those lines commented out) | `*.jks`, `*.keystore`, `keystore.properties` ignored in both `.gitignore` files |

Saved-report access is scoped per account and tested: another account gets **404** on read
and delete, never another user's data.

---

## Correctness fixes

- **Atmakaraka was computed wrongly.** Jaimini defines it as the planet with the highest
  degree *within its own sign* (0–30°); the code used the highest **absolute** longitude
  around the zodiac, which gives a different planet almost every time.
- **Polar births crashed the app.** `swe.houses(..., b"P")` (Placidus) is undefined beyond
  the polar circles and raises. Now falls back to whole-sign. Verified with Svalbard
  (78.2°N): was a 500, now returns 12 houses.
- **Equatorial coordinates were dropped.** The frontend used `formData.lat ? … : null`, so
  a latitude or longitude of exactly `0` was sent as `null`. Now an explicit null check.
- **Tezi-Mandi dates were off by one for Indian users.** `toISOString()` returns the *UTC*
  date, so before 05:30 IST "Aaj" meant yesterday. Now formatted from local date parts.
- Yahoo Finance window timestamps are anchored to UTC instead of the server's local timezone.
- `datetime.utcfromtimestamp` (deprecated) replaced with timezone-aware equivalents.

---

## Performance fixes

- **`TimezoneFinder()` was constructed on every chart computation**, loading its polygon
  dataset each time — and `/kundli-analysis` builds two charts per request. Now a lazy
  module-level singleton.
- **25 MB of images shipped in every build.** `medha-logo.png`, `medha-bold-logo.png`,
  `medha-vedic-logo.png` (≈19 MB) and `bell.mp3` were **referenced nowhere** in the code,
  and `fortune-guru-logo.png` was a 6.4 MB / 2816×1536 PNG rendered as a 120 px avatar.
  Unused originals moved to `frontend/brand-assets/` (kept, not deleted); the served logo
  is regenerated at 512 px. **`public/` went from 25 MB → 701 KB.**

---

## Gaps completed

- **Native Android app** — Capacitor 6 → 8 (targets SDK 36, meeting current Play Store
  requirements), `frontend/android/` generated, `@capacitor/app` + `status-bar` +
  `splash-screen` installed and wired up: hardware back button navigates in-app instead of
  quitting, status bar themed, splash auto-hidden, safe-area insets applied.
- **Native-hostile web code fixed** — `window.open('_blank')` cannot work in a WebView (no
  tabs; it would bounce to the system browser where the session doesn't exist), and the
  hard-coded `http://127.0.0.1:8010` fallback burned a full timeout on every phone request.
  Both are now gated on the platform, with a clear error if `REACT_APP_API_URL` is unset.
- **Service worker disabled inside the native shell**, where it only serves stale files
  after an app update.
- **Branded icons** — PWA icons were still the default Create React App React logo.
  `brand-assets/generate_icons.py` now produces the web logo, PWA icons (with proper
  separate `maskable` entries — the old manifest used the deprecated `"any maskable"`),
  favicon, and native icon/splash sources; `capacitor-assets` expands them to 136 Android files.
- **Saved kundli history** (listed as pending in the previous report) — `/history` GET/DELETE
  endpoints, auto-save on every reading, per-account scoping, pruning, and a **Saved Reports** UI.
- **KP cusp table was computed and discarded.** The backend built a full 12-cusp sub-lord
  table for every section; the frontend extracted it into unused variables (three ESLint
  `no-unused-vars` errors that broke `CI=true npm run build`). Now rendered as an
  expandable table.
- **Unreachable UI** — the `#remedies` route had no link anywhere in the app; there was no
  way back to Home from the kundli page. Both now have navigation.
- **Broken media handling** — every file in `public/guruji/` is a 0-byte placeholder, so
  avatars showed broken images and `audio.play()` produced an unhandled promise rejection
  with the UI stuck in a permanent "speaking" state. Avatars now fall back to the logo and
  audio failures show a message.
- **Test coverage** — 8 chart tests → **43 backend + 8 frontend**, covering auth, endpoint
  protection, rate limiting, history isolation, and the language helpers. `conftest.py`
  ensures tests use a temp DB and never touch the real `users.db` or call a real LLM.

---

## Verification

| Check | Result |
|-------|--------|
| `python -m pytest` (backend) | **43 passed** |
| `npm test` (frontend) | **8 passed** |
| `CI=true npm run build` | **Compiled successfully**, no warnings |
| Live API smoke test (15 checks) | **15/15 passed** |
| Real Gemini generation | Hindi kundli kept (not replaced), 12 houses, section Q&A answered |
| Browser walkthrough | Sign-up → form → kundli → KP table → Saved Reports, no console errors |
| `npx cap add android` + `cap sync` | Native project created, 3 plugins detected, web assets synced (2.1 MB) |

Live smoke test covered: health, 401 on unauthenticated access, signup, `/auth/me`,
12-house kundli, lagna/dasha, KP cusp table, history list/get/delete, cross-account 404,
Tezi-Mandi historical close (real Yahoo data), `lat=0/lng=0`, and polar latitude.

---

## Round 2 — full feature test with 10 real celebrity charts

Ten public figures were used to exercise the engine across timezones (IST, HST,
PST, CET, BST), DST boundaries, and a 1869–1973 date range: Gandhi, Einstein,
Marilyn Monroe, Lata Mangeshkar, Amitabh Bachchan, Narendra Modi, Steve Jobs,
Barack Obama, Diana Spencer, Sachin Tendulkar.

### Bug — pre-standard-time births got the wrong ascendant 🔴

Gandhi's chart came out with a **Virgo** ascendant; his chart is published
everywhere with **Libra (Tula)**.

India had no standard time in 1869, so the IANA zone `Asia/Kolkata` falls back
to Calcutta's mean time (HMT, +5:53:20). Applying a Calcutta offset to a
**Porbandar** birth (69.63°E, true local mean time +4:38:31) is **75 minutes
fast** — and at ~1° of ascendant per 4 minutes that is ~19°, a whole sign.

Standard-time offsets are always whole multiples of 15 minutes; mean-time
offsets are not. The engine now uses that to detect the pre-standard era and
substitutes the birth longitude's own mean solar time. Gandhi now computes
Libra, matching the published chart. Einstein (1879 Ulm, 13.5 min error) is
corrected the same way.

Modern births are untouched — verified explicitly for Hawaii (−10:00), Pacific
(−08:00), IST (+05:30), British Summer Time (+01:00) and India's 1942 wartime
+06:30 offset, all of which are valid quarter-hour offsets.

### Bug — Gemini model choice hit a 20-requests/day ceiling 🟠

The model reordering from round 1 selected `gemini-flash-latest`, which Google
resolves to `gemini-3.6-flash` — free-tier quota **20 requests/day**. The app
exhausted it almost immediately. Preference order now leads with the
established high-quota Flash models.

### Bug — a quota refusal burned 164 seconds 🟠

On HTTP 429 the SDK retried internally with backoff, so a single request took
**164s** to fail and then reported a misleading *"timeout"*. The per-request
deadline is now bounded, quota errors are detected explicitly, and the engine
**switches to the next candidate model** instead of giving up — 4 models are
now tried in **1.4s**. Quota-exhausted models are rotated (they reset);
withdrawn models are retired permanently.

User-facing messages now distinguish *quota exhausted* from *timed out*, and
`/health` reports the active model, remaining candidates and the last provider
error so a degraded install is diagnosable without reading logs.

### Verified

| Suite | Result |
|-------|--------|
| Astronomy vs external references + invariants | **43/43** |
| Functional sweep, 10 celebrities, all endpoints | **914/914** |
| Android project / bundle / native code paths | **56/56** |
| Backend unit + API tests | **57 passed** |
| Frontend tests | **8 passed** |

The astronomy suite checks the Lahiri ayanamsa against its published J2000
value (23.85°), precession rate (50.3″/yr), the tropical Sun at the March
equinox, Ketu's exact 180° opposition, the 120-year Vimshottari total, KP
sub-lord spans summing to one nakshatra, navamsha mapping, dasha contiguity and
ordering, and re-derives every celebrity's Sun longitude independently from raw
Swiss Ephemeris calls.

The functional sweep validates, per celebrity: all 9 grahas with valid
sign/house/nakshatra/degree, 12 houses consistent across all three reading
blocks *and* the chart summary, whole-sign house sequencing, house-occupancy
agreement, decade predictions, KP cusp tables, Atmakaraka correctness
(highest degree-within-sign), history isolation between accounts, and
Tezi-Mandi across 10 instruments.

### Bug — model preference was wrong for newly-issued API keys 🔴

Testing the key directly showed the round-2 ordering was backwards for it.
`list_models()` lists models that then return **404 "no longer available to new
users"** on the first real call, so it is not an availability signal. Which
models a key may use depends on **when the key was issued**:

| Model | This key (`AQ.` format) |
|-------|------------------------|
| `gemini-2.0-flash`, `-001`, `-lite` | **404** |
| `gemini-2.5-flash`, `-flash-lite`, `-pro` | **404** |
| `gemini-flash-latest` | works |
| `gemini-3.6-flash`, `gemini-3.5-flash` | works |
| `gemini-flash-lite-latest`, `gemini-3.1-flash-lite` | works |
| `gemini-pro-latest` | works |

Round 2 had put the entire Gemini 2.x family first. Combined with a
per-request cap of **4** candidate attempts, a request could spend all four
attempts on instant 404s and fail **even though working models sat further
down the list** — which is exactly what produced the `DeadlineExceeded`
fallbacks seen during the celebrity test.

Fixed by leading with the maintained `-latest` alias (which follows Google's
current best Flash model and survives retirements automatically), then current
explicit versions, then the lite variants as a higher-quota fallback, then the
2.x family for older keys. The attempt cap is now 10, since 404s are free,
sub-second, and the wall-clock deadline is enforced separately every iteration.

Result: the app now selects a working model at startup and generates in ~2s
instead of exhausting its attempts.

### Timeout budget was too tight for a real generation

With the key working, a full Hindi kundli measured **69.9 s against a 70 s
budget** — a coin flip that discarded good readings on timing jitter alone.
Budgets widened to 90 s server / 105 s client for the kundli, 75 s / 90 s
elsewhere (server always below client so the graceful fallback can be
delivered), and the loading screen now says 60–90 seconds.

Verified after the fix: full AI kundli generated and **kept** — 997 characters,
772 Devanagari, 0 Latin, all three sections distinct, house predictions and
mantra/ratan/daan remedies in proper Hindi, chart intact.

### Note on the Gemini key in `backend/.env`

The key is **valid and working** — it authenticates, and full AI kundli
generation succeeds end to end in Hindi. Two things to know about it:

- It is a **new-format key** (`AQ.` prefix, 53 chars), so it can only use
  current-generation models; the whole Gemini 2.x family returns 404 for it.
  The app now handles that automatically.
- It is on the **free tier**, where `gemini-3.6-flash` allows only
  **20 requests/day**. That is roughly 10 kundli readings per day (each page
  load calls `/kundli-analysis` and `/full-analysis`). Once exhausted, every
  reading falls back to the computed chart until the daily reset.

No `OPENAI_API_KEY` is set. Since OpenAI is the primary provider, setting one
would both remove the daily ceiling and skip the Gemini fallback entirely.

---

## Not done — needs you

1. **Compile the APK.** This machine has **no JDK** and only **Android SDK 34** (the project
   targets 36), so the Gradle build could not be run here. Everything up to that point is
   verified. Install Android Studio (bundles JDK 21) + SDK 36, then `npm run cap:android`.
   Full steps in `MOBILE_APP.md`.
2. **Replace the 0-byte placeholder assets** in `frontend/public/guruji/` — 10 avatar images
   and 2 voice files. The app degrades gracefully without them, but the avatar cycling and
   voice buttons do nothing until real files are dropped in.
3. **Login-page deity images** (`jagdacharya-…jpg`, `shiv-parivar.png`, `lakshmi-narayan.png`)
   are still absent and fall back to the logo. These are specific photos only you can supply.
4. **Rotate the Gemini key** in `backend/.env` if it was ever committed or shared, and set
   `AUTH_SECRET_KEY` so logins survive restarts.
5. **iOS project** — run `npx cap add ios` on a Mac.
6. **LLM capacity.** The configured Gemini key is on an exhausted free tier and there is no
   OpenAI key. Every reading currently falls back to the computed chart. Set `OPENAI_API_KEY`
   (OpenAI is the primary provider) or move the Google key to a paid plan. Check
   `GET /health` — `last_llm_error` will name the exact problem.

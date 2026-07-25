# MEDHA AI — Audit & Fix Report

_Date: 2026-07-25_

## What this app is

**MEDHA AI** is an AI-powered Vedic astrology (Jyotish) web application. It computes
**real sidereal birth charts** using the Swiss Ephemeris (Lahiri ayanamsa) and uses an LLM
to write chart-grounded interpretations in Hindi, Hinglish, and English. The astrology math
is done in code; the LLM only narrates the computed data (it is explicitly forbidden from
inventing planetary placements).

- **Backend:** Python, FastAPI + Uvicorn, `pyswisseph`, `timezonefinder`, `httpx`. Single file: `backend/main.py` (~3,390 lines).
- **Frontend:** React 19 (Create React App). Single file: `frontend/src/App.js` (~1,590 lines).
- **LLM:** OpenAI `gpt-4o-mini` (primary) with Google Gemini `gemini-2.5-flash` fallback.
- **External:** OpenStreetMap Nominatim (geocoding), Yahoo Finance (price history).
- **Storage:** none — stateless; the frontend caches to `localStorage`.

## Features

1. **Kundli analysis (Trividha Kundli)** — Janam (natal), Prashna (horary), and Gochar (transit)
   readings. Builds all 12 houses (sign / lord / occupants), Vimshottari Dasha timeline (current
   maha/antar/pratyantar + decade-by-decade mapping), navamsha, nakshatra/pada, and dignities.
2. **Multi-system engine** — a weighted rule engine blending Parashar, KP (cusp sub-lords),
   Jaimini (Atmakaraka/Karakamsa), and Bhrigu signals into a confidence score.
3. **Full-analysis ("Guru Ji" reading)** — long-form 8-section life reading tied to the chart.
4. **Section Q&A** — free-text horary follow-ups with automatic Hindi/Hinglish/English style detection.
5. **Tezi-Mandi market prediction** — astrology-driven forecast/history for commodities & indices
   (Gold, Silver, Crude, Nifty, etc.), combining `engine_config.json` rules with Yahoo Finance closes.
6. **"Guru Ji" persona** — avatar cycling and voice assets; self-reference is normalized to "Guru Ji".

## Bugs found & fixed

### 1. CRITICAL — `/kundli-analysis` crashed on every request (500)
The app's primary endpoint used five variables that were **never defined** in its scope:
`computed_houses`, `multi_system_natal`, `multi_system_gochar`, `multi_system_prashna`, and the
prompt-local `maha` / `antar`. A `NameError` was raised before the `try` block, so the endpoint
returned HTTP 500 every time — the core kundli feature never worked (users only ever saw the
"could not load" error or a stale cached report).

**Fix:** after chart computation, the endpoint now derives these:
- `computed_houses = _build_computed_houses(chart, language)`
- `maha` / `antar` from the computed dasha
- a live **transit chart** for the current moment
- `multi_system_{natal,gochar,prashna} = _multi_system_analysis(...)` for each mode

Both the LLM-success path and the LLM-failure fallback path were verified to return a complete
12-house payload (Hindi and English).

### 2. HIGH — OpenAI-only setups were refused
`/full-analysis`, `/section-qa`, and `/kundli-analysis` gated on `if model is None` (Gemini only)
and returned "GOOGLE_API_KEY missing". But per the README **OpenAI is the primary provider**, so a
valid OpenAI-only configuration was rejected even though generation would have worked.

**Fix:** gates now check `if model is None and openai_client is None`, and the message references
either key. `/health` now reports `openai_configured`, `gemini_configured`, and `llm_available`.

## Verification

- `python -m py_compile main.py` → OK
- `pytest` → **8 passed** (chart computation, lagna, grahas, ayanamsa, dasha, house builder)
- Runtime test of `/kundli-analysis` (LLM-failure path) → 12 houses returned, multi-system present, HI + EN
- Runtime test of `/kundli-analysis` (LLM-success path with valid JSON) → normalized 12 houses + decade timeline
- Frontend `App.js` → braces balanced; API contract matches backend output

## Notes / non-blocking observations

- `backend/.env` is present in the working tree but correctly ignored by `.gitignore`. If any key
  in it was ever pushed to a remote, rotate it.
- README states `MODEL_TIMEOUT_SECONDS` default is 300; the code default is 150. Cosmetic doc mismatch only.
- Frontend references optional image assets (e.g. `shiv-parivar.png`, guru portraits) that may be
  absent; these degrade gracefully via `onError` fallbacks to `fortune-guru-logo.png`.
- No `TODO`/`FIXME`/stub markers remain in first-party source.

## Enhancement — real authentication (replaces the fake login)

The previous login accepted any email/password and just set a `localStorage` flag. It has been
replaced with genuine credential-based auth, using **only the Python standard library** (no new
dependencies, no external database service):

- **Passwords** are stored as PBKDF2-HMAC-SHA256 hashes (200k iterations, per-user salt) in a
  local SQLite file `backend/users.db` — never in plaintext.
- **Tokens** are stateless, HMAC-SHA256-signed, and carry an expiry (default 30 days).
- **New endpoints:** `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`.
- **Frontend:** the login screen now has a Login/Sign-up toggle, calls the real endpoints, stores
  the returned token, shows server errors, supports Enter-to-submit, and clears the token on logout.
- **Config:** set `AUTH_SECRET_KEY` in `backend/.env` so tokens survive restarts (documented in
  `.env.example`); `backend/users.db` and `*.db` are git-ignored.

Verified with 10 scenarios: signup, duplicate-signup rejection, short-password rejection, correct
login, wrong-password rejection, unknown-user rejection, token verification, tampered-token
rejection, expired-token rejection, and confirmation that stored passwords are hashed.

_Note:_ this makes the login real (credentials are verified). The astrology endpoints themselves
are not yet token-gated server-side — a reasonable next hardening step, since they expose no
per-user data today.

## Hardening — server-side protection, CORS, rate limiting

Building on the auth work, the API is now actually protected (not just the UI):

- **Server-side token gate.** `/kundli-analysis`, `/full-analysis`, `/section-qa`, and
  `/tezi-mandi` now require a valid `Authorization: Bearer <token>` header (returns **401**
  otherwise). Controlled by `AUTH_ENFORCE` (default `true`; set `false` for anonymous/local use).
  The frontend attaches the token automatically and, on a 401, clears the session and redirects
  to login.
- **Configurable CORS.** `ALLOWED_ORIGINS` (comma-separated) replaces the hard-coded `"*"`;
  defaults to `"*"` for dev, lock it down in production.
- **Rate limiting.** In-memory sliding-window limit per client IP on the heavy endpoints,
  `RATE_LIMIT_PER_MINUTE` (default 30, `0` disables) — returns **429** when exceeded.
- **Docs.** README env table corrected (timeout defaults were wrong; provider roles clarified —
  OpenAI primary, Gemini fallback) and all new env vars documented, plus an Accounts section.

Verified via FastAPI TestClient: no-token → 401, valid-token → 200, tampered-token → 401,
rate limit → `[200,200,200,200,200,429,429]` at a limit of 5, and anonymous access → 200 when
`AUTH_ENFORCE=false`.

## Enhancement — installable PWA (Progressive Web App)

The app is now installable to a phone/desktop home screen and launches standalone (no browser
chrome), while remaining the same web app:

- `frontend/public/manifest.json` — real app name ("MEDHA AI — Fortune Guru"), icons (192/512 +
  maskable), standalone display, portrait, branded theme/background colors.
- `frontend/public/service-worker.js` — offline support: network-first for navigations with an
  app-shell fallback, cache-first for static assets. Only caches same-origin GET requests, so the
  backend API is never cached.
- `frontend/src/index.js` — registers the service worker in production builds only.
- `frontend/public/index.html` — branded title/description, `theme-color`, and Apple
  web-app meta tags for iOS "Add to Home Screen".

To use it: run `npm run build` and serve the `build/` folder over **HTTPS** (PWAs require HTTPS,
except on `localhost`). Chrome/Edge then show an "Install" icon in the address bar; iOS Safari
uses Share → "Add to Home Screen". _Note: the production `npm run build` should be run in your
environment — it could not be run to completion in the audit sandbox, though all PWA files were
syntax-validated and the project builds with the standard CRA toolchain._

## Deployment prep (Render backend + Vercel frontend)

The app is now deploy-shaped for Render (API) and Vercel (frontend):

- `backend/main.py` — bind host is configurable via `HOST` (defaults to `0.0.0.0` so cloud
  hosts can reach it); `AUTH_DB_PATH` is configurable so the user DB can live on a persistent disk.
- `render.yaml` — Render Blueprint: Python 3.11.9, `pip install`, `uvicorn main:app`, health check
  at `/health`, auto-generated `AUTH_SECRET_KEY`, and placeholders for the LLM keys + `ALLOWED_ORIGINS`.
  Includes commented-out persistent-disk config for durable accounts.
- `backend/.python-version` — pins Python 3.11.9.
- `frontend/vercel.json` — CRA framework preset, SPA rewrites, and a no-cache header for the
  service worker.
- `DEPLOYMENT.md` — full step-by-step: deploy backend → set keys → deploy frontend with
  `REACT_APP_API_URL` → set `ALLOWED_ORIGINS` to the Vercel URL → verify.
- `backend/.env.example` — documents `HOST` and `AUTH_DB_PATH`.

Verified: backend compiles, `render.yaml` is valid YAML, `vercel.json` is valid JSON, and the
`AUTH_DB_PATH`/`HOST` overrides work (signup writes to the custom DB path).

_Still to run in your environment:_ push to GitHub, click through the Render + Vercel steps in
`DEPLOYMENT.md`, and (for production accounts that survive redeploys) enable the Render persistent
disk or move auth to Postgres.

## Remaining (needs your input — not code-fixable by me)

- **Login-page deity images** (`jagdacharya-…jpg`, `shiv-parivar.png`, `lakshmi-narayan.png`) are
  still absent and fall back to the logo. These are specific photos you'll need to supply — drop
  them into `frontend/public/` with those names and they'll appear automatically.
- **Persistent kundli history** across devices would require storing readings server-side (the
  auth SQLite DB is now a natural home for this) — a feature build rather than a fix.
- **Frontend Jest smoke test** (`npm test`) should be run in your environment (needs `npm install`).

## Files changed

- `backend/main.py` — defined missing kundli variables; fixed provider gating; enriched `/health`;
  added the authentication module + `/auth/*`; added server-side token gate, configurable CORS,
  and per-IP rate limiting.
- `frontend/src/App.js` — real login/signup flow with token storage; sends bearer token on every
  API call; handles 401 (re-login) and 429; token-based logout.
- `backend/.env.example` — documented `AUTH_SECRET_KEY`, `AUTH_TOKEN_TTL_SECONDS`.
- `README.md` — corrected env table and added Accounts + new config vars.
- `.gitignore` — ignore `backend/users.db` / `*.db`.

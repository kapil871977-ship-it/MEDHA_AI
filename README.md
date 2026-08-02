# MEDHA AI

AI-powered Vedic astrology (Jyotish) web application. It computes real sidereal birth charts with the Swiss Ephemeris and uses an LLM to write personalized, chart-grounded interpretations in Hindi, Hinglish, and English. It also includes **Tezi-Mandi**, an astrology-based market/commodity prediction module that blends a KP rule engine with live historical price data.

## Features

- **Kundli analysis** — Janam (natal), Prashna (horary), and Gochar (transit) charts. Builds 12 houses with signs/lords/occupants and a Vimshottari Dasha timeline. AI interpretations are constrained to the computed chart so the model cannot invent placements.
- **Tezi-Mandi market prediction** — astrology-driven forecasts for commodities/indices (Gold, Silver, Crude Oil, Nifty, etc.), combining a configurable rule engine (`backend/engine_config.json`) with historical close prices from Yahoo Finance.
- **Section Q&A** — free-text follow-up questions per section, with Hindi/Hinglish/English style detection.
- **KP cusp sub-lord analysis** — per-house nakshatra, nakshatra lord, sub-lord, linked houses and the current event window, shown in every kundli section.
- **Saved reports** — every reading is stored server-side against your account, so your history follows you across devices (browser, phone, tablet).
- **"Guru Ji" persona** — avatar and voice assets under `frontend/public/guruji/`.
- **Installable app** — a PWA in the browser and a real native **Android** app (Capacitor 8) in `frontend/android/`. See `MOBILE_APP.md`.

## Tech stack

| Layer    | Technology |
|----------|-----------|
| Backend  | Python, FastAPI + Uvicorn, Swiss Ephemeris (`pyswisseph`), `timezonefinder`, `httpx` |
| LLM      | OpenAI `gpt-4o-mini` (primary), Google Gemini (fallback, auto-selects the best available Flash model) |
| Frontend | React 19 (Create React App) |
| Mobile   | Capacitor 8 (native Android shell, iOS-ready) |
| External | OpenStreetMap Nominatim (geocoding), Yahoo Finance (price history) |
| Storage  | SQLite (`backend/users.db`) — accounts and saved readings |

## Prerequisites

- Python 3.11+
- Node.js 20+
- An OpenAI API key (primary) and/or a Google Gemini API key (fallback)

The astrology engine itself needs no API key: charts, houses, dasha timeline and the
KP/Jaimini analysis are all computed locally from the Swiss Ephemeris. Without an LLM key
the app still returns a complete chart-based reading — only the AI-written prose is skipped.

## Setup

1. **Configure secrets.** Copy the example env file and add your keys:

   ```bat
   copy backend\.env.example backend\.env
   ```

   Edit `backend\.env` and set `GOOGLE_API_KEY` (and optionally `OPENAI_API_KEY`).

2. **Install dependencies.** Run the setup script (creates the backend venv, installs Python deps, scaffolds the frontend if missing):

   ```bat
   setup.bat
   ```

   Or manually:

   ```bat
   cd backend
   python -m venv venv
   venv\Scripts\activate.bat
   pip install -r requirements.txt
   cd ..\frontend
   npm install
   ```

## Running

Start both backend and frontend together:

```bat
run_medha.bat
```

This launches the FastAPI backend on **http://127.0.0.1:8010** and the React frontend on **http://localhost:3000**.

To start the backend alone:

```bat
start_backend.bat
```

The frontend talks to the backend at `http://127.0.0.1:8010` by default; override with the `REACT_APP_API_URL` environment variable.

## Environment variables

At least one LLM key (`OPENAI_API_KEY` **or** `GOOGLE_API_KEY`) must be set. OpenAI is the
primary provider; Gemini is the fallback.

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | One of the two | OpenAI key (primary LLM, `gpt-4o-mini`) |
| `GOOGLE_API_KEY` | One of the two | Google Gemini key (fallback LLM) |
| `OPENAI_MODEL` | No | OpenAI model name (default `gpt-4o-mini`) |
| `MODEL_TIMEOUT_SECONDS` | No | LLM call timeout (default 60) |
| `KUNDLI_MODEL_TIMEOUT_SECONDS` | No | Kundli-specific LLM timeout (default 70) |
| `HOST` | No | Bind host (default `0.0.0.0`; use `127.0.0.1` for local-only) |
| `PORT` | No | Backend port (default 8010) |
| `AUTH_DB_PATH` | No | SQLite path for accounts + saved readings (default `backend/users.db`) |
| `AUTH_SECRET_KEY` | No | Secret for signing auth tokens. Set it so logins survive restarts; random per-process if unset |
| `AUTH_TOKEN_TTL_SECONDS` | No | Auth token lifetime (default 2592000 = 30 days) |
| `AUTH_ENFORCE` | No | Require a valid token on the astrology/market endpoints (default `true`; set `false` to allow anonymous access) |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS allow-list (default `*`). Lock this down in production |
| `RATE_LIMIT_PER_MINUTE` | No | Max requests per client IP on heavy endpoints (default 30; `0` disables) |
| `AUTH_RATE_LIMIT_PER_MINUTE` | No | Max requests per client IP on `/auth/login` and `/auth/signup` — this is what stops password brute-forcing (default 10; `0` disables) |
| `KUNDLI_HISTORY_LIMIT` | No | Saved readings kept per account (default 20; oldest pruned) |

> **Timeouts must stay below the frontend's own limits** (70s for most calls, 80s for
> `/kundli-analysis`). If the server timeout is higher, the browser aborts first and the
> server's graceful fallback never reaches the user.

### Accounts

The app requires an account. On first use, open the login screen and choose **"Account banayein"**
to sign up with an email/mobile and password (min 6 characters). Credentials are verified
server-side; passwords are stored only as PBKDF2-HMAC-SHA256 hashes in `backend/users.db`.

Every kundli you generate is saved against your account and listed under **Saved Reports**,
so your readings are available from any device you sign in on.

## API endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET`  | `/health` | — | Service + LLM provider status |
| `POST` | `/auth/signup` | — | Create an account, returns a bearer token |
| `POST` | `/auth/login` | — | Sign in, returns a bearer token |
| `GET`  | `/auth/me` | Bearer | Verify the current session |
| `POST` | `/kundli-analysis` | Bearer | Full Trividha kundli; auto-saves to history |
| `POST` | `/full-analysis` | Bearer | Long-form dasha reading |
| `POST` | `/section-qa` | Bearer | Free-text horary follow-up |
| `POST` | `/tezi-mandi` | Bearer | Market forecast / historical close |
| `GET`  | `/history` | Bearer | List this account's saved readings |
| `GET`  | `/history/{id}` | Bearer | Fetch one saved reading in full |
| `DELETE` | `/history/{id}` | Bearer | Delete one saved reading |

## Tests

Backend — 43 tests covering chart computation, authentication, endpoint protection,
rate limiting, saved-report isolation and the language/self-reference helpers.
No API keys or network access needed:

```bat
cd backend
pip install -r requirements-dev.txt
pytest
```

Frontend — 8 tests covering rendering, login/sign-up flow, session validation and
form validation:

```bat
cd frontend
npm test
```

## Project layout

```
MEDHA_AI/
├── backend/
│   ├── main.py              # FastAPI app: chart computation + LLM orchestration
│   ├── engine_config.json   # Tezi-Mandi market rule engine
│   ├── requirements.txt
│   ├── requirements-dev.txt # test deps (pytest)
│   ├── conftest.py          # test env setup (temp DB, no LLM keys)
│   ├── test_chart.py        # chart-computation tests
│   ├── test_api.py          # auth / endpoint / history / language tests
│   └── .env.example
├── frontend/
│   ├── src/App.js           # React 19 UI
│   ├── public/              # web assets (icons, manifest, service worker)
│   ├── brand-assets/        # source logo + icon generator (not shipped)
│   ├── assets/              # native icon/splash sources for capacitor-assets
│   ├── android/             # real native Android project (Capacitor 8)
│   └── capacitor.config.json
├── MOBILE_APP.md            # Android/iOS build + Play Store guide
├── DEPLOYMENT.md            # Render + Vercel deployment guide
├── setup.bat                # First-time setup
├── run_medha.bat            # Start backend + frontend
└── start_backend.bat        # Start backend only
```

## Mobile app

The repo contains a real native **Android** project at `frontend/android/`, generated with
Capacitor 8 and targeting Android SDK 36. Build and publish instructions (including
signing and the Play Store upload) are in **`MOBILE_APP.md`**.

```bat
cd frontend
set REACT_APP_API_URL=https://your-backend.onrender.com
npm run cap:sync
npm run cap:android
```

Requires **JDK 21** and **Android SDK 36** (both come with a current Android Studio).

## Notes

- The astrology engine performs real ephemeris computation; the LLM only narrates the computed data.
- Predictions are for entertainment/informational purposes and are not financial advice.
- Never commit `backend/.env`. If a key was ever committed, rotate it.

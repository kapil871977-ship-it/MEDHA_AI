# MEDHA AI

AI-powered Vedic astrology (Jyotish) web application. It computes real sidereal birth charts with the Swiss Ephemeris and uses an LLM to write personalized, chart-grounded interpretations in Hindi, Hinglish, and English. It also includes **Tezi-Mandi**, an astrology-based market/commodity prediction module that blends a KP rule engine with live historical price data.

## Features

- **Kundli analysis** — Janam (natal), Prashna (horary), and Gochar (transit) charts. Builds 12 houses with signs/lords/occupants and a Vimshottari Dasha timeline. AI interpretations are constrained to the computed chart so the model cannot invent placements.
- **Tezi-Mandi market prediction** — astrology-driven forecasts for commodities/indices (Gold, Silver, Crude Oil, Nifty, etc.), combining a configurable rule engine (`backend/engine_config.json`) with historical close prices from Yahoo Finance.
- **Section Q&A** — free-text follow-up questions per section, with Hindi/Hinglish/English style detection.
- **"Guru Ji" persona** — avatar and voice assets under `frontend/public/guruji/`.

## Tech stack

| Layer    | Technology |
|----------|-----------|
| Backend  | Python, FastAPI + Uvicorn, Swiss Ephemeris (`pyswisseph`), `timezonefinder`, `httpx` |
| LLM      | OpenAI `gpt-4o-mini` (primary), Google Gemini (`gemini-2.5-flash`, fallback) |
| Frontend | React 19 (Create React App) |
| External | OpenStreetMap Nominatim (geocoding), Yahoo Finance (price history) |
| Storage  | None — the app is stateless (no database) |

## Prerequisites

- Python 3.11+
- Node.js 18+
- A Google Gemini API key (and optionally an OpenAI API key)

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
| `MODEL_TIMEOUT_SECONDS` | No | LLM call timeout (default 150) |
| `KUNDLI_MODEL_TIMEOUT_SECONDS` | No | Kundli-specific LLM timeout (default: min(MODEL_TIMEOUT_SECONDS, 55)) |
| `PORT` | No | Backend port (default 8010) |
| `AUTH_SECRET_KEY` | No | Secret for signing auth tokens. Set it so logins survive restarts; random per-process if unset |
| `AUTH_TOKEN_TTL_SECONDS` | No | Auth token lifetime (default 2592000 = 30 days) |
| `AUTH_ENFORCE` | No | Require a valid token on the astrology/market endpoints (default `true`; set `false` to allow anonymous access) |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS allow-list (default `*`). Lock this down in production |
| `RATE_LIMIT_PER_MINUTE` | No | Max requests per client IP on heavy endpoints (default 30; `0` disables) |

### Accounts

The app requires an account. On first use, open the login screen and choose **"Account banayein"**
to sign up with an email/mobile and password (min 6 characters). Credentials are verified
server-side; passwords are stored only as PBKDF2-HMAC-SHA256 hashes in `backend/users.db`.

## Tests

Backend (chart-computation tests, no API keys needed):

```bat
cd backend
pip install -r requirements-dev.txt
pytest
```

Frontend (render smoke test):

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
│   ├── test_chart.py        # backend chart-computation tests
│   └── .env.example
├── frontend/                # React 19 UI (src/App.js)
├── setup.bat                # First-time setup
├── run_medha.bat            # Start backend + frontend
└── start_backend.bat        # Start backend only
```

## Notes

- The astrology engine performs real ephemeris computation; the LLM only narrates the computed data.
- Predictions are for entertainment/informational purposes and are not financial advice.
- Never commit `backend/.env`. If a key was ever committed, rotate it.

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './App.css';

// Safe localStorage wrappers: private-mode / disabled storage throws on access,
// which would otherwise white-screen the whole app. These degrade gracefully.
const safeGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const safeSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage disabled */ } };
const safeRemove = (k) => { try { localStorage.removeItem(k); } catch { /* storage disabled */ } };

// True when running inside the Capacitor native shell (Android/iOS), where the
// bridge injects `window.Capacitor`. Checked lazily so the web build and the
// Jest environment never need the native runtime.
function isNativeApp() {
  return typeof window !== 'undefined'
    && typeof window.Capacitor?.isNativePlatform === 'function'
    && window.Capacitor.isNativePlatform() === true;
}

// A phone cannot reach the developer's localhost, so the loopback fallback is
// only useful for browser development. Including it on device meant every
// request burned a full timeout against an address that can never answer.
// Resolved per request rather than at module load, so it is correct no matter
// when the Capacitor bridge finishes initialising.
function getApiBaseUrls() {
  const configured = process.env.REACT_APP_API_URL;
  if (isNativeApp()) {
    return [configured].filter(Boolean);
  }
  return [configured, 'http://127.0.0.1:8010'].filter(Boolean);
}

// Local (not UTC) calendar date as YYYY-MM-DD. `toISOString()` returns the UTC
// day, which is the previous date for IST users before 05:30 local time.
function toLocalDateString(dateObj) {
  const d = dateObj instanceof Date ? dateObj : new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// Each must exceed the matching server-side model timeout (75s general,
// 90s kundli) so the server can return its graceful fallback instead of the
// browser aborting first and showing a bare network error.
const REQUEST_TIMEOUT_MS = 90000;
const KUNDLI_REQUEST_TIMEOUT_MS = 105000;
const DASHA_REQUEST_TIMEOUT_MS = 95000;

const FORM_STORAGE_KEY = 'medha_kundli_form_data';
const AUTH_STORAGE_KEY = 'medha_is_logged_in';
const AUTH_TOKEN_KEY = 'medha_auth_token';
const AUTH_IDENTIFIER_KEY = 'medha_auth_identifier';
const TEZI_MANDI_HISTORY_KEY = 'medha_tezi_mandi_history_v1';
const LATEST_KUNDLI_KEY = 'medha_latest_kundli_response';

const GURU_IMAGE_CANDIDATES = [
  '/jagdacharya-swami-akhileshji-maharaj.png',
  '/jagdacharya-swami-akhileshji-maharaj.jpg',
  '/guru-ji.jpg',
  '/fortune-guru-logo.png'
];

// Only instruments the backend can actually resolve to a price symbol.
// Mustard, Jeera and Turmeric were previously offered here but have no
// mapping, so they silently returned a signal with no price attached.
const TEZI_COMMODITY_SUGGESTIONS = [
  'Gold', 'Silver', 'Crude Oil', 'Natural Gas', 'Copper', 'Aluminium',
  'Nifty 50', 'Bank Nifty', 'Sensex', 'USDINR', 'EURINR', 'JPYINR',
  'Soybean', 'Corn', 'Cotton', 'Sugar', 'Wheat', 'Rice', 'Coffee',
  'Bitcoin', 'Ethereum'
];

const HOUSE_NAME_HI = {
  1: 'Lagna Bhav',
  2: 'Dhan Bhav',
  3: 'Parakram Bhav',
  4: 'Sukh Bhav',
  5: 'Putra Bhav',
  6: 'Rog Bhav',
  7: 'Kalatra Bhav',
  8: 'Mrityu Bhav',
  9: 'Bhagya Bhav',
  10: 'Karma Bhav',
  11: 'Labh Bhav',
  12: 'Vyay Bhav',
};

const PLANET_FIELD_HINTS_HI = {
  Sun: 'leadership, authority, confidence, government/public role',
  Moon: 'mind, emotions, caregiving, public connection',
  Mars: 'courage, engineering, sports, operations, execution',
  Mercury: 'communication, business, writing, analytics, trading',
  Jupiter: 'teaching, strategy, finance guidance, wisdom, dharma',
  Venus: 'beauty, fashion, acting/media, arts, luxury, relationship harmony',
  Saturn: 'discipline, administration, systems, industry, persistence',
  Rahu: 'technology, digital scale, foreign links, unconventional growth',
  Ketu: 'research, spirituality, deep analysis, detachment',
};

async function fetchWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

function clearSession() {
  safeRemove(AUTH_TOKEN_KEY);
  safeRemove(AUTH_IDENTIFIER_KEY);
  safeRemove(AUTH_STORAGE_KEY);
}

/**
 * Issue a request against the first reachable API base URL.
 * Handles bearer auth, 401 session expiry, 429 throttling and timeouts.
 */
async function apiRequest(endpointPath, options = {}) {
  const { method = 'POST', payload } = options;
  // Auth calls should fail fast: a hung login shouldn't burn ~180s (90s per
  // base URL) before the user sees an error.
  const isAuthPath = endpointPath.startsWith('/auth/');
  const timeoutMs = options.timeoutMs ?? (isAuthPath ? 15000 : REQUEST_TIMEOUT_MS);
  const baseUrls = getApiBaseUrls();

  if (!baseUrls.length) {
    throw new Error(
      'Server address configure nahi hai. App ko REACT_APP_API_URL ke saath build karein.'
    );
  }

  const token = safeGet(AUTH_TOKEN_KEY);
  const headers = {};
  if (payload !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;

  let lastError = null;

  for (const baseUrl of baseUrls) {
    try {
      const res = await fetchWithTimeout(`${baseUrl}${endpointPath}`, {
        method,
        headers,
        ...(payload !== undefined ? { body: JSON.stringify(payload) } : {})
      }, timeoutMs);

      if (res.status === 401) {
        // Session expired or invalid — clear auth and force re-login. This is a
        // definitive answer from the server, so do not retry the next base URL.
        clearSession();
        window.dispatchEvent(new Event('medha-auth-expired'));
        if (window.location.hash !== '#login') window.location.hash = '#login';
        const err401 = new Error('Session expired. Kripya dubara login karein.');
        err401.nonRetryable = true;
        throw err401;
      }
      if (res.status === 429) {
        const err429 = new Error('Bahut zyada requests. Kripya ek minute baad try karein.');
        err429.nonRetryable = true;
        throw err429;
      }
      if (res.status === 404) {
        const err404 = new Error('Yeh record nahi mila.');
        err404.nonRetryable = true;
        throw err404;
      }
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const json = await res.json();
      if (json?.error) {
        throw new Error(json.error);
      }
      return json;
    } catch (err) {
      // A definitive HTTP status (401/404/429) is the server's final word — do
      // not fall through to the next base URL, surface it immediately.
      if (err?.nonRetryable) {
        throw err;
      }
      if (err?.name === 'AbortError') {
        lastError = new Error(`Request timeout (${Math.round(timeoutMs / 1000)}s) at ${baseUrl}`);
      } else {
        lastError = err;
      }
    }
  }

  throw lastError || new Error('Backend unavailable');
}

async function postWithFallback(endpointPath, payload, options = {}) {
  return apiRequest(endpointPath, { ...options, method: 'POST', payload });
}

function handleImageFallback(event) {
  const img = event.currentTarget;
  const fallbackList = String(img.dataset.fallbacks || '')
    .split('|')
    .map((s) => s.trim())
    .filter(Boolean);
  if (!fallbackList.length) return;
  img.src = fallbackList.shift();
  img.dataset.fallbacks = fallbackList.join('|');
}

function formatSystemNotice(note) {
  const text = String(note || '').trim();
  if (!text) return '';

  const lower = text.toLowerCase();
  if (lower.includes('resourceexhausted') || lower.includes('quota')) {
    return 'Notice: API quota exceed ho gaya hai. Abhi fast fallback response dikhaya ja raha hai.';
  }
  if (lower.includes('timeout')) {
    return 'Notice: API slow tha, isliye fast fallback response dikhaya ja raha hai.';
  }
  if (lower.includes('fallback')) {
    return 'Notice: Fast fallback response active hai.';
  }
  return `Notice: ${text.slice(0, 180)}`;
}

function formatDashaErrorText(raw) {
  const text = String(raw || '').trim();
  if (!text) return '';
  const lower = text.toLowerCase();

  if (lower.includes('resourceexhausted') || lower.includes('quota')) {
    return 'Dasha detailed output abhi API quota limit ki wajah se temporary unavailable hai. Thodi der baad retry karein.';
  }
  if (lower.includes('api error') || lower.includes('traceback')) {
    return 'Dasha detailed output me temporary technical issue aya tha. Kripya dobara try karein.';
  }
  if (lower.includes('timeout')) {
    return 'Dasha detailed output delay ho gaya (timeout). Kripya dubara try karein.';
  }
  return text;
}

function buildDashaFallbackFromChart(data) {
  const d = data?.chart_summary?.dasha || {};
  const maha = String(d?.mahadasha || '').trim();
  const antar = String(d?.antardasha || '').trim();
  const praty = String(d?.pratyantardasha || '').trim();

  if (!maha && !antar) {
    return 'Dasha summary chart se fetch nahi ho paayi. Kripya thodi der baad Dasha tab ko reload karein.';
  }

  return dedupeSentences(
    `Chalit Dasha Sanket: ${maha || 'Unknown'} Mahadasha, ${antar || 'Unknown'} Antardasha${praty ? `, ${praty} Pratyantardasha` : ''}. ` +
    'Is phase me consistency, decision clarity aur disciplined routine aapke liye sabse bada multiplier rahega. ' +
    'Major commitments me risk-check karke chalna, aur weekly review ke saath execution rakhna adhik labhkari hoga.'
  );
}

function dedupeSentences(input) {
  const text = String(input || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';

  const normalize = (value) => String(value || '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  const parts = text
    .split(/(?<=[.!?])\s+/)
    .map((p) => p.trim())
    .filter(Boolean);

  const seen = new Set();
  const out = [];
  for (const part of parts) {
    const key = normalize(part);
    if (!seen.has(key)) {
      seen.add(key);
      out.push(part);
    }
  }
  return out.join(' ');
}

function getHouseHeading(houseNumber, fallbackName) {
  const num = Number(houseNumber || 0);
  const hiName = HOUSE_NAME_HI[num] || 'Bhav';
  const cleanFallback = String(fallbackName || '').trim();
  if (cleanFallback) {
    return `Bhav ${num}: ${hiName} (${cleanFallback})`;
  }
  return `Bhav ${num}: ${hiName}`;
}

function buildDetailedFromBlock(block, title) {
  const houses = Array.isArray(block?.houses) ? block.houses : [];
  const keySignals = houses
    .map((h) => String(h?.prediction || '').trim())
    .filter(Boolean)
    .slice(0, 4)
    .map((txt) => txt.split('.').map((x) => x.trim()).filter(Boolean)[0])
    .filter(Boolean);

  const steps = Array.isArray(block?.next_steps)
    ? block.next_steps.map((x) => String(x || '').trim()).filter(Boolean).slice(0, 4)
    : [];

  const dominantPlanets = [...new Set(
    houses
      .map((h) => String(h?.lord || '').trim())
      .filter(Boolean)
  )].slice(0, 3);

  const domainLines = dominantPlanets
    .map((p) => PLANET_FIELD_HINTS_HI[p] ? `${p} se jude kshetra: ${PLANET_FIELD_HINTS_HI[p]}` : '')
    .filter(Boolean)
    .slice(0, 2);

  if (!keySignals.length && !steps.length && !domainLines.length) return '';

  const intro = `${title} ka vistaar se saar: chart ke mukhya graha-prabhav ke hisab se aapko disciplined aur phased action lena hoga.`;
  const signalText = keySignals.length ? `Mukhya sanket: ${keySignals.join(' | ')}.` : '';
  const domainText = domainLines.length ? `Graha-domain focus: ${domainLines.join(' | ')}.` : '';
  const actionText = steps.length ? `Karya yojana: ${steps.join(' | ')}.` : '';
  const closing = 'Ateet-vartaman-bhavishya tino layer me ek hi sutra rakhein: clarity, consistency, aur practical execution.';

  return dedupeSentences(`${intro} ${signalText} ${domainText} ${actionText} ${closing}`);
}

function buildQuickPairAnswer(activeModule, data, dashaPrediction) {
  const blockMap = {
    janam: data?.janam_kundli,
    gochar: data?.gochar_kundli,
    prashna: data?.prashna_kundli
  };

  const block = blockMap[activeModule] || {};
  const chartSummary = data?.chart_summary || {};
  const lagna = chartSummary?.lagna || {};

  const lords = Array.isArray(block?.houses)
    ? [...new Set(block.houses.map((h) => String(h?.lord || '').trim()).filter(Boolean))].slice(0, 3)
    : [];

  const lordDomains = lords
    .map((p) => PLANET_FIELD_HINTS_HI[p] ? `${p}: ${PLANET_FIELD_HINTS_HI[p]}` : '')
    .filter(Boolean)
    .slice(0, 2);

  const focusByModule = {
    janam: 'Aapka asli growth focus long-term personality architecture, relationship maturity aur financial-discipline alignment par hona chahiye.',
    gochar: 'Agle 1-3 mahine ka focus timing-sensitive decisions, communication clarity aur workload restructuring par rakhein.',
    prashna: 'Current prashn ke liye focus immediate action-clarity, risk control, aur measurable short-cycle outcome par rakhein.',
    dasha: 'Chal rahi dasha me focus routine discipline, karmic consistency, aur selective opportunities par rakhein.',
  };

  const lagnaLine = lagna?.rashi_hi
    ? `Lagna sanket: ${lagna.rashi_hi} (${lagna.rashi}) aur Lagnesh ${lagna.lagnesh} aapke decision framework ko lead kar rahe hain.`
    : '';

  const domainLine = lordDomains.length
    ? `Aapke chart ke mukhya graha-field: ${lordDomains.join(' | ')}.`
    : '';

  const detailFromBlock = buildDetailedFromBlock(block, activeModule === 'dasha' ? 'Dasha' : 'Kundli');
  const fallbackFromPrediction = dedupeSentences(String(block?.prediction || dashaPrediction || '').trim());

  return dedupeSentences(
    `${focusByModule[activeModule] || ''} ${lagnaLine} ${domainLine} ${detailFromBlock || fallbackFromPrediction}`
  );
}

function sanitizeHouseAnalysis(analysis) {
  const text = String(analysis || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';

  // Hide technical fallback dump lines that make cards noisy.
  const lower = text.toLowerCase();
  if (lower.includes('swiss ephemeris') || text.startsWith('[')) {
    return '';
  }

  return text;
}

/** App title. Rendered as the single <h1> on every page. */
function Brand() {
  return <h1 style={heroTopStyle}>Fortune Guru</h1>;
}

/**
 * Native-shell wiring (no-op in the browser):
 *  - hides the splash screen once React has mounted
 *  - styles the Android status bar to match the app background
 *  - maps the hardware back button to in-app navigation instead of
 *    closing the app from any screen
 */
function useNativeShell(route) {
  useEffect(() => {
    if (!isNativeApp()) return undefined;

    let removeBackListener = null;
    let cancelled = false;

    (async () => {
      try {
        const [{ App: CapApp }, { StatusBar, Style }, { SplashScreen }] = await Promise.all([
          import('@capacitor/app'),
          import('@capacitor/status-bar'),
          import('@capacitor/splash-screen')
        ]);
        if (cancelled) return;

        StatusBar.setStyle({ style: Style.Dark }).catch(() => {});
        StatusBar.setBackgroundColor({ color: '#020617' }).catch(() => {});
        SplashScreen.hide().catch(() => {});

        const handle = await CapApp.addListener('backButton', ({ canGoBack }) => {
          const current = window.location.hash || '#home';
          if (current !== '#home' && current !== '#login') {
            window.location.hash = '#home';
          } else if (canGoBack) {
            window.history.back();
          } else {
            CapApp.exitApp();
          }
        });
        if (cancelled) {
          handle.remove();
          return;
        }
        removeBackListener = () => handle.remove();
      } catch {
        // Plugins unavailable — the app still works, just without the extras.
      }
    })();

    return () => {
      cancelled = true;
      if (removeBackListener) removeBackListener();
    };
  }, [route]);
}

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(Boolean(safeGet(AUTH_TOKEN_KEY)));
  const [route, setRoute] = useState(window.location.hash || '#home');

  useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash || '#home');
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // A 401 anywhere in the app clears the stored token and fires this event so
  // the UI drops back to the logged-out state instead of showing stale auth.
  useEffect(() => {
    const onAuthExpired = () => setIsLoggedIn(false);
    window.addEventListener('medha-auth-expired', onAuthExpired);
    return () => window.removeEventListener('medha-auth-expired', onAuthExpired);
  }, []);

  useNativeShell(route);

  // A stored token can be expired or signed with an old server secret. Verify
  // it once on start-up so the user lands on the login screen immediately
  // instead of hitting an error on their first real request.
  useEffect(() => {
    if (!safeGet(AUTH_TOKEN_KEY)) return undefined;

    let cancelled = false;
    (async () => {
      try {
        const res = await apiRequest('/auth/me', { method: 'GET', timeoutMs: 15000 });
        if (!cancelled && res && res.authenticated === false) {
          clearSession();
          setIsLoggedIn(false);
          window.location.hash = '#login';
        }
      } catch {
        // Offline or backend down: keep the cached session so saved reports
        // remain readable; the next real request will surface any problem.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleLogout = () => {
    clearSession();
    setIsLoggedIn(false);
    window.location.hash = '#login';
  };

  const onLoginSuccess = () => setIsLoggedIn(true);

  const guarded = (element) => (isLoggedIn ? element : <LoginPage onLoginSuccess={onLoginSuccess} />);

  let page = null;
  if (route === '#login') {
    page = <LoginPage onLoginSuccess={onLoginSuccess} />;
  } else if (route === '#kundli') {
    page = guarded(<KundliPage onLogout={handleLogout} />);
  } else if (route === '#saved') {
    page = guarded(<KundliPage onLogout={handleLogout} savedMode />);
  } else if (route === '#remedies') {
    page = guarded(<RemediesPage onLogout={handleLogout} />);
  } else if (route === '#history') {
    page = guarded(<HistoryPage onLogout={handleLogout} />);
  } else {
    page = guarded(<HomePage onLogout={handleLogout} />);
  }

  return (
    <>
      {page}
      <RemedyNotice />
      <FloatingGuruPhoto />
    </>
  );
}

function LoginPage({ onLoginSuccess }) {
  const [mode, setMode] = useState('login'); // 'login' | 'signup'
  const [emailOrMobile, setEmailOrMobile] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const isSignup = mode === 'signup';

  const handleSubmit = async () => {
    setError('');
    if (!emailOrMobile.trim() || !password.trim()) {
      setError('Email/Mobile aur password dono bharna zaroori hai.');
      return;
    }
    if (isSignup && password.trim().length < 6) {
      setError('Password kam se kam 6 characters ka hona chahiye.');
      return;
    }

    setLoading(true);
    try {
      const endpoint = isSignup ? '/auth/signup' : '/auth/login';
      const res = await postWithFallback(endpoint, {
        identifier: emailOrMobile.trim(),
        password: password
      });

      if (!res?.token) {
        throw new Error('Server se token nahi mila. Dubara try karein.');
      }

      safeSet(AUTH_TOKEN_KEY, res.token);
      safeSet(AUTH_IDENTIFIER_KEY, res.identifier || emailOrMobile.trim().toLowerCase());
      safeSet(AUTH_STORAGE_KEY, '1');
      onLoginSuccess();
      window.location.hash = '#home';
    } catch (e) {
      console.error('Auth request failed:', e);
      const msg = String(e?.message || '');
      const looksTechnical = /http\s*\d|timeout|127\.0\.0\.1|https?:\/\//i.test(msg);
      setError(looksTechnical || !msg
        ? 'Server se connection nahi ho paya. Kripya thodi der baad try karein.'
        : msg);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !loading) handleSubmit();
  };

  return (
    <div style={pageStyle}>
      <Brand />
      <div style={loginCenterStyle}>
        <section style={{ ...cardStyle, maxWidth: 460, width: '100%' }}>
          <div style={deityRowStyle}>
            <img
              src="/shiv-parivar.jpg"
              data-fallbacks="/fortune-guru-logo.png"
              onError={handleImageFallback}
              alt="Shiv Parivar"
              style={deityImgStyle}
            />
            <img
              src="/lakshmi-narayan.jpg"
              data-fallbacks="/fortune-guru-logo.png"
              onError={handleImageFallback}
              alt="Lakshmi Narayan"
              style={deityImgStyle}
            />
          </div>
          <div style={avatarWrapStyle}>
            <img
              src={GURU_IMAGE_CANDIDATES[0]}
              data-fallbacks={GURU_IMAGE_CANDIDATES.slice(1).join('|')}
              onError={handleImageFallback}
              alt="Guru Ji"
              style={avatarStyle}
            />
          </div>
          <h2 style={titleStyle}>{isSignup ? 'Naya Account Banayein' : 'Login'}</h2>
          <p style={subStyle}>
            {isSignup
              ? 'Account banakar divine guidance shuru karein.'
              : 'Divine guidance ke liye login karein.'}
          </p>

          <label style={labelStyle}>Email ya Mobile</label>
          <input
            style={inputStyle}
            value={emailOrMobile}
            onChange={(e) => setEmailOrMobile(e.target.value)}
            onKeyDown={handleKeyDown}
            autoComplete="username"
          />

          <label style={labelStyle}>Password</label>
          <input
            type="password"
            style={inputStyle}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={handleKeyDown}
            autoComplete={isSignup ? 'new-password' : 'current-password'}
          />

          <button style={buttonStyle} onClick={handleSubmit} disabled={loading}>
            {loading ? 'Kripya intezaar karein...' : (isSignup ? 'Account Banayein' : 'Login')}
          </button>

          <p style={{ ...subStyle, marginTop: 14 }}>
            {isSignup ? 'Pehle se account hai? ' : 'Naye user hain? '}
            <span
              role="button"
              tabIndex={0}
              onClick={() => { setError(''); setMode(isSignup ? 'login' : 'signup'); }}
              onKeyDown={(e) => { if (e.key === 'Enter') { setError(''); setMode(isSignup ? 'login' : 'signup'); } }}
              style={{ color: '#b8860b', cursor: 'pointer', fontWeight: 700, textDecoration: 'underline' }}
            >
              {isSignup ? 'Login karein' : 'Account banayein'}
            </span>
          </p>

          {error ? <p style={errorStyle}>{error}</p> : null}
        </section>
      </div>
    </div>
  );
}

// ── Time-of-birth helpers: store tob as 24h "HH:MM", edit as 12h + AM/PM ──
function parseTob(tob) {
  const m = /^(\d{1,2}):(\d{2})/.exec(String(tob || ''));
  if (!m) return { h12: '', min: '', ampm: 'AM' };
  const h = parseInt(m[1], 10);
  const ampm = h >= 12 ? 'PM' : 'AM';
  let h12 = h % 12;
  if (h12 === 0) h12 = 12;
  return { h12: String(h12), min: m[2], ampm };
}
function buildTob(h12, min, ampm) {
  if (!h12 || min === '' || min === undefined || min === null) return '';
  let h = parseInt(h12, 10) % 12;
  if (ampm === 'PM') h += 12;
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

function HomePage({ onLogout }) {
  const [message, setMessage] = useState('');
  const [messageIsError, setMessageIsError] = useState(false);
  const [placeSuggestions, setPlaceSuggestions] = useState([]);
  const [placeLoading, setPlaceLoading] = useState(false);
  const justSelectedPlace = useRef(false);
  const [formData, setFormData] = useState(() => {
    try {
      const raw = safeGet(FORM_STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch {
      // ignore invalid cache
    }
    return {
      first_name: '',
      dob: '',
      tob: '',
      place: '',
      selected_number: 1,
      language: 'hi',
      lat: null,
      lng: null,
    };
  });

  // Live place suggestions from OpenStreetMap (debounced). Selecting one also
  // captures exact lat/lng so the reading uses precise coordinates.
  useEffect(() => {
    const q = String(formData.place || '').trim();
    if (justSelectedPlace.current) { justSelectedPlace.current = false; return; }
    if (q.length < 3) { setPlaceSuggestions([]); return; }
    const timer = setTimeout(async () => {
      try {
        setPlaceLoading(true);
        const res = await fetch(
          `https://nominatim.openstreetmap.org/search?format=json&limit=5&q=${encodeURIComponent(q)}`,
          { headers: { 'Accept-Language': 'en' } }
        );
        const data = await res.json();
        setPlaceSuggestions(Array.isArray(data)
          ? data.map((d) => ({ name: d.display_name, lat: parseFloat(d.lat), lng: parseFloat(d.lon) }))
          : []);
      } catch {
        setPlaceSuggestions([]);
      } finally {
        setPlaceLoading(false);
      }
    }, 450);
    return () => clearTimeout(timer);
  }, [formData.place]);

  const openKundliPage = () => {
    const missing = [];
    if (!formData.first_name?.trim()) missing.push('Naam');
    if (!formData.dob) missing.push('Janam Tarikh');
    if (!formData.tob) missing.push('Janam Samay');
    if (!formData.place?.trim()) missing.push('Janam Sthan');
    if (missing.length) {
      setMessageIsError(true);
      setMessage(`Yeh field bharna zaroori hai: ${missing.join(', ')}.`);
      return;
    }

    const dobDate = new Date(`${formData.dob}T00:00:00`);
    if (Number.isNaN(dobDate.getTime())) {
      setMessageIsError(true);
      setMessage('Janam tarikh sahi format me nahi hai.');
      return;
    }
    if (dobDate > new Date()) {
      setMessageIsError(true);
      setMessage('Janam tarikh future me nahi ho sakti.');
      return;
    }

    setMessageIsError(false);
    setMessage('');
    safeSet(FORM_STORAGE_KEY, JSON.stringify(formData));

    // Open the kundli in place (same page) rather than a new browser tab: a new
    // tab has no access to this session/saved form, and native WebViews have no
    // tabs at all.
    window.location.hash = '#kundli';
  };

  return (
    <div style={pageStyle}>
      <Brand />
      <div style={{ ...cardStyle, maxWidth: 860 }}>
        <div style={rowBetweenStyle}>
          <h2 style={titleStyle}>Basic Details Form</h2>
          <div style={rowWrapStyle}>
            <button style={secondaryButtonStyle} onClick={() => { window.location.hash = '#history'; }}>Saved Reports</button>
            <button style={secondaryButtonStyle} onClick={() => { window.location.hash = '#remedies'; }}>Remedies</button>
            <button style={secondaryButtonStyle} onClick={onLogout}>Logout</button>
          </div>
        </div>

        <label style={labelStyle}>Aapka Naam</label>
        <input style={inputStyle} value={formData.first_name} onChange={(e) => setFormData({ ...formData, first_name: e.target.value })} />

        <label style={labelStyle}>Janam Tarikh</label>
        <input type="date" style={inputStyle} value={formData.dob} onChange={(e) => setFormData({ ...formData, dob: e.target.value })} />

        <label style={labelStyle}>Janam Samay</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <select
            style={{ ...inputStyle, flex: 1 }}
            value={parseTob(formData.tob).h12}
            onChange={(e) => setFormData({ ...formData, tob: buildTob(e.target.value, parseTob(formData.tob).min || '00', parseTob(formData.tob).ampm) })}
          >
            <option value="">Ghanta</option>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((h) => <option key={h} value={h}>{h}</option>)}
          </select>
          <select
            style={{ ...inputStyle, flex: 1 }}
            value={parseTob(formData.tob).min}
            onChange={(e) => setFormData({ ...formData, tob: buildTob(parseTob(formData.tob).h12 || '12', e.target.value, parseTob(formData.tob).ampm) })}
          >
            <option value="">Minute</option>
            {Array.from({ length: 60 }, (_, i) => i).map((m) => {
              const mm = String(m).padStart(2, '0');
              return <option key={mm} value={mm}>{mm}</option>;
            })}
          </select>
          <select
            style={{ ...inputStyle, flex: 1 }}
            value={parseTob(formData.tob).ampm}
            onChange={(e) => setFormData({ ...formData, tob: buildTob(parseTob(formData.tob).h12 || '12', parseTob(formData.tob).min || '00', e.target.value) })}
          >
            <option value="AM">AM</option>
            <option value="PM">PM</option>
          </select>
        </div>

        <label style={labelStyle}>Janam Sthan</label>
        <input
          style={inputStyle}
          value={formData.place}
          placeholder="Sheher ka naam likhein (jaise New Delhi)"
          onChange={(e) => setFormData({ ...formData, place: e.target.value, lat: null, lng: null })}
        />
        {placeLoading ? <p style={mutedStyle}>Sthan dhoondh rahe hain...</p> : null}
        {placeSuggestions.length > 0 ? (
          <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {placeSuggestions.map((s, i) => (
              <button
                key={`ps-${i}`}
                type="button"
                style={{ ...secondaryButtonStyle, textAlign: 'left', fontSize: 13 }}
                onClick={() => {
                  justSelectedPlace.current = true;
                  setFormData((f) => ({ ...f, place: s.name, lat: s.lat, lng: s.lng }));
                  setPlaceSuggestions([]);
                }}
              >
                {s.name}
              </button>
            ))}
          </div>
        ) : null}

        <label style={labelStyle}>Lucky Number (1-9)</label>
        <input
          type="number"
          min="1"
          max="9"
          style={inputStyle}
          value={formData.selected_number}
          onChange={(e) => setFormData({ ...formData, selected_number: Math.min(9, Math.max(1, parseInt(e.target.value || '1', 10) || 1)) })}
        />

        <label style={labelStyle}>Language</label>
        <select style={inputStyle} value={formData.language} onChange={(e) => setFormData({ ...formData, language: e.target.value })}>
          <option value="hi">Hindi</option>
          <option value="en">English</option>
        </select>

        <button style={buttonStyle} onClick={openKundliPage}>Kundli Kholen</button>
        {message ? <p style={messageIsError ? errorStyle : msgStyle}>{message}</p> : null}
      </div>
    </div>
  );
}

function collectRemedies(data) {
  const out = [];
  const push = (v) => {
    const t = String(v || '').trim();
    if (t && !out.includes(t)) out.push(t);
  };

  [data?.janam_kundli, data?.prashna_kundli, data?.gochar_kundli].forEach((b) => {
    (b?.houses || []).forEach((h) => push(h?.advice || h?.upay));
    (b?.next_steps || []).forEach((s) => push(s));
  });
  return out;
}

function KundliPage({ onLogout, savedMode = false }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [warning, setWarning] = useState('');
  const [data, setData] = useState(null);
  const [dashaPrediction, setDashaPrediction] = useState('');
  const [dashaLoading, setDashaLoading] = useState(false);
  const [dashaError, setDashaError] = useState('');
  const [activeModule, setActiveModule] = useState('janam');

  const formData = useMemo(() => {
    const raw = safeGet(FORM_STORAGE_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      // Saved-report mode: render a previously saved reading from local storage,
      // no network call.
      if (savedMode) {
        const raw = safeGet(LATEST_KUNDLI_KEY);
        let saved = null;
        if (raw) { try { saved = JSON.parse(raw); } catch { saved = null; } }
        if (saved) {
          setData(saved);
          setWarning('Yeh aapki saved report hai.');
          setDashaPrediction(buildDashaFallbackFromChart(saved));
        } else {
          setError('Saved report nahi mili. Kripya nayi kundli banayein.');
        }
        setLoading(false);
        setDashaLoading(false);
        return;
      }

      if (!formData) {
        setError('Pehle home page par details fill karke kundli kholen.');
        setLoading(false);
        return;
      }

      try {
        const result = await postWithFallback('/kundli-analysis', formData, { timeoutMs: KUNDLI_REQUEST_TIMEOUT_MS });
        if (!cancelled) {
          setData(result);
          setWarning(result?.system_note ? formatSystemNotice(result.system_note) : '');
          safeSet(LATEST_KUNDLI_KEY, JSON.stringify(result));
          setLoading(false);
          setDashaLoading(true);
        }

        try {
          const dashaResult = await postWithFallback('/full-analysis', formData, { timeoutMs: DASHA_REQUEST_TIMEOUT_MS });
          if (!cancelled) {
            const rawDashaText = String(dashaResult?.prediction || '').trim();
            const safeDashaText = formatDashaErrorText(rawDashaText);
            const lower = safeDashaText.toLowerCase();
            // Only treat this as an error notice when the text is SHORT and
            // clearly an error message. A real reading is long and may
            // legitimately use words like "temporary", so the length guard
            // prevents a valid reading from being shown as a red error.
            const looksLikeError = safeDashaText.length < 400 && (
              lower.includes('unavailable') ||
              lower.includes('retry') ||
              lower.includes('quota') ||
              lower.includes('timeout') ||
              lower.includes('temporary issue') ||
              lower.includes('technical issue')
            );
            if (looksLikeError) {
              setDashaError(safeDashaText);
              setDashaPrediction(buildDashaFallbackFromChart(result));
            } else {
              setDashaPrediction(safeDashaText);
            }
          }
        } catch (dErr) {
          if (!cancelled) {
            setDashaError(formatDashaErrorText(`Dasha load nahi hui: ${String(dErr?.message || dErr)}`));
            setDashaPrediction(buildDashaFallbackFromChart(result));
          }
        } finally {
          if (!cancelled) setDashaLoading(false);
        }
      } catch (e) {
        console.error('Kundli load failed:', e);
        if (!cancelled) {
          const cachedRaw = safeGet(LATEST_KUNDLI_KEY);
          let cachedData = null;
          if (cachedRaw) {
            try {
              cachedData = JSON.parse(cachedRaw);
            } catch {
              cachedData = null;
            }
          }
          if (cachedData) {
            setData(cachedData);
            setWarning('Live kundli abhi load nahi hui. Last saved report dikhayi ja rahi hai.');
          } else {
            setError('Server se connection nahi ho paya. Kripya thodi der baad try karein.');
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    run();
    return () => { cancelled = true; };
  }, [formData, savedMode]);


  // Guru Ji avatar UI (rotating photos)

  const gurujiAvatars = [
    '/guruji/guruji1.jpeg',
    '/guruji/guruji2.jpeg',
    '/guruji/guruji3.jpeg',
    '/guruji/guruji4.jpeg',
    '/guruji/guruji5.jpeg',
    '/guruji/guruji6.jpeg',
    '/guruji/guruji7.jpeg',
    '/guruji/guruji8.jpeg',
    '/guruji/guruji9.jpeg',
    '/guruji/guruji10.jpeg',
  ];
  const [avatarIdx, setAvatarIdx] = useState(0);
  const gurujiAvatar = gurujiAvatars[avatarIdx];

  // Cycle avatar on click
  const handleAvatarClick = () => setAvatarIdx((i) => (i + 1) % gurujiAvatars.length);

  if (loading) return (
    <KundliLoadingScreen
      avatar={gurujiAvatar}
      onAvatarClick={handleAvatarClick}
    />
  );

  if (error) {
    return (
      <div style={errorPageStyle}>
        <img
          src={gurujiAvatar}
          data-fallbacks={GURU_IMAGE_CANDIDATES.join('|')}
          onError={handleImageFallback}
          alt="Guru Ji"
          style={{ width: 120, borderRadius: '50%', marginBottom: 16, animation: 'guruji-blink 2s infinite', cursor: 'pointer' }}
          onClick={handleAvatarClick}
        />
        <div>{error}</div>
        <div style={{ marginTop: 12, display: 'flex', gap: 8, flexDirection: 'column' }}>
          <button style={secondaryButtonStyle} onClick={() => { window.location.hash = '#home'; }}>Home par wapas jayein</button>
          <button style={secondaryButtonStyle} onClick={() => window.location.reload()}>Dubara try karein</button>
        </div>
        <style>{`@keyframes guruji-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }`}</style>
      </div>
    );
  }

  const remedies = collectRemedies(data);
  const qaSectionNameByModule = {
    janam: 'Janam Kundli',
    gochar: 'Gochar Kundli',
    prashna: 'Prashna Kundli',
    dasha: 'Dasha Details',
    remedies: 'Quick Guide Remedies',
    tezi_mandi: 'Tezi-Mandi'
  };

  const qaContextByModule = {
    janam: { section_data: data?.janam_kundli || {}, chart_summary: data?.chart_summary || {} },
    gochar: { section_data: data?.gochar_kundli || {}, chart_summary: data?.chart_summary || {} },
    prashna: { section_data: data?.prashna_kundli || {}, chart_summary: data?.chart_summary || {} },
    dasha: { dasha_prediction: dashaPrediction, dasha_error: dashaError, chart_summary: data?.chart_summary || {} },
    remedies: { remedies, chart_summary: data?.chart_summary || {} },
    tezi_mandi: { chart_summary: data?.chart_summary || {}, note: 'Commodity trend guidance module' }
  };

  const qaSectionName = qaSectionNameByModule[activeModule] || 'General';
  const qaContextText = JSON.stringify(qaContextByModule[activeModule] || {}).slice(0, 6000);

  return (
    <div style={pageStyle}>
      <Brand />
      <div style={{ ...cardStyle, maxWidth: 1120 }}>
        <div style={rowBetweenStyle}>
          <h2 style={titleStyle}>{data?.title || 'Trividha Kundli Vishleshan'}</h2>
          <div style={rowWrapStyle}>
            <button style={secondaryButtonStyle} onClick={() => { window.location.hash = '#home'; }}>Home</button>
            <button style={secondaryButtonStyle} onClick={() => { window.location.hash = '#history'; }}>Saved Reports</button>
            <button style={secondaryButtonStyle} onClick={onLogout}>Logout</button>
          </div>
        </div>

        {warning ? <p style={warnStyle}>{warning}</p> : null}

        <div style={moduleWrapStyle}>
          <button style={moduleButtonStyle(activeModule === 'janam')} onClick={() => setActiveModule('janam')}>Janam</button>
          <button style={moduleButtonStyle(activeModule === 'gochar')} onClick={() => setActiveModule('gochar')}>Gochar</button>
          <button style={moduleButtonStyle(activeModule === 'prashna')} onClick={() => setActiveModule('prashna')}>Prashna</button>
          <button style={moduleButtonStyle(activeModule === 'dasha')} onClick={() => setActiveModule('dasha')}>Dasha</button>
          <button style={moduleButtonStyle(activeModule === 'remedies')} onClick={() => setActiveModule('remedies')}>Quick Guide</button>
          <button style={moduleButtonStyle(activeModule === 'tezi_mandi')} onClick={() => setActiveModule('tezi_mandi')}>Tezi-Mandi</button>
        </div>

        {activeModule === 'janam' ? <KundliSection title="Janam Kundli" block={data?.janam_kundli} /> : null}
        {activeModule === 'gochar' ? <KundliSection title="Gochar Kundli" block={data?.gochar_kundli} /> : null}
        {activeModule === 'prashna' ? <KundliSection title="Prashna Kundli" block={data?.prashna_kundli} /> : null}
        {activeModule === 'dasha' ? <DashaSection prediction={dashaPrediction} loading={dashaLoading} error={dashaError} /> : null}
        {activeModule === 'remedies' ? <RemedyBlock remedies={remedies} /> : null}
        {activeModule === 'tezi_mandi' ? <TeziMandiPanel formData={formData} /> : null}

        <SectionQAPanel
          section={qaSectionName}
          language={formData?.language || 'hi'}
          contextText={qaContextText}
        />

        <SectionRapidGuidance activeModule={activeModule} data={data} dashaPrediction={dashaPrediction} />
      </div>
    </div>
  );
}

function RemedyBlock({ remedies }) {
  return (
    <section style={sectionStyle}>
      <h2 style={sectionTitleStyle}>Quick Guide Remedies</h2>
      {remedies.length ? (
        <ul style={listStyle}>
          {remedies.map((r, i) => <li key={`r-${i}`} style={listItemStyle}>{r}</li>)}
        </ul>
      ) : <p style={mutedStyle}>Remedies unavailable.</p>}
    </section>
  );
}

/**
 * KP (Krishnamurti Paddhati) cusp sub-lord table.
 *
 * The backend computes this for every section — sub-lord per cusp, the houses
 * each sub-lord links to, and the event window from the current antardasha —
 * but nothing rendered it, so the whole analysis was discarded client-side.
 */
function KpCuspPanel({ table, topHouses, window: eventWindow }) {
  const [expanded, setExpanded] = useState(false);

  const rows = Array.isArray(table) ? table.filter((r) => r && r.sublord) : [];
  const top = Array.isArray(topHouses) ? topHouses.filter((r) => r && r.sublord) : [];
  const start = String(eventWindow?.start || '').trim();
  const end = String(eventWindow?.end || '').trim();

  if (!rows.length && !top.length && !start && !end) return null;

  return (
    <div style={sectionInnerStyle}>
      <h3 style={smallHeadStyle}>KP Cusp Sub-Lord Vishleshan</h3>
      {start || end ? (
        <p style={mutedStyle}>
          Event window: {start || '?'} se {end || '?'} tak
        </p>
      ) : null}

      {top.length > 0 ? (
        <p style={textStyle}>
          Sabse sakriya bhav:{' '}
          {top.slice(0, 3).map((r) => `Bhav ${r.house} (${r.sublord})`).join(', ')}
        </p>
      ) : null}

      {rows.length > 0 ? (
        <>
          <button
            type="button"
            style={secondaryButtonStyle}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Poori KP table chhupayein' : 'Poori KP table dekhein'}
          </button>
          {expanded ? (
            <div style={{ overflowX: 'auto', marginTop: 10 }}>
              <table style={kpTableStyle}>
                <thead>
                  <tr>
                    <th style={kpThStyle}>Bhav</th>
                    <th style={kpThStyle}>Nakshatra</th>
                    <th style={kpThStyle}>Nakshatra Swami</th>
                    <th style={kpThStyle}>Sub-Lord</th>
                    <th style={kpThStyle}>Linked Bhav</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`kp-${r.house}`}>
                      <td style={kpTdStyle}>{r.house}</td>
                      <td style={kpTdStyle}>{r.nakshatra || '-'}</td>
                      <td style={kpTdStyle}>{r.nakshatra_lord || '-'}</td>
                      <td style={kpTdStyle}>{r.sublord || '-'}</td>
                      <td style={kpTdStyle}>
                        {Array.isArray(r.linked_houses) && r.linked_houses.length
                          ? r.linked_houses.join(', ')
                          : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function KundliSection({ title, block }) {
  const houses = Array.isArray(block?.houses) ? block.houses : [];
  // Remove unwanted fallback phrase from predictions
  const cleanPrediction = (text) => {
    if (!text) return '';
    return String(text).replace(/Detailed .*? Kundli fallback: viewed across past-present-future,? ?/i, '');
  };
  const shortPrediction = dedupeSentences(cleanPrediction(block?.prediction) || 'Prediction unavailable.');
  const rawDetailedPrediction = dedupeSentences(cleanPrediction(block?.detailed_prediction) || '');
  const detailedPrediction = rawDetailedPrediction || buildDetailedFromBlock(block, title);
  const showDetailed = Boolean(detailedPrediction);
  // Analysis fields removed from user view
  const kpCore = block?.kp_core && typeof block.kp_core === 'object' ? block.kp_core : {};
  const kpFullCuspTable = Array.isArray(kpCore?.full_cusp_table) ? kpCore.full_cusp_table : [];
  const kpTopEventHouses = Array.isArray(kpCore?.top_event_houses) ? kpCore.top_event_houses : [];
  const kpWindow = kpCore?.event_windows && typeof kpCore.event_windows === 'object' ? kpCore.event_windows : null;
  const nextSteps = Array.isArray(block?.next_steps)
    ? block.next_steps
      .map((s) => dedupeSentences(String(s || '').trim()))
      .filter(Boolean)
    : [];

  return (
    <section style={sectionStyle}>
      <h2 style={sectionTitleStyle}>{title}</h2>
      {showDetailed ? <p style={textStyle}>{detailedPrediction}</p> : <p style={textStyle}>{shortPrediction}</p>}
      {showDetailed && shortPrediction ? (
        <p style={{ ...mutedStyle, fontStyle: 'italic' }}>Saar: {shortPrediction}</p>
      ) : null}
      {nextSteps.length > 0 ? (
        <>
          <h3 style={smallHeadStyle}>Next Steps</h3>
          <ul style={listStyle}>
            {nextSteps.map((s, i) => <li key={`s-${i}`} style={listItemStyle}>{s}</li>)}
          </ul>
        </>
      ) : null}
      <KpCuspPanel
        table={kpFullCuspTable}
        topHouses={kpTopEventHouses}
        window={kpWindow}
      />
      {houses.length > 0 ? (
        <>
          <h3 style={smallHeadStyle}>12 Houses</h3>
          <div style={houseGridStyle}>
            {houses.map((h, i) => {
              const cleanAnalysis = sanitizeHouseAnalysis(h.analysis);
              const bodyParts = String(h?.body_parts || '').trim();
              const issues = Array.isArray(h?.possible_issues)
                ? h.possible_issues.map((x) => String(x || '').trim()).filter(Boolean)
                : [];
              return (
                <article key={`h-${i}`} style={houseCardStyle}>
                  <p style={houseTitleStyle}>{getHouseHeading(h.house, h.name)}</p>
                  {h.sign ? <p style={textStyle}>Rashi: {h.sign}</p> : null}
                  {h.lord ? <p style={textStyle}>Lord: {h.lord}</p> : null}
                  {bodyParts ? <p style={textStyle}>Body Parts: {bodyParts}</p> : null}
                  {issues.length > 0 ? <p style={textStyle}>Possible Issues: {issues.join(', ')}</p> : null}
                  {/* Health Note removed as per user request */}
                  {cleanAnalysis ? <p style={textStyle}>{cleanAnalysis}</p> : null}
                  {h.prediction ? <p style={{ ...textStyle, color: '#fef08a' }}>{dedupeSentences(h.prediction)}</p> : null}
                  {(h.advice || h.upay) ? <p style={{ ...textStyle, color: '#86efac' }}>Upay: {h.advice || h.upay}</p> : null}
                </article>
              );
            })}
          </div>
        </>
      ) : null}
    </section>
  );
}

function DashaSection({ prediction, loading, error }) {
  return (
    <section style={sectionStyle}>
      <h2 style={sectionTitleStyle}>Dasha Detailed Prediction</h2>
      {loading ? <p style={textStyle}>Dasha details generate ho rahi hain...</p> : null}
      {!loading && error ? <p style={errorStyle}>{error}</p> : null}
      {!loading && !error && prediction ? <p style={textStyle}>{prediction}</p> : null}
      {!loading && !error && !prediction ? <p style={mutedStyle}>Dasha detailed prediction unavailable.</p> : null}
    </section>
  );
}

/**
 * Closing price shown in the currency and unit the exchange actually quotes,
 * with an indicative INR conversion for USD-quoted instruments.
 *
 * The old table hard-coded "Price (Rs.)" and per-gram / per-kg / per-quintal
 * rows for every instrument. Those symbols are USD-quoted (COMEX gold is USD
 * per troy ounce, CBOT wheat is US cents per bushel, Nifty is index points),
 * so the headline figure was wrong in both currency and magnitude.
 */
function PriceBreakdownTable({ result }) {
  const currency = String(result.price_currency || '').trim();
  const unit = result.price_base_unit || 'unit';
  const fmt = (v) => (v === null || v === undefined ? null : Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2
  }));

  const rows = [
    { label: `Prati ${unit}`, native: result.price_per_base_unit, inr: result.price_inr_per_base_unit },
    { label: 'Prati gram', native: result.price_per_gram, inr: result.price_inr_per_gram },
    { label: 'Prati kilo', native: result.price_per_kg, inr: result.price_inr_per_kg },
    { label: 'Prati quintal', native: result.price_per_quintal, inr: result.price_inr_per_quintal }
  ].filter((r) => r.native !== null && r.native !== undefined);

  const showInr = currency !== 'INR' && rows.some((r) => r.inr !== null && r.inr !== undefined);
  const move = result.historical_change_percent !== null && result.historical_change_percent !== undefined
    ? `${Math.abs(Number(result.historical_change_percent)).toFixed(2)}%`
    : 'N/A';

  return (
    <>
      <p style={textStyle}>
        Closing Figure: {currency} {fmt(result.price_per_base_unit ?? result.historical_close_rate)} per {unit}
        {' | '}Direction: {String(result.historical_market_direction || 'neutral').toUpperCase()}
        {' | '}Move: {move}
        {result.quote_symbol ? ` | Source: ${result.quote_symbol}` : ''}
      </p>

      {rows.length > 0 ? (
        <div style={{ overflowX: 'auto' }}>
          <table style={kpTableStyle}>
            <thead>
              <tr>
                <th style={kpThStyle}>Unit</th>
                <th style={kpThStyle}>Price ({currency || '-'})</th>
                {showInr ? <th style={kpThStyle}>Approx INR</th> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label}>
                  <td style={kpTdStyle}>{r.label}</td>
                  <td style={kpTdStyle}>{fmt(r.native) ?? 'N/A'}</td>
                  {showInr ? <td style={kpTdStyle}>{fmt(r.inr) ?? 'N/A'}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {showInr ? (
        <p style={mutedStyle}>
          INR figures convert the international price
          {result.price_fx_usd_inr ? ` at ${Number(result.price_fx_usd_inr).toFixed(2)} USD/INR` : ''}.
          Indian retail rates additionally carry import duty, GST and a local premium.
        </p>
      ) : null}
    </>
  );
}

function TeziMandiPanel({ formData }) {
  const [product, setProduct] = useState('Gold');
  const [targetDate, setTargetDate] = useState(toLocalDateString(new Date()));
  const [productSuggestions, setProductSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState(() => {
    try {
      const raw = safeGet(TEZI_MANDI_HISTORY_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });

  const dateSuggestions = useMemo(() => {
    const base = new Date();
    const fmt = toLocalDateString;
    const add = (n) => {
      const x = new Date(base);
      x.setDate(x.getDate() + n);
      return x;
    };
    const monthEnd = new Date(base.getFullYear(), base.getMonth() + 1, 0);
    return [
      { label: 'Aaj', value: fmt(base) },
      { label: 'Kal', value: fmt(add(1)) },
      { label: '3 din baad', value: fmt(add(3)) },
      { label: '7 din baad', value: fmt(add(7)) },
      { label: 'Mahine ka antim din', value: fmt(monthEnd) }
    ];
  }, []);

  const normalizeSignalMeta = (res) => {
    const raw = String(res?.signal || '').toUpperCase();
    if (raw === 'TEZI') {
      return { signal: 'BUY', hi: 'Kharid (Buy)', en: 'Buy', legacy: true };
    }
    if (raw === 'MANDI') {
      return { signal: 'SELL', hi: 'Bikri (Sell)', en: 'Sell', legacy: true };
    }
    if (raw === 'STHIR') {
      return { signal: 'NO_TRADE', hi: 'No Trade', en: 'No Trade', legacy: true };
    }

    const normalized = raw || 'NO_TRADE';
    const hiMap = {
      STRONG_BUY: 'Majboot Kharid (Strong Buy)',
      BUY: 'Kharid (Buy)',
      SELL: 'Bikri (Sell)',
      NO_TRADE: 'No Trade'
    };
    const enMap = {
      STRONG_BUY: 'Strong Buy',
      BUY: 'Buy',
      SELL: 'Sell',
      NO_TRADE: 'No Trade'
    };
    return {
      signal: normalized,
      hi: hiMap[normalized] || (res?.display_signal_hi || normalized),
      en: enMap[normalized] || (res?.display_signal_en || normalized),
      legacy: false
    };
  };

  const updateProductWithSuggestions = (value) => {
    setProduct(value);
    const q = value.trim().toLowerCase();
    if (q.length < 3) {
      setProductSuggestions([]);
      return;
    }
    setProductSuggestions(
      TEZI_COMMODITY_SUGGESTIONS.filter((item) => item.toLowerCase().includes(q)).slice(0, 8)
    );
  };

  const runPrediction = async () => {
    if (!product.trim()) {
      setError('Commodity/Product ka naam zaroor bharein.');
      return;
    }

    if (!formData?.dob || !formData?.tob) {
      setError('Pehle home page par janam vivaran bharein, tabhi Tezi-Mandi chalega.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    try {
      // Compare against null/undefined, not truthiness: latitude or longitude
      // of exactly 0 is a valid coordinate (equator / prime meridian).
      const toCoord = (value) => (
        value === null || value === undefined || value === '' || Number.isNaN(Number(value))
          ? null
          : Number(value)
      );

      const payload = {
        first_name: formData?.first_name || 'User',
        dob: formData?.dob,
        tob: formData?.tob,
        place: formData?.place,
        lat: toCoord(formData?.lat),
        lng: toCoord(formData?.lng),
        language: formData?.language || 'hi',
        product: product.trim(),
        target_date: targetDate,
      };

      const res = await postWithFallback('/tezi-mandi', payload);
      const meta = normalizeSignalMeta(res);
      const nextResult = {
        ...res,
        signal: meta.signal,
        display_signal_hi: meta.hi,
        display_signal_en: meta.en,
        _legacy_signal_detected: meta.legacy
      };
      setResult(nextResult);

      const entry = {
        product: nextResult.product || product.trim(),
        target_date: nextResult.target_date || targetDate,
        signal: nextResult.display_signal_hi || nextResult.signal,
        summary: nextResult.mode === 'historical'
          ? `${nextResult.historical_session_date || nextResult.target_date} close ${nextResult.price_currency || ''} ${nextResult.price_per_base_unit ?? nextResult.historical_close_rate ?? '-'} per ${nextResult.price_base_unit || 'unit'} | ${nextResult.historical_market_direction || 'neutral'}`.replace(/\s+/g, ' ')
          : `Up ${nextResult.chance_up_percent ?? '-'}% | Neutral ${nextResult.chance_neutral_percent ?? '-'}% | Down ${nextResult.chance_down_percent ?? '-'}%`,
        created_at: new Date().toISOString(),
      };
      const nextHistory = [entry, ...history].slice(0, 8);
      setHistory(nextHistory);
      safeSet(TEZI_MANDI_HISTORY_KEY, JSON.stringify(nextHistory));
    } catch (e) {
      console.error('Tezi-Mandi request failed:', e);
      setError('Server se connection nahi ho paya. Kripya thodi der baad try karein.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section style={sectionStyle}>
      <h2 style={sectionTitleStyle}>Tezi-Mandi Sanket</h2>
      <p style={mutedStyle}>Product aur date dijiye. Past date par us din ka bazaar rujhan, future date par tezi-mandi sanket milega.</p>

      <div style={teziGridStyle}>
        <div>
          <label style={labelStyle}>Product / Commodity</label>
          <input
            value={product}
            onChange={(e) => updateProductWithSuggestions(e.target.value)}
            placeholder="Gold, Silver, Crude Oil, Nifty, Soybean..."
            style={inputStyle}
            list="tezi-product-list"
          />
          <datalist id="tezi-product-list">
            {productSuggestions.map((item) => <option key={item} value={item} />)}
          </datalist>
          {product.trim().length >= 3 && productSuggestions.length > 0 ? (
            <div style={chipRowStyle}>
              {productSuggestions.map((item) => (
                <button
                  key={`s-${item}`}
                  type="button"
                  style={chipStyle}
                  onClick={() => {
                    setProduct(item);
                    setProductSuggestions([]);
                  }}
                >
                  {item}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div>
          <label style={labelStyle}>Date</label>
          <input type="date" style={inputStyle} value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
          <div style={chipRowStyle}>
            {dateSuggestions.map((d) => (
              <button
                key={d.value}
                type="button"
                style={targetDate === d.value ? activeChipStyle : chipStyle}
                onClick={() => setTargetDate(d.value)}
              >
                {d.label}: {d.value}
              </button>
            ))}
          </div>
        </div>
      </div>

      <button style={buttonStyle} onClick={runPrediction} disabled={loading}>
        {loading ? 'Ganana chal rahi hai...' : 'Tezi-Mandi Check karein'}
      </button>

      {error ? <p style={errorStyle}>{error}</p> : null}

      {result ? (
        <div style={sectionInnerStyle}>
          <h3 style={smallHeadStyle}>
            {result.mode === 'historical'
              ? `Us din ka bazaar rujhan: ${result.display_signal_hi || result.signal}`
              : `Sanket: ${result.display_signal_hi || result.signal}`}
          </h3>
          {result.mode === 'historical' && result.historical_phase_label ? (
            <p
              style={{
                ...textStyle,
                display: 'inline-block',
                padding: '6px 10px',
                borderRadius: 999,
                border: '1px solid rgba(148,163,184,0.35)',
                background:
                  String(result.historical_phase_label).toUpperCase() === 'BULL'
                    ? 'rgba(22,163,74,0.22)'
                    : String(result.historical_phase_label).toUpperCase() === 'BEAR'
                      ? 'rgba(220,38,38,0.24)'
                      : String(result.historical_phase_label).toUpperCase() === 'VOLATILE'
                        ? 'rgba(245,158,11,0.24)'
                        : 'rgba(71,85,105,0.24)',
                color:
                  String(result.historical_phase_label).toUpperCase() === 'BULL'
                    ? '#86efac'
                    : String(result.historical_phase_label).toUpperCase() === 'BEAR'
                      ? '#fca5a5'
                      : String(result.historical_phase_label).toUpperCase() === 'VOLATILE'
                        ? '#fcd34d'
                        : '#cbd5e1'
              }}
            >
              Historical Phase: {String(result.historical_phase_label).toUpperCase()}
            </p>
          ) : null}
          <p style={textStyle}>{result.summary}</p>
          {result.mode === 'historical' && result.historical_close_rate !== null && result.historical_close_rate !== undefined ? (
            <PriceBreakdownTable result={result} />
          ) : null}
          {result.mode !== 'historical' ? (
            <p style={textStyle}>
              Up: {result.chance_up_percent ?? '-'}% | Neutral: {result.chance_neutral_percent ?? '-'}% | Down: {result.chance_down_percent ?? '-'}% | Highest: {String(result.strongest_probability_side || '').toUpperCase()}
            </p>
          ) : null}
          {result.investment_advice ? <p style={textStyle}>{result.investment_advice}</p> : null}
          {result.investment_advice_engine ? (
            <p style={mutedStyle}>
              Investment Action: {String(result.investment_advice_engine.action || 'avoid').toUpperCase()} | Reasons: {Array.isArray(result.investment_advice_engine.reason) && result.investment_advice_engine.reason.length > 0 ? result.investment_advice_engine.reason.join(' | ') : 'N/A'}
            </p>
          ) : null}
          <p style={mutedStyle}>
            Confidence: {result.confidence ?? '-'}% | Volatility: {result.volatility || '-'}
            {Array.isArray(result.karaka_planets) && result.karaka_planets.length
              ? ` | Karaka: ${result.karaka_planets.join(', ')}`
              : ''}
          </p>
          <h3 style={smallHeadStyle}>Graha Drivers</h3>
          <ul style={listStyle}>
            {(result.drivers || []).map((d, i) => <li key={`d-${i}`} style={listItemStyle}>{d}</li>)}
          </ul>
        </div>
      ) : null}

      {history.length > 0 ? (
        <div style={sectionInnerStyle}>
          <h3 style={smallHeadStyle}>Recent Predictions</h3>
          <ul style={listStyle}>
            {history.map((h, i) => (
              <li key={`h-${i}`} style={listItemStyle}>
                {h.target_date} | {h.product} | {h.signal} - {h.summary}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function SectionQAPanel({ section, language, contextText }) {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [isDetailed, setIsDetailed] = useState(false);

  const askQuestion = async () => {
    if (!question.trim()) {
      setError('Kripya apna prashna likhein.');
      return;
    }

    setLoading(true);
    setError('');
    setAnswer('');

    try {
      const res = await postWithFallback('/section-qa', {
        section,
        question,
        language,
        context: contextText,
        answer_mode: isDetailed ? 'detailed' : 'short'
      });
      setAnswer(String(res?.answer || '').trim() || 'Uttar uplabdh nahi hai.');
    } catch (e) {
      console.error('Section Q&A request failed:', e);
      setError('Server se connection nahi ho paya. Kripya thodi der baad try karein.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section style={sectionStyle}>
      <h2 style={sectionTitleStyle}>Section Q&A</h2>
      <p style={mutedStyle}>Current Section: {section}</p>
      <p style={mutedStyle}>Answer language follows your question pattern: Hindi / English / Hinglish.</p>
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Apna prashna yahan likhein..."
        style={textAreaStyle}
      />
      <div style={rowWrapStyle}>
        <label style={checkboxLabelStyle}>
          <input type="checkbox" checked={isDetailed} onChange={(e) => setIsDetailed(e.target.checked)} />
          Detailed Uttar
        </label>
        <button style={buttonStyle} onClick={askQuestion} disabled={loading}>
          {loading ? 'Uttar taiyaar ho raha hai...' : 'Uttar Prapt Karein'}
        </button>
      </div>
      {error ? <p style={errorStyle}>{error}</p> : null}
      {answer ? <div style={sectionInnerStyle}><p style={textStyle}>{answer}</p></div> : null}
    </section>
  );
}

function SectionRapidGuidance({ activeModule, data, dashaPrediction }) {
  const moduleMeta = {
    janam: {
      title: 'Tatkal Margdarshan - Janam Kundli',
      question: 'Meri janam kundli ke hisab se mera asli growth focus kya hai?',
      defaultAnswer: 'Aapka growth focus mool svabhav, parivarik santulan aur long-term discipline par rakhein.'
    },
    gochar: {
      title: 'Tatkal Margdarshan - Gochar Kundli',
      question: 'Agle 1-3 mahine me kaunse badlav par turant kaam karna chahiye?',
      defaultAnswer: 'Gochar ke hisab se timing-sensitive kadam phased tareeke se lein.'
    },
    prashna: {
      title: 'Tatkal Margdarshan - Prashna Kundli',
      question: 'Mere current prashn ka practical agla kadam kya hona chahiye?',
      defaultAnswer: 'Current prashn ke liye short-cycle aur measurable action plan follow karein.'
    },
    dasha: {
      title: 'Tatkal Margdarshan - Dasha',
      question: 'Chal rahi dasha ka sabse practical upyog kaise karun?',
      defaultAnswer: 'Dasha ke core theme par consistent karmic discipline rakhein.'
    }
  };

  const meta = moduleMeta[activeModule];
  if (!meta) return null;

  const blockMap = {
    janam: data?.janam_kundli,
    gochar: data?.gochar_kundli,
    prashna: data?.prashna_kundli
  };

  const block = blockMap[activeModule] || {};
  const answerText = buildQuickPairAnswer(activeModule, data, dashaPrediction) || meta.defaultAnswer;
  const actions = Array.isArray(block?.next_steps) ? [...new Set(block.next_steps.map((x) => String(x).trim()).filter(Boolean))].slice(0, 5) : [];
  const highlights = Array.isArray(block?.houses)
    ? [...new Set(
      block.houses
        .map((h) => String(h?.prediction || '').split('.').map((s) => s.trim()).filter(Boolean)[0])
        .filter(Boolean)
    )].slice(0, 3)
    : [];

  const summary = activeModule === 'janam'
    ? 'Janam drishti: jeevan ki mool disha aur personality alignment par kendrit margdarshan.'
    : activeModule === 'gochar'
      ? 'Gochar drishti: vartaman samay ke activation aur timing windows par kendrit margdarshan.'
      : activeModule === 'prashna'
        ? 'Prashna drishti: turant parinaam aur practical decision clarity par kendrit margdarshan.'
        : 'Dasha drishti: chalit dasha ke phase-anusar focus aur discipline ka margdarshan.';

  return (
    <section style={sectionStyle}>
      <h2 style={sectionTitleStyle}>{meta.title}</h2>
      <p style={mutedStyle}>{summary}</p>

      <div style={sectionInnerStyle}>
        <h3 style={smallHeadStyle}>Guru Ji ka Turant Sujhav</h3>
        <p style={textStyle}><strong>Q:</strong> {meta.question}</p>
        <p style={textStyle}><strong>A:</strong> {answerText}</p>
      </div>

      {actions.length > 0 ? (
        <div style={sectionInnerStyle}>
          <h3 style={smallHeadStyle}>Priority Actions</h3>
          <ul style={listStyle}>{actions.map((a, i) => <li key={`a-${i}`} style={listItemStyle}>{a}</li>)}</ul>
        </div>
      ) : null}

      {highlights.length > 0 ? (
        <div style={sectionInnerStyle}>
          <h3 style={smallHeadStyle}>Section Highlights</h3>
          <ul style={listStyle}>{highlights.map((h, i) => <li key={`h-${i}`} style={listItemStyle}>{h}</li>)}</ul>
        </div>
      ) : null}
    </section>
  );
}

function RemediesPage({ onLogout }) {
  const [savedData, setSavedData] = useState(null);

  useEffect(() => {
    const raw = safeGet(LATEST_KUNDLI_KEY);
    if (!raw) return;
    try {
      setSavedData(JSON.parse(raw));
    } catch {
      setSavedData(null);
    }
  }, []);

  const remedies = collectRemedies(savedData);

  return (
    <div style={pageStyle}>
      <Brand />
      <div style={{ ...cardStyle, maxWidth: 1100 }}>
        <div style={rowBetweenStyle}>
          <h2 style={titleStyle}>Remedies</h2>
          <div style={rowWrapStyle}>
            <button style={secondaryButtonStyle} onClick={() => { window.location.hash = '#home'; }}>Home</button>
            <button style={secondaryButtonStyle} onClick={onLogout}>Logout</button>
          </div>
        </div>

        <SectionQAPanel
          section="Remedies"
          language="hi"
          contextText={JSON.stringify({ remedies }).slice(0, 6000)}
        />

        <section style={sectionStyle}>
          <h2 style={sectionTitleStyle}>Suggested Remedies</h2>
          {remedies.length ? (
            <ul style={listStyle}>
              {remedies.map((r, i) => <li key={`rr-${i}`} style={listItemStyle}>{r}</li>)}
            </ul>
          ) : <p style={mutedStyle}>Kundli open karne ke baad remedies yahan dikhengi.</p>}
        </section>
      </div>
    </div>
  );
}

function formatSavedAt(isoString) {
  const d = new Date(String(isoString || ''));
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString();
}

/**
 * Readings saved server-side against the signed-in account, so they follow the
 * user across devices instead of living only in one browser's localStorage.
 */
function HistoryPage({ onLogout }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiRequest('/history', { method: 'GET', timeoutMs: 20000 });
      setItems(Array.isArray(res?.items) ? res.items : []);
    } catch (e) {
      setError(`Saved reports load nahi ho paaye: ${String(e?.message || e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const openReport = async (id) => {
    setBusyId(id);
    setError('');
    try {
      const res = await apiRequest(`/history/${id}`, { method: 'GET', timeoutMs: 20000 });
      if (!res?.report) throw new Error('Report khali hai.');
      safeSet(LATEST_KUNDLI_KEY, JSON.stringify(res.report));
      window.location.hash = '#saved';
    } catch (e) {
      setError(`Report khul nahi paayi: ${String(e?.message || e)}`);
    } finally {
      setBusyId(null);
    }
  };

  const deleteReport = async (id) => {
    if (!window.confirm('Ye report delete karein?')) return;
    setBusyId(id);
    setError('');
    try {
      await apiRequest(`/history/${id}`, { method: 'DELETE', timeoutMs: 20000 });
      setItems((prev) => prev.filter((it) => it.id !== id));
    } catch (e) {
      setError(`Report delete nahi ho paayi: ${String(e?.message || e)}`);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div style={pageStyle}>
      <Brand />
      <div style={{ ...cardStyle, maxWidth: 1100 }}>
        <div style={rowBetweenStyle}>
          <h2 style={titleStyle}>Saved Reports</h2>
          <div style={rowWrapStyle}>
            <button style={secondaryButtonStyle} onClick={() => { window.location.hash = '#home'; }}>Home</button>
            <button style={secondaryButtonStyle} onClick={loadHistory} disabled={loading}>Refresh</button>
            <button style={secondaryButtonStyle} onClick={onLogout}>Logout</button>
          </div>
        </div>

        <p style={mutedStyle}>
          Aapki kundli reports account ke saath save hoti hain, isliye kisi bhi device par milengi.
        </p>

        {error ? <p style={errorStyle}>{error}</p> : null}

        <section style={sectionStyle}>
          {loading ? <p style={textStyle}>Saved reports load ho rahe hain...</p> : null}
          {!loading && items.length === 0 && !error ? (
            <p style={mutedStyle}>Abhi koi saved report nahi hai. Ek kundli banayein, wo yahan apne aap save ho jayegi.</p>
          ) : null}
          {!loading && items.length > 0 ? (
            <div style={houseGridStyle}>
              {items.map((it) => (
                <article key={`hist-${it.id}`} style={houseCardStyle}>
                  <p style={houseTitleStyle}>{it.person_name || 'Unnamed'}</p>
                  <p style={textStyle}>{it.title}</p>
                  <p style={mutedStyle}>
                    {it.dob}{it.tob ? ` ${it.tob}` : ''}{it.place ? ` | ${it.place}` : ''}
                  </p>
                  <p style={mutedStyle}>Saved: {formatSavedAt(it.created_at)}</p>
                  <div style={rowWrapStyle}>
                    <button
                      style={secondaryButtonStyle}
                      onClick={() => openReport(it.id)}
                      disabled={busyId === it.id}
                    >
                      {busyId === it.id ? 'Kholi ja rahi hai...' : 'Kholein'}
                    </button>
                    <button
                      style={secondaryButtonStyle}
                      onClick={() => deleteReport(it.id)}
                      disabled={busyId === it.id}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function RemedyNotice() {
  return (
    <div style={tickerStyle}>
      Guru Vani: Upay aur guidance spiritual direction ke liye hai. Financial nirnay apni research ke saath hi lein.
    </div>
  );
}

function FloatingGuruPhoto() {
  return (
    <div style={floatingGuruWrapStyle}>
      <img
        src={GURU_IMAGE_CANDIDATES[0]}
        data-fallbacks={GURU_IMAGE_CANDIDATES.slice(1).join('|')}
        onError={handleImageFallback}
        alt="Guru"
        style={floatingGuruImgStyle}
      />
    </div>
  );
}

const pageStyle = {
  minHeight: '100vh',
  background: 'radial-gradient(circle at 15% 10%, rgba(14,116,144,0.22), transparent 45%), radial-gradient(circle at 85% 18%, rgba(30,64,175,0.2), transparent 42%), linear-gradient(165deg, #020617, #0f172a 55%, #111827)',
  color: '#e5e7eb',
  // Safe-area insets keep content clear of the Android/iOS status bar and the
  // home indicator when the app runs full-screen inside the native shell.
  paddingTop: 'calc(22px + env(safe-area-inset-top, 0px))',
  paddingRight: 'calc(18px + env(safe-area-inset-right, 0px))',
  paddingBottom: 'calc(110px + env(safe-area-inset-bottom, 0px))',
  paddingLeft: 'calc(18px + env(safe-area-inset-left, 0px))',
  fontFamily: "Calibri, 'Segoe UI', Arial, sans-serif"
};

const heroTopStyle = {
  maxWidth: 1120,
  margin: '0 auto 14px',
  color: '#67e8f9',
  fontFamily: "Calibri, 'Segoe UI', Arial, sans-serif",
  letterSpacing: '1px',
  fontSize: 28,
  fontWeight: 700
};

const cardStyle = {
  maxWidth: 760,
  margin: '0 auto',
  border: '1px solid rgba(56,189,248,0.4)',
  borderRadius: 16,
  padding: 16,
  background: 'linear-gradient(155deg, rgba(15,23,42,0.84), rgba(10,25,63,0.66))',
  boxShadow: '0 16px 34px rgba(2,6,23,0.45)'
};

const loginCenterStyle = {
  maxWidth: 1120,
  margin: '0 auto',
  display: 'flex',
  justifyContent: 'center',
  alignItems: 'flex-start',
  padding: '10px 0 40px'
};

const deityRowStyle = {
  display: 'flex',
  gap: 10,
  justifyContent: 'center',
  marginBottom: 12
};

const deityImgStyle = {
  width: '46%',
  maxWidth: 160,
  height: 130,
  objectFit: 'contain',
  borderRadius: 12
};

const avatarWrapStyle = {
  display: 'flex',
  justifyContent: 'center',
  marginBottom: 10
};

const avatarStyle = {
  width: 130,
  height: 130,
  borderRadius: '50%',
  objectFit: 'contain'
};

const titleStyle = { margin: '0 0 10px', color: '#f8fafc', fontFamily: "Calibri, 'Segoe UI', Arial, sans-serif" };
const subStyle = { margin: '0 0 12px', color: '#bae6fd' };
const labelStyle = { display: 'block', margin: '10px 0 6px', color: '#93c5fd', fontSize: 15 };

const inputStyle = {
  width: '100%',
  borderRadius: 10,
  border: '1px solid rgba(148,163,184,0.45)',
  background: 'rgba(2,6,23,0.45)',
  color: '#e5e7eb',
  padding: '10px 12px',
  fontSize: 15
};

const buttonStyle = {
  marginTop: 14,
  borderRadius: 10,
  border: '1px solid rgba(45,212,191,0.5)',
  background: 'linear-gradient(135deg, rgba(13,148,136,0.85), rgba(59,130,246,0.85))',
  color: '#f8fafc',
  padding: '10px 14px',
  cursor: 'pointer',
  fontWeight: 700
};

const secondaryButtonStyle = {
  borderRadius: 10,
  border: '1px solid rgba(56,189,248,0.45)',
  background: 'rgba(2,132,199,0.15)',
  color: '#bae6fd',
  padding: '8px 12px',
  cursor: 'pointer'
};

const msgStyle = { marginTop: 10, color: '#a7f3d0' };
const errorStyle = { marginTop: 10, color: '#fca5a5' };
const warnStyle = { marginBottom: 12, color: '#fcd34d' };

const rowBetweenStyle = {
  display: 'flex',
  gap: 12,
  justifyContent: 'space-between',
  alignItems: 'center',
  flexWrap: 'wrap'
};

const rowWrapStyle = { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' };

const moduleWrapStyle = {
  display: 'flex',
  gap: 8,
  flexWrap: 'wrap',
  margin: '10px 0 18px'
};

const moduleButtonStyle = (active) => ({
  borderRadius: 999,
  border: active ? '1px solid #22d3ee' : '1px solid rgba(148,163,184,0.45)',
  background: active ? 'rgba(6,182,212,0.2)' : 'rgba(2,6,23,0.45)',
  color: active ? '#a5f3fc' : '#cbd5e1',
  padding: '7px 12px',
  cursor: 'pointer'
});

const sectionStyle = {
  marginTop: 14,
  border: '1px solid rgba(148,163,184,0.35)',
  borderRadius: 14,
  padding: 14,
  background: 'rgba(15,23,42,0.58)'
};

const sectionInnerStyle = {
  marginTop: 10,
  border: '1px solid rgba(148,163,184,0.25)',
  borderRadius: 12,
  padding: 12,
  background: 'rgba(2,6,23,0.35)'
};

const sectionTitleStyle = {
  margin: '0 0 8px',
  color: '#67e8f9',
  fontFamily: "Calibri, 'Segoe UI', Arial, sans-serif"
};

const smallHeadStyle = { margin: '0 0 8px', color: '#dbeafe' };
const textStyle = { margin: '6px 0', lineHeight: 1.6, color: '#e2e8f0' };
const mutedStyle = { margin: '6px 0', color: '#93c5fd' };

const listStyle = { margin: 0, paddingLeft: 20 };
const listItemStyle = { marginBottom: 8, color: '#cbd5e1', lineHeight: 1.5 };

const houseGridStyle = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
  gap: 10,
  marginTop: 10
};

const houseCardStyle = {
  border: '1px solid rgba(148,163,184,0.3)',
  borderRadius: 10,
  padding: 10,
  background: 'rgba(2,6,23,0.3)'
};

const houseTitleStyle = { margin: '0 0 8px', color: '#93c5fd', fontWeight: 700 };

const kpTableStyle = { width: '100%', borderCollapse: 'collapse', color: '#e5e7eb', fontSize: 14 };
const kpThStyle = { borderBottom: '1px solid #374151', textAlign: 'left', padding: '8px 6px', color: '#bae6fd' };
const kpTdStyle = { borderBottom: '1px solid #1f2937', padding: '8px 6px' };

const textAreaStyle = {
  width: '100%',
  minHeight: 88,
  resize: 'vertical',
  borderRadius: 10,
  border: '1px solid rgba(148,163,184,0.45)',
  background: 'rgba(2,6,23,0.45)',
  color: '#e5e7eb',
  padding: 10,
  fontSize: 15
};

const checkboxLabelStyle = { display: 'flex', alignItems: 'center', gap: 8, color: '#bfdbfe' };

const loadingStyle = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#e2e8f0',
  background: '#0f172a',
  fontSize: 22
};

const errorPageStyle = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#fecaca',
  background: '#0f172a',
  padding: 22,
  textAlign: 'center'
};

const teziGridStyle = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 };
const chipRowStyle = { marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 };

const chipStyle = {
  border: '1px solid rgba(56,189,248,0.5)',
  background: 'rgba(2,132,199,0.12)',
  color: '#7dd3fc',
  borderRadius: 999,
  padding: '4px 10px',
  cursor: 'pointer',
  fontSize: 13
};

const activeChipStyle = { ...chipStyle, border: '1px solid #22d3ee', background: 'rgba(6,182,212,0.2)' };

const tickerStyle = {
  position: 'fixed',
  left: 0,
  right: 0,
  bottom: 0,
  zIndex: 20,
  borderTop: '1px solid rgba(45,212,191,0.35)',
  background: 'rgba(2,6,23,0.92)',
  color: '#a7f3d0',
  padding: '8px 14px calc(8px + env(safe-area-inset-bottom, 0px))',
  textAlign: 'center',
  fontSize: 14
};

const floatingGuruWrapStyle = {
  position: 'fixed',
  right: 14,
  bottom: 68,
  width: 88,
  height: 88,
  borderRadius: '50%',
  overflow: 'hidden',
  border: '2px solid rgba(45,212,191,0.6)',
  boxShadow: '0 10px 24px rgba(15,23,42,0.7)',
  zIndex: 19
};

const floatingGuruImgStyle = {
  width: '100%',
  height: '100%',
  objectFit: 'contain',
  objectPosition: 'center top',
  background: 'rgba(15,23,42,0.82)'
};

const loadingCardStyle = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  textAlign: 'center',
  maxWidth: 420,
  width: '100%',
  padding: '24px 20px'
};

const loadingAvatarStyle = {
  width: 130,
  height: 130,
  borderRadius: '50%',
  objectFit: 'contain',
  marginBottom: 18,
  animation: 'guruji-blink 2s infinite',
  cursor: 'pointer'
};

const loadingTitleStyle = { fontSize: 20, fontWeight: 700, color: '#f8fafc', marginBottom: 10 };
const loadingMsgStyle = { minHeight: 46, fontSize: 15, color: '#bae6fd', lineHeight: 1.5, marginBottom: 16 };

const progressTrackStyle = {
  position: 'relative',
  width: '100%',
  maxWidth: 280,
  height: 6,
  borderRadius: 999,
  background: 'rgba(148,163,184,0.22)',
  overflow: 'hidden'
};

const progressBarStyle = {
  position: 'absolute',
  top: 0,
  bottom: 0,
  left: '-42%',
  width: '42%',
  borderRadius: 999,
  background: 'linear-gradient(90deg, rgba(13,148,136,0.9), rgba(59,130,246,0.95))',
  animation: 'medha-progress-slide 1.25s ease-in-out infinite'
};

const loadingHintStyle = { fontSize: 13, color: '#93c5fd', marginTop: 14, lineHeight: 1.5 };

const KUNDLI_LOADING_MESSAGES = [
  'Aapke janm-vivaran se kundli banayi ja rahi hai...',
  'Grah, rashi aur nakshatra ki sthiti compute ho rahi hai...',
  'Bhaav aur Vimshottari dasha timeline taiyaar ho rahi hai...',
  'Guru Ji aapke chart ka vishleshan likh rahe hain...',
  'Antim sanket, timing aur upay jode ja rahe hain...'
];

function KundliLoadingScreen({ avatar, onAvatarClick }) {
  const [msgIdx, setMsgIdx] = useState(0);

  useEffect(() => {
    const t = setInterval(() => {
      setMsgIdx((i) => (i + 1) % KUNDLI_LOADING_MESSAGES.length);
    }, 3200);
    return () => clearInterval(t);
  }, []);

  return (
    <div style={loadingStyle}>
      <div style={loadingCardStyle}>
        <img
          src={avatar}
          data-fallbacks={GURU_IMAGE_CANDIDATES.join('|')}
          onError={handleImageFallback}
          alt="Guru Ji"
          onClick={onAvatarClick}
          style={loadingAvatarStyle}
        />
        <div style={loadingTitleStyle}>Guru Ji aapki kundli dekh rahe hain</div>
        <div style={loadingMsgStyle}>{KUNDLI_LOADING_MESSAGES[msgIdx]}</div>
        <div style={progressTrackStyle}>
          <div style={progressBarStyle} />
        </div>
        <div style={loadingHintStyle}>
          Ismein aam taur par 60&ndash;90 second lag sakte hain. Kripya page band na karein.
        </div>
      </div>
      <style>{`
        @keyframes guruji-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.72; } }
        @keyframes medha-progress-slide { 0% { left: -42%; } 100% { left: 100%; } }
      `}</style>
    </div>
  );
}

export default App;

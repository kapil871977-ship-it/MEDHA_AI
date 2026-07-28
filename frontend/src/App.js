import React, { useEffect, useMemo, useState } from 'react';
import './App.css';

const API_BASE_URLS = [
  process.env.REACT_APP_API_URL,
  'http://127.0.0.1:8010'
].filter(Boolean);

const REQUEST_TIMEOUT_MS = 70000;
const KUNDLI_REQUEST_TIMEOUT_MS = 80000;
const DASHA_REQUEST_TIMEOUT_MS = 70000;

const FORM_STORAGE_KEY = 'medha_kundli_form_data';
const AUTH_STORAGE_KEY = 'medha_is_logged_in';
const AUTH_TOKEN_KEY = 'medha_auth_token';
const AUTH_IDENTIFIER_KEY = 'medha_auth_identifier';
const TEZI_MANDI_HISTORY_KEY = 'medha_tezi_mandi_history_v1';
const LATEST_KUNDLI_KEY = 'medha_latest_kundli_response';

const GURU_IMAGE_CANDIDATES = [
  '/jagdacharya-swami-akhileshji-maharaj.jpg',
  '/jagdacharya-swami-akhileshji-maharaj.png',
  '/guru-ji.jpg',
  '/fortune-guru-logo.png'
];

const TEZI_COMMODITY_SUGGESTIONS = [
  'Gold', 'Silver', 'Crude Oil', 'Natural Gas', 'Copper', 'Aluminium',
  'Nifty 50', 'Bank Nifty', 'Sensex', 'USDINR', 'EURINR', 'JPYINR',
  'Soybean', 'Mustard', 'Jeera', 'Turmeric', 'Cotton', 'Sugar', 'Wheat', 'Rice'
];

const HOUSE_NAME_HI = {
  1: 'लग्न भाव',
  2: 'धन भाव',
  3: 'पराक्रम भाव',
  4: 'सुख भाव',
  5: 'पुत्र भाव',
  6: 'रोग भाव',
  7: 'कलत्र भाव',
  8: 'मृत्यु भाव',
  9: 'भाग्य भाव',
  10: 'कर्म भाव',
  11: 'लाभ भाव',
  12: 'व्यय भाव',
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

async function postWithFallback(endpointPath, payload, options = {}) {
  const timeoutMs = options?.timeoutMs || REQUEST_TIMEOUT_MS;
  let lastError = null;

  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;

  for (const baseUrl of API_BASE_URLS) {
    try {
      const res = await fetchWithTimeout(`${baseUrl}${endpointPath}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      }, timeoutMs);

      if (res.status === 401) {
        // Session expired or invalid — clear auth and force re-login.
        localStorage.removeItem(AUTH_TOKEN_KEY);
        localStorage.removeItem(AUTH_IDENTIFIER_KEY);
        localStorage.removeItem(AUTH_STORAGE_KEY);
        if (window.location.hash !== '#login') window.location.hash = '#login';
        throw new Error('Session expired. Kripya dubara login karein.');
      }
      if (res.status === 429) {
        throw new Error('Bahut zyada requests. Kripya ek minute baad try karein.');
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
      if (err?.name === 'AbortError') {
        lastError = new Error(`Request timeout (${Math.round(timeoutMs / 1000)}s) at ${baseUrl}`);
      } else {
        lastError = err;
      }
    }
  }

  throw lastError || new Error('Backend unavailable');
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
  const hiName = HOUSE_NAME_HI[num] || 'भाव';
  const cleanFallback = String(fallbackName || '').trim();
  if (cleanFallback) {
    return `भाव ${num}: ${hiName} (${cleanFallback})`;
  }
  return `भाव ${num}: ${hiName}`;
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

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(Boolean(localStorage.getItem(AUTH_TOKEN_KEY)));
  const [route, setRoute] = useState(window.location.hash || '#home');

  useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash || '#home');
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const handleLogout = () => {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_IDENTIFIER_KEY);
    localStorage.removeItem(AUTH_STORAGE_KEY);
    setIsLoggedIn(false);
    window.location.hash = '#login';
  };

  let page = null;
  if (route === '#login') {
    page = <LoginPage onLoginSuccess={() => setIsLoggedIn(true)} />;
  } else if (route === '#kundli') {
    page = isLoggedIn ? <KundliPage onLogout={handleLogout} /> : <LoginPage onLoginSuccess={() => setIsLoggedIn(true)} />;
  } else if (route === '#remedies') {
    page = isLoggedIn ? <RemediesPage onLogout={handleLogout} /> : <LoginPage onLoginSuccess={() => setIsLoggedIn(true)} />;
  } else {
    page = isLoggedIn ? <HomePage onLogout={handleLogout} /> : <LoginPage onLoginSuccess={() => setIsLoggedIn(true)} />;
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

      localStorage.setItem(AUTH_TOKEN_KEY, res.token);
      localStorage.setItem(AUTH_IDENTIFIER_KEY, res.identifier || emailOrMobile.trim().toLowerCase());
      localStorage.setItem(AUTH_STORAGE_KEY, '1');
      onLoginSuccess();
      window.location.hash = '#home';
    } catch (e) {
      setError(String(e?.message || e || 'Kuch galat ho gaya. Dubara try karein.'));
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !loading) handleSubmit();
  };

  return (
    <div style={pageStyle}>
      <div style={heroTopStyle}>Fortune Guru</div>
      <div style={loginCenterStyle}>
        <section style={{ ...cardStyle, maxWidth: 460, width: '100%' }}>
          <div style={avatarWrapStyle}>
            <img
              src={GURU_IMAGE_CANDIDATES[0]}
              data-fallbacks={GURU_IMAGE_CANDIDATES.slice(1).join('|')}
              onError={handleImageFallback}
              alt="Jagdacharya"
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

function HomePage({ onLogout }) {
  const [message, setMessage] = useState('');
  const [formData, setFormData] = useState(() => {
    try {
      const raw = localStorage.getItem(FORM_STORAGE_KEY);
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

  const openKundliPage = () => {
    if (!formData.first_name || !formData.dob || !formData.tob || !formData.place) {
      setMessage('Naam, DOB, TOB aur Place bharna zaroori hai.');
      return;
    }

    localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(formData));
    const url = `${window.location.origin}${window.location.pathname}#kundli`;
    const newTab = window.open(url, '_blank', 'noopener,noreferrer');

    if (!newTab || newTab.closed || typeof newTab.closed === 'undefined') {
      window.location.hash = '#kundli';
      setMessage('Popup blocked tha, kundli isi tab me khol di gayi hai.');
      return;
    }

    setMessage('Kundli nayi tab me khul gayi hai.');
  };

  return (
    <div style={pageStyle}>
      <div style={heroTopStyle}>Fortune Guru</div>
      <div style={{ ...cardStyle, maxWidth: 860 }}>
        <div style={rowBetweenStyle}>
          <h1 style={titleStyle}>Basic Details Form</h1>
          <button style={secondaryButtonStyle} onClick={onLogout}>Logout</button>
        </div>

        <label style={labelStyle}>Aapka Naam</label>
        <input style={inputStyle} value={formData.first_name} onChange={(e) => setFormData({ ...formData, first_name: e.target.value })} />

        <label style={labelStyle}>Janam Tarikh</label>
        <input type="date" style={inputStyle} value={formData.dob} onChange={(e) => setFormData({ ...formData, dob: e.target.value })} />

        <label style={labelStyle}>Janam Samay</label>
        <input type="time" style={inputStyle} value={formData.tob} onChange={(e) => setFormData({ ...formData, tob: e.target.value })} />

        <label style={labelStyle}>Janam Sthan</label>
        <input style={inputStyle} value={formData.place} onChange={(e) => setFormData({ ...formData, place: e.target.value })} />

        <label style={labelStyle}>Lucky Number (1-9)</label>
        <input
          type="number"
          min="1"
          max="9"
          style={inputStyle}
          value={formData.selected_number}
          onChange={(e) => setFormData({ ...formData, selected_number: parseInt(e.target.value || '1', 10) })}
        />

        <label style={labelStyle}>Language</label>
        <select style={inputStyle} value={formData.language} onChange={(e) => setFormData({ ...formData, language: e.target.value })}>
          <option value="hi">Hindi</option>
          <option value="en">English</option>
        </select>

        <button style={buttonStyle} onClick={openKundliPage}>Kundli Nayi Page Mein Kholen</button>
        {message ? <p style={msgStyle}>{message}</p> : null}
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

function KundliPage({ onLogout }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [warning, setWarning] = useState('');
  const [data, setData] = useState(null);
  const [dashaPrediction, setDashaPrediction] = useState('');
  const [dashaLoading, setDashaLoading] = useState(false);
  const [dashaError, setDashaError] = useState('');
  const [activeModule, setActiveModule] = useState('janam');

  const formData = useMemo(() => {
    const raw = localStorage.getItem(FORM_STORAGE_KEY);
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
          localStorage.setItem(LATEST_KUNDLI_KEY, JSON.stringify(result));
          setLoading(false);
          setDashaLoading(true);
        }

        try {
          const dashaResult = await postWithFallback('/full-analysis', formData, { timeoutMs: DASHA_REQUEST_TIMEOUT_MS });
          if (!cancelled) {
            const rawDashaText = String(dashaResult?.prediction || '').trim();
            const safeDashaText = formatDashaErrorText(rawDashaText);
            const lower = safeDashaText.toLowerCase();
            if (lower.includes('temporary') || lower.includes('unavailable') || lower.includes('retry') || lower.includes('quota')) {
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
        if (!cancelled) {
          const cachedRaw = localStorage.getItem(LATEST_KUNDLI_KEY);
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
            setWarning(`Live kundli abhi load nahi hui: ${String(e.message || e)}. Last saved report dikhayi ja rahi hai.`);
          } else {
            setError(`Kundli load nahi ho paayi: ${String(e.message || e)}`);
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    run();
    return () => { cancelled = true; };
  }, [formData]);


  // Guruji avatar and voice activation UI

  const [gurujiSpeaking, setGurujiSpeaking] = useState(false);
  const [gurujiAudio, setGurujiAudio] = useState(null);
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

  // Play Guruji audio (original or cloned)
  const playGurujiAudio = (type) => {
    if (gurujiAudio) {
      gurujiAudio.pause();
      setGurujiAudio(null);
    }
    let src = '';
    if (type === 'original') src = '/guruji/guruji_original.mpeg';
    else if (type === 'cloned') src = '/guruji/guruji_cloned.mpeg';
    if (src) {
      const audio = new window.Audio(src);
      setGurujiAudio(audio);
      setGurujiSpeaking(true);
      audio.onended = () => setGurujiSpeaking(false);
      audio.play();
    }
  };


  if (loading) return (
    <KundliLoadingScreen
      avatar={gurujiAvatar}
      onAvatarClick={handleAvatarClick}
      onPlay={playGurujiAudio}
    />
  );

  if (error) {
    return (
      <div style={errorPageStyle}>
        <img
          src={gurujiAvatar}
          alt="Guruji"
          style={{ width: 120, borderRadius: '50%', marginBottom: 16, animation: 'guruji-blink 2s infinite', cursor: 'pointer' }}
          onClick={handleAvatarClick}
        />
        <div>{error}</div>
        <div style={{ marginTop: 12, display: 'flex', gap: 8, flexDirection: 'column' }}>
          <button onClick={() => playGurujiAudio('original')}>Guruji Original Voice</button>
          <button onClick={() => playGurujiAudio('cloned')}>Guruji Cloned Voice</button>
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
      <div style={heroTopStyle}>Fortune Guru</div>
      <div style={{ ...cardStyle, maxWidth: 1120 }}>
        <div style={rowBetweenStyle}>
          <h1 style={titleStyle}>{data?.title || 'Trividha Kundli Vishleshan'}</h1>
          <button style={secondaryButtonStyle} onClick={onLogout}>Logout</button>
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

function KundliSection({ title, block }) {
  const houses = Array.isArray(block?.houses) ? block.houses : [];
  // Remove unwanted fallback phrase from predictions
  const cleanPrediction = (text) => {
    if (!text) return '';
    return String(text).replace(/Detailed Janam Kundli fallback: viewed across past-present-future,? ?/i, '');
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
              const healthNote = String(h?.health_note || '').trim();
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

function TeziMandiPanel({ formData }) {
  const [product, setProduct] = useState('Gold');
  const [targetDate, setTargetDate] = useState(new Date().toISOString().slice(0, 10));
  const [productSuggestions, setProductSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState(() => {
    try {
      const raw = localStorage.getItem(TEZI_MANDI_HISTORY_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });

  const dateSuggestions = useMemo(() => {
    const base = new Date();
    const fmt = (d) => d.toISOString().slice(0, 10);
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

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const payload = {
        first_name: formData?.first_name || 'User',
        dob: formData?.dob,
        tob: formData?.tob,
        place: formData?.place,
        lat: formData?.lat ? Number(formData.lat) : null,
        lng: formData?.lng ? Number(formData.lng) : null,
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
        product: nextResult.product,
        target_date: nextResult.target_date,
        signal: nextResult.display_signal_hi || nextResult.signal,
        summary: nextResult.mode === 'historical'
          ? `${nextResult.historical_session_date || nextResult.target_date} close Rs ${nextResult.price_per_base_unit ?? nextResult.historical_close_rate ?? '-'} per ${nextResult.price_base_unit || 'unit'} | ${nextResult.historical_market_direction || 'neutral'}`
          : `Up ${nextResult.chance_up_percent ?? '-'}% | Neutral ${nextResult.chance_neutral_percent ?? '-'}% | Down ${nextResult.chance_down_percent ?? '-'}%`,
        created_at: new Date().toISOString(),
      };
      const nextHistory = [entry, ...history].slice(0, 8);
      setHistory(nextHistory);
      localStorage.setItem(TEZI_MANDI_HISTORY_KEY, JSON.stringify(nextHistory));
    } catch (e) {
      setError(`Tezi-Mandi error: ${String(e?.message || e)}`);
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
            <>
              <p style={textStyle}>
                Closing Figure: Rs {Number(result.price_per_base_unit ?? result.historical_close_rate).toFixed(2)} per {result.price_base_unit || 'unit'} | Direction: {String(result.historical_market_direction || 'neutral').toUpperCase()} | Move: {result.historical_change_percent !== null && result.historical_change_percent !== undefined ? `${Math.abs(Number(result.historical_change_percent)).toFixed(2)}%` : 'N/A'}
              </p>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', color: '#e5e7eb', marginTop: 8 }}>
                  <thead>
                    <tr>
                      <th style={{ borderBottom: '1px solid #374151', textAlign: 'left', padding: '8px 6px' }}>Unit (इकाई)</th>
                      <th style={{ borderBottom: '1px solid #374151', textAlign: 'left', padding: '8px 6px' }}>Price (रु.)</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td style={{ borderBottom: '1px solid #1f2937', padding: '8px 6px' }}>प्रति {result.price_base_unit || 'unit'}</td>
                      <td style={{ borderBottom: '1px solid #1f2937', padding: '8px 6px' }}>{result.price_per_base_unit !== null && result.price_per_base_unit !== undefined ? Number(result.price_per_base_unit).toFixed(2) : '-'}</td>
                    </tr>
                    <tr>
                      <td style={{ borderBottom: '1px solid #1f2937', padding: '8px 6px' }}>प्रति ग्राम</td>
                      <td style={{ borderBottom: '1px solid #1f2937', padding: '8px 6px' }}>{result.price_per_gram !== null && result.price_per_gram !== undefined ? Number(result.price_per_gram).toFixed(2) : 'N/A'}</td>
                    </tr>
                    <tr>
                      <td style={{ borderBottom: '1px solid #1f2937', padding: '8px 6px' }}>प्रति किलो</td>
                      <td style={{ borderBottom: '1px solid #1f2937', padding: '8px 6px' }}>{result.price_per_kg !== null && result.price_per_kg !== undefined ? Number(result.price_per_kg).toFixed(2) : 'N/A'}</td>
                    </tr>
                    <tr>
                      <td style={{ padding: '8px 6px' }}>प्रति क्विंटल</td>
                      <td style={{ padding: '8px 6px' }}>{result.price_per_quintal !== null && result.price_per_quintal !== undefined ? Number(result.price_per_quintal).toFixed(2) : 'N/A'}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
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
          <p style={mutedStyle}>Confidence: {result.confidence}% | Volatility: {result.volatility}</p>
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
      setError('Please enter your question / कृपया अपना प्रश्न लिखें।');
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
      setAnswer(String(res?.answer || '').trim() || 'No answer generated / उत्तर उपलब्ध नहीं है।');
    } catch (e) {
      setError(`Q&A error: ${String(e?.message || e)}`);
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
        placeholder="अपना प्रश्न लिखें... / Write your question..."
        style={textAreaStyle}
      />
      <div style={rowWrapStyle}>
        <label style={checkboxLabelStyle}>
          <input type="checkbox" checked={isDetailed} onChange={(e) => setIsDetailed(e.target.checked)} />
          Detailed Answer / विस्तृत उत्तर
        </label>
        <button style={buttonStyle} onClick={askQuestion} disabled={loading}>
          {loading ? 'Generating answer... / उत्तर तैयार हो रहा है...' : 'Get Answer / उत्तर प्राप्त करें'}
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
        <h3 style={smallHeadStyle}>Q&A Tatkal Uttar</h3>
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
    const raw = localStorage.getItem(LATEST_KUNDLI_KEY);
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
      <div style={heroTopStyle}>Fortune Guru</div>
      <div style={{ ...cardStyle, maxWidth: 1100 }}>
        <div style={rowBetweenStyle}>
          <h1 style={titleStyle}>Remedies</h1>
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
  padding: '22px 18px 110px',
  fontFamily: "Calibri, 'Segoe UI', Arial, sans-serif"
};

const heroTopStyle = {
  maxWidth: 1120,
  margin: '0 auto 14px',
  color: '#67e8f9',
  fontFamily: "Calibri, 'Segoe UI', Arial, sans-serif",
  letterSpacing: '1px',
  fontSize: 28
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

const avatarWrapStyle = {
  display: 'flex',
  justifyContent: 'center',
  marginBottom: 10
};

const avatarStyle = {
  width: 120,
  height: 120,
  borderRadius: '50%',
  objectFit: 'cover',
  objectPosition: 'center top',
  border: '2px solid rgba(34,211,238,0.7)'
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
  padding: '8px 14px',
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
  width: 118,
  height: 118,
  borderRadius: '50%',
  objectFit: 'cover',
  objectPosition: 'center top',
  marginBottom: 18,
  border: '2px solid rgba(34,211,238,0.7)',
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
const loadingVoiceRowStyle = { marginTop: 18, display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' };

const KUNDLI_LOADING_MESSAGES = [
  'Aapke janm-vivaran se kundli banayi ja rahi hai...',
  'Grah, rashi aur nakshatra ki sthiti compute ho rahi hai...',
  'Bhaav aur Vimshottari dasha timeline taiyaar ho rahi hai...',
  'Guru Ji aapke chart ka vishleshan likh rahe hain...',
  'Antim sanket, timing aur upay jode ja rahe hain...'
];

function KundliLoadingScreen({ avatar, onAvatarClick, onPlay }) {
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
        <img src={avatar} alt="Guru Ji" onClick={onAvatarClick} style={loadingAvatarStyle} />
        <div style={loadingTitleStyle}>Guru Ji aapki kundli dekh rahe hain</div>
        <div style={loadingMsgStyle}>{KUNDLI_LOADING_MESSAGES[msgIdx]}</div>
        <div style={progressTrackStyle}>
          <div style={progressBarStyle} />
        </div>
        <div style={loadingHintStyle}>
          Ismein aam taur par 30&ndash;60 second lag sakte hain. Kripya page band na karein.
        </div>
        <div style={loadingVoiceRowStyle}>
          <button style={secondaryButtonStyle} onClick={() => onPlay('original')}>Guru Ji Original Voice</button>
          <button style={secondaryButtonStyle} onClick={() => onPlay('cloned')}>Guru Ji Cloned Voice</button>
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

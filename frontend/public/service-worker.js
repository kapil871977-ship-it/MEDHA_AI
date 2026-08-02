/* MEDHA AI — PWA service worker
 *
 * Strategy (safe + simple):
 *   - Only handles same-origin GET requests (the backend API runs on a
 *     different origin/port, so API calls are ignored and never cached).
 *   - Navigations: network-first, falling back to cache, then to the app shell
 *     when offline.
 *   - Other static assets (JS/CSS/images): cache-first, populated on the fly.
 *   - Old caches are cleaned up on activate.
 *
 * Bump CACHE_VERSION whenever you want clients to drop the old cache.
 */
// Bumped to v2: app icons, logo and manifest were replaced, so returning
// visitors must drop the v1 cache rather than keep serving the old assets.
const CACHE_VERSION = 'medha-ai-v2';
const APP_SHELL = ['./', './index.html', './manifest.json', './favicon.ico'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(APP_SHELL)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only same-origin GET requests are cacheable here.
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Navigations → network-first, fall back to cache / app shell offline.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(request).then((cached) => cached || caches.match('./index.html')))
    );
    return;
  }

  // Static assets → cache-first, populate cache on the fly.
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((res) => {
        if (res && res.status === 200 && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy)).catch(() => {});
        }
        return res;
      });
    })
  );
});

// HSFOODS service worker — network-first (safe, installable).
// Always serves fresh content when online (no stale-cache trap), falls back to
// cache only when offline. Having a fetch handler makes both apps installable
// as Android/desktop apps.
const CACHE = 'hsfoods-v8';
const SHELL = [
  '/', '/index.html', '/styles.css', '/app.js',
  '/shop.html', '/shop.css', '/shop.js',
  '/manifest.json', '/shop-manifest.json',
  '/icons/mgmt-192.png', '/icons/shop-192.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;

  // API: always live; cache is only an offline fallback
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }

  // App shell: network-first (fresh online) with cache fallback (works offline)
  e.respondWith((async () => {
    try {
      const resp = await fetch(e.request);
      if (resp && resp.ok) {
        const cache = await caches.open(CACHE);
        cache.put(e.request, resp.clone());
      }
      return resp;
    } catch {
      const cached = await caches.match(e.request);
      return cached || caches.match(url.pathname.startsWith('/shop') ? '/shop.html' : '/');
    }
  })());
});

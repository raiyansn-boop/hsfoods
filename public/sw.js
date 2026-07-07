// HSFOODS service worker — offline app shell for the PWAs.
const CACHE = 'hsfoods-v2';
const SHELL = [
  '/', '/index.html', '/styles.css', '/app.js',
  '/shop.html', '/shop.css', '/shop.js',
  '/manifest.json', '/shop-manifest.json',
  '/icons/mgmt-192.png', '/icons/shop-192.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Network-first for API + pages (always fresh); cache-first for static assets.
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;

  const isApi = url.pathname.startsWith('/api/');
  const isPage = e.request.mode === 'navigate' ||
    /\.(html|js|css)$/.test(url.pathname) || url.pathname === '/';

  if (isApi || isPage) {
    // network-first: fresh content online, cached fallback offline
    e.respondWith(
      fetch(e.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return resp;
      }).catch(() => caches.match(e.request).then((c) => c || caches.match('/shop.html')))
    );
    return;
  }

  // static assets (icons, fonts): cache-first
  e.respondWith(
    caches.match(e.request).then((cached) =>
      cached || fetch(e.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return resp;
      })
    )
  );
});

// TEMPORARY kill-switch service worker.
// Recovers any browser stuck on a stale cache: on activation it deletes ALL
// caches, unregisters itself, and reloads open pages — so the site then loads
// 100% fresh from the network every time. Zero manual steps needed.
//
// A proper offline/installable SW will be re-introduced right before real
// phone / Play Store install.
self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      await caches.delete(key);
    }
    await self.registration.unregister();
    const clients = await self.clients.matchAll({ type: 'window' });
    for (const client of clients) {
      client.navigate(client.url);
    }
  })());
});

// Never serve from cache while the kill-switch is active.
self.addEventListener('fetch', () => {});

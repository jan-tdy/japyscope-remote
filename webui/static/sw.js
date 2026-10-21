self.addEventListener('install', function(event) {
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  event.waitUntil(self.clients.claim());
});

// Pass every request straight to the network. This file exists only to
// satisfy the browser's installability check -- caching would show stale
// telescope state, which is worse than no offline support at all.
self.addEventListener('fetch', function(event) {
  event.respondWith(fetch(event.request));
});

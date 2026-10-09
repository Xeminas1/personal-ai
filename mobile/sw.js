const CACHE = "xemai-mobile-v0.9.5";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((key) => caches.delete(key)))
    )
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET") return;

  // XemAi requires its PC server to be online anyway, so stale cached app code
  // is more harmful than useful. Always fetch current UI/API content.
  if (url.origin === self.location.origin) {
    event.respondWith(
      fetch(request, { cache: "no-store" })
    );
  }
});

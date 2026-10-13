// N00dle service worker -- what makes the site installable as an app.
//
// It deliberately does NOT cache pages: every page still comes from the
// network (and the server-side caching / ?r= region logic) exactly as in
// a normal browser tab, so the app never shows stale news. The only thing
// it adds is a friendly offline page when there is no connection.
//
// Bump VERSION when offline.html or the files below change.
const VERSION = "v1";
const CACHE = `n00dle-${VERSION}`;
const OFFLINE_FILES = ["/offline.html", "/logo.svg", "/favicon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(OFFLINE_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k.startsWith("n00dle-") && k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  // Only full page loads; everything else (images, scripts, the in-page
  // navigation fetches) goes straight to the network untouched.
  if (req.mode !== "navigate") return;
  event.respondWith(fetch(req).catch(() => caches.match("/offline.html")));
});

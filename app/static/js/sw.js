// Service worker for the PWA. Served from /sw.js so its scope is the whole origin.
// __CACHE_VERSION__ is substituted server-side with DEPLOY_VERSION, so a deploy
// bumps the cache name and retires the old one.
//
// Strategy, chosen to be safe for an authenticated app:
//   * Navigations  -> network-only, falling back to the offline page. We never
//     cache HTML, so a logged-in page can't be served to the wrong person.
//   * /static/*    -> stale-while-revalidate (fast, self-healing on deploy).
//   * Everything else (APIs, auth, billing…) -> untouched, straight to network.
"use strict";

const VERSION = "__CACHE_VERSION__";
const CACHE = "app-" + VERSION;
const OFFLINE_URL = "/offline";

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.add(new Request(OFFLINE_URL, { cache: "reload" }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== CACHE; })
            .map(function (k) { return caches.delete(k); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Cache versioned static assets; serve cached, refresh in the background.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.open(CACHE).then(function (cache) {
        return cache.match(req).then(function (hit) {
          const network = fetch(req).then(function (res) {
            if (res && res.ok) cache.put(req, res.clone());
            return res;
          }).catch(function () { return hit; });
          return hit || network;
        });
      })
    );
    return;
  }

  // Page loads: always hit the network; only fall back to the offline page.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(function () { return caches.match(OFFLINE_URL); })
    );
  }
  // Anything else (JSON APIs, auth, billing) is left to the network untouched.
});

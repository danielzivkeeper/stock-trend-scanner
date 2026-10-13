/* Service worker: makes the dashboard installable and usable offline.
 * App files: cache-first (bump VERSION when you change them).
 * data/*.json: network-first, falling back to the last copy we saw. */
var VERSION = "v3";
var SHELL = ["./", "index.html", "style.css", "app.js", "papertrade.js", "manifest.webmanifest",
             "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open("shell-" + VERSION).then(function (c) { return c.addAll(SHELL); }));
  self.skipWaiting();
});

self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== "shell-" + VERSION && k !== "data"; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.indexOf("/data/") !== -1) {
    var key = url.origin + url.pathname; // ignore the ?t= cache-buster
    e.respondWith(fetch(e.request).then(function (r) {
      if (r.ok) { var copy = r.clone(); caches.open("data").then(function (c) { c.put(key, copy); }); }
      return r;
    }).catch(function () {
      return caches.open("data").then(function (c) { return c.match(key); }).then(function (r) {
        return r || new Response('{"error":"offline"}', { status: 503, headers: { "Content-Type": "application/json" } });
      });
    }));
    return;
  }
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(function (r) {
    return r || fetch(e.request);
  }));
});

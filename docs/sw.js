/* Service worker: makes the dashboard installable and usable offline.
 * Everything is network-first: always the newest version when online, the
 * last saved copy when offline. */
var VERSION = "v9";
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
  // Network first, so a new version shows up the next time the app opens; the
  // saved copy is only used when offline.
  var isData = url.pathname.indexOf("/data/") !== -1;
  var key = isData ? url.origin + url.pathname : e.request; // ignore the ?t= cache-buster on data
  var bucket = isData ? "data" : "shell-" + VERSION;
  e.respondWith(fetch(e.request).then(function (r) {
    if (r.ok) { var copy = r.clone(); caches.open(bucket).then(function (c) { c.put(key, copy); }); }
    return r;
  }).catch(function () {
    return caches.open(bucket).then(function (c) { return c.match(key, { ignoreSearch: true }); }).then(function (r) {
      return r || (isData ? new Response('{"error":"offline"}', { status: 503, headers: { "Content-Type": "application/json" } })
                          : caches.match("index.html"));
    });
  }));
});

// Offline-Fähigkeit: App-Hülle zwischenspeichern, Daten immer zuerst frisch holen.
const C = "handball7-v14";
self.addEventListener("install", e => { self.skipWaiting(); e.waitUntil(caches.open(C).then(c => c.addAll(["./", "index.html", "icon.svg", "manifest.webmanifest"]))); });
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== C).map(x => caches.delete(x)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  // immer am Server nachfragen (kein veralteter Browser-Cache)
  e.respondWith(fetch(e.request, { cache: "no-cache" }).then(r => { const k = r.clone(); caches.open(C).then(c => c.put(e.request, k)); return r; })
    .catch(() => caches.match(e.request)));
});

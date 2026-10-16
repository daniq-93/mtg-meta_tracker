// Service worker de Meta Standard: la app funciona sin conexión con los últimos datos descargados.
const SHELL = "meta-shell-v6";
const CARDS = "meta-cards-v1";
const DATA = "meta-data-v1";
const SHELL_FILES = ["./", "index.html", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png", "icons/favicon.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== DATA && k !== CARDS).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.hostname === "api.scryfall.com" || url.hostname === "cards.scryfall.io") {
    // cartas: lo guardado si ya se abrió antes; si no, de la red y se guarda
    e.respondWith(caches.open(CARDS).then(c => c.match(e.request).then(hit => hit || fetch(e.request).then(r => { if (r.ok || r.type === "opaque") c.put(e.request, r.clone()); return r; }))));
    return;
  }
  if (url.origin !== location.origin) return;
  if (url.pathname.includes("/data/")) {
    // datos: primero la red, si no hay conexión lo último guardado
    e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(DATA).then(c => c.put(e.request, copy)); return r; })
      .catch(() => caches.match(e.request)));
    return;
  }
  // la página: primero la red, para que una versión nueva se vea al abrir; sin conexión, lo guardado
  if (e.request.mode === "navigate" || url.pathname.endsWith("/index.html")) {
    e.respondWith(fetch(e.request).then(r => { if (r.ok) { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); } return r; })
      .catch(() => caches.match(e.request).then(hit => hit || caches.match("index.html"))));
    return;
  }
  // resto de la interfaz: lo guardado al momento y se refresca en segundo plano
  e.respondWith(caches.match(e.request).then(hit => {
    const net = fetch(e.request).then(r => { if (r.ok) { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); } return r; }).catch(() => hit);
    return hit || net;
  }));
});

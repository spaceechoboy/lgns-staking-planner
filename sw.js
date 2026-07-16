/* LGNS Staking Planner service worker — 앱셸 network-first, 외부 RPC·rates.json 신선도 우선 */
const CACHE = 'lgns-planner-v3';
const SHELL = ['./', './index.html', './manifest.json', './icons/icon-192.png', './icons/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  // 외부(RPC 등) 또는 rates.json → network-first, 실패 시 캐시
  if (u.origin !== location.origin || u.pathname.endsWith('rates.json')) {
    e.respondWith(fetch(e.request).then(r => {
      if (u.pathname.endsWith('rates.json')) { const cp = r.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); }
      return r;
    }).catch(() => caches.match(e.request)));
    return;
  }
  // 앱셸 → network-first(온라인이면 최신 반영), 실패 시 캐시
  e.respondWith(fetch(e.request).then(r => {
    const cp = r.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); return r;
  }).catch(() => caches.match(e.request).then(m => m || caches.match('./index.html'))));
});

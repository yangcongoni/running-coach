const cacheName = 'running-coach-daily-shell-__SHELL_VERSION__';
const shell = '/offline-feedback';
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const response = await fetch(shell, {credentials:'same-origin', cache:'no-store'});
    if (!response.ok || !response.headers.get('Content-Type')?.includes('text/html')) throw Error('Offline form unavailable');
    await (await caches.open(cacheName)).put(shell, response);
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith('running-coach-daily-shell-') && name !== cacheName) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.mode !== 'navigate' || event.request.method !== 'GET' ||
      url.origin !== self.location.origin || !['/','/mobile'].includes(url.pathname)) return;
  event.respondWith(fetch(event.request).catch(async () => (await caches.open(cacheName)).match(shell)));
});

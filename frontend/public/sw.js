/* Wazza Inbox Enterprise PWA service worker */
const SW_VERSION = 'wazza-mobile-pwa-v1';
const APP_SHELL_CACHE = `${SW_VERSION}-shell`;
const INBOX_CACHE = `${SW_VERSION}-inbox`;
const APP_SHELL_URLS = [
  '/mobile',
  '/manifest.webmanifest',
  '/Logo.svg',
];
const INBOX_API_PATTERNS = [
  /\/api\/conversations(?:\?|$)/,
  /\/api\/messages\/conversation\//,
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(APP_SHELL_CACHE)
      .then((cache) => cache.addAll(APP_SHELL_URLS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith('wazza-mobile-pwa-') && !key.startsWith(SW_VERSION))
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

function isInboxApiRequest(requestUrl) {
  return INBOX_API_PATTERNS.some((pattern) => pattern.test(requestUrl.pathname));
}

function withOfflineFallback(request) {
  return fetch(request).then((response) => {
    if (response && response.ok) {
      const copy = response.clone();
      caches.open(INBOX_CACHE).then((cache) => cache.put(request, copy));
    }
    return response;
  }).catch(async () => {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ offline: true, items: [] }), {
      headers: { 'Content-Type': 'application/json' },
      status: 503,
      statusText: 'Offline',
    });
  });
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const requestUrl = new URL(request.url);
  const sameOrigin = requestUrl.origin === self.location.origin;

  if (sameOrigin && request.mode === 'navigate' && requestUrl.pathname.startsWith('/mobile')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(APP_SHELL_CACHE).then((cache) => cache.put('/mobile', copy));
          return response;
        })
        .catch(() => caches.match('/mobile'))
    );
    return;
  }

  if (sameOrigin && isInboxApiRequest(requestUrl)) {
    event.respondWith(withOfflineFallback(request));
    return;
  }

  if (sameOrigin && APP_SHELL_URLS.includes(requestUrl.pathname)) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
  }
});

self.addEventListener('push', (event) => {
  const payload = (() => {
    try {
      return event.data ? event.data.json() : {};
    } catch {
      return { title: 'Novo alerta', body: event.data?.text() || 'Você tem uma nova atualização no Inbox.' };
    }
  })();

  const title = payload.title || 'Wazza Inbox';
  const body = payload.body || payload.text || 'Nova mensagem recebida.';
  const conversationId = payload.conversation_id || payload.conversationId || null;
  const badgeCount = Number(payload.badge ?? payload.badgeCount ?? 1);

  event.waitUntil((async () => {
    if ('setAppBadge' in navigator && Number.isFinite(badgeCount)) {
      try { await navigator.setAppBadge(badgeCount); } catch { /* noop */ }
    }

    await self.registration.showNotification(title, {
      body,
      icon: '/Logo.svg',
      badge: '/Logo.svg',
      tag: conversationId ? `conversation-${conversationId}` : 'wazza-inbox',
      renotify: true,
      vibrate: [120, 60, 120],
      data: {
        url: conversationId ? `/mobile?conversation_id=${encodeURIComponent(conversationId)}` : '/mobile',
        conversation_id: conversationId,
      },
      actions: [
        { action: 'open', title: 'Abrir Inbox' },
      ],
    });
  })());
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || '/mobile';
  const conversationId = event.notification.data?.conversation_id;

  event.waitUntil((async () => {
    if ('clearAppBadge' in navigator) {
      try { await navigator.clearAppBadge(); } catch { /* noop */ }
    }

    const clientsList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of clientsList) {
      const clientUrl = new URL(client.url);
      if (clientUrl.origin === self.location.origin && clientUrl.pathname.startsWith('/mobile')) {
        await client.focus();
        client.postMessage({ type: 'NOTIFICATION_CLICK', conversation_id: conversationId });
        return;
      }
    }
    await self.clients.openWindow(targetUrl);
  })());
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

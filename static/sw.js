// Omnivault Service Worker v3
// Estratégia: cache-first para imagens, network-first para API

const SHELL_CACHE  = 'cs-shell-v7';
const IMG_CACHE    = 'cs-images-v7';   // v7: capas agora são miniaturas (300x450)
const API_CACHE    = 'cs-api-v7';   // v7: chave de cache inclui o perfil (X-Profile)
// Downloads explícitos ("Baixar no aparelho") — escrito pela página via
// caches.open(); o caches.match() global abaixo já serve destas entradas.
// Nunca deve ser limpo no activate: é o acervo offline do usuário.
const OFFLINE_CACHE = 'cs-offline-v1';

const SHELL_URLS = ['/', '/reader.html', '/profile.js', '/manifest.json', '/fonts/fonts.css'];

// ── Install ───────────────────────────────────────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(SHELL_CACHE)
      .then(c => c.addAll(SHELL_URLS))
      .then(() => self.skipWaiting())
  );
});

// ── Activate ──────────────────────────────────────────────────────────────────
self.addEventListener('activate', e => {
  const keep = new Set([SHELL_CACHE, IMG_CACHE, API_CACHE, OFFLINE_CACHE]);
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => !keep.has(k)).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ── Fetch ─────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Auth — always network
  if (url.pathname.startsWith('/auth/')) return;

  // Capas de PASTA são mutáveis (o usuário pode trocá-las) — network-first:
  // o servidor responde no-cache+ETag, então online é um 304 barato e a troca
  // aparece sempre; offline cai no cache normalmente.
  if (e.request.method === 'GET' &&
      url.pathname.startsWith('/api/folders/') && url.pathname.includes('/cover')) {
    e.respondWith(networkFirst(e.request, IMG_CACHE));
    return;
  }

  // Capas de HQ + páginas são imutáveis — cache-first para GET apenas
  // POST requests (cover refresh/upload) nunca devem ser cacheados
  if (e.request.method === 'GET' &&
      (url.pathname.includes('/cover') || url.pathname.includes('/page/'))) {
    e.respondWith(cacheFirst(e.request, IMG_CACHE));
    return;
  }

  // API — network-first, fall back to cache (allows offline browsing of cached state)
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(networkFirst(e.request, API_CACHE));
    return;
  }

  // Shell (HTML, icons) — network-first para app local
  // Garante que mudanças no index.html são sempre reflectidas imediatamente
  e.respondWith(networkFirst(e.request, SHELL_CACHE));
});

async function cacheFirst(req, cacheName) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const resp = await fetch(req);
    if (resp.ok && req.method === 'GET') {  // Cache API não suporta POST
      const cache = await caches.open(cacheName);
      cache.put(req, resp.clone());
    }
    return resp;
  } catch {
    return new Response('Offline', { status: 503 });
  }
}

// Respostas por perfil (estado, listas, stats) têm a mesma URL para todos os
// perfis: o header X-Profile entra na chave do cache, senão o fallback offline
// mostraria o estado de um perfil para outro. Só nessas rotas — o resto (ex.:
// /info das HQs baixadas em cs-offline-v1) continua com a URL pura como chave.
const PROFILE_SCOPED = /^\/api\/(reading\/|lists|stats)/;
function cacheKey(req) {
  const p = req.headers.get('X-Profile');
  const u = new URL(req.url);
  if (!p || !PROFILE_SCOPED.test(u.pathname)) return req;
  u.searchParams.set('__profile', p);
  return u.href;
}

async function networkFirst(req, cacheName) {
  const key = cacheKey(req);
  try {
    const resp = await fetch(req);
    if (resp.ok && req.method === 'GET') {  // Cache API não suporta POST
      const cache = await caches.open(cacheName);
      cache.put(key, resp.clone());
    }
    return resp;
  } catch {
    const cached = await caches.match(key);
    return cached || new Response('{"error":"offline"}',
      { status: 503, headers: { 'Content-Type': 'application/json' } });
  }
}

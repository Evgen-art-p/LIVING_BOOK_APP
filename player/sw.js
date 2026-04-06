// sw.js — Service Worker v3. Кэш для офлайн-режима.
// ФИКС: не кэшируем /api/ и POST-запросы.

const CACHE     = 'iskra-fort-v3';
const BOOK_PATH = '../books/grondheim_01/';

const PRECACHE = [
    './',
    './index.html',
    BOOK_PATH + 'book.json',
    BOOK_PATH + 'chapters/ch_01_awakening.json',
    BOOK_PATH + 'chapters/ch_02_tunnel.json',
    BOOK_PATH + 'characters/eirik.json',
    BOOK_PATH + 'characters/iskra.json',
    BOOK_PATH + 'ethics.json',
    BOOK_PATH + 'config.json',
];

const AUDIO_EXTS = ['.mp3', '.ogg', '.wav'];

async function safeCachePut(cache, request, response) {
    if (!response || response.status !== 200 || response.type === 'error') return;
    try {
        await cache.put(request, response);
    } catch (e) {
        // Тихо проглатываем (POST, opaque и т.д.)
    }
}

self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE).then(async cache => {
            await Promise.allSettled(
                PRECACHE.map(url =>
                    fetch(new Request(url, { cache: 'reload' }))
                        .then(res => safeCachePut(cache, url, res))
                        .catch(() => {})
                )
            );
        }).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);

    // ФИКС 3: НЕ кэшируем API и POST-запросы — пропускаем насквозь
    if (e.request.method !== 'GET') return;
    if (url.pathname.startsWith('/api/')) return;
    if (url.pathname.includes('/beacon')) return;

    // Аудио — cache-first
    if (AUDIO_EXTS.some(ext => url.pathname.endsWith(ext))) {
        e.respondWith(
            caches.match(e.request).then(cached => {
                if (cached) return cached;
                return fetch(e.request)
                    .then(async res => {
                        if (res && res.status === 200) {
                            const cache = await caches.open(CACHE);
                            await safeCachePut(cache, e.request, res.clone());
                        }
                        return res;
                    })
                    .catch(() => new Response('', { status: 404, statusText: 'Audio not recorded yet' }));
            })
        );
        return;
    }

    // Всё остальное (HTML, JSON книг) — network-first
    e.respondWith(
        fetch(e.request)
            .then(async res => {
                if (res && res.status === 200) {
                    const cache = await caches.open(CACHE);
                    await safeCachePut(cache, e.request, res.clone());
                }
                return res;
            })
            .catch(() => caches.match(e.request))
    );
});

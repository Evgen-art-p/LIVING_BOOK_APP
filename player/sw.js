// sw.js — Service Worker. Кэш для полного офлайн-режима.

const CACHE     = 'iskra-fort-v2';
const BOOK_PATH = '../books/grondheim_01/';

// Файлы которые кэшируем при установке
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

// Аудио-файлы кэшируем по мере запроса (стратегия cache-first)
const AUDIO_EXTS = ['.mp3', '.ogg', '.wav'];

// ─── Хелпер: безопасное добавление в кэш (игнорирует 404 и ошибки) ──────────
async function safeCachePut(cache, request, response) {
    if (!response || response.status !== 200 || response.type === 'error') return;
    try {
        await cache.put(request, response);
    } catch (e) {
        console.warn('[SW] Не удалось закэшировать:', request.url, e.message);
    }
}

// ─── Установка: кэшируем только то, что реально существует ──────────────────
self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE).then(async cache => {
            const results = await Promise.allSettled(
                PRECACHE.map(url =>
                    fetch(new Request(url, { cache: 'reload' }))
                        .then(res => safeCachePut(cache, url, res))
                        .catch(err => console.warn('[SW] Пропущен при установке:', url, err.message))
                )
            );
            const failed = results.filter(r => r.status === 'rejected').length;
            if (failed > 0) console.warn(`[SW] Установка: ${failed} файл(ов) не закэшировано (норма если MP3 ещё не записаны)`);
        }).then(() => self.skipWaiting())
    );
});

// ─── Активация: чистим старые версии кэша ───────────────────────────────────
self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

// ─── Перехват запросов ───────────────────────────────────────────────────────
self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);

    // Маяк — не кэшируем, нужна живая сеть
    if (url.pathname.includes('/beacon')) return;

    // Аудио — cache-first (один раз скачали и всё)
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
                    .catch(() => {
                        // MP3 ещё не записан — тихо отдаём 404, движок уйдёт на TTS-фоллбэк
                        console.warn('[SW] Аудио недоступно (TTS-фоллбэк):', url.pathname);
                        return new Response('', { status: 404, statusText: 'Audio not recorded yet' });
                    });
            })
        );
        return;
    }

    // Всё остальное — network-first, fallback на кэш
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

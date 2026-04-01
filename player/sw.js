// sw.js — Service Worker. Кэш для полного офлайн-режима.

const CACHE     = 'iskra-fort-v1';
const BOOK_PATH = '../books/grondheim_01/';

// Файлы которые кэшируем при установке
const PRECACHE = [
    './',
    './index.html',
    BOOK_PATH + 'book.json',
    BOOK_PATH + 'chapters/ch01_awakening.json',
    BOOK_PATH + 'characters/eirik.json',
    BOOK_PATH + 'ethics.json',
    BOOK_PATH + 'config.json',
];

// Аудио-файлы кэшируем по мере запроса (стратегия cache-first)
const AUDIO_EXTS = ['.mp3', '.ogg', '.wav'];

self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE)
            .then(c => c.addAll(PRECACHE.map(url => new Request(url, { cache: 'reload' }))))
            .then(() => self.skipWaiting())
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

    // Маяк — не кэшируем, нужна живая сеть
    if (url.pathname.includes('/beacon')) return;

    // Аудио — cache-first (один раз скачали и всё)
    if (AUDIO_EXTS.some(ext => url.pathname.endsWith(ext))) {
        e.respondWith(
            caches.match(e.request).then(cached => {
                if (cached) return cached;
                return fetch(e.request).then(res => {
                    const clone = res.clone();
                    caches.open(CACHE).then(c => c.put(e.request, clone));
                    return res;
                });
            })
        );
        return;
    }

    // Всё остальное — network-first, fallback на кэш
    e.respondWith(
        fetch(e.request)
            .then(res => {
                const clone = res.clone();
                caches.open(CACHE).then(c => c.put(e.request, clone));
                return res;
            })
            .catch(() => caches.match(e.request))
    );
});

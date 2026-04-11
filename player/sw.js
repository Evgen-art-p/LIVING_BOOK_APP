// sw.js — Service Worker v4.0
// Живая Книга — Агрессивное кэширование аудио для 3D-погружения
// Поддержка офлайн-режима для незрячих детей

const CACHE_NAME = 'iskra-fort-v4';
const AUDIO_CACHE_NAME = 'iskra-audio-v1';

// ============================================================
// СПИСОК ФАЙЛОВ ДЛЯ ПРЕКЭШИРОВАНИЯ (устанавливаются при первом запуске)
// ============================================================
const PRECACHE_URLS = [
    './',
    './index.html',
    './manifest.json',
    // Основные JSON (если нужны)
    '../books/grondheim_01/book.json',
    '../books/grondheim_01/chapters/ch_01_awakening.json',
    '../books/grondheim_01/chapters/ch_02_tunnel.json',
    '../books/grondheim_01/characters/eirik.json',
    '../books/grondheim_01/characters/iskra.json',
    '../books/grondheim_01/ethics.json',
    '../books/grondheim_01/config.json',
];

// ============================================================
// АУДИОФАЙЛЫ ДЛЯ АГРЕССИВНОГО КЭШИРОВАНИЯ (офлайн-ядро)
// ============================================================
const AUDIO_PRECACHE = [
    // UI звуки состояний
    '/audio/ui/listening_bell.mp3',
    '/audio/ui/thinking_pages.mp3',
    
    // Реверберация для миров
    '/audio/reverb/cave_ir.mp3',
    '/audio/reverb/forest_ir.mp3',
    
    // Эмбиенты миров (Слот 2)
    '/audio/worlds/whispering_caves/ambient.mp3',
    '/audio/worlds/whispering_caves/drip_loop.mp3',
    '/audio/worlds/whispering_caves/mystery_theme.mp3',
    '/audio/worlds/grondheim_forest/ambient.mp3',
    '/audio/worlds/grondheim_forest/leaves_loop.mp3',
    
    // Звуки персонажей (Слот 1)
    '/audio/characters/eirik_entry.mp3',
    '/audio/characters/eirik_idle.mp3',
    '/audio/characters/sovunya_entry.mp3',
    '/audio/characters/sovunya_idle.mp3',
    
    // Звуки артефактов (Слот 4) — будут добавлены динамически через API
    // Но прекэшируем базовые
    '/audio/artifacts/crystal_key.mp3',
    '/audio/artifacts/shadow_tear.mp3',
    '/audio/artifacts/glowing_moss.mp3',
];

// Расширения аудиофайлов для определения "audio-first" стратегии
const AUDIO_EXTS = ['.mp3', '.ogg', '.wav', '.m4a'];

// ============================================================
// ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ============================================================
function isAudioRequest(url) {
    return AUDIO_EXTS.some(ext => url.pathname.toLowerCase().endsWith(ext));
}

function isApiRequest(url) {
    // НЕ кэшируем API-запросы (они идут на сервер)
    return url.pathname.startsWith('/api/') || 
           url.pathname.includes('/beacon') ||
           url.pathname.includes('/parent') ||
           url.pathname.includes('/uid');
}

function isStaticAsset(url) {
    // Статика, которую можно кэшировать
    return url.pathname.endsWith('.js') ||
           url.pathname.endsWith('.css') ||
           url.pathname.endsWith('.json') ||
           url.pathname.endsWith('.html') ||
           url.pathname.endsWith('.webmanifest');
}

// Безопасное сохранение в кэш (обрабатывает ошибки)
async function safeCachePut(cache, request, response) {
    if (!response || response.status !== 200 || response.type === 'error' || response.type === 'opaque') {
        return false;
    }
    try {
        await cache.put(request, response.clone());
        return true;
    } catch (e) {
        console.warn('[SW] Cache put failed:', e.message);
        return false;
    }
}

// ============================================================
// INSTALL — прекэширование критических файлов
// ============================================================
self.addEventListener('install', event => {
    console.log('[SW] Installing v4.0...');
    
    event.waitUntil(
        (async () => {
            // Открываем оба кэша
            const cache = await caches.open(CACHE_NAME);
            const audioCache = await caches.open(AUDIO_CACHE_NAME);
            
            // Кэшируем основные файлы
            const precachePromises = PRECACHE_URLS.map(async url => {
                try {
                    const response = await fetch(url, { cache: 'reload' });
                    if (response && response.status === 200) {
                        await safeCachePut(cache, url, response);
                        console.log('[SW] Precached:', url);
                    }
                } catch (e) {
                    console.warn('[SW] Failed to precache:', url, e.message);
                }
            });
            
            // АГРЕССИВНО кэшируем аудиофайлы (офлайн-ядро)
            const audioPromises = AUDIO_PRECACHE.map(async audioUrl => {
                try {
                    const response = await fetch(audioUrl, { cache: 'reload' });
                    if (response && response.status === 200) {
                        await safeCachePut(audioCache, audioUrl, response);
                        console.log('[SW] Audio precached:', audioUrl);
                    } else {
                        console.warn('[SW] Audio not available (will cache later):', audioUrl);
                    }
                } catch (e) {
                    console.warn('[SW] Failed to precache audio:', audioUrl, e.message);
                }
            });
            
            await Promise.allSettled([...precachePromises, ...audioPromises]);
            
            // Принудительно активируем сразу
            await self.skipWaiting();
        })()
    );
});

// ============================================================
// ACTIVATE — очистка старых кэшей
// ============================================================
self.addEventListener('activate', event => {
    console.log('[SW] Activating v4.0...');
    
    event.waitUntil(
        (async () => {
            // Удаляем старые версии кэшей
            const cacheNames = await caches.keys();
            const oldCaches = cacheNames.filter(name => 
                name !== CACHE_NAME && name !== AUDIO_CACHE_NAME && name !== 'iskra-fort-v3'
            );
            
            await Promise.all(oldCaches.map(name => {
                console.log('[SW] Deleting old cache:', name);
                return caches.delete(name);
            }));
            
            // Захватываем контроль над всеми клиентами
            await self.clients.claim();
            console.log('[SW] Activated, controlling all clients');
        })()
    );
});

// ============================================================
// FETCH — умная стратегия кэширования
// ============================================================
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    const request = event.request;
    
    // Только GET-запросы
    if (request.method !== 'GET') return;
    
    // ============================================================
    // 1. API-запросы — НЕ КЭШИРУЕМ, только сеть
    // ============================================================
    if (isApiRequest(url)) {
        // Для API нужна свежая информация с сервера
        event.respondWith(fetch(request));
        return;
    }
    
    // ============================================================
    // 2. АУДИО-ЗАПРОСЫ — Cache First (офлайн-приоритет)
    // ============================================================
    if (isAudioRequest(url)) {
        event.respondWith(
            (async () => {
                // Сначала ищем в аудио-кэше
                const audioCache = await caches.open(AUDIO_CACHE_NAME);
                let cached = await audioCache.match(request);
                
                if (cached) {
                    console.log('[SW] Audio from cache:', url.pathname);
                    return cached;
                }
                
                // Пробуем в основном кэше
                const mainCache = await caches.open(CACHE_NAME);
                cached = await mainCache.match(request);
                if (cached) {
                    console.log('[SW] Audio from main cache:', url.pathname);
                    return cached;
                }
                
                // Загружаем из сети и сохраняем для будущих офлайн-сессий
                try {
                    console.log('[SW] Fetching audio from network:', url.pathname);
                    const networkResponse = await fetch(request);
                    
                    if (networkResponse && networkResponse.status === 200) {
                        // Сохраняем в аудио-кэш
                        await safeCachePut(audioCache, request, networkResponse.clone());
                        console.log('[SW] Audio cached for offline:', url.pathname);
                    }
                    
                    return networkResponse;
                } catch (error) {
                    console.warn('[SW] Audio fetch failed (offline mode):', url.pathname);
                    // Возвращаем тишину вместо ошибки
                    return new Response(null, { status: 204, statusText: 'No Audio (Offline)' });
                }
            })()
        );
        return;
    }
    
    // ============================================================
    // 3. СТАТИЧЕСКИЕ АССЕТЫ (JS, CSS, JSON, HTML) — Network First с fallback
    // ============================================================
    if (isStaticAsset(url)) {
        event.respondWith(
            (async () => {
                try {
                    // Пытаемся получить из сети
                    const networkResponse = await fetch(request);
                    if (networkResponse && networkResponse.status === 200) {
                        // Обновляем кэш в фоне
                        const cache = await caches.open(CACHE_NAME);
                        await safeCachePut(cache, request, networkResponse.clone());
                        return networkResponse;
                    }
                    throw new Error('Network response not ok');
                } catch (error) {
                    // Fallback на кэш
                    const cached = await caches.match(request);
                    if (cached) {
                        console.log('[SW] Static asset from cache:', url.pathname);
                        return cached;
                    }
                    
                    // Если нет в кэше — возвращаем страницу-заглушку
                    if (url.pathname.endsWith('.html')) {
                        return caches.match('./index.html');
                    }
                    
                    return new Response('Resource not available offline', { status: 404 });
                }
            })()
        );
        return;
    }
    
    // ============================================================
    // 4. ВСЁ ОСТАЛЬНОЕ — Network First
    // ============================================================
    event.respondWith(
        (async () => {
            try {
                const networkResponse = await fetch(request);
                if (networkResponse && networkResponse.status === 200) {
                    // Сохраняем в кэш для будущих офлайн-сессий
                    const cache = await caches.open(CACHE_NAME);
                    await safeCachePut(cache, request, networkResponse.clone());
                    return networkResponse;
                }
                throw new Error('Network failed');
            } catch (error) {
                const cached = await caches.match(request);
                if (cached) {
                    console.log('[SW] Fallback to cache:', url.pathname);
                    return cached;
                }
                return new Response('Content not available offline', { status: 404 });
            }
        })()
    );
});

// ============================================================
// ОБРАБОТКА СООБЩЕНИЙ ОТ КЛИЕНТА (для динамического кэширования)
// ============================================================
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'CACHE_AUDIO') {
        const audioUrl = event.data.url;
        console.log('[SW] Received cache request for:', audioUrl);
        
        event.waitUntil(
            (async () => {
                try {
                    const response = await fetch(audioUrl);
                    if (response && response.status === 200) {
                        const audioCache = await caches.open(AUDIO_CACHE_NAME);
                        await safeCachePut(audioCache, audioUrl, response);
                        console.log('[SW] Dynamically cached:', audioUrl);
                        
                        // Подтверждаем клиенту
                        if (event.ports && event.ports[0]) {
                            event.ports[0].postMessage({ success: true, url: audioUrl });
                        }
                    }
                } catch (e) {
                    console.warn('[SW] Dynamic cache failed:', audioUrl, e);
                    if (event.ports && event.ports[0]) {
                        event.ports[0].postMessage({ success: false, url: audioUrl, error: e.message });
                    }
                }
            })()
        );
    }
    
    // Синхронизация с клиентом
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

// ============================================================
// ОБРАБОТКА ПУШ-УВЕДОМЛЕНИЙ (если понадобятся)
// ============================================================
self.addEventListener('push', event => {
    if (event.data) {
        const data = event.data.json();
        event.waitUntil(
            self.registration.showNotification(data.title || 'Живая Книга', {
                body: data.body || 'Новое приключение ждёт!',
                icon: '/icons/icon-192.png',
                vibrate: [200, 100, 200]
            })
        );
    }
});

console.log('[SW] Service Worker v4.0 initialized — 3D Audio Ready for Offline');
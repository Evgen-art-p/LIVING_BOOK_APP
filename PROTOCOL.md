# PROTOCOL.md — Единая Точка Правды
## Живая Книга: Протокол взаимодействия Студия ↔ Маяк ↔ Искорка

> **Версия:** 1.0  
> **Дата:** 2026-04-05  
> **Автор:** Евгений + Лока + Клод  
> **Статус:** ЧЕРНОВИК → на утверждение Продюсера

---

## 1. Философия

Три модуля, один контракт:

```
СТУДИЯ (производит)  →  МАЯК (хранит и раздаёт)  →  ИСКОРКА (показывает)
    18 агентов              FastAPI сервер              HTML/JS плеер
```

**Правило:** Каждый модуль доверяет данным от предыдущего. Если данных нет — работает с тем что есть. Если не может — показывает заглушку, но **никогда не падает**.

---

## 2. Единый Пакет (Book Package)

### 2.1 Структура на диске

```
books/{child_name}/
├── book.json                  ← ОБЯЗАТЕЛЬНО. Точка входа
├── chapters/
│   └── {chapter_id}.json      ← По одному файлу на главу
├── characters/
│   └── {character_id}.json    ← Персонажи (опционально)
├── child_profile.json         ← Профиль ребёнка (опционально)
├── biography.json             ← Биография/прогресс (опционально)
├── ethics.json                ← Этический фильтр (опционально)
├── config.json                ← Настройки LLM/TTS (опционально)
├── gift_baskets/              ← Корзинки подарков (опционально)
│   └── basket_{id}.json
└── _master_brief.json         ← Служебный: бриф от SET (не для Искорки)
```

### 2.2 Правило имён папок

```
ЗАКОН: Папка ребёнка = child_name КАК ЕСТЬ (с оригинальным регистром)
```

- Студия сохраняет: `books/Женя/` (как пришло из заказа)
- Маяк ищет: case-insensitive (Женя = женя = ЖЕНЯ)
- Искорка передаёт: `CHILD_NAME` как в конфиге → Маяк разберётся

**Запрещено:** `.lower()` при сохранении. Имя ребёнка — священно.

---

## 3. Контракт данных: book.json

```json
{
  "id": "string — уникальный ID книги",
  "title": "string — название для UI",
  "description": "string — описание (опционально)",
  "age_group": "string — '3-6' | '7-12' | '13+'",
  "language": "string — 'ru'",
  "version": "string — семвер",
  "created_by": "string — 'Six Fingers Studio'",
  
  "chapters": [
    {
      "id": "string — ID главы (= имя файла без .json)",
      "title": "string — название главы",
      "file": "string — путь: 'chapters/{id}.json'"
    }
  ],
  
  "characters": [
    {
      "id": "string — ID персонажа",
      "file": "string — путь: 'characters/{id}.json'"
    }
  ],
  
  "starting_chapter": "string — ID первой главы",
  "starting_scene": "string — ID первой сцены в первой главе",
  
  "global_intents": {
    "intent_name": {
      "keywords": ["список", "ключевых", "слов"],
      "action": "string — 'pause_game_until_adult' | 'reply'",
      "reply_text": "string — ответ Искорки",
      "notify_parent": "boolean"
    }
  }
}
```

**Правило ID:** `starting_scene` ДОЛЖЕН совпадать с `id` сцены в файле главы.

---

## 4. Контракт данных: chapter JSON

```json
{
  "id": "string — ID главы",
  "title": "string — название",
  "scenes": [
    {
      "scene_id": "string — ОБЯЗАТЕЛЬНО. Уникальный ID сцены",
      "speaker": "string — ID персонажа",
      "mode": "string — 'free_talk' | 'ask_choice'",
      
      "intro_event": {
        "text": "string — вступительная реплика (озвучивается TTS)",
        "audio_file": "string — путь к аудио (опционально)",
        "ui_pulse_color": "string — цвет Искорки: 'cyan'|'gold'|'red'|..."
      },
      
      "scripted_responses": {
        "intent_name": {
          "keywords": ["слово1", "слово2"],
          "reply_text": "string — ответ",
          "reply_audio": "string — путь к аудио (опционально)",
          "ui_pulse_color": "string",
          "memory_vector": "string — тег для памяти",
          "memory_key": "string — ключ для биографии"
        },
        "fallback": {
          "reply_text": "string — ответ по умолчанию",
          "ui_pulse_color": "cyan"
        }
      },
      
      "choices": [
        {
          "id": "string",
          "label": "string — текст для UI",
          "keywords": ["слово1", "слово2"],
          "next_scene": "string — scene_id",
          "memory_vector": "string"
        }
      ],
      
      "context": "string — контекст для LLM (free_talk)",
      "ai_instructions": "string — правила для LLM",
      "max_turns": "number — макс ходов в free_talk",
      "on_end": "string — scene_id следующей | 'end'"
    }
  ]
}
```

### КРИТИЧЕСКОЕ ПРАВИЛО: `scene_id` vs `id`

```
ЗАКОН: Поле сцены называется "scene_id", НЕ "id"
```

- Спецификация: `scene_id`
- Искорка индексирует по: `scene_id`
- Если агент сгенерировал `id` вместо `scene_id` → A16 (Марка Файн) ОБЯЗАН исправить
- Fallback в Искорке: `const sid = s.scene_id || s.id` (защита от кривых данных)

---

## 5. API Маяка: контракт эндпоинтов

### 5.1 Искорка → Маяк

| Метод | URL | Возвращает | Когда |
|-------|-----|------------|-------|
| GET | `/api/beacon/stories/{name}/meta` | `book.json` целиком | При старте |
| GET | `/api/beacon/stories/{name}/chapters/{id}` | chapter JSON | При загрузке главы |
| GET | `/api/beacon/stories/{name}` | `[{story_id, title, created_at}]` | Проверка новых книг |
| POST | `/api/free_talk` | `{text, color, cached}` | Гибридный диалог |
| POST | `/beacon` | `{ok, received}` | Ночная синхронизация |

### 5.2 Родительский кабинет → Маяк

| Метод | URL | Возвращает | Когда |
|-------|-----|------------|-------|
| POST | `/api/studio/generate` | `{ok, book_dir, ...}` | Заказ новой книги |
| POST | `/api/studio/quick_scene` | `{ok, scene}` | Быстрая сцена |
| GET | `/api/parent/{category}/{name}` | JSON файл | Биография, профиль и т.д. |

### 5.3 Правило CORS и раздачи

```
ЗАКОН: Искорка открывается ТОЛЬКО через HTTP, НИКОГДА через file://
```

Маяк раздаёт `player/` как статику: `http://127.0.0.1:8001/player/index.html`

---

## 6. Правила отказоустойчивости Искорки

### 6.1 Книга не загрузилась

```
BookEngine.init() → catch → speak("Привет, {name}. Я здесь.") → idle
```
Кнопка ВСЕГДА работает. Если нет книги — Искорка просто здоровается.

### 6.2 Сцена не найдена

```
getScene(chId, sceneId) → null → getFirstScene(chId) → null → idle
```

### 6.3 Маяк недоступен

```
fetch(/api/free_talk) → catch → локальный fallback → "Я тебя слышу..."
```

### 6.4 Поле отсутствует

```
scene.intro_event → null/undefined → setState('idle') (не падаем)
scene.scripted_responses → {} → Dialog возвращает дефолт
scene.global_intents → {} → GlobalIntents не матчит ничего
```

---

## 7. Пайплайн Студии → Пакет

### 7.1 Ответственность агентов за поля пакета

| Агент | Что производит | Куда попадает |
|-------|---------------|---------------|
| A00 Фабула | Сюжет, сцены, реплики | `chapters/*.json` → `scenes[].intro_event.text` |
| A00a Вера | Ревизия (не производит файлов) | — |
| A01 | Промпты персонажей | `characters/*.json`, `scenes[].ai_instructions` |
| A02 | Детский язык | Все текстовые поля |
| A03 | Структура глав | `book.json → chapters[]`, имена файлов |
| A04 | Диалоги/интенты | `scenes[].scripted_responses`, `scenes[].context` |
| A05-A08 | Аудио, музыка | `audio/` пути |
| A09-A12 | Постпродакшн, QA | Валидация всех полей |
| A13-A15 | Тестирование, упаковка | — |
| **A16 Марка Файн** | **ФИНАЛЬНАЯ СБОРКА** | **Весь Book Package** |

### 7.2 Контрольный чеклист A16

A16 (Марка Файн) — последний агент. Он ОБЯЗАН проверить:

- [ ] `book.json` содержит `starting_chapter` и `starting_scene`
- [ ] `starting_scene` реально существует в `chapters/{starting_chapter}.json`
- [ ] Все сцены имеют поле `scene_id` (НЕ `id`)
- [ ] Все `next_scene` ссылаются на существующие `scene_id`
- [ ] Нет полей со значением `MISSING:*` — если есть, заменить заглушкой
- [ ] `chapters/` содержит все файлы из `book.json → chapters[].file`
- [ ] Файлы — валидный JSON (парсится без ошибок)

---

## 8. Нерешённые вопросы (TODO)

1. **Единый запрос:** Искорка делает 2 запроса (meta + chapter). Объединить в один `/api/beacon/stories/{name}/full`?
2. **Версионирование:** Как обрабатывать обновления книги? Перезаписывать или хранить версии?
3. **Аудио:** Путь к аудиофайлам в пакете — через Маяк или абсолютный?
4. **Кэш Искорки:** Service Worker кэширует книгу. Как инвалидировать?
5. **Корзины подарков:** Формат `gift_baskets/` не описан. Нужна спецификация.
6. **React-детектор:** Harbor of Meanings пропускает React/JS как "narrative". Нужен code-detector.

---

## 9. Глоссарий

| Термин | Значение |
|--------|----------|
| **Искорка** | HTML/JS плеер, фронтенд для ребёнка |
| **Маяк** | FastAPI сервер (beacon_v4.py), хранит и раздаёт данные |
| **Студия** | 18-агентный пайплайн, производит Book Package |
| **Book Package** | Набор JSON-файлов = одна книга |
| **scene_id** | Уникальный ID сцены внутри главы |
| **intro_event** | Вступительное событие сцены (текст + аудио + цвет) |
| **free_talk** | Режим свободного диалога через LLM |
| **ask_choice** | Режим выбора из вариантов |
| **Форт** | Офлайн-режим Искорки (IndexedDB) |

---

> **Следующий шаг:** Евгений утверждает протокол → Клод переписывает A16 prompt
> под чеклист → Лока ревьюит → запуск «вчистую».

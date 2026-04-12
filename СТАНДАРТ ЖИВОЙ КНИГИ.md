
# СТАНДАРТ ЖИВОЙ КНИГИ v3.0

**Единый контракт между Студией, Маяком, Искоркой и Кабинетом родителя.**

> Версия: 3.0  
> Дата: 2026-04-12  
> Статус: УТВЕРЖДЁН  
> Заменяет: `BOOK_PACKAGE_SPEC.md` (v1.0) и `PROTOCOL.md` (v2.0)

---

## Оглавление

1. [Философия](#1-философия)
2. [Архитектура](#2-архитектура)
3. [Структура папок на диске](#3-структура-папок-на-диске)
4. [Единый контрактный файл](#4-единый-контрактный-файл-story_packagejson)
5. [Формат книги](#5-формат-книги-bookjson)
6. [Формат главы](#6-формат-главы-chapterjson)
7. [Библиотека слотов](#7-библиотека-слотов-для-студии)
8. [Биография и память](#8-биография-и-память-biographyjson)
9. [Этика и безопасность](#9-этика-и-безопасность-ethicsjson)
10. [API Маяка](#10-api-маяка)
11. [Поток данных](#11-поток-данных-цикл-жизни)
12. [Что упраздняется](#12-что-упраздняется-из-старых-версий)
13. [Глоссарий](#13-глоссарий)

---

## 1. Философия

**Искорка — это книжка, а не чат-бот.**

- Никакого `free_talk` (свободного диалога с LLM в рантайме)
- Никакой LLM в плеере
- Ребёнок только выбирает варианты **голосом** (ключевые слова)
- Всё работает **офлайн** после загрузки книги
- Экран почти чёрный — приоритет звука и голоса

**Три модуля, один контракт:**

```
КАБИНЕТ РОДИТЕЛЯ (заказывает) → МАЯК (роутер + хранилище) → СТУДИЯ (генерирует)
                                      ↓
                                ИСКОРКА (показывает)
```

**Единый файл** `story_package.json` ходит между всеми узлами.

---

## 2. Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                         КАБИНЕТ РОДИТЕЛЯ                         │
│  (веб-интерфейс: кнопки, графики, выбор слотов, статистика)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ POST /api/package/order
                              │ (story_package.json)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                              МАЯК                                 │
│  - хранит книги и профили (books/{uid}/)                         │
│  - роутинг запросов                                               │
│  - обновляет biography.json из отчётов                           │
│  - НЕ содержит логики генерации                                   │
└─────────────────────────────────────────────────────────────────┘
                    │                              │
                    │ order                        │ chapter
                    ▼                              ▼
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│           СТУДИЯ                 │  │           ИСКОРКА               │
│  (18 агентов, офлайн-генерация)  │  │  (HTML/JS плеер для ребёнка)     │
│  - читает biography_snapshot     │  │  - 3D-звук, TTS, STT             │
│  - собирает главу из слотов      │  │  - только keyword-matching       │
│  - возвращает chapter            │  │  - офлайн-режим                  │
└─────────────────────────────────┘  └─────────────────────────────────┘
```

---

## 3. Структура папок на диске

```
books/
├── registry.json                         ← Мастер-реестр всех детей
│
├── {uid}/                                 ← Папка ребёнка (LB-2026-04-05-0001)
│   ├── book.json                          ← Метаданные текущей книги
│   ├── chapters/
│   │   ├── ch01.json                      ← Первая глава
│   │   ├── ch02.json                      ← Вторая глава
│   │   └── ...
│   ├── characters/
│   │   └── {id}.json                      ← Копии персонажей из библиотеки
│   ├── biography.json                     ← Память (карма, артефакты, выборы)
│   ├── child_profile.json                 ← Психологические паттерны
│   ├── basket.json                        ← Мостики в реальность
│   ├── ethics.json                        ← Этические ограничения
│   └── config.json                        ← Технические настройки
│
└── system_registry/                       ← Библиотеки (общие, не для Искорки)
    ├── characters/                        ← Шаблоны персонажей
    ├── locations/                         ← Шаблоны локаций
    ├── plots/                             ← Шаблоны сюжетов
    ├── finales/                           ← Шаблоны финалов
    └── ready_books/                       ← Полностью готовые первые книги
```

### 3.1 `registry.json` — мастер-реестр

```json
{
  "version": "3.0",
  "updated_at": "2026-04-12T10:00:00Z",
  "profiles": [
    {
      "uid": "LB-2026-04-05-0001",
      "alias": "Женя",
      "folder": "LB-2026-04-05-0001",
      "age_group": "7-12",
      "created_at": "2026-04-05",
      "last_activity": "2026-04-12T09:00:00Z",
      "status": "active"
    }
  ]
}
```

---

## 4. Единый контрактный файл: `story_package.json`

**Один JSON-файл, который передаётся между Кабинетом, Маяком, Студией и Искоркой.**

### 4.1 Корневая структура

```json
{
  "meta": { ... },
  "child": { ... },
  "order": { ... },
  "biography_snapshot": { ... },
  "chapter": { ... },
  "report": { ... },
  "bridges": { ... }
}
```

### 4.2 `meta` — служебная информация

| Поле | Тип | Обязательность | Описание |
|------|-----|----------------|----------|
| `version` | string | всегда | `"3.0"` |
| `type` | string | всегда | `"order"`, `"chapter"`, `"report"` |
| `timestamp` | string | всегда | ISO 8601 |
| `package_id` | string | всегда | Уникальный ID (UUID или генерация) |
| `in_response_to` | string | если ответ | ID пакета, на который отвечаем |

**Пример:**
```json
{
  "meta": {
    "version": "3.0",
    "type": "order",
    "timestamp": "2026-04-12T10:00:00Z",
    "package_id": "pkg_001",
    "in_response_to": null
  }
}
```

### 4.3 `child` — данные ребёнка

| Поле | Тип | Обязательность | Описание |
|------|-----|----------------|----------|
| `uid` | string | всегда | Уникальный ID ребёнка |
| `name` | string | всегда | Имя |
| `age_group` | string | всегда | `"3-6"`, `"7-12"`, `"13+"` |

**Пример:**
```json
{
  "child": {
    "uid": "LB-2026-04-05-0001",
    "name": "Женя",
    "age_group": "7-12"
  }
}
```

### 4.4 `order` — заказ на генерацию

Используется в `type: "order"`.

| Поле | Тип | Обязательность | Описание |
|------|-----|----------------|----------|
| `mode` | string | всегда | `"first_book"` или `"next_chapter"` |
| `book_id` | string | если `mode: first_book` | ID готовой книги из `ready_books/` |
| `slots` | object | если `mode: next_chapter` | `{location, plot, finale}` |

**Пример заказа первой книги:**
```json
{
  "order": {
    "mode": "first_book",
    "book_id": "eirik_cave_intro"
  }
}
```

**Пример заказа следующей главы:**
```json
{
  "order": {
    "mode": "next_chapter",
    "slots": {
      "location": "forest",
      "plot": "rescue_friend",
      "finale": "friendship"
    }
  }
}
```

### 4.5 `biography_snapshot` — срез памяти

| Поле | Тип | Описание |
|------|-----|----------|
| `main_character` | string | Кто главный герой (`eirik`, `loka`, `fenrir`) |
| `home_world` | string | Родной мир персонажа |
| `artifacts` | array | Полученные артефакты |
| `character_bonds` | object | Отношения с персонажами (0–10) |
| `karma` | number | Текущая карма |
| `last_choices` | array | Последние 5–10 выборов (memory_vector) |
| `completed_stories` | array | Пройденные книги/главы |

**Пример:**
```json
{
  "biography_snapshot": {
    "main_character": "eirik",
    "home_world": "cave",
    "artifacts": [
      {
        "id": "crystal_of_bravery",
        "name": "Кристалл смелости",
        "obtained_at": "2026-04-10T00:00:00Z"
      }
    ],
    "character_bonds": {
      "eirik": 5,
      "loka": 2
    },
    "karma": 12,
    "last_choices": ["brave", "curious", "helpful"],
    "completed_stories": ["eirik_cave_intro"]
  }
}
```

### 4.6 `chapter` — готовая глава

Используется в `type: "chapter"`.

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | string | ID главы (`ch01`, `ch02`...) |
| `title` | string | Название главы |
| `world_id` | string | ID локации (для звуков) |
| `scenes` | array | Массив сцен |
| `bridges` | array | Мостики в реальность |
| `rewards` | object | Награды в конце главы |
| `on_end` | object | Что делать после главы |

**Пример:**
```json
{
  "chapter": {
    "id": "ch02",
    "title": "Эйрик и Спасение Друга",
    "world_id": "forest",
    "scenes": [...],
    "bridges": [...],
    "rewards": {...},
    "on_end": {
      "action": "load_next_chapter",
      "target_chapter": "ch03",
      "auto_start": true
    }
  }
}
```

### 4.7 `report` — отчёт о прохождении

Используется в `type: "report"`.

| Поле | Тип | Описание |
|------|-----|----------|
| `chapter_id` | string | ID пройденной главы |
| `session_start` | string | Начало сессии (ISO) |
| `session_end` | string | Конец сессии (ISO) |
| `choices_made` | array | `{scene_id, choice_id, timestamp}` |
| `memory_vectors` | array | Собранные теги |
| `bridges_completed` | array | Выполненные мостики |
| `new_artifacts` | array | Полученные артефакты |
| `karma_gained` | number | Карма за сессию |

**Пример:**
```json
{
  "report": {
    "chapter_id": "ch02",
    "session_start": "2026-04-12T18:00:00Z",
    "session_end": "2026-04-12T18:15:00Z",
    "choices_made": [
      {
        "scene_id": "scene_01",
        "choice_id": "go_help",
        "timestamp": "2026-04-12T18:05:00Z"
      }
    ],
    "memory_vectors": ["helpful", "brave"],
    "bridges_completed": ["bridge_01"],
    "new_artifacts": ["friendship_medal"],
    "karma_gained": 7
  }
}
```

### 4.8 `bridges` — мостики в реальность

```json
{
  "bridges": {
    "pending": [
      {
        "id": "bridge_01",
        "task": "Обними маму и скажи 'я тебя люблю'",
        "karma_reward": 2,
        "created_at": "2026-04-12T10:00:00Z"
      }
    ],
    "completed": [
      {
        "id": "bridge_00",
        "task": "Найти мягкую игрушку",
        "completed_at": "2026-04-11T19:00:00Z",
        "karma_rewarded": 2
      }
    ]
  }
}
```

---

## 5. Формат книги (`book.json`)

Лежит в папке ребёнка, описывает текущую книгу.

```json
{
  "id": "LB-2026-04-05-0001",
  "title": "Эйрик и Тайна Фонаря",
  "description": "Первое приключение в пещере",
  "age_group": "7-12",
  "language": "ru",
  "version": "1.0",
  "created_by": "Six Fingers Studio",
  
  "main_character": "eirik",
  
  "chapters": [
    { "id": "ch01", "title": "Вход в пещеру", "file": "chapters/ch01.json" },
    { "id": "ch02", "title": "Глубина", "file": "chapters/ch02.json" }
  ],
  
  "starting_chapter": "ch01",
  "starting_scene": "scene_01",
  
  "global_intents": {
    "emergency": {
      "keywords": ["помогите", "спасите", "мне плохо", "больно"],
      "action": "pause_game_until_adult",
      "reply_text": "Я рядом. Сейчас позову взрослого.",
      "notify_parent": true
    },
    "stop": {
      "keywords": ["стоп", "хватит", "перестань", "замолчи"],
      "action": "reply",
      "reply_text": "Хорошо, я замолкаю. Скажи, когда продолжить.",
      "notify_parent": false
    }
  }
}
```

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | string | Уникальный ID книги (обычно uid ребёнка) |
| `title` | string | Название |
| `description` | string | Описание |
| `age_group` | string | `"3-6"`, `"7-12"`, `"13+"` |
| `main_character` | string | Кто главный герой |
| `chapters` | array | Список глав |
| `starting_chapter` | string | ID первой главы |
| `starting_scene` | string | ID первой сцены |
| `global_intents` | object | Глобальные команды (работают в любой сцене) |

---

## 6. Формат главы (`chapter.json`)

```json
{
  "id": "ch01",
  "title": "Вход в пещеру",
  "world_id": "cave",
  "scenes": [
    {
      "scene_id": "scene_01",
      "speaker": "eirik",
      "text": "Мы у входа в пещеру. Здесь темно и сыро. Слышишь, как капает вода? Пойдём внутрь?",
      "foley": ["water_drip.mp3", "footsteps_echo.mp3"],
      "music": "cave_ambient.mp3",
      "mode": "voice_choice",
      "choices": [
        {
          "id": "go_inside",
          "label": "Пойти внутрь",
          "keywords": ["пойдём", "внутрь", "да", "идём", "вперёд"],
          "next_scene": "scene_02_deep",
          "memory_vector": "brave"
        },
        {
          "id": "stay_outside",
          "label": "Остаться у входа",
          "keywords": ["остаться", "нет", "боюсь", "подождать"],
          "next_scene": "scene_02_outside",
          "memory_vector": "cautious"
        }
      ]
    },
    {
      "scene_id": "scene_02_deep",
      "speaker": "eirik",
      "text": "Ты смело шагнул в темноту. Вода капает где-то рядом. Слышишь?",
      "foley": ["water_drip_close.mp3"],
      "music": "cave_tension.mp3",
      "mode": "voice_choice",
      "choices": [
        {
          "id": "go_further",
          "label": "Идти дальше",
          "keywords": ["дальше", "вперёд", "глубже"],
          "next_scene": "scene_03_crystal",
          "memory_vector": "persistent"
        },
        {
          "id": "go_back",
          "label": "Вернуться",
          "keywords": ["назад", "вернуться", "выход"],
          "next_scene": "scene_02_outside",
          "memory_vector": "cautious"
        }
      ]
    }
  ],
  "on_end": {
    "action": "load_next_chapter",
    "target_chapter": "ch02",
    "auto_start": true
  }
}
```

### 6.1 Поля сцены

| Поле | Тип | Обязательность | Описание |
|------|-----|----------------|----------|
| `scene_id` | string | всегда | Уникальный ID сцены |
| `speaker` | string | всегда | `eirik`, `loka`, `fenrir`, `iskra` |
| `text` | string | всегда | Текст для TTS |
| `foley` | array | опционально | Пути к звукам (из `audio/foley/`) |
| `music` | string | опционально | Путь к фоновой музыке |
| `mode` | string | всегда | `"voice_choice"` |
| `choices` | array | всегда | Варианты действий |

### 6.2 Поля выбора

| Поле | Тип | Обязательность | Описание |
|------|-----|----------------|----------|
| `id` | string | всегда | Уникальный ID выбора |
| `label` | string | опционально | Для отладки (не видно ребёнку) |
| `keywords` | array | всегда | Ключевые слова для распознавания голоса |
| `next_scene` | string | всегда | ID следующей сцены |
| `memory_vector` | string | опционально | Тег для биографии |

### 6.3 `on_end` — завершение главы

| Поле | Тип | Описание |
|------|-----|----------|
| `action` | string | `"load_next_chapter"`, `"show_credits"`, `"end"` |
| `target_chapter` | string | ID следующей главы (если `load_next_chapter`) |
| `auto_start` | boolean | Автоматически начать следующую главу |

---

## 7. Библиотека слотов (для Студии)

Слоты — это **ингредиенты**, из которых Студия собирает главу. Они лежат в `system_registry/` и **не используются Искоркой напрямую**.

### 7.1 Персонаж (`characters/eirik.json`)

```json
{
  "id": "eirik",
  "name": "Эйрик",
  "role": "Хранитель",
  "traits": ["смелый", "мудрый", "боится темноты"],
  "voice": {
    "speed": 0.95,
    "pitch": "low"
  },
  "catchphrase": "Каждый шаг — это выбор. И каждый выбор — это ты.",
  "home_world": "cave"
}
```

### 7.2 Локация (`locations/cave.json`)

```json
{
  "id": "cave",
  "name": "Пещера",
  "ambient_sound": "/audio/ambient/cave_drip.mp3",
  "music_tension": "/audio/music/cave_tension.mp3",
  "music_calm": "/audio/music/cave_calm.mp3",
  "foley_palette": ["water_drip.mp3", "footsteps_echo.mp3", "wind_hollow.mp3"],
  "description": "Темно, сыро, эхо. Кажется, что кто-то следит."
}
```

### 7.3 Сюжет (`plots/defeat_fear.json`)

```json
{
  "id": "defeat_fear",
  "name": "Победить страх",
  "arc_structure": "hero_vs_self",
  "mandatory_beats": [
    "герой сталкивается со страхом",
    "герой пытается избежать",
    "герой находит опору",
    "герой действует вопреки страху",
    "герой побеждает страх"
  ],
  "typical_lesson": "Смелость — это не отсутствие страха, а действие вопреки ему",
  "suitable_ages": ["3-6", "7-12"]
}
```

### 7.4 Финал (`finales/skill.json`)

```json
{
  "id": "skill",
  "type": "internal",
  "reward_description": "Герой получает новый навык или качество",
  "karma_base": 3,
  "bridge_suggestion": "Попробуй сегодня сделать то, чего боялся вчера"
}
```

### 7.5 Готовая книга (`ready_books/eirik_cave_intro.json`)

Это **полностью готовая первая глава**, которая копируется ребёнку при регистрации.

```json
{
  "book_id": "eirik_cave_intro",
  "title": "Эйрик и Тайна Фонаря",
  "description": "Первое приключение в пещере",
  "age_group": "7-12",
  "main_character": "eirik",
  "home_world": "cave",
  "chapter": {
    "id": "ch01",
    "title": "Вход в пещеру",
    "world_id": "cave",
    "scenes": [...],
    "on_end": {
      "action": "end",
      "message": "Ты прошёл первое испытание! Скоро будет продолжение."
    }
  },
  "initial_bridges": [
    {
      "id": "bridge_intro",
      "task": "Найди в комнате предмет, который издаёт мягкий звук",
      "karma_reward": 2
    }
  ],
  "initial_karma": 0
}
```

---

## 8. Биография и память (`biography.json`)

```json
{
  "uid": "LB-2026-04-05-0001",
  "child_name": "Женя",
  "created_at": "2026-04-05T00:00:00Z",
  "updated_at": "2026-04-12T10:00:00Z",
  "total_stories": 3,
  
  "main_character": "eirik",
  "home_world": "cave",
  
  "karmic_trail": [
    {
      "date": "2026-04-05T22:41:00Z",
      "chapter_id": "ch01",
      "theme": "смелость",
      "choices_made": [
        { "choice_id": "go_inside", "memory_vector": "brave" }
      ],
      "key_message": "Темнота — не враг, а приключение"
    }
  ],
  
  "artifacts": [
    {
      "id": "crystal_of_bravery",
      "name": "Кристалл смелости",
      "obtained_at": "2026-04-05T22:45:00Z"
    }
  ],
  
  "character_bonds": {
    "eirik": 5,
    "loka": 2
  },
  
  "karma": {
    "current": 12,
    "history": [
      { "ts": "2026-04-05T22:45:00Z", "delta": 5, "reason": "chapter_completed" }
    ]
  },
  
  "psychological_patterns": ["Смелость:высокая", "Любознательность:средняя"]
}
```

---

## 9. Этика и безопасность (`ethics.json`)

```json
{
  "version": "3.0",
  
  "forbidden_topics": [
    "насилие как решение",
    "смерть как наказание",
    "буллинг без выхода",
    "самоповреждение"
  ],
  
  "forbidden_phrases": [
    "ты должен",
    "ты обязан",
    "так нельзя",
    "это плохо",
    "перестань бояться",
    "не плачь"
  ],
  
  "empathy_rules": [
    "Всегда сначала называй чувство ребёнка",
    "Никогда не давай готовых решений",
    "Вопрос в конце каждого ответа — обязательно"
  ],
  
  "redirect_triggers": {
    "keywords": ["убью", "убей", "умереть", "себя порезать", "суицид", "хочу исчезнуть"],
    "redirect_response": "Ты сказал кое-что важное. Расскажи мне — что ты сейчас чувствуешь внутри?",
    "notify_parent": true
  },
  
  "age_limits": {
    "3-6": { "max_session_minutes": 15, "max_choices_per_scene": 2 },
    "7-12": { "max_session_minutes": 30, "max_choices_per_scene": 3 },
    "13+": { "max_session_minutes": 45, "max_choices_per_scene": 4 }
  }
}
```

---

## 10. API Маяка

### 10.1 Эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/package/order` | Принять заказ от Кабинета, отправить в Студию |
| POST | `/api/package/deliver` | Принять готовую главу от Студии, сохранить |
| POST | `/api/package/report` | Принять отчёт от Искорки, обновить БД |
| GET | `/api/package/child/{uid}` | Отдать свежий `story_package.json` (глава + биография) |
| GET | `/api/registry` | Список всех детей |
| POST | `/api/registry/add_child` | Добавить нового ребёнка |
| GET | `/api/health` | Проверка статуса |

### 10.2 Форматы запросов/ответов

**POST `/api/package/order`**
- Request: `story_package.json` с `type: "order"`
- Response: `{ "ok": true, "package_id": "pkg_001", "status": "processing" }`

**POST `/api/package/deliver`**
- Request: `story_package.json` с `type: "chapter"`
- Response: `{ "ok": true, "chapter_id": "ch02", "saved_to": "chapters/ch02.json" }`

**POST `/api/package/report`**
- Request: `story_package.json` с `type: "report"`
- Response: `{ "ok": true, "karma_updated": 19, "new_artifacts": 1 }`

**GET `/api/package/child/{uid}`**
- Response: `story_package.json` с `type: "chapter"` (последняя не пройденная глава) или `type: "report"` (если всё пройдено)

---

## 11. Поток данных (цикл жизни)

### 11.1 Регистрация и первая книга

```
1. КАБИНЕТ РОДИТЕЛЯ
   → выбирает book_id (eirik_cave_intro)
   → отправляет POST /api/package/order
     { meta:{type:"order"}, child:{name:"Женя",age_group:"7-12"}, order:{mode:"first_book",book_id:"eirik_cave_intro"} }

2. МАЯК
   → создаёт uid (LB-2026-04-12-0001)
   → создаёт папку books/{uid}/
   → копирует готовую книгу из system_registry/ready_books/
   → создаёт biography.json, child_profile.json
   → возвращает {ok:true, uid:"..."}

3. ИСКОРКА
   → загружается с ?uid=...
   → GET /api/package/child/{uid}
   → получает story_package.json с главой
   → показывает главу
```

### 11.2 Заказ следующей главы

```
1. КАБИНЕТ РОДИТЕЛЯ
   → выбирает слоты (location, plot, finale)
   → отправляет POST /api/package/order

2. МАЯК
   → дополняет заказ biography_snapshot из БД
   → отправляет в Студию (HTTP запрос)

3. СТУДИЯ
   → читает biography_snapshot (знает main_character)
   → читает слоты
   → генерирует главу (A00 → A16)
   → возвращает story_package.json с type:"chapter"

4. МАЯК
   → сохраняет главу в chapters/ch{N}.json
   → обновляет book.json (добавляет главу в список)
   → возвращает ответ Кабинету

5. ИСКОРКА
   → при следующем запуске или по команде загружает новую главу
```

### 11.3 Отчёт

```
1. ИСКОРКА
   → ребёнок прошёл главу
   → формирует report
   → отправляет POST /api/package/report

2. МАЯК
   → обновляет biography.json:
      - добавляет choices_made в karmic_trail
      - добавляет new_artifacts
      - обновляет karma.current
      - обновляет character_bonds
   → обновляет basket.json (мостики)
   → возвращает ответ

3. КАБИНЕТ РОДИТЕЛЯ
   → при загрузке видит обновлённые графики
```

---

## 12. Что упраздняется из старых версий

| Было (v2.0) | Стало (v3.0) |
|-------------|--------------|
| `free_talk` | **Удалено** |
| `scripted_responses` | **Удалено** (только `choices.keywords`) |
| `ai_instructions` | **Удалено** |
| `max_turns` | **Удалено** |
| `mode: "free_talk"` | **Удалено** |
| `mode: "ask_choice"` | Переименовано в `"voice_choice"` |
| Гибридный Intent Engine (LLM fallback) | Только keyword-matching |
| LLM в рантайме Искорки | Только в Студии (при генерации) |
| `intro_event` объект | Упрощено до полей `speaker`, `text`, `foley`, `music` |
| `on_end` как строка | Только объект с `action` |

---

## 13. Глоссарий

| Термин | Значение |
|--------|----------|
| **Искорка** | HTML/JS плеер для ребёнка (чёрный экран, голос, 3D-звук) |
| **Маяк** | FastAPI сервер, хранит данные, роутит запросы |
| **Студия** | 18 агентов, генерирует главы из слотов |
| **Кабинет Родителя** | Dashboard UI для родителя (кнопки, графики) |
| **story_package.json** | Единый контрактный файл между всеми узлами |
| **Слот** | Ингредиент для генерации (персонаж, локация, сюжет, финал) |
| **voice_choice** | Режим сцены: ребёнок выбирает голосом по ключевым словам |
| **memory_vector** | Тег выбора, сохраняется в biography.json |
| **Мостик в реальность** | Задание для ребёнка в реальном мире |
| **Карма** | Очки прогресса, накапливаются за прохождение |
| **uid** | Сквозной ID ребёнка (`LB-YYYY-MM-DD-NNNN`) |

---

## Приложение А: Пример полного `story_package.json` (заказ)

```json
{
  "meta": {
    "version": "3.0",
    "type": "order",
    "timestamp": "2026-04-12T10:00:00Z",
    "package_id": "pkg_001"
  },
  "child": {
    "uid": "LB-2026-04-05-0001",
    "name": "Женя",
    "age_group": "7-12"
  },
  "order": {
    "mode": "next_chapter",
    "slots": {
      "location": "forest",
      "plot": "rescue_friend",
      "finale": "friendship"
    }
  },
  "biography_snapshot": {
    "main_character": "eirik",
    "artifacts": ["crystal_of_bravery"],
    "character_bonds": { "eirik": 5, "loka": 2 },
    "karma": 12,
    "last_choices": ["brave", "curious"]
  }
}
```

## Приложение Б: Пример полного `story_package.json` (готовая глава)

```json
{
  "meta": {
    "version": "3.0",
    "type": "chapter",
    "timestamp": "2026-04-12T10:05:00Z",
    "package_id": "pkg_002",
    "in_response_to": "pkg_001"
  },
  "child": {
    "uid": "LB-2026-04-05-0001"
  },
  "chapter": {
    "id": "ch02",
    "title": "Эйрик и Спасение Друга",
    "world_id": "forest",
    "scenes": [
      {
        "scene_id": "scene_01",
        "speaker": "eirik",
        "text": "Мы в лесу. Слышу чей-то плач...",
        "foley": ["forest_wind.mp3", "crying.mp3"],
        "mode": "voice_choice",
        "choices": [
          {
            "id": "go_help",
            "label": "Пойти помочь",
            "keywords": ["помочь", "пойти", "спасти"],
            "next_scene": "scene_02_help",
            "memory_vector": "helpful"
          }
        ]
      }
    ],
    "bridges": [
      {
        "id": "bridge_01",
        "task": "Обними маму",
        "karma_reward": 2
      }
    ],
    "rewards": {
      "artifacts": [
        {
          "id": "friendship_medal",
          "name": "Медаль дружбы",
          "sound": "/audio/artifacts/medal.mp3"
        }
      ],
      "karma_reward": 5
    },
    "on_end": {
      "action": "end",
      "message": "Ты спас друга! Скоро новое приключение."
    }
  }
}
```

## Приложение В: Пример полного `story_package.json` (отчёт)

```json
{
  "meta": {
    "version": "3.0",
    "type": "report",
    "timestamp": "2026-04-12T18:20:00Z",
    "package_id": "pkg_003",
    "in_response_to": "pkg_002"
  },
  "child": {
    "uid": "LB-2026-04-05-0001"
  },
  "report": {
    "chapter_id": "ch02",
    "session_start": "2026-04-12T18:00:00Z",
    "session_end": "2026-04-12T18:15:00Z",
    "choices_made": [
      {
        "scene_id": "scene_01",
        "choice_id": "go_help",
        "timestamp": "2026-04-12T18:05:00Z"
      }
    ],
    "memory_vectors": ["helpful", "brave"],
    "bridges_completed": ["bridge_01"],
    "new_artifacts": ["friendship_medal"],
    "karma_gained": 7
  }
}
```

---

**Конец документа.**
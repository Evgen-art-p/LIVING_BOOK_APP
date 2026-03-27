# Book Package — формат пакета книжки

> Это контракт между студией (фабрикой) и приложением (плеером).
> Студия производит пакет. Приложение его загружает и проживает с ребёнком.

## Структура пакета

```
my_book/
├── book.json              ← главный файл: метаданные + оглавление
├── chapters/
│   ├── ch01_awakening.json    ← глава: сцены, ветки выбора, реплики
│   ├── ch02_forest.json
│   └── ...
├── characters/
│   ├── eirik.json             ← персонаж: голос, характер, системный промпт
│   └── loka.json
├── audio/
│   ├── foley/                 ← звуки: шаги, скрип, дождь
│   │   ├── footsteps_snow.mp3
│   │   └── rain_light.mp3
│   ├── music/                 ← фоновая музыка по настроениям
│   │   ├── calm_forest.mp3
│   │   └── tension_cave.mp3
│   └── voices/                ← предзаписанные ключевые фразы (опционально)
│       └── eirik_greeting.mp3
├── ethics.json            ← запрещённые темы, фразы, возрастные лимиты
└── config.json            ← технические настройки: temperature, модель, язык
```

## book.json — главный файл

```json
{
  "id": "grondheim_book_01",
  "title": "Грондхейм: Пробуждение",
  "description": "Первая книга мира Грондхейм",
  "age_group": "7-12",
  "language": "ru",
  "version": "1.0.0",
  "created_by": "Six Fingers Studio",
  "chapters": [
    { "id": "ch01", "title": "Пробуждение", "file": "chapters/ch01_awakening.json" },
    { "id": "ch02", "title": "Тёмный лес",  "file": "chapters/ch02_forest.json" }
  ],
  "characters": [
    { "id": "eirik", "file": "characters/eirik.json" },
    { "id": "loka",  "file": "characters/loka.json" }
  ],
  "starting_chapter": "ch01",
  "starting_scene": "scene_01"
}
```

## Глава (chapter JSON)

Каждая глава — набор сцен. Сцена — это момент истории.

```json
{
  "id": "ch01",
  "title": "Пробуждение",
  "scenes": [
    {
      "id": "scene_01",
      "speaker": "eirik",
      "text": "Тише... Ты слышишь? Снег скрипит под ногами. Мы у подножия горы Грондхейм.",
      "audio": {
        "foley": ["foley/footsteps_snow.mp3"],
        "music": "music/calm_forest.mp3",
        "spatial": { "speaker_position": { "azimuth": 45, "distance": 2.0 } }
      },
      "after_speech": "ask_choice",
      "choices": [
        {
          "id": "go_cave",
          "label": "Пойти к пещере",
          "triggers": ["memory:brave_choice"],
          "next_scene": "scene_02a"
        },
        {
          "id": "stay_camp",
          "label": "Остаться у костра",
          "triggers": ["memory:careful_choice"],
          "next_scene": "scene_02b"
        }
      ]
    },
    {
      "id": "scene_02a",
      "speaker": "eirik",
      "mode": "free_talk",
      "context": "Ребёнок выбрал пещеру. Эйрик ведёт его внутрь. Темно, эхо.",
      "ai_instructions": "Задавай вопросы. Не давай ответов. Помоги ребёнку описать что он чувствует в темноте.",
      "max_turns": 5,
      "on_end": "scene_03",
      "audio": {
        "foley": ["foley/cave_echo.mp3", "foley/water_drip.mp3"],
        "music": "music/tension_cave.mp3"
      }
    }
  ]
}
```

### Два режима сцены:

1. **`ask_choice`** — фиксированные варианты. Персонаж говорит, ребёнок выбирает из списка.
2. **`free_talk`** — свободный разговор через Gemini. Персонаж ведёт диалог по правилам из `ai_instructions`. Заканчивается после `max_turns` или по ключевому слову.

## Персонаж (character JSON)

```json
{
  "id": "eirik",
  "name": "Эйрик",
  "role": "Верный Хранитель",
  "voice": {
    "tts_model": "elevenlabs",
    "voice_id": "xxx-xxx",
    "speed": 0.95,
    "pitch": "low",
    "emotion_style": "warm_protective"
  },
  "personality": "Спокойный, мудрый, терпеливый. Говорит медленно. Любит природу. Никогда не торопит ребёнка.",
  "system_prompt": "Ты — Эйрик, хранитель мира Грондхейм. Ты разговариваешь с ребёнком. Твоя задача — не давать готовых ответов, а задавать направляющие вопросы. Говори простым языком. Никогда не пугай и не стыди.",
  "catchphrase": "Каждый шаг — это выбор. И каждый выбор — это ты."
}
```

## ethics.json — этический фильтр

```json
{
  "forbidden_topics": ["насилие", "смерть как наказание", "буллинг без решения"],
  "forbidden_phrases": ["ты должен", "это плохо", "так делать нельзя"],
  "age_limits": {
    "3-6": { "max_session_minutes": 15, "max_choices_per_scene": 2 },
    "7-12": { "max_session_minutes": 30, "max_choices_per_scene": 3 },
    "13+": { "max_session_minutes": 45, "max_choices_per_scene": 4 }
  }
}
```

## config.json — настройки ИИ

```json
{
  "llm": {
    "provider": "google",
    "model": "gemini-2.0-flash",
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "max_tokens": 300
  },
  "stt": {
    "model": "whisper-large-v3-turbo",
    "language": "ru"
  },
  "tts": {
    "provider": "elevenlabs",
    "default_speed": 1.0
  }
}
```

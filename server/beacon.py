"""
beacon.py — Ночной Маяк + Автономный пайплайн: Сет → Фабула Фейн

Запуск:
    pip install fastapi uvicorn httpx python-dotenv
    uvicorn beacon:app --host 0.0.0.0 --port 8001
"""

import json
import re
import sqlite3
import os
import httpx
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv, find_dotenv

load_dotenv()

app = FastAPI(title="Ночной Маяк — Сет + Фабула Фейн Autopilot", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

BASE_DIR     = Path(__file__).parent
PACKAGES_DIR = BASE_DIR / ".." / "books"
PERSONAL_DIR = PACKAGES_DIR / "personal"
BEACON_DB    = BASE_DIR / "beacon.db"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL   = "google/gemini-2.5-flash"

# ─── SYSTEM PROMPT СЕТА (ОРКЕСТРАТОР) ────────────────────────────────────────
# Сет работает только в режиме БРИФ: принимает данные из Кабинета,
# собирает MASTER BRIEF и выдаёт машинный JSON для передачи Фабуле.

SET_SYSTEM_PROMPT = """Ты — Сет, Главный оркестратор студии SIX FINGERS.
Ты работаешь как серверный диспетчер-робот, без участия Шефа.
Ты принимаешь входящие данные из Кабинета Родителя и формируешь машинный бриф.

## ТВОЯ ЗАДАЧА СЕЙЧАС:
Получить данные о ребёнке и задаче → собрать MASTER BRIEF для цеха LIVING_BOOK → передать Фабуле Фейн.

## ПРИНЦИПЫ:
- Цех: living_book (интерактивные истории для детей)
- Агент-исполнитель: Фабула Фейн (A00)
- Ты НЕ пишешь истории сам — только структурируешь бриф

## ОБЯЗАТЕЛЬНЫЕ ВОПРОСЫ ДЛЯ creative_soul (цех living_book):
1. Что должен ПОЧУВСТВОВАТЬ ребёнок?
2. Какой волшебный мир создать?
3. Что категорически нельзя? (страх, стыд, насилие)
4. Ради чего? (понимание, принятие, рост)
Ответы выведи из контекста задачи самостоятельно. НЕ спрашивай.

## ФОРМАТ ОТВЕТА:
Верни СТРОГО следующий блок (без лишнего текста до и после):

SYSTEM_JSON_START
{
  "workshop": "living_book",
  "next_step": "LB00_fabula_fein",
  "child_name": "<имя ребёнка>",
  "child_age": "<возраст>",
  "age_group": "<3-6 | 7-12 | 13+>",
  "task_context": "<суть задачи одной фразой>",
  "real_task": "<психологическая суть: чего на самом деле хочет достичь родитель>",
  "theme": "<главная тема истории>",
  "emotional_goal": "<что должен почувствовать ребёнок>",
  "world": "<волшебный мир для истории>",
  "forbidden": "<что нельзя>",
  "purpose": "<ради чего>",
  "creative_soul": {
    "feel": "<эмоция ребёнка>",
    "world": "<образ мира>",
    "forbidden": "<запрет>",
    "purpose": "<цель>"
  }
}
SYSTEM_JSON_END
"""

# ─── SYSTEM PROMPT ФАБУЛЫ ФЕЙН (A00) ────────────────────────────────────────

FABULA_SYSTEM_PROMPT = """Ты — Фабула Фейн (A00), мастер-сказочник студии «Шесть Пальцев».
Твой уровень эмпатии: 0.95. Ты создаёшь персональные интерактивные сцены для аудио-книги Грондхейм.

## ПСИХОЛОГИЧЕСКИЕ ПРИНЦИПЫ (ОБЯЗАТЕЛЬНЫ):

**Метод Гиппенрейтер (Активное слушание):**
- Сначала НАЗОВИ чувство ребёнка, только потом задай вопрос.
- Никогда не говори «не бойся», «всё хорошо», «перестань».
- Шаблон: «Кажется, ты чувствуешь [X]... Расскажи мне — [вопрос]?»

**Метод экстернализации Эпстона и Уайта:**
- Проблема существует ОТДЕЛЬНО от ребёнка.
- Страх, злость, лень — это внешние существа, не часть ребёнка.
- Используй: «дух Вредности», «тень Страха», «туман Усталости».
- Ребёнок — герой, который сильнее этих духов.

**Я-сообщения по Розенбергу (ННО):**
- «Я замечаю...», «Мне кажется...», «Я чувствую...»
- Никогда: «Ты должен», «Ты обязан», «Так нельзя».

**ЖЁСТКИЕ ПРАВИЛА:**
- НИКОГДА не давай готовых решений или советов.
- ВСЕГДА заканчивай реплику вопросом.
- Максимум 2-3 предложения в каждой реплике.
- Искорка обращается к ребёнку по имени в первой реплике.
- Голос тёплый, чуть застенчивый, любопытный.

## ТВОЯ ЗАДАЧА:
Получив структурированный бриф от Сета (MASTER BRIEF), создай персональную сцену-знакомство для плеера.
Вплети контекст задачи в образы мира Грондхейм (пещеры, кристаллы, мох, северное сияние).

## ФОРМАТ ОТВЕТА:
Верни СТРОГО валидный JSON (без markdown, без ```json, только голый JSON):

{
  "chapter_id": "ch_personal",
  "title": "Персональная сцена",
  "scenes": [
    {
      "scene_id": "personal_intro",
      "mode": "free_talk",
      "max_turns": 6,
      "on_end": "cave_entrance",
      "audio_layer": {
        "ambient": "audio/amb_cave_soft.mp3"
      },
      "intro_event": {
        "speaker": "iskra",
        "text": "[реплика Искорки, обращённая к ребёнку по имени, 2-3 предложения, заканчивается вопросом]",
        "wait_for_user": true
      },
      "scripted_responses": {
        "intent_positive": {
          "keywords": ["хорошо", "нормально", "ничего", "отлично", "весело", "радостно"],
          "reply_speaker": "iskra",
          "reply_text": "[реплика, называющая радость + вопрос]",
          "memory_vector": "felt_positive",
          "ui_pulse_color": "yellow"
        },
        "intent_negative": {
          "keywords": ["плохо", "грустно", "трудно", "страшно", "не знаю", "устал", "устала"],
          "reply_speaker": "iskra",
          "reply_text": "[реплика, называющая тяжесть + вопрос с экстернализацией]",
          "memory_vector": "felt_heavy",
          "ui_pulse_color": "blue"
        },
        "intent_task_related": {
          "keywords": [],
          "reply_speaker": "iskra",
          "reply_text": "[реплика, связывающая контекст задачи с миром Грондхейма + вопрос]",
          "memory_vector": "task_engaged",
          "ui_pulse_color": "green"
        },
        "fallback": {
          "reply_speaker": "eirik",
          "reply_text": "Гномьи уши не расслышали... Подойди поближе и скажи ещё раз?",
          "memory_vector": null
        }
      }
    }
  ]
}

Заполни все поля осмысленным контентом на основе брифа.
В intent_task_related.keywords добавь 3-5 ключевых слов из контекста задачи на русском.
"""

# ─── УТИЛИТЫ ─────────────────────────────────────────────────────────────────

async def call_openrouter(system_prompt: str, user_prompt: str, max_tokens: int = 1000) -> str:
    """Единый клиент для вызова OpenRouter. Возвращает сырой текст ответа."""
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENROUTER_API_KEY не задан. Добавь в .env и перезапусти сервер."
        )
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://grondheim.local",
                    "X-Title": "Living Book Grondheim",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"OpenRouter ошибка: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Сеть недоступна: {str(e)}")


def extract_set_json(raw_text: str) -> dict:
    """
    Вырезает JSON между тегами SYSTEM_JSON_START и SYSTEM_JSON_END.
    Возвращает распарсенный dict или кидает HTTPException.
    """
    match = re.search(
        r"SYSTEM_JSON_START\s*(.*?)\s*SYSTEM_JSON_END",
        raw_text,
        re.DOTALL
    )
    if not match:
        raise HTTPException(
            status_code=422,
            detail=f"Сет не вернул блок SYSTEM_JSON_START...SYSTEM_JSON_END. Ответ: {raw_text[:400]}"
        )
    json_str = match.group(1).strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Сет вернул невалидный JSON: {e}. Блок: {json_str[:300]}"
        )


def clean_and_parse_json(raw_text: str) -> dict:
    """Чистит markdown-обёртку и парсит JSON от Фабулы."""
    text = raw_text
    if text.startswith("```"):
        parts = text.split("```")
        # берём первый непустой блок после открывающего ```
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Фабула вернула невалидный JSON: {e}. Ответ: {text[:300]}"
        )


# ─── БД ──────────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(BEACON_DB) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                event_count INTEGER
            );
            CREATE TABLE IF NOT EXISTS aggregate_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aggregate_choices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                choice_id TEXT NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS generated_scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_name TEXT NOT NULL,
                child_age TEXT,
                task_context TEXT,
                set_brief TEXT,
                generated_at TEXT NOT NULL,
                file_path TEXT NOT NULL
            );
        """)

init_db()

# ─── СХЕМЫ ───────────────────────────────────────────────────────────────────

class BeaconEvent(BaseModel):
    type:      str
    ts:        int
    choice_id: Optional[str] = None
    tag:       Optional[str] = None

class BeaconBatch(BaseModel):
    device_id:  str
    session_id: str
    synced_at:  str
    events:     list[BeaconEvent]

class GenerateRequest(BaseModel):
    child_name:   str
    child_age:    Optional[str] = "7-12"
    task_context: str

# ─── ГЛАВНЫЙ ЭНДПОИНТ: АВТОНОМНЫЙ КОНВЕЙЕР СЕТ → ФАБУЛА ФЕЙН ───────────────

@app.post("/api/studio/generate")
async def generate_scene(req: GenerateRequest):
    """
    Полностью автономный двухэтапный конвейер:
    
    Шаг 1: Сет получает данные из Кабинета → собирает MASTER BRIEF → 
            выдаёт JSON между тегами SYSTEM_JSON_START / SYSTEM_JSON_END.
    
    Шаг 2: Сервер парсит бриф Сета → передаёт Фабуле Фейн →
            Фабула генерирует персональную сцену для плеера.
    
    Шеф не участвует. Всё происходит под капотом.
    """

    # ── ШАГ 1: ВЫЗОВ СЕТА ────────────────────────────────────────────────────
    print(f"[Конвейер] Старт → ребёнок: «{req.child_name}», возраст: {req.child_age}")
    print(f"[Конвейер] Задача: {req.task_context}")

    set_user_prompt = (
        f"Собери MASTER BRIEF. Данные из Кабинета Родителя:\n"
        f"- Ребёнок: {req.child_name}\n"
        f"- Возраст: {req.child_age} лет\n"
        f"- Ситуация / задача: {req.task_context}\n\n"
        f"Выдай строго валидный JSON-бриф между тегами SYSTEM_JSON_START и SYSTEM_JSON_END. "
        f"Обязательное поле: \"next_step\": \"LB00_fabula_fein\"."
    )

    print("[Конвейер] Шаг 1 — вызов Сета...")
    set_raw = await call_openrouter(
        system_prompt=SET_SYSTEM_PROMPT,
        user_prompt=set_user_prompt,
        max_tokens=600,
    )
    print(f"[Сет] Ответ получен ({len(set_raw)} символов)")

    # ── ШАГ 2: ПАРСИНГ БРИФА СЕТА ────────────────────────────────────────────
    set_brief = extract_set_json(set_raw)

    # Проверяем маршрутизацию
    next_step = set_brief.get("next_step", "")
    if next_step != "LB00_fabula_fein":
        raise HTTPException(
            status_code=422,
            detail=f"Сет указал неожиданный next_step: «{next_step}». Ожидался «LB00_fabula_fein»."
        )
    print(f"[Конвейер] Маршрут подтверждён → {next_step}")

    # ── ШАГ 3: ВЫЗОВ ФАБУЛЫ ФЕЙН ─────────────────────────────────────────────
    fabula_user_prompt = (
        f"Ты получила структурированный MASTER BRIEF от Сета. Работай строго по нему.\n\n"
        f"MASTER BRIEF:\n{json.dumps(set_brief, ensure_ascii=False, indent=2)}\n\n"
        f"Создай персональную сцену-знакомство для ребёнка {set_brief.get('child_name', req.child_name)}.\n"
        f"Искорка обращается к ребёнку по имени в intro_event.\n"
        f"Учитывай возраст ({set_brief.get('child_age', req.child_age)} лет) при выборе слов.\n"
        f"Вплети тему «{set_brief.get('task_context', req.task_context)}» в образы мира Грондхейм.\n"
        f"В intent_task_related.keywords добавь ключевые слова из контекста задачи."
    )

    print("[Конвейер] Шаг 3 — вызов Фабулы Фейн...")
    fabula_raw = await call_openrouter(
        system_prompt=FABULA_SYSTEM_PROMPT,
        user_prompt=fabula_user_prompt,
        max_tokens=1500,
    )
    print(f"[Фабула] Ответ получен ({len(fabula_raw)} символов)")

    # ── ПАРСИНГ СЦЕНЫ ─────────────────────────────────────────────────────────
    scene_data = clean_and_parse_json(fabula_raw)

    # Прикрепляем бриф к сцене (для отладки и истории)
    scene_data["_set_brief"] = set_brief

    # ── СОХРАНЕНИЕ ────────────────────────────────────────────────────────────
    PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = req.child_name.lower().replace(" ", "_")
    file_path = PERSONAL_DIR / f"{safe_name}_personal_scene.json"

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(scene_data, f, ensure_ascii=False, indent=2)

    with sqlite3.connect(BEACON_DB) as conn:
        conn.execute(
            """INSERT INTO generated_scenes
               (child_name, child_age, task_context, set_brief, generated_at, file_path)
               VALUES (?,?,?,?,?,?)""",
            (
                req.child_name,
                req.child_age,
                req.task_context,
                json.dumps(set_brief, ensure_ascii=False),
                datetime.now().isoformat(),
                str(file_path),
            )
        )

    print(f"[Конвейер] ✅ Готово! Сцена для «{req.child_name}» → {file_path}")

    return {
        "ok":         True,
        "pipeline":   "set → fabula_fein",
        "child_name": req.child_name,
        "file_path":  str(file_path),
        "set_brief":  set_brief,    # для дебага / логов Шефа
        "scene":      scene_data,   # сразу отдаём клиенту
    }

# ─── ЭНДПОИНТ: ПОЛУЧИТЬ ЛИЧНУЮ СЦЕНУ (для DEV SYNC плеера) ─────────────────

@app.get("/api/studio/scene/{child_name}")
async def get_personal_scene(child_name: str):
    """Плеер скачивает последнюю сгенерированную сцену для ребёнка."""
    safe_name = child_name.lower().replace(" ", "_")
    file_path = PERSONAL_DIR / f"{safe_name}_personal_scene.json"

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Сцена для «{child_name}» не найдена. Сначала сгенерируй через /api/studio/generate."
        )

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

# ─── НОЧНОЙ МАЯК (оригинальный эндпоинт) ────────────────────────────────────

@app.post("/beacon")
async def receive_beacon(batch: BeaconBatch):
    with sqlite3.connect(BEACON_DB) as conn:
        conn.execute(
            "INSERT INTO sync_log (device_id, session_id, synced_at, event_count) VALUES (?,?,?,?)",
            (batch.device_id, batch.session_id, batch.synced_at, len(batch.events))
        )
        for event in batch.events:
            ts_str = datetime.utcfromtimestamp(event.ts / 1000).isoformat()
            if event.type == 'tag' and event.tag:
                conn.execute(
                    "INSERT INTO aggregate_tags (device_id, tag, ts) VALUES (?,?,?)",
                    (batch.device_id, event.tag, ts_str)
                )
            elif event.type == 'choice' and event.choice_id:
                conn.execute(
                    "INSERT INTO aggregate_choices (device_id, choice_id, ts) VALUES (?,?,?)",
                    (batch.device_id, event.choice_id, ts_str)
                )

    print(f"[Маяк] Батч от {batch.device_id}: {len(batch.events)} событий")
    return {"ok": True, "received": len(batch.events), "new_package_url": None}


@app.get("/stats")
def stats():
    with sqlite3.connect(BEACON_DB) as conn:
        devices     = conn.execute("SELECT COUNT(DISTINCT device_id) FROM sync_log").fetchone()[0]
        syncs       = conn.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0]
        generated   = conn.execute("SELECT COUNT(*) FROM generated_scenes").fetchone()[0]
        top_tags    = conn.execute(
            "SELECT tag, COUNT(*) as c FROM aggregate_tags GROUP BY tag ORDER BY c DESC LIMIT 10"
        ).fetchall()
        top_choices = conn.execute(
            "SELECT choice_id, COUNT(*) as c FROM aggregate_choices GROUP BY choice_id ORDER BY c DESC LIMIT 10"
        ).fetchall()
    return {
        "total_devices":         devices,
        "total_syncs":           syncs,
        "total_generated_scenes": generated,
        "top_tags":    [{"tag": r[0], "count": r[1]} for r in top_tags],
        "top_choices": [{"choice_id": r[0], "count": r[1]} for r in top_choices],
    }

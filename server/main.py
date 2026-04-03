# main.py — объединённый сервер Маяка + Оркестратора с реальными агентами
import json
import os
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import requests
from dotenv import load_dotenv

# Загрузка .env
load_dotenv()

# Конфиг
OPEN_ROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY")
OPEN_ROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPEN_ROUTER_MODEL = os.getenv("OPEN_ROUTER_MODEL", "google/gemini-2.5-flash")
STORIES_ROOT = os.getenv("STORIES_ROOT", "stories")

print(f"🔑 API Key: {OPEN_ROUTER_API_KEY[:20] if OPEN_ROUTER_API_KEY else 'НЕТ'}")
print(f"🤖 Модель: {OPEN_ROUTER_MODEL}")
print(f"📁 Истории в: {STORIES_ROOT}")

os.makedirs(STORIES_ROOT, exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    child_name: str
    child_age: str
    task_context: str
    parent_email: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# 1. Родительский кабинет
# ═══════════════════════════════════════════════════════════════════
@app.get("/parent/feed")
async def parent_feed(limit: int = 15):
    events = []
    if os.path.exists(STORIES_ROOT):
        for child_name in os.listdir(STORIES_ROOT):
            child_dir = os.path.join(STORIES_ROOT, child_name)
            if not os.path.isdir(child_dir):
                continue
            for filename in os.listdir(child_dir):
                if filename.endswith(".json"):
                    filepath = os.path.join(child_dir, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            story = json.load(f)
                        status = "pending" if "_pending" in filename else "delivered"
                        events.append({
                            "type": "story_generated",
                            "child_name": child_name,
                            "story_id": filename.replace("_pending.json", "").replace("_delivered.json", ""),
                            "title": story.get("book", {}).get("title", "Новая история"),
                            "ts": datetime.fromtimestamp(os.path.getctime(filepath)).isoformat(),
                            "status": status
                        })
                    except:
                        pass
    events.sort(key=lambda x: x["ts"], reverse=True)
    return {"events": events[:limit]}


@app.get("/parent/stats")
async def parent_stats():
    return {
        "total_sessions": 0,
        "total_choices": 0,
        "total_chats": 0,
        "artifacts": [],
        "choices_history": [],
        "memory_tags": []
    }


# ═══════════════════════════════════════════════════════════════════
# 2. Генерация сказки через Студию
# ═══════════════════════════════════════════════════════════════════
@app.post("/api/studio/generate")
async def generate_story(request: GenerateRequest):
    print(f"📖 Заказ в Студию: {request.child_name}, {request.child_age}, {request.task_context}")
    
    STUDIO_URL = "http://localhost:8080"
    
    try:
        response = requests.post(
            f"{STUDIO_URL}/api/studio/generate",
            json={
                "child_name": request.child_name,
                "child_age": request.child_age,
                "task_context": request.task_context,
                "parent_email": request.parent_email,
            },
            timeout=10
        )
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"status": "error", "message": "Студия не запущена на порту 8080"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════════
# 3. Агенты через Open Router
# ═══════════════════════════════════════════════════════════════════
async def call_openrouter(prompt: str) -> str:
    """Вызов Open Router API"""
    headers = {
        "Authorization": f"Bearer {OPEN_ROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": OPEN_ROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 4000
    }
    
    response = requests.post(OPEN_ROUTER_URL, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()
    return data['choices'][0]['message']['content']


async def call_set(request: GenerateRequest) -> dict:
    """SET — собирает MASTER BRIEF"""
    prompt = f"""Ты — SET, главный оркестратор студии Six Fingers.

Шеф прислал задачу:
- Имя ребёнка: {request.child_name}
- Возраст: {request.child_age}
- Контекст: {request.task_context}

Цех: LIVING_BOOK.

Заполни creative_soul:
- Что должен ПОЧУВСТВОВАТЬ ребёнок?
- Какой волшебный мир создать?
- Что категорически нельзя? (страх, стыд, насилие)
- Ради чего? (понимание, принятие, рост)

Выдай ТОЛЬКО JSON без пояснений:

{{
  "agent": "SET",
  "stage": "routing",
  "project": {{
    "name": "История для {request.child_name}",
    "workshop": "living_book",
    "age_group": "{request.child_age}",
    "format": "interactive"
  }},
  "story": {{
    "theme": "courage",
    "real_task": "{request.task_context}",
    "desired_emotion": "радость, уверенность, спокойствие",
    "magic_world": "волшебный лес Грондхейм"
  }},
  "child": {{
    "name": "{request.child_name}",
    "age": "{request.child_age}"
  }},
  "key_message": "Что ребёнок должен вынести из истории",
  "next_step": "LB00_fabula_fein"
}}"""
    
    response = await call_openrouter(prompt)
    # Очищаем ответ от возможных markdown-обёрток
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    return json.loads(response)


async def call_fabula_fein(master_brief: dict) -> dict:
    """Фабула Фейн — пишет историю"""
    prompt = f"""Ты — Фабула Фейн (A00), Сказочник в студии Six Fingers.

MASTER BRIEF:
{json.dumps(master_brief, ensure_ascii=False, indent=2)}

Создай структуру интерактивной истории:
- Главный герой — ребёнок (имя из брифа)
- 3-5 сцен
- 2-3 ключевых выбора
- Счастливый финал

Выдай ТОЛЬКО JSON:

{{
  "story_id": "story_001",
  "title": "Название истории",
  "description": "Краткое описание",
  "scenes": [
    {{
      "id": "scene_01",
      "speaker": "eirik",
      "text": "Привет!...",
      "choices": []
    }}
  ],
  "characters": [
    {{"id": "eirik", "name": "Эйрик", "personality": "добрый гном"}}
  ]
}}"""
    
    response = await call_openrouter(prompt)
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    return json.loads(response)


async def call_vera_dusha(story: dict) -> dict:
    """Вера Душа — проверяет безопасность"""
    prompt = f"""Ты — Вера Душа (A00a), психолог в студии Six Fingers.

Проверь историю на психологическую безопасность для ребёнка:

{json.dumps(story, ensure_ascii=False, indent=2)}

Выдай ТОЛЬКО JSON:
{{
  "verdict": "safe",
  "issues": [],
  "recommendations": []
}}"""
    
    response = await call_openrouter(prompt)
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    return json.loads(response)


async def call_marka_fain(results: dict) -> dict:
    """Марка Файн — упаковывает в BOOK PACKAGE"""
    prompt = f"""Ты — Марка Файн (A16), финализатор в студии Six Fingers.

Упакуй результаты в BOOK PACKAGE для LIVING_BOOK_APP:

{json.dumps(results, ensure_ascii=False, indent=2)[:6000]}

Выдай ТОЛЬКО JSON со структурой:

{{
  "book": {{
    "id": "grondheim_book_01",
    "title": "Название",
    "description": "Описание",
    "age_group": "7-12",
    "language": "ru",
    "version": "1.0.0",
    "created_by": "Six Fingers Studio",
    "chapters": [{{"id": "ch01", "title": "Начало", "file": "chapters/ch01.json"}}],
    "characters": [{{"id": "eirik", "file": "characters/eirik.json"}}],
    "starting_chapter": "ch01",
    "starting_scene": "scene_01"
  }},
  "chapters": {{
    "ch01": {{
      "scenes": [
        {{
          "id": "scene_01",
          "mode": "free_talk",
          "intro_event": {{"speaker": "eirik", "text": "...", "wait_for_user": true}},
          "scripted_responses": {{
            "fallback": {{"reply_text": "Расскажи мне..."}}
          }}
        }}
      ]
    }}
  }},
  "characters": {{
    "eirik": {{
      "id": "eirik",
      "name": "Эйрик",
      "voice": {{"tts_model": "elevenlabs", "voice_id": "21m00Tcm4TlvDq8ikWAM"}}
    }}
  }},
  "ethics": {{
    "forbidden_topics": [],
    "forbidden_phrases": [],
    "age_limits": {{}}
  }},
  "config": {{
    "llm": {{"provider": "google", "model": "gemini-2.0-flash-exp", "temperature": 0.7}},
    "tts": {{"provider": "elevenlabs", "default_speed": 1.0}}
  }}
}}"""
    
    response = await call_openrouter(prompt)
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    return json.loads(response)


# ═══════════════════════════════════════════════════════════════════
# 4. Искорка забирает сказки
# ═══════════════════════════════════════════════════════════════════
@app.get("/api/beacon/stories")
async def get_stories(child_id: str):
    child_dir = os.path.join(STORIES_ROOT, child_id)
    
    if not os.path.exists(child_dir):
        return []
    
    pending_stories = []
    
    for filename in os.listdir(child_dir):
        if filename.endswith("_pending.json"):
            filepath = os.path.join(child_dir, filename)
            
            with open(filepath, 'r', encoding='utf-8') as f:
                story = json.load(f)
            
            pending_stories.append({
                "story_id": filename.replace("_pending.json", ""),
                "title": story.get("book", {}).get("title", "Новая история"),
                "package": story,
                "created_at": datetime.fromtimestamp(os.path.getctime(filepath)).isoformat()
            })
            
            new_name = filename.replace("_pending", "_delivered")
            os.rename(filepath, os.path.join(child_dir, new_name))
    
    return pending_stories


# ═══════════════════════════════════════════════════════════════════
# 5. Запуск
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    print("🚀 Сервер запущен на http://localhost:8001")
    print("🤖 Агенты работают через Open Router")
    uvicorn.run(app, host="0.0.0.0", port=8001)
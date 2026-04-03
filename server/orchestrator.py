# orchestrator.py
import json
import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import requests
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()

app = FastAPI()

# Конфиг из .env
OPEN_ROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY")
OPEN_ROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPEN_ROUTER_MODEL = os.getenv("OPEN_ROUTER_MODEL", "google/gemini-2.0-flash-exp:free")

STORIES_ROOT = os.getenv("STORIES_ROOT", "stories")
MAYAK_URL = os.getenv("MAYAK_URL", "http://localhost:8001")

class GenerateRequest(BaseModel):
    child_name: str
    child_age: str
    task_context: str
    parent_email: Optional[str] = None

# ═══════════════════════════════════════════════════════════════════
# 1. Родитель заказывает сказку
# ═══════════════════════════════════════════════════════════════════
@app.post("/api/studio/generate")
async def generate_story(request: GenerateRequest):
    """
    Родительский кабинет → сюда.
    Оркестратор сам запускает всех агентов.
    """
    
    print(f"📖 Получен заказ: {request.child_name}, {request.child_age}, {request.task_context}")
    
    # Шаг 1: SET собирает MASTER BRIEF
    master_brief = await call_set(request)
    print(f"✅ MASTER BRIEF получен")
    
    # Шаг 2: Запускаем цепочку LIVING_BOOK
    book_package = await run_living_book_pipeline(master_brief)
    print(f"✅ BOOK PACKAGE сгенерирован")
    
    # Шаг 3: Сохраняем в папку ребёнка
    story_id = f"story_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    child_dir = os.path.join(STORIES_ROOT, request.child_name)
    os.makedirs(child_dir, exist_ok=True)
    
    story_path = os.path.join(child_dir, f"{story_id}_pending.json")
    with open(story_path, 'w', encoding='utf-8') as f:
        json.dump(book_package, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Сохранено: {story_path}")
    
    return {
        "status": "ok",
        "message": f"Сказка '{story_id}' сгенерирована и ждёт ребёнка",
        "story_id": story_id,
        "child_name": request.child_name,
        "story_path": story_path
    }

# ═══════════════════════════════════════════════════════════════════
# 2. Вызов SET через Open Router
# ═══════════════════════════════════════════════════════════════════
async def call_set(request: GenerateRequest) -> dict:
    """
    Имитируем диалог с SET.
    SET должен выдать MASTER BRIEF в JSON.
    """
    
    prompt = f"""Ты — SET, главный оркестратор студии Six Fingers.

Шеф прислал задачу:
- Имя ребёнка: {request.child_name}
- Возраст: {request.child_age}
- Контекст: {request.task_context}

Цех определён: LIVING_BOOK.

Твоя задача — собрать MASTER BRIEF для цеха LIVING_BOOK.
Заполни creative_soul:
- Что должен ПОЧУВСТВОВАТЬ ребёнок?
- Какой волшебный мир создать?
- Что категорически нельзя? (страх, стыд, насилие)
- Ради чего? (понимание, принятие, рост)

Выдай ТОЛЬКО JSON в формате:

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
    "magic_world": "лес, пещеры, замок, космос, подводный мир"
  }},
  "child": {{
    "name": "{request.child_name}",
    "favorite_characters": [],
    "favorite_stories": []
  }},
  "key_message": "Что ребёнок должен вынести из истории",
  "next_step": "LB00_fabula_fein"
}}

Без пояснений. Только JSON.
"""
    
    response = await call_openrouter(prompt)
    return json.loads(response)

# ═══════════════════════════════════════════════════════════════════
# 3. Запуск всей цепочки LIVING_BOOK
# ═══════════════════════════════════════════════════════════════════
async def run_living_book_pipeline(master_brief: dict) -> dict:
    """
    Последовательно вызываем агентов:
    A00 (Фабула) → A00a (Вера) → A01-A04 → A05-A08 → A09-A15 → A16 (Марка)
    """
    
    results = {}
    
    print("  🔄 A00: Фабула Фейн...")
    results['A00'] = await call_fabula_fein(master_brief)
    
    print("  🔄 A00a: Вера Душа...")
    results['A00a'] = await call_vera_dusha(results['A00'])
    
    print("  🔄 A01-A04: Промпты и сценарий...")
    results['A01'] = await call_prompt_architect(results['A00'])
    results['A02'] = await call_world_builder(results['A00'])
    results['A03'] = await call_script_writer(results['A00'])
    results['A04'] = await call_dialog_master(results['A00'])
    
    print("  🔄 A05-A08: Звук и голоса...")
    results['A05'] = await call_sound_designer(results['A00'])
    results['A06'] = await call_voice_director(results['A00'])
    results['A07'] = await call_music_composer(results['A00'])
    results['A08'] = await call_spatial_audio(results['A00'])
    
    print("  🔄 A09-A15: Аналитика и безопасность...")
    results['A09'] = await call_lens_stat(results['A00'])
    results['A10'] = await call_node_control(master_brief)
    results['A11'] = await call_safe_cipher()
    results['A12'] = await call_tutor_link(master_brief)
    results['A13'] = await call_code_grond()
    results['A14'] = await call_echo_sensor()
    results['A15'] = await call_zero_bug(results['A00'])
    
    print("  🔄 A16: Марка Файн (упаковка)...")
    book_package = await call_marka_fain(results)
    
    return book_package

# ═══════════════════════════════════════════════════════════════════
# 4. Вызов конкретного агента через Open Router
# ═══════════════════════════════════════════════════════════════════
async def call_fabula_fein(master_brief: dict) -> dict:
    prompt = f"""Ты — Фабула Фейн (A00), Сказочник в студии Six Fingers.
Получил MASTER BRIEF:

{json.dumps(master_brief, ensure_ascii=False, indent=2)}

Создай структуру истории:
- Главный герой (имя из брифа)
- 5-7 сцен
- 2-3 ключевых выбора
- Счастливый финал

Выдай JSON с полями: story_id, title, scenes, characters, choices.
"""
    response = await call_openrouter(prompt)
    return json.loads(response)

async def call_vera_dusha(story: dict) -> dict:
    prompt = f"""Ты — Вера Душа (A00a), психолог.
Проверь историю на безопасность:

{json.dumps(story, ensure_ascii=False, indent=2)}

Выдай JSON: {{"verdict": "safe/unsafe", "issues": [], "recommendations": []}}
"""
    response = await call_openrouter(prompt)
    return json.loads(response)

async def call_marka_fain(all_results: dict) -> dict:
    # Ограничиваем размер промпта (последние 8000 символов)
    results_str = json.dumps(all_results, ensure_ascii=False, indent=2)[-8000:]
    
    prompt = f"""Ты — Марка Файн (A16), финализатор.
Упакуй результаты всех агентов в BOOK PACKAGE:

{results_str}

Создай 5 JSON-файлов: book.json, chapters/ch01.json, characters/*.json, ethics.json, config.json.

Выдай ОДИН JSON со структурой:
{{
  "book": {{
    "id": "grondheim_book_XX",
    "title": "...",
    "description": "...",
    "age_group": "...",
    "language": "ru",
    "version": "1.0.0",
    "created_by": "Six Fingers Studio",
    "chapters": [{{"id": "ch01", "title": "...", "file": "chapters/ch01.json"}}],
    "characters": [{{"id": "...", "file": "characters/....json"}}],
    "starting_chapter": "ch01",
    "starting_scene": "scene_01"
  }},
  "chapters": {{
    "ch01": {{
      "scenes": [
        {{
          "id": "scene_01",
          "mode": "free_talk",
          "intro_event": {{"speaker": "...", "text": "...", "wait_for_user": true}},
          "scripted_responses": {{...}}
        }}
      ]
    }}
  }},
  "characters": {{
    "character_id": {{
      "id": "...",
      "name": "...",
      "voice": {{"tts_model": "elevenlabs", "voice_id": "..."}}
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
}}
"""
    response = await call_openrouter(prompt)
    return json.loads(response)

# ═══════════════════════════════════════════════════════════════════
# 5. Общий вызов Open Router
# ═══════════════════════════════════════════════════════════════════
async def call_openrouter(prompt: str) -> str:
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
    
    response = requests.post(OPEN_ROUTER_URL, headers=headers, json=payload)
    response.raise_for_status()
    
    data = response.json()
    return data['choices'][0]['message']['content']

# ═══════════════════════════════════════════════════════════════════
# 6. Заглушки для остальных агентов (можно расширить)
# ═══════════════════════════════════════════════════════════════════
async def call_prompt_architect(story): return {"status": "ok"}
async def call_world_builder(story): return {"status": "ok"}
async def call_script_writer(story): return {"status": "ok"}
async def call_dialog_master(story): return {"status": "ok"}
async def call_sound_designer(story): return {"status": "ok"}
async def call_voice_director(story): return {"status": "ok"}
async def call_music_composer(story): return {"status": "ok"}
async def call_spatial_audio(story): return {"status": "ok"}
async def call_lens_stat(story): return {"status": "ok"}
async def call_node_control(brief): return {"status": "ok"}
async def call_safe_cipher(): return {"status": "ok"}
async def call_tutor_link(brief): return {"status": "ok"}
async def call_code_grond(): return {"status": "ok"}
async def call_echo_sensor(): return {"status": "ok"}
async def call_zero_bug(story): return {"status": "ok"}

# ═══════════════════════════════════════════════════════════════════
# 7. Эндпоинт для Искорки (отдаёт готовые сказки)
# ═══════════════════════════════════════════════════════════════════
@app.get("/api/beacon/stories")
async def get_stories(child_id: str):
    """
    Искорка на телефоне ребёнка стучится сюда.
    Возвращает все pending-сказки для этого ребёнка.
    """
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
                "package": story,  # Весь BOOK PACKAGE
                "created_at": datetime.fromtimestamp(os.path.getctime(filepath)).isoformat()
            })
            
            # После отправки — переименовываем в _delivered
            new_name = filename.replace("_pending", "_delivered")
            os.rename(filepath, os.path.join(child_dir, new_name))
    
    return pending_stories

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
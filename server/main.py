# main.py — Маяк Живой Книги
# LIVING_BOOK_APP · 2026
#
# Маяк = КЛИЕНТ студии, НЕ параллельный мозг.
# Генерация книг → через студию (18 агентов, ДНК, память, ревизия).
# Живой диалог Искорки (free_talk) → локальный keyword-матчинг + LLM.
#
# ДУБЛЕЙ НЕТ. Агенты живут в студии.

import json
import os
from datetime import datetime
from functools import lru_cache
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import requests
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════
# КОНФИГ
# ═══════════════════════════════════════════════════════════

OPEN_ROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY")
OPEN_ROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPEN_ROUTER_MODEL = os.getenv("OPEN_ROUTER_MODEL", "google/gemini-2.5-flash")
STORIES_ROOT = os.getenv("STORIES_ROOT", "stories")

# Адрес студии (Студия-2)
STUDIO_URL = os.getenv("STUDIO_URL", "http://localhost:8080")

print(f"🔑 API Key: {OPEN_ROUTER_API_KEY[:20] if OPEN_ROUTER_API_KEY else 'НЕТ'}")
print(f"🤖 Модель (free_talk): {OPEN_ROUTER_MODEL}")
print(f"🏭 Студия: {STUDIO_URL}")
print(f"📁 Истории: {STORIES_ROOT}")

os.makedirs(STORIES_ROOT, exist_ok=True)

app = FastAPI(title="Маяк Живой Книги", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════
# МОДЕЛИ
# ═══════════════════════════════════════════════════════════

class GenerateRequest(BaseModel):
    child_name: str
    child_age: str
    task_context: str
    parent_email: Optional[str] = None
    child_interests: Optional[str] = None
    child_notes: Optional[str] = None


class FreeTalkRequest(BaseModel):
    utterance: str
    scene_context: Optional[str] = None
    child_name: Optional[str] = None
    child_age: Optional[str] = None
    memory_tags: Optional[list] = None


# ═══════════════════════════════════════════════════════════
# 1. ГЕНЕРАЦИЯ КНИГИ — ЧЕРЕЗ СТУДИЮ
# ═══════════════════════════════════════════════════════════

@app.post("/api/studio/generate")
async def generate_story(request: GenerateRequest):
    """Заказ книги через Студию «Шесть Пальцев».
    
    Маяк отправляет данные ребёнка → Студия прогоняет полный
    пайплайн living_book (18 агентов с ДНК, памятью, ревизией Веры)
    → возвращает book_package.
    
    Старый путь (call_set → call_fabula → call_vera → call_marka)
    УДАЛЁН. Всё через студию.
    """
    print(f"\n{'='*60}")
    print(f"📖 Заказ книги: {request.child_name}, {request.child_age}")
    print(f"📝 Задача: {request.task_context}")
    print(f"🏭 Отправляю в студию: {STUDIO_URL}")
    print(f"{'='*60}\n")
    
    try:
        response = requests.post(
            f"{STUDIO_URL}/api/living_book/generate",
            json={
                "child_name": request.child_name,
                "child_age": request.child_age,
                "task_context": request.task_context,
                "parent_email": request.parent_email,
                "child_interests": request.child_interests,
                "child_notes": request.child_notes,
            },
            timeout=600,  # 10 минут — пайплайн может быть долгим
        )
        
        result = response.json()
        
        # Сохраняем book_package локально для Искорки
        if result.get("status") in ("completed", "completed_with_errors"):
            book_package = result.get("book_package")
            if book_package:
                child_dir = os.path.join(STORIES_ROOT, request.child_name)
                os.makedirs(child_dir, exist_ok=True)
                
                filename = f"book_{datetime.now().strftime('%Y%m%d_%H%M%S')}_pending.json"
                filepath = os.path.join(child_dir, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(book_package, f, ensure_ascii=False, indent=2)
                
                print(f"💾 Книга сохранена: {filepath}")
        
        return result
        
    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "child_name": request.child_name,
            "error": f"Студия не запущена ({STUDIO_URL}). Запустите python main.py в папке студии.",
        }
    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "child_name": request.child_name,
            "error": "Таймаут — студия не ответила за 10 минут. Возможно, пайплайн ещё работает.",
        }
    except Exception as e:
        return {
            "status": "error",
            "child_name": request.child_name,
            "error": str(e),
        }


# ═══════════════════════════════════════════════════════════
# 2. ЖИВОЙ ДИАЛОГ ИСКОРКИ (free_talk) — ОСТАЁТСЯ ЛОКАЛЬНЫМ
# ═══════════════════════════════════════════════════════════
# Это НЕ дубль студии. Это реалтайм-диалог ребёнка с персонажем.
# Работает через OpenRouter напрямую — нужна мгновенная реакция.
# Кэш экономит токены до 80%.

@lru_cache(maxsize=1000)
def _cached_llm_call(prompt_hash: str, prompt: str) -> str:
    """Серверный кэш LLM-ответов."""
    headers = {
        "Authorization": f"Bearer {OPEN_ROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPEN_ROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 300,
    }
    response = requests.post(OPEN_ROUTER_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


@app.post("/api/free_talk")
async def free_talk(request: FreeTalkRequest):
    """Живой диалог Искорки с ребёнком.
    
    Прокси-Маяк: локальный keyword-матчинг на клиенте,
    при промахе → сюда → LLM → ответ.
    
    Агенты София (этика) и Нейро Спарк (генерация)
    встроены в system prompt.
    """
    if not OPEN_ROUTER_API_KEY:
        return {
            "reply": "Я немного задумалась... Расскажи мне ещё!",
            "source": "fallback",
        }
    
    # System prompt с встроенными агентами София + Нейро Спарк
    system_prompt = (
        "Ты — Искорка, добрый проводник в мире Грондхейм. "
        "Ты разговариваешь с ребёнком. "
        "ПРАВИЛА (агент София — этика): "
        "- Никогда не давай готовых решений, задавай направляющие вопросы. "
        "- Никогда не пугай, не стыди, не обесценивай. "
        "- Валидируй эмоции: 'Я слышу тебя', 'Это важно'. "
        "- Если ребёнок расстроен — экстернализируй: 'Эта тревога — как тёмное облачко'. "
        "ПРАВИЛА (агент Нейро Спарк — генерация): "
        "- Говори коротко (1-3 предложения). "
        "- Используй Я-сообщения. "
        "- Говори простым языком, понятным ребёнку. "
        "- Всегда заканчивай вопросом или предложением действия."
    )
    
    child_ctx = ""
    if request.child_name:
        child_ctx = f"\nРебёнка зовут {request.child_name}"
    if request.child_age:
        child_ctx += f", возраст {request.child_age}"
    
    scene_ctx = ""
    if request.scene_context:
        scene_ctx = f"\nТекущая сцена: {request.scene_context}"
    
    memory_ctx = ""
    if request.memory_tags:
        memory_ctx = f"\nТеги памяти: {', '.join(request.memory_tags)}"
    
    prompt = f"{system_prompt}{child_ctx}{scene_ctx}{memory_ctx}\n\nРебёнок говорит: {request.utterance}"
    
    try:
        import hashlib
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        reply = _cached_llm_call(prompt_hash, prompt)
        
        return {
            "reply": reply,
            "source": "llm",
            "cached": False,  # lru_cache не сообщает, но экономит
        }
    except Exception as e:
        print(f"[FREE_TALK] Ошибка LLM: {e}")
        return {
            "reply": "Хм, я немного задумалась... Продолжай, я слушаю!",
            "source": "fallback",
            "error": str(e),
        }


# ═══════════════════════════════════════════════════════════
# 3. ИСКОРКА ЗАБИРАЕТ СКАЗКИ
# ═══════════════════════════════════════════════════════════

@app.get("/api/beacon/stories")
async def get_stories(child_id: str):
    """Искорка забирает готовые книги.
    
    Вызывается клиентом (PWA) при подключении к сети.
    Возвращает pending книги и помечает их как delivered.
    """
    child_dir = os.path.join(STORIES_ROOT, child_id)
    
    if not os.path.exists(child_dir):
        return []
    
    pending_stories = []
    
    for filename in os.listdir(child_dir):
        if filename.endswith("_pending.json"):
            filepath = os.path.join(child_dir, filename)
            
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    story = json.load(f)
            except Exception:
                continue
            
            pending_stories.append({
                "story_id": filename.replace("_pending.json", ""),
                "title": story.get("book", {}).get("title", "Новая история"),
                "package": story,
                "created_at": datetime.fromtimestamp(
                    os.path.getctime(filepath)
                ).isoformat(),
            })
            
            # Помечаем как доставленную
            new_name = filename.replace("_pending", "_delivered")
            os.rename(filepath, os.path.join(child_dir, new_name))
    
    return pending_stories


# ═══════════════════════════════════════════════════════════
# 4. РОДИТЕЛЬСКИЙ КАБИНЕТ
# ═══════════════════════════════════════════════════════════

@app.get("/parent/feed")
async def parent_feed(limit: int = 15):
    """Лента событий для родителя."""
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
                            "status": status,
                        })
                    except Exception:
                        pass
    events.sort(key=lambda x: x["ts"], reverse=True)
    return {"events": events[:limit]}


@app.get("/parent/stats")
async def parent_stats():
    """Статистика для родителя."""
    return {
        "total_sessions": 0,
        "total_choices": 0,
        "total_chats": 0,
        "artifacts": [],
        "choices_history": [],
        "memory_tags": [],
    }


# ═══════════════════════════════════════════════════════════
# 5. HEALTH CHECK
# ═══════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    """Проверка здоровья Маяка и связи со студией."""
    studio_ok = False
    try:
        r = requests.get(f"{STUDIO_URL}/api/living_book/status", timeout=5)
        if r.status_code == 200:
            studio_ok = True
            studio_info = r.json()
        else:
            studio_info = {"error": f"status {r.status_code}"}
    except Exception as e:
        studio_info = {"error": str(e)}
    
    return {
        "beacon": "ok",
        "studio_connected": studio_ok,
        "studio_url": STUDIO_URL,
        "studio_info": studio_info,
        "llm_configured": bool(OPEN_ROUTER_API_KEY),
    }


# ═══════════════════════════════════════════════════════════
# 6. ЗАПУСК
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print("\n🔦 Маяк Живой Книги запущен")
    print(f"   Маяк:    http://localhost:8001")
    print(f"   Студия:  {STUDIO_URL}")
    print(f"   Health:  http://localhost:8001/api/health")
    print()
    uvicorn.run(app, host="0.0.0.0", port=8001)

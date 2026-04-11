"""
beacon.py v6.2 — Сетевая интеграция со Студией (Маяк → Сет)
===================================================================================
v6.2:
  - Новая переменная окружения SETH_WORKER_URL
  - POST /api/parent/uid/{uid}/generate_chapter — сборка брифа и отправка Сету
  - POST /api/internal/deliver_chapter — callback от Сета для сохранения готовой главы
  - Обновление БД: статус PENDING_SETH → реальный путь

v6.1:
  - Рефакторинг GET /api/worlds → читает из system_registry/worlds_registry.json
  - Новая структура registry.json: parents + profiles
  - POST /api/parent/register — регистрация родителя
  - POST /api/parent/{parent_id}/child — регистрация ребёнка
  - GET /api/showcase — список готовых историй из system_registry/showcase/
  - POST /api/parent/{parent_id}/uid/{uid}/onboarding/start — копирование эталонной истории
  - Блокировка POST /api/parent/uid/{uid}/basket до прохождения первой истории
"""

import json
import re
import hashlib
import sqlite3
import os
import httpx
import shutil
from datetime import datetime
from pathlib import Path
from functools import lru_cache
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Живая Книга — Сервер v6.2 (Сетевая Студия)", version="6.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── ПУТИ ────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent
BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"
BOOKS_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_REGISTRY_DIR = Path(__file__).resolve().parent.parent / "system_registry"
SYSTEM_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

PERSONAL_DIR  = BOOKS_DIR / "personal"
REGISTRY_PATH = BOOKS_DIR / "registry.json"
BEACON_DB     = BASE_DIR / "beacon.db"

print(f"📁 BOOKS_DIR = {BOOKS_DIR}")
print(f"📁 SYSTEM_REGISTRY_DIR = {SYSTEM_REGISTRY_DIR}")

# ─── СЕТЕВАЯ ИНТЕГРАЦИЯ СО СТУДИЕЙ ───────────────────────────────────────────
SETH_WORKER_URL = os.getenv("SETH_WORKER_URL", "http://127.0.0.1:8002/api/seth/task")
print(f"🌐 SETH_WORKER_URL = {SETH_WORKER_URL}")

# ─── OPENROUTER (ОСТАЁТСЯ ДЛЯ FREE_TALK И ДРУГИХ МЕЛКИХ ЗАДАЧ) ────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")

# ─── ПРОМПТЫ АГЕНТОВ ─────────────────────────────────────────────────────────
STUDIO_ROOT  = Path(os.getenv("STUDIO_ROOT", str(BASE_DIR / ".." / ".." / "-2")))
MODULES_PATH = STUDIO_ROOT / "studio" / "modules" / "living_book"


# ═══════════════════════════════════════════════════════════════════════════════
# ВОЗРАСТНАЯ ДНК (без изменений)
# ═══════════════════════════════════════════════════════════════════════════════

AGE_PARADIGMS = {
    "2-4": {
        "name": "Дирижёр звука",
        "system_addon": """ВОЗРАСТНАЯ ПАРАДИГМА: 2-4 года (Принцип Тёмной Комнаты)
- Говори ОЧЕНЬ коротко: 1 предложение максимум.
- Используй простые слова, как для малыша.
- Добавляй звуковые теги в квадратных скобках: [magic_chime], [water_splash], [soft_bell].
- Звуки ВАЖНЕЕ слов. Каждый ответ должен содержать хотя бы один звуковой тег.
- Тон: нежный, напевный, как колыбельная."""
    },
    "3-6": {
        "name": "Нежный проводник",
        "system_addon": """ВОЗРАСТНАЯ ПАРАДИГМА: 3-6 лет
- Говори коротко: максимум 2 предложения.
- Простые слова, тёплый тон.
- Можно добавлять звуковые теги: [magic_chime], [bird_song].
- Метод Гиппенрейтер: отрази чувство, предложи простое действие."""
    },
    "5-9": {
        "name": "Оранжевый страх и два вдоха",
        "system_addon": """ВОЗРАСТНАЯ ПАРАДИГМА: 5-9 лет (Матрица Эмпатии)
- Максимум 2 предложения.
- Строгий метод Гиппенрейтер: отрази чувство ребёнка, задай направляющий вопрос.
- ЗАПРЕЩЕНО давать готовые решения типа «не бойся, монстров нет».
- Если ребёнок боится — признай легитимность страха, предложи алгоритм «двух вдохов»."""
    },
    "7-12": {
        "name": "Свет ярче тени",
        "system_addon": """ВОЗРАСТНАЯ ПАРАДИГМА: 7-12 лет (Свет ярче тени)
- Максимум 2-3 предложения.
- Метод Гиппенрейтер + правило «Честность выше комфорта».
- НЕ сглаживай углы. Если ребёнок говорит о сложном — будь честен.
- Разрешён глубокий философский разговор: обсуждай внутренние тени."""
    },
    "13+": {
        "name": "Честный собеседник",
        "system_addon": """ВОЗРАСТНАЯ ПАРАДИГМА: 13+ лет
- Говори как с равным. Без сюсюканья.
- Честность выше комфорта. Не избегай сложных тем.
- Ты — не учитель, а собеседник.
- Задавай глубокие вопросы."""
    },
}

def get_age_paradigm(child_name: str, uid: Optional[str] = None) -> str:
    """Определяет возрастную парадигму для ребёнка."""
    age_group = "7-12"
    
    folder = None
    if uid:
        folder = resolve_uid(uid)
    if not folder:
        folder = _find_child_folder(child_name)

    if folder:
        profile_path = folder / "child_profile.json"
        if profile_path.exists():
            try:
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
                ag = profile.get("age_group")
                if ag:
                    age_group = ag
            except Exception as e:
                print(f"[AGE DNA] Error: {e}")

    if uid and age_group == "7-12":
        profile = get_profile_by_uid(uid)
        if profile and profile.get("age_group"):
            age_group = profile["age_group"]

    paradigm = AGE_PARADIGMS.get(age_group)
    if not paradigm:
        for key in AGE_PARADIGMS:
            if age_group in key or key in age_group:
                paradigm = AGE_PARADIGMS[key]
                break
    if not paradigm:
        paradigm = AGE_PARADIGMS["7-12"]

    return paradigm["system_addon"]


# ═══════════════════════════════════════════════════════════════════════════════
# РЕЕСТР СУДЕБ (REGISTRY) — обновлённая структура
# ═══════════════════════════════════════════════════════════════════════════════

def load_registry() -> dict:
    """Загружает реестр с новой структурой: parents + profiles"""
    if REGISTRY_PATH.exists():
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if "parents" not in data:
            data["parents"] = []
        if "profiles" not in data:
            data["profiles"] = []
        return data
    empty = {
        "version": "2.0",
        "updated_at": datetime.now().isoformat(),
        "parents": [],
        "profiles": []
    }
    save_registry(empty)
    return empty

def save_registry(registry: dict):
    registry["updated_at"] = datetime.now().isoformat()
    registry["version"] = "2.0"
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

def generate_parent_id() -> str:
    import random
    import string
    while True:
        pid = "P-" + ''.join(random.choices(string.digits, k=6))
        registry = load_registry()
        if not any(p.get("parent_id") == pid for p in registry.get("parents", [])):
            return pid

def generate_uid(parent_id: str = None) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    registry = load_registry()
    today_count = sum(1 for p in registry.get("profiles", []) if p["uid"].startswith(f"LB-{today}"))
    uid = f"LB-{today}-{today_count + 1:04d}"
    return uid

def resolve_uid(uid: str) -> Optional[Path]:
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            folder = PERSONAL_DIR / profile["folder"]
            if folder.exists():
                return folder
    return None

def get_profile_by_uid(uid: str) -> Optional[dict]:
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            return profile
    return None

def get_parent_by_id(parent_id: str) -> Optional[dict]:
    registry = load_registry()
    for parent in registry.get("parents", []):
        if parent["parent_id"] == parent_id:
            return parent
    return None

def validate_child_belongs_to_parent(parent_id: str, uid: str) -> bool:
    registry = load_registry()
    parent = get_parent_by_id(parent_id)
    if not parent:
        return False
    if uid in parent.get("children", []):
        return True
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid and profile.get("parent_id") == parent_id:
            return True
    return False

def _find_child_folder(name: str) -> Optional[Path]:
    if not PERSONAL_DIR.exists():
        return None
    for d in PERSONAL_DIR.iterdir():
        if d.is_dir() and d.name.lower() == name.lower():
            return d
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# BIOGRAPHY + ARTIFACTS + BRIDGES (утилиты)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_bio(folder: Path, uid: str, alias: str = "Ребёнок") -> dict:
    bio_path = folder / "biography.json"
    if bio_path.exists():
        bio = json.loads(bio_path.read_text(encoding="utf-8"))
    else:
        bio = {
            "uid": uid, "child_name": alias, "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "artifacts": [], "completed_stories": [], "unlocked_worlds": ["whispering_caves"],
            "relationships": {}, "pending_bridges": [], "completed_bridges": [],
            "karma": {"current": 0, "history": []}, "karmic_trail": [], "emotional_trail": []
        }
    bio.setdefault("artifacts", [])
    bio.setdefault("pending_bridges", [])
    bio.setdefault("completed_bridges", [])
    bio.setdefault("karma", {"current": 0, "history": []})
    return bio

def _save_bio(folder: Path, bio: dict):
    bio["updated_at"] = datetime.now().isoformat()
    (folder / "biography.json").write_text(json.dumps(bio, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# ЗАДАЧА 1: НАСТРОЙКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (уже сделана выше — SETH_WORKER_URL)
# ═══════════════════════════════════════════════════════════════════════════════

# ЗАДАЧА 2: ЭНДПОИНТ ГЕНЕРАЦИИ (СБОРКА И ОТПРАВКА БРИФА)
# ═══════════════════════════════════════════════════════════════════════════════

class GenerateChapterRequest(BaseModel):
    character_id: str  # например, "eirik"
    world_id: str      # например, "whispering_caves"

@app.post("/api/parent/uid/{uid}/generate_chapter")
async def generate_chapter(uid: str, req: GenerateChapterRequest, background_tasks: BackgroundTasks):
    """
    v6.2: Сборка брифа и отправка Сету (асинхронно, без ожидания генерации)
    """
    # 1. Проверяем существование папки ребёнка
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")
    
    # 2. Паспорт ребёнка
    profile = get_profile_by_uid(uid)
    if not profile:
        raise HTTPException(404, f"Профиль для {uid} не найден")
    
    child_name = profile.get("alias", "Ребёнок")
    age_group = profile.get("age_group", "7-12")
    
    # 3. Корзинка Даров (basket.json)
    basket_path = folder / "basket.json"
    if not basket_path.exists():
        raise HTTPException(404, "Корзинка даров (basket.json) не найдена. Сначала создайте задачу через /api/parent/uid/{uid}/basket")
    
    basket_data = json.loads(basket_path.read_text(encoding="utf-8"))
    active_baskets = basket_data.get("active_baskets", [])
    if not active_baskets:
        raise HTTPException(400, "Нет активных корзин. Сначала создайте задачу.")
    
    # Берём первую активную корзину
    current_basket = active_baskets[0]
    
    # 4. Историческая память (biography.json)
    bio = _load_bio(folder, uid, child_name)
    completed_stories = bio.get("completed_stories", [])
    artifacts = bio.get("artifacts", [])
    karma = bio.get("karma", {}).get("current", 0)
    
    # 5. Слот 1: Герой из characters_registry.json
    characters_registry_path = SYSTEM_REGISTRY_DIR / "characters_registry.json"
    if not characters_registry_path.exists():
        raise HTTPException(404, "characters_registry.json не найден в system_registry/")
    
    characters_data = json.loads(characters_registry_path.read_text(encoding="utf-8"))
    character = None
    for char in characters_data.get("characters", []):
        if char.get("id") == req.character_id:
            character = char
            break
    
    if not character:
        raise HTTPException(404, f"Герой с id '{req.character_id}' не найден")
    
    # 6. Слот 2: Мир из worlds_registry.json
    worlds_registry_path = SYSTEM_REGISTRY_DIR / "worlds_registry.json"
    if not worlds_registry_path.exists():
        raise HTTPException(404, "worlds_registry.json не найден в system_registry/")
    
    worlds_data = json.loads(worlds_registry_path.read_text(encoding="utf-8"))
    world = None
    for w in worlds_data.get("worlds", []):
        if w.get("id") == req.world_id:
            world = w
            break
    
    if not world:
        raise HTTPException(404, f"Мир с id '{req.world_id}' не найден")
    
    # 7. Возрастная ДНК
    age_paradigm_text = get_age_paradigm(child_name, uid)
    
    # 8. Сборка полного брифа
    brief = {
        "uid": uid,
        "child_name": child_name,
        "age_group": age_group,
        "age_paradigm": age_paradigm_text,
        "basket": {
            "id": current_basket.get("id"),
            "title": current_basket.get("title"),
            "description": current_basket.get("description"),
            "parent_goal": current_basket.get("parent_goal"),
            "child_problem_statement": current_basket.get("child_problem_statement"),
            "theme": current_basket.get("theme"),
            "emotional_context": current_basket.get("emotional_context", {})
        },
        "character": character,
        "world": world,
        "memory": {
            "completed_stories": completed_stories,
            "artifacts": artifacts,
            "current_karma": karma
        },
        "timestamp": datetime.now().isoformat()
    }
    
    # 9. Отправка Сету (асинхронно, в фоне, чтобы не блокировать ответ)
    async def send_to_seth():
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    SETH_WORKER_URL,
                    json=brief,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                print(f"[SETH] ✅ Задача для {uid} отправлена успешно")
                
                # 10. Обновляем БД: создаём запись со статусом PENDING_SETH
                with sqlite3.connect(BEACON_DB) as conn:
                    conn.execute(
                        "INSERT INTO generated_scenes (child_name, child_age, task_context, set_brief, generated_at, file_path) VALUES (?, ?, ?, ?, ?, ?)",
                        (child_name, age_group, f"generate_chapter_{req.character_id}_{req.world_id}", json.dumps(brief), datetime.now().isoformat(), "PENDING_SETH")
                    )
                    conn.commit()
                    
        except httpx.TimeoutException:
            print(f"[SETH] ❌ Таймаут при отправке задачи для {uid}")
        except Exception as e:
            print(f"[SETH] ❌ Ошибка при отправке задачи для {uid}: {e}")
    
    # Запускаем отправку в фоне
    background_tasks.add_task(send_to_seth)
    
    return {
        "status": "processing",
        "message": "Задача передана в Студию (Сет). Глава будет доставлена через callback.",
        "brief_preview": {
            "uid": uid,
            "child_name": child_name,
            "character": character.get("name"),
            "world": world.get("name"),
            "basket_title": current_basket.get("title")
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ЗАДАЧА 3: ВНУТРЕННИЙ ЭНДПОИНТ ДОСТАВКИ (Callback от Сета)
# ═══════════════════════════════════════════════════════════════════════════════

class DeliverChapterRequest(BaseModel):
    uid: str
    chapter_data: Dict[str, Any]  # Полный, готовый JSON-объект главы (scene.json)

@app.post("/api/internal/deliver_chapter")
async def deliver_chapter(req: DeliverChapterRequest):
    """
    v6.2: Callback от Сета — сохранение готовой главы в папку ребёнка
    """
    # 1. Находим папку ребёнка
    folder = resolve_uid(req.uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {req.uid} не найден")
    
    chapters_folder = folder / "chapters"
    chapters_folder.mkdir(exist_ok=True)
    
    # 2. Определяем следующий номер главы
    existing_chapters = list(chapters_folder.glob("chapter_*.json"))
    max_index = 0
    for ch in existing_chapters:
        try:
            # Извлекаем число из "chapter_X.json"
            idx = int(ch.stem.split("_")[1])
            if idx > max_index:
                max_index = idx
        except (IndexError, ValueError):
            pass
    
    next_index = max_index + 1
    chapter_filename = f"chapter_{next_index}.json"
    chapter_path = chapters_folder / chapter_filename
    
    # 3. Сохраняем главу
    # Добавляем метаданные о времени сохранения, если их нет
    if "saved_at" not in req.chapter_data:
        req.chapter_data["saved_at"] = datetime.now().isoformat()
    if "chapter_index" not in req.chapter_data:
        req.chapter_data["chapter_index"] = next_index
    
    chapter_path.write_text(json.dumps(req.chapter_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # 4. Обновляем запись в БД (находим последнюю PENDING_SETH для этого ребёнка)
    with sqlite3.connect(BEACON_DB) as conn:
        # Находим самую свежую запись со статусом PENDING_SETH для этого ребёнка
        cursor = conn.execute(
            "SELECT id FROM generated_scenes WHERE file_path = 'PENDING_SETH' AND child_name = (SELECT alias FROM profiles WHERE uid = ?) ORDER BY generated_at DESC LIMIT 1",
            (req.uid,)
        )
        row = cursor.fetchone()
        
        if row:
            # Обновляем статус на реальный путь
            conn.execute(
                "UPDATE generated_scenes SET file_path = ? WHERE id = ?",
                (str(chapter_path), row[0])
            )
            conn.commit()
            print(f"[CALLBACK] ✅ Обновлена запись в БД: {chapter_path}")
        else:
            # Если не нашли PENDING_SETH, просто создаём новую запись
            profile = get_profile_by_uid(req.uid)
            child_name = profile.get("alias", "Unknown") if profile else "Unknown"
            age_group = profile.get("age_group", "7-12") if profile else "7-12"
            conn.execute(
                "INSERT INTO generated_scenes (child_name, child_age, task_context, set_brief, generated_at, file_path) VALUES (?, ?, ?, ?, ?, ?)",
                (child_name, age_group, "callback_delivery", json.dumps(req.chapter_data), datetime.now().isoformat(), str(chapter_path))
            )
            conn.commit()
            print(f"[CALLBACK] ✅ Создана новая запись в БД: {chapter_path}")
    
    # 5. (Опционально) Обновляем biography.json — добавляем информацию о новой главе
    bio = _load_bio(folder, req.uid, profile.get("alias", "Ребёнок") if profile else "Ребёнок")
    bio.setdefault("chapters_received", []).append({
        "chapter_index": next_index,
        "chapter_id": req.chapter_data.get("scene_id", chapter_filename),
        "received_at": datetime.now().isoformat()
    })
    _save_bio(folder, bio)
    
    print(f"[CALLBACK] ✅ Глава {chapter_filename} сохранена для {req.uid}")
    
    return {
        "ok": True,
        "uid": req.uid,
        "chapter_path": str(chapter_path),
        "chapter_index": next_index
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ОСТАЛЬНЫЕ ЭНДПОИНТЫ (без изменений, но нужны для полноты)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/worlds")
async def get_worlds():
    """v6.1: Реестр миров из system_registry/worlds_registry.json"""
    worlds_path = SYSTEM_REGISTRY_DIR / "worlds_registry.json"
    if worlds_path.exists():
        return json.loads(worlds_path.read_text(encoding="utf-8"))
    raise HTTPException(404, "worlds_registry.json не найден в system_registry/")

@app.get("/api/beacon/uid/{uid}/bio")
async def get_biography_v4(uid: str):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Папка для {uid} не найдена")
    profile = get_profile_by_uid(uid)
    alias = profile.get("alias", "Ребёнок") if profile else "Ребёнок"
    bio = _load_bio(folder, uid, alias)
    return bio

@app.post("/api/beacon/uid/{uid}/artifact")
async def add_artifact(uid: str, artifact: dict):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")
    profile = get_profile_by_uid(uid)
    alias = profile.get("alias", "Ребёнок") if profile else "Ребёнок"
    bio = _load_bio(folder, uid, alias)
    artifacts = bio.get("artifacts", [])
    if not any(a.get("id") == artifact.get("id") for a in artifacts):
        artifact["obtained_at"] = datetime.now().isoformat()
        artifact["permanent"] = True
        artifacts.append(artifact)
        bio["artifacts"] = artifacts
        _save_bio(folder, bio)
        print(f"[ARTIFACT] ✅ {uid} got: {artifact.get('name')}")
        return {"ok": True, "artifact": artifact}
    return {"ok": False, "message": "Артефакт уже есть"}

@app.get("/api/parent/uid/{uid}/artifacts")
async def get_artifacts(uid: str):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")
    profile = get_profile_by_uid(uid)
    alias = profile.get("alias", "Ребёнок") if profile else "Ребёнок"
    bio = _load_bio(folder, uid, alias)
    return {"artifacts": bio.get("artifacts", [])}

@app.get("/api/parent/uid/{uid}/pending_bridges")
async def get_pending_bridges(uid: str):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404)
    profile = get_profile_by_uid(uid)
    alias = profile.get("alias", "Ребёнок") if profile else "Ребёнок"
    bio = _load_bio(folder, uid, alias)
    return {"pending_bridges": bio.get("pending_bridges", [])}

class BridgeCompleteRequest(BaseModel):
    task: str
    completed_at: Optional[str] = None

@app.post("/api/parent/uid/{uid}/bridge/complete")
async def complete_bridge(uid: str, req: BridgeCompleteRequest):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")
    profile = get_profile_by_uid(uid)
    alias = profile.get("alias", "Ребёнок") if profile else "Ребёнок"
    bio = _load_bio(folder, uid, alias)
    pending = bio.get("pending_bridges", [])
    found_idx = None
    found = None
    for i, b in enumerate(pending):
        if b.get("task") == req.task:
            found_idx = i
            found = pending.pop(i)
            break
    if not found:
        raise HTTPException(404, f"Мостик с задачей '{req.task[:50]}...' не найден")
    found["completed_at"] = req.completed_at or datetime.now().isoformat()
    found["status"] = "completed"
    bio.setdefault("completed_bridges", []).append(found)
    karma_reward = found.get("karma_reward_on_success", 2)
    bio["karma"]["current"] += karma_reward
    bio["karma"]["history"].append({
        "ts": datetime.now().isoformat(),
        "delta": karma_reward,
        "reason": f"bridge_completed"
    })
    _save_bio(folder, bio)
    print(f"[BRIDGE] ✅ {uid} completed: {found.get('task', '')[:60]}... +{karma_reward} karma")
    return {
        "ok": True,
        "success_scene": found.get("success_scene"),
        "karma_reward": karma_reward,
        "current_karma": bio["karma"]["current"]
    }

# (basket эндпоинт с блокировкой из v6.1)
class CreateBasketRequest(BaseModel):
    title: str
    description: str
    parent_goal: str
    child_problem_statement: str
    theme: str = "дружба"
    emotional_context: Optional[dict] = None

@app.post("/api/parent/uid/{uid}/basket")
async def create_basket(uid: str, req: CreateBasketRequest):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")
    
    # Валидация: проверяем completed_stories
    bio_path = folder / "biography.json"
    if not bio_path.exists():
        raise HTTPException(404, "biography.json не найден")
    bio = json.loads(bio_path.read_text(encoding="utf-8"))
    completed_stories = bio.get("completed_stories", [])
    if len(completed_stories) == 0:
        raise HTTPException(
            status_code=403,
            detail="Сначала пройдите историю знакомства (онбординг)"
        )
    
    basket_path = folder / "basket.json"
    if basket_path.exists():
        basket = json.loads(basket_path.read_text(encoding="utf-8"))
    else:
        basket = {
            "uid": uid,
            "version": "4.0",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "active_baskets": [],
            "completed_baskets": []
        }
    basket_id = f"basket_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    bridge_task = f"Расскажи {['маме', 'папе', 'бабушке', 'дедушке'][hash(basket_id) % 4]}, что тебя сегодня беспокоит, и обними их"
    new_basket = {
        "id": basket_id,
        "title": req.title,
        "description": req.description,
        "parent_goal": req.parent_goal,
        "child_problem_statement": req.child_problem_statement,
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "theme": req.theme,
        "emotional_context": req.emotional_context or {},
        "bridge_to_reality": {
            "real_world_action": bridge_task,
            "reward": "Наклейка в Календарь Доблести + 2 кармы",
            "completed": False,
            "accessibility": {"requires_vision": False}
        }
    }
    basket["active_baskets"].append(new_basket)
    basket["updated_at"] = datetime.now().isoformat()
    basket_path.write_text(json.dumps(basket, ensure_ascii=False, indent=2), encoding="utf-8")
    
    profile = get_profile_by_uid(uid)
    alias = profile.get("alias", "Ребёнок") if profile else "Ребёнок"
    bio = _load_bio(folder, uid, alias)
    bio.setdefault("pending_bridges", []).append({
        "task": bridge_task,
        "created_at": datetime.now().isoformat(),
        "deadline_hours": 48,
        "status": "pending",
        "basket_id": basket_id,
        "karma_reward_on_success": 2,
        "accessibility": {"requires_vision": False},
        "success_scene": None
    })
    _save_bio(folder, bio)
    print(f"[BASKET] ✅ {uid} created: {basket_id}")
    return {
        "ok": True,
        "basket_id": basket_id,
        "status": "pending",
        "bridge_to_reality": new_basket["bridge_to_reality"]
    }

@app.get("/api/showcase")
async def get_showcase():
    showcase_dir = SYSTEM_REGISTRY_DIR / "showcase"
    if not showcase_dir.exists():
        raise HTTPException(404, "Папка showcase не найдена в system_registry/")
    stories = []
    for json_file in showcase_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            stories.append({
                "story_id": json_file.stem,
                "title": data.get("title", json_file.stem),
                "description": data.get("description", ""),
                "character_id": data.get("character_id", ""),
                "world_id": data.get("world_id", ""),
                "thumbnail": data.get("thumbnail", ""),
                "duration_minutes": data.get("duration_minutes", 10)
            })
        except Exception as e:
            print(f"[SHOWCASE] Ошибка чтения {json_file.name}: {e}")
    return {"stories": stories, "count": len(stories)}

class OnboardingStartRequest(BaseModel):
    story_id: str

@app.post("/api/parent/{parent_id}/uid/{uid}/onboarding/start")
async def start_onboarding_story(parent_id: str, uid: str, req: OnboardingStartRequest):
    if not validate_child_belongs_to_parent(parent_id, uid):
        raise HTTPException(403, f"Ребёнок {uid} не принадлежит родителю {parent_id}")
    child_folder = resolve_uid(uid)
    if not child_folder:
        raise HTTPException(404, f"Папка ребёнка {uid} не найдена")
    chapters_folder = child_folder / "chapters"
    chapters_folder.mkdir(exist_ok=True)
    source_file = SYSTEM_REGISTRY_DIR / "showcase" / f"{req.story_id}.json"
    if not source_file.exists():
        raise HTTPException(404, f"История {req.story_id} не найдена в showcase/")
    dest_file = chapters_folder / "chapter_1.json"
    shutil.copy2(source_file, dest_file)
    print(f"[ONBOARDING] ✅ История {req.story_id} скопирована для {uid}")
    return {"ok": True, "story_id": req.story_id, "chapter_path": "chapters/chapter_1.json"}

@app.post("/api/parent/register")
async def register_parent(req: dict):
    parent_id = generate_parent_id()
    registry = load_registry()
    new_parent = {
        "parent_id": parent_id,
        "name": req.get("name", "Родитель"),
        "email": req.get("email"),
        "created_at": datetime.now().isoformat(),
        "children": []
    }
    registry["parents"].append(new_parent)
    save_registry(registry)
    return {"ok": True, "parent_id": parent_id}

@app.post("/api/parent/{parent_id}/child")
async def register_child(parent_id: str, req: dict):
    parent = get_parent_by_id(parent_id)
    if not parent:
        raise HTTPException(404, f"Родитель с ID {parent_id} не найден")
    uid = generate_uid(parent_id)
    child_name = req.get("child_name", "Ребёнок")
    age_group = req.get("age_group", "7-12")
    child_folder = PERSONAL_DIR / uid
    child_folder.mkdir(parents=True, exist_ok=True)
    chapters_folder = child_folder / "chapters"
    chapters_folder.mkdir(exist_ok=True)
    child_profile = {
        "uid": uid,
        "child_name": child_name,
        "age_group": age_group,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    (child_folder / "child_profile.json").write_text(json.dumps(child_profile, ensure_ascii=False, indent=2), encoding="utf-8")
    bio = {
        "uid": uid,
        "child_name": child_name,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "artifacts": [],
        "completed_stories": [],
        "unlocked_worlds": [],
        "relationships": {},
        "pending_bridges": [],
        "completed_bridges": [],
        "karma": {"current": 0, "history": []}
    }
    (child_folder / "biography.json").write_text(json.dumps(bio, ensure_ascii=False, indent=2), encoding="utf-8")
    registry = load_registry()
    registry["profiles"].append({
        "uid": uid,
        "alias": child_name,
        "folder": uid,
        "parent_id": parent_id,
        "age_group": age_group,
        "created_at": datetime.now().isoformat(),
        "last_activity": datetime.now().isoformat(),
        "status": "active"
    })
    for p in registry["parents"]:
        if p["parent_id"] == parent_id:
            p["children"].append(uid)
            break
    save_registry(registry)
    return {"ok": True, "uid": uid, "child_name": child_name, "parent_id": parent_id}

@app.get("/stats")
def stats():
    with sqlite3.connect(BEACON_DB) as conn:
        devices = conn.execute("SELECT COUNT(DISTINCT device_id) FROM sync_log").fetchone()[0]
        syncs = conn.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0]
        generated = conn.execute("SELECT COUNT(*) FROM generated_scenes").fetchone()[0]
        top_tags = conn.execute("SELECT tag, COUNT(*) as c FROM aggregate_tags GROUP BY tag ORDER BY c DESC LIMIT 10").fetchall()
    registry = load_registry()
    return {"total_devices": devices, "total_syncs": syncs, "total_generated_books": generated,
            "total_profiles": len(registry.get("profiles", [])),
            "top_tags": [{"tag": r[0], "count": r[1]} for r in top_tags]}

@app.get("/health")
def health():
    agents = 0
    if MODULES_PATH.exists():
        agents = sum(1 for d in MODULES_PATH.iterdir() if d.is_dir() and d.name.startswith("A"))
    registry = load_registry()
    return {"status": "ok", "version": "6.2.0", "protocol": "v4.0", "model": OPENROUTER_MODEL,
            "api_key_set": bool(OPENROUTER_API_KEY), "agents_available": agents,
            "books_dir": str(BOOKS_DIR), "registry_profiles": len(registry.get("profiles", [])),
            "seth_worker_url": SETH_WORKER_URL}

# ─── FREE_TALK (оставляем, но он теперь не основной генератор) ───────────────
class FreeTalkRequest(BaseModel):
    child_text: str
    scene_id: str
    chapter_id: str = ""
    child_name: str = "Ребёнок"
    uid: Optional[str] = None
    session_id: str = ""

SAFETY_KEYWORDS = ["помогите", "спасите", "умереть", "убить", "кровь", "наркотик", "секс", "порно"]

async def call_openrouter(system_prompt: str, user_prompt: str, max_tokens: int = 4000, temperature: float = 0.7) -> str:
    if not OPENROUTER_API_KEY:
        return "Извини, я сейчас не могу ответить. Давай просто побудем вместе?"
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(OPENROUTER_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json",
                     "HTTP-Referer": "https://grondheim.local", "X-Title": "Living Book Grondheim"},
            json={"model": OPENROUTER_MODEL, "max_tokens": max_tokens, "temperature": temperature,
                  "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

@app.post("/api/free_talk")
async def free_talk(req: FreeTalkRequest):
    text_lower = req.child_text.lower()
    if any(kw in text_lower for kw in SAFETY_KEYWORDS):
        return {"text": "Давай поговорим о чём-то другом, хорошо?", "color": "yellow", "blocked": True}
    aggression_analysis = {"source": "none", "emotion": "neutral"}
    characters = ["эйрик", "лока", "петя", "петей", "искорка"]
    for char in characters:
        if char in text_lower and any(word in text_lower for word in ["дурак", "тупой", "идиот", "дебил"]):
            aggression_analysis["source"] = "character"
            break
    self_aggression_words = ["я дурак", "я тупой", "я ничтожество", "у меня не получится", "я плохой"]
    if any(word in text_lower for word in self_aggression_words):
        aggression_analysis["source"] = "self"
    external_threat_words = ["меня бьют", "меня обижают", "мне страшно от", "он меня ударил"]
    if any(word in text_lower for word in external_threat_words):
        aggression_analysis["source"] = "external"
    age_addon = get_age_paradigm(req.child_name, req.uid)
    system_prompt = f"""Ты — Искорка, тёплый спутник ребёнка в мире Грондхейм.
Отвечай ТОЛЬКО текст для ребёнка, без JSON, без скобок, без технических пометок.
{age_addon}"""
    if aggression_analysis["source"] == "character":
        system_prompt = f"""⚠️ Ребёнок оскорбил персонажа. Признай его гнев, скажи прямо: «Я слышу, что ты рассердился. Что случилось?»
{system_prompt}"""
    elif aggression_analysis["source"] == "self":
        system_prompt = f"""⚠️ Ребёнок проявляет селф-агрессию. НЕ поддерживай это. Скажи: «Я вижу тебя иначе. Расскажи, что случилось?»
{system_prompt}"""
    user_prompt = f"""Ребёнок {req.child_name} в сцене {req.scene_id} сказал: «{req.child_text}»
Ответь согласно инструкциям. Будь тёплым, но честным."""
    ai_text = "Я тебя слышу... Расскажи ещё раз?"
    try:
        ai_text = await call_openrouter(system_prompt, user_prompt, max_tokens=150, temperature=0.8)
    except Exception as e:
        print(f"[FREE_TALK] LLM error: {e}")
    return {
        "text": ai_text,
        "color": "cyan",
        "cached": False,
        "detected_emotion": aggression_analysis["emotion"],
        "conflict_detected": aggression_analysis["source"] != "none",
        "source_of_aggression": aggression_analysis["source"]
    }

# ─── РАЗДАЧА СТАТИКИ ──────────────────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles

PLAYER_DIR    = BASE_DIR.parent / "player"
DASHBOARD_DIR = BASE_DIR.parent / "dashboard"

if PLAYER_DIR.exists():
    app.mount("/player", StaticFiles(directory=str(PLAYER_DIR), html=True), name="player")
if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")

# ─── ИНИЦИАЛИЗАЦИЯ БД ─────────────────────────────────────────────────────────
def init_db():
    with sqlite3.connect(BEACON_DB) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sync_log (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL, session_id TEXT NOT NULL, synced_at TEXT NOT NULL, event_count INTEGER);
            CREATE TABLE IF NOT EXISTS aggregate_tags (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL, tag TEXT NOT NULL, ts TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS aggregate_choices (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL, choice_id TEXT NOT NULL, ts TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS generated_scenes (id INTEGER PRIMARY KEY AUTOINCREMENT, child_name TEXT NOT NULL, child_age TEXT, task_context TEXT, set_brief TEXT, generated_at TEXT NOT NULL, file_path TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS llm_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL, session_id TEXT NOT NULL, total_requests INTEGER DEFAULT 0, cache_hits INTEGER DEFAULT 0, estimated_tokens INTEGER DEFAULT 0, ts TEXT NOT NULL);
        """)
init_db()

if __name__ == "__main__":
    import uvicorn
    registry = load_registry()
    print("🚀 Живая Книга — Сервер v6.2 (Сетевая Студия)")
    print(f"🤖 {OPENROUTER_MODEL} (только для free_talk)")
    print(f"🌐 SETH_WORKER_URL = {SETH_WORKER_URL}")
    print(f"📖 {BOOKS_DIR} | 🆔 {len(registry.get('profiles',[]))} профилей")
    print(f"👨‍👩‍👧 Родителей: {len(registry.get('parents',[]))}")
    if PLAYER_DIR.exists():
        print(f"📺 Искорка:  http://127.0.0.1:8001/player/index.html")
    if DASHBOARD_DIR.exists():
        print(f"📊 Кабинет:  http://127.0.0.1:8001/dashboard/index.html")
    print("⚠️  НЕ используй Live Server — он перезагружает Искорку!")
    uvicorn.run(app, host="0.0.0.0", port=8001)
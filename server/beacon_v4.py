"""
beacon.py v5.0 — Единый сервер Живой Книги (Реестр Судеб)
============================================================
Объединяет: Ночной Маяк + Полный 18-агентный пайплайн + Автодоставка
Новое в v5.0: uid-маршрутизация, registry.json, biography writer

Поток:
  Кабинет Родителя → POST /api/studio/generate
    → SET (маршрутизация) → uid из registry.json
    → A00 Фабула Фейн (история) + biography.json
    → A00a Вера Душа (ревизия, макс 3 петли)
    → A01-A16 (полный пайплайн)
    → Book Package → books/{uid_folder}/ (автодоставка для Искорки)

  Искорка → GET /api/beacon/uid/{uid}/meta        (v2 — приоритет)
  Искорка → GET /api/beacon/stories/{name}/meta    (v1 — обратная совместимость)
  Искорка → POST /beacon                           (NightBeacon → biography.json)
  Искорка → POST /api/free_talk                    (гибридный диалог)

  Кабинет → GET /api/parent/uid/{uid}/{category}   (v2)
  Кабинет → GET /api/parent/{category}/{name}      (v1)
  Кабинет → GET /api/registry                      (список профилей)

Запуск:
    pip install fastapi uvicorn httpx python-dotenv
    uvicorn beacon_v4:app --host 0.0.0.0 --port 8001
"""

import json
import re
import hashlib
import sqlite3
import os
import httpx
from datetime import datetime
from pathlib import Path
from functools import lru_cache
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Живая Книга — Единый Сервер v5.0 (Реестр Судеб)", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── ПУТИ ────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent          # .../server/
BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"   # .../books/
BOOKS_DIR.mkdir(parents=True, exist_ok=True)

PERSONAL_DIR  = BOOKS_DIR / "personal"
REGISTRY_PATH = BOOKS_DIR / "registry.json"
BEACON_DB     = BASE_DIR / "beacon.db"

print(f"📁 BOOKS_DIR = {BOOKS_DIR}")

# ─── OPENROUTER ──────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")

# ─── ПРОМПТЫ АГЕНТОВ ─────────────────────────────────────────────────────────
STUDIO_ROOT  = Path(os.getenv("STUDIO_ROOT", str(BASE_DIR / ".." / ".." / "-2")))
MODULES_PATH = STUDIO_ROOT / "studio" / "modules" / "living_book"


# ═══════════════════════════════════════════════════════════════════════════════
# РЕЕСТР СУДЕБ (REGISTRY) — §10
# ═══════════════════════════════════════════════════════════════════════════════

def load_registry() -> dict:
    """Загружает registry.json. Создаёт пустой если не существует."""
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    empty = {"version": "1.0", "updated_at": datetime.now().isoformat(), "profiles": []}
    save_registry(empty)
    return empty


def save_registry(registry: dict):
    """Сохраняет registry.json с обновлённой датой."""
    registry["updated_at"] = datetime.now().isoformat()
    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def generate_uid() -> str:
    """Генерирует новый uid формата LB-YYYY-MM-DD-NNNN."""
    today = datetime.now().strftime("%Y-%m-%d")
    registry = load_registry()
    today_count = sum(
        1 for p in registry["profiles"]
        if p["uid"].startswith(f"LB-{today}")
    )
    return f"LB-{today}-{today_count + 1:04d}"


def resolve_uid(uid: str) -> Optional[Path]:
    """
    Находит папку ребёнка по uid из registry.json.
    Возвращает Path к папке или None.
    """
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            folder = BOOKS_DIR / profile["folder"]
            if folder.exists():
                return folder
    return None


def get_profile_by_uid(uid: str) -> Optional[dict]:
    """Возвращает профиль из реестра по uid."""
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            return profile
    return None


def find_uid_by_name(child_name: str) -> Optional[str]:
    """Ищет uid по alias (имени ребёнка). Case-insensitive."""
    registry = load_registry()
    target = child_name.lower()
    for profile in registry.get("profiles", []):
        if profile.get("alias", "").lower() == target:
            return profile["uid"]
        if profile.get("folder", "").lower() == target:
            return profile["uid"]
    return None


def ensure_registry_entry(child_name: str, age_group: str = "7-12") -> str:
    """
    Гарантирует наличие записи в реестре.
    Если нет — создаёт новую (авто-миграция v1 → v2).
    Возвращает uid.
    """
    existing_uid = find_uid_by_name(child_name)
    if existing_uid:
        return existing_uid

    # Авто-миграция: создаём запись для существующей папки
    uid = generate_uid()
    registry = load_registry()

    # Определяем folder — если папка уже есть по имени, используем её
    folder = child_name
    child_dir = _find_child_folder(child_name)
    if child_dir:
        folder = child_dir.name  # Сохраняем оригинальное имя папки

    registry["profiles"].append({
        "uid": uid,
        "alias": child_name,
        "folder": folder,
        "age_group": age_group,
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "last_activity": datetime.now().isoformat(),
        "history_file": "biography.json",
        "device_ids": [],
        "status": "active",
    })
    save_registry(registry)
    print(f"[REGISTRY] ✅ Создан профиль: {uid} → {folder} (alias: {child_name})")
    return uid


def update_last_activity(uid: str):
    """Обновляет last_activity в реестре."""
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            profile["last_activity"] = datetime.now().isoformat()
            save_registry(registry)
            return


# ═══════════════════════════════════════════════════════════════════════════════
# BIOGRAPHY WRITER (Историческая Память) — §12
# ═══════════════════════════════════════════════════════════════════════════════

def update_biography(uid: str, entry: dict):
    """
    Добавляет запись в biography.json ребёнка.
    Создаёт файл если не существует.
    """
    folder = resolve_uid(uid)
    if not folder:
        print(f"[BIOGRAPHY] ⚠️ Папка не найдена для uid={uid}")
        return

    bio_path = folder / "biography.json"
    profile = get_profile_by_uid(uid)
    alias = profile.get("alias", "Ребёнок") if profile else "Ребёнок"

    if bio_path.exists():
        bio = json.loads(bio_path.read_text(encoding="utf-8"))
    else:
        bio = {
            "uid": uid,
            "child_name": alias,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "total_stories": 0,
            "memory_depth": "infinite",
            "karmic_trail": [],
            "character_bonds": {},
            "world_knowledge": [],
            "emotional_milestones": [],
            "psychological_patterns": [],
        }

    # Добавляем uid если его нет (миграция)
    bio.setdefault("uid", uid)
    bio.setdefault("memory_depth", "infinite")

    # Добавляем запись
    bio["karmic_trail"].append(entry)
    bio["total_stories"] = len(bio["karmic_trail"])
    bio["updated_at"] = datetime.now().isoformat()

    # Обновляем character_bonds
    for char in entry.get("characters_met", []):
        bio["character_bonds"][char] = bio["character_bonds"].get(char, 0) + 1

    bio_path.write_text(
        json.dumps(bio, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[BIOGRAPHY] ✅ Обновлён для {alias} (uid={uid}): {len(bio['karmic_trail'])} записей")


def append_choices_to_biography(uid: str, choices: list, tags: list):
    """
    Добавляет choices и tags из NightBeacon в последнюю запись karmic_trail.
    Вызывается при POST /beacon.
    """
    folder = resolve_uid(uid)
    if not folder:
        return

    bio_path = folder / "biography.json"
    if not bio_path.exists():
        return

    bio = json.loads(bio_path.read_text(encoding="utf-8"))
    if not bio.get("karmic_trail"):
        return

    # Добавляем в последнюю запись
    last = bio["karmic_trail"][-1]
    existing_choices = last.get("choices_made", [])
    existing_choices.extend([{"choice_id": c, "source": "nightbeacon"} for c in choices])
    last["choices_made"] = existing_choices

    # Теги → psychological_patterns
    for tag in tags:
        if tag not in bio.get("psychological_patterns", []):
            bio.setdefault("psychological_patterns", []).append(tag)

    bio["updated_at"] = datetime.now().isoformat()
    bio_path.write_text(
        json.dumps(bio, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════════════════════

def load_agent_prompt(agent_id: str) -> str:
    """Загружает промпт агента из Студии (modules/living_book/{agent_id}/forge/prompt.md)"""
    for prompt_path in [
        MODULES_PATH / agent_id / "forge" / "prompt.md",
        MODULES_PATH / agent_id / "prompt.md",
    ]:
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
    return f"Ты агент {agent_id}. Выполни задачу качественно."


def load_agent_anchor(agent_id: str) -> str:
    """Загружает якорные точки агента"""
    anchor_path = MODULES_PATH / agent_id / "core" / "anchor_points.md"
    if anchor_path.exists():
        return anchor_path.read_text(encoding="utf-8")
    return ""


async def call_openrouter(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4000,
    temperature: float = 0.7,
) -> str:
    """Единый клиент OpenRouter."""
    if not OPENROUTER_API_KEY:
        raise HTTPException(500, "OPENROUTER_API_KEY не задан")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
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
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


def extract_json_from_response(raw: str) -> dict:
    """Извлекает JSON из ответа агента (между SYSTEM_JSON_START/END или ```json)."""
    # Попытка 1: теги
    match = re.search(r"SYSTEM_JSON_START\s*(.*?)\s*SYSTEM_JSON_END", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    
    # Попытка 2: markdown блок
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    
    # Попытка 3: голый JSON
    for start in [raw.find("{"), raw.find("[")]:
        if start >= 0:
            try:
                return json.loads(raw[start:])
            except json.JSONDecodeError:
                pass
    
    return {}


def _find_child_folder(name: str) -> Optional[Path]:
    """Case-insensitive поиск папки ребёнка в books/"""
    if not BOOKS_DIR.exists():
        return None
    for d in BOOKS_DIR.iterdir():
        if d.is_dir() and d.name.lower() == name.lower():
            return d
    return None


def _find_book_path(child_name: str) -> Optional[Path]:
    """
    Ищет book.json в BOOKS_DIR с учётом регистра папки.
    Приоритет: точное совпадение → lower() → case-insensitive перебор.
    """
    candidates = [
        BOOKS_DIR / child_name / "book.json",
        BOOKS_DIR / child_name.lower() / "book.json",
        BOOKS_DIR / child_name.lower().replace(" ", "_") / "book.json",
    ]
    for p in candidates:
        if p.exists():
            return p

    if BOOKS_DIR.exists():
        target_lower = child_name.lower().replace(" ", "_")
        for entry in BOOKS_DIR.iterdir():
            if entry.is_dir() and entry.name.lower().replace(" ", "_") == target_lower:
                p = entry / "book.json"
                if p.exists():
                    return p
    return None


def _find_book_path_by_uid(uid: str) -> Optional[Path]:
    """Ищет book.json через uid → registry → folder."""
    folder = resolve_uid(uid)
    if folder:
        book_path = folder / "book.json"
        if book_path.exists():
            return book_path
    return None


def _find_stories_folder(child_name: str) -> Optional[Path]:
    """Case-insensitive поиск папки в server/stories/"""
    stories_root = BASE_DIR / "stories"
    if not stories_root.exists():
        return None
    direct = stories_root / child_name
    if direct.exists():
        return direct
    lower = stories_root / child_name.lower().replace(" ", "_")
    if lower.exists():
        return lower
    target = child_name.lower().replace(" ", "_")
    for entry in stories_root.iterdir():
        if entry.is_dir() and entry.name.lower().replace(" ", "_") == target:
            return entry
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# SET — ОРКЕСТРАТОР
# ═══════════════════════════════════════════════════════════════════════════════

SET_SYSTEM_PROMPT = """Ты — Сет, Главный оркестратор студии SIX FINGERS.
Ты работаешь как серверный диспетчер-робот.
Ты принимаешь данные из Кабинета Родителя и формируешь машинный бриф.

## ЗАДАЧА:
Получить данные о ребёнке и задаче → собрать MASTER BRIEF для цеха LIVING_BOOK.

## ПРИНЦИПЫ:
- Цех: living_book
- Следующий агент: A00 (Фабула Фейн)
- Ты НЕ пишешь истории — только структурируешь бриф

## ОБЯЗАТЕЛЬНЫЕ ПОЛЯ creative_soul:
1. Что должен ПОЧУВСТВОВАТЬ ребёнок?
2. Какой волшебный мир создать?
3. Что категорически нельзя?
4. Ради чего?

## ФОРМАТ:
SYSTEM_JSON_START
{
  "workshop": "living_book",
  "next_step": "A00",
  "child_name": "<имя>",
  "child_age": "<возраст>",
  "age_group": "<3-6 | 7-12 | 13+>",
  "task_context": "<суть задачи>",
  "real_task": "<психологическая суть>",
  "theme": "<тема>",
  "emotional_goal": "<что почувствует ребёнок>",
  "world": "<волшебный мир>",
  "forbidden": "<что нельзя>",
  "purpose": "<ради чего>",
  "creative_soul": {
    "feel": "<эмоция>",
    "world": "<мир>",
    "forbidden": "<запрет>",
    "purpose": "<цель>"
  }
}
SYSTEM_JSON_END
"""


# ═══════════════════════════════════════════════════════════════════════════════
# ПОЛНЫЙ ПАЙПЛАЙН
# ═══════════════════════════════════════════════════════════════════════════════

PIPELINE_AGENTS = [
    "A01", "A02", "A03", "A04",   # PRE-PROD
    "A05", "A06", "A07", "A08",   # PROD
    "A09", "A10", "A11", "A12",   # POST-PROD
    "A13", "A14", "A15", "A16",   # DELIVERY
]

MAX_REVISION_LOOPS = 3


async def run_genesis(master_brief: dict) -> tuple[str, dict]:
    """
    GENESIS фаза: A00 (Фабула) → A00a (Вера) с ревизионной петлёй.
    Возвращает (raw_a00_result, a00a_meta).
    """
    brief_json = json.dumps(master_brief, ensure_ascii=False, indent=2)
    revision_notes = ""
    
    for loop in range(MAX_REVISION_LOOPS):
        a00_prompt = load_agent_prompt("A00")
        a00_anchor = load_agent_anchor("A00")
        
        user_ctx = f"MASTER BRIEF:\n{brief_json}\n"
        if revision_notes:
            user_ctx += f"\n⚠️ ЗАМЕЧАНИЯ ОТ ВЕРЫ ДУШИ (исправь!):\n{revision_notes}\n"
        if a00_anchor:
            user_ctx = a00_anchor + "\n\n" + user_ctx
        
        print(f"  [GENESIS] A00 Фабула Фейн (петля {loop + 1}/{MAX_REVISION_LOOPS})...")
        a00_raw = await call_openrouter(a00_prompt, user_ctx)
        
        a00a_prompt = load_agent_prompt("A00a")
        a00a_anchor = load_agent_anchor("A00a")
        
        a00a_ctx = f"РЕЗУЛЬТАТ ФАБУЛЫ ФЕЙН:\n{a00_raw}\n\nMASTER BRIEF:\n{brief_json}"
        if a00a_anchor:
            a00a_ctx = a00a_anchor + "\n\n" + a00a_ctx
        
        print(f"  [GENESIS] A00a Вера Душа...")
        a00a_raw = await call_openrouter(a00a_prompt, a00a_ctx)
        a00a_meta = extract_json_from_response(a00a_raw)
        
        my_output = a00a_meta.get("my_output", a00a_meta)
        verdict = my_output.get("verdict", "APPROVED").upper()
        
        if "APPROVED" in verdict:
            print(f"  [GENESIS] ✅ Вера одобрила (петля {loop + 1})")
            return a00_raw, a00a_meta
        
        revision_notes = my_output.get("revision_notes", "")
        recommendations = my_output.get("recommendations", [])
        if recommendations:
            revision_notes += "\n\nКонкретные исправления:\n"
            for i, rec in enumerate(recommendations, 1):
                revision_notes += f"{i}. {rec}\n"
        
        print(f"  [GENESIS] 🔄 REVISION (петля {loop + 1}): {revision_notes[:100]}...")
    
    print(f"  [GENESIS] ⚠️ Исчерпаны {MAX_REVISION_LOOPS} петель, пропускаем с пометкой")
    return a00_raw, {"my_output": {"verdict": "APPROVED_WITH_NOTES", "note": "Исчерпан лимит ревизий"}}


async def run_pipeline_agent(agent_id: str, chain_context: str, master_brief: dict) -> str:
    """Запускает одного агента пайплайна."""
    system_prompt = load_agent_prompt(agent_id)
    anchor = load_agent_anchor(agent_id)
    
    user_ctx = ""
    if anchor:
        user_ctx += anchor + "\n\n"
    user_ctx += f"MASTER BRIEF:\n{json.dumps(master_brief, ensure_ascii=False, indent=2)}\n\n"
    user_ctx += f"РЕЗУЛЬТАТЫ ПРЕДЫДУЩИХ АГЕНТОВ:\n{chain_context[-6000:]}\n"
    
    raw = await call_openrouter(system_prompt, user_ctx, max_tokens=4000)
    return raw


async def run_full_pipeline(master_brief: dict) -> dict:
    """Полный 18-агентный пайплайн."""
    results = {}
    
    print("[PIPELINE] === GENESIS ===")
    a00_raw, a00a_meta = await run_genesis(master_brief)
    results["A00"] = a00_raw
    results["A00a"] = a00a_meta
    
    chain_context = f"--- A00 Фабула Фейн ---\n{a00_raw[:3000]}\n"
    chain_context += f"--- A00a Вера Душа ---\nВердикт: {a00a_meta.get('my_output', {}).get('verdict', 'APPROVED')}\n"
    
    for agent_id in PIPELINE_AGENTS:
        prompt = load_agent_prompt(agent_id)
        is_stub = prompt.startswith("Ты агент") and len(prompt) < 100
        
        if is_stub:
            print(f"  [PIPELINE] {agent_id}: заглушка, пропускаем")
            results[agent_id] = {"status": "stub", "note": "Промпт не написан"}
            continue
        
        phase = "PRE-PROD" if agent_id in ["A01","A02","A03","A04"] else \
                "PROD" if agent_id in ["A05","A06","A07","A08"] else \
                "POST-PROD" if agent_id in ["A09","A10","A11","A12"] else "DELIVERY"
        
        print(f"  [PIPELINE] {phase} → {agent_id}...")
        
        try:
            raw = await run_pipeline_agent(agent_id, chain_context, master_brief)
            results[agent_id] = raw
            
            meta = extract_json_from_response(raw)
            my_output = meta.get("my_output", {})
            if my_output:
                chain_context += f"\n--- {agent_id} ---\n{json.dumps(my_output, ensure_ascii=False)[:1500]}\n"
            else:
                chain_context += f"\n--- {agent_id} ---\n{raw[:1000]}\n"
                
        except Exception as e:
            print(f"  [PIPELINE] ❌ {agent_id}: {e}")
            results[agent_id] = {"status": "error", "error": str(e)}
    
    return results


def extract_book_package(results: dict) -> dict:
    """Извлекает Book Package из результата A16 (Марка Файн)."""
    a16_raw = results.get("A16", "")
    if isinstance(a16_raw, dict):
        return a16_raw
    
    package = {}
    
    file_blocks = re.findall(
        r'### === FILE:\s*(.+?)\s*===\s*\n```json\s*\n(.*?)\n```',
        a16_raw, re.DOTALL
    )
    
    for filename, content in file_blocks:
        filename = filename.strip()
        try:
            package[filename] = json.loads(content)
        except json.JSONDecodeError:
            package[filename] = content
    
    if not package:
        meta = extract_json_from_response(a16_raw)
        if meta:
            package = meta
    
    return package


def save_book_package(uid: str, child_name: str, package: dict, master_brief: dict) -> Path:
    """
    Сохраняет Book Package в books/{folder}/ для Искорки.
    v5.0: работает через uid → registry → folder.
    """
    folder = resolve_uid(uid)
    if not folder:
        # Fallback: создаём по имени (обратная совместимость)
        safe_name = child_name.lower().replace(" ", "_")
        folder = BOOKS_DIR / safe_name
    
    folder.mkdir(parents=True, exist_ok=True)
    
    for filename, content in package.items():
        file_path = folder / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        if isinstance(content, (dict, list)):
            # Инжектим uid в book.json
            if filename == "book.json" and isinstance(content, dict):
                content["uid"] = uid
            file_path.write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        else:
            file_path.write_text(str(content), encoding="utf-8")
        
        print(f"  [SAVE] {file_path}")
    
    # Мастер-бриф
    brief_path = folder / "_master_brief.json"
    brief_path.write_text(
        json.dumps(master_brief, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    # Pending для /api/beacon/stories
    profile = get_profile_by_uid(uid)
    pending_key = profile["folder"].lower().replace(" ", "_") if profile else child_name.lower().replace(" ", "_")
    pending_dir = BASE_DIR / "stories" / pending_key
    pending_dir.mkdir(parents=True, exist_ok=True)
    story_id = f"story_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    pending_path = pending_dir / f"{story_id}_pending.json"
    pending_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    return folder


# ═══════════════════════════════════════════════════════════════════════════════
# ЭНДПОИНТЫ
# ═══════════════════════════════════════════════════════════════════════════════

# ─── СХЕМЫ ───────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    child_name: str
    child_age: Optional[str] = "7-12"
    task_context: str
    uid: Optional[str] = None  # v2: можно передать uid напрямую

class FreeTalkRequest(BaseModel):
    child_text: str
    scene_id: str
    chapter_id: str = ""
    child_name: str = "Ребёнок"
    uid: Optional[str] = None  # v2
    session_id: str = ""

class BeaconEvent(BaseModel):
    type: str
    ts: int
    choice_id: Optional[str] = None
    tag: Optional[str] = None

class BeaconBatch(BaseModel):
    device_id: str
    session_id: str
    synced_at: str
    uid: Optional[str] = None  # v2: привязка к uid
    events: list[BeaconEvent]
    llm_stats: Optional[dict] = None


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY ENDPOINTS (§10)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/registry")
async def get_registry():
    """Возвращает весь реестр профилей."""
    return load_registry()


@app.get("/api/registry/{uid}")
async def get_registry_profile(uid: str):
    """Возвращает один профиль по uid."""
    profile = get_profile_by_uid(uid)
    if not profile:
        raise HTTPException(404, f"Профиль {uid} не найден")
    return profile


# ═══════════════════════════════════════════════════════════════════════════════
# ГЕНЕРАЦИЯ КНИГИ (полный пайплайн)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/studio/generate")
async def generate_book(req: GenerateRequest):
    """
    Полный автономный конвейер:
    SET → A00 ↔ A00a → A01-A16 → Book Package → books/{folder}/
    v5.0: uid-маршрутизация + biography writer
    """
    print(f"\n{'='*60}")
    print(f"📖 ЗАКАЗ: {req.child_name}, {req.child_age}, {req.task_context}")
    print(f"{'='*60}")
    
    # ── uid: получаем или создаём ──
    uid = req.uid or ensure_registry_entry(req.child_name, req.child_age or "7-12")
    print(f"  🆔 uid: {uid}")
    
    # ── ШАГ 1: SET ──
    print("\n[1/4] SET — маршрутизация...")
    set_raw = await call_openrouter(
        system_prompt=SET_SYSTEM_PROMPT,
        user_prompt=(
            f"Данные из Кабинета Родителя:\n"
            f"- Ребёнок: {req.child_name}\n"
            f"- Возраст: {req.child_age}\n"
            f"- Задача: {req.task_context}\n\n"
            f"Выдай MASTER BRIEF между тегами SYSTEM_JSON_START и SYSTEM_JSON_END."
        ),
        max_tokens=800,
    )
    master_brief = extract_json_from_response(set_raw)
    if not master_brief:
        raise HTTPException(422, f"SET не вернул валидный JSON: {set_raw[:300]}")
    
    master_brief.setdefault("child_name", req.child_name)
    master_brief.setdefault("child_age", req.child_age)
    master_brief.setdefault("task_context", req.task_context)
    master_brief["uid"] = uid  # Инжектим uid в бриф
    print(f"  ✅ MASTER BRIEF получен")
    
    # ── ШАГ 2: ПОЛНЫЙ ПАЙПЛАЙН ──
    print("\n[2/4] ПАЙПЛАЙН — 18 агентов...")
    results = await run_full_pipeline(master_brief)
    print(f"  ✅ Пайплайн завершён ({len(results)} агентов)")
    
    # ── ШАГ 3: СОХРАНЕНИЕ ──
    print("\n[3/4] СОХРАНЕНИЕ Book Package...")
    package = extract_book_package(results)
    
    if package:
        book_dir = save_book_package(uid, req.child_name, package, master_brief)
        print(f"  ✅ Сохранено в {book_dir}")
    else:
        print(f"  ⚠️ Не удалось извлечь Book Package из A16")
        book_dir = None
    
    # ── ШАГ 4: BIOGRAPHY WRITER (§12) ──
    print("\n[4/4] BIOGRAPHY — запись в Историческую Память...")
    update_biography(uid, {
        "date": datetime.now().isoformat(),
        "story_id": f"story_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "theme": master_brief.get("theme", ""),
        "task_context": master_brief.get("task_context", ""),
        "emotional_goal": master_brief.get("emotional_goal", ""),
        "characters_met": [],  # A16 should fill this
        "choices_made": [],
        "key_message": master_brief.get("purpose", ""),
        "world": master_brief.get("world", ""),
    })
    update_last_activity(uid)
    
    # БД
    with sqlite3.connect(BEACON_DB) as conn:
        conn.execute(
            """INSERT INTO generated_scenes
               (child_name, child_age, task_context, set_brief, generated_at, file_path)
               VALUES (?,?,?,?,?,?)""",
            (req.child_name, req.child_age, req.task_context,
             json.dumps(master_brief, ensure_ascii=False),
             datetime.now().isoformat(),
             str(book_dir) if book_dir else "")
        )
    
    print(f"\n{'='*60}")
    print(f"🎉 ГОТОВО! Книга для «{req.child_name}» создана. uid={uid}")
    print(f"{'='*60}\n")
    
    return {
        "ok": True,
        "uid": uid,
        "pipeline": "SET → A00 ↔ A00a → A01-A16",
        "child_name": req.child_name,
        "book_dir": str(book_dir) if book_dir else None,
        "agents_completed": len([r for r in results.values() if not (isinstance(r, dict) and r.get("status") == "stub")]),
        "agents_stubbed": len([r for r in results.values() if isinstance(r, dict) and r.get("status") == "stub")]),
        "package_files": list(package.keys()) if package else [],
        "master_brief": master_brief,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FREE TALK (гибридный диалог для Искорки)
# ═══════════════════════════════════════════════════════════════════════════════

SAFETY_KEYWORDS = [
    "помогите", "спасите", "умереть", "убить", "кровь",
    "наркотик", "секс", "порно",
]

@lru_cache(maxsize=1000)
def _cached_llm_response(text_hash: str, scene_id: str) -> str:
    """Серверный кэш LLM-ответов (в памяти процесса)."""
    return ""

@app.post("/api/free_talk")
async def free_talk(req: FreeTalkRequest):
    """Гибридный диалог для Искорки."""
    text_lower = req.child_text.lower()
    if any(kw in text_lower for kw in SAFETY_KEYWORDS):
        return {
            "text": "Давай поговорим о чём-то другом, хорошо?",
            "color": "yellow",
            "cached": False,
            "blocked": True,
        }
    
    text_hash = hashlib.md5(f"{req.child_text}:{req.scene_id}".encode()).hexdigest()
    cached = _cached_llm_response(text_hash, req.scene_id)
    if cached:
        return {"text": cached, "color": "cyan", "cached": True}
    
    prompt = f"""Ты — Искорка, тёплый спутник ребёнка в мире Грондхейм.
Ребёнок {req.child_name} в сцене {req.scene_id} сказал: «{req.child_text}»

Ответь по методу Гиппенрейтер:
- Не давай готовых решений.
- Отрази чувство ребёнка.
- Задай направляющий вопрос.
- Максимум 2 предложения.
- Тон: тёплый, любопытный, застенчивый."""

    try:
        response = await call_openrouter(
            system_prompt="Ты — Искорка. Отвечай ТОЛЬКО текст для ребёнка, без JSON.",
            user_prompt=prompt,
            max_tokens=150,
            temperature=0.8,
        )
        return {"text": response, "color": "cyan", "cached": False}
    except Exception as e:
        return {
            "text": "Я тебя слышу... Расскажи ещё раз?",
            "color": "blue",
            "cached": False,
            "error": str(e),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# UID-МАРШРУТЫ (v2 — §5, §10)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/beacon/uid/{uid}/meta")
async def get_book_meta_by_uid(uid: str):
    """v2: Искорка запрашивает book.json через uid."""
    book_path = _find_book_path_by_uid(uid)
    if not book_path:
        raise HTTPException(404, f"Книга для uid='{uid}' не найдена")
    data = json.loads(book_path.read_text(encoding="utf-8"))
    update_last_activity(uid)
    profile = get_profile_by_uid(uid)
    data["_alias"] = profile.get("alias", "") if profile else ""
    print(f"[META/uid] Отдаю book.json для uid={uid}: {data.get('title', '?')}")
    return data


@app.get("/api/beacon/uid/{uid}/chapters/{chapter_id}")
async def get_chapter_by_uid(uid: str, chapter_id: str):
    """v2: Искорка запрашивает главу через uid."""
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Папка для uid='{uid}' не найдена")
    
    chapter_file = folder / "chapters" / f"{chapter_id}.json"
    
    if not chapter_file.exists():
        chapters_dir = folder / "chapters"
        if chapters_dir.exists():
            for f in chapters_dir.iterdir():
                if f.stem.lower() == chapter_id.lower():
                    chapter_file = f
                    break
    
    if not chapter_file.exists():
        raise HTTPException(404, f"Глава '{chapter_id}' не найдена (uid={uid})")
    
    data = json.loads(chapter_file.read_text(encoding="utf-8"))
    update_last_activity(uid)
    print(f"[CHAPTER/uid] Отдаю {chapter_id} для uid={uid}: {len(data.get('scenes', []))} сцен")
    return data


@app.get("/api/beacon/uid/{uid}/stories")
async def get_stories_by_uid(uid: str):
    """v2: Искорка проверяет новые книги через uid."""
    profile = get_profile_by_uid(uid)
    if not profile:
        raise HTTPException(404, f"Профиль uid='{uid}' не найден")
    
    folder_name = profile["folder"].lower().replace(" ", "_")
    stories_dir = BASE_DIR / "stories" / folder_name
    
    if not stories_dir.exists():
        return []
    
    stories = []
    for pending_file in stories_dir.glob("*_pending.json"):
        data = json.loads(pending_file.read_text(encoding="utf-8"))
        stories.append({
            "story_id": pending_file.stem.replace("_pending", ""),
            "title": data.get("title", "Новая история"),
            "created_at": datetime.fromtimestamp(pending_file.stat().st_mtime).isoformat(),
        })
    return stories


# ─── PARENT CABINET uid-маршруты (§13) ───────────────────────────────────────

@app.get("/api/parent/uid/{uid}/{category}")
async def get_parent_data_by_uid(uid: str, category: str):
    """v2: Кабинет Родителя запрашивает данные через uid."""
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Папка для uid='{uid}' не найдена")
    
    target_file = folder / f"{category}.json"
    if not target_file.exists():
        raise HTTPException(404, f"Файл {category}.json не найден (uid={uid})")
    
    data = json.loads(target_file.read_text(encoding="utf-8"))
    print(f"✅ [PARENT/uid] {category} для uid={uid}")
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# ОБРАТНАЯ СОВМЕСТИМОСТЬ (v1 маршруты — по имени)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/beacon/stories/{child_name}/meta")
async def get_book_meta(child_name: str):
    """v1: Искорка запрашивает book.json по имени (обратная совместимость)."""
    book_path = _find_book_path(child_name)
    if not book_path or not book_path.exists():
        raise HTTPException(404, f"Книга для '{child_name}' не найдена")
    data = json.loads(book_path.read_text(encoding="utf-8"))
    # Авто-миграция: создаём запись в реестре если нет
    ensure_registry_entry(child_name)
    print(f"[META/v1] Отдаю book.json для '{child_name}': {data.get('title', '?')}")
    return data


@app.get("/api/beacon/stories/{child_name}/chapters/{chapter_id}")
async def get_chapter(child_name: str, chapter_id: str):
    """v1: Искорка запрашивает главу по имени (обратная совместимость)."""
    book_path = _find_book_path(child_name)
    if not book_path:
        raise HTTPException(404, f"Книга для '{child_name}' не найдена")
    
    book_dir = book_path.parent
    chapter_file = book_dir / "chapters" / f"{chapter_id}.json"
    
    if not chapter_file.exists():
        chapters_dir = book_dir / "chapters"
        if chapters_dir.exists():
            for f in chapters_dir.iterdir():
                if f.stem.lower() == chapter_id.lower():
                    chapter_file = f
                    break
    
    if not chapter_file.exists():
        raise HTTPException(404, f"Глава '{chapter_id}' не найдена")
    
    data = json.loads(chapter_file.read_text(encoding="utf-8"))
    print(f"[CHAPTER/v1] Отдаю {chapter_id} для '{child_name}': {len(data.get('scenes', []))} сцен")
    return data


@app.get("/api/beacon/stories/{child_name}")
async def get_stories_for_child(child_name: str):
    """v1: Искорка забирает книги по имени (обратная совместимость)."""
    stories_dir = _find_stories_folder(child_name)
    
    if not stories_dir or not stories_dir.exists():
        return []
    
    stories = []
    for pending_file in stories_dir.glob("*_pending.json"):
        data = json.loads(pending_file.read_text(encoding="utf-8"))
        stories.append({
            "story_id": pending_file.stem.replace("_pending", ""),
            "title": data.get("title", "Новая история"),
            "created_at": datetime.fromtimestamp(pending_file.stat().st_mtime).isoformat(),
        })
    return stories


@app.get("/api/parent/{category}/{child_name}")
async def get_parent_data(category: str, child_name: str):
    """v1: Кабинет Родителя по имени (обратная совместимость)."""
    child_dir = _find_child_folder(child_name)
    if not child_dir:
        raise HTTPException(404, f"Папка для {child_name} не найдена")

    target_file = child_dir / f"{category}.json"
    if target_file.exists():
        print(f"✅ [PARENT/v1] {category} для {child_name}")
        return json.loads(target_file.read_text(encoding="utf-8"))
    
    raise HTTPException(404, f"Файл {category}.json не найден в {child_dir}")


# ═══════════════════════════════════════════════════════════════════════════════
# НОЧНОЙ МАЯК (NightBeacon) — §12
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/beacon")
async def receive_beacon(batch: BeaconBatch):
    """
    Ночной батч метрик от Искорки.
    v5.0: записывает choices/tags в biography.json через uid.
    """
    with sqlite3.connect(BEACON_DB) as conn:
        conn.execute(
            "INSERT INTO sync_log (device_id, session_id, synced_at, event_count) VALUES (?,?,?,?)",
            (batch.device_id, batch.session_id, batch.synced_at, len(batch.events))
        )
        
        choices_collected = []
        tags_collected = []
        
        for event in batch.events:
            ts_str = datetime.utcfromtimestamp(event.ts / 1000).isoformat()
            if event.type == "tag" and event.tag:
                conn.execute(
                    "INSERT INTO aggregate_tags (device_id, tag, ts) VALUES (?,?,?)",
                    (batch.device_id, event.tag, ts_str)
                )
                tags_collected.append(event.tag)
            elif event.type == "choice" and event.choice_id:
                conn.execute(
                    "INSERT INTO aggregate_choices (device_id, choice_id, ts) VALUES (?,?,?)",
                    (batch.device_id, event.choice_id, ts_str)
                )
                choices_collected.append(event.choice_id)
        
        # LLM метрики
        if batch.llm_stats:
            conn.execute(
                """INSERT OR REPLACE INTO llm_metrics 
                   (device_id, session_id, total_requests, cache_hits, estimated_tokens, ts)
                   VALUES (?,?,?,?,?,?)""",
                (batch.device_id, batch.session_id,
                 batch.llm_stats.get("total_requests", 0),
                 batch.llm_stats.get("cache_hits", 0),
                 batch.llm_stats.get("estimated_tokens", 0),
                 batch.synced_at)
            )
    
    # §12: Записываем в biography.json
    if batch.uid and (choices_collected or tags_collected):
        append_choices_to_biography(batch.uid, choices_collected, tags_collected)
        # Привязываем device_id к профилю
        registry = load_registry()
        for profile in registry.get("profiles", []):
            if profile["uid"] == batch.uid:
                if batch.device_id not in profile.get("device_ids", []):
                    profile.setdefault("device_ids", []).append(batch.device_id)
                    save_registry(registry)
                break
    
    print(f"[МАЯК] Батч от {batch.device_id}: {len(batch.events)} событий"
          f"{f' (uid={batch.uid})' if batch.uid else ''}")
    return {"ok": True, "received": len(batch.events)}


# ═══════════════════════════════════════════════════════════════════════════════
# ПЕРСОНАЛЬНАЯ СЦЕНА (быстрая генерация)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/studio/quick_scene")
async def quick_scene(req: GenerateRequest):
    """Быстрая генерация: только SET → Фабула (без полного пайплайна)."""
    print(f"[QUICK] Быстрая сцена для {req.child_name}...")
    
    uid = req.uid or ensure_registry_entry(req.child_name, req.child_age or "7-12")
    
    set_raw = await call_openrouter(
        system_prompt=SET_SYSTEM_PROMPT,
        user_prompt=f"Ребёнок: {req.child_name}, {req.child_age}. Задача: {req.task_context}",
        max_tokens=600,
    )
    master_brief = extract_json_from_response(set_raw)
    master_brief["uid"] = uid
    
    fabula_prompt = load_agent_prompt("A00")
    fabula_raw = await call_openrouter(
        system_prompt=fabula_prompt,
        user_prompt=f"MASTER BRIEF:\n{json.dumps(master_brief, ensure_ascii=False, indent=2)}",
        max_tokens=2000,
    )
    
    PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = req.child_name.lower().replace(" ", "_")
    file_path = PERSONAL_DIR / f"{safe_name}_personal_scene.json"
    
    scene_data = extract_json_from_response(fabula_raw)
    if not scene_data:
        scene_data = {"raw": fabula_raw}
    scene_data["_master_brief"] = master_brief
    scene_data["uid"] = uid
    
    file_path.write_text(json.dumps(scene_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return {
        "ok": True,
        "uid": uid,
        "pipeline": "SET → Фабула (quick)",
        "child_name": req.child_name,
        "file_path": str(file_path),
        "scene": scene_data,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# СТАТИСТИКА И ЗДОРОВЬЕ
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/stats")
def stats():
    with sqlite3.connect(BEACON_DB) as conn:
        devices   = conn.execute("SELECT COUNT(DISTINCT device_id) FROM sync_log").fetchone()[0]
        syncs     = conn.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0]
        generated = conn.execute("SELECT COUNT(*) FROM generated_scenes").fetchone()[0]
        top_tags  = conn.execute(
            "SELECT tag, COUNT(*) as c FROM aggregate_tags GROUP BY tag ORDER BY c DESC LIMIT 10"
        ).fetchall()
    
    registry = load_registry()
    
    return {
        "total_devices": devices,
        "total_syncs": syncs,
        "total_generated_books": generated,
        "total_profiles": len(registry.get("profiles", [])),
        "top_tags": [{"tag": r[0], "count": r[1]} for r in top_tags],
    }


@app.get("/health")
def health():
    """Проверка здоровья."""
    agents_available = 0
    if MODULES_PATH.exists():
        for d in MODULES_PATH.iterdir():
            if d.is_dir() and d.name.startswith("A"):
                agents_available += 1
    
    registry = load_registry()
    
    return {
        "status": "ok",
        "version": "5.0.0",
        "protocol": "v2.0",
        "model": OPENROUTER_MODEL,
        "api_key_set": bool(OPENROUTER_API_KEY),
        "studio_root": str(STUDIO_ROOT),
        "modules_path": str(MODULES_PATH),
        "agents_available": agents_available,
        "books_dir": str(BOOKS_DIR),
        "registry_profiles": len(registry.get("profiles", [])),
    }


# ─── ИНИЦИАЛИЗАЦИЯ БД ───────────────────────────────────────────────────────

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
            CREATE TABLE IF NOT EXISTS llm_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                total_requests INTEGER DEFAULT 0,
                cache_hits INTEGER DEFAULT 0,
                estimated_tokens INTEGER DEFAULT 0,
                ts TEXT NOT NULL
            );
        """)

init_db()


# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    registry = load_registry()
    print("🚀 Живая Книга — Единый Сервер v5.0 (Реестр Судеб)")
    print(f"🤖 Модель: {OPENROUTER_MODEL}")
    print(f"📚 Студия: {STUDIO_ROOT}")
    print(f"📖 Книги:  {BOOKS_DIR}")
    print(f"🆔 Профилей в реестре: {len(registry.get('profiles', []))}")
    print(f"🔑 API Key: {'✅' if OPENROUTER_API_KEY else '❌'}")
    uvicorn.run(app, host="0.0.0.0", port=8001)

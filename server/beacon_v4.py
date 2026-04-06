"""
beacon.py v5.1 — Единый сервер Живой Книги (Живая Память)
============================================================
Новое в v5.1: free_talk пишет в biography в реальном времени,
автосоздание basket.json, live session tracking.

v5.0: uid-маршрутизация, registry.json, biography writer
v4.0: Ночной Маяк + 18-агентный пайплайн + Автодоставка

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

app = FastAPI(title="Живая Книга — Единый Сервер v5.1 (Живая Память)", version="5.1.0")

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
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    empty = {"version": "1.0", "updated_at": datetime.now().isoformat(), "profiles": []}
    save_registry(empty)
    return empty

def save_registry(registry: dict):
    registry["updated_at"] = datetime.now().isoformat()
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

def generate_uid() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    registry = load_registry()
    today_count = sum(1 for p in registry["profiles"] if p["uid"].startswith(f"LB-{today}"))
    return f"LB-{today}-{today_count + 1:04d}"

def resolve_uid(uid: str) -> Optional[Path]:
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            folder = BOOKS_DIR / profile["folder"]
            if folder.exists():
                return folder
    return None

def get_profile_by_uid(uid: str) -> Optional[dict]:
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            return profile
    return None

def find_uid_by_name(child_name: str) -> Optional[str]:
    registry = load_registry()
    target = child_name.lower()
    for profile in registry.get("profiles", []):
        if profile.get("alias", "").lower() == target:
            return profile["uid"]
        if profile.get("folder", "").lower() == target:
            return profile["uid"]
    return None

def ensure_registry_entry(child_name: str, age_group: str = "7-12") -> str:
    existing_uid = find_uid_by_name(child_name)
    if existing_uid:
        return existing_uid
    uid = generate_uid()
    registry = load_registry()
    folder = child_name
    child_dir = _find_child_folder(child_name)
    if child_dir:
        folder = child_dir.name
    registry["profiles"].append({
        "uid": uid, "alias": child_name, "folder": folder,
        "age_group": age_group, "created_at": datetime.now().strftime("%Y-%m-%d"),
        "last_activity": datetime.now().isoformat(),
        "history_file": "biography.json", "device_ids": [], "status": "active",
    })
    save_registry(registry)
    print(f"[REGISTRY] ✅ Создан профиль: {uid} → {folder} (alias: {child_name})")
    return uid

def update_last_activity(uid: str):
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            profile["last_activity"] = datetime.now().isoformat()
            save_registry(registry)
            return


# ═══════════════════════════════════════════════════════════════════════════════
# BIOGRAPHY WRITER (Историческая Память) — §12
# ═══════════════════════════════════════════════════════════════════════════════

def _load_bio(folder: Path, uid: str, alias: str = "Ребёнок") -> dict:
    """Загружает или создаёт biography.json."""
    bio_path = folder / "biography.json"
    if bio_path.exists():
        bio = json.loads(bio_path.read_text(encoding="utf-8"))
    else:
        bio = {
            "uid": uid, "child_name": alias,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "total_stories": 0, "memory_depth": "infinite",
            "karmic_trail": [], "character_bonds": {},
            "world_knowledge": [], "emotional_milestones": [],
            "psychological_patterns": [], "live_dialogues": [],
        }
    bio.setdefault("uid", uid)
    bio.setdefault("memory_depth", "infinite")
    bio.setdefault("live_dialogues", [])
    return bio

def _save_bio(folder: Path, bio: dict):
    """Сохраняет biography.json."""
    bio["updated_at"] = datetime.now().isoformat()
    bio["total_stories"] = len(bio.get("karmic_trail", []))
    (folder / "biography.json").write_text(
        json.dumps(bio, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def update_biography(uid: str, entry: dict):
    """Добавляет запись в karmic_trail (после генерации книги)."""
    folder = resolve_uid(uid)
    if not folder:
        print(f"[BIOGRAPHY] ⚠️ Папка не найдена для uid={uid}")
        return
    profile = get_profile_by_uid(uid)
    alias = profile.get("alias", "Ребёнок") if profile else "Ребёнок"
    bio = _load_bio(folder, uid, alias)
    bio["karmic_trail"].append(entry)
    for char in entry.get("characters_met", []):
        bio["character_bonds"][char] = bio["character_bonds"].get(char, 0) + 1
    _save_bio(folder, bio)
    print(f"[BIOGRAPHY] ✅ karmic_trail: {len(bio['karmic_trail'])} записей для {alias}")

def append_choices_to_biography(uid: str, choices: list, tags: list):
    """Добавляет choices/tags из NightBeacon."""
    folder = resolve_uid(uid)
    if not folder:
        return
    profile = get_profile_by_uid(uid)
    bio = _load_bio(folder, uid, profile.get("alias", "") if profile else "")
    if not bio.get("karmic_trail"):
        return
    last = bio["karmic_trail"][-1]
    existing = last.get("choices_made", [])
    existing.extend([{"choice_id": c, "source": "nightbeacon"} for c in choices])
    last["choices_made"] = existing
    for tag in tags:
        if tag not in bio.get("psychological_patterns", []):
            bio.setdefault("psychological_patterns", []).append(tag)
    _save_bio(folder, bio)


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE MEMORY — v5.1: запись из free_talk в реальном времени
# ═══════════════════════════════════════════════════════════════════════════════

def live_record_dialogue(child_name: str, uid: Optional[str],
                         scene_id: str, child_text: str, ai_text: str):
    """
    Записывает каждый диалог Искорка↔Ребёнок в biography.json → live_dialogues.
    Вызывается из POST /api/free_talk после каждого ответа LLM.
    """
    # Находим папку
    folder = None
    if uid:
        folder = resolve_uid(uid)
    if not folder:
        folder = _find_child_folder(child_name)
    if not folder:
        return  # нет папки — не записываем

    resolved_uid = uid or find_uid_by_name(child_name) or "unknown"
    profile = get_profile_by_uid(resolved_uid) if resolved_uid != "unknown" else None
    alias = profile.get("alias", child_name) if profile else child_name

    bio = _load_bio(folder, resolved_uid, alias)

    # Добавляем запись в live_dialogues
    bio["live_dialogues"].append({
        "ts": datetime.now().isoformat(),
        "scene_id": scene_id,
        "child_said": child_text[:200],
        "iskra_said": ai_text[:200],
    })

    # Обрезаем до 500 последних (не раздувать файл)
    if len(bio["live_dialogues"]) > 500:
        bio["live_dialogues"] = bio["live_dialogues"][-500:]

    # Извлекаем имена персонажей из текста ребёнка (character_bonds)
    KNOWN_CHARS = ["искорка", "эйрик", "лока", "петя", "петей"]
    text_lower = child_text.lower()
    for char_name in KNOWN_CHARS:
        if char_name in text_lower:
            # Нормализуем имя
            norm = char_name.capitalize().replace("Петей", "Петя")
            bio["character_bonds"][norm] = bio["character_bonds"].get(norm, 0) + 1

    _save_bio(folder, bio)
    print(f"[LIVE] 📝 {alias} в {scene_id}: «{child_text[:40]}...»")


def ensure_basket(child_name: str, uid: Optional[str], scene_id: str, ai_text: str):
    """
    Автосоздание basket.json если его нет.
    Заполняет минимальную структуру для Корзинки Даров в Кабинете.
    """
    folder = None
    if uid:
        folder = resolve_uid(uid)
    if not folder:
        folder = _find_child_folder(child_name)
    if not folder:
        return

    basket_path = folder / "basket.json"
    if basket_path.exists():
        return  # уже есть

    basket = {
        "created_at": datetime.now().isoformat(),
        "story_theme": "Сад Памяти",
        "task_context": "Диалог с Искоркой",
        "parent_insights": [
            "Ребёнок активно взаимодействует с Искоркой",
            "Диалог идёт через голосовой интерфейс",
        ],
        "bridge_to_reality": {
            "conversation_starters": [
                f"Спроси у {child_name}: что тебе сегодня рассказала Искорка?",
                f"Попробуйте вместе вспомнить любимый момент дня.",
            ],
            "activities": [
                "Нарисуйте вместе Сад Памяти — каждый цветок = одно воспоминание",
                "Перед сном вспомните 3 хороших момента за день",
            ],
        },
        "next_story_hints": {
            "suggested_theme": "Дружба и новые знакомства",
        },
    }

    basket_path.write_text(
        json.dumps(basket, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[BASKET] ✅ Создан basket.json для {child_name}")


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════════════════════

def load_agent_prompt(agent_id: str) -> str:
    for prompt_path in [
        MODULES_PATH / agent_id / "forge" / "prompt.md",
        MODULES_PATH / agent_id / "prompt.md",
    ]:
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
    return f"Ты агент {agent_id}. Выполни задачу качественно."

def load_agent_anchor(agent_id: str) -> str:
    anchor_path = MODULES_PATH / agent_id / "core" / "anchor_points.md"
    if anchor_path.exists():
        return anchor_path.read_text(encoding="utf-8")
    return ""

async def call_openrouter(system_prompt: str, user_prompt: str,
                           max_tokens: int = 4000, temperature: float = 0.7) -> str:
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
                "model": OPENROUTER_MODEL, "max_tokens": max_tokens,
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
    match = re.search(r"SYSTEM_JSON_START\s*(.*?)\s*SYSTEM_JSON_END", raw, re.DOTALL)
    if match:
        try: return json.loads(match.group(1).strip())
        except json.JSONDecodeError: pass
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        try: return json.loads(match.group(1).strip())
        except json.JSONDecodeError: pass
    for start in [raw.find("{"), raw.find("[")]:
        if start >= 0:
            try: return json.loads(raw[start:])
            except json.JSONDecodeError: pass
    return {}

def _find_child_folder(name: str) -> Optional[Path]:
    if not BOOKS_DIR.exists(): return None
    for d in BOOKS_DIR.iterdir():
        if d.is_dir() and d.name.lower() == name.lower():
            return d
    return None

def _find_book_path(child_name: str) -> Optional[Path]:
    candidates = [
        BOOKS_DIR / child_name / "book.json",
        BOOKS_DIR / child_name.lower() / "book.json",
        BOOKS_DIR / child_name.lower().replace(" ", "_") / "book.json",
    ]
    for p in candidates:
        if p.exists(): return p
    if BOOKS_DIR.exists():
        target_lower = child_name.lower().replace(" ", "_")
        for entry in BOOKS_DIR.iterdir():
            if entry.is_dir() and entry.name.lower().replace(" ", "_") == target_lower:
                p = entry / "book.json"
                if p.exists(): return p
    return None

def _find_book_path_by_uid(uid: str) -> Optional[Path]:
    folder = resolve_uid(uid)
    if folder:
        book_path = folder / "book.json"
        if book_path.exists(): return book_path
    return None

def _find_stories_folder(child_name: str) -> Optional[Path]:
    stories_root = BASE_DIR / "stories"
    if not stories_root.exists(): return None
    direct = stories_root / child_name
    if direct.exists(): return direct
    lower = stories_root / child_name.lower().replace(" ", "_")
    if lower.exists(): return lower
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
    "A01", "A02", "A03", "A04",
    "A05", "A06", "A07", "A08",
    "A09", "A10", "A11", "A12",
    "A13", "A14", "A15", "A16",
]
MAX_REVISION_LOOPS = 3

async def run_genesis(master_brief: dict) -> tuple[str, dict]:
    brief_json = json.dumps(master_brief, ensure_ascii=False, indent=2)
    revision_notes = ""
    for loop in range(MAX_REVISION_LOOPS):
        a00_prompt = load_agent_prompt("A00")
        a00_anchor = load_agent_anchor("A00")
        user_ctx = f"MASTER BRIEF:\n{brief_json}\n"
        if revision_notes: user_ctx += f"\n⚠️ ЗАМЕЧАНИЯ:\n{revision_notes}\n"
        if a00_anchor: user_ctx = a00_anchor + "\n\n" + user_ctx
        print(f"  [GENESIS] A00 (петля {loop+1}/{MAX_REVISION_LOOPS})...")
        a00_raw = await call_openrouter(a00_prompt, user_ctx)
        a00a_prompt = load_agent_prompt("A00a")
        a00a_anchor = load_agent_anchor("A00a")
        a00a_ctx = f"РЕЗУЛЬТАТ ФАБУЛЫ:\n{a00_raw}\n\nBRIEF:\n{brief_json}"
        if a00a_anchor: a00a_ctx = a00a_anchor + "\n\n" + a00a_ctx
        print(f"  [GENESIS] A00a Вера Душа...")
        a00a_raw = await call_openrouter(a00a_prompt, a00a_ctx)
        a00a_meta = extract_json_from_response(a00a_raw)
        my_output = a00a_meta.get("my_output", a00a_meta)
        verdict = my_output.get("verdict", "APPROVED").upper()
        if "APPROVED" in verdict:
            print(f"  [GENESIS] ✅ Одобрено (петля {loop+1})")
            return a00_raw, a00a_meta
        revision_notes = my_output.get("revision_notes", "")
        recs = my_output.get("recommendations", [])
        if recs: revision_notes += "\n" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(recs))
        print(f"  [GENESIS] 🔄 REVISION: {revision_notes[:100]}...")
    return a00_raw, {"my_output": {"verdict": "APPROVED_WITH_NOTES"}}

async def run_pipeline_agent(agent_id: str, chain_context: str, master_brief: dict) -> str:
    system_prompt = load_agent_prompt(agent_id)
    anchor = load_agent_anchor(agent_id)
    user_ctx = ""
    if anchor: user_ctx += anchor + "\n\n"
    user_ctx += f"MASTER BRIEF:\n{json.dumps(master_brief, ensure_ascii=False, indent=2)}\n\n"
    user_ctx += f"ПРЕДЫДУЩИЕ:\n{chain_context[-6000:]}\n"
    return await call_openrouter(system_prompt, user_ctx, max_tokens=4000)

async def run_full_pipeline(master_brief: dict) -> dict:
    results = {}
    print("[PIPELINE] === GENESIS ===")
    a00_raw, a00a_meta = await run_genesis(master_brief)
    results["A00"] = a00_raw
    results["A00a"] = a00a_meta
    chain = f"--- A00 ---\n{a00_raw[:3000]}\n--- A00a ---\nВердикт: {a00a_meta.get('my_output',{}).get('verdict','APPROVED')}\n"
    for agent_id in PIPELINE_AGENTS:
        prompt = load_agent_prompt(agent_id)
        if prompt.startswith("Ты агент") and len(prompt) < 100:
            results[agent_id] = {"status": "stub"}
            continue
        phase = "PRE" if agent_id <= "A04" else "PROD" if agent_id <= "A08" else "POST" if agent_id <= "A12" else "DELIVERY"
        print(f"  [PIPELINE] {phase} → {agent_id}...")
        try:
            raw = await run_pipeline_agent(agent_id, chain, master_brief)
            results[agent_id] = raw
            meta = extract_json_from_response(raw)
            mo = meta.get("my_output", {})
            chain += f"\n--- {agent_id} ---\n{json.dumps(mo, ensure_ascii=False)[:1500] if mo else raw[:1000]}\n"
        except Exception as e:
            print(f"  [PIPELINE] ❌ {agent_id}: {e}")
            results[agent_id] = {"status": "error", "error": str(e)}
    return results

def extract_book_package(results: dict) -> dict:
    a16_raw = results.get("A16", "")
    if isinstance(a16_raw, dict): return a16_raw
    package = {}
    for fn, content in re.findall(r'### === FILE:\s*(.+?)\s*===\s*\n```json\s*\n(.*?)\n```', a16_raw, re.DOTALL):
        try: package[fn.strip()] = json.loads(content)
        except: package[fn.strip()] = content
    if not package:
        meta = extract_json_from_response(a16_raw)
        if meta: package = meta
    return package

def save_book_package(uid: str, child_name: str, package: dict, master_brief: dict) -> Path:
    folder = resolve_uid(uid)
    if not folder:
        folder = BOOKS_DIR / child_name.lower().replace(" ", "_")
    folder.mkdir(parents=True, exist_ok=True)
    for filename, content in package.items():
        fp = folder / filename
        fp.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, (dict, list)):
            if filename == "book.json" and isinstance(content, dict): content["uid"] = uid
            fp.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            fp.write_text(str(content), encoding="utf-8")
    (folder / "_master_brief.json").write_text(json.dumps(master_brief, ensure_ascii=False, indent=2), encoding="utf-8")
    profile = get_profile_by_uid(uid)
    pk = profile["folder"].lower().replace(" ", "_") if profile else child_name.lower().replace(" ", "_")
    pd = BASE_DIR / "stories" / pk
    pd.mkdir(parents=True, exist_ok=True)
    sid = f"story_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    (pd / f"{sid}_pending.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


# ═══════════════════════════════════════════════════════════════════════════════
# ЭНДПОИНТЫ — СХЕМЫ
# ═══════════════════════════════════════════════════════════════════════════════

class GenerateRequest(BaseModel):
    child_name: str
    child_age: Optional[str] = "7-12"
    task_context: str
    uid: Optional[str] = None

class FreeTalkRequest(BaseModel):
    child_text: str
    scene_id: str
    chapter_id: str = ""
    child_name: str = "Ребёнок"
    uid: Optional[str] = None
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
    uid: Optional[str] = None
    events: list[BeaconEvent]
    llm_stats: Optional[dict] = None


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY ENDPOINTS (§10)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/registry")
async def get_registry():
    return load_registry()

@app.get("/api/registry/{uid}")
async def get_registry_profile(uid: str):
    profile = get_profile_by_uid(uid)
    if not profile: raise HTTPException(404, f"Профиль {uid} не найден")
    return profile


# ═══════════════════════════════════════════════════════════════════════════════
# ГЕНЕРАЦИЯ КНИГИ
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/studio/generate")
async def generate_book(req: GenerateRequest):
    print(f"\n{'='*60}\n📖 ЗАКАЗ: {req.child_name}, {req.child_age}, {req.task_context}\n{'='*60}")
    uid = req.uid or ensure_registry_entry(req.child_name, req.child_age or "7-12")
    print(f"  🆔 uid: {uid}")
    print("\n[1/4] SET...")
    set_raw = await call_openrouter(SET_SYSTEM_PROMPT,
        f"Ребёнок: {req.child_name}, {req.child_age}. Задача: {req.task_context}\nВыдай MASTER BRIEF.",
        max_tokens=800)
    master_brief = extract_json_from_response(set_raw)
    if not master_brief: raise HTTPException(422, f"SET не вернул JSON: {set_raw[:300]}")
    master_brief.setdefault("child_name", req.child_name)
    master_brief.setdefault("child_age", req.child_age)
    master_brief.setdefault("task_context", req.task_context)
    master_brief["uid"] = uid
    print("\n[2/4] ПАЙПЛАЙН...")
    results = await run_full_pipeline(master_brief)
    print("\n[3/4] СОХРАНЕНИЕ...")
    package = extract_book_package(results)
    book_dir = save_book_package(uid, req.child_name, package, master_brief) if package else None
    print("\n[4/4] BIOGRAPHY...")
    update_biography(uid, {
        "date": datetime.now().isoformat(),
        "story_id": f"story_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "theme": master_brief.get("theme", ""),
        "task_context": master_brief.get("task_context", ""),
        "emotional_goal": master_brief.get("emotional_goal", ""),
        "characters_met": [], "choices_made": [],
        "key_message": master_brief.get("purpose", ""),
        "world": master_brief.get("world", ""),
    })
    update_last_activity(uid)
    with sqlite3.connect(BEACON_DB) as conn:
        conn.execute("INSERT INTO generated_scenes (child_name,child_age,task_context,set_brief,generated_at,file_path) VALUES (?,?,?,?,?,?)",
            (req.child_name, req.child_age, req.task_context, json.dumps(master_brief, ensure_ascii=False), datetime.now().isoformat(), str(book_dir) if book_dir else ""))
    print(f"\n🎉 ГОТОВО! uid={uid}\n")
    return {"ok": True, "uid": uid, "child_name": req.child_name, "book_dir": str(book_dir) if book_dir else None,
            "agents_completed": len([r for r in results.values() if not (isinstance(r, dict) and r.get("status") in ("stub","error"))]),
            "package_files": list(package.keys()) if package else [], "master_brief": master_brief}


# ═══════════════════════════════════════════════════════════════════════════════
# FREE TALK — v5.1: ЖИВАЯ ЗАПИСЬ
# ═══════════════════════════════════════════════════════════════════════════════

SAFETY_KEYWORDS = ["помогите", "спасите", "умереть", "убить", "кровь", "наркотик", "секс", "порно"]

@app.post("/api/free_talk")
async def free_talk(req: FreeTalkRequest):
    """Гибридный диалог. v5.1: каждый диалог пишется в biography в реальном времени."""
    text_lower = req.child_text.lower()
    if any(kw in text_lower for kw in SAFETY_KEYWORDS):
        return {"text": "Давай поговорим о чём-то другом, хорошо?", "color": "yellow", "cached": False, "blocked": True}

    prompt = f"""Ты — Искорка, тёплый спутник ребёнка в мире Грондхейм.
Ребёнок {req.child_name} в сцене {req.scene_id} сказал: «{req.child_text}»

Ответь по методу Гиппенрейтер:
- Не давай готовых решений.
- Отрази чувство ребёнка.
- Задай направляющий вопрос.
- Максимум 2 предложения.
- Тон: тёплый, любопытный, застенчивый."""

    ai_text = "Я тебя слышу... Расскажи ещё раз?"
    try:
        ai_text = await call_openrouter(
            "Ты — Искорка. Отвечай ТОЛЬКО текст для ребёнка, без JSON.",
            prompt, max_tokens=150, temperature=0.8)
    except Exception as e:
        print(f"[FREE_TALK] LLM error: {e}")

    # ═══ v5.1: ЖИВАЯ ЗАПИСЬ ═══
    try:
        live_record_dialogue(req.child_name, req.uid, req.scene_id, req.child_text, ai_text)
        ensure_basket(req.child_name, req.uid, req.scene_id, ai_text)
    except Exception as e:
        print(f"[LIVE] ⚠️ Ошибка записи: {e}")

    return {"text": ai_text, "color": "cyan", "cached": False}


# ═══════════════════════════════════════════════════════════════════════════════
# UID-МАРШРУТЫ (v2)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/beacon/uid/{uid}/meta")
async def get_book_meta_by_uid(uid: str):
    book_path = _find_book_path_by_uid(uid)
    if not book_path: raise HTTPException(404, f"Книга для uid='{uid}' не найдена")
    data = json.loads(book_path.read_text(encoding="utf-8"))
    update_last_activity(uid)
    profile = get_profile_by_uid(uid)
    data["_alias"] = profile.get("alias", "") if profile else ""
    return data

@app.get("/api/beacon/uid/{uid}/chapters/{chapter_id}")
async def get_chapter_by_uid(uid: str, chapter_id: str):
    folder = resolve_uid(uid)
    if not folder: raise HTTPException(404, f"Папка для uid='{uid}' не найдена")
    chapter_file = folder / "chapters" / f"{chapter_id}.json"
    if not chapter_file.exists():
        cd = folder / "chapters"
        if cd.exists():
            for f in cd.iterdir():
                if f.stem.lower() == chapter_id.lower(): chapter_file = f; break
    if not chapter_file.exists(): raise HTTPException(404, f"Глава '{chapter_id}' не найдена")
    data = json.loads(chapter_file.read_text(encoding="utf-8"))
    update_last_activity(uid)
    return data

@app.get("/api/beacon/uid/{uid}/stories")
async def get_stories_by_uid(uid: str):
    profile = get_profile_by_uid(uid)
    if not profile: raise HTTPException(404)
    sd = BASE_DIR / "stories" / profile["folder"].lower().replace(" ", "_")
    if not sd.exists(): return []
    return [{"story_id": f.stem.replace("_pending",""), "title": json.loads(f.read_text(encoding="utf-8")).get("title","?"),
             "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat()} for f in sd.glob("*_pending.json")]

@app.get("/api/parent/uid/{uid}/{category}")
async def get_parent_data_by_uid(uid: str, category: str):
    folder = resolve_uid(uid)
    if not folder: raise HTTPException(404, f"Папка для uid='{uid}' не найдена")
    tf = folder / f"{category}.json"
    if not tf.exists(): raise HTTPException(404, f"{category}.json не найден (uid={uid})")
    return json.loads(tf.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════════
# ОБРАТНАЯ СОВМЕСТИМОСТЬ (v1)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/beacon/stories/{child_name}/meta")
async def get_book_meta(child_name: str):
    bp = _find_book_path(child_name)
    if not bp: raise HTTPException(404)
    ensure_registry_entry(child_name)
    return json.loads(bp.read_text(encoding="utf-8"))

@app.get("/api/beacon/stories/{child_name}/chapters/{chapter_id}")
async def get_chapter(child_name: str, chapter_id: str):
    bp = _find_book_path(child_name)
    if not bp: raise HTTPException(404)
    cf = bp.parent / "chapters" / f"{chapter_id}.json"
    if not cf.exists():
        cd = bp.parent / "chapters"
        if cd.exists():
            for f in cd.iterdir():
                if f.stem.lower() == chapter_id.lower(): cf = f; break
    if not cf.exists(): raise HTTPException(404)
    return json.loads(cf.read_text(encoding="utf-8"))

@app.get("/api/beacon/stories/{child_name}")
async def get_stories_for_child(child_name: str):
    sd = _find_stories_folder(child_name)
    if not sd: return []
    return [{"story_id": f.stem.replace("_pending",""), "title": json.loads(f.read_text(encoding="utf-8")).get("title","?"),
             "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat()} for f in sd.glob("*_pending.json")]

@app.get("/api/parent/{category}/{child_name}")
async def get_parent_data(category: str, child_name: str):
    cd = _find_child_folder(child_name)
    if not cd: raise HTTPException(404)
    tf = cd / f"{category}.json"
    if not tf.exists(): raise HTTPException(404)
    return json.loads(tf.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════════
# НОЧНОЙ МАЯК
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/beacon")
async def receive_beacon(batch: BeaconBatch):
    with sqlite3.connect(BEACON_DB) as conn:
        conn.execute("INSERT INTO sync_log (device_id,session_id,synced_at,event_count) VALUES (?,?,?,?)",
            (batch.device_id, batch.session_id, batch.synced_at, len(batch.events)))
        choices, tags = [], []
        for ev in batch.events:
            ts = datetime.utcfromtimestamp(ev.ts/1000).isoformat()
            if ev.type == "tag" and ev.tag:
                conn.execute("INSERT INTO aggregate_tags (device_id,tag,ts) VALUES (?,?,?)", (batch.device_id, ev.tag, ts))
                tags.append(ev.tag)
            elif ev.type == "choice" and ev.choice_id:
                conn.execute("INSERT INTO aggregate_choices (device_id,choice_id,ts) VALUES (?,?,?)", (batch.device_id, ev.choice_id, ts))
                choices.append(ev.choice_id)
        if batch.llm_stats:
            conn.execute("INSERT OR REPLACE INTO llm_metrics (device_id,session_id,total_requests,cache_hits,estimated_tokens,ts) VALUES (?,?,?,?,?,?)",
                (batch.device_id, batch.session_id, batch.llm_stats.get("total_requests",0), batch.llm_stats.get("cache_hits",0), batch.llm_stats.get("estimated_tokens",0), batch.synced_at))
    if batch.uid and (choices or tags):
        append_choices_to_biography(batch.uid, choices, tags)
    print(f"[МАЯК] Батч: {len(batch.events)} событий{f' uid={batch.uid}' if batch.uid else ''}")
    return {"ok": True, "received": len(batch.events)}


# ═══════════════════════════════════════════════════════════════════════════════
# QUICK SCENE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/studio/quick_scene")
async def quick_scene(req: GenerateRequest):
    uid = req.uid or ensure_registry_entry(req.child_name, req.child_age or "7-12")
    set_raw = await call_openrouter(SET_SYSTEM_PROMPT, f"Ребёнок: {req.child_name}, {req.child_age}. Задача: {req.task_context}", max_tokens=600)
    mb = extract_json_from_response(set_raw)
    mb["uid"] = uid
    fabula_raw = await call_openrouter(load_agent_prompt("A00"), f"MASTER BRIEF:\n{json.dumps(mb, ensure_ascii=False, indent=2)}", max_tokens=2000)
    PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
    fp = PERSONAL_DIR / f"{req.child_name.lower().replace(' ','_')}_personal_scene.json"
    sd = extract_json_from_response(fabula_raw) or {"raw": fabula_raw}
    sd["_master_brief"] = mb; sd["uid"] = uid
    fp.write_text(json.dumps(sd, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "uid": uid, "scene": sd}


# ═══════════════════════════════════════════════════════════════════════════════
# СТАТИСТИКА И ЗДОРОВЬЕ
# ═══════════════════════════════════════════════════════════════════════════════

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
    return {"status": "ok", "version": "5.1.0", "protocol": "v2.0", "model": OPENROUTER_MODEL,
            "api_key_set": bool(OPENROUTER_API_KEY), "agents_available": agents,
            "books_dir": str(BOOKS_DIR), "registry_profiles": len(registry.get("profiles", []))}


# ─── ИНИЦИАЛИЗАЦИЯ БД ───────────────────────────────────────────────────────

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
    print("🚀 Живая Книга — Сервер v5.1 (Живая Память)")
    print(f"🤖 {OPENROUTER_MODEL} | 📖 {BOOKS_DIR} | 🆔 {len(registry.get('profiles',[]))} профилей")
    uvicorn.run(app, host="0.0.0.0", port=8001)

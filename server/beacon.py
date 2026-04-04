"""
beacon.py v4.0 — Единый сервер Живой Книги
============================================
Объединяет: Ночной Маяк + Полный 18-агентный пайплайн + Автодоставка

Поток:
  Родительский кабинет → POST /api/studio/generate
    → SET (маршрутизация)
    → A00 Фабула Фейн (история)
    → A00a Вера Душа (ревизия, макс 3 петли)
    → A01-A16 (полный пайплайн)
    → Book Package → books/{child_name}/ (автодоставка для Искорки)

  Искорка → GET /api/beacon/stories/{child_name}
    → забирает pending-книги

  Искорка → POST /beacon
    → ночной батч метрик

  Искорка → POST /api/free_talk
    → гибридный диалог (LLM с кэшем)

Запуск:
    pip install fastapi uvicorn httpx python-dotenv
    uvicorn beacon:app --host 0.0.0.0 --port 8001
"""

import json
import re
import hashlib
import sqlite3
import os
import httpx
from post_run import run_post_reflection
from datetime import datetime
from pathlib import Path
from functools import lru_cache
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Живая Книга — Единый Сервер v4.0", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── ПУТИ ────────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
BOOKS_DIR    = BASE_DIR / ".." / "books"       # LIVING_BOOK_APP/books/
PERSONAL_DIR = BOOKS_DIR / "personal"
BEACON_DB    = BASE_DIR / "beacon.db"

# ─── OPENROUTER ──────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")

# ─── ПРОМПТЫ АГЕНТОВ ─────────────────────────────────────────────────────────
# Путь к студии — для загрузки промптов из modules/living_book/
STUDIO_ROOT = Path(os.getenv("STUDIO_ROOT", str(BASE_DIR / ".." / ".." / "студия 2")))
MODULES_PATH = STUDIO_ROOT / "studio" / "modules" / "living_book"


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

# Порядок агентов (без A00/A00a — они обрабатываются отдельно в ревизионной петле)
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
        # ── A00: Фабула Фейн ──
        a00_prompt = load_agent_prompt("A00")
        a00_anchor = load_agent_anchor("A00")
        
        user_ctx = f"MASTER BRIEF:\n{brief_json}\n"
        if revision_notes:
            user_ctx += f"\n⚠️ ЗАМЕЧАНИЯ ОТ ВЕРЫ ДУШИ (исправь!):\n{revision_notes}\n"
        if a00_anchor:
            user_ctx = a00_anchor + "\n\n" + user_ctx
        
        print(f"  [GENESIS] A00 Фабула Фейн (петля {loop + 1}/{MAX_REVISION_LOOPS})...")
        a00_raw = await call_openrouter(a00_prompt, user_ctx)
        
        # ── A00a: Вера Душа ──
        a00a_prompt = load_agent_prompt("A00a")
        a00a_anchor = load_agent_anchor("A00a")
        
        a00a_ctx = f"РЕЗУЛЬТАТ ФАБУЛЫ ФЕЙН:\n{a00_raw}\n\nMASTER BRIEF:\n{brief_json}"
        if a00a_anchor:
            a00a_ctx = a00a_anchor + "\n\n" + a00a_ctx
        
        print(f"  [GENESIS] A00a Вера Душа...")
        a00a_raw = await call_openrouter(a00a_prompt, a00a_ctx)
        a00a_meta = extract_json_from_response(a00a_raw)
        
        # Проверяем вердикт
        my_output = a00a_meta.get("my_output", a00a_meta)
        verdict = my_output.get("verdict", "APPROVED").upper()
        
        if "APPROVED" in verdict:
            print(f"  [GENESIS] ✅ Вера одобрила (петля {loop + 1})")
            return a00_raw, a00a_meta
        
        # REVISION — собираем замечания для следующей петли
        revision_notes = my_output.get("revision_notes", "")
        recommendations = my_output.get("recommendations", [])
        if recommendations:
            revision_notes += "\n\nКонкретные исправления:\n"
            for i, rec in enumerate(recommendations, 1):
                revision_notes += f"{i}. {rec}\n"
        
        print(f"  [GENESIS] 🔄 REVISION (петля {loop + 1}): {revision_notes[:100]}...")
    
    # Исчерпали петли — пропускаем с пометкой
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
    """
    Полный 18-агентный пайплайн.
    Возвращает dict со всеми результатами.
    """
    results = {}
    
    # ── GENESIS: A00 + A00a (с ревизионной петлёй) ──
    print("[PIPELINE] === GENESIS ===")
    a00_raw, a00a_meta = await run_genesis(master_brief)
    results["A00"] = a00_raw
    results["A00a"] = a00a_meta
    
    # Строим chain context
    chain_context = f"--- A00 Фабула Фейн ---\n{a00_raw[:3000]}\n"
    chain_context += f"--- A00a Вера Душа ---\nВердикт: {a00a_meta.get('my_output', {}).get('verdict', 'APPROVED')}\n"
    
    # ── ОСНОВНОЙ ПАЙПЛАЙН: A01-A16 ──
    for agent_id in PIPELINE_AGENTS:
        # Проверяем есть ли промпт (не заглушка ли)
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
            
            # Добавляем в chain (ограничиваем размер)
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
    
    # Ищем JSON-блоки с файлами
    package = {}
    
    # Ищем === FILE: xxx === блоки
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
    
    # Если не нашли файловые блоки — ищем общий JSON
    if not package:
        meta = extract_json_from_response(a16_raw)
        if meta:
            package = meta
    
    return package


def save_book_package(child_name: str, package: dict, master_brief: dict) -> Path:
    """Сохраняет Book Package в books/{child_name}/ для Искорки."""
    safe_name = child_name.lower().replace(" ", "_")
    book_dir = BOOKS_DIR / safe_name
    book_dir.mkdir(parents=True, exist_ok=True)
    
    # Сохраняем каждый файл из пакета
    for filename, content in package.items():
        # Создаём поддиректории если нужно
        file_path = book_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        if isinstance(content, (dict, list)):
            file_path.write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        else:
            file_path.write_text(str(content), encoding="utf-8")
        
        print(f"  [SAVE] {file_path}")
    
    # Сохраняем мастер-бриф для истории
    brief_path = book_dir / "_master_brief.json"
    brief_path.write_text(
        json.dumps(master_brief, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    # Также сохраняем как pending для /api/beacon/stories
    pending_dir = BASE_DIR / "stories" / safe_name
    pending_dir.mkdir(parents=True, exist_ok=True)
    story_id = f"story_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    pending_path = pending_dir / f"{story_id}_pending.json"
    pending_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    return book_dir


# ═══════════════════════════════════════════════════════════════════════════════
# ЭНДПОИНТЫ
# ═══════════════════════════════════════════════════════════════════════════════

# ─── СХЕМЫ ───────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    child_name: str
    child_age: Optional[str] = "7-12"
    task_context: str

class FreeTalkRequest(BaseModel):
    child_text: str
    scene_id: str
    chapter_id: str = ""
    child_name: str = "Ребёнок"
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
    events: list[BeaconEvent]
    llm_stats: Optional[dict] = None


# ─── ГЕНЕРАЦИЯ КНИГИ (полный пайплайн) ──────────────────────────────────────

@app.post("/api/studio/generate")
async def generate_book(req: GenerateRequest):
    """
    Полный автономный конвейер:
    SET → A00 ↔ A00a → A01-A16 → Book Package → books/
    """
    print(f"\n{'='*60}")
    print(f"📖 ЗАКАЗ: {req.child_name}, {req.child_age}, {req.task_context}")
    print(f"{'='*60}")
    
    # ── ШАГ 1: SET ──
    print("\n[1/3] SET — маршрутизация...")
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
    
    # Дополняем бриф данными из запроса
    master_brief.setdefault("child_name", req.child_name)
    master_brief.setdefault("child_age", req.child_age)
    master_brief.setdefault("task_context", req.task_context)
    print(f"  ✅ MASTER BRIEF получен")
    
    # ── ШАГ 2: ПОЛНЫЙ ПАЙПЛАЙН ──
    print("\n[2/3] ПАЙПЛАЙН — 18 агентов...")
    results = await run_full_pipeline(master_brief)
    print(f"  ✅ Пайплайн завершён ({len(results)} агентов)")

    print("\n[2.5/3] РЕФЛЕКСИЯ — Линза Стат + Тьютор Линк + Хронос Мемо...")
    try:
        reflection = run_post_reflection(
            child_name=req.child_name,
            books_dir=BOOKS_DIR,
            pipeline_results=results,
            master_brief=master_brief,
            studio_root=STUDIO_ROOT,
        )
        print(f"  ✅ Рефлексия завершена")
    except Exception as e:
        print(f"  ⚠️ Рефлексия не удалась: {e}")
        reflection = {}
    
    # ── ШАГ 3: СОХРАНЕНИЕ ──
    print("\n[3/3] СОХРАНЕНИЕ Book Package...")
    package = extract_book_package(results)
    
    if package:
        book_dir = save_book_package(req.child_name, package, master_brief)
        print(f"  ✅ Сохранено в {book_dir}")
    else:
        print(f"  ⚠️ Не удалось извлечь Book Package из A16")
        book_dir = None
    
    # Сохраняем в БД
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
    print(f"🎉 ГОТОВО! Книга для «{req.child_name}» создана.")
    print(f"{'='*60}\n")
    
    return {
        "ok": True,
        "pipeline": "SET → A00 ↔ A00a → A01-A16",
        "child_name": req.child_name,
        "reflection": reflection,
        "book_dir": str(book_dir) if book_dir else None,
        "agents_completed": len([r for r in results.values() if not (isinstance(r, dict) and r.get("status") == "stub")]),
        "agents_stubbed": len([r for r in results.values() if isinstance(r, dict) and r.get("status") == "stub"]),
        "package_files": list(package.keys()) if package else [],
        "master_brief": master_brief,
    }


# ─── FREE TALK (гибридный диалог для Искорки) ───────────────────────────────

SAFETY_KEYWORDS = [
    "помогите", "спасите", "умереть", "убить", "кровь",
    "наркотик", "секс", "порно",
]

@lru_cache(maxsize=1000)
def _cached_llm_response(text_hash: str, scene_id: str) -> str:
    """Серверный кэш LLM-ответов (в памяти процесса)."""
    # Заглушка — реальный вызов в free_talk
    return ""

@app.post("/api/free_talk")
async def free_talk(req: FreeTalkRequest):
    """
    Гибридный диалог для Искорки.
    Проверка безопасности → LLM → кэш.
    """
    # Safety check
    text_lower = req.child_text.lower()
    if any(kw in text_lower for kw in SAFETY_KEYWORDS):
        return {
            "text": "Давай поговорим о чём-то другом, хорошо?",
            "color": "yellow",
            "cached": False,
            "blocked": True,
        }
    
    # Кэш
    text_hash = hashlib.md5(f"{req.child_text}:{req.scene_id}".encode()).hexdigest()
    cached = _cached_llm_response(text_hash, req.scene_id)
    if cached:
        return {"text": cached, "color": "cyan", "cached": True}
    
    # LLM
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
        
        # Обновляем кэш (хак: вызываем с результатом)
        _cached_llm_response.__wrapped__(text_hash, req.scene_id)
        # TODO: proper cache update
        
        return {"text": response, "color": "cyan", "cached": False}
    
    except Exception as e:
        return {
            "text": "Я тебя слышу... Расскажи ещё раз?",
            "color": "blue",
            "cached": False,
            "error": str(e),
        }


# ─── ИСКОРКА ЗАБИРАЕТ КНИГИ ─────────────────────────────────────────────────

@app.get("/api/beacon/stories/{child_name}")
async def get_stories(child_name: str):
    """Искорка забирает pending-книги."""
    safe_name = child_name.lower().replace(" ", "_")
    stories_dir = BASE_DIR / "stories" / safe_name
    
    if not stories_dir.exists():
        return []
    
    pending = []
    for f in stories_dir.iterdir():
        if f.name.endswith("_pending.json"):
            with open(f, "r", encoding="utf-8") as fp:
                story = json.load(fp)
            
            pending.append({
                "story_id": f.name.replace("_pending.json", ""),
                "title": story.get("book.json", {}).get("title", story.get("book", {}).get("title", "Новая история")),
                "package": story,
                "created_at": datetime.fromtimestamp(f.stat().st_ctime).isoformat(),
            })
            
            # Переименовываем в delivered
            new_name = f.name.replace("_pending", "_delivered")
            f.rename(stories_dir / new_name)
    
    return pending


# ─── ПЕРСОНАЛЬНАЯ СЦЕНА (быстрая генерация SET→Фабула) ──────────────────────

@app.post("/api/studio/quick_scene")
async def quick_scene(req: GenerateRequest):
    """
    Быстрая генерация: только SET → Фабула (без полного пайплайна).
    Для тестов и быстрых персональных сцен.
    """
    print(f"[QUICK] Быстрая сцена для {req.child_name}...")
    
    # SET
    set_raw = await call_openrouter(
        system_prompt=SET_SYSTEM_PROMPT,
        user_prompt=f"Ребёнок: {req.child_name}, {req.child_age}. Задача: {req.task_context}",
        max_tokens=600,
    )
    master_brief = extract_json_from_response(set_raw)
    
    # Фабула (с психопринципами из нового промпта)
    fabula_prompt = load_agent_prompt("A00")
    fabula_raw = await call_openrouter(
        system_prompt=fabula_prompt,
        user_prompt=f"MASTER BRIEF:\n{json.dumps(master_brief, ensure_ascii=False, indent=2)}",
        max_tokens=2000,
    )
    
    # Сохраняем
    PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = req.child_name.lower().replace(" ", "_")
    file_path = PERSONAL_DIR / f"{safe_name}_personal_scene.json"
    
    scene_data = extract_json_from_response(fabula_raw)
    if not scene_data:
        scene_data = {"raw": fabula_raw}
    scene_data["_master_brief"] = master_brief
    
    file_path.write_text(json.dumps(scene_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return {
        "ok": True,
        "pipeline": "SET → Фабула (quick)",
        "child_name": req.child_name,
        "file_path": str(file_path),
        "scene": scene_data,
    }


# ─── НОЧНОЙ МАЯК ────────────────────────────────────────────────────────────

@app.post("/beacon")
async def receive_beacon(batch: BeaconBatch):
    """Ночной батч метрик от Искорки."""
    with sqlite3.connect(BEACON_DB) as conn:
        conn.execute(
            "INSERT INTO sync_log (device_id, session_id, synced_at, event_count) VALUES (?,?,?,?)",
            (batch.device_id, batch.session_id, batch.synced_at, len(batch.events))
        )
        for event in batch.events:
            ts_str = datetime.utcfromtimestamp(event.ts / 1000).isoformat()
            if event.type == "tag" and event.tag:
                conn.execute(
                    "INSERT INTO aggregate_tags (device_id, tag, ts) VALUES (?,?,?)",
                    (batch.device_id, event.tag, ts_str)
                )
            elif event.type == "choice" and event.choice_id:
                conn.execute(
                    "INSERT INTO aggregate_choices (device_id, choice_id, ts) VALUES (?,?,?)",
                    (batch.device_id, event.choice_id, ts_str)
                )
        
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
    
    print(f"[МАЯК] Батч от {batch.device_id}: {len(batch.events)} событий")
    return {"ok": True, "received": len(batch.events)}


# ─── СТАТИСТИКА ──────────────────────────────────────────────────────────────

@app.get("/stats")
def stats():
    with sqlite3.connect(BEACON_DB) as conn:
        devices   = conn.execute("SELECT COUNT(DISTINCT device_id) FROM sync_log").fetchone()[0]
        syncs     = conn.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0]
        generated = conn.execute("SELECT COUNT(*) FROM generated_scenes").fetchone()[0]
        top_tags  = conn.execute(
            "SELECT tag, COUNT(*) as c FROM aggregate_tags GROUP BY tag ORDER BY c DESC LIMIT 10"
        ).fetchall()
    
    return {
        "total_devices": devices,
        "total_syncs": syncs,
        "total_generated_books": generated,
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
    
    return {
        "status": "ok",
        "version": "4.0.0",
        "model": OPENROUTER_MODEL,
        "api_key_set": bool(OPENROUTER_API_KEY),
        "studio_root": str(STUDIO_ROOT),
        "modules_path": str(MODULES_PATH),
        "agents_available": agents_available,
        "books_dir": str(BOOKS_DIR),
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

@app.get("/api/parent/profile/{child_name}")
async def get_child_profile(child_name: str):
    """Родительский кабинет: профиль ребёнка."""
    safe_name = child_name.lower().replace(" ", "_")
    path = BOOKS_DIR / safe_name / "child_profile.json"
    if not path.exists():
        return {"error": "Профиль не найден", "child_name": child_name}
    return json.loads(path.read_text(encoding="utf-8"))
 
 
@app.get("/api/parent/basket/{child_name}")
async def get_gift_basket(child_name: str):
    """Родительский кабинет: последняя Корзинка Даров."""
    safe_name = child_name.lower().replace(" ", "_")
    path = BOOKS_DIR / safe_name / "gift_baskets" / "latest.json"
    if not path.exists():
        return {"error": "Корзинка не найдена", "child_name": child_name}
    return json.loads(path.read_text(encoding="utf-8"))
 
 
@app.get("/api/parent/biography/{child_name}")
async def get_biography(child_name: str):
    """Родительский кабинет: биография героя (кармический след)."""
    safe_name = child_name.lower().replace(" ", "_")
    path = BOOKS_DIR / safe_name / "biography.json"
    if not path.exists():
        return {"error": "Биография не найдена", "child_name": child_name}
    return json.loads(path.read_text(encoding="utf-8"))


# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("🚀 Живая Книга — Единый Сервер v4.0")
    print(f"🤖 Модель: {OPENROUTER_MODEL}")
    print(f"📚 Студия: {STUDIO_ROOT}")
    print(f"📖 Книги:  {BOOKS_DIR}")
    print(f"🔑 API Key: {'✅' if OPENROUTER_API_KEY else '❌'}")
    uvicorn.run(app, host="0.0.0.0", port=8001)

"""
beacon_v7.py — Маяк Живой Книги v7.0
===================================================================================
STANDARD.md v3.0 compliant.

Единый контракт: story_package.json
Эндпоинты:
  POST /api/package/order     — принять заказ от Кабинета, relay в Студию
  POST /api/package/deliver   — принять готовую главу от Студии
  POST /api/package/report    — принять отчёт от Искорки, обновить biography
  GET  /api/package/child/{uid} — отдать story_package для Искорки
  GET  /api/registry          — список детей
  POST /api/registry/add_child — добавить ребёнка
  GET  /api/health            — проверка статуса

❌ /api/free_talk — УДАЛЁН (STANDARD v3.0: никакого LLM в рантайме Искорки)

Legacy endpoints preserved for backward compatibility.
"""

import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# КОНФИГ
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Маяк Живой Книги", version="7.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
BOOKS_DIR = BASE_DIR.parent / "books"
BOOKS_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_REGISTRY_DIR = BASE_DIR.parent / "system_registry"
SYSTEM_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

PERSONAL_DIR = BOOKS_DIR / "personal"
REGISTRY_PATH = BOOKS_DIR / "registry.json"
BEACON_DB = BASE_DIR / "beacon.db"

# Студия (для relay заказов)
STUDIO_URL = os.getenv("STUDIO_URL", "http://localhost:8080")

print(f"📁 BOOKS_DIR = {BOOKS_DIR}")
print(f"📁 SYSTEM_REGISTRY = {SYSTEM_REGISTRY_DIR}")
print(f"🏭 STUDIO_URL = {STUDIO_URL}")


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ: РЕЕСТР
# ═══════════════════════════════════════════════════════════════════════════════

def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        data.setdefault("version", "3.0")
        data.setdefault("profiles", [])
        data.setdefault("parents", [])
        return data
    empty = {
        "version": "3.0",
        "updated_at": datetime.now().isoformat(),
        "profiles": [],
        "parents": [],
    }
    save_registry(empty)
    return empty


def save_registry(registry: dict):
    registry["updated_at"] = datetime.now().isoformat()
    registry["version"] = "3.0"
    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def generate_uid() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    registry = load_registry()
    today_count = sum(
        1 for p in registry.get("profiles", [])
        if p["uid"].startswith(f"LB-{today}")
    )
    return f"LB-{today}-{today_count + 1:04d}"


def resolve_uid(uid: str) -> Optional[Path]:
    """Возвращает папку ребёнка по uid."""
    # Сначала стандартный путь: books/{uid}/
    direct = BOOKS_DIR / uid
    if direct.exists():
        return direct
    # Legacy: books/personal/{folder}/
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            folder = profile.get("folder", uid)
            legacy = PERSONAL_DIR / folder
            if legacy.exists():
                return legacy
    return None


def get_profile_by_uid(uid: str) -> Optional[dict]:
    registry = load_registry()
    for profile in registry.get("profiles", []):
        if profile["uid"] == uid:
            return profile
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ: BIOGRAPHY
# ═══════════════════════════════════════════════════════════════════════════════

def load_bio(folder: Path, uid: str, alias: str = "Ребёнок") -> dict:
    bio_path = folder / "biography.json"
    if bio_path.exists():
        bio = json.loads(bio_path.read_text(encoding="utf-8"))
    else:
        bio = {
            "uid": uid,
            "child_name": alias,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "total_stories": 0,
            "main_character": None,
            "home_world": None,
            "karmic_trail": [],
            "artifacts": [],
            "character_bonds": {},
            "karma": {"current": 0, "history": []},
            "psychological_patterns": [],
            "completed_stories": [],
            "pending_bridges": [],
            "completed_bridges": [],
        }
    # Гарантируем все нужные поля
    bio.setdefault("artifacts", [])
    bio.setdefault("karmic_trail", [])
    bio.setdefault("character_bonds", {})
    bio.setdefault("karma", {"current": 0, "history": []})
    bio.setdefault("pending_bridges", [])
    bio.setdefault("completed_bridges", [])
    bio.setdefault("completed_stories", [])
    bio.setdefault("main_character", None)
    bio.setdefault("home_world", None)
    return bio


def save_bio(folder: Path, bio: dict):
    bio["updated_at"] = datetime.now().isoformat()
    (folder / "biography.json").write_text(
        json.dumps(bio, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def make_biography_snapshot(bio: dict) -> dict:
    """Формирует biography_snapshot для story_package.json (Стандарт §4.5)."""
    return {
        "main_character": bio.get("main_character"),
        "home_world": bio.get("home_world"),
        "artifacts": [
            {"id": a["id"], "name": a.get("name", a["id"]), "obtained_at": a.get("obtained_at")}
            for a in bio.get("artifacts", [])
        ],
        "character_bonds": bio.get("character_bonds", {}),
        "karma": bio.get("karma", {}).get("current", 0),
        "last_choices": [
            entry.get("choices_made", [{}])[-1].get("memory_vector", "")
            for entry in bio.get("karmic_trail", [])[-10:]
            if entry.get("choices_made")
        ],
        "completed_stories": bio.get("completed_stories", []),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ: BOOK.JSON
# ═══════════════════════════════════════════════════════════════════════════════

def load_book(folder: Path) -> Optional[dict]:
    book_path = folder / "book.json"
    if book_path.exists():
        return json.loads(book_path.read_text(encoding="utf-8"))
    return None


def save_book(folder: Path, book: dict):
    (folder / "book.json").write_text(
        json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_next_chapter_id(folder: Path) -> str:
    chapters_dir = folder / "chapters"
    if not chapters_dir.exists():
        return "ch01"
    existing = sorted(chapters_dir.glob("ch*.json"))
    if not existing:
        return "ch01"
    last_num = 0
    for ch in existing:
        try:
            num = int(ch.stem.replace("ch", ""))
            if num > last_num:
                last_num = num
        except ValueError:
            pass
    return f"ch{last_num + 1:02d}"


# ═══════════════════════════════════════════════════════════════════════════════
#  СТАНДАРТ v3.0: POST /api/package/order
#  Принять заказ от Кабинета → relay в Студию
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/package/order")
async def package_order(body: dict, background_tasks: BackgroundTasks):
    """
    Принимает story_package.json с type: 'order' от Кабинета Родителя.
    
    Два режима:
      - first_book: копирует готовую книгу из ready_books/
      - next_chapter: дополняет biography_snapshot, relay в Студию
    """
    meta = body.get("meta", {})
    child = body.get("child", {})
    order = body.get("order", {})

    # Валидация
    if meta.get("type") != "order":
        raise HTTPException(400, "meta.type must be 'order'")
    if not child.get("uid") and not child.get("name"):
        raise HTTPException(400, "child.uid or child.name required")

    uid = child.get("uid")
    mode = order.get("mode", "next_chapter")
    package_id = meta.get("package_id", f"pkg_{uuid.uuid4().hex[:8]}")

    # ── РЕЖИМ 1: first_book ──────────────────────────────────────────────
    if mode == "first_book":
        book_id = order.get("book_id")
        if not book_id:
            raise HTTPException(400, "order.book_id required for first_book")

        # Если uid нет — создаём нового ребёнка
        if not uid:
            uid = generate_uid()
            child_folder = BOOKS_DIR / uid
            child_folder.mkdir(parents=True, exist_ok=True)
            (child_folder / "chapters").mkdir(exist_ok=True)

            # Создаём child_profile.json
            profile_data = {
                "uid": uid,
                "child_name": child.get("name", "Ребёнок"),
                "age_group": child.get("age_group", "7-12"),
                "created_at": datetime.now().isoformat(),
            }
            (child_folder / "child_profile.json").write_text(
                json.dumps(profile_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # Создаём biography.json
            bio = load_bio(child_folder, uid, child.get("name", "Ребёнок"))
            save_bio(child_folder, bio)

            # Создаём ethics.json (копируем шаблон если есть)
            ethics_template = BOOKS_DIR / "ethics.json"
            if ethics_template.exists():
                shutil.copy2(ethics_template, child_folder / "ethics.json")

            # Регистрируем в реестре
            registry = load_registry()
            registry["profiles"].append({
                "uid": uid,
                "alias": child.get("name", "Ребёнок"),
                "folder": uid,
                "age_group": child.get("age_group", "7-12"),
                "created_at": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat(),
                "status": "active",
            })
            save_registry(registry)
        else:
            child_folder = resolve_uid(uid)
            if not child_folder:
                raise HTTPException(404, f"Ребёнок {uid} не найден")

        # Копируем готовую книгу из system_registry/ready_books/
        ready_book_path = SYSTEM_REGISTRY_DIR / "ready_books" / f"{book_id}.json"
        if not ready_book_path.exists():
            raise HTTPException(404, f"Готовая книга '{book_id}' не найдена в ready_books/")

        ready_book = json.loads(ready_book_path.read_text(encoding="utf-8"))

        # Создаём book.json
        book = {
            "id": uid,
            "title": ready_book.get("title", "Первая книга"),
            "description": ready_book.get("description", ""),
            "age_group": child.get("age_group", "7-12"),
            "language": "ru",
            "version": "1.0",
            "created_by": "Six Fingers Studio",
            "main_character": ready_book.get("main_character", "eirik"),
            "chapters": [],
            "starting_chapter": "ch01",
            "starting_scene": "scene_01",
            "global_intents": {
                "emergency": {
                    "keywords": ["помогите", "спасите", "мне плохо", "больно"],
                    "action": "pause_game_until_adult",
                    "reply_text": "Я рядом. Сейчас позову взрослого.",
                    "notify_parent": True,
                },
                "stop": {
                    "keywords": ["стоп", "хватит", "перестань", "замолчи"],
                    "action": "reply",
                    "reply_text": "Хорошо, я замолкаю. Скажи, когда продолжить.",
                    "notify_parent": False,
                },
            },
        }

        # Сохраняем первую главу
        chapters_dir = child_folder / "chapters"
        chapters_dir.mkdir(exist_ok=True)

        chapter_data = ready_book.get("chapter", {})
        chapter_id = chapter_data.get("id", "ch01")
        chapter_path = chapters_dir / f"{chapter_id}.json"
        chapter_path.write_text(
            json.dumps(chapter_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        book["chapters"].append({
            "id": chapter_id,
            "title": chapter_data.get("title", "Первая глава"),
            "file": f"chapters/{chapter_id}.json",
        })
        save_book(child_folder, book)

        # Обновляем biography: main_character, home_world, начальные мостики
        bio = load_bio(child_folder, uid)
        bio["main_character"] = ready_book.get("main_character", "eirik")
        bio["home_world"] = ready_book.get("home_world", "cave")
        for bridge in ready_book.get("initial_bridges", []):
            bridge["status"] = "pending"
            bridge["created_at"] = datetime.now().isoformat()
            bio["pending_bridges"].append(bridge)
        bio["karma"]["current"] = ready_book.get("initial_karma", 0)
        save_bio(child_folder, bio)

        print(f"[ORDER] ✅ first_book '{book_id}' → {uid}")

        return {
            "ok": True,
            "uid": uid,
            "package_id": package_id,
            "status": "delivered",
            "chapter_id": chapter_id,
        }

    # ── РЕЖИМ 2: next_chapter ────────────────────────────────────────────
    if not uid:
        raise HTTPException(400, "child.uid required for next_chapter")

    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")

    profile = get_profile_by_uid(uid)
    bio = load_bio(folder, uid, profile.get("alias", "Ребёнок") if profile else "Ребёнок")

    # Дополняем пакет biography_snapshot
    biography_snapshot = make_biography_snapshot(bio)

    # Полный пакет для Студии
    studio_package = {
        "meta": {
            "version": "3.0",
            "type": "order",
            "timestamp": datetime.now().isoformat(),
            "package_id": package_id,
        },
        "child": {
            "uid": uid,
            "name": profile.get("alias", child.get("name", "Ребёнок")) if profile else child.get("name", "Ребёнок"),
            "age_group": profile.get("age_group", child.get("age_group", "7-12")) if profile else child.get("age_group", "7-12"),
        },
        "order": order,
        "biography_snapshot": biography_snapshot,
    }

    # Relay в Студию (в фоне)
    async def relay_to_studio():
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                r = await client.post(
                    f"{STUDIO_URL}/api/living_book/generate",
                    json=studio_package,
                )
                r.raise_for_status()
                result = r.json()
                print(f"[ORDER] ✅ Студия ответила для {uid}: {result.get('status')}")

                # Если Студия вернула chapter сразу — сохраняем
                if result.get("book_package", {}).get("chapter"):
                    await _save_delivered_chapter(
                        uid, folder, result["book_package"], package_id
                    )
        except Exception as e:
            print(f"[ORDER] ❌ Ошибка relay в Студию для {uid}: {e}")

    background_tasks.add_task(relay_to_studio)

    return {
        "ok": True,
        "package_id": package_id,
        "status": "processing",
        "message": "Заказ передан в Студию. Глава будет доставлена через /api/package/deliver",
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  СТАНДАРТ v3.0: POST /api/package/deliver
#  Принять готовую главу от Студии → сохранить
# ═══════════════════════════════════════════════════════════════════════════════

async def _save_delivered_chapter(
    uid: str, folder: Path, package: dict, in_response_to: str = None
):
    """Внутренняя логика сохранения главы."""
    chapter = package.get("chapter", {})
    chapter_id = chapter.get("id") or get_next_chapter_id(folder)

    chapters_dir = folder / "chapters"
    chapters_dir.mkdir(exist_ok=True)

    # Сохраняем файл главы
    chapter_path = chapters_dir / f"{chapter_id}.json"
    chapter_path.write_text(
        json.dumps(chapter, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Обновляем book.json
    book = load_book(folder) or {"id": uid, "chapters": []}
    if not any(ch["id"] == chapter_id for ch in book.get("chapters", [])):
        book.setdefault("chapters", []).append({
            "id": chapter_id,
            "title": chapter.get("title", f"Глава {chapter_id}"),
            "file": f"chapters/{chapter_id}.json",
        })
        save_book(folder, book)

    # Мостики из главы → pending_bridges в biography
    bio = load_bio(folder, uid)
    for bridge in chapter.get("bridges", []):
        bridge["status"] = "pending"
        bridge["created_at"] = datetime.now().isoformat()
        bio["pending_bridges"].append(bridge)
    save_bio(folder, bio)

    print(f"[DELIVER] ✅ Глава {chapter_id} сохранена для {uid}")
    return chapter_id


@app.post("/api/package/deliver")
async def package_deliver(body: dict):
    """
    Принимает story_package.json с type: 'chapter' от Студии.
    Сохраняет главу в books/{uid}/chapters/
    """
    meta = body.get("meta", {})
    child = body.get("child", {})

    if meta.get("type") != "chapter":
        raise HTTPException(400, "meta.type must be 'chapter'")

    uid = child.get("uid")
    if not uid:
        raise HTTPException(400, "child.uid required")

    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")

    chapter_id = await _save_delivered_chapter(
        uid, folder, body, meta.get("in_response_to")
    )

    return {
        "ok": True,
        "chapter_id": chapter_id,
        "saved_to": f"chapters/{chapter_id}.json",
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  СТАНДАРТ v3.0: POST /api/package/report
#  Принять отчёт от Искорки → обновить biography.json
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/package/report")
async def package_report(body: dict):
    """
    Принимает story_package.json с type: 'report' от Искорки.
    Обновляет biography.json:
      - karmic_trail (добавляет choices_made)
      - artifacts (добавляет new_artifacts)
      - karma (обновляет current)
      - character_bonds (если есть)
      - completed_stories
      - bridges (обновляет completed)
    """
    meta = body.get("meta", {})
    child = body.get("child", {})
    report = body.get("report", {})
    bridges_data = body.get("bridges", {})

    if meta.get("type") != "report":
        raise HTTPException(400, "meta.type must be 'report'")

    uid = child.get("uid")
    if not uid:
        raise HTTPException(400, "child.uid required")

    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")

    bio = load_bio(folder, uid)

    # 1. Karmic trail — запись о прохождении
    chapter_id = report.get("chapter_id", "unknown")
    memory_vectors = report.get("memory_vectors", [])
    choices_made = report.get("choices_made", [])

    bio["karmic_trail"].append({
        "date": report.get("session_end", datetime.now().isoformat()),
        "chapter_id": chapter_id,
        "theme": ", ".join(memory_vectors[:3]) if memory_vectors else "unknown",
        "choices_made": choices_made,
        "key_message": "",
    })

    # 2. Артефакты
    for artifact_id in report.get("new_artifacts", []):
        if not any(a.get("id") == artifact_id for a in bio["artifacts"]):
            bio["artifacts"].append({
                "id": artifact_id,
                "name": artifact_id,
                "obtained_at": datetime.now().isoformat(),
            })

    # 3. Карма
    karma_gained = report.get("karma_gained", 0)
    bio["karma"]["current"] += karma_gained
    bio["karma"]["history"].append({
        "ts": datetime.now().isoformat(),
        "delta": karma_gained,
        "reason": f"chapter_completed:{chapter_id}",
    })

    # 4. Completed stories
    if chapter_id not in bio.get("completed_stories", []):
        bio.setdefault("completed_stories", []).append(chapter_id)
    bio["total_stories"] = len(bio.get("completed_stories", []))

    # 5. Мостики — перемещаем из pending в completed
    completed_bridge_ids = report.get("bridges_completed", [])
    still_pending = []
    for bridge in bio.get("pending_bridges", []):
        if bridge.get("id") in completed_bridge_ids:
            bridge["completed_at"] = datetime.now().isoformat()
            bridge["status"] = "completed"
            bio.setdefault("completed_bridges", []).append(bridge)
            # Карма за мостик
            bridge_karma = bridge.get("karma_reward", 0)
            if bridge_karma:
                bio["karma"]["current"] += bridge_karma
                bio["karma"]["history"].append({
                    "ts": datetime.now().isoformat(),
                    "delta": bridge_karma,
                    "reason": f"bridge_completed:{bridge.get('id')}",
                })
        else:
            still_pending.append(bridge)
    bio["pending_bridges"] = still_pending

    # 6. Сохраняем
    save_bio(folder, bio)

    # 7. Обновляем last_activity в реестре
    registry = load_registry()
    for p in registry.get("profiles", []):
        if p["uid"] == uid:
            p["last_activity"] = datetime.now().isoformat()
            break
    save_registry(registry)

    print(f"[REPORT] ✅ {uid} chapter={chapter_id} karma={bio['karma']['current']} artifacts={len(bio['artifacts'])}")

    return {
        "ok": True,
        "karma_updated": bio["karma"]["current"],
        "new_artifacts": len(report.get("new_artifacts", [])),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  СТАНДАРТ v3.0: GET /api/package/child/{uid}
#  Отдать story_package (последнюю не пройденную главу) для Искорки
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/package/child/{uid}")
async def package_child(uid: str):
    """
    Возвращает story_package.json для Искорки:
      - Если есть непройденная глава → type: 'chapter'
      - Если всё пройдено → type: 'waiting'
    """
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")

    profile = get_profile_by_uid(uid)
    bio = load_bio(folder, uid, profile.get("alias", "Ребёнок") if profile else "Ребёнок")
    book = load_book(folder)

    completed = set(bio.get("completed_stories", []))

    # Ищем первую непройденную главу
    next_chapter = None
    if book:
        for ch_entry in book.get("chapters", []):
            if ch_entry["id"] not in completed:
                chapter_file = folder / ch_entry.get("file", f"chapters/{ch_entry['id']}.json")
                if chapter_file.exists():
                    next_chapter = json.loads(chapter_file.read_text(encoding="utf-8"))
                    break

    if not next_chapter:
        return {
            "meta": {
                "version": "3.0",
                "type": "waiting",
                "timestamp": datetime.now().isoformat(),
                "package_id": f"pkg_{uuid.uuid4().hex[:8]}",
            },
            "child": {"uid": uid},
            "message": "Все главы пройдены. Закажите новую в Кабинете родителя.",
            "biography_snapshot": make_biography_snapshot(bio),
        }

    return {
        "meta": {
            "version": "3.0",
            "type": "chapter",
            "timestamp": datetime.now().isoformat(),
            "package_id": f"pkg_{uuid.uuid4().hex[:8]}",
        },
        "child": {
            "uid": uid,
            "name": bio.get("child_name", "Ребёнок"),
            "age_group": profile.get("age_group", "7-12") if profile else "7-12",
        },
        "chapter": next_chapter,
        "bridges": {
            "pending": bio.get("pending_bridges", []),
            "completed": bio.get("completed_bridges", [])[-5:],
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  СТАНДАРТ v3.0: GET /api/registry
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/registry")
async def get_registry():
    return load_registry()


# ═══════════════════════════════════════════════════════════════════════════════
#  СТАНДАРТ v3.0: POST /api/registry/add_child
# ═══════════════════════════════════════════════════════════════════════════════

class AddChildRequest(BaseModel):
    name: str
    age_group: str = "7-12"
    parent_id: Optional[str] = None

@app.post("/api/registry/add_child")
async def add_child(req: AddChildRequest):
    uid = generate_uid()
    child_folder = BOOKS_DIR / uid
    child_folder.mkdir(parents=True, exist_ok=True)
    (child_folder / "chapters").mkdir(exist_ok=True)

    profile_data = {
        "uid": uid,
        "child_name": req.name,
        "age_group": req.age_group,
        "created_at": datetime.now().isoformat(),
    }
    (child_folder / "child_profile.json").write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    bio = load_bio(child_folder, uid, req.name)
    save_bio(child_folder, bio)

    ethics_template = BOOKS_DIR / "ethics.json"
    if ethics_template.exists():
        shutil.copy2(ethics_template, child_folder / "ethics.json")

    registry = load_registry()
    new_profile = {
        "uid": uid,
        "alias": req.name,
        "folder": uid,
        "age_group": req.age_group,
        "created_at": datetime.now().isoformat(),
        "last_activity": datetime.now().isoformat(),
        "status": "active",
    }
    if req.parent_id:
        new_profile["parent_id"] = req.parent_id
    registry["profiles"].append(new_profile)
    save_registry(registry)

    return {"ok": True, "uid": uid, "name": req.name}


# ═══════════════════════════════════════════════════════════════════════════════
#  LEGACY ENDPOINTS (обратная совместимость)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/worlds")
async def get_worlds():
    worlds_path = SYSTEM_REGISTRY_DIR / "worlds_registry.json"
    if worlds_path.exists():
        return json.loads(worlds_path.read_text(encoding="utf-8"))
    raise HTTPException(404, "worlds_registry.json не найден")


@app.get("/api/beacon/uid/{uid}/bio")
async def get_biography_legacy(uid: str):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Папка для {uid} не найдена")
    profile = get_profile_by_uid(uid)
    alias = profile.get("alias", "Ребёнок") if profile else "Ребёнок"
    return load_bio(folder, uid, alias)


@app.post("/api/beacon/uid/{uid}/artifact")
async def add_artifact_legacy(uid: str, artifact: dict):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404, f"Ребёнок {uid} не найден")
    bio = load_bio(folder, uid)
    if not any(a.get("id") == artifact.get("id") for a in bio.get("artifacts", [])):
        artifact["obtained_at"] = datetime.now().isoformat()
        artifact["permanent"] = True
        bio["artifacts"].append(artifact)
        save_bio(folder, bio)
        return {"ok": True, "artifact": artifact}
    return {"ok": False, "message": "Артефакт уже есть"}


@app.get("/api/parent/uid/{uid}/artifacts")
async def get_artifacts_legacy(uid: str):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404)
    bio = load_bio(folder, uid)
    return {"artifacts": bio.get("artifacts", [])}


@app.get("/api/parent/uid/{uid}/pending_bridges")
async def get_pending_bridges_legacy(uid: str):
    folder = resolve_uid(uid)
    if not folder:
        raise HTTPException(404)
    bio = load_bio(folder, uid)
    return {"pending_bridges": bio.get("pending_bridges", [])}


@app.get("/api/showcase")
async def get_showcase():
    showcase_dir = SYSTEM_REGISTRY_DIR / "showcase"
    if not showcase_dir.exists():
        return {"stories": [], "count": 0}
    stories = []
    for json_file in showcase_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            stories.append({
                "story_id": json_file.stem,
                "title": data.get("title", json_file.stem),
                "description": data.get("description", ""),
            })
        except Exception:
            pass
    return {"stories": stories, "count": len(stories)}


# ═══════════════════════════════════════════════════════════════════════════════
#  HEALTH CHECK (Стандарт v3.0 §10.1)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    studio_ok = False
    studio_info = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{STUDIO_URL}/api/living_book/status")
            if r.status_code == 200:
                studio_ok = True
                studio_info = r.json()
            else:
                studio_info = {"error": f"status {r.status_code}"}
    except Exception as e:
        studio_info = {"error": str(e)}

    registry = load_registry()
    return {
        "beacon": "ok",
        "version": "7.0.0",
        "standard": "3.0",
        "studio_connected": studio_ok,
        "studio_url": STUDIO_URL,
        "studio_info": studio_info,
        "profiles_count": len(registry.get("profiles", [])),
        "books_dir": str(BOOKS_DIR),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  РАЗДАЧА СТАТИКИ
# ═══════════════════════════════════════════════════════════════════════════════

PLAYER_DIR = BASE_DIR.parent / "player"
DASHBOARD_DIR = BASE_DIR.parent / "dashboard"

if PLAYER_DIR.exists():
    app.mount("/player", StaticFiles(directory=str(PLAYER_DIR), html=True), name="player")
if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")


# ═══════════════════════════════════════════════════════════════════════════════
#  ИНИЦИАЛИЗАЦИЯ БД
# ═══════════════════════════════════════════════════════════════════════════════

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
            CREATE TABLE IF NOT EXISTS package_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                package_id TEXT NOT NULL,
                uid TEXT NOT NULL,
                type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_preview TEXT
            );
        """)

init_db()


# ═══════════════════════════════════════════════════════════════════════════════
#  ЗАПУСК
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    registry = load_registry()
    print()
    print("🔦 Маяк Живой Книги v7.0 (STANDARD.md v3.0)")
    print(f"   📖 books:   {BOOKS_DIR}")
    print(f"   🏭 studio:  {STUDIO_URL}")
    print(f"   🆔 profiles: {len(registry.get('profiles', []))}")
    print()
    print("   📡 СТАНДАРТ v3.0 ЭНДПОИНТЫ:")
    print("     POST /api/package/order     — заказ от Кабинета")
    print("     POST /api/package/deliver   — глава от Студии")
    print("     POST /api/package/report    — отчёт от Искорки")
    print("     GET  /api/package/child/{uid} — пакет для Искорки")
    print("     GET  /api/registry          — список детей")
    print("     POST /api/registry/add_child — регистрация")
    print("     GET  /api/health            — проверка статуса")
    print()
    print("   ❌ /api/free_talk — УДАЛЁН (STANDARD v3.0)")
    print()
    if PLAYER_DIR.exists():
        print(f"   📺 Искорка:  http://127.0.0.1:8001/player/")
    if DASHBOARD_DIR.exists():
        print(f"   📊 Кабинет:  http://127.0.0.1:8001/dashboard/")
    print()
    uvicorn.run(app, host="0.0.0.0", port=8001)

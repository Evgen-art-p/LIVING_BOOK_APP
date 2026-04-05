"""
patch_beacon_iskra.py — Патч для beacon_v4.py + index.html
==========================================================
Исправляет 3 бага, из-за которых Искорка не запускается:

  БАГ 1: В beacon_v4.py НЕТ эндпоинтов /meta и /chapters/{id},
         которые Искорка вызывает в BookEngine.init() и _loadChapter()
  
  БАГ 2: Регистрозависимость — папка "Женя" (большая), а код ищет "женя" (lower)
  
  БАГ 3: В ch01.json поле называется "id", а index.html ищет "scene_id"
         → сцена не индексируется → playScene(null) → тишина

Запуск из корня LIVING_BOOK_APP:
    python patch_beacon_iskra.py

После патча:
    cd server
    uvicorn beacon_v4:app --host 0.0.0.0 --port 8001 --reload
"""

import shutil
from pathlib import Path

print("=" * 60)
print("  ПАТЧ ИСКОРКИ — 3 бага")
print("=" * 60)

# ─── НАЙТИ ФАЙЛЫ ────────────────────────────────────────────────────────────
def find_file(candidates):
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p
    return None

BEACON_FILE = find_file([
    Path(__file__).parent / "server" / "beacon_v4.py",
    "server/beacon_v4.py",
    "beacon_v4.py",
])

INDEX_FILE = find_file([
    Path(__file__).parent / "player" / "index.html",
    "player/index.html",
    "index.html",
])

assert BEACON_FILE, "Не найден beacon_v4.py! Запусти из корня LIVING_BOOK_APP"

# ═══════════════════════════════════════════════════════════════════════════════
# ПАТЧИМ beacon_v4.py
# ═══════════════════════════════════════════════════════════════════════════════
backup = BEACON_FILE.with_suffix(".py.bak_pre_iskra")
shutil.copy2(BEACON_FILE, backup)
print(f"\n✅ Бэкап: {backup}")

content = BEACON_FILE.read_text(encoding="utf-8")
patched = 0

# --- ПАТЧ 1: Фикс регистра в get_stories_for_child ---
OLD_STORIES = '''@app.get("/api/beacon/stories/{child_name}")
async def get_stories_for_child(child_name: str):
    """Искорка забирает свои книги"""
    safe_name = child_name.lower().replace(" ", "_")
    stories_dir = BASE_DIR / "stories" / safe_name
    
    if not stories_dir.exists():
        return []  # Нет новых книг'''

NEW_STORIES = '''@app.get("/api/beacon/stories/{child_name}")
async def get_stories_for_child(child_name: str):
    """Искорка забирает свои книги"""
    stories_dir = _find_stories_folder(child_name)
    
    if not stories_dir or not stories_dir.exists():
        return []  # Нет новых книг'''

if OLD_STORIES in content:
    content = content.replace(OLD_STORIES, NEW_STORIES)
    print("✅ ПАТЧ 1: Фикс регистрозависимости в get_stories_for_child()")
    patched += 1
else:
    print("⚠️  ПАТЧ 1: Блок не найден (уже пропатчен?)")

# --- ПАТЧ 2: Добавляем новые эндпоинты ---
NEW_ENDPOINTS = '''
# ─── ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: case-insensitive поиск папки stories ───────────

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


# ─── ИСКОРКА: метаданные книги (book.json) ──────────────────────────────────

@app.get("/api/beacon/stories/{child_name}/meta")
async def get_book_meta(child_name: str):
    """
    Искорка запрашивает book.json — метаданные книги.
    Ищет в books/{child_name}/book.json (case-insensitive).
    """
    book_path = _find_book_path(child_name)
    if not book_path or not book_path.exists():
        raise HTTPException(404, f"Книга для '{child_name}' не найдена")
    data = json.loads(book_path.read_text(encoding="utf-8"))
    print(f"[META] Отдаю book.json для '{child_name}': {data.get('title', '?')}")
    return data


# ─── ИСКОРКА: загрузка главы ─────────────────────────────────────────────────

@app.get("/api/beacon/stories/{child_name}/chapters/{chapter_id}")
async def get_chapter(child_name: str, chapter_id: str):
    """
    Искорка запрашивает конкретную главу: chapters/{chapter_id}.json
    """
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
    print(f"[CHAPTER] Отдаю {chapter_id} для '{child_name}': {len(data.get('scenes', []))} сцен")
    return data


'''

STATS_MARKER = '@app.get("/stats")'
if STATS_MARKER in content:
    if '/api/beacon/stories/{child_name}/meta' not in content:
        content = content.replace(STATS_MARKER, NEW_ENDPOINTS + STATS_MARKER)
        print("✅ ПАТЧ 2: Добавлены /meta и /chapters/{chapter_id}")
        patched += 1
    else:
        print("⚠️  ПАТЧ 2: Эндпоинты уже существуют")
else:
    print("❌ ПАТЧ 2: Маркер @app.get('/stats') не найден!")

BEACON_FILE.write_text(content, encoding="utf-8")
print(f"   Записано: {BEACON_FILE}")

# ═══════════════════════════════════════════════════════════════════════════════
# ПАТЧИМ index.html (scene_id vs id)
# ═══════════════════════════════════════════════════════════════════════════════
if INDEX_FILE:
    idx_content = INDEX_FILE.read_text(encoding="utf-8")
    idx_backup = INDEX_FILE.with_suffix(".html.bak_pre_iskra")
    shutil.copy2(INDEX_FILE, idx_backup)
    
    # Фикс: в ch01.json поле "id", а код ищет "scene_id"
    OLD_INDEX = 'if (s.scene_id) data._index[s.scene_id] = s;'
    NEW_INDEX = 'const sid = s.scene_id || s.id; if (sid) { data._index[sid] = s; s.scene_id = sid; }'
    
    if OLD_INDEX in idx_content:
        idx_content = idx_content.replace(OLD_INDEX, NEW_INDEX)
        INDEX_FILE.write_text(idx_content, encoding="utf-8")
        print(f"✅ ПАТЧ 3: Фикс scene_id vs id в index.html")
        print(f"   Бэкап: {idx_backup}")
        patched += 1
    else:
        print("⚠️  ПАТЧ 3: Строка индексации не найдена (уже пропатчена?)")
else:
    print(f"⚠️  ПАТЧ 3: index.html не найден")


# ═══════════════════════════════════════════════════════════════════════════════
# ИТОГ
# ═══════════════════════════════════════════════════════════════════════════════
print(f"""
{'=' * 60}
  ГОТОВО! Применено {patched} из 3 патчей
{'=' * 60}

  beacon_v4.py:
  + GET /api/beacon/stories/{{name}}/meta      → book.json
  + GET /api/beacon/stories/{{name}}/chapters/{{id}} → глава
  + Фикс регистра: Женя/женя → case-insensitive
  + _find_stories_folder() — универсальный поиск

  index.html:
  + Фикс scene_id vs id (JSON: "id", код искал "scene_id")

  ────────────────────────────────────────────────────────────
  ДАЛЬШЕ:
  1. cd server
  2. uvicorn beacon_v4:app --host 0.0.0.0 --port 8001 --reload
  3. Открой player/index.html → «Зажечь Искорку»
  4. Если не работает → F12 → Console → ищи 404
  ────────────────────────────────────────────────────────────
""")

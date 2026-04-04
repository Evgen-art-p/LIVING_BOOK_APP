"""
post_run.py — Пост-ранная рефлексия агентов Живой Книги
========================================================
Запускается автоматически после завершения пайплайна в beacon.py.

Три фазы рефлексии:

1. ЛИНЗА СТАТ (A09) → Анализ выборов ребёнка → обновление child_profile.json
2. ТЬЮТОР ЛИНК (A12) → Корзинка Даров → рекомендации для родителя
3. ХРОНОС МЕМО (A02) → Архивация сессии → biography.json (кармический след)

Дополнительно:
4. ПРОГУЛКА → агенты идут гулять по Грондхейму (Гавань Смыслов, Библиотека)

Запуск: вызывается из beacon.py после run_full_pipeline()
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ЛИНЗА СТАТ (A09) — Обновление профиля ребёнка
# ═══════════════════════════════════════════════════════════════════════════════

def update_child_profile(
    child_name: str,
    books_dir: Path,
    a09_output: dict,
    master_brief: dict,
) -> dict:
    """
    Линза Стат анализирует выборы ребёнка и обновляет его психологический профиль.
    
    Профиль хранится в books/{child_name}/child_profile.json
    Накапливается от книги к книге — каждый ран добавляет данные.
    """
    safe_name = child_name.lower().replace(" ", "_")
    profile_path = books_dir / safe_name / "child_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Загружаем существующий профиль или создаём новый
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    else:
        profile = {
            "child_name": child_name,
            "created_at": datetime.now().isoformat(),
            "total_sessions": 0,
            "total_choices_made": 0,
            "psychological_patterns": [],
            "growth_zones": [],
            "dominant_strategies": {},
            "emotional_trajectory": [],
            "sessions": [],
        }
    
    # Извлекаем данные из A09
    my_output = a09_output if isinstance(a09_output, dict) else {}
    if "my_output" in my_output:
        my_output = my_output["my_output"]
    
    # Новая сессия
    session = {
        "date": datetime.now().isoformat(),
        "theme": master_brief.get("theme", "unknown"),
        "task_context": master_brief.get("task_context", ""),
        "age_group": master_brief.get("age_group", "7-12"),
        "patterns": my_output.get("psychological_patterns", []),
        "growth_zones": my_output.get("growth_zones", []),
        "parent_insights": my_output.get("parent_insights", []),
        "choice_statistics": my_output.get("choice_statistics", {}),
    }
    
    # Обновляем профиль
    profile["total_sessions"] += 1
    profile["updated_at"] = datetime.now().isoformat()
    profile["sessions"].append(session)
    
    # Обновляем паттерны (дедупликация по содержанию)
    existing_patterns = set(profile.get("psychological_patterns", []))
    for pattern in my_output.get("psychological_patterns", []):
        # Берём первые 80 символов как ключ для дедупликации
        key = pattern[:80] if isinstance(pattern, str) else str(pattern)[:80]
        if key not in existing_patterns:
            profile["psychological_patterns"].append(pattern)
            existing_patterns.add(key)
    
    # Обновляем зоны роста
    existing_zones = set(profile.get("growth_zones", []))
    for zone in my_output.get("growth_zones", []):
        key = zone[:80] if isinstance(zone, str) else str(zone)[:80]
        if key not in existing_zones:
            profile["growth_zones"].append(zone)
            existing_zones.add(key)
    
    # Обновляем стратегии
    for choice_key, stats in my_output.get("choice_statistics", {}).items():
        count = stats.get("count", 1) if isinstance(stats, dict) else 1
        profile["dominant_strategies"][choice_key] = \
            profile["dominant_strategies"].get(choice_key, 0) + count
    
    # Считаем общие выборы
    total_choices = sum(
        s.get("count", 1) if isinstance(s, dict) else 1
        for s in my_output.get("choice_statistics", {}).values()
    )
    profile["total_choices_made"] += total_choices
    
    # Добавляем эмоциональную точку
    profile["emotional_trajectory"].append({
        "date": datetime.now().isoformat(),
        "theme": master_brief.get("theme", ""),
        "emotional_goal": master_brief.get("emotional_goal", ""),
        "patterns_count": len(my_output.get("psychological_patterns", [])),
    })
    
    # Ограничиваем историю (последние 50 сессий подробно)
    if len(profile["sessions"]) > 50:
        profile["sessions"] = profile["sessions"][-50:]
    
    # Сохраняем
    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    print(f"[ЛИНЗА СТАТ] 📊 Профиль «{child_name}» обновлён: "
          f"{profile['total_sessions']} сессий, "
          f"{profile['total_choices_made']} выборов, "
          f"{len(profile['psychological_patterns'])} паттернов")
    
    return profile


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ТЬЮТОР ЛИНК (A12) — Корзинка Даров
# ═══════════════════════════════════════════════════════════════════════════════

def build_gift_basket(
    child_name: str,
    books_dir: Path,
    a12_output: dict,
    a09_output: dict,
    master_brief: dict,
) -> dict:
    """
    Тьютор Линк формирует «Корзинку Даров» для родителя:
    - Что ребёнок прожил в этой истории
    - Какие темы поднялись
    - Как продолжить разговор в реальной жизни
    - «Мостик в Реал» — конкретные действия для родителя
    """
    safe_name = child_name.lower().replace(" ", "_")
    basket_dir = books_dir / safe_name / "gift_baskets"
    basket_dir.mkdir(parents=True, exist_ok=True)
    
    # Извлекаем данные
    a09_data = a09_output if isinstance(a09_output, dict) else {}
    if "my_output" in a09_data:
        a09_data = a09_data["my_output"]
    
    a12_data = a12_output if isinstance(a12_output, dict) else {}
    if "my_output" in a12_data:
        a12_data = a12_data["my_output"]
    
    # Формируем корзинку
    basket = {
        "date": datetime.now().isoformat(),
        "child_name": child_name,
        "story_theme": master_brief.get("theme", ""),
        "task_context": master_brief.get("task_context", ""),
        
        # Что ребёнок прожил
        "child_experience": {
            "emotional_goal": master_brief.get("emotional_goal", ""),
            "patterns_observed": a09_data.get("psychological_patterns", []),
            "growth_zones": a09_data.get("growth_zones", []),
        },
        
        # Инсайты для родителя (от Линзы Стат)
        "parent_insights": a09_data.get("parent_insights", []),
        
        # Мостик в Реал (от Тьютора Линк)
        "bridge_to_reality": {
            "conversation_starters": [
                f"Расскажи мне, что тебе больше всего понравилось в истории?",
                f"Как ты думаешь, почему {child_name} сделал именно такой выбор?",
                f"Бывало ли у тебя похожее чувство в жизни?",
            ],
            "activities": a12_data.get("activities", [
                "Нарисовать любимую сцену из истории",
                "Придумать продолжение — что будет дальше?",
                "Поиграть в «а что, если?» — перебрать другие варианты",
            ]),
            "real_life_connections": a12_data.get("real_life_connections", []),
        },
        
        # Рекомендации по следующей теме
        "next_story_hints": {
            "suggested_theme": _suggest_next_theme(a09_data, master_brief),
            "areas_to_explore": a09_data.get("growth_zones", [])[:2],
        },
    }
    
    # Сохраняем
    basket_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    basket_path = basket_dir / f"basket_{basket_id}.json"
    basket_path.write_text(
        json.dumps(basket, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    # Также сохраняем «последнюю» для быстрого доступа кабинетом
    latest_path = basket_dir / "latest.json"
    latest_path.write_text(
        json.dumps(basket, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    print(f"[ТЬЮТОР ЛИНК] 🎁 Корзинка Даров для «{child_name}»: "
          f"{len(basket['parent_insights'])} инсайтов, "
          f"{len(basket['bridge_to_reality']['activities'])} активностей")
    
    return basket


def _suggest_next_theme(a09_data: dict, master_brief: dict) -> str:
    """Предлагает тему следующей истории на основе зон роста."""
    growth_zones = a09_data.get("growth_zones", [])
    current_theme = master_brief.get("theme", "")
    
    theme_map = {
        "смелость": "дружба",
        "дружба": "прощение",
        "прощение": "честность",
        "честность": "принятие",
        "принятие": "помощь",
        "помощь": "смелость",
    }
    
    # Если есть зоны роста — предлагаем тему, которая их затрагивает
    for zone in growth_zones:
        zone_lower = zone.lower() if isinstance(zone, str) else ""
        if "самостоятел" in zone_lower:
            return "самостоятельность"
        if "риск" in zone_lower or "осторожн" in zone_lower:
            return "смелость"
        if "помощ" in zone_lower:
            return "дружба"
    
    # Иначе — следующая по кругу
    return theme_map.get(current_theme, "дружба")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ХРОНОС МЕМО (A02) — Архивация сессии
# ═══════════════════════════════════════════════════════════════════════════════

def archive_session(
    child_name: str,
    books_dir: Path,
    pipeline_results: dict,
    master_brief: dict,
) -> dict:
    """
    Хронос Мемо архивирует сессию:
    - Сохраняет «кармический след» в biography.json
    - Очищает оперативные данные
    - Формирует summary для будущих ранов
    """
    safe_name = child_name.lower().replace(" ", "_")
    bio_path = books_dir / safe_name / "biography.json"
    bio_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Загружаем или создаём биографию
    if bio_path.exists():
        biography = json.loads(bio_path.read_text(encoding="utf-8"))
    else:
        biography = {
            "child_name": child_name,
            "created_at": datetime.now().isoformat(),
            "total_stories": 0,
            "karmic_trail": [],        # Кармические следы — краткие записи
            "character_bonds": {},      # Связи с персонажами
            "world_knowledge": [],      # Что ребёнок узнал о мире Грондхейм
            "emotional_milestones": [], # Эмоциональные вехи
        }
    
    # Извлекаем ключевые данные из рана
    a00_raw = pipeline_results.get("A00", "")
    a16_raw = pipeline_results.get("A16", "")
    
    # Определяем персонажей из рана
    characters_seen = set()
    for key in ["A00", "A16"]:
        raw = pipeline_results.get(key, "")
        if isinstance(raw, str):
            for char in ["Эйрик", "Пиксель", "Искорка", "Ева Эпик", "Лока"]:
                if char in raw:
                    characters_seen.add(char)
    
    # Формируем кармический след
    trail_entry = {
        "date": datetime.now().isoformat(),
        "story_id": f"story_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "theme": master_brief.get("theme", "unknown"),
        "task_context": master_brief.get("task_context", ""),
        "emotional_goal": master_brief.get("emotional_goal", ""),
        "characters_met": list(characters_seen),
        "key_message": master_brief.get("key_message", master_brief.get("purpose", "")),
        "world": master_brief.get("world", "Грондхейм"),
    }
    
    # Обновляем биографию
    biography["total_stories"] += 1
    biography["updated_at"] = datetime.now().isoformat()
    biography["karmic_trail"].append(trail_entry)
    
    # Обновляем связи с персонажами
    for char in characters_seen:
        biography["character_bonds"][char] = \
            biography["character_bonds"].get(char, 0) + 1
    
    # Ограничиваем историю (последние 100 следов)
    if len(biography["karmic_trail"]) > 100:
        biography["karmic_trail"] = biography["karmic_trail"][-100:]
    
    # Сохраняем
    bio_path.write_text(
        json.dumps(biography, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    print(f"[ХРОНОС МЕМО] ⏳ Биография «{child_name}» обновлена: "
          f"{biography['total_stories']} историй, "
          f"{len(biography['character_bonds'])} персонажей, "
          f"{len(biography['karmic_trail'])} следов")
    
    return biography


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ПРОГУЛКА АГЕНТОВ (опционально — если подключена Студия)
# ═══════════════════════════════════════════════════════════════════════════════

def trigger_agent_walks(
    pipeline_results: dict,
    studio_root: Optional[Path] = None,
):
    """
    После рана агенты живой книги «гуляют» по Грондхейму:
    - Записывают sensory_event о завершённой работе
    - sync_to_dna обновляет их стресс/свет
    - Если подключена Студия — вызывают city_walk_workshop
    
    Это делает агентов «живыми» — каждый ран меняет их DNA.
    """
    if not studio_root or not (studio_root / "studio" / "grondheim_memory.py").exists():
        print("[ПРОГУЛКА] ⚠️ Студия не подключена — прогулки отложены")
        return
    
    try:
        import sys
        sys.path.insert(0, str(studio_root))
        from studio.grondheim_memory import (
            on_agent_done,
            record_sensory_event,
            sync_to_dna,
        )
        
        agents_walked = 0
        for agent_id, result in pipeline_results.items():
            if not agent_id.startswith("A"):
                continue
            
            # Определяем качество работы
            if isinstance(result, dict) and result.get("status") == "stub":
                continue  # Пропускаем заглушки
            
            quality = 0.7  # Дефолт — хорошая работа
            
            # on_agent_done — обновляет streak, stress, DNA
            on_agent_done(
                agent_id=agent_id,
                result_summary=f"Завершил работу в пайплайне living_book",
                quality_score=quality,
                dept="living_book",
            )
            
            # sensory_event — «воспоминание» о работе
            record_sensory_event(
                agent_id=agent_id,
                dept="living_book",
                feeling=f"Закончил работу над книгой. Чувствую {'удовлетворение' if quality > 0.6 else 'усталость'}.",
                location="Мастерская Живой Книги",
                tags=["работа", "living_book", "завершение"],
            )
            
            # sync_to_dna — стресс снижается после завершения
            sync_to_dna(
                agent_id=agent_id,
                event="task_completed",
                intensity=0.3,
                dept="living_book",
            )
            
            agents_walked += 1
        
        print(f"[ПРОГУЛКА] 🚶 {agents_walked} агентов обновили DNA после рана")
        
    except Exception as e:
        print(f"[ПРОГУЛКА] ⚠️ Ошибка: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ — вызывается из beacon.py
# ═══════════════════════════════════════════════════════════════════════════════

def run_post_reflection(
    child_name: str,
    books_dir: Path,
    pipeline_results: dict,
    master_brief: dict,
    studio_root: Optional[Path] = None,
) -> dict:
    """
    Полная пост-ранная рефлексия.
    Вызывается из beacon.py после run_full_pipeline().
    
    Возвращает dict с результатами всех фаз.
    """
    print(f"\n{'─'*60}")
    print(f"🧘 ПОСТ-РАННАЯ РЕФЛЕКСИЯ для «{child_name}»")
    print(f"{'─'*60}")
    
    results = {}
    
    # Извлекаем данные агентов из рана
    a09_output = _extract_agent_meta(pipeline_results.get("A09", ""))
    a12_output = _extract_agent_meta(pipeline_results.get("A12", ""))
    
    # 1. Линза Стат → профиль ребёнка
    try:
        profile = update_child_profile(child_name, books_dir, a09_output, master_brief)
        results["child_profile"] = profile
    except Exception as e:
        print(f"[ЛИНЗА СТАТ] ❌ {e}")
    
    # 2. Тьютор Линк → Корзинка Даров
    try:
        basket = build_gift_basket(child_name, books_dir, a12_output, a09_output, master_brief)
        results["gift_basket"] = basket
    except Exception as e:
        print(f"[ТЬЮТОР ЛИНК] ❌ {e}")
    
    # 3. Хронос Мемо → архивация
    try:
        biography = archive_session(child_name, books_dir, pipeline_results, master_brief)
        results["biography"] = biography
    except Exception as e:
        print(f"[ХРОНОС МЕМО] ❌ {e}")
    
    # 4. Прогулка агентов
    trigger_agent_walks(pipeline_results, studio_root)
    
    print(f"{'─'*60}")
    print(f"✅ Рефлексия завершена")
    print(f"{'─'*60}\n")
    
    return results


def _extract_agent_meta(raw) -> dict:
    """Извлекает my_output из сырого результата агента."""
    if isinstance(raw, dict):
        return raw
    
    if not isinstance(raw, str):
        return {}
    
    # Ищем SYSTEM_JSON
    import re
    match = re.search(r"SYSTEM_JSON_START\s*(.*?)\s*SYSTEM_JSON_END", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return data.get("my_output", data)
        except json.JSONDecodeError:
            pass
    
    # Ищем ```json
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    
    return {}

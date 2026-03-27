"""Event Log — фиксация событий для родительского кабинета.

Каждое действие ребёнка записывается в лог.
Родитель видит: выборы, диалоги, время сессий, артефакты.
"""
import json
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

EVENTS_DIR = Path("../events")


def ensure_events_dir():
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)


def log_event(child_id: str, event_type: str, data: dict):
    """Записать событие в лог ребёнка.

    event_type: choice | chat | session_start | session_end | artifact | tutor_link
    """
    ensure_events_dir()
    path = EVENTS_DIR / f"{child_id}.jsonl"

    event = {
        "ts": datetime.now().isoformat(),
        "epoch": time.time(),
        "type": event_type,
        **data,
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event


def get_events(child_id: str, limit: int = 50, event_type: Optional[str] = None) -> list:
    """Получить последние события ребёнка."""
    path = EVENTS_DIR / f"{child_id}.jsonl"
    if not path.exists():
        return []

    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if event_type and ev.get("type") != event_type:
                    continue
                events.append(ev)
            except json.JSONDecodeError:
                continue

    # Последние N
    return events[-limit:]


def get_session_stats(child_id: str) -> dict:
    """Статистика по сессиям ребёнка."""
    events = get_events(child_id, limit=10000)

    total_choices = len([e for e in events if e["type"] == "choice"])
    total_chats = len([e for e in events if e["type"] == "chat"])
    total_sessions = len([e for e in events if e["type"] == "session_start"])

    # Собранные артефакты
    artifacts = [
        e.get("artifact", "") for e in events
        if e["type"] == "artifact" and e.get("artifact")
    ]

    # Все выборы
    choices = [
        e.get("choice_label", "") for e in events
        if e["type"] == "choice" and e.get("choice_label")
    ]

    # Все триггеры памяти
    memory_tags = []
    for e in events:
        for t in e.get("triggers", []):
            tag = t.replace("memory:", "").replace("artifact:", "")
            if tag and tag not in memory_tags:
                memory_tags.append(tag)

    # Время последней активности
    last_active = events[-1]["ts"] if events else None

    return {
        "child_id": child_id,
        "total_sessions": total_sessions,
        "total_choices": total_choices,
        "total_chats": total_chats,
        "artifacts": artifacts,
        "choices_history": choices,
        "memory_tags": memory_tags,
        "last_active": last_active,
    }


def save_tutor_context(child_id: str, context: str):
    """Родитель вписывает контекст дня (Тьютор Линк)."""
    return log_event(child_id, "tutor_link", {"context": context})


def get_tutor_context(child_id: str) -> Optional[str]:
    """Получить последний контекст от родителя."""
    events = get_events(child_id, event_type="tutor_link")
    if events:
        return events[-1].get("context")
    return None

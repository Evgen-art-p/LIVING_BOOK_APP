"""Parent API — эндпоинты для родительского кабинета.

Подключается к основному FastAPI приложению как роутер.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from event_log import (
    get_events,
    get_session_stats,
    save_tutor_context,
    get_tutor_context,
)

router = APIRouter(prefix="/parent", tags=["parent"])

DEFAULT_CHILD = "default"


class TutorRequest(BaseModel):
    context: str
    child_id: str = DEFAULT_CHILD


@router.get("/feed")
def get_feed(child_id: str = DEFAULT_CHILD, limit: int = 20):
    """Лента событий — что происходит с ребёнком."""
    events = get_events(child_id, limit=limit)
    # Обратный порядок — новые сверху
    events.reverse()
    return {"child_id": child_id, "events": events}


@router.get("/stats")
def get_stats(child_id: str = DEFAULT_CHILD):
    """Статистика: сколько сессий, выборов, чатов, артефактов."""
    return get_session_stats(child_id)


@router.post("/tutor")
def set_tutor(req: TutorRequest):
    """Тьютор Линк — родитель вписывает контекст дня."""
    event = save_tutor_context(req.child_id, req.context)
    return {"status": "ok", "event": event}


@router.get("/tutor")
def get_tutor(child_id: str = DEFAULT_CHILD):
    """Получить текущий контекст от родителя."""
    ctx = get_tutor_context(child_id)
    return {"child_id": child_id, "context": ctx}

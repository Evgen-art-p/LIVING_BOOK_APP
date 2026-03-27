"""Alive Book — сервер v0.5

Фаза 1: сцены + выборы
Фаза 2: free_talk через OpenRouter
Фаза 5: родительский кабинет (/parent/*)
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

from story_engine import StoryEngine
from ai_brain import chat_with_character
from memory import save_session, load_session
from event_log import log_event, get_tutor_context
from parent_api import router as parent_router

app = FastAPI(title="Alive Book Player", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Родительский кабинет — статика
dashboard_path = Path("../dashboard")
if dashboard_path.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")

# Подключаем родительский API
app.include_router(parent_router)

engine = StoryEngine(book_path="../books/grondheim_01")

# ID ребёнка по умолчанию (позже — из авторизации)
CHILD_ID = "default"


class ChoiceRequest(BaseModel):
    choice_id: str

class ChatRequest(BaseModel):
    message: str

class SessionRequest(BaseModel):
    child_id: str = "default"


@app.get("/")
def root():
    return {
        "status": "ok",
        "book": engine.book.get("title", "Unknown"),
        "version": "0.5.0",
        "dashboard": "/dashboard/",
    }


@app.get("/scene")
def get_scene():
    scene = engine.get_current_scene()
    if not scene:
        raise HTTPException(status_code=404, detail="Сцена не найдена")
    return scene


@app.post("/choice")
def make_choice(req: ChoiceRequest):
    scene = engine.get_current_scene()
    next_scene = engine.make_choice(req.choice_id)
    if not next_scene:
        raise HTTPException(status_code=400, detail="Неверный выбор")

    # Логируем для родителя
    chosen = None
    if scene and "choices" in scene:
        for c in scene["choices"]:
            if c["id"] == req.choice_id:
                chosen = c
                break

    log_event(CHILD_ID, "choice", {
        "choice_id": req.choice_id,
        "choice_label": chosen["label"] if chosen else req.choice_id,
        "triggers": chosen.get("triggers", []) if chosen else [],
        "scene_id": scene["id"] if scene else "",
        "speaker": scene.get("speaker", "") if scene else "",
    })

    # Если выбор дал артефакт — отдельное событие
    if chosen:
        for t in chosen.get("triggers", []):
            if t.startswith("artifact:"):
                log_event(CHILD_ID, "artifact", {
                    "artifact": t.replace("artifact:", ""),
                })

    return next_scene


@app.post("/chat")
async def chat(req: ChatRequest):
    scene = engine.get_current_scene()
    if not scene:
        raise HTTPException(status_code=404, detail="Сцена не найдена")

    if scene.get("mode") != "free_talk":
        raise HTTPException(status_code=400, detail="Сцена не в режиме free_talk")

    speaker_id = scene.get("speaker", "")
    character = engine.characters.get(speaker_id, {})

    engine.history.append({"role": "child", "text": req.message})

    # Инжектим контекст от родителя (Тьютор Линк)
    tutor_ctx = get_tutor_context(CHILD_ID)
    enriched_config = dict(engine.config)
    if tutor_ctx:
        # Добавляем контекст дня в инструкции сцены
        enriched_scene = dict(scene)
        existing = enriched_scene.get("ai_instructions", "")
        enriched_scene["ai_instructions"] = (
            f"{existing}\n\n"
            f"КОНТЕКСТ ДНЯ ОТ РОДИТЕЛЯ: {tutor_ctx}\n"
            f"Учитывай это в разговоре, если уместно."
        )
    else:
        enriched_scene = scene

    reply = await chat_with_character(
        character=character,
        scene=enriched_scene,
        history=engine.history,
        child_message=req.message,
        memory=engine.memory,
        ethics=engine.ethics,
        config=enriched_config,
    )

    engine.history.append({"role": "character", "text": reply})

    # Логируем для родителя
    log_event(CHILD_ID, "chat", {
        "speaker": character.get("name", speaker_id),
        "child_said": req.message,
        "character_said": reply,
    })

    max_turns = scene.get("max_turns", 999)
    child_turns = len([m for m in engine.history if m["role"] == "child"])
    is_finished = child_turns >= max_turns

    result = {
        "speaker": character.get("name", speaker_id),
        "text": reply,
        "turns_left": max(0, max_turns - child_turns),
        "is_finished": is_finished,
    }

    if is_finished:
        next_scene_id = scene.get("on_end")
        if next_scene_id:
            engine.current_scene_id = next_scene_id
            engine.history = []
            result["next_scene"] = engine.get_current_scene()

    return result


@app.get("/state")
def get_state():
    return engine.get_state()


@app.post("/save")
def save(req: SessionRequest):
    state = engine.get_state()
    save_session(req.child_id, state)
    log_event(req.child_id, "session_end", {"state": state})
    return {"status": "saved", "child_id": req.child_id}


@app.post("/load")
def load(req: SessionRequest):
    state = load_session(req.child_id)
    if not state:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    engine.load_state(state)
    log_event(req.child_id, "session_start", {"state": state})
    return {"status": "loaded", "child_id": req.child_id, "scene": engine.get_current_scene()}

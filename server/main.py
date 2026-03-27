"""Alive Book — сервер приложения v0.2

Эндпоинты:
- GET  /scene       — текущая сцена
- POST /choice      — отправить выбор
- POST /chat        — свободный диалог (free_talk)
- GET  /state       — текущее состояние
- POST /save        — сохранить сессию
- POST /load        — загрузить сессию
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from story_engine import StoryEngine
from ai_brain import chat_with_character
from memory import save_session, load_session

app = FastAPI(title="Alive Book Player", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = StoryEngine(book_path="../books/grondheim_01")


class ChoiceRequest(BaseModel):
    choice_id: str

class ChatRequest(BaseModel):
    message: str

class SessionRequest(BaseModel):
    child_id: str


@app.get("/")
def root():
    return {"status": "ok", "book": engine.book.get("title", "Unknown"), "version": "0.2.0"}


@app.get("/scene")
def get_scene():
    scene = engine.get_current_scene()
    if not scene:
        raise HTTPException(status_code=404, detail="Сцена не найдена")
    return scene


@app.post("/choice")
def make_choice(req: ChoiceRequest):
    next_scene = engine.make_choice(req.choice_id)
    if not next_scene:
        raise HTTPException(status_code=400, detail="Неверный выбор")
    return next_scene


@app.post("/chat")
async def chat(req: ChatRequest):
    """Свободный диалог с персонажем (free_talk сцены)."""
    scene = engine.get_current_scene()
    if not scene:
        raise HTTPException(status_code=404, detail="Сцена не найдена")

    if scene.get("mode") != "free_talk":
        raise HTTPException(status_code=400, detail="Сцена не в режиме free_talk")

    speaker_id = scene.get("speaker", "")
    character = engine.characters.get(speaker_id, {})

    # Добавляем сообщение ребёнка
    engine.history.append({"role": "child", "text": req.message})

    # Ответ от LLM
    reply = await chat_with_character(
        character=character,
        scene=scene,
        history=engine.history,
        child_message=req.message,
        memory=engine.memory,
        ethics=engine.ethics,
        config=engine.config,
    )

    # Добавляем ответ персонажа
    engine.history.append({"role": "character", "text": reply})

    # Лимит реплик
    max_turns = scene.get("max_turns", 999)
    child_turns = len([m for m in engine.history if m["role"] == "child"])
    is_finished = child_turns >= max_turns

    result = {
        "speaker": character.get("name", speaker_id),
        "text": reply,
        "turns_left": max(0, max_turns - child_turns),
        "is_finished": is_finished,
    }

    # Диалог закончился — переход
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
    return {"status": "saved", "child_id": req.child_id}


@app.post("/load")
def load(req: SessionRequest):
    state = load_session(req.child_id)
    if not state:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    engine.load_state(state)
    return {"status": "loaded", "child_id": req.child_id, "scene": engine.get_current_scene()}

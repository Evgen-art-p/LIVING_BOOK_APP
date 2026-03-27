"""Living Book — сервер приложения.

FastAPI. Три простых эндпоинта для начала:
- GET  /scene  — текущая сцена
- POST /choice — отправить выбор
- GET  /state  — текущее состояние
"""
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from story_engine import StoryEngine

app = FastAPI(title="Living Book Player", version="0.1.0")

# Разрешаем запросы от фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Загружаем книжку при старте
# TODO: сделать динамическую загрузку разных книг
engine = StoryEngine(book_path="../books/grondheim_01")


class ChoiceRequest(BaseModel):
    choice_id: str


@app.get("/")
def root():
    return {"status": "ok", "book": engine.book.get("title", "Unknown")}


@app.get("/scene")
def get_scene():
    """Получить текущую сцену."""
    scene = engine.get_current_scene()
    if not scene:
        raise HTTPException(status_code=404, detail="Сцена не найдена")
    return scene


@app.post("/choice")
def make_choice(req: ChoiceRequest):
    """Ребёнок делает выбор."""
    next_scene = engine.make_choice(req.choice_id)
    if not next_scene:
        raise HTTPException(status_code=400, detail="Неверный выбор")
    return next_scene


@app.get("/state")
def get_state():
    """Текущее состояние игры."""
    return engine.get_state()

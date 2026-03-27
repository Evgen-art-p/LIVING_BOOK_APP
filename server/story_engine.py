"""Story Engine — мозг плеера.

Загружает книжку (Book Package), держит состояние сессии,
навигирует по сценам, обрабатывает выборы ребёнка.
"""
import json
from pathlib import Path
from typing import Optional


class StoryEngine:
    """Движок истории. Одна сессия = один ребёнок + одна книжка."""

    def __init__(self, book_path: str):
        self.book_path = Path(book_path)
        self.book = self._load_json(self.book_path / "book.json")
        self.chapters: dict = {}       # id → chapter data
        self.characters: dict = {}     # id → character data
        self.ethics: dict = {}         # этический фильтр
        self.config: dict = {}         # настройки ИИ

        # Состояние сессии
        self.current_chapter_id: str = self.book["starting_chapter"]
        self.current_scene_id: str = self.book["starting_scene"]
        self.memory: list = []         # список триггеров (выборов ребёнка)
        self.history: list = []        # история диалога в free_talk

        self._load_all()

    # ── загрузка ────────────────────────────────────────

    def _load_json(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_all(self):
        """Загружаем все части книжки в память."""
        # Главы
        for ch in self.book["chapters"]:
            data = self._load_json(self.book_path / ch["file"])
            self.chapters[ch["id"]] = data

        # Персонажи
        for char in self.book["characters"]:
            data = self._load_json(self.book_path / char["file"])
            self.characters[char["id"]] = data

        # Этика и конфиг
        ethics_path = self.book_path / "ethics.json"
        if ethics_path.exists():
            self.ethics = self._load_json(ethics_path)

        config_path = self.book_path / "config.json"
        if config_path.exists():
            self.config = self._load_json(config_path)

    # ── навигация ───────────────────────────────────────

    def get_current_scene(self) -> Optional[dict]:
        """Вернуть текущую сцену."""
        chapter = self.chapters.get(self.current_chapter_id)
        if not chapter:
            return None
        for scene in chapter["scenes"]:
            if scene["id"] == self.current_scene_id:
                # Добавляем данные персонажа
                speaker_id = scene.get("speaker")
                if speaker_id and speaker_id in self.characters:
                    scene["character"] = self.characters[speaker_id]
                return scene
        return None

    def make_choice(self, choice_id: str) -> Optional[dict]:
        """Ребёнок выбрал вариант. Обновляем состояние."""
        scene = self.get_current_scene()
        if not scene or "choices" not in scene:
            return None

        # Найти выбранный вариант
        chosen = None
        for choice in scene["choices"]:
            if choice["id"] == choice_id:
                chosen = choice
                break

        if not chosen:
            return None

        # Запомнить триггеры
        for trigger in chosen.get("triggers", []):
            self.memory.append(trigger)

        # Перейти к следующей сцене
        next_scene = chosen["next_scene"]

        # Проверить — сцена в текущей главе или в другой?
        if self._find_scene_in_chapter(self.current_chapter_id, next_scene):
            self.current_scene_id = next_scene
        else:
            # Ищем в других главах
            for ch_id, ch_data in self.chapters.items():
                if self._find_scene_in_chapter(ch_id, next_scene):
                    self.current_chapter_id = ch_id
                    self.current_scene_id = next_scene
                    break

        return self.get_current_scene()

    def _find_scene_in_chapter(self, chapter_id: str, scene_id: str) -> bool:
        chapter = self.chapters.get(chapter_id)
        if not chapter:
            return False
        return any(s["id"] == scene_id for s in chapter["scenes"])

    # ── состояние ───────────────────────────────────────

    def get_state(self) -> dict:
        """Полное состояние для сохранения/восстановления."""
        return {
            "book_id": self.book["id"],
            "current_chapter": self.current_chapter_id,
            "current_scene": self.current_scene_id,
            "memory": self.memory,
            "history": self.history,
        }

    def load_state(self, state: dict):
        """Восстановить состояние (при повторном входе ребёнка)."""
        self.current_chapter_id = state["current_chapter"]
        self.current_scene_id = state["current_scene"]
        self.memory = state.get("memory", [])
        self.history = state.get("history", [])

"""Memory — сохранение состояния между сессиями."""
import json
from pathlib import Path
from typing import Optional

SAVES_DIR = Path("../saves")

def ensure_saves_dir():
    SAVES_DIR.mkdir(parents=True, exist_ok=True)

def save_session(child_id: str, state: dict):
    ensure_saves_dir()
    path = SAVES_DIR / f"{child_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_session(child_id: str) -> Optional[dict]:
    path = SAVES_DIR / f"{child_id}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def list_sessions() -> list:
    ensure_saves_dir()
    return [p.stem for p in SAVES_DIR.glob("*.json")]

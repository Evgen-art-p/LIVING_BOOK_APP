"""
beacon.py — Ночной Маяк (Студия, домашний сервер)

Это НЕ сервер реального времени.
Принимает батч раз в сутки. Обновляет пакеты. Больше ничего.

Запуск:
    pip install fastapi uvicorn
    uvicorn beacon:app --host 0.0.0.0 --port 8001
"""

import json
import sqlite3
import os
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Ночной Маяк", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "..", "books")
BEACON_DB    = os.path.join(os.path.dirname(__file__), "beacon.db")

# ─── БАЗА ДАННЫХ МАЯКА ────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(BEACON_DB) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id  TEXT NOT NULL,
                session_id TEXT NOT NULL,
                synced_at  TEXT NOT NULL,
                event_count INTEGER
            );
            CREATE TABLE IF NOT EXISTS aggregate_tags (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                tag       TEXT NOT NULL,
                ts        TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aggregate_choices (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                choice_id TEXT NOT NULL,
                ts        TEXT NOT NULL
            );
        """)

init_db()

# ─── СХЕМА БАТЧА ──────────────────────────────────────────────────────────────

class BeaconEvent(BaseModel):
    type:      str                 # 'choice' | 'tag' | 'utterance'
    ts:        int
    choice_id: Optional[str] = None
    tag:       Optional[str] = None
    # текст реплик сюда НЕ ПОПАДАЕТ — только мета-данные

class BeaconBatch(BaseModel):
    device_id:  str
    session_id: str
    synced_at:  str
    events:     list[BeaconEvent]

# ─── ПРИЁМ БАТЧА ──────────────────────────────────────────────────────────────

@app.post("/beacon")
async def receive_beacon(batch: BeaconBatch):
    """
    Принимает обезличенный батч с телефона.
    Сохраняет агрегированные мета-данные.
    Возвращает обновлённый пакет (если есть).
    """
    with sqlite3.connect(BEACON_DB) as conn:
        # Лог синхронизации
        conn.execute(
            "INSERT INTO sync_log (device_id, session_id, synced_at, event_count) VALUES (?,?,?,?)",
            (batch.device_id, batch.session_id, batch.synced_at, len(batch.events))
        )

        for event in batch.events:
            ts_str = datetime.utcfromtimestamp(event.ts / 1000).isoformat()

            if event.type == 'tag' and event.tag:
                conn.execute(
                    "INSERT INTO aggregate_tags (device_id, tag, ts) VALUES (?,?,?)",
                    (batch.device_id, event.tag, ts_str)
                )
            elif event.type == 'choice' and event.choice_id:
                conn.execute(
                    "INSERT INTO aggregate_choices (device_id, choice_id, ts) VALUES (?,?,?)",
                    (batch.device_id, event.choice_id, ts_str)
                )

    print(f"[Маяк] Получен батч от {batch.device_id}: {len(batch.events)} событий")

    # Проверяем — есть ли обновлённый пакет для этого устройства
    updated_package = check_for_update(batch.device_id)

    return {
        "ok": True,
        "received": len(batch.events),
        "new_package_url": updated_package,   # None если обновлений нет
    }

def check_for_update(device_id: str) -> Optional[str]:
    """
    Проверяет наличие персонализированного обновлённого пакета.
    Пока возвращает None — в будущем здесь логика Studio.
    """
    # TODO: Studio агенты генерируют персонализированные обновления
    # и кладут их в /books/updates/{device_id}/
    update_path = os.path.join(PACKAGES_DIR, "updates", device_id, "book.json")
    if os.path.exists(update_path):
        return f"/packages/{device_id}/book.json"
    return None

# ─── СТАТИСТИКА ДЛЯ СТУДИИ ────────────────────────────────────────────────────

@app.get("/stats")
def stats():
    """Агрегированная статистика по всем устройствам (для Studio)."""
    with sqlite3.connect(BEACON_DB) as conn:
        devices = conn.execute("SELECT COUNT(DISTINCT device_id) FROM sync_log").fetchone()[0]
        syncs   = conn.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0]
        top_tags = conn.execute(
            "SELECT tag, COUNT(*) as c FROM aggregate_tags GROUP BY tag ORDER BY c DESC LIMIT 10"
        ).fetchall()
        top_choices = conn.execute(
            "SELECT choice_id, COUNT(*) as c FROM aggregate_choices GROUP BY choice_id ORDER BY c DESC LIMIT 10"
        ).fetchall()

    return {
        "total_devices": devices,
        "total_syncs":   syncs,
        "top_tags":    [{"tag": r[0], "count": r[1]} for r in top_tags],
        "top_choices": [{"choice_id": r[0], "count": r[1]} for r in top_choices],
    }

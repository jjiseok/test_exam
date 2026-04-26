import os
import sqlite3
from pathlib import Path
from typing import Iterable, Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = os.environ.get("DB_PATH", str(DATA_DIR / "exam_supervision.db"))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_all(query: str, params: Iterable[Any] = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]


def fetch_one(query: str, params: Iterable[Any] = ()) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
        return dict(row) if row else None


def execute(query: str, params: Iterable[Any] = ()) -> int:
    with get_conn() as conn:
        cur = conn.execute(query, tuple(params))
        conn.commit()
        return cur.lastrowid


def executemany(query: str, rows: list[Iterable[Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(query, rows)
        conn.commit()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                subject TEXT DEFAULT '',
                is_homeroom INTEGER DEFAULT 0,
                grade TEXT DEFAULT '',
                class_no TEXT DEFAULT '',
                department TEXT DEFAULT '',
                can_supervise INTEGER DEFAULT 1,
                exclude_chief INTEGER DEFAULT 0,
                exclude_assistant INTEGER DEFAULT 0,
                exclude_hallway INTEGER DEFAULT 0,
                exclude_dates TEXT DEFAULT '',
                exclude_periods TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                school_year INTEGER NOT NULL,
                semester INTEGER NOT NULL,
                exam_round INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS exam_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL,
                exam_date TEXT NOT NULL,
                period_no INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                grade TEXT NOT NULL,
                subject TEXT NOT NULL,
                room_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(exam_id) REFERENCES exams(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL,
                slot_id INTEGER NOT NULL,
                exam_date TEXT NOT NULL,
                period_no INTEGER NOT NULL,
                time_label TEXT NOT NULL,
                grade TEXT NOT NULL,
                subject TEXT NOT NULL,
                room_name TEXT NOT NULL,
                role TEXT NOT NULL,
                teacher_id INTEGER,
                teacher_name TEXT NOT NULL,
                teacher_subject TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(exam_id) REFERENCES exams(id) ON DELETE CASCADE,
                FOREIGN KEY(slot_id) REFERENCES exam_slots(id) ON DELETE CASCADE,
                FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE SET NULL
            );
            """
        )
        conn.commit()

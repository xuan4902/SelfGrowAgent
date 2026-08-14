"""SQLite 关系型存储：连接 + schema 初始化 + 通用 CRUD。

数据表与学习闭环对应：
learners / assessments / plans / learning_records / spar_sessions / reviews / knowledge_docs
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from selfgrow.paths import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS learners (
    id          TEXT PRIMARY KEY,
    goal        TEXT NOT NULL DEFAULT '',
    xp          INTEGER NOT NULL DEFAULT 0,
    level       INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS assessments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,           -- baseline | reassess
    radar_json  TEXT NOT NULL,
    gaps_json   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS plans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id    TEXT NOT NULL,
    plan_json     TEXT NOT NULL,
    current_week  INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS learning_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id  TEXT NOT NULL,
    week        INTEGER NOT NULL,
    dimension   TEXT NOT NULL,
    lesson      TEXT NOT NULL DEFAULT '',
    knowledge_hits_json TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS spar_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id      TEXT NOT NULL,
    week            INTEGER NOT NULL,
    scenario_id     TEXT NOT NULL,
    transcript_json TEXT NOT NULL DEFAULT '[]',
    feedback_json   TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id  TEXT NOT NULL,
    week        INTEGER NOT NULL,
    kolb_json   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS knowledge_docs (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    path        TEXT NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    """轻量 SQLite 封装：惰性建库、通用插入/查询。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(DB_PATH)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---- 通用 ----
    def insert(self, table: str, data: dict[str, Any]) -> int:
        cols = list(data.keys())
        placeholders = ", ".join("?" * len(cols))
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
        cur = self._conn.execute(sql, [data[c] for c in cols])
        self._conn.commit()
        return int(cur.lastrowid)

    def insert_many(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        placeholders = ", ".join("?" * len(cols))
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
        self._conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])
        self._conn.commit()

    def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._conn.execute(sql, params)
        self._conn.commit()

    @staticmethod
    def dumps(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def loads(text: str | None, default: Any = None) -> Any:
        if not text:
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return default

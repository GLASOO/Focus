"""Focus Agent — 可观测层（事件溯源，学 DeepSeek Harness Trajectory）。

仅追加 events 表：每个重要动作（记忆落账/工具调用/梦完成）留下不可变痕迹，
可随时回放。emit 永不抛异常——可观测不许拖累主路径（此机不停）。
"""
from __future__ import annotations

import json
from typing import Optional

KINDS = ("memory", "tool", "dream", "error")  # 事件类型（开放扩展）


class EventLog:
    """事件溯源日志。一个 GraphDB 一个实例，schema 幂等。"""

    def __init__(self, db):
        self.db = db
        self.ensure_schema()

    def ensure_schema(self) -> None:
        try:
            self.db.conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT DEFAULT (datetime('now')),
                    kind TEXT NOT NULL,
                    actor TEXT,
                    payload TEXT)""")
            self.db.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_kind "
                "ON events(kind, id)")
            self.db.conn.commit()
        except Exception:
            pass

    def emit(self, kind: str, actor: str = "", payload: Optional[dict] = None):
        """追加一条事件。任何异常静默吞掉。"""
        try:
            self.db.conn.execute(
                "INSERT INTO events (kind, actor, payload) VALUES (?,?,?)",
                (kind, actor,
                 json.dumps(payload or {}, ensure_ascii=False)[:2000]))
            self.db.conn.commit()
        except Exception:
            pass

    def recent(self, n: int = 50, kind: Optional[str] = None) -> list:
        """最近 n 条事件（Trajectory 回放的数据源）。"""
        try:
            if kind:
                rows = self.db.conn.execute(
                    "SELECT * FROM events WHERE kind=? ORDER BY id DESC LIMIT ?",
                    (kind, n)).fetchall()
            else:
                rows = self.db.conn.execute(
                    "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                    (n,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def trajectory(self, actor: str, n: int = 20) -> list:
        """按 actor（如节点 id 前缀）回放事件链。"""
        try:
            rows = self.db.conn.execute(
                "SELECT * FROM events WHERE actor LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{actor}%", n)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

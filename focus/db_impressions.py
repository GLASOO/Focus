"""GraphDB 拆分模块（2026-08-15 工程债清理）——ImpressionsMixin。

原 graph_db.py 巨石（991行）按职责拆分；GraphDB 门面类组合各 mixin。
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from typing import Any, Optional

import numpy as np
from loguru import logger

from .db_core import DB_LOCK


class ImpressionsMixin:

    def add_impression(self, source_id: str, content: str,
                       culture_type: str = "knowledge",
                       attraction_value: float = 0.3,
                       lineage: str = "") -> str:
        """创建 impression 节点（DMN 压缩产物）。"""
        return self.add_node(
            type="impression", brief=content[:100], content=content,
            source_id=source_id, priority=0.4,
            culture_type=culture_type, attraction_value=attraction_value,
            lineage=lineage,
        )

    # ────────────────────────────────────────────
    # 原文存储（分层记忆第1层）
    # ────────────────────────────────────────────

    def impression_exists(self, source_id: str) -> bool:
        """该 source_id 是否已生成 impression。"""
        row = self.conn.execute(
            "SELECT 1 FROM nodes WHERE type='impression' AND source_id=? LIMIT 1",
            (source_id,),
        ).fetchone()
        return row is not None

    def store_original(self, source_id: str, content: str,
                       meta: Optional[dict] = None) -> str:
        orig_id = uuid.uuid4().hex[:12]
        with DB_LOCK:
            self.conn.execute(
                "INSERT INTO originals (id, source_id, content, meta) VALUES (?, ?, ?, ?)",
                (orig_id, source_id, content, json.dumps(meta or {}, ensure_ascii=False)),
            )
            self.conn.commit()
        return orig_id

    def get_original(self, orig_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM originals WHERE id=?", (orig_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["meta"] = json.loads(d["meta"] or "{}")
        return d

    # ────────────────────────────────────────────
    # Self-Map
    # ────────────────────────────────────────────

    def get_unpatrolled(self, limit: int = 20) -> list[dict]:
        """DMN 巡逻用：没有 embedding 或长时间未巡逻的节点。

        2026-08-13 修复（准验收）：任务书 v2.1 明确 DMN 的职责是
        整理已完成的想法（embedding/连线/压缩 impression），但原 SQL 排除
        status='done'，导致 DMN 永远巡逻不到最重要的对象（done 节点全积压）。
        现在 done 节点只要没巡逻过（或超1小时）就纳入巡逻。
        """
        rows = self.conn.execute(
            """
            SELECT * FROM nodes
            WHERE status NOT IN ('skip')
              AND (embedding IS NULL OR last_patrolled IS NULL
                   OR last_patrolled < datetime('now', '-1 hour'))
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_patrolled(self, node_id: str) -> None:
        self.update_node(node_id, last_patrolled=time.strftime("%Y-%m-%d %H:%M:%S"))

    def get_patrolled(self, limit: int = 20, exclude: str = "") -> list[dict]:
        """最近已巡逻节点（DMN 隐式连线参照）。"""
        q = ("SELECT * FROM nodes WHERE last_patrolled IS NOT NULL "
             "AND embedding IS NOT NULL ")
        params: list = []
        if exclude:
            q += "AND id != ? "
            params.append(exclude)
        q += "ORDER BY last_patrolled DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

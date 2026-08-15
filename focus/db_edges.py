"""GraphDB 拆分模块（2026-08-15 工程债清理）——EdgesMixin。

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


class EdgesMixin:

    def add_edge(self, source_id: str, target_id: str, relation: str = "related",
                 weight: float = 1.0) -> None:
        with DB_LOCK:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO edges (source_id, target_id, relation, weight)
                VALUES (?, ?, ?, ?)
                """,
                (source_id, target_id, relation, weight),
            )
            self.conn.commit()

    def get_edges(self, node_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM edges WHERE source_id=? OR target_id=?",
            (node_id, node_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_neighbors(self, node_id: str, relation: Optional[str] = None) -> list[dict]:
        """返回邻居节点（含 relation 和 weight）。双向匹配。

        边的方向语义（任务书）：
          parent:    父→子（子节点查询时自己是 target）
          depends_on:依赖→被依赖（查询者自己是 target）
          leads_to:  当前→下一个（查询者自己是 source）
        """
        q = (
            "SELECT e.relation, e.weight, n.* FROM edges e "
            "JOIN nodes n ON n.id = "
            "  CASE WHEN e.source_id = ? THEN e.target_id ELSE e.source_id END "
            "WHERE (e.source_id = ? OR e.target_id = ?)"
        )
        params: list = [node_id, node_id, node_id]
        if relation:
            q += " AND e.relation = ?"
            params.append(relation)
        rows = self.conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    # ────────────────────────────────────────────
    # 焦点选择
    # ────────────────────────────────────────────

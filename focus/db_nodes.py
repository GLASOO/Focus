"""GraphDB 拆分模块（2026-08-15 工程债清理）——NodesMixin。

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


class NodesMixin:

    def add_node(self, type: str = "work", brief: str = "", content: str = "",
                 priority: float = 0.5, source_id: str = "", role: str = "",
                 lineage: str = "", shareable: int = 0,
                 culture_type: str = "none", attraction_value: float = 0.0,
                 status: str = "pending", parent_id: Optional[str] = None,
                 **extra: Any) -> str:
        """创建一个节点。返回 node_id。

        v4.0: lineage 默认 'copy_id:node_id'（自己生成的）。
        共享层拉取的节点由调用方传入 'shared:xxx'。
        """
        node_id = uuid.uuid4().hex[:12]
        if not lineage:
            lineage = f"{self.copy_id}:{node_id}"
        with DB_LOCK:
            self.conn.execute(
                """
                INSERT INTO nodes
                    (id, type, status, brief, content, priority, source_id,
                     role, lineage, shareable, culture_type, attraction_value)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, type, status, brief, content, priority, source_id,
                 role, lineage, shareable, culture_type, attraction_value),
            )
            if parent_id:
                self.add_edge(parent_id, node_id, "parent")
                self.conn.execute(
                    "UPDATE nodes SET parent_id=? WHERE id=?", (parent_id, node_id))
            self.conn.commit()
        return node_id

    def get_node(self, node_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return dict(row) if row else None

    def update_node(self, node_id: str, **fields: Any) -> None:
        """按字段名更新节点。白名单校验。"""
        allowed = {
            "type", "status", "brief", "content", "source_output", "summary",
            "hint", "next_focus", "prepared_context", "source_id", "priority",
            "visit_count", "role", "embedding", "lineage", "shareable",
            "culture_type", "attraction_value", "last_patrolled", "structure",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"未知字段: {bad}")
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [node_id]
        with DB_LOCK:
            self.conn.execute(
                f"UPDATE nodes SET {sets}, updated_at=datetime('now') WHERE id=?",
                vals,
            )
            self.conn.commit()

    def delete_node(self, node_id: str) -> None:
        with DB_LOCK:
            self.conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            self.conn.execute("DELETE FROM edges WHERE source_id=? OR target_id=?",
                              (node_id, node_id))
            self.conn.commit()

    def append_source_output(self, node_id: str, text: str) -> None:
        """流式落盘：追加 source_output。"""
        with DB_LOCK:
            self.conn.execute(
                "UPDATE nodes SET source_output = source_output || ?, "
                "updated_at = datetime('now') WHERE id=?",
                (text, node_id),
            )
            self.conn.commit()

    # ────────────────────────────────────────────
    # Edge
    # ────────────────────────────────────────────

    def get_next_focus(self) -> Optional[dict]:
        """选下一个要处理的节点。

        规则（硬编码优先级，从上到下依次检查）：
          0. 冷却期：最近30秒内处理过的节点跳过（防重复呼吸同一念头）
          1. user_input（任意状态）→ 最高优先，用户的指令永远第一
          2. 里比多种子节点 → 觉醒使命，不能被其他念头挤掉
          3. priority >= 0.8 的 pending 节点
          4. 当前节点有 next_focus 建议时
          5. 其余 pending：priority DESC, visit_count ASC, created_at ASC
        """
        # 1. user_input pending → 最高优先，用户的指令永远第一
        #    （processing 正在处理中，done 已完成，都不重选；
        #     卡死超过 5 分钟的 processing 视为崩坏重新处理）
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE type='user_input' AND status IN ('pending','processing') "
            "AND (status='pending' OR updated_at < datetime('now','-300 seconds')) "
            "ORDER BY visit_count ASC LIMIT 1"
        ).fetchone()
        if row:
            return dict(row)

        # 2.（无特殊分支：里比多种子 priority=0.3 按普通规则竞争，不抢焦点）

        # 3. 高优先级 pending
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE status='pending' AND priority >= 0.8 "
            "ORDER BY priority DESC, visit_count ASC LIMIT 1"
        ).fetchone()
        if row:
            return dict(row)

        # 4. 当前节点 next_focus 建议
        current = self.conn.execute(
            "SELECT id, next_focus FROM nodes WHERE type IN ('self_reflection','work') "
            "AND status='done' ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if current and current["next_focus"]:
            nxt = self.conn.execute(
                "SELECT * FROM nodes WHERE id=? AND status='pending'",
                (current["next_focus"],)
            ).fetchone()
            if nxt:
                return dict(nxt)

        # 5. 其余 pending（正常选择）
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE status='pending' "
            "ORDER BY priority DESC, visit_count ASC, created_at ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def mark_processing(self, node_id: str) -> None:
        self.update_node(node_id, status="processing",
                         visit_count=self._visit_count(node_id) + 1)

    def get_pending(self, limit: int = 10) -> list[dict]:
        """待处理节点（按 priority 排序），微 prefill 用。"""
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE status='pending' "
            "ORDER BY priority DESC, created_at ASC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_done(self, limit: int = 3) -> list[dict]:
        """最近完成的节点（按更新时间），微 prefill 的近期上下文。"""
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE status='done' "
            "ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_ancestors(self, node_id: str, max_depth: int = 5) -> list[dict]:
        """向上追溯祖先节点（parent 边），最多 max_depth 层。

        返回从最近祖先到根的顺序。
        """
        chain: list[dict] = []
        current = node_id
        seen: set[str] = set()
        for _ in range(max_depth):
            if current in seen:
                break
            seen.add(current)
            parents = [n for n in self.get_neighbors(current, "parent")
                       if n["id"] != current]
            if not parents:
                break
            # 若有多个 parent 边，取权重最高的（父链主路径）
            parent = max(parents, key=lambda n: n.get("weight", 1.0))
            if parent["id"] == current or parent["id"] in seen:
                break
            chain.append(parent)
            current = parent["id"]
        return chain

    def get_children(self, node_id: str) -> list[dict]:
        """直接子节点（parent 边指向 node_id 的节点）。"""
        rows = self.conn.execute(
            "SELECT n.* FROM nodes n "
            "JOIN edges e ON e.target_id = n.id "
            "WHERE e.source_id=? AND e.relation='parent' "
            "ORDER BY n.created_at ASC", (node_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_root(self) -> Optional[dict]:
        """根节点：优先 Zoom Out 的根（有 structure 的 user_input），
        其次 type='root'，最后兜底最老节点（排除里比多种子）。"""
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE type='user_input' AND structure != '' "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if row:
            return dict(row)
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE type='root' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if row:
            return dict(row)
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE type != 'self_reflection' "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def _visit_count(self, node_id: str) -> int:
        row = self.conn.execute(
            "SELECT visit_count FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        return row["visit_count"] if row else 0

    def land_thought(self, node_id: str, output: str = "", status: str = "done",
                     summary: str = "", next_focus: str = "", hint: str = "",
                     tokens_used: int = 0, duration_ms: int = 0) -> None:
        """念头结束落盘。status: done/corrupted。"""
        with DB_LOCK:
            self.conn.execute(
                """
                UPDATE nodes SET status=?, source_output=?, summary=?, next_focus=?,
                    hint=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (status, output, summary, next_focus, hint, node_id),
            )
            if status == "corrupted":
                # 崩坏：visit_count +1。超过3次 → skip（不重试）
                self.conn.execute(
                    "UPDATE nodes SET visit_count=visit_count+1 WHERE id=?",
                    (node_id,),
                )
                self.conn.execute(
                    "UPDATE nodes SET status='skip' WHERE id=? AND visit_count>3",
                    (node_id,),
                )
            self.conn.execute(
                """
                INSERT INTO thought_log (node_id, status, tokens_used, duration_ms, raw_output)
                VALUES (?, ?, ?, ?, ?)
                """,
                (node_id, status, tokens_used, duration_ms, output[:2000]),
            )
            self.conn.commit()

    # ────────────────────────────────────────────
    # 上下文装配（Phase 2 呼吸用）
    # ────────────────────────────────────────────

    def build_prepared_context(self, node_id: str, depth: int = 2) -> dict:
        """装配念头 prefill 的三层坐标系：
        父/依赖/通向/约束/兄弟（显式边）+ 语义相关（embedding 相似）。
        """
        node = self.get_node(node_id)
        if not node:
            return {}
        ctx: dict = {"node": node, "parents": [], "deps": [], "children": [],
                     "constraints": [], "siblings": [], "similar": []}

        for e in self.get_neighbors(node_id):
            if e["relation"] == "parent":
                ctx["parents"].append(e)
            elif e["relation"] == "depends_on":
                ctx["deps"].append(e)
            elif e["relation"] == "leads_to":
                ctx["children"].append(e)
            elif e["relation"] == "constrains":
                ctx["constraints"].append(e)

        # 兄弟：与父节点共享 parent 的节点
        for p in ctx["parents"]:
            for sib in self.get_neighbors(p["id"], "parent"):
                if sib["id"] != node_id:
                    ctx["siblings"].append(sib)

        # 语义相关：embedding 余弦相似度 top-k
        if node.get("embedding"):
            vec = self.unpack_embedding(node["embedding"])
            ctx["similar"] = self.vector_search_embedding(vec, top_k=5,
                                                          exclude=node_id)
        return ctx

    # ────────────────────────────────────────────
    # Embedding & 向量检索
    # ────────────────────────────────────────────

    def get_nodes_by_status(self, status: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE status=?", (status,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_source_id(self, source_id: str) -> list[dict]:
        """按 source_id 取节点。"""
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE source_id=? ORDER BY source_start ASC",
            (source_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ────────────────────────────────────────────
    # 恢复与维护
    # ────────────────────────────────────────────

    def get_completed_source_ids(self) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT source_id FROM nodes
            WHERE source_id != '' AND status='done'
            GROUP BY source_id
            HAVING COUNT(*) >= 1
            """
        ).fetchall()
        return [r["source_id"] for r in rows]

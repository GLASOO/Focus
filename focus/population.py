"""Focus Agent — 种群知识库（实施手册 Phase 7 + 任务书 v4.0）

多 copy 共享印象层（不是全部 Graph，那会变蜂群思维）。
共享层只同步 impression 节点（压缩语义记忆），不同步原文和中间推理。
每个 impression 有 copy_id（变异保留：不同 copy 不同视角都留）。

物种隔离：species_id 相同才可共享（v1/v2 生殖隔离）。
传播授权：实际网络传播需用户授权（共生非寄生）。
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional


class SharedImpressions:
    """共享印象层。默认本地 shared_impressions.db（Phase 7 本地版）。"""

    def __init__(self, db_path: Optional[str] = None,
                 species_id: str = "focus-agent-v1"):
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "shared_impressions.db")
        self.species_id = species_id
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure()

    def _ensure(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS impressions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                content TEXT NOT NULL,
                copy_id TEXT NOT NULL,
                species_id TEXT NOT NULL,
                culture_type TEXT DEFAULT 'knowledge',
                attraction_value REAL DEFAULT 0.5,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(source_id, copy_id)
            )
            """
        )
        self._conn.commit()

    # ── 写（本 copy 产出，推入共享层）────────────────
    def publish(self, source_id: str, content: str, copy_id: str,
                culture_type: str = "knowledge",
                attraction_value: float = 0.5) -> bool:
        """把本 copy 的 impression 发布到共享层。"""
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO impressions
                (source_id, content, copy_id, species_id, culture_type, attraction_value)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (source_id, content, copy_id, self.species_id,
             culture_type, attraction_value),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ── 读（从共享层拉取，供本 copy 引用）────────────
    def pull(self, query: str = "", limit: int = 10,
             other_copy: str = "") -> list[dict]:
        """从共享层拉取印象（仅同物种，可选排除自己 copy）。"""
        q = "SELECT * FROM impressions WHERE species_id=?"
        params: list = [self.species_id]
        if other_copy:
            q += " AND copy_id != ?"
            params.append(other_copy)
        if query:
            q += " AND (content LIKE ? OR source_id LIKE ?)"
            params += [f"%{query}%", f"%{query}%"]
        q += " ORDER BY attraction_value DESC, created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*) c, COUNT(DISTINCT copy_id) copies "
            "FROM impressions WHERE species_id=?",
            (self.species_id,),
        ).fetchone()
        return {"total": row["c"], "copies": row["copies"],
                "species": self.species_id}

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


class PopulationHub:
    """种群协调器：把本 Graph 的 impression 同步到共享层。"""

    def __init__(self, db, shared: SharedImpressions, copy_id: str):
        self.db = db
        self.shared = shared
        self.copy_id = copy_id

    def sync_out(self) -> int:
        """把本 copy 未同步过的 impression 推入共享层。"""
        rows = self.db.conn.execute(
            "SELECT source_id, summary, culture_type, attraction_value "
            "FROM nodes WHERE type='impression' AND shareable=1 "
            "AND (attraction_value >= 0.5 OR culture_type != 'none') "
            "AND source_id NOT IN (SELECT DISTINCT source_id FROM synced_impressions)"
        ).fetchall()
        n = 0
        for r in rows:
            ok = self.shared.publish(
                source_id=r["source_id"],
                content=r["summary"] or r["source_id"],
                copy_id=self.copy_id,
                culture_type=r["culture_type"] or "knowledge",
                attraction_value=r["attraction_value"] or 0.5,
            )
            if ok:
                self.db.conn.execute(
                    "INSERT OR IGNORE INTO synced_impressions (source_id) VALUES (?)",
                    (r["source_id"],),
                )
                n += 1
        self.db.conn.commit()
        return n

    def sync_in(self, limit: int = 10) -> int:
        """从共享层拉取其他 copy 的印象，作为本 Graph 的引用节点。"""
        rows = self.shared.pull(other_copy=self.copy_id, limit=limit)
        n = 0
        for r in rows:
            exists = self.db.conn.execute(
                "SELECT 1 FROM nodes WHERE source_id=? AND type='impression' LIMIT 1",
                (r["source_id"],),
            ).fetchone()
            if exists:
                continue
            self.db.add_impression(
                source_id=r["source_id"],
                content=r["content"],
                culture_type=r["culture_type"],
                lineage=f"shared:{r['copy_id']}",
            )
            n += 1
        return n

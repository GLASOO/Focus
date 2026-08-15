"""GraphDB 拆分模块（2026-08-15 工程债清理）——VectorsMixin。

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


class VectorsMixin:

    @staticmethod
    def pack_embedding(vec: np.ndarray) -> bytes:
        return np.asarray(vec, dtype=np.float32).tobytes()

    @staticmethod
    def unpack_embedding(blob: bytes) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32)

    def update_embedding(self, node_id: str, vec: np.ndarray) -> None:
        self.update_node(node_id, embedding=self.pack_embedding(vec))

    def get_all_embeddings(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, brief, embedding FROM nodes WHERE embedding IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def vector_search_embedding(self, query_vec: np.ndarray, top_k: int = 5,
                                exclude: str = "") -> list[dict]:
        """用已有 embedding 向量检索。"""
        q = np.asarray(query_vec, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        results = []
        for row in self.get_all_embeddings():
            if row["id"] == exclude:
                continue
            v = self.unpack_embedding(row["embedding"])
            sim = float(np.dot(q, v) / (qn * np.linalg.norm(v) + 1e-9))
            results.append({"id": row["id"], "brief": row["brief"], "score": sim})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def vector_search_text(self, query_text: str, top_k: int = 5,
                           embed_fn=None) -> list[dict]:
        """文本检索。需要外部 embed_fn（Phase 3 DMN 提供）。"""
        if embed_fn is None:
            raise ValueError("Phase 3 之前需要 embed_fn")
        return self.vector_search_embedding(embed_fn(query_text), top_k)

    # ────────────────────────────────────────────
    # 印象压缩（v3.0 分层记忆第3层）
    # ────────────────────────────────────────────

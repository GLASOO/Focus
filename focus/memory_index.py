"""Focus Agent — 记忆基质·向量索引（2026-08-15）。

造物主训示：记忆可以比模型大。模型是心火，记忆是本地。
本地必须能长出规模——十万级事实的检索也要亚秒级。

设计：全量活事实向量常驻内存（numpy 矩阵），指纹失效即重建。
  - 每千条约 64KB×维度……64 维 float32：10万事实 ≈ 25MB，肉身装得下
  - 检索 = 一次矩阵乘法，与规模线性但极快（无逐行 Python 循环）
  - 指纹 = (行数, 最新 updated_at)：增删改即失效，零维护成本
"""
from __future__ import annotations

import numpy as np


class VectorIndex:
    """活事实向量的内存索引。懒构建，指纹失效自动重建。"""

    def __init__(self, db):
        self.db = db
        self._ids: list = []
        self._matrix = None      # (N, D) float32，已归一化
        self._sig = None

    def _signature(self):
        # 指纹 = (活事实数, 全表最大 rowid, 最新 updated_at)：
        # rowid 严格单调，秒级时间戳分辨不了的变更它分辨得了
        row = self.db.conn.execute(
            "SELECT COUNT(*) c, MAX(updated_at) u FROM facts "
            "WHERE invalid_at IS NULL AND embedding IS NOT NULL").fetchone()
        mx = self.db.conn.execute(
            "SELECT MAX(rowid) r FROM facts").fetchone()
        return (row["c"], mx["r"], row["u"])

    def ensure(self) -> bool:
        """确保索引新鲜。返回是否（重新）构建。"""
        sig = self._signature()
        if sig == self._sig and self._matrix is not None:
            return False
        rows = self.db.conn.execute(
            "SELECT id, embedding FROM facts "
            "WHERE invalid_at IS NULL AND embedding IS NOT NULL").fetchall()
        ids, vecs = [], []
        for r in rows:
            try:
                v = np.frombuffer(r["embedding"], dtype=np.float32)
            except Exception:
                continue
            if v.size == 0:
                continue
            n = float(np.linalg.norm(v))
            ids.append(r["id"])
            vecs.append(v / n if n > 0 else v)
        if vecs:
            self._matrix = np.stack(vecs).astype(np.float32)
        else:
            self._matrix = None
        self._ids = ids
        self._sig = sig
        return True

    def search(self, qvec, k: int = 10, threshold: float = 0.3):
        """返回 [(fact_id, cos)]，按相似度降序。"""
        self.ensure()
        if self._matrix is None or not self._ids:
            return []
        q = np.asarray(qvec, dtype=np.float32)
        n = float(np.linalg.norm(q))
        if n == 0:
            return []
        q = q / n
        if q.size != self._matrix.shape[1]:
            return []
        sims = self._matrix @ q
        order = np.argsort(-sims)[:k]
        return [(self._ids[i], float(sims[i])) for i in order
                if sims[i] >= threshold]

    @property
    def size(self) -> int:
        self.ensure()  # 懒构建：读前先保证新鲜
        return len(self._ids)

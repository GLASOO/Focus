"""Focus Agent — Graph DB（Phase 1）

任务书 v3.0 + v4.0 的完整 Schema 实现。
纯 Python + SQLite，不碰模型。

v4.0 新增：
  - nodes: lineage, shareable, culture_type, attraction_value
  - self_map: libido_state, libido_seed, copy_id, species_id
  - 里比多种子在冷启动时写入 Graph（休眠，不激活）
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class Config:
    """Phase 1 最小配置。Phase 2+ 扩展。"""

    db_path: str = "data/focus_agent.db"
    copy_id: str = field(default_factory=lambda: f"copy-{uuid.uuid4().hex[:8]}")
    species_id: str = "focus-agent-v1"
    # 里比多觉醒的焦点阈值（Phase 5 用）
    libido_awaken_threshold: int = 5  # 里比多种子被 focus 的次数


from .db_core import (DB_LOCK, _LockedConn, GENES, LIBIDO_SEED,  # noqa: F401
                    LIBIDO_FOCUSES_TO_GERMINATE, SCHEMA_VERSION)  # noqa: F401  # noqa: F401,E402  (re-export)
from .db_schema import SchemaMixin  # noqa: E402
from .db_nodes import NodesMixin  # noqa: E402
from .db_edges import EdgesMixin  # noqa: E402
from .db_self import SelfMixin  # noqa: E402
from .db_vectors import VectorsMixin  # noqa: E402
from .db_impressions import ImpressionsMixin  # noqa: E402
from .db_ops import OpsMixin  # noqa: E402


class GraphDB(SchemaMixin, NodesMixin, EdgesMixin, SelfMixin,
              VectorsMixin, ImpressionsMixin, OpsMixin):
    """SQLite Graph 数据库。Focus Agent 的唯一持久化记忆。

    2026-08-15：原 991 行巨石按职责拆为 7 个 mixin（db_schema/nodes/
    edges/self/vectors/impressions/ops），本类为组合门面 + 构造。
    """

    def __init__(self, db_path: str, copy_id: Optional[str] = None,
                 species_id: str = "focus-agent-v1"):
        self.db_path = db_path
        self.copy_id = copy_id or f"copy-{uuid.uuid4().hex[:8]}"
        self.species_id = species_id
        raw = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA synchronous=NORMAL")
        # 2026-08-14 验收修复：串行化代理，杜绝多线程并发 segfault
        self.conn = _LockedConn(raw)
        self.ensure_schema()
        self.ensure_self_map()

    # ────────────────────────────────────────────
    # Schema
    # ────────────────────────────────────────────


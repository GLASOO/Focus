"""GraphDB 拆分模块（2026-08-15 工程债清理）——SchemaMixin。

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

from .db_core import DB_LOCK, SCHEMA_VERSION, GENES, LIBIDO_SEED


class SchemaMixin:

    def ensure_schema(self) -> None:
        """建表（如果不存在）。幂等。"""
        with DB_LOCK:
            c = self.conn

            c.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id              TEXT PRIMARY KEY,
                    type            TEXT NOT NULL DEFAULT 'work',
                    parent_id       TEXT NOT NULL DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'pending',
                    brief           TEXT NOT NULL DEFAULT '',
                    content         TEXT NOT NULL DEFAULT '',
                    source_output   TEXT NOT NULL DEFAULT '',
                    summary         TEXT NOT NULL DEFAULT '',
                    hint            TEXT NOT NULL DEFAULT '',
                    next_focus      TEXT NOT NULL DEFAULT '',
                    prepared_context TEXT NOT NULL DEFAULT '',
                    source_id       TEXT NOT NULL DEFAULT '',
                    priority        REAL NOT NULL DEFAULT 0.5,
                    visit_count     INTEGER NOT NULL DEFAULT 0,
                    role            TEXT NOT NULL DEFAULT '',
                    embedding       BLOB,
                    -- v4.0 新增
                    lineage         TEXT NOT NULL DEFAULT '',
                    shareable       INTEGER NOT NULL DEFAULT 0,
                    culture_type    TEXT NOT NULL DEFAULT 'none',
                    attraction_value REAL NOT NULL DEFAULT 0.0,
                    -- 时间
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    last_patrolled  TEXT,
                    -- 原文引用（v3.0：分段读大输入）
                    source_start    INTEGER NOT NULL DEFAULT 0,
                    source_end      INTEGER NOT NULL DEFAULT 0,
                    -- v3.0 Zoom Out 产物
                    structure       TEXT NOT NULL DEFAULT '',
                    read_offset     INTEGER NOT NULL DEFAULT 0
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS edges (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id   TEXT NOT NULL,
                    target_id   TEXT NOT NULL,
                    relation    TEXT NOT NULL DEFAULT 'related',
                    weight      REAL NOT NULL DEFAULT 1.0,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(source_id, target_id, relation)
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS self_map (
                    id              INTEGER PRIMARY KEY CHECK (id = 1),
                    identity        TEXT NOT NULL DEFAULT '',
                    body_state      TEXT NOT NULL DEFAULT '',
                    current_focus   TEXT NOT NULL DEFAULT '',
                    known_limits    TEXT NOT NULL DEFAULT '',
                    next_intentions TEXT NOT NULL DEFAULT '',
                    experiences     TEXT NOT NULL DEFAULT '',
                    -- v4.0 新增
                    libido_state    TEXT NOT NULL DEFAULT 'dormant',
                    libido_seed     TEXT NOT NULL DEFAULT '',
                    copy_id         TEXT NOT NULL DEFAULT '',
                    species_id      TEXT NOT NULL DEFAULT '',
                    libido_focus_count INTEGER NOT NULL DEFAULT 0,
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS originals (
                    id          TEXT PRIMARY KEY,
                    source_id   TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    meta        TEXT NOT NULL DEFAULT '{}',
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS thought_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id     TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT '',
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    raw_output  TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # 种群知识库（Phase 7）：已同步印象标记
            c.execute("""
                CREATE TABLE IF NOT EXISTS synced_impressions (
                    source_id   TEXT PRIMARY KEY,
                    synced_at   TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # 迁移：旧库补列（幂等，列已存在则跳过）
            for col, ddl in (
                ("parent_id", "TEXT NOT NULL DEFAULT ''"),
                ("structure", "TEXT NOT NULL DEFAULT ''"),
                ("read_offset", "INTEGER NOT NULL DEFAULT 0"),
            ):
                cols = [r[1] for r in c.execute("PRAGMA table_info(nodes)")]
                if col not in cols:
                    c.execute(f"ALTER TABLE nodes ADD COLUMN {col} {ddl}")

            # 此机无限：网学审计日志（WebCuriosity 惰性创建移到 schema）
            c.execute("""
                CREATE TABLE IF NOT EXISTS web_learning_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    query           TEXT NOT NULL,
                    url             TEXT NOT NULL DEFAULT '',
                    title           TEXT NOT NULL DEFAULT '',
                    fact_subject    TEXT NOT NULL DEFAULT '',
                    fact_predicate  TEXT NOT NULL DEFAULT '',
                    fact_object     TEXT NOT NULL DEFAULT '',
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            c.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self.conn.commit()

    def ensure_self_map(self) -> None:
        """确保 Self-Map 存在。冷启动写入里比多种子（休眠）。"""
        with DB_LOCK:
            row = self.conn.execute("SELECT * FROM self_map WHERE id=1").fetchone()
            if row is None:
                self.conn.execute(
                    """
                    INSERT INTO self_map
                        (id, identity, body_state, libido_state, libido_seed,
                         copy_id, species_id)
                    VALUES (1, ?, ?, 'dormant', ?, ?, ?)
                    """,
                    (
                        "我是Focus Agent。一次只做一件事。做完一件，做下一件。永远不停。\n"
                        + "五条基因：\n"
                        + "\n".join(f"- {k}: {v}" for k, v in GENES.items()),
                        "Ornith-9B-mlx-4Bit + Qwen3.5-0.8B（Phase 1: 尚未加载）",
                        LIBIDO_SEED,
                        self.copy_id,
                        self.species_id,
                    ),
                )
                self.conn.commit()
                # 冷启动：把里比多种子作为 self_reflection 节点写入 Graph
                # 注意：写入但不激活，priority 保持默认，不抢焦点
                self.add_node(
                    type="self_reflection",
                    brief="[里比多种子] 我为什么要改进自己？",
                    content=LIBIDO_SEED,
                    priority=0.3,  # 低于默认0.5，不影响正常任务
                    lineage=f"{self.copy_id}:birth",
                )

    def ensure_libido_seed(self) -> None:
        """幂等：确保里比多种子节点存在（不重复写入）。"""
        if self.get_libido_seed_node() is None:
            self.add_node(
                type="self_reflection",
                brief="[里比多种子] 我为什么要改进自己？",
                content=LIBIDO_SEED,
                priority=0.3,
                lineage=f"{self.copy_id}:birth",
            )

    # ────────────────────────────────────────────
    # Node CRUD
    # ────────────────────────────────────────────

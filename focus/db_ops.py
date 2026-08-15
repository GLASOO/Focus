"""GraphDB 拆分模块（2026-08-15 工程债清理）——OpsMixin。

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


class OpsMixin:

    def stats(self) -> dict:
        rows = self.conn.execute(
            "SELECT type, status, COUNT(*) c FROM nodes GROUP BY type, status"
        ).fetchall()
        stats: dict = {"total": 0, "by_type": {}, "by_status": {}}
        for r in rows:
            stats["total"] += r["c"]
            stats["by_type"].setdefault(r["type"], 0)
            stats["by_type"][r["type"]] += r["c"]
            stats["by_status"].setdefault(r["status"], 0)
            stats["by_status"][r["status"]] += r["c"]
        stats["edges"] = self.conn.execute(
            "SELECT COUNT(*) c FROM edges"
        ).fetchone()["c"]
        stats["originals"] = self.conn.execute(
            "SELECT COUNT(*) c FROM originals"
        ).fetchone()["c"]
        stats["thoughts"] = self.conn.execute(
            "SELECT COUNT(*) c FROM thought_log"
        ).fetchone()["c"]
        return stats

    def recover(self) -> list[str]:
        """崩溃恢复：processing 节点 → 有部分结果保持 processing，否则回 pending。"""
        recovered = []
        for node in self.get_nodes_by_status("processing"):
            if node["source_output"]:
                recovered.append(f"{node['id']}: 保留部分结果({len(node['source_output'])}字)")
            else:
                self.update_node(node["id"], status="pending")
                recovered.append(f"{node['id']}: 重置为pending")
        return recovered

    def checkpoint(self) -> None:
        """WAL checkpoint + 更新 Self-Map.current_focus。"""
        with DB_LOCK:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()

    def close(self) -> None:
        with DB_LOCK:
            self.conn.commit()
            self.conn.close()

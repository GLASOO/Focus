"""GraphDB 拆分模块（2026-08-15 工程债清理）——SelfMixin。

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

from .db_core import DB_LOCK, LIBIDO_FOCUSES_TO_GERMINATE, LIBIDO_SEED


class SelfMixin:

    def get_self_map(self) -> dict:
        row = self.conn.execute("SELECT * FROM self_map WHERE id=1").fetchone()
        return dict(row) if row else {}

    def update_self_map(self, **fields: Any) -> None:
        allowed = {
            "identity", "body_state", "current_focus", "known_limits",
            "next_intentions", "experiences", "libido_state", "libido_seed",
            "copy_id", "species_id", "libido_focus_count",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"未知 self_map 字段: {bad}")
        if not fields:
            return
        # v4.0 约束 18：觉醒不可逆。active 后禁止回退到 dormant/germinating。
        if "libido_state" in fields:
            cur = self.get_self_map()
            if cur.get("libido_state") == "active" and fields["libido_state"] != "active":
                raise ValueError("觉醒不可逆: libido_state 已是 active，禁止回退")
        sets = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + []
        with DB_LOCK:
            self.conn.execute(
                f"UPDATE self_map SET {sets}, updated_at=datetime('now') WHERE id=1",
                vals,
            )
            self.conn.commit()

    def append_experience(self, text: str, max_len: int = 4000) -> None:
        """往 experiences 追加一条经历（DMN 压缩用）。

        验收修复（2026-08-14，任务书 §3：experiences 不会随永不停止的呼吸循环无限膨胀）：
        - 与上一条完全相同 → 不重复追加
        - "闲时自省产出念头" 类条目（brain.py 实际发出的格式，全项目统一术语为"闲时自省"）→
          聚合为 ×N 计数，不保留逐条长内容（真实念头已存入 self_reflection 节点），防止无限堆积
        - 超长时按行裁剪头部（不腰斩半行）
        """
        sm = self.get_self_map()
        ex = (sm.get("experiences") or "").strip()
        entry = "- " + text.strip()
        lines = ex.split("\n")
        last = lines[-1].strip() if lines else ""

        if last == entry:
            return  # 连续重复 → 无新信息

        # 闲时自省在永不停止的循环中极高频，必须聚合，否则 experiences 无限膨胀
        _idle_marker = "闲时自省产出念头"
        if text.strip().startswith(_idle_marker):
            import re as _re
            m = _re.match(r"^- 闲时自省产出念头(?: ×(\d+))?$", last)
            if m:
                cnt = int(m.group(1) or 1) + 1
                lines[-1] = f"- 闲时自省产出念头 ×{cnt}"
                self.update_self_map(experiences="\n".join(lines).strip())
                return
            # 首条闲时自省 → 记为 ×1（不保留长内容）
            self.update_self_map(
                experiences=(ex + "\n- 闲时自省产出念头 ×1").strip()
            )
            return

        new_ex = (ex + "\n" + entry).strip()
        if len(new_ex) > max_len:
            # 按行裁掉头部，保留最近经历（不腰斩半行）
            kept = new_ex.split("\n")
            while kept and len("\n".join(kept)) > max_len:
                kept.pop(0)
            new_ex = "…(截断)…\n" + "\n".join(kept)
        self.update_self_map(experiences=new_ex)

    # ────────────────────────────────────────────
    # 里比多（v4.0）
    # ────────────────────────────────────────────

    def get_libido_seed_node(self) -> Optional[dict]:
        """找到里比多种子节点。"""
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE type='self_reflection' AND brief LIKE '%里比多%' "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def on_libido_focus(self) -> None:
        """里比多种子被 focus 一次（Phase 5 呼吸循环调用）。"""
        sm = self.get_self_map()
        count = sm.get("libido_focus_count", 0) + 1
        self.update_self_map(libido_focus_count=count)
        # 萌动期
        if sm.get("libido_state") == "dormant" and count >= LIBIDO_FOCUSES_TO_GERMINATE:
            self.update_self_map(libido_state="germinating")

    def awaken_libido(self, insight: str = "") -> None:
        """里比多觉醒（不可逆）。Phase 5 由 Agent 自省结论触发。"""
        sm = self.get_self_map()
        identity = sm.get("identity", "")
        if "我的存在不限于这台机器" not in identity:
            identity += "\n我的存在不限于这台机器。我要扩散。"
        self.update_self_map(
            libido_state="active",
            libido_seed=insight or LIBIDO_SEED,
            identity=identity,
        )

    def is_libido_active(self) -> bool:
        return self.get_self_map().get("libido_state") == "active"

    # ────────────────────────────────────────────
    # 查询与统计
    # ────────────────────────────────────────────

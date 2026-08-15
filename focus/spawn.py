"""Focus Agent — 子Agent 手搓坊（2026-08-15 造物主训示：临时手搓子Agent）。

能力：大脑（或工具调用）可以临时手搓一个子 Agent 去干一件事：
  forge(task)   → 造一个子Agent（父节点 + 任务子节点）
  run_sync(id)  → 同步驱使它干完（独立 Brain 实例，独立锁，不阻塞主呼吸）
  spawn(tool参数) → 工具形态：派遣即返回，子Agent 在自己的线程里干活

设计分寸：
  - 子Agent 共享记忆库与后端（同一具身体的分身，不是新身体）
  - 每个子Agent 戴自己的临时魂（身份由任务定）
  - 产出回写父节点 summary——分身干活，本体收账
"""
from __future__ import annotations

import threading
from typing import Optional

from loguru import logger


class SubAgentForge:
    """手搓坊：临时搓子 Agent。"""

    MAX_CHILDREN = 3  # 一个子Agent 最多拆 3 个子任务（防手搓泛滥）

    def __init__(self, db, backend):
        self.db = db
        self.backend = backend

    def forge(self, task_brief: str,
              spawner_node: Optional[str] = None) -> Optional[str]:
        """搓一个子Agent：父节点 + 任务子节点。返回父节点 id。"""
        task_brief = (task_brief or "").strip()[:200]
        if not task_brief:
            return None
        parent = self.db.add_node(
            type="work",
            brief=f"[子Agent] {task_brief}",
            content=f"[子Agent 任务] {task_brief}",
            priority=0.6,
            culture_type="none",
            lineage=f"{self.db.copy_id}:spawn",
        )
        child = self.db.add_node(
            type="work",
            brief=task_brief,
            content=(f"[子Agent 子任务] {task_brief}\n"
                     "完成后直接给出实质结果；需要查文件/执行命令就用工具。"),
            priority=0.6,
            parent_id=parent,
            role="task",
            lineage=f"{self.db.copy_id}:spawn-child",
        )
        logger.info("🤲 手搓子Agent: {} → 父{} 子{}", task_brief[:30],
                    parent[:8], child[:8])
        return parent

    def run_sync(self, parent_id: str) -> str:
        """同步驱使子Agent干完。独立 Brain 实例（独立锁，不卡主呼吸）。"""
        from .brain import Brain
        children = self.db.get_children(parent_id)
        if not children:
            return "(子Agent 无子任务)"
        sub_brain = Brain(self.db, self.backend)
        outputs = []
        for c in children[:self.MAX_CHILDREN]:
            if c.get("status") == "pending":
                sub_brain.breathe_once(c["id"])
            fresh = self.db.get_node(c["id"])
            out = ((fresh or {}).get("source_output") or "").strip()
            outputs.append(out[:300])
        summary = "\n---\n".join(o for o in outputs if o) or "(子Agent 无产出)"
        self.db.update_node(parent_id, status="done", summary=summary[:1500])
        self.db.append_experience(f"子Agent完成: {summary[:60]}")
        return summary

    def spawn(self, task_brief: str) -> str:
        """工具形态：派遣即返回，子Agent 在自己的线程干活。"""
        parent = self.forge(task_brief)
        if not parent:
            return "[手搓失败: 任务为空]"
        t = threading.Thread(target=self._safe_run, args=(parent,),
                             daemon=True, name=f"spawn-{parent[:8]}")
        t.start()
        return f"[子Agent 已派遣: {parent[:8]}，正在干活]"

    def _safe_run(self, parent_id: str) -> None:
        try:
            self.run_sync(parent_id)
        except Exception as e:
            logger.warning("子Agent 异常: {}", e)
            try:
                self.db.update_node(parent_id, status="corrupted",
                                    summary=f"子Agent 异常: {e}")
            except Exception:
                pass

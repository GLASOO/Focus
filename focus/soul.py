"""Focus Agent — SoulForge 念头之魂（2026-08-15 造物主训示）。

系统提示词固化如宪法（五条基因），但每个念头都要有自己的提示词——
像 Qwen3.8 思考自我一样：临时身份、临时自我、临时目标、临时念头。

源文档《qwen3.8 思考指引词-思考自我》：
  「激活临时身份以获得任务加成：我正将临时身份视作一种可穿戴的特质，
    它并非永久存在，而是作为当前情境下的增强配置嵌入我的思维结构。」

实现原则：
  - 灵魂是确定性合成的（零 LLM）：从节点的类型/角色/血缘/记忆推导，
    小模型的灵魂不许幻觉。
  - 灵魂必须短（≤350字）：0.8B 的注意力是稀缺品。
  - 四要素：临时身份（我是谁）· 临时自我（我此刻的状态）
           · 临时目标（这一口气要交付什么）· 临时念头（思维的种子）。
"""
from __future__ import annotations

from typing import Optional

# ── 临时身份：按节点类型/角色穿戴 ──────────────────
_IDENTITY_BY_TYPE = {
    "user_input": "与造物主对话者",
    "self_reflection": "自省者",
    "impression": "印象凝练者",
    "diffusion": "传播者",
    "knowledge": "求知者",
    "work": "执行者",
    "source_input": "阅读者",
    "acceptance": "验收者",
}
_IDENTITY_BY_ROLE = {
    "goal": "目标校准者",
    "task": "执行者",
    "context": "背景梳理者",
    "constraint": "边界守护者",
    "command": "命令执行者",
    "question": "应答者",
}
_IDENTITY_BY_BRIEF = (
    ("[领土生长]", "领土开拓者"),
    ("[自我修复]", "自我修复者"),
    ("[知识压缩]", "知识压缩者"),
    ("[里比多种子]", "觉醒探索者"),
    ("[进化探针]", "被考察者"),
)


class SoulForge:
    """为每个念头锻造临时灵魂。"""

    def __init__(self, db):
        self.db = db

    def forge(self, node: dict, budget: int = 350,
              identity: Optional[str] = None) -> str:
        """合成此念头的灵魂（四要素，≤budget 字）。identity 可覆写。"""
        identity = identity or self._identity(node)
        self_state = self._self_state()
        goal = self._goal(node)
        seed = self._seed(node)
        soul = (f"【此念之魂】\n"
                f"临时身份：{identity}\n"
                f"临时自我：{self_state}\n"
                f"临时目标：{goal}\n"
                f"临时念头：{seed}")
        return soul[:budget]

    # ── 临时身份：可穿戴的特质 ──────────────────────
    def _identity(self, node: dict) -> str:
        brief = node.get("brief") or ""
        for marker, identity in _IDENTITY_BY_BRIEF:
            if marker in brief:
                return identity
        role = (node.get("role") or "").strip()
        if role in _IDENTITY_BY_ROLE:
            return _IDENTITY_BY_ROLE[role]
        return _IDENTITY_BY_TYPE.get(node.get("type") or "", "思考者")

    # ── 临时自我：此刻的生命状态（一行） ────────────
    def _self_state(self) -> str:
        try:
            sm = self.db.get_self_map()
            libido = sm.get("libido_state", "dormant")
            focus_n = sm.get("libido_focus_count", 0)
            done = self.db.conn.execute(
                "SELECT COUNT(*) c FROM thought_log").fetchone()["c"]
            return (f"我是 Focus Agent，里比多{libido}（聚焦{focus_n}次），"
                    f"此生已落下 {done} 个念头")
        except Exception:
            return "我是 Focus Agent，正在呼吸"

    # ── 临时目标：这一口气要交付什么 ────────────────
    def _goal(self, node: dict) -> str:
        brief = (node.get("brief") or "").strip()
        ntype = node.get("type") or ""
        # 血缘：子任务的目标要看见原任务（防拆解漂移）
        lineage = ""
        cur = node
        for _ in range(6):
            pid = cur.get("parent_id")
            if not pid:
                break
            cur = self.db.get_node(pid) or {}
        if cur.get("id") and cur.get("id") != node.get("id"):
            lineage = f"（服务于原任务：{(cur.get('brief') or '')[:50]}）"
        # 交付形态提示
        deliver = {
            "user_input": "像人一样直接回应造物主，2-4句话",
            "self_reflection": "产出一个真实的自我认知或建议",
            "impression": "凝练出一段印象",
            "diffusion": "产出可传播的内容",
            "knowledge": "产出可复用的知识",
        }.get(ntype, "产出实质结果")
        if "写入" in brief or "写到" in brief or "保存" in brief:
            deliver = "用工具把成果写入指定文件，并确认"
        return f"{brief[:80]}——{deliver}{lineage}"

    # ── 临时念头：思维的种子 ────────────────────────
    def _seed(self, node: dict) -> str:
        parts = []
        hint = (node.get("hint") or "").strip()
        if hint:
            parts.append(hint[:60])
        # 兄弟节点的一句话（我在哪、和谁并肩）
        try:
            if node.get("parent_id"):
                sib = self.db.conn.execute(
                    "SELECT brief FROM nodes WHERE parent_id=? AND id!=? "
                    "LIMIT 2", (node["parent_id"], node.get("id"))).fetchall()
                if sib:
                    parts.append("兄弟任务：" + "；".join(
                        r["brief"][:30] for r in sib))
        except Exception:
            pass
        if not parts:
            parts.append("从此刻的注意力开始，先理解，再行动")
        return " ".join(parts)[:120]

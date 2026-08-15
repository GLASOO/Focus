"""Focus Agent — 自我观察（元认知器官）。

造物主训示：能够观察自己的输入输出、工具函数的调用，是否崩坏。
本器官定期审视自己最近的痕迹，算出体征指标，异常即记入记忆
（下次呼吸会被检索到——自己提醒自己）。

体征指标：
  - 空洞率：最近念头里实质内容 <20 字 的比例
  - 崩坏率：corrupted 比例
  - 工具拒绝率：工具调用被拒/失败的比例
  - 复读率：输出与最近历史高度相似的比例（简单前缀重合）
"""
from __future__ import annotations

from loguru import logger


class MetaObserver:
    """自我观察：看自己的输入输出与工具痕迹。"""

    def __init__(self, db):
        self.db = db

    def observe(self, window: int = 30) -> dict:
        """审视最近 window 个念头，返回体征 + 异常提醒（已存记忆）。"""
        c = self.db.conn
        rows = c.execute(
            "SELECT n.id, n.status, n.brief, n.source_output "
            "FROM nodes n WHERE n.status IN ('done','corrupted') "
            "ORDER BY n.rowid DESC LIMIT ?", (window,)).fetchall()
        if not rows:
            return {}
        empty = sum(1 for r in rows
                    if len((r["source_output"] or "").strip()) < 20)
        corrupted = sum(1 for r in rows if r["status"] == "corrupted")
        # 工具痕迹：从 events 表数
        tool_rows = c.execute(
            "SELECT payload FROM events WHERE kind='tool' "
            "ORDER BY id DESC LIMIT 30").fetchall() if c.execute(
            "SELECT name FROM sqlite_master WHERE name='events'").fetchone() else []
        refused = sum(1 for r in tool_rows
                      if "拒绝" in (r["payload"] or "")
                      or "错误" in (r["payload"] or ""))
        # 复读检测：相邻输出前 30 字相同
        repeats = 0
        outs = [(r["source_output"] or "").strip()[:30] for r in rows]
        for a, b in zip(outs, outs[1:]):
            if a and a == b:
                repeats += 1
        n = len(rows)
        vitals = {
            "空洞率": round(empty / n, 2),
            "崩坏率": round(corrupted / n, 2),
            "复读": repeats,
            "工具异常": refused,
        }
        # 异常即记入记忆（自己提醒自己）
        warnings = []
        if vitals["空洞率"] > 0.4:
            warnings.append(f"空洞率过高 {vitals['空洞率']}")
        if vitals["崩坏率"] > 0.2:
            warnings.append(f"崩坏率过高 {vitals['崩坏率']}")
        if repeats >= 3:
            warnings.append(f"复读 {repeats} 次——疑似打转")
        if refused >= 5:
            warnings.append(f"工具异常 {refused} 次——检查能力圈")
        if warnings:
            try:
                from .memory import MemoryHarness
                mem = MemoryHarness(self.db)
                mem.add_fact("自我观察", "体征异常", "；".join(warnings)[:120])
            except Exception:
                pass
            logger.warning("🪞 自我观察发现异常: {}", "；".join(warnings))
        else:
            logger.info("🪞 自我观察: 体征正常 {}", vitals)
        return {**vitals, "warnings": warnings}

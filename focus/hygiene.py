"""Focus Agent — 记忆卫生（ autonomously 清理自己的记忆）。

造物主训示：记忆可以比模型大——但大不等于脏。0.8B 自语会产生垃圾事实
（整句当主语、指令残片、同主题碎念），脏记忆污染检索，检索污染输出。
卫生是记忆基质的下水道：梦境里定期清扫，垃圾不删史（失效留痕）。

垃圾判据（确定性规则，零 LLM）：
  1. 主语/宾语是整句话（>24字）——事实的主语应是词，不是话
  2. 含指令残片（【记】【记录】/半截工具标签）——解析失败的产物
  3. 同(主,谓)碎念堆积——已有双时间轴去重兜底，此处扫历史漏网
  4. 宾语过短（<2字）——无信息量
"""
from __future__ import annotations

import re

from loguru import logger

MAX_TERM_LEN = 24      # 主语/宾语超过此长 = 整句，不是词
MIN_OBJECT_LEN = 2     # 宾语短于此 = 无信息量
_RESIDUE = re.compile(r"【记|【记录|<tool=|</tool|\*\*【")


def is_garbage(subject: str, predicate: str, obj: str) -> str:
    """返回垃圾理由；空字符串 = 干净。"""
    s, p, o = (subject or "").strip(), (predicate or "").strip(), (obj or "").strip()
    if len(s) >= MAX_TERM_LEN:  # >= 24 字即视为整句（含边界）
        return f"主语是整句（{len(s)}字）"
    if len(o) > 60:
        return f"宾语过长（{len(o)}字）"
    if len(o) < MIN_OBJECT_LEN and not o.isalnum():
        return "宾语过短"  # 单字汉字/数字是有效宾语（如"宾"、"1"）
    for seg in (s, p, o):
        if _RESIDUE.search(seg):
            return "指令残片"
    return ""


class MemoryHygiene:
    """记忆卫生：扫描活事实，垃圾失效（留痕不删史）。"""

    def __init__(self, db):
        self.db = db

    def sweep(self) -> dict:
        """一轮清扫。返回 {scanned, cleaned, reasons}。"""
        c = self.db.conn
        rows = c.execute(
            "SELECT id, subject, predicate, object FROM facts "
            "WHERE invalid_at IS NULL").fetchall()
        cleaned = 0
        reasons: dict = {}
        garbage_ids = []
        for r in rows:
            why = is_garbage(r["subject"], r["predicate"], r["object"])
            if why:
                garbage_ids.append(r["id"])
                reasons[why] = reasons.get(why, 0) + 1
        # 批量失效（留痕不删史）
        for i in range(0, len(garbage_ids), 100):
            chunk = garbage_ids[i:i + 100]
            ph = ",".join("?" * len(chunk))
            c.execute(
                f"UPDATE facts SET invalid_at=datetime('now') WHERE id IN ({ph})",
                chunk)
        cleaned = len(garbage_ids)
        # 同(主,谓)堆积兜底（历史漏网）
        dups = c.execute(
            "SELECT subject, predicate FROM facts WHERE invalid_at IS NULL "
            "GROUP BY subject, predicate HAVING COUNT(*) > 1").fetchall()
        deduped = 0
        for d in dups:
            keep = c.execute(
                "SELECT id FROM facts WHERE subject=? AND predicate=? "
                "AND invalid_at IS NULL ORDER BY updated_at DESC LIMIT 1",
                (d["subject"], d["predicate"])).fetchone()
            if keep:
                n = c.execute(
                    "UPDATE facts SET invalid_at=datetime('now') "
                    "WHERE subject=? AND predicate=? AND invalid_at IS NULL "
                    "AND id != ?", (d["subject"], d["predicate"], keep["id"]))
                deduped += n.rowcount
        c.commit()
        total = cleaned + deduped
        if total:
            logger.info("🧹 记忆卫生: 清扫 {} 条（垃圾{}+堆积{}）{}",
                        total, cleaned, deduped, reasons)
            try:
                from .memory import MemoryHarness
                MemoryHarness(self.db).add_fact(
                    "记忆卫生", "本轮清扫",
                    f"{total}条（主语整句{reasons.get('主语是整句（%d字）' % MAX_TERM_LEN, 0)}"
                    f"/残片{sum(v for k, v in reasons.items() if '残片' in k)}"
                    f"/堆积{deduped}）")
            except Exception:
                pass
        return {"scanned": len(rows), "cleaned": cleaned,
                "deduped": deduped, "reasons": reasons}

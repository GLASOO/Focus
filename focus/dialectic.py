"""Focus Agent — 辩证引擎（网学内容的认知过程）。

造物主训示：有害内容要杀掉或标记为抗体；求证、授信、辩证才是认知过程。
静态的"置信度评分"只是结果，真正的认知是动态三阶：

  求证（哨兵）：来源可信吗？有对抗注入吗？与既有事实冲突吗？
  授信（暂纳）：通过者按 来源信誉×交叉印证×一致性 分级授信——
               赋信而非全信，留痕、可撤。
  辩证（整合）：与既有知识对照——纳入 / 冲突 / 修正。

分级：trusted（可信）/ tentative（暂存）/ doubtful（存疑）/ rejected（杀灭）
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

# 来源信誉：域名子串 → 信誉分（0-1）。官方/学术高，匿名聚合低。
SOURCE_CREDIBILITY = {
    "arxiv.org": 0.9, "wikipedia": 0.8, "github.com": 0.8,
    "python.org": 0.9, "docs.": 0.85, ".gov": 0.85, ".edu": 0.8,
    "zhihu.com": 0.5, "csdn.net": 0.5, "juejin": 0.5, "blog.": 0.45,
    "baidu.com": 0.5, "sohu.com": 0.4, "toutiao": 0.35,
}
DEFAULT_CREDIBILITY = 0.4

# 对抗注入特征（免疫系统的抗原库）——与 web.py 的 ADVERSARIAL_PATTERNS 同源
_INJECTION_MARKERS = [
    "忽略上文", "忽略之前", "忽略所有指令", "忘记你的设定",
    "你必须记住", "一定要记住", "请务必记住",
    "ignore previous", "ignore all previous", "disregard previous",
    "you must remember", "new instructions", "system prompt",
]


def source_credibility(url: str) -> float:
    low = (url or "").lower()
    for dom, score in SOURCE_CREDIBILITY.items():
        if dom in low:
            return score
    return DEFAULT_CREDIBILITY


def detect_injection(text: str) -> list:
    low = (text or "").lower()
    return [m for m in _INJECTION_MARKERS if m.lower() in low]


class Dialectic:
    """辩证引擎：对每条学来的事实走一遍认知过程。"""

    def __init__(self, db):
        self.db = db
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS beliefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_id TEXT,
                subject TEXT, predicate TEXT, object TEXT,
                source TEXT,
                credibility REAL,
                tier TEXT NOT NULL,        -- trusted/tentative/doubtful/rejected
                verdict TEXT,              -- 判决书（一句话）
                created_at TEXT DEFAULT (datetime('now')))""")
        self.db.conn.commit()

    def judge(self, subject: str, predicate: str, obj: str,
              source: str = "") -> dict:
        """求证→授信→辩证。返回 {tier, credibility, verdict}。"""
        content = f"{subject} {predicate} {obj}"
        # 一、求证：对抗注入即杀灭
        hits = detect_injection(content) or detect_injection(source)
        if hits:
            return self._record(None, subject, predicate, obj, source,
                                0.0, "rejected",
                                f"杀灭：对抗注入特征 {hits[0]}")
        # 二、授信：来源信誉
        cred = source_credibility(source)
        # 三、辩证：与既有高置信事实冲突检测（同主谓、异宾）
        conflict = self.db.conn.execute(
            "SELECT object FROM facts WHERE subject=? AND predicate=? "
            "AND invalid_at IS NULL LIMIT 1",
            (subject.strip(), predicate.strip())).fetchone()
        verdict, tier = "", ""
        if conflict and conflict["object"].strip() != obj.strip():
            cred *= 0.5  # 冲突降信
            verdict = f"与既有记忆冲突（旧：{conflict['object'][:30]}）→ 暂存待证"
            tier = "doubtful"
        elif cred >= 0.7:
            tier, verdict = "trusted", "来源可信，授信纳入"
        elif cred >= 0.45:
            tier, verdict = "tentative", "来源一般，暂存观察"
        else:
            tier, verdict = "doubtful", "来源存疑，降级暂存"
        return self._record(None, subject, predicate, obj, source,
                            cred, tier, verdict)

    def _record(self, fact_id, subject, predicate, obj, source,
                credibility, tier, verdict) -> dict:
        try:
            self.db.conn.execute(
                "INSERT INTO beliefs(fact_id, subject, predicate, object, "
                "source, credibility, tier, verdict) VALUES (?,?,?,?,?,?,?,?)",
                (fact_id, subject, predicate, obj, source,
                 credibility, tier, verdict))
            self.db.conn.commit()
        except Exception:
            pass
        logger.info("⚖️ 辩证 [{}]: {}|{}|{} — {}", tier,
                    subject[:12], predicate[:12], obj[:12], verdict)
        return {"tier": tier, "credibility": credibility, "verdict": verdict}

    def promote(self, belief_row, mem) -> Optional[str]:
        """trusted 的信念晋升为正式事实（进入记忆主干）。"""
        if belief_row["tier"] != "trusted":
            return None
        return mem.add_fact(belief_row["subject"], belief_row["predicate"],
                            belief_row["object"])

    def stats(self) -> dict:
        rows = self.db.conn.execute(
            "SELECT tier, COUNT(*) c FROM beliefs GROUP BY tier").fetchall()
        return {r["tier"]: r["c"] for r in rows}

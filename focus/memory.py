"""Focus Agent — Memory Harness（记忆系统 v2 · M1）

设计文档：《Focus Agent — 记忆系统重构设计 v2.0.md》
四层记忆：
  L0 Episode  nodes.source_output（原始念头，全量保留，天然证据链）
  L1 事实     facts 表（subject|predicate|object，双时间轴，失效而非覆盖）
  L2 Wiki     wiki 表（M3 由 DMN Dreaming 汇编）
  L3 Core     self_map.core_memory（≤800字，恒注入）

0.8B 适配要点：
  - 记忆指令协议【记】【忘】【忆】：固定符号格式，纯正则解析（小模型做不好
    JSON 工具调用，但很会模仿固定格式——与解析【思考】/[DONE]同路数）
  - 检索零 LLM：FTS5(BM25) + LIKE 兜底 + 图遍历 + 时间衰减，亚秒级
"""

from __future__ import annotations

import math
import re
import sqlite3
import time
import uuid
from collections import deque
from typing import Optional

from loguru import logger

from .observability import EventLog

CORE_MAX = 800          # L3 注入预算（对标 Claude core/ ≤1000字）
FACTS_BUDGET = 500      # 检索事实注入预算
DECAY_DAYS = 30.0       # 时间衰减半衰期（天）

# ── 记忆指令协议 ────────────────────────────────────
_RE_RECORD = re.compile(r"^【记】\s*(.+?)\s*[|｜]\s*(.+?)\s*[|｜]\s*(.+?)\s*$")
_RE_FORGET = re.compile(r"^【忘】\s*(.+?)\s*$")
_RE_RECALL = re.compile(r"^【忆】\s*(.+?)\s*$")


def parse_directives(text: str):
    """解析呼吸输出中的记忆指令。返回 (records, forgets, recalls)。

    records: [(subject, predicate, object)]  forgets: [str]  recalls: [str]
    解析失败的行静默丢弃——指令是增量，不许影响念头落盘。
    """
    records, forgets, recalls = [], [], []
    for line in (text or "").splitlines():
        line = line.strip().replace("｜", "|")
        if not line:
            continue
        # 容错（2026-08-14 实机评测）：0.8B 有时漏写【记】头，
        # 裸 "主|谓|宾" 三段式同样受理
        if line.count("|") == 2 and not line.startswith("【"):
            s, p, o = [x.strip() for x in line.split("|")]
            if s and p and o:
                records.append((s, p, o))
                continue
        m = _RE_RECORD.match(line)
        if m:
            records.append((m.group(1), m.group(2), m.group(3)))
            continue
        m = _RE_FORGET.match(line)
        if m:
            forgets.append(m.group(1))
            continue
        m = _RE_RECALL.match(line)
        if m:
            recalls.append(m.group(1))
    return records, forgets, recalls


class MemoryHarness:
    """记忆系统 v2 的 M1 实现：事实层 + 检索 + 组装。"""

    def __init__(self, db):
        self.db = db
        self.recall_queue: deque = deque(maxlen=8)  # 【忆】主动回忆队列（M2 消费）
        self._embedder = None        # 向量路（战役2：DMN 注入 nomic）
        from .memory_index import VectorIndex
        self._vindex = VectorIndex(db)  # 记忆基质：十万级事实的亚秒检索
        self._events = EventLog(db)  # 事件溯源（战役3）
        self.ensure_schema()

    # ── Schema ────────────────────────────────────
    def ensure_schema(self) -> None:
        c = self.db.conn
        c.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                source_node TEXT,          -- 证据下钻 → nodes.id
                valid_at TEXT DEFAULT (datetime('now')),
                invalid_at TEXT,           -- NULL = 当前有效（Zep 双时间轴）
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_facts_sp "
                  "ON facts(subject, predicate, invalid_at)")
        try:
            c.execute("CREATE VIRTUAL TABLE facts_fts USING fts5"
                      "(subject, predicate, object)")
        except sqlite3.OperationalError:
            pass  # FTS5 不可用 → 退化为纯 LIKE（中文主力本来就是 LIKE）
        c.execute("""
            CREATE TABLE IF NOT EXISTS wiki (
                topic TEXT PRIMARY KEY,
                category TEXT DEFAULT '概念',
                content TEXT,
                updated_at TEXT DEFAULT (datetime('now')))""")
        # 战役2：facts 向量列（幂等）
        try:
            c.execute("ALTER TABLE facts ADD COLUMN embedding BLOB")
        except sqlite3.OperationalError:
            pass
        # core_memory 列（幂等）
        try:
            c.execute("ALTER TABLE self_map ADD COLUMN core_memory TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        c.commit()

    # ── 写入：失效而非覆盖 ─────────────────────────
    def add_fact(self, subject: str, predicate: str, obj: str,
                 source_node: Optional[str] = None) -> str:
        """同三元组 → 续期；同(主,谓)不同宾 → 旧事实失效（Zep 模式）。"""
        c = self.db.conn
        subject, predicate, obj = subject.strip(), predicate.strip(), obj.strip()
        if not (subject and predicate and obj):
            return ""
        if subject == predicate == obj:
            return ""  # 同段复读 = 垃圾（实测 0.8B 输出过 三段全同）
        row = c.execute(
            "SELECT id FROM facts WHERE subject=? AND predicate=? AND object=? "
            "AND invalid_at IS NULL", (subject, predicate, obj)).fetchone()
        if row:  # 完全相同 → 续期
            c.execute("UPDATE facts SET updated_at=datetime('now') WHERE id=?",
                      (row["id"],))
            self._fts_sync(row["id"], subject, predicate, obj)
            c.commit()
            return row["id"]
        c.execute("UPDATE facts SET invalid_at=datetime('now') "
                  "WHERE subject=? AND predicate=? AND invalid_at IS NULL",
                  (subject, predicate))
        fid = uuid.uuid4().hex[:12]
        c.execute("INSERT INTO facts (id, subject, predicate, object, source_node) "
                  "VALUES (?,?,?,?,?)", (fid, subject, predicate, obj, source_node))
        self._fts_sync(fid, subject, predicate, obj)
        c.commit()
        return fid

    def _fts_sync(self, fid: str, s: str, p: str, o: str) -> None:
        try:
            rowid = self.db.conn.execute(
                "SELECT rowid FROM facts WHERE id=?", (fid,)).fetchone()[0]
            self.db.conn.execute(
                "DELETE FROM facts_fts WHERE rowid=?", (rowid,))
            self.db.conn.execute(
                "INSERT INTO facts_fts(rowid, subject, predicate, object) "
                "VALUES (?,?,?,?)", (rowid, s, p, o))
        except sqlite3.OperationalError:
            pass  # 无 FTS5

    def forget(self, spec: str) -> int:
        """【忘】主语|谓语 或 事实id → 失效。返回影响行数。"""
        c = self.db.conn
        spec = spec.strip()
        if "|" in spec or "｜" in spec:
            s, p = re.split(r"[|｜]", spec, maxsplit=1)
            r = c.execute("UPDATE facts SET invalid_at=datetime('now') "
                          "WHERE subject=? AND predicate=? AND invalid_at IS NULL",
                          (s.strip(), p.strip()))
        else:
            r = c.execute("UPDATE facts SET invalid_at=datetime('now') "
                          "WHERE id=? AND invalid_at IS NULL", (spec,))
        c.commit()
        return r.rowcount

    # ── 观察：呼吸落盘后的唯一入口 ──────────────────
    def observe(self, node_id: str, output: str) -> dict:
        """解析一次呼吸输出中的记忆指令并落账。"""
        records, forgets, recalls = parse_directives(output or "")
        added = [self.add_fact(s, p, o, source_node=node_id)
                 for s, p, o in records]
        for spec in forgets:
            self.forget(spec)
        for q in recalls:
            self.recall_queue.append(q)
        if records or forgets or recalls:
            logger.info("🧠 记忆落账 node={}: 记{} 忘{} 忆{}",
                        node_id[:8], len(records), len(forgets), len(recalls))
            self._events.emit("memory", node_id[:8],
                              {"记": len(records), "忘": len(forgets),
                               "忆": recalls})
        return {"added": [a for a in added if a], "forgot": len(forgets),
                "recalls": recalls}

    # ── 检索：零 LLM，三路融合 ──────────────────────
    def search_memory(self, query: str, node_id: Optional[str] = None,
                      k: int = 5) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        c = self.db.conn
        cand: dict[str, float] = {}
        facts_by_id: dict[str, dict] = {}

        def feed(rows, score):
            for r in rows:
                d = dict(r)
                facts_by_id[d["id"]] = d
                cand[d["id"]] = max(cand.get(d["id"], 0.0), score)

        # 1. FTS5 BM25（ASCII/混合词主力）
        try:
            q = '"' + query.replace('"', ' ') + '"'
            rows = c.execute(
                "SELECT f.* FROM facts_fts t JOIN facts f ON f.rowid=t.rowid "
                "WHERE facts_fts MATCH ? AND f.invalid_at IS NULL LIMIT 20",
                (q,)).fetchall()
            feed(rows, 2.0)
        except sqlite3.OperationalError:
            pass
        # 2. LIKE 兜底（中文短事实主力——FTS unicode61 不切中文词）
        like = f"%{query}%"
        feed(c.execute(
            "SELECT * FROM facts WHERE invalid_at IS NULL AND "
            "(subject LIKE ? OR predicate LIKE ? OR object LIKE ?) LIMIT 20",
            (like, like, like)).fetchall(), 1.5)
        # 3. 图遍历：当前节点及邻居产出的事实（关系推理）
        if node_id:
            nbrs = [node_id] + [r["target_id"] for r in c.execute(
                "SELECT target_id FROM edges WHERE source_id=?", (node_id,))]
            ph = ",".join("?" * len(nbrs))
            feed(c.execute(
                f"SELECT * FROM facts WHERE invalid_at IS NULL AND source_node "
                f"IN ({ph}) LIMIT 10", nbrs).fetchall(), 1.0)
        # 4. 向量余弦（战役2：三路齐备）
        feed(self._vector_search(query, k=10), 1.8)

        # 时间衰减 + 排序 + 同主语去重（MMR 思想，最多2条/主语）
        now = time.time()
        scored = []
        for fid, base in cand.items():
            f = facts_by_id[fid]
            try:
                va = time.mktime(time.strptime(f["valid_at"], "%Y-%m-%d %H:%M:%S"))
                age_days = max(0.0, (now - va) / 86400.0)
            except Exception:
                age_days = 0.0
            scored.append((base * math.exp(-age_days / DECAY_DAYS), f))
        scored.sort(key=lambda x: -x[0])
        out, per_subj = [], {}
        for _, f in scored:
            n = per_subj.get(f["subject"], 0)
            if n >= 2:
                continue
            per_subj[f["subject"]] = n + 1
            out.append(f)
            if len(out) >= k:
                break
        return out

    # ── L3 Core ────────────────────────────────────
    def get_core(self) -> str:
        row = self.db.conn.execute(
            "SELECT core_memory FROM self_map LIMIT 1").fetchone()
        return (row["core_memory"] or "") if row else ""

    def set_core(self, text: str) -> None:
        self.db.conn.execute(
            "UPDATE self_map SET core_memory=?", (text[:CORE_MAX],))
        self.db.conn.commit()

    # ── 向量路（战役2：检索三路齐备） ────────────────
    def set_embedder(self, embedder) -> None:
        """注入嵌入器（DMN 的 nomic-embed）。"""
        self._embedder = embedder

    def ensure_fact_embeddings(self, limit: int = 50) -> int:
        """给缺向量的活事实补嵌入（Dreaming 时调用）。返回补的条数。"""
        if self._embedder is None:
            return 0
        c = self.db.conn
        rows = c.execute(
            "SELECT id, subject, predicate, object FROM facts "
            "WHERE invalid_at IS NULL AND embedding IS NULL LIMIT ?",
            (limit,)).fetchall()
        if not rows:
            return 0
        import numpy as np
        texts = [f"{r['subject']} {r['predicate']} {r['object']}" for r in rows]
        try:
            vecs = self._embedder.embed(texts)
        except Exception:
            return 0
        n = 0
        for r, v in zip(rows, vecs):
            c.execute("UPDATE facts SET embedding=? WHERE id=?",
                      (np.asarray(v, dtype=np.float32).tobytes(), r["id"]))
            n += 1
        c.commit()
        return n

    def _vector_search(self, query: str, k: int = 10) -> list:
        """向量余弦路（2026-08-15 基质扩容：内存矩阵索引，十万级亚秒）。"""
        if self._embedder is None:
            return []
        try:
            qv = self._embedder.embed([query])[0]
        except Exception:
            return []
        hits = self._vindex.search(qv, k=k)
        if not hits:
            return []
        ids = [h[0] for h in hits]
        ph = ",".join("?" * len(ids))
        rows = self.db.conn.execute(
            f"SELECT * FROM facts WHERE id IN ({ph})", ids).fetchall()
        by_id = {r["id"]: dict(r) for r in rows}
        return [by_id[i] for i, _ in hits if i in by_id]

    def compile_wiki(self, max_pages: int = 10) -> int:
        """按主语聚类活事实 → wiki 页（每页≤1000字）。返回页数。"""
        c = self.db.conn
        rows = c.execute(
            "SELECT subject, predicate, object FROM facts "
            "WHERE invalid_at IS NULL ORDER BY subject, updated_at DESC"
        ).fetchall()
        pages: dict = {}
        for r in rows:
            pages.setdefault(r["subject"], []).append(r)
        n = 0
        for subj, fs in list(pages.items())[:max_pages]:
            lines = [f"- {f['predicate']}：{f['object']}" for f in fs[:20]]
            content = (f"主题：{subj}\n" + "\n".join(lines))[:1000]
            c.execute("INSERT INTO wiki(topic, category, content, updated_at) "
                      "VALUES (?,?,?,datetime('now')) "
                      "ON CONFLICT(topic) DO UPDATE SET content=excluded.content,"
                      " updated_at=excluded.updated_at",
                      (subj[:80], "概念", content))
            n += 1
        c.commit()
        return n

    def get_wiki_page(self, topic: str) -> str:
        r = self.db.conn.execute(
            "SELECT content FROM wiki WHERE topic=?", (topic,)).fetchone()
        return r["content"] if r else ""

    def wiki_topics(self) -> list:
        return [r["topic"] for r in self.db.conn.execute(
            "SELECT topic FROM wiki ORDER BY updated_at DESC LIMIT 20")]

    # ── L3 Core 压缩（规则蒸馏，确定性） ────────────
    def compact_core(self, top_facts: int = 10) -> str:
        """身份 + 里比多状态 + 高价值事实 → core（≤800字）。"""
        sm = self.db.get_self_map()
        parts = [
            (sm.get("identity") or "我是 Focus Agent。")[:120],
            f"里比多状态：{sm.get('libido_state', 'dormant')}"
            f"（聚焦 {sm.get('libido_focus_count', 0)} 次）",
        ]
        facts = self.db.conn.execute(
            "SELECT subject, predicate, object FROM facts "
            "WHERE invalid_at IS NULL ORDER BY updated_at DESC LIMIT ?",
            (top_facts,)).fetchall()
        if facts:
            parts.append("关键认知：" + "；".join(
                f"{f['subject']}{f['predicate']}{f['object']}"
                for f in facts))
        core = "\n".join(parts)[:CORE_MAX]
        self.set_core(core)
        return core

    # ── 矛盾自愈 ────────────────────────────────────
    def dedupe_recent(self, minutes: int = 5) -> int:
        """增量去重：只看最近 N 分钟内变更的 (主,谓) 组（基质扩容配套）。

        add_fact 已保证新增时旧者失效；此函数兜底历史脏数据与并发竞态，
        且只扫增量——十万级事实时代，全表扫描是不可接受的。
        """
        c = self.db.conn
        rows = c.execute(
            "SELECT DISTINCT subject, predicate FROM facts "
            "WHERE updated_at > datetime('now', ?)",
            (f"-{int(minutes*60)} seconds",)).fetchall()
        fixed = 0
        for r in rows:
            keep = c.execute(
                "SELECT id FROM facts WHERE subject=? AND predicate=? "
                "AND invalid_at IS NULL ORDER BY updated_at DESC LIMIT 1",
                (r["subject"], r["predicate"])).fetchone()
            if not keep:
                continue
            n = c.execute(
                "UPDATE facts SET invalid_at=datetime('now') "
                "WHERE subject=? AND predicate=? AND invalid_at IS NULL "
                "AND id != ?", (r["subject"], r["predicate"], keep["id"]))
            fixed += n.rowcount
        if fixed:
            c.commit()
        return fixed

    def dedupe_active(self) -> int:
        """同(主,谓)多条活事实 → 只留最新（自愈历史脏数据）。"""
        c = self.db.conn
        rows = c.execute(
            "SELECT subject, predicate, COUNT(*) n FROM facts "
            "WHERE invalid_at IS NULL GROUP BY subject, predicate HAVING n > 1"
        ).fetchall()
        fixed = 0
        for r in rows:
            keep = c.execute(
                "SELECT id FROM facts WHERE subject=? AND predicate=? "
                "AND invalid_at IS NULL ORDER BY updated_at DESC LIMIT 1",
                (r["subject"], r["predicate"])).fetchone()
            c.execute("UPDATE facts SET invalid_at=datetime('now') "
                      "WHERE subject=? AND predicate=? AND invalid_at IS NULL "
                      "AND id != ?", (r["subject"], r["predicate"], keep["id"]))
            fixed += 1
        c.commit()
        return fixed

    # ── 呼吸前上下文组装（预算裁剪） ────────────────
    def assemble(self, node_brief: str, node_id: Optional[str] = None,
                 budget: int = 1800) -> str:
        parts, used = [], 0

        def push(block: str):
            nonlocal used
            if not block or used + len(block) > budget:
                return
            parts.append(block)
            used += len(block)

        core = self.get_core()
        if core:
            push(f"【核心记忆】\n{core}")
        # 【忆】队列优先，其次节点主题
        queries = list(self.recall_queue) + [node_brief]
        seen_fact_ids: set = set()
        lines = []
        for q in queries:
            for f in self.search_memory(q, node_id=node_id, k=3):
                if f["id"] in seen_fact_ids:
                    continue
                seen_fact_ids.add(f["id"])
                lines.append(f"- {f['subject']}|{f['predicate']}|{f['object']}")
        if lines:
            push("【相关记忆】\n" + "\n".join(lines)[:FACTS_BUDGET])
        return "\n".join(parts)

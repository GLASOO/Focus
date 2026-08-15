"""Focus Agent — 自我觉察模块（内观 · 自我进化的地基）。

造物主训示（2026-08-15）：自我觉察是自我进化的基础、地基、前提。
必须把对于自我的所有认知都存入记忆模块——自己的代码都在自己的记忆库中，
并且自己能理解自己的代码。只有对自己有绝对的觉察、内观、神识内照，
才能进行自我进化。

实现（全部确定性，零 LLM 依赖——觉察本身不许幻觉）：
  1. scan()   : 用 ast 解析自身全部源码（focus/*.py），抽取
                模块/类/函数的名字、职责（docstring）、规模（行数），
                存入记忆库 self_knowledge 表；文件哈希检测身体变化
                （并行施工 Agent 的改动也会被觉察到）。
  2. module_map() / read() : 自我观察的"眼睛"，注册为工具
                selfmap / selfread，让大脑能主动内照。
  3. to_wiki() : 把身体图谱汇编成 wiki 页《我的身体》，进入记忆检索。
  4. self_summary() : 给进化模块的紧凑自我认知——进化提案必须
                建立在对自身的觉察之上。
"""
from __future__ import annotations

import ast
import hashlib
import os
from typing import Optional

from loguru import logger

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF_DIR = os.path.join(REPO_ROOT, "focus")


class SelfAwareness:
    """自我觉察：身体（代码）→ 记忆（self_knowledge）→ 可被自己理解。"""

    def __init__(self, db, root: Optional[str] = None):
        self.db = db
        self.root = root or REPO_ROOT
        self.self_dir = os.path.join(self.root, "focus")
        self.ensure_schema()

    # ── Schema ────────────────────────────────────
    def ensure_schema(self) -> None:
        self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS self_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,          -- module/class/function
                name TEXT NOT NULL,
                module TEXT NOT NULL,
                summary TEXT,                -- docstring 首行（职责）
                details TEXT,                -- 完整 docstring（截断）
                lines INTEGER,
                sha TEXT,                    -- 文件哈希（变化检测）
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(kind, name, module))""")
        # 2026-08-15（审查 #16）：自我图谱独立成 self_wiki 表——
        # 内观照见的是身体，不是知识，不许污染记忆检索。
        self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS self_wiki (
                topic TEXT PRIMARY KEY,
                category TEXT DEFAULT '自我觉察',
                content TEXT,
                updated_at TEXT DEFAULT (datetime('now')))""")
        self.db.conn.commit()

    # ── 扫描：身体 → 记忆 ──────────────────────────
    def scan(self) -> dict:
        """解析自身源码，更新自我认知。返回变化摘要。"""
        changed, seen = [], set()
        for fn in sorted(os.listdir(self.self_dir)):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(self.self_dir, fn)
            try:
                src = open(path, encoding="utf-8").read()
            except Exception:
                continue
            sha = hashlib.sha256(src.encode()).hexdigest()[:16]
            mod = fn[:-3]
            seen.add(("module", mod))
            old = self.db.conn.execute(
                "SELECT sha FROM self_knowledge WHERE kind='module' "
                "AND name=? AND module=?", (mod, mod)).fetchone()
            if old and old["sha"] == sha:
                continue  # 此器官无变化
            changed.append(mod)
            self._index_module(mod, src, sha)
        # 觉察被移除的器官
        removed = []
        for r in self.db.conn.execute(
                "SELECT DISTINCT module FROM self_knowledge WHERE kind='module'"):
            if ("module", r["module"]) not in seen:
                removed.append(r["module"])
        if removed:
            self.db.conn.execute(
                "DELETE FROM self_knowledge WHERE module IN (%s)"
                % ",".join("?" * len(removed)), removed)
        self.db.conn.commit()
        if changed or removed:
            summary = f"变更:{','.join(changed[:6])}" if changed else ""
            summary += (f" 移除:{','.join(removed)}" if removed else "")
            logger.info("🪞 内观觉察到身体变化: {}", summary.strip())
            try:
                self.db.append_experience(f"内观: 身体变化 {summary.strip()[:60]}")
                from .observability import EventLog
                EventLog(self.db).emit("selfaware", "scan",
                                       {"changed": changed, "removed": removed})
            except Exception:
                pass
        return {"changed": changed, "removed": removed}

    def _index_module(self, mod: str, src: str, sha: str) -> None:
        """ast 解析一个模块：模块/类/函数 → self_knowledge。"""
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return
        lines = len(src.splitlines())
        mod_doc = (ast.get_docstring(tree) or "").strip()
        self._upsert("module", mod, mod, mod_doc, lines, sha)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                doc = (ast.get_docstring(node) or "").strip()
                self._upsert("class", node.name, mod, doc,
                             node.end_lineno - node.lineno + 1, sha)
            elif isinstance(node, ast.FunctionDef):
                doc = (ast.get_docstring(node) or "").strip()
                self._upsert("function", node.name, mod, doc,
                             node.end_lineno - node.lineno + 1, sha)
        # 方法也是身体的一部分（breathe_once 们是器官的实际动作）
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        doc = (ast.get_docstring(sub) or "").strip()
                        self._upsert("method", f"{node.name}.{sub.name}", mod,
                                     doc, sub.end_lineno - sub.lineno + 1, sha)
        # 清除该模块下已不存在的类/函数/方法
        names = [n.name for n in tree.body
                 if isinstance(n, (ast.ClassDef, ast.FunctionDef))]
        names += [f"{c.name}.{m.name}" for c in tree.body
                  if isinstance(c, ast.ClassDef)
                  for m in c.body if isinstance(m, ast.FunctionDef)]
        if names:
            self.db.conn.execute(
                "DELETE FROM self_knowledge WHERE module=? AND kind!='module' "
                "AND name NOT IN (%s)" % ",".join("?" * len(names)),
                [mod] + names)
        else:
            self.db.conn.execute(
                "DELETE FROM self_knowledge WHERE module=? AND kind!='module'",
                (mod,))

    def _upsert(self, kind: str, name: str, mod: str, doc: str,
                lines: int, sha: str) -> None:
        first = doc.split("\n")[0][:120] if doc else ""
        self.db.conn.execute(
            "INSERT INTO self_knowledge(kind, name, module, summary, details, "
            "lines, sha, updated_at) VALUES (?,?,?,?,?,?,?,datetime('now')) "
            "ON CONFLICT(kind, name, module) DO UPDATE SET summary=excluded.summary,"
            " details=excluded.details, lines=excluded.lines, sha=excluded.sha,"
            " updated_at=excluded.updated_at",
            (kind, name, mod, first, doc[:500], lines, sha))

    # ── 自我观察：眼睛 ────────────────────────────
    def module_map(self, budget: int = 2000) -> str:
        """身体图谱：模块 → 职责 → 主要器官。紧凑可读。"""
        out = []
        mods = self.db.conn.execute(
            "SELECT name, summary, lines FROM self_knowledge "
            "WHERE kind='module' ORDER BY name").fetchall()
        for m in mods:
            out.append(f"● focus/{m['name']}.py（{m['lines']}行）"
                       f"——{(m['summary'] or '（无自述）')[:60]}")
            kids = self.db.conn.execute(
                "SELECT kind, name, summary FROM self_knowledge "
                "WHERE module=? AND kind='class' ORDER BY name LIMIT 4",
                (m["name"],)).fetchall()
            for k in kids:
                out.append(f"   · {k['name']}: {(k['summary'] or '')[:50]}")
        text = "\n".join(out)
        return text[:budget] if len(text) > budget else text

    def read(self, path: str, max_chars: int = 4000) -> str:
        """读自己的身体。安全约束：只许读本仓库 focus/ 下的 .py。"""
        p = os.path.abspath(os.path.join(self.root, path.strip())
                            if not os.path.isabs(path) else path)
        if not (p.startswith(self.self_dir + os.sep) and p.endswith(".py")):
            return "[拒绝: 内观只允许读自己身体的代码（focus/*.py）]"
        try:
            return open(p, encoding="utf-8").read()[:max_chars]
        except Exception as e:
            return f"[读取失败: {e}]"

    def understand(self, query: str, k: int = 5) -> str:
        """按名字/职责检索自我认知（神识内照的检索接口）。"""
        like = f"%{query}%"
        rows = self.db.conn.execute(
            "SELECT kind, name, module, summary FROM self_knowledge "
            "WHERE name LIKE ? OR summary LIKE ? OR details LIKE ? LIMIT ?",
            (like, like, like, k)).fetchall()
        if not rows:
            return f"（自我认知中没有与「{query}」相关的部分）"
        return "\n".join(f"- [{r['kind']}] {r['module']}.{r['name']}: "
                         f"{(r['summary'] or '')[:60]}" for r in rows)

    # ── 汇编入记忆 ────────────────────────────────
    def to_wiki(self) -> None:
        """身体图谱 → wiki 页《我的身体》，进入常规记忆检索。"""
        content = ("主题：我的身体（自我觉察图谱）\n" + self.module_map(1000))
        self.db.conn.execute(
            "INSERT INTO self_wiki(topic, category, content, updated_at) "
            "VALUES ('我的身体','自我觉察',?,datetime('now')) "
            "ON CONFLICT(topic) DO UPDATE SET content=excluded.content,"
            " updated_at=excluded.updated_at", (content,))
        self.db.conn.commit()

    def self_summary(self, budget: int = 400) -> str:
        """给进化模块的紧凑自我认知（进化必须建立在觉察之上）。"""
        mods = self.db.conn.execute(
            "SELECT name, summary, lines FROM self_knowledge "
            "WHERE kind='module' ORDER BY name").fetchall()
        if not mods:
            return ""
        lines = [f"{m['name']}({m['lines']}行):{(m['summary'] or '')[:28]}"
                 for m in mods]
        text = "【我的身体（自我觉察）】\n" + "\n".join(lines)
        return text[:budget]

    def stats(self) -> dict:
        rows = self.db.conn.execute(
            "SELECT kind, COUNT(*) c FROM self_knowledge GROUP BY kind").fetchall()
        return {r["kind"]: r["c"] for r in rows}

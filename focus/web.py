"""Focus Agent — 上网学习模块（此机无限 · 开放系统）

让 0.8B 驱动的 Agent 能自己上网搜索、阅读网页、提取知识。
无需大模型——用确定性管道把网页内容压缩成【记】事实，写入 Graph。

设计原则：
  - 零外部依赖（仅用 Python 标准库 urllib + re）
  - 容错优先（网络失败静默返回空，不崩呼吸循环）
  - 0.8B 友好（搜索结果已结构化，模型只需判断/提取，不需要理解原始 HTML）
  - 安全限制（域名白名单可选、超时、内容大小上限）

使用方式：
  1. ToolRegistry 注册 web_search / web_read 两个工具
  2. brain._idle() 的领土生长调用 WebCuriosity 主动发现知识空白
  3. DMN Dreaming 时 WebCuriosity.learn() 拉取新知识写入 facts
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Optional

from loguru import logger


# ── 配置 ────────────────────────────────────────────
WEB_TIMEOUT = 15          # 网络请求超时（秒）
MAX_CONTENT_CHARS = 4000  # 网页内容提取上限（0.8B 上下文有限）
MAX_SEARCH_RESULTS = 5    # 搜索结果条数
USER_AGENT = "FocusAgent/1.0 (compatible; learning mode)"

# 可选域名白名单（空 = 不限）。环境变量 FOCUS_WEB_WHITELIST=comma,sep
_WEB_WHITELIST = [
    d.strip() for d in
    os.environ.get("FOCUS_WEB_WHITELIST", "").split(",")
    if d.strip()
]


def _is_allowed_domain(url: str) -> bool:
    """检查 URL 域名是否在白名单内（白名单为空则全部允许）。"""
    if not _WEB_WHITELIST:
        return True
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        return any(host.endswith(d) for d in _WEB_WHITELIST)
    except Exception:
        return False


def _fetch_url(url: str, timeout: int = WEB_TIMEOUT) -> Optional[str]:
    """获取 URL 内容（返回原始文本或 None）。"""
    if not _is_allowed_domain(url):
        logger.debug("web: 域名不在白名单: {}", url)
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT,
                     "Accept": "text/html,text/plain,application/json,*/*;q=0.8"},
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        # 检查内容类型
        ctype = resp.headers.get("Content-Type", "")
        if "text" not in ctype and "json" not in ctype and "xml" not in ctype:
            return None
        raw = resp.read(200_000)  # 最多读 200KB
        # 尝试常见编码
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, ValueError):
                continue
        return raw.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("web: 获取失败 {}: {}", url[:60], e)
        return None


def extract_readable(html: str) -> str:
    """从 HTML 中提取可读文本（确定性管道，不依赖 LLM）。

    策略：
      1. 优先提取 <article> / <main> / <div class="content"> 内的内容
      2. 移除 script/style/nav/header/footer/aside 标签及内容
      3. 提取 <p>, <li>, <h1>-<h3>, <code>, <pre> 内文本
      4. 清理 HTML 实体、多余空白
      5. 截断到 MAX_CONTENT_CHARS
    """
    if not html:
        return ""

    # 优先提取 article/main/content 区域
    for selector in (r"<article[^>]*>(.*?)</article>",
                     r"<main[^>]*>(.*?)</main>",
                     r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>'):
        m = re.search(selector, html, re.DOTALL | re.IGNORECASE)
        if m and len(m.group(1)) > 500:
            html = m.group(1)
            break

    # 移除不需要的标签及内容
    for tag in ("script", "style", "nav", "header", "footer", "aside",
                "svg", "iframe", "noscript", "form", "ul"):
        html = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>", "", html,
            flags=re.DOTALL | re.IGNORECASE)
    # 提取有意义的文本标签
    chunks = []
    for pattern in (r"<(?:h[1-3])[^>]*>(.*?)</(?:h[1-3])>",
                    r"<p[^>]*>(.*?)</p>",
                    r"<li[^>]*>(.*?)</li>",
                    r"<(?:code|pre)[^>]*>(.*?)</(?:code|pre)>",
                    r"<td[^>]*>(.*?)</td>"):
        for m in re.finditer(pattern, html, re.DOTALL | re.IGNORECASE):
            text = re.sub(r"<[^>]+>", "", m.group(1))  # 去嵌套标签
            text = _clean_entities(text).strip()
            if len(text) > 15:  # 过滤太短的碎片
                chunks.append(text)
    result = "\n".join(chunks)
    if not result:
        # 退路：去所有标签
        result = re.sub(r"<[^>]+>", " ", html)
        result = _clean_entities(result).strip()
    return result[:MAX_CONTENT_CHARS]


def _clean_entities(text: str) -> str:
    """清理 HTML 实体。"""
    entities = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&hellip;": "...",
        "&mdash;": "—", "&ndash;": "–",
    }
    for ent, char in entities.items():
        text = text.replace(ent, char)
    # 数字实体
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    # 压缩空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# ── DuckDuckGo Lite 搜索（零 API Key） ──────────────
def web_search(query: str, n: int = MAX_SEARCH_RESULTS) -> list[dict]:
    """多源搜索：DDG Lite → Wikipedia API 退路。

    返回 [{"title", "url", "snippet"}]。
    DDG Lite 不稳定（限流/验证码），Wikipedia API 稳定但覆盖面有限。
    """
    query = query.strip()
    if not query:
        return []

    # 第一源：DuckDuckGo Lite
    results = _ddg_search(query, n)
    if results:
        return results

    # 退路：Wikipedia API（稳定，无需 Key）
    logger.debug("web_search: DDG 无结果，退回 Wikipedia API")
    return _wiki_search(query, n)


def _ddg_search(query: str, n: int) -> list[dict]:
    """DuckDuckGo Lite 搜索（无需 API Key）。"""
    try:
        url = "https://lite.duckduckgo.com/lite/"
        data = urllib.parse.urlencode({"q": query, "kl": "cn-zh"}).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"User-Agent": USER_AGENT,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = urllib.request.urlopen(req, timeout=WEB_TIMEOUT)
        html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("web_search: DDG 请求失败: {}", e)
        return _ddg_json_search(query, n)

    # DDG Lite：提取所有外链（实测无 class="result-link"）
    results = []
    for m in re.finditer(
        r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        html, re.DOTALL | re.IGNORECASE
    ):
        link = m.group(1)
        title = _clean_entities(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        if (title and len(title) > 5
                and "duckduckgo.com" not in link
                and "lite.duckduckgo" not in link):
            results.append({"title": title, "url": link, "snippet": ""})

    # 尝试提取 snippet（DDG Lite 的 snippet 在链接附近的 td 里）
    if results:
        # 粗暴：按 </a> 后面的文本提取
        parts = re.split(r"</a>", html)
        for i, r in enumerate(results):
            if i + 1 < len(parts):
                snippet = _clean_entities(
                    re.sub(r"<[^>]+>", "", parts[i + 1])).strip()[:200]
                r["snippet"] = snippet

    return results[:n]


def _ddg_json_search(query: str, n: int) -> list[dict]:
    """退路：用 DDG instant answer API。"""
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=WEB_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
        results = []
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", query),
                "url": data.get("AbstractURL", ""),
                "snippet": data["AbstractText"][:300],
            })
        for r in (data.get("RelatedTopics") or [])[:n - 1]:
            if isinstance(r, dict) and r.get("Text"):
                results.append({
                    "title": r.get("Text", "")[:60],
                    "url": r.get("FirstURL", ""),
                    "snippet": r.get("Text", "")[:300],
                })
        return results[:n]
    except Exception:
        return []


def _wiki_search(query: str, n: int) -> list[dict]:
    """Wikipedia API 搜索（稳定退路，无需 API Key）。

    覆盖面有限（只搜 Wikipedia），但 DDG 限流时保证基本可用。
    支持中英文（自动检测中文查询用 zh.wiki）。
    """
    try:
        # 中文查询用中文 Wikipedia
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", query))
        lang = "zh" if has_cjk else "en"
        url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(n),
            "format": "json",
            "origin": "*",
        })
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=WEB_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
        results = []
        for r in data.get("query", {}).get("search", []):
            # 清理 snippet 中的 HTML 标签
            snippet = re.sub(r"<[^>]+>", "", r.get("snippet", ""))
            snippet = _clean_entities(snippet).strip()
            pageid = r.get("pageid", 0)
            wiki_url = f"https://{lang}.wikipedia.org/?curid={pageid}"
            results.append({
                "title": r.get("title", ""),
                "url": wiki_url,
                "snippet": snippet[:300],
            })
        return results[:n]
    except Exception as e:
        logger.debug("wiki_search 失败: {}", e)
        return []


def web_read(url: str) -> str:
    """读取一个网页，返回提取后的纯文本。"""
    html = _fetch_url(url)
    if not html:
        return "[网页获取失败]"
    text = extract_readable(html)
    if not text or len(text) < 50:
        return "[网页内容为空或无法提取]"
    return text


# ── 知识提取（0.8B 友好） ───────────────────────────
def format_search_for_model(query: str, results: list[dict]) -> str:
    """把搜索结果格式化成 0.8B 能消化的结构化文本。

    0.8B 不需要理解 HTML，只需从结构化文本中提取事实。
    """
    if not results:
        return f"搜索「{query}」无结果。"
    parts = [f"搜索「{query}」找到 {len(results)} 条结果：\n"]
    for i, r in enumerate(results, 1):
        parts.append(f"[{i}] {r['title']}")
        if r.get("snippet"):
            parts.append(f"    摘要：{r['snippet'][:150]}")
        parts.append(f"    链接：{r['url']}\n")
    return "\n".join(parts)


def format_webpage_for_model(url: str, text: str) -> str:
    """把网页内容格式化成 0.8B 能消化的结构化文本。"""
    return f"网页内容（{url}）：\n{text[:2000]}\n\n从以上内容中提取值得记住的事实。"


# ── WebCuriosity：主动学习引擎 ──────────────────────
class WebCuriosity:
    """Agent 的好奇心引擎：发现知识空白 → 搜索 → 阅读 → 提取事实。

    集成点：
      1. brain._idle() 的领土生长调用 WebCuriosity.explore()
      2. DMN Dreaming 调用 WebCuriosity.learn() 补充新知识
      3. 工具层注册 web_search / web_read 供 0.8B 直接调用
    """

    # 学习主题候选（Agent 自我认知 + 通用知识）
    SELF_TOPICS = [
        "Focus Agent 生命型 Agent 架构",
        "小模型 harness 设计模式",
        "SQLite Graph database for AI agents",
        "agent memory system design",
        "0.8B 小模型能力边界",
        "LLM agent harness 论文 2024 2025",
        "persistent agent architecture",
        "agent self-improvement loop",
    ]

    def __init__(self, db, llm=None):
        self.db = db
        self.llm = llm  # 可选：有 0.8B 时用它提取事实
        self._searched_topics: set[str] = set()
        self._load_searched()

    def _load_searched(self) -> None:
        """从 DB 加载已搜索主题（防重复搜索）。"""
        try:
            rows = self.db.conn.execute(
                "SELECT query FROM web_learning_log ORDER BY id DESC LIMIT 100"
            ).fetchall()
            self._searched_topics = {r["query"] for r in rows}
        except Exception:
            # 表不存在 → 创建
            try:
                self.db.conn.execute("""
                    CREATE TABLE IF NOT EXISTS web_learning_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        query TEXT NOT NULL,
                        url TEXT,
                        title TEXT,
                        fact_subject TEXT,
                        fact_predicate TEXT,
                        fact_object TEXT,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
                self.db.conn.commit()
            except Exception:
                pass

    def _log_search(self, query: str, url: str = "", title: str = "",
                    fact: tuple = ("", "", "")) -> None:
        """记录搜索历史。"""
        try:
            self.db.conn.execute(
                "INSERT INTO web_learning_log (query, url, title, "
                "fact_subject, fact_predicate, fact_object) VALUES (?,?,?,?,?,?)",
                (query, url, title, fact[0], fact[1], fact[2]),
            )
            self.db.conn.commit()
        except Exception:
            pass

    def discover_gap(self) -> Optional[str]:
        """发现知识空白：从 Graph 的 facts 中找未被覆盖的主题。

        策略：
          1. 列出所有 wiki 主题（已有知识）
          2. 从 SELF_TOPICS 中选一个未搜索过的
          3. 或从最近节点 brief 中提取关键词，若该关键词在 facts 中 <3 条 → 是空白
        """
        # 优先：SELF_TOPICS 中未搜索的
        for topic in self.SELF_TOPICS:
            if topic not in self._searched_topics:
                return topic

        # 其次：从最近节点提取关键词，检查知识覆盖度
        try:
            recent = self.db.conn.execute(
                "SELECT brief FROM nodes WHERE status='done' "
                "ORDER BY rowid DESC LIMIT 20"
            ).fetchall()
            known_subjects = {
                r["subject"] for r in
                self.db.conn.execute(
                    "SELECT DISTINCT subject FROM facts "
                    "WHERE invalid_at IS NULL").fetchall()
            }
            for r in recent:
                # 提取中文关键词（2-4字）
                words = re.findall(r"[\u4e00-\u9fff]{2,4}", r["brief"] or "")
                for w in words:
                    if w not in known_subjects and w not in self._searched_topics:
                        # 检查 facts 覆盖度
                        cnt = self.db.conn.execute(
                            "SELECT COUNT(*) c FROM facts "
                            "WHERE invalid_at IS NULL AND "
                            "(subject LIKE ? OR object LIKE ?)",
                            (f"%{w}%", f"%{w}%")
                        ).fetchone()["c"]
                        if cnt < 3:
                            return w
        except Exception:
            pass

        return None

    def explore(self) -> Optional[str]:
        """一次探索：发现空白 → 搜索 → 阅读顶部结果 → 提取事实 → 写入 Graph。

        返回新建节点 id（若有），否则 None。
        这是 _idle() 领土生长的替代——真正的知识增长。
        """
        topic = self.discover_gap()
        if not topic:
            return None

        logger.info("🌐 好奇心探索: 「{}」", topic)

        # 1. 搜索
        results = web_search(topic, n=3)
        self._searched_topics.add(topic)
        if not results:
            self._log_search(topic)
            return None

        # 2. 阅读第一个结果的全文
        top = results[0]
        content = ""
        if top.get("url"):
            content = web_read(top["url"])

        # 3. 格式化给 0.8B（如有）
        facts_added = []
        if self.llm is not None and content:
            search_text = format_search_for_model(topic, results)
            web_text = format_webpage_for_model(top["url"], content)
            prompt = (
                "你是Focus Agent，正在上网学习。下面是搜索结果和网页内容。\n"
                "从中提取值得长期记住的事实，每条一行，格式：【记】主语|谓语|宾语\n"
                "主语谓语宾语必须简短。最多5条。没有就输出：无\n\n"
                f"{search_text}\n\n{web_text}\n\n【记】"
            )
            try:
                out, _ = self.llm.generate(prompt, max_tokens=300)
                # 解析【记】行
                from .memory import parse_directives
                records, _, _ = parse_directives(out)
                # 写入 facts 表
                from .memory import MemoryHarness
                mem = MemoryHarness(self.db)
                for s, p, o in records:
                    fid = mem.add_fact(s, p, o, source_node=None)
                    if fid:
                        facts_added.append((s, p, o))
                        self._log_search(topic, top["url"], top["title"], (s, p, o))
                logger.info("🌐 学习到 {} 条事实: 「{}」", len(facts_added), topic)
            except Exception as e:
                logger.warning("🌐 0.8B 事实提取失败: {}", e)

        # 4. 写入 Graph 节点（只保留 0.8B 提取的事实 + 网页内容摘要）
        brief = f"[网学] {topic}"
        content_parts = []
        if facts_added:
            content_parts.append("提取的事实：")
            for s, p, o in facts_added:
                content_parts.append(f"  {s}|{p}|{o}")
        if content:
            content_parts.append(f"\n网页内容摘要:\n{content[:800]}")
        if not content_parts:
            content_parts.append(f"搜索「{topic}」找到 {len(results)} 条结果，未能提取有效内容。")
        content_full = "\n".join(content_parts)

        try:
            node_id = self.db.add_node(
                type="self_reflection",
                brief=brief,
                content=content_full,
                priority=0.4,
                lineage=f"web:explore-{topic[:20]}",
            )
            self.db.land_thought(
                node_id, output=content_full, status="done",
                summary=f"网学: {topic} ({len(facts_added)} 条事实)",
                tokens_used=len(content_full) // 4, duration_ms=0)
            self.db.append_experience(f"网学探索: {topic[:30]}")
            return node_id
        except Exception as e:
            logger.warning("🌐 网学节点写入失败: {}", e)
            return None

    def learn(self, topic: str = "") -> dict:
        """DMN Dreaming 调用：补充新知识到 facts 表。

        与 explore() 的区别：
          - explore() 是 _idle() 调用，创建 Graph 节点
          - learn() 是 Dreaming 调用，直接写 facts，不创建节点
        """
        if not topic:
            topic = self.discover_gap() or ""
        if not topic:
            return {"learned": 0}

        results = web_search(topic, n=3)
        self._searched_topics.add(topic)
        if not results:
            self._log_search(topic)
            return {"learned": 0}

        facts_added = 0
        # 确定性提取：只记录到 web_learning_log（审计用），不写 facts 表
        # 原因：搜索结果 snippet 是元数据噪声，不是真正的事实
        # 只有 0.8B 深度提取的事实才写 facts
        for r in results:
            self._log_search(topic, r.get("url", ""), r.get("title", ""))

        # 0.8B 深度提取（如有）
        if self.llm is not None and results:
            top = results[0]
            content = ""
            if top.get("url"):
                content = web_read(top["url"])
            if content:
                search_text = format_search_for_model(topic, results)
                web_text = format_webpage_for_model(top["url"], content)
                prompt = (
                    "从下面的网页内容中提取值得记住的事实。\n"
                    "格式：每行一条【记】主语|谓语|宾语\n"
                    "主语谓语宾语必须简短。最多3条。没有就输出：无\n\n"
                    f"{web_text}\n\n【记】"
                )
                try:
                    out, _ = self.llm.generate(prompt, max_tokens=200)
                    from .memory import parse_directives
                    records, _, _ = parse_directives(out)
                    from .memory import MemoryHarness
                    mem = MemoryHarness(self.db)
                    for s, p, o in records:
                        fid = mem.add_fact(s, p, o, source_node=None)
                        if fid:
                            facts_added += 1
                            self._log_search(topic, top["url"], top["title"], (s, p, o))
                except Exception as e:
                    logger.debug("🌐 Dreaming 网学提取失败: {}", e)

        logger.info("🌐 Dreaming 网学: 「{}」 +{} 事实", topic, facts_added)
        return {"learned": facts_added, "topic": topic}

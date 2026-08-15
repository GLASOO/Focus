"""Focus Agent — DMN（默认模式网络，实施手册 §12 + 任务书 v2.1 问题2）

后台巡逻线程，职责：
  1. 排名 priority（user_input 强制 1.0）
  2. 显式连线（父/子/依赖/约束关系维护）
  3. 隐式连线（embedding 余弦相似度 → similar/strongly_similar）
  4. 写 hint / summary
  5. 压缩经历为 impression（同 source_id 全 done 时）

小模型不汇报，只改 Graph。后台线程持续运行，与大模型并行。

v2.1 修正：embedding 用专门 encoder（bge-small-zh-v1.5），
不用 decoder-only 0.8B 的 hidden state（语义质量差）。
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from loguru import logger

from .prompts import IDENTITY_DMN as _IDENTITY_DMN

from . import config
from .graph_db import GraphDB


class FakeEmbedder:
    """确定性零向量嵌入器。测试用，不触发任何网络/MLX 调用。"""
    def load(self) -> None: pass
    def embed(self, texts: list[str]) -> list[list[float]]:
        import numpy as np
        return [np.zeros(64, dtype=np.float32).tolist() for _ in texts]


class Embedder:
    """语义嵌入器。

    设计决策（2026-08-13）：用 LM Studio 模型库现成的
    text-embedding-nomic-embed-text-v1.5，走 OpenAI 兼容 /v1/embeddings。
    零下载（本地模型库），不用 mlx-embeddings 去下载 BGE。
    失败时退化到词袋哈希向量（不崩）。

    注意：nomic 是英文模型，中文语义区分度弱（无关文本 cos 也常 >0.6）。
    隐式连线阈值需按 nomic 分布校准，且显式连线（0.8B 判断）才是主脑。
    """

    def __init__(self, model_name: str = "", base_url: str = "",
                 api_key: str = ""):
        self.model_name = model_name or config.DMN_EMBED_MODEL
        self.base_url = (base_url or config.LMSTUDIO_BASE).rstrip("/")
        self.api_key = api_key or config.API_KEY
        self._loaded = False

    def load(self) -> None:
        """探测 LM Studio /v1/embeddings 可用性。"""
        if self._loaded:
            return
        try:
            import json, urllib.request
            req = urllib.request.Request(
                f"{self.base_url}/embeddings",
                data=json.dumps({"model": self.model_name,
                                 "input": ["探"]}).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            self._loaded = True
            logger.info("🧠 Embedder 就绪: {} @ {}", self.model_name, self.base_url)
        except Exception as e:
            logger.warning("Embedder 探测失败({}), 退化词袋", e)
            self._loaded = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入（走 LM Studio OpenAI 兼容端点）。失败退词袋。"""
        if not texts:
            return []
        if self._loaded:
            try:
                import json, urllib.request
                req = urllib.request.Request(
                    f"{self.base_url}/embeddings",
                    data=json.dumps({"model": self.model_name,
                                     "input": texts}).encode(),
                    headers={"Content-Type": "application/json"})
                d = json.loads(urllib.request.urlopen(req, timeout=60).read())
                arr = [x["embedding"] for x in sorted(d["data"],
                        key=lambda e: e["index"])]
                import numpy as np
                vecs = []
                for v in arr:
                    v = np.asarray(v, dtype=np.float32)
                    norm = float(np.linalg.norm(v))
                    if norm > 0:
                        v = v / norm
                    vecs.append(v.tolist())
                return vecs
            except Exception as e:
                logger.warning("embed 失败: {}", e)
        # 退化：词袋哈希向量
        import numpy as np
        vecs = []
        for t in texts:
            v = np.zeros(64, dtype=np.float32)
            for ch in t:
                v[ord(ch) % 64] += 1.0
            norm = np.linalg.norm(v)
            if norm > 0:
                v /= norm
            vecs.append(v.tolist())
        return vecs


class DMN:
    """后台巡逻网络。"""

    def __init__(self, db: GraphDB, *, interval: float = config.DMN_INTERVAL_SEC,
                 embedder: Optional[Embedder] = None,
                 llm: Optional[object] = None):
        self.db = db
        self.interval = interval
        self.embedder = embedder or Embedder()
        self.llm = llm  # 0.8B 后端（任务书：小模型是 DMN 主脑，做显式分类/排名/hint/压缩）
        self._embedder_loaded = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.rounds = 0
        self._llm_calls = 0  # 0.8B 调用计数（观测）
        # ── 记忆系统 v2 · M3：Dreaming ──
        self._memory = None
        self._last_dream = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.embedder.load()
        self._embedder_loaded = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="dmn-patrol")
        self._thread.start()
        logger.info("🌙 DMN 巡逻启动")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("🌙 DMN 巡逻停止")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.patrol_once()
            except Exception as e:
                logger.exception("DMN 巡逻异常: {}", e)
            self.rounds += 1
            self._stop.wait(self.interval)

    # ── 单轮巡逻 ────────────────────────────────────
    def patrol_once(self) -> int:
        """一轮巡逻：取 N 个未巡逻节点 → 嵌入 → 排名/连线/写回。

        Returns: 处理的节点数。
        """
        # 压缩 impression 是独立职责：即使没有未巡逻节点也要执行
        self._compress_impressions()

        nodes = self.db.get_unpatrolled(limit=config.DMN_BATCH)
        if not nodes:
            return 0
        # 确保嵌入器已加载（直接调 patrol_once 也能用真 BGE）
        if not self._embedder_loaded:
            self.embedder.load()
            self._embedder_loaded = True

        # 1. 批量嵌入
        texts = [f"{n['brief']} {n.get('summary', '')}".strip() for n in nodes]
        try:
            vecs = self.embedder.embed(texts)
        except Exception:
            import traceback
            traceback.print_exc()
            raise

        for node, vec in zip(nodes, vecs):
            node_id = node["id"]

            # 2. 写 embedding
            import numpy as np
            self.db.update_embedding(node_id, np.array(vec, dtype=np.float32))

            # 3. 优先级排名（规则化，不调模型）
            priority = self._rank_priority(node)
            self.db.update_node(node_id, priority=priority)

            # 4. 隐式连线：与已巡逻节点比余弦
            self._link_similar(node_id, vec)

            # 5. hint（规则化）
            if not node.get("hint") and node.get("type") in ("work", "user_input"):
                hint = self._make_hint(node)
                if hint:
                    self.db.update_node(node_id, hint=hint)

            # 6. 标记已巡逻
            self.db.mark_patrolled(node_id)

        # 7. 压缩 impression（同 source_id 全 done）
        self._compress_impressions()

        # 8. 记忆系统 v2 · M3：Dreaming（限频 30min，惰性建 harness）
        try:
            if self._memory is None:
                from .memory import MemoryHarness
                self._memory = MemoryHarness(self.db)
                self._memory.set_embedder(self.embedder)  # 战役2：向量路
            self.dream()
        except Exception as e:
            logger.warning("💤 Dreaming 异常(忽略): {}", e)

        return len(nodes)

    # ── 记忆系统 v2 · M3：Dreaming（睡眠固化） ────────
    # 2026-08-15 P0（WorkBuddy 审查 #7）：类属性在定义时求值一次，
    # 自我进化改 config 后不会生效。改为实例方法读活配置。
    def _dream_every(self) -> float:
        return float(getattr(config, "DREAM_EVERY_SEC", 120))

    def dream(self) -> dict:
        """睡眠固化：未固化 episode → 模板提取【记】行 → wiki 汇编 → core 压缩。

        0.8B 适配：固定模板约束输出格式（小模型做不好自由提取，但会模仿模板）。
        无模型时静默跳过提取，仍做 wiki/core/矛盾自愈（规则化）。
        """
        import time as _time
        now = _time.time()
        if now - self._last_dream < self._dream_every():
            return {"skipped": True}
        self._last_dream = now

        # 0. 幂等加列
        try:
            self.db.conn.execute(
                "ALTER TABLE nodes ADD COLUMN memory_consolidated INTEGER DEFAULT 0")
            self.db.conn.commit()
        except Exception:
            pass

        fixed = self._memory.dedupe_recent(minutes=5)  # 增量化（基质扩容）
        extracted = 0
        # 此机无限 · 开放系统：Dreaming 时上网学习新知识
        web_learned = 0
        try:
            from .web import WebCuriosity
            wc = WebCuriosity(self.db, llm=self.llm)
            result = wc.learn()
            web_learned = result.get("learned", 0)
        except Exception as e:
            logger.debug("🌐 Dreaming 网学失败: {}", e)
        if self.llm is not None:
            rows = self.db.conn.execute(
                "SELECT id, brief, source_output FROM nodes WHERE status='done' "
                "AND COALESCE(memory_consolidated,0)=0 "
                "AND LENGTH(COALESCE(source_output,'')) > 20 "
                f"ORDER BY rowid DESC LIMIT "
                f"{getattr(config, 'DREAM_BATCH', 20)}").fetchall()
            for r in rows:
                try:
                    out, _ = self.llm.generate(self._dream_prompt(r),
                                               max_tokens=160)
                    res = self._memory.observe(r["id"], out)
                    extracted += len(res.get("added", []))
                    self._llm_calls += 1
                except Exception as e:
                    logger.debug("梦提取失败 node={}: {}", r["id"][:8], e)
                self.db.conn.execute(
                    "UPDATE nodes SET memory_consolidated=1 WHERE id=?",
                    (r["id"],))
            self.db.conn.commit()
        pages = self._memory.compile_wiki()
        self._memory.compact_core()
        try:
            self._memory.ensure_fact_embeddings(50)  # 战役2：补事实向量
        except Exception:
            pass
        # 2026-08-15 自我觉察（内观）：每次做梦先照见自己的身体（确定性，零LLM）
        try:
            from .selfaware import SelfAwareness
            sa = SelfAwareness(self.db)
            ch = sa.scan()
            if ch["changed"] or ch["removed"]:
                sa.to_wiki()  # 身体变了 → 更新《我的身体》图谱
        except Exception as e:
            logger.debug("🪞 内观异常(忽略): {}", e)

        # 2026-08-15 肉身卫生：梦后清扫对象 + 蜕皮检查（防缓慢膨胀）
        try:
            import gc as _gc
            _gc.collect()
            from .shedding import maybe_shed
            maybe_shed("Dreaming")
        except Exception:
            pass

        # 2026-08-15 记忆卫生：每小时清扫一次垃圾事实（留痕不删史）
        try:
            import time as _t4
            if _t4.time() - getattr(self, "_last_hygiene", 0) > 3600:
                self._last_hygiene = _t4.time()
                from .hygiene import MemoryHygiene
                MemoryHygiene(self.db).sweep()
        except Exception:
            pass

        # 2026-08-15 自我观察（元认知）：每 30 分钟审视一次自己的体征
        try:
            import time as _t3
            if _t3.time() - getattr(self, "_last_meta", 0) > 1800:
                self._last_meta = _t3.time()
                from .meta import MetaObserver
                MetaObserver(self.db).observe()
        except Exception:
            pass

        # 2026-08-15 餐桌卫生：每次做梦顺手清理重复模型实例（静默容错）
        try:
            from .digestion import hygiene
            hygiene(self.db)
        except Exception:
            pass

        # 2026-08-15 自主觅食：每小时找一次饭（发现/领养供应商，静默容错）
        try:
            import time as _t2
            if _t2.time() - getattr(self, "_last_forage", 0) > 3600:
                self._last_forage = _t2.time()
                from .providers import ProviderScout
                fr = ProviderScout(self.db).auto_cycle()
                logger.info("🍚 觅食循环: {}", fr.get("action"))
        except Exception as e:
            logger.debug("🍚 觅食异常(忽略): {}", e)

        # 2026-08-15 自我进化 v1：低频进化周期（6h 一次，门禁保护，静默容错）
        try:
            import time as _t
            if _t.time() - getattr(self, "_last_evolve", 0) > 21600:
                self._last_evolve = _t.time()
                if self.llm is not None:
                    from .evolution import EvolutionEngine
                    res = EvolutionEngine(self.db, self.llm).cycle()
                    logger.info("🧬 自我进化周期: {}", res.get("step"))
        except Exception as e:
            logger.debug("🧬 进化周期异常(忽略): {}", e)

        logger.info("💤 Dreaming 完成: 提取{} 事实, wiki {} 页, 矛盾自愈 {}, 网学 {}",
                    extracted, pages, fixed, web_learned)
        try:  # 战役3：事件溯源
            from .observability import EventLog
            EventLog(self.db).emit("dream", "dmn",
                                   {"extracted": extracted, "pages": pages,
                                    "deduped": fixed, "web_learned": web_learned})
        except Exception:
            pass
        return {"extracted": extracted, "pages": pages, "deduped": fixed}

    @staticmethod
    def _dream_prompt(node_row) -> str:
        text = ((node_row["brief"] or "") + "\n"
                + (node_row["source_output"] or ""))[:600]
        return ("从下面的思考中提取值得长期记住的事实。\n"
                "格式严格：每行一条【记】主语|谓语|宾语\n"
                "主语谓语宾语都必须是简短词语，不许带括号、编号、引号。\n"
                "示例：【记】呼吸|节奏|15秒\n"
                "只输出【记】行，最多3条，没有就输出：无\n\n"
                f"思考内容：\n{text}\n\n【记】")

    # ── 子任务 ──────────────────────────────────────
    def _rank_priority(self, node: dict) -> float:
        """优先级排名。

        任务书 v2.1 问题8：小模型逐个标注 high/medium/low。
        优先 0.8B 判断；无模型时规则兜底。
        """
        t = node.get("type", "")
        if t == "user_input":
            return config.USER_INPUT_PRIORITY
        if t == "self_reflection":
            return min(0.3, node.get("priority", 0.3))

        if self.llm is not None:
            try:
                label = self._ask_llm_priority(node)
                mapping = {"high": 0.9, "medium": 0.6, "low": 0.3}
                if label in mapping:
                    return mapping[label]
            except Exception as e:
                logger.debug("0.8B 排名失败({}), 规则兜底", e)
        return node.get("priority", 0.5)

    def _make_hint(self, node: dict) -> str:
        """生成 hint（0.8B 写备注；无模型时规则兜底）。"""
        t = node.get("type", "")
        if self.llm is not None:
            try:
                return self._ask_llm_hint(node)
            except Exception as e:
                logger.debug("0.8B hint 失败({}), 规则兜底", e)
        if t == "user_input":
            return "这是用户输入，先 Zoom Out 看形状，再 Zoom In 拆解。"
        if t == "root":
            return "这是根节点，拆解为 3-5 个子任务。"
        if t == "self_reflection":
            return "自省节点：思考我为什么要改进自己。"
        return ""

    def _link_similar(self, node_id: str, vec: list[float]) -> None:
        """与最近已巡逻节点连线。

        第一层：0.8B 显式分类（读 briefs 两两判断 related/depends_on/conflicts）
        第二层：embedding 余弦（similar/strongly_similar）
        """
        recent = self.db.get_patrolled(limit=20, exclude=node_id)
        if not recent:
            return
        node = self.db.get_node(node_id)
        if node and self.llm is not None:
            try:
                self._ask_llm_links(node, recent)
                return  # 0.8B 显式判断优先，建边后不再用余弦（防噪声）
            except Exception as e:
                logger.debug("0.8B 连线失败({}), 余弦兜底", e)
        self._cosine_links(node_id, vec, recent)

    def _cosine_links(self, node_id: str, vec: list[float],
                      recent: list[dict]) -> None:
        """余弦相似连线（第二层辅助）。"""
        import numpy as np
        if not recent:
            return
        v = np.asarray(vec, dtype=np.float32)
        for other in recent:
            ov = self.db.unpack_embedding(other.get("embedding"))
            if ov is None:
                continue
            cos = float(np.dot(v, ov) / (np.linalg.norm(v) * np.linalg.norm(ov) + 1e-9))
            if cos >= config.STRONG_SIMILAR_THRESHOLD:
                self.db.add_edge(node_id, other["id"], "strongly_similar", weight=cos)
            elif cos >= config.SIMILAR_THRESHOLD:
                self.db.add_edge(node_id, other["id"], "similar", weight=cos)

    # ── 0.8B 显式判断（任务书 v2.1：小模型是 DMN 主脑）──
    def _ask_llm_priority(self, node: dict) -> str:
        """0.8B 判断节点优先级：high/medium/low。"""
        self._llm_calls += 1
        brief = node.get("brief", "")[:100]
        typ = node.get("type", "")
        prompt = (
            f"{_IDENTITY_DMN}\n"
            f"节点类型: {typ}\n节点brief: {brief}\n"
            "判断这个节点对Agent的价值优先级，只输出一个词：high 或 medium 或 low。\n"
            "规则：用户输入和核心任务=high；有价值的洞察=medium；琐碎/重复/已完成=low。"
        )
        text, _ = self.llm.generate(prompt, max_tokens=8)
        text = text.strip().lower()
        for label in ("high", "medium", "low"):
            if label in text:
                return label
        return "medium"

    def _ask_llm_hint(self, node: dict) -> str:
        """0.8B 给节点写一句 hint（下一念头参考）。"""
        self._llm_calls += 1
        brief = node.get("brief", "")[:100]
        typ = node.get("type", "")
        prompt = (
            "你是Focus Agent的DMN，给下面的节点写一句hint（备注），"
            "供大模型下一次处理时参考。\n"
            f"节点类型: {typ}\n节点brief: {brief}\n"
            "hint要求：一句话，指出关键点或建议方向，30字以内。只输出hint本身。"
        )
        text, _ = self.llm.generate(prompt, max_tokens=60)
        hint = text.strip().split("\n")[0][:60]
        return hint if hint else ""

    def _ask_llm_links(self, node: dict, recent: list[dict]) -> None:
        """0.8B 显式连线：读 briefs 两两判断关系并建边。"""
        self._llm_calls += 1
        brief = node.get("brief", "")[:80]
        # 2026-08-13：排除父子/祖孙关系（已由 parent 边表达，
        # 0.8B 会把"子任务 vs 父任务"误判成 conflicts）
        node_pid = node.get("parent_id") or ""
        recent = [r for r in recent
                  if r["id"] != node_pid and node_pid not in (r.get("parent_id") or "")
                  and r.get("parent_id") != node["id"]][:8]
        if not recent:
            return
        candidates = "\n".join(
            f"{r['id'][:8]}: {r.get('brief', '')[:60]}" for r in recent)
        prompt = (
            "你是Focus Agent的DMN，判断节点A与每个候选B的关系。\n"
            f"节点A: {brief}\n"
            f"候选节点B列表:\n{candidates}\n"
            "对每个候选必须输出一行，格式：<B的8位id> <关系词>\n"
            "关系词只能是：related(相关) / depends_on(A依赖B) / conflicts(矛盾) / none(无关)\n"
            "严格定义：\n"
            "- related：A与B讲同一主题或互补\n"
            "- depends_on：A的结论需要B支持\n"
            "- conflicts：A与B的**结论直接冲突**（一个说A一个说非A），仅仅是话题不同不算conflicts\n"
            "- none：其他情况\n"
            "自省类节点（闲时自省/观察/反思）之间默认none，除非结论明确冲突。\n"
            "逐对认真判断，不要省略任何候选。"
        )
        text, _ = self.llm.generate(prompt, max_tokens=120)
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        # 0.8B 实际输出两种格式（实测）：
        #   A) "6ec2276a related"           （单行 id+关系）
        #   B) "6ec2276a: brief\nrelated=相关" （两行：id行 + 关系行）
        # 解析器两者兼容
        rel_map = {"related": "related", "depends_on": "depends_on",
                   "conflicts": "conflicts", "相关": "related",
                   "依赖": "depends_on", "矛盾": "conflicts"}
        i = 0
        while i < len(lines):
            line = lines[i]
            rid = None
            rel = None
            # 行内含关系词（格式 A）
            parts = line.split()
            for p in parts:
                if p in rel_map:
                    rel = rel_map[p]
                    # 同行找 id
                    for pp in parts:
                        if len(pp) >= 8 and pp not in rel_map:
                            rid = pp
                    break
            if rel is None and "=" in line:
                # 格式 B 的关系行：related=相关
                k, _, v = line.partition("=")
                if k.strip() in rel_map and i > 0:
                    # 上一行是 id
                    prev = lines[i - 1]
                    rid = prev.split()[0].rstrip(":")
                    rel = rel_map[k.strip()]
            if rel and rid:
                rid_clean = rid.rstrip(":")
                target = next((r["id"] for r in recent
                               if r["id"].startswith(rid_clean)
                               or rid_clean.startswith(r["id"][:8])),
                              None)
                if target:
                    self.db.add_edge(node["id"], target, rel)
            i += 1

    def _compress_impressions(self) -> None:
        """同 source_id 全部 done → 压缩为 impression 节点。"""
        for sid in self.db.get_completed_source_ids():
            if self.db.impression_exists(sid):
                continue
            nodes = self.db.get_by_source_id(sid)
            if not nodes:
                continue
            # 用 content(原文) + summary(认知结果) 压缩，brief 只是标题
            parts = []
            for n in nodes:
                if n.get("content") and len(n["content"]) > len(n.get("brief", "")):
                    parts.append(n["content"])
                elif n.get("summary"):
                    parts.append(n["summary"])
            briefs = "；".join(parts) if parts else "；".join(
                n["brief"] for n in nodes if n.get("brief"))
            if self.llm is not None:
                try:
                    summary = self._ask_llm_summary(briefs)
                except Exception as e:
                    logger.debug("0.8B 压缩失败({}), 规则兜底", e)
                    summary = self._summarize(briefs)
            else:
                summary = self._summarize(briefs)
            self.db.add_impression(sid, summary, culture_type="knowledge")
            logger.info("🧬 印象压缩: source={} → impression", sid)

    def _ask_llm_summary(self, briefs: str) -> str:
        """0.8B 把多个 briefs 压缩成 3-5 句印象（任务书：DMN 压缩经历）。"""
        self._llm_calls += 1
        prompt = (
            "你是Focus Agent的DMN，把下面同一来源的多个节点brief压缩成一条印象。\n"
            f"内容:\n{briefs[:800]}\n"
            "要求：3-5句话，保留核心语义，适合长期记忆。只输出印象本身。"
        )
        text, _ = self.llm.generate(prompt, max_tokens=200)
        return text.strip()[:400] or briefs[:200]

    @staticmethod
    def _summarize(text: str, max_words: int = 150) -> str:
        """压缩：取关键句（规则化，不调模型）。"""
        if not text:
            return ""
        sentences = [s for s in text.replace("。", "。\n").split("\n")
                     if s.strip()]
        picked = []
        total = 0
        for s in sentences:
            if total + len(s) > max_words * 1.5:
                break
            picked.append(s.strip())
            total += len(s)
        if not picked and text:
            picked = [text[:200]]
        return "。".join(picked)[: max_words * 2]

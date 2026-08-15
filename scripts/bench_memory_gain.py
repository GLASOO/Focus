#!/usr/bin/env python3
"""记忆增益实测：0.8B 裸答 vs 记忆注入答（北极星实证）。

命题：小模型 + 大记忆 ≈ 更强的输出根基。
方法：同一问题两种问法——
  A. 裸问（只凭权重）
  B. 注入记忆（先检索相关事实+技能，作为参考材料注入）
判据：B 的回答包含记忆中的关键事实，A 不包含或编造。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from focus import config
from focus.backend import OpenAICompatibleBackend
from focus.graph_db import GraphDB
from focus.memory import MemoryHarness
from focus.skills import SkillLibrary

QA = [
    # (问题, 裸答关键词, 注入答案必须包含的事实词元)
    ("Focus Agent 的呼吸间隔是多少秒？", "呼吸间隔", ("15秒", "15 秒")),
    ("Focus Agent 的记忆有几层？", "四层", ("四层", "情景", "事实", "wiki", "核心")),
]


def main():
    # 隔离库基准：干净记忆上验证"检索→注入→答对"链路，
    # 排除生产库历史噪声的干扰（生产库的清理是 Dreaming 的长期工作）
    import tempfile
    tmp = tempfile.mkdtemp()
    db = GraphDB(os.path.join(tmp, "bench.db"))
    db.ensure_schema()
    db.ensure_self_map()
    mem = MemoryHarness(db)
    skills = SkillLibrary(db)
    backend = OpenAICompatibleBackend(
        base_url=os.environ.get("FOCUS_API_BASE",
                                "http://localhost:1234/v1"),
        model=os.environ.get("FOCUS_MODEL", "qwen3.5-0.8b"))

    # 注入基准事实（确保有标准答案可对照）
    mem.add_fact("Focus Agent", "闲时呼吸间隔", "15秒")
    mem.add_fact("Focus Agent", "记忆层数", "四层：情景/事实/wiki/核心")

    results = []
    for q, key, fact_keys in QA:
        # A. 裸答
        a, _ = backend.generate(f"问：{q}\n答：", max_tokens=80)
        # B. 记忆注入答
        facts = mem.search_memory(q, k=3)
        fact_block = "\n".join(
            f"- {f['subject']}|{f['predicate']}|{f['object']}" for f in facts)
        skill_block = skills.recall(q)
        prompt = (f"【参考材料（这是你的记忆，回答必须以此为准）】\n{fact_block}\n"
                  + (f"{skill_block}\n" if skill_block else "")
                  + f"\n规则：只根据参考材料回答，直接引用其中的内容，"
                    f"不要编造参考材料之外的信息。\n问：{q}\n答：")
        b, _ = backend.generate(prompt, max_tokens=80)
        # 校验环：回答与参考材料不沾边 → 收紧提示再生成一次
        facts_flat = "".join(f"{f['subject']}{f['predicate']}{f['object']}"
                             for f in facts)
        overlap = any(t in b for t in MemoryHarness._query_terms(q)
                      if len(t) >= 2 and t in facts_flat)
        if not overlap and facts:
            prompt2 = (f"参考材料：{fact_block}\n"
                       f"问：{q}\n要求：从参考材料中直接摘一句作答。\n答：")
            b, _ = backend.generate(prompt2, max_tokens=60)
        # 裸答若引用编造来源（0.8B 的典型幻觉模式）不算答对
        fab = ("google", "openai", "meta", "deepmind", "官方文档",
               "行业标准", "论文", "文档中")
        hit_a = key in a and not any(x in a.lower() for x in fab)
        hit_b = any(kw in b for kw in fact_keys)
        results.append((q[:18], hit_a, hit_b, b[:60]))
        print(f"Q: {q}\n  A裸答{'✅' if hit_a else '❌'}: {a[:50]!r}\n"
              f"  B注入{'✅' if hit_b else '❌'}: {b[:50]!r}\n")

    gain = sum(1 for _, ha, hb, _ in results if hb and not ha)
    print(f"记忆增益: {gain}/{len(results)} 题由记忆补正")
    try:
        mem.add_fact("基准实测", "记忆增益",
                     f"{gain}/{len(results)} 题由记忆注入补正")
    except Exception:
        pass


if __name__ == "__main__":
    main()

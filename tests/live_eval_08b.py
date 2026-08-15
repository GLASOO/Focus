#!/usr/bin/env python3
"""Focus Agent · 0.8B 实机评测（发布门禁）。

验证问题：我们是否真的造出了能 harness 0.8B 的 Agent？
  A. 工具调用：让模型用 <tool=ls> 看目录，结果必须真实回写
  B. 记忆指令：让模型输出【记】，事实必须落库且可召回
  C. 长程任务：Zoom Out 拆解 → 子任务逐个执行 → 产物落盘（/tmp/focus_poem.txt）

用法：
  python tests/live_eval_08b.py            # 需要 LM Studio 0.8B 在 localhost:1234
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from focus.backend import OpenAICompatibleBackend
from focus.brain import Brain
from focus.graph_db import GraphDB

DB = "/tmp/focus_live_eval.db"
POEM = "/tmp/focus_poem.txt"
RESULTS = []


def report(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok))
    print(f"{'✅ PASS' if ok else '❌ FAIL'} | {name} | {detail}", flush=True)


def main() -> None:
    for f in (DB, POEM):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    db = GraphDB(DB)
    db.ensure_schema()
    db.ensure_self_map()
    db.ensure_libido_seed()
    backend = OpenAICompatibleBackend(
        base_url=os.environ.get("FOCUS_API_BASE", "http://localhost:1234/v1"),
        model=os.environ.get("FOCUS_MODEL", "qwen3.5-0.8b"))
    brain = Brain(db, backend)
    brain.birth()

    # ── A. 工具调用 ────────────────────────────────
    print("\n=== A. 工具调用任务 ===", flush=True)
    nid = db.add_node(type="user_input", priority=1.0,
                      brief="用工具看看 ~/focus-agent 目录里有什么，然后告诉我",
                      content="用工具看看 ~/focus-agent 目录里有什么，然后告诉我")
    t0 = time.time()
    brain.breathe_once(nid)
    node = db.get_node(nid)
    out = node.get("source_output") or ""
    tool_ok = "[工具执行结果]" in out
    real_ok = any(k in out for k in ("focus", "tests", "data", "README"))
    report("A1 工具被执行且结果回写", tool_ok,
           f"{time.time()-t0:.1f}s, len={len(out)}")
    report("A2 结果含真实目录内容", real_ok, out[-200:].replace("\n", " "))

    # ── B. 记忆指令 ────────────────────────────────
    print("\n=== B. 记忆指令任务 ===", flush=True)
    nid = db.add_node(type="user_input", priority=1.0,
                      brief="请记住这个事实并回答我：Focus Agent 的呼吸间隔是15秒。"
                            "回答后请单独一行输出：【记】Focus Agent|呼吸间隔|15秒",
                      content="请记住这个事实并回答我：Focus Agent 的呼吸间隔是15秒。"
                              "回答后请单独一行输出：【记】Focus Agent|呼吸间隔|15秒")
    brain.breathe_once(nid)
    facts = db.conn.execute(
        "SELECT subject, object FROM facts WHERE invalid_at IS NULL").fetchall()
    hit = any("呼吸间隔" in (f["subject"] + f["object"]) or
              "15秒" in f["object"] or "15 秒" in f["object"]
              for f in facts)
    report("B1 事实经【记】指令落库", hit, f"活事实 {len(facts)} 条")
    if hit:
        mem_hits = brain.memory.search_memory("呼吸间隔")
        report("B2 落库事实可被召回", len(mem_hits) > 0,
               str([f["object"] for f in mem_hits][:2]))

    # ── C. 长程任务（Zoom Out → 子任务 → 产物） ─────
    print("\n=== C. 长程任务 ===", flush=True)
    long_task = ("多步任务：第一步，先想好一首关于呼吸的四行短诗；"
                 "第二步，用工具把这首诗写入文件 /tmp/focus_poem.txt；"
                 "第三步，用工具读回该文件验证写入成功，并报告结果")
    nid = db.add_node(type="user_input", priority=1.0,
                      brief=long_task, content=long_task)
    steps = 0
    for i in range(12):
        r = brain.breathe_once()
        steps += 1
        if r is None:
            break
    poem_exists = os.path.exists(POEM)
    poem = open(POEM, encoding="utf-8", errors="replace").read()[:200] if poem_exists else ""
    children = db.conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE parent_id=?", (nid,)).fetchone()["c"]
    done_children = db.conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE parent_id=? AND status='done'",
        (nid,)).fetchone()["c"]
    report("C1 Zoom Out 完成拆解", children >= 2, f"子任务 {children} 个")
    report("C2 子任务被逐个执行", done_children >= 1,
           f"done {done_children}/{children}, 共呼吸 {steps} 次")
    report("C3 最终产物落盘", poem_exists and len(poem.strip()) > 0,
           poem.replace("\n", " / ")[:120])

    # ── 汇总 ──────────────────────────────────────
    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n{'='*50}\n总计: {passed}/{len(RESULTS)} 通过", flush=True)
    hard_fail = [n for n, ok in RESULTS if not ok and n[0] in "AC"]
    if hard_fail:
        print(f"⛔ 关键项未过: {hard_fail} —— 不得发布")
    else:
        print("🚀 核心链路可用 —— 达到发布门禁")


if __name__ == "__main__":
    main()

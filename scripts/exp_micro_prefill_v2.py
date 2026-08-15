#!/usr/bin/env python3
"""微 prefill 三档实验 v2（修正版）：完整输出对比。

大帝令：让模型多思考，max_tokens 给足，禁止截断误判模型行为。
- 单 DB：同一任务 3 个 self_reflection 节点
- 顺序跑 A/B/C，每次前改 config.MICRO_PREFILL_TOKENS
- MAX_THOUGHT_TOKENS 保持生产值 6000（不截断）
- 指标：status/完整输出/summary 提取/位置感/重复率/收束时间

用法：EXP_BACKEND=mlx python3 scripts/exp_micro_prefill_v2.py
"""
import sys, os, time, json, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FOCUS_LOG", "WARNING")

import focus.config as config
from focus.brain import Brain
from focus.graph_db import GraphDB
from focus.backend import create_backend

TIERS = {"A": 150, "B": 300, "C": 600}
TASK = "解释微 prefill 三层坐标系的作用，说明它如何帮模型定位'我在哪'"

def analyze(out: str, node_brief: str) -> dict:
    pos_refs = re.findall(r"(三层坐标|呼吸循环|祖先|路径|父|兄弟|Graph|当前节点)", out)
    grams = [out[i:i+16] for i in range(0, max(0, len(out)-16), 16)]
    rep = 1 - len(set(grams)) / len(grams) if len(grams) > 5 else 0.0
    has_done = "[DONE]" in out
    return {
        "pos_refs": pos_refs[:6],
        "repeat_ratio": round(rep, 3),
        "has_done": has_done,
        "len_chars": len(out),
    }

def main():
    db_path = "/tmp/exp_prefill_v2.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    db = GraphDB(db_path)
    backend_name = os.environ.get("EXP_BACKEND", "dummy")
    backend = (create_backend(backend_name, model_path=config.ORNITH_9B)
               if backend_name == "mlx" else create_backend(backend_name))
    brain = Brain(db, backend=backend)

    # root + 3 个同任务子节点
    root_id = db.add_node(type="user_input", brief="研究微 prefill 三层坐标系",
                          content=TASK, priority=1.0, role="user")
    node_ids = []
    for i, tier in enumerate(["A", "B", "C"]):
        nid = db.add_node(type="self_reflection",
                          brief=f"[实验档位{tier}] {TASK}",
                          content=TASK,
                          parent_id=root_id, priority=0.3, role="self")
        node_ids.append(nid)

    results = {}
    for tier, nid in zip(["A", "B", "C"], node_ids):
        config.MICRO_PREFILL_TOKENS = TIERS[tier]
        t0 = time.time()
        brain.breathe_once(nid)
        dt = time.time() - t0
        row = db.conn.execute(
            "SELECT status, source_output, summary, next_focus, hint"
            " FROM nodes WHERE id=?", (nid,)).fetchone()
        out = (row["source_output"] if row else "") or ""
        results[tier] = {
            "budget": TIERS[tier],
            "status": row["status"] if row else "?",
            "seconds": round(dt, 1),
            "tokens_used": len(out) // 4,
            "has_summary": bool(row["summary"]) if row else False,
            "summary": (row["summary"] if row else "")[:80],
            "has_next_focus": bool(row["next_focus"]) if row else False,
            **analyze(out, TASK),
            "output_head": out[:400],
            "output_tail": out[-200:],
        }
        print(f"\n=== {tier} (预算 {TIERS[tier]}) {dt:.0f}s ===")
        print(json.dumps(results[tier], ensure_ascii=False, indent=1))
        sys.stdout.flush()

    print("\n\n===== 三档汇总 =====")
    for tier in ["A", "B", "C"]:
        r = results[tier]
        print(f"{tier}({r['budget']}): status={r['status']} "
              f"tokens={r['tokens_used']} {r['seconds']}s "
              f"summary={'Y' if r['has_summary'] else 'N'} "
              f"done={'Y' if r['has_done'] else 'N'} "
              f"repeat={r['repeat_ratio']} pos={len(r['pos_refs'])}")
    with open("/tmp/exp_prefill_v2_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("\n结果已存 /tmp/exp_prefill_v2_results.json")

if __name__ == "__main__":
    main()

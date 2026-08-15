#!/usr/bin/env python3
"""微 prefill 三档实验（架构审查问题6：A=150/B=300/C=600）。

方法：同一任务子节点分别用三档微 prefill 预算跑 9B+KV，
限制输出长度（MAX_TOKENS=250）加速，对比：
  1. 收束质量（summary 提取/是否 [DONE]）
  2. 位置感（输出是否引用路径/祖先）
  3. 崩坏风险（ngram 重复分）

用法：EXP_BACKEND=mlx python3 scripts/exp_micro_prefill.py [A|B|C]
"""
import sys, os, time, json, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FOCUS_LOG", "WARNING")

import focus.config as config
from focus.brain import Brain
from focus.graph_db import GraphDB
from focus.backend import create_backend

TIERS = {"A": 150, "B": 300, "C": 600}
MAX_TOKENS = int(os.environ.get("EXP_MAX_TOKENS", "250"))

def run_tier(tier: str) -> dict:
    config.MICRO_PREFILL_TOKENS = TIERS[tier]
    # 限制输出长度（brain 读 config.MAX_THOUGHT_TOKENS）
    config.MAX_THOUGHT_TOKENS = MAX_TOKENS
    db_path = f"/tmp/exp_prefill_{tier}.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    db = GraphDB(db_path)
    backend_name = os.environ.get("EXP_BACKEND", "dummy")
    brain = Brain(db, backend=create_backend(
        backend_name, model_path=config.ORNITH_9B) if backend_name == "mlx"
        else create_backend(backend_name))

    # 造 self_reflection 节点（走 build_micro_prefill 分支，三档实验对象）
    root_id = db.add_node(type="self_reflection",
                          brief="分析 Focus Agent 的呼吸循环机制",
                          content="分析 Focus Agent 的呼吸循环机制，包括微 prefill、生成、落盘、崩坏检测。",
                          priority=0.3, role="self")
    kid = db.add_node(type="self_reflection",
                      brief="解释微 prefill 三层坐标系的作用",
                      content="解释微 prefill 三层坐标系的作用，说明它如何帮模型定位'我在哪'。",
                      parent_id=root_id, priority=0.3, role="self")

    # 呼吸（限制输出长度）
    t0 = time.time()
    brain.breathe_once(kid)
    dt = time.time() - t0
    row = db.conn.execute(
        "SELECT status, source_output, summary, next_focus, hint FROM nodes WHERE id=?",
        (kid,)).fetchone()
    out = (row["source_output"] if row else "") or ""
    # 位置感检测：输出是否引用路径/祖先/兄弟
    pos_refs = re.findall(r"(三层坐标|呼吸循环|祖先|路径|父|兄弟|Graph)", out)
    # 重复率粗估：连续相同 4-gram
    rep = 0.0
    grams = [out[i:i+16] for i in range(0, max(0, len(out)-16), 16)]
    if len(grams) > 5:
        rep = 1 - len(set(grams)) / len(grams)
    return {
        "tier": tier, "budget": TIERS[tier],
        "status": row["status"] if row else "?",
        "tokens": len(out) // 4, "seconds": round(dt, 1),
        "has_summary": bool(row["summary"]) if row else False,
        "summary": (row["summary"] if row else "")[:60],
        "has_next_focus": bool(row["next_focus"]) if row else False,
        "position_refs": pos_refs[:5], "repeat_ratio": round(rep, 3),
        "output": out[:300],
    }

if __name__ == "__main__":
    tier = sys.argv[1] if len(sys.argv) > 1 else "B"
    print(f"=== 微 prefill 档位 {tier} (预算 {TIERS[tier]} token, 输出上限 {MAX_TOKENS}) ===")
    r = run_tier(tier)
    print(json.dumps(r, ensure_ascii=False, indent=1))

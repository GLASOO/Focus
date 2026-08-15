#!/usr/bin/env python3
"""存量记忆固化冲刺（下一战役 #1）。

把历史 episode 用 0.8B 模板提取批量固化入 facts（--dummy 可无模型演练）。
与常驻 DMN Dreaming 共享 memory_consolidated 标记，天然不重复。

用法：
  python -m focus.consolidate_backlog            # 生产（LM Studio 0.8B）
  python -m focus.consolidate_backlog --dummy    # 演练
  python -m focus.consolidate_backlog --limit 50 # 限量
"""
from __future__ import annotations

import argparse
import os
import time

from . import config
from .backend import DummyBackend, OpenAICompatibleBackend
from .dmn import DMN
from .graph_db import GraphDB
from .memory import MemoryHarness


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=600)
    ap.add_argument("--dummy", action="store_true")
    args = ap.parse_args()

    db = GraphDB(config.DB_PATH)
    db.ensure_schema()
    db.ensure_self_map()
    mem = MemoryHarness(db)
    if args.dummy:
        backend = DummyBackend(responses=["【记】演练|状态|成功"])
    else:
        backend = OpenAICompatibleBackend(
            base_url=os.environ.get("FOCUS_API_BASE",
                                    "http://localhost:1234/v1"),
            model=os.environ.get("FOCUS_MODEL", "qwen3.5-0.8b"))
    try:
        db.conn.execute("ALTER TABLE nodes ADD COLUMN memory_consolidated "
                        "INTEGER DEFAULT 0")
        db.conn.commit()
    except Exception:
        pass

    done = 0
    while done < args.limit:
        rows = db.conn.execute(
            "SELECT id, brief, source_output FROM nodes WHERE status='done' "
            "AND COALESCE(memory_consolidated,0)=0 "
            "AND LENGTH(COALESCE(source_output,'')) > 20 "
            "ORDER BY rowid LIMIT 20").fetchall()
        if not rows:
            break
        for r in rows:
            try:
                out, _ = backend.generate(DMN._dream_prompt(r), max_tokens=160)
                mem.observe(r["id"], out)
            except Exception as e:
                print(f"! {r['id'][:8]}: {e}")
            db.conn.execute(
                "UPDATE nodes SET memory_consolidated=1 WHERE id=?", (r["id"],))
            db.conn.commit()
            done += 1
            if done % 20 == 0:
                print(f"进度 {done}", flush=True)
            time.sleep(0.15)  # 给呼吸循环留算力
        if args.dummy:
            break  # 演练只跑一批
    mem.compile_wiki()
    mem.compact_core()
    print(f"✅ 固化完成: {done} episodes")


if __name__ == "__main__":
    main()

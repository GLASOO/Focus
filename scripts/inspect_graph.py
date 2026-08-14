#!/usr/bin/env python3
"""Focus Agent — Graph 检查工具（实施手册 §10.2）

用法：
  python scripts/inspect_graph.py [db_path]
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from focus.graph_db import GraphDB


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/focus_agent.db"
    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}")
        sys.exit(1)

    db = GraphDB(db_path)
    s = db.stats()

    print("=== 节点统计 ===")
    print(f"  总计: {s['total']}  边: {s['edges']}  原文: {s['originals']}  念头: {s['thoughts']}")
    for t, c in sorted(s["by_type"].items()):
        print(f"  type={t:16s} {c}")
    for st, c in sorted(s["by_status"].items()):
        print(f"  status={st:12s} {c}")

    print("\n=== 待处理节点（按 priority） ===")
    rows = db.conn.execute(
        "SELECT id, type, brief, priority, visit_count FROM nodes "
        "WHERE status='pending' ORDER BY priority DESC, created_at ASC LIMIT 10"
    ).fetchall()
    for r in rows:
        print(f"  [{r['priority']:.2f}] v{r['visit_count']} {r['type'][:12]:12s} "
              f"{r['id'][:8]}... {r['brief'][:50]}")

    print("\n=== 最近念头 ===")
    for r in db.conn.execute(
        "SELECT node_id, status, tokens_used, duration_ms, created_at "
        "FROM thought_log ORDER BY id DESC LIMIT 5"
    ).fetchall():
        print(f"  {r['created_at']} node={r['node_id'][:8]}... "
              f"{r['status']} {r['tokens_used']}tok {r['duration_ms']}ms")

    print("\n=== Self-Map ===")
    sm = db.get_self_map()
    print(f"  identity: {sm['identity'][:80]}...")
    print(f"  libido: {sm['libido_state']} (focus x{sm['libido_focus_count']})")
    print(f"  copy: {sm['copy_id']}  species: {sm['species_id']}")
    print(f"  focus: {sm['current_focus'][:60]}")
    print(f"  experiences: {sm['experiences'][:100]}")

    db.close()


if __name__ == "__main__":
    main()

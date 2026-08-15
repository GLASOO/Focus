"""下一战役验收：向量路 / 事件溯源 / 存量固化脚本 / 打包清单。"""
import os
import subprocess
import sys

import pytest

from focus.graph_db import GraphDB
from focus.memory import MemoryHarness
from focus.observability import EventLog


class FakeEmbedder:
    """词袋哈希嵌入（与生产 nomic 同形状：64维归一化）。"""

    def load(self):
        pass

    def embed(self, texts):
        import numpy as np
        out = []
        for t in texts:
            v = np.zeros(64, dtype=np.float32)
            for ch in t:
                v[ord(ch) % 64] += 1.0
            n = float(np.linalg.norm(v))
            out.append((v / n).tolist() if n > 0 else v.tolist())
        return out


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "camp.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return d


@pytest.fixture
def mem(db):
    m = MemoryHarness(db)
    m.set_embedder(FakeEmbedder())
    return m


def test_vector_search_hits(mem):
    """战役2：向量路独立召回（查询词与事实共享字符）。"""
    mem.add_fact("白泽", "身份", "硅基神识的守护者")
    mem.ensure_fact_embeddings(10)
    hits = mem._vector_search("守护者")
    assert any(f["subject"] == "白泽" for f in hits), "向量路未召回"


def test_search_three_routes_union(mem):
    """战役2：三路融合不互相干扰。"""
    mem.add_fact("呼吸", "节奏", "十五秒一次")
    mem.ensure_fact_embeddings(10)
    assert mem.search_memory("呼吸")


def test_eventlog_emit_replay(db):
    """战役3：事件落库 + Trajectory 回放。"""
    ev = EventLog(db)
    ev.emit("tool", "ls", {"arg": "/tmp", "result": "ok"})
    ev.emit("memory", "abc12345", {"记": 1})
    assert len(ev.recent(10)) == 2
    assert len(ev.recent(10, kind="tool")) == 1
    assert ev.trajectory("abc12345")
    ev.emit("error", "x", {"e": "never raises"})  # 不许抛


def test_memory_observe_emits_event(mem, db):
    mem.observe("deadbeef0001", "【记】测试|事件|落库")
    ev = EventLog(db)
    evts = ev.recent(5, kind="memory")
    assert evts and "deadbeef" in evts[0]["actor"]


def test_consolidate_backlog_dummy(db, tmp_path):
    """战役1：固化脚本 dummy 演练（真跑一次，端到端）。"""
    nid = db.add_node(type="work", brief="演练节点", content="x" * 30)
    db.land_thought(nid, output="这是一段足够长的历史思考输出，用来演练存量固化流程。",
                    status="done", summary="", tokens_used=0, duration_ms=0)
    db.close()
    env = dict(os.environ, FOCUS_DB=db.db_path,
               PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    r = subprocess.run(
        [sys.executable, "-m", "focus.consolidate_backlog", "--dummy"],
        capture_output=True, text=True, env=env, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "固化完成" in r.stdout, r.stdout + r.stderr
    c = GraphDB(db.db_path)
    flag = c.conn.execute("SELECT memory_consolidated FROM nodes WHERE id=?",
                          (nid,)).fetchone()[0]
    assert flag == 1
    assert c.conn.execute("SELECT COUNT(*) c FROM facts").fetchone()["c"] >= 1


def test_packaging_files_exist():
    """战役4：打包清单就位。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.exists(os.path.join(root, "pyproject.toml"))
    assert os.path.exists(os.path.join(root, "packaging/README-DISTRIBUTION.md"))
    assert os.path.exists(os.path.join(root, "packaging/DSH-PLUGIN.md"))

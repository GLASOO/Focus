"""记忆基质测试：向量矩阵索引（十万级野心的地基）。"""
import time

import numpy as np
import pytest

from focus.graph_db import GraphDB
from focus.memory import MemoryHarness
from focus.memory_index import VectorIndex


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "mx.db"))
    d.ensure_schema()
    d.ensure_self_map()
    MemoryHarness(d)  # facts/fts/wiki 表由记忆层建立
    return d


def _mkvec(seed, dim=64):
    rng = np.random.default_rng(seed)
    v = rng.random(dim).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


def _add(db, s, p, o, vec):
    fid = MemoryHarness(db).add_fact(s, p, o)
    db.conn.execute("UPDATE facts SET embedding=? WHERE id=?",
                    (vec.tobytes(), fid))
    db.conn.commit()
    return fid


def test_index_build_and_search(db):
    ids = {}
    for i in range(5):
        ids[i] = _add(db, f"主{i}", "谓", "宾", _mkvec(i))
    idx = VectorIndex(db)
    hits = idx.search(_mkvec(2), k=3, threshold=0.0)
    assert hits and hits[0][0] == ids[2]  # 自己与自己最相似


def test_index_invalidates_on_change(db):
    _add(db, "甲", "是", "乙", _mkvec(1))
    idx = VectorIndex(db)
    assert idx.size == 1
    assert idx.ensure() is False  # 无变化 → 不重建
    _add(db, "丙", "是", "丁", _mkvec(2))
    assert idx.ensure() is True   # 指纹失效 → 重建
    assert idx.size == 2


def test_index_excludes_invalidated(db):
    fid = _add(db, "活", "的", "事实", _mkvec(1))
    db.conn.execute("UPDATE facts SET invalid_at=datetime('now') WHERE id=?",
                    (fid,))
    db.conn.commit()
    idx = VectorIndex(db)
    assert idx.size == 0


def test_scale_10k(db):
    """一万条事实：建索引与检索都要快（基质扩容的实证）。"""
    rows = [(f"id{i}", f"主{i%100}", "谓", "宾", _mkvec(i % 512).tobytes())
            for i in range(10000)]
    db.conn.executemany(
        "INSERT INTO facts(id, subject, predicate, object, embedding) "
        "VALUES (?,?,?,?,?)", rows)
    db.conn.commit()
    idx = VectorIndex(db)
    t0 = time.time()
    idx.ensure()
    build_ms = (time.time() - t0) * 1000
    t0 = time.time()
    hits = idx.search(_mkvec(7), k=5, threshold=0.0)
    query_ms = (time.time() - t0) * 1000
    assert idx.size == 10000 and hits
    assert query_ms < 200, f"检索 {query_ms:.0f}ms 太慢"
    print(f"10k 事实: 建索引 {build_ms:.0f}ms, 检索 {query_ms:.1f}ms")

"""记忆系统 v2 · M1 测试（facts 双时间轴 / 指令协议 / 混合检索 / 组装预算）。"""
import pytest

from focus.graph_db import GraphDB
from focus.memory import (MemoryHarness, parse_directives, CORE_MAX)


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "mem.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return d


@pytest.fixture
def mem(db):
    return MemoryHarness(db)


def test_parse_directives():
    text = ("思考过程...\n"
            "【记】呼吸|意义|维持节点活性\n"
            "【记】用户|偏好|中文回复\n"
            "【忘】呼吸|意义\n"
            "【忆】里比多种子\n"
            "无关行 | 不是指令")
    records, forgets, recalls = parse_directives(text)
    assert records == [("呼吸", "意义", "维持节点活性"), ("用户", "偏好", "中文回复")]
    assert forgets == ["呼吸|意义"]
    assert recalls == ["里比多种子"]


def test_parse_directives_malformed_silent(mem):
    """坏指令静默丢弃，绝不抛异常（指令是增量不是关键路径）。"""
    records, forgets, recalls = parse_directives("【记】缺分隔符的一行")
    assert records == [] and forgets == [] and recalls == []
    mem.observe("node-x", "【记】只有两段|没有宾语")  # 不抛异常


def test_add_fact_conflict_invalidates(mem):
    """同(主,谓)新事实 → 旧事实失效而非覆盖（Zep 双时间轴）。"""
    fid1 = mem.add_fact("呼吸", "意义", "维持节点活性")
    fid2 = mem.add_fact("呼吸", "意义", "为扩散做准备")
    assert fid1 != fid2
    active = mem.db.conn.execute(
        "SELECT * FROM facts WHERE subject='呼吸' AND invalid_at IS NULL"
    ).fetchall()
    assert len(active) == 1
    assert active[0]["object"] == "为扩散做准备"
    # 旧事实仍可查（历史轨迹保留）
    old = mem.db.conn.execute(
        "SELECT * FROM facts WHERE id=?", (fid1,)).fetchone()
    assert old["invalid_at"] is not None


def test_add_fact_identical_renews(mem):
    fid1 = mem.add_fact("用户", "语言", "中文")
    fid2 = mem.add_fact("用户", "语言", "中文")
    assert fid1 == fid2
    n = mem.db.conn.execute("SELECT COUNT(*) c FROM facts").fetchone()["c"]
    assert n == 1


def test_search_memory_hit_miss_and_filter(mem):
    mem.add_fact("呼吸", "节奏", "15秒一次闲时呼吸")
    mem.add_fact("DMN", "职责", "巡逻与记忆固化")
    hits = mem.search_memory("呼吸")
    assert any("15秒" in f["object"] for f in hits)
    assert mem.search_memory("不存在的主题xyz") == []
    # 失效事实不得召回
    mem.forget("DMN|职责")
    assert mem.search_memory("DMN") == []


def test_observe_applies_directives(mem):
    out = "结论如下\n【记】Focus Agent|状态|已复活\n【忆】五条基因"
    r = mem.observe("98ed4208723b", out)
    assert len(r["added"]) == 1
    assert r["recalls"] == ["五条基因"]
    assert "五条基因" in mem.recall_queue
    assert mem.search_memory("Focus Agent")


def test_graph_traversal_recall(mem, db):
    """图遍历路：节点邻居产出的事实可被召回。"""
    nid = db.add_node(type="work", brief="测试节点")
    mem.add_fact("测试", "来源", "该节点", source_node=nid)
    hits = mem.search_memory("完全无关的查询词abc", node_id=nid)
    assert any(f["subject"] == "测试" for f in hits)


def test_core_and_assemble_budget(mem, db):
    mem.set_core("我是 Focus Agent。" * 200)  # 超 800 字
    assert len(mem.get_core()) <= CORE_MAX
    mem.add_fact("呼吸的意义", "结论", "维持节点活性")
    ctx = mem.assemble("呼吸的意义", budget=1800)
    assert "【核心记忆】" in ctx
    assert "【相关记忆】" in ctx
    assert len(ctx) <= 1800

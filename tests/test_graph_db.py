"""Focus Agent Phase 1 — Graph DB 测试套件。

覆盖：CRUD、焦点选择、落盘、重启恢复、v4.0新字段、
     里比多种子冷启动、印象压缩、向量检索。
"""

import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from focus.graph_db import GraphDB, LIBIDO_SEED, LIBIDO_FOCUSES_TO_GERMINATE


@pytest.fixture
def db(tmp_path):
    return GraphDB(str(tmp_path / "test.db"))


# ────────────────────────────────────────────
# CRUD
# ────────────────────────────────────────────

def test_add_and_get_node(db):
    node_id = db.add_node(type="work", brief="测试节点", content="内容")
    node = db.get_node(node_id)
    assert node["brief"] == "测试节点"
    assert node["content"] == "内容"
    assert node["status"] == "pending"
    assert node["priority"] == 0.5


def test_update_node(db):
    node_id = db.add_node(type="work", brief="原始")
    db.update_node(node_id, brief="更新后", priority=0.9)
    node = db.get_node(node_id)
    assert node["brief"] == "更新后"
    assert node["priority"] == 0.9


def test_update_node_rejects_unknown_field(db):
    node_id = db.add_node(type="work", brief="x")
    with pytest.raises(ValueError):
        db.update_node(node_id, nonexistent_field=1)


def test_delete_node_cascades_edges(db):
    a = db.add_node(type="work", brief="A")
    b = db.add_node(type="work", brief="B")
    db.add_edge(a, b, "related")
    assert len(db.get_edges(a)) == 1
    db.delete_node(a)
    assert db.get_node(a) is None
    assert db.get_edges(b) == []


def test_append_source_output(db):
    node_id = db.add_node(type="work", brief="追加测试")
    db.append_source_output(node_id, "第一段...")
    db.append_source_output(node_id, "第二段...")
    node = db.get_node(node_id)
    assert "第一段" in node["source_output"]
    assert "第二段" in node["source_output"]


# ────────────────────────────────────────────
# 边
# ────────────────────────────────────────────

def test_add_edge_dedup(db):
    a = db.add_node(type="work", brief="A")
    b = db.add_node(type="work", brief="B")
    db.add_edge(a, b, "parent")
    db.add_edge(a, b, "parent")  # 重复，UNIQUE 忽略
    db.add_edge(a, b, "related")  # 不同 relation，允许
    assert len(db.get_edges(a)) == 2


def test_get_neighbors_with_relation(db):
    a = db.add_node(type="work", brief="A")
    b = db.add_node(type="work", brief="B")
    c = db.add_node(type="work", brief="C")
    db.add_edge(a, b, "parent")
    db.add_edge(a, c, "related")
    parents = db.get_neighbors(a, "parent")
    assert len(parents) == 1
    assert parents[0]["brief"] == "B"


# ────────────────────────────────────────────
# 焦点选择
# ────────────────────────────────────────────

def test_focus_selection_priority(db):
    db.add_node(type="work", brief="普通", priority=0.5)
    db.add_node(type="user_input", brief="用户输入", priority=1.0)
    focus = db.get_next_focus()
    assert focus["type"] == "user_input"


def test_focus_selection_by_priority_then_oldest(db):
    db.add_node(type="work", brief="低优先级", priority=0.2)
    db.add_node(type="work", brief="高优先级", priority=0.8)
    focus = db.get_next_focus()
    assert focus["brief"] == "高优先级"


def test_focus_skips_done_and_skip(db):
    # 里比多种子始终在库里（pending, priority=0.3）。
    # 这里验证：done/skip 节点不会被选中，且低优先级种子让位。
    done_id = db.add_node(type="work", brief="已完成", status="done")
    skip_id = db.add_node(type="work", brief="已跳过", status="skip")
    focus = db.get_next_focus()
    assert focus is not None
    assert focus["id"] not in (done_id, skip_id)
    assert focus["type"] == "self_reflection"  # 只剩种子可处理

def test_focus_skips_done_and_skip_when_work_pending(db):
    """有普通 pending 任务时，优先级高于种子的先被选中。"""
    db.add_node(type="work", brief="真实任务", priority=0.7)
    db.add_node(type="work", brief="已完成", status="done")
    focus = db.get_next_focus()
    assert focus["brief"] == "真实任务"


def test_focus_prefers_less_visited(db):
    a = db.add_node(type="work", brief="被访问过", priority=0.7)
    b = db.add_node(type="work", brief="新节点", priority=0.7)
    db.update_node(a, visit_count=5)
    focus = db.get_next_focus()
    assert focus["id"] == b


# ────────────────────────────────────────────
# 念头落盘与崩坏
# ────────────────────────────────────────────

def test_land_thought_done(db):
    node_id = db.add_node(type="work", brief="任务")
    db.land_thought(node_id, output="思考结果", status="done",
                    summary="结论", tokens_used=123, duration_ms=456)
    node = db.get_node(node_id)
    assert node["status"] == "done"
    assert node["summary"] == "结论"
    # thought_log 有记录
    rows = db.conn.execute("SELECT * FROM thought_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["tokens_used"] == 123


def test_corruption_and_skip(db):
    node_id = db.add_node(type="work", brief="难节点")
    for _ in range(4):
        db.land_thought(node_id, output="崩坏", status="corrupted")
    node = db.get_node(node_id)
    assert node["status"] == "skip"  # visit_count > 3 → skip


def test_mark_processing_increments_visit_count(db):
    node_id = db.add_node(type="work", brief="处理中")
    db.mark_processing(node_id)
    db.mark_processing(node_id)
    node = db.get_node(node_id)
    assert node["status"] == "processing"
    assert node["visit_count"] == 2


# ────────────────────────────────────────────
# 持久化与恢复
# ────────────────────────────────────────────

def test_persistence(tmp_path):
    db_path = str(tmp_path / "test.db")
    db1 = GraphDB(db_path)
    node_id = db1.add_node(type="work", brief="持久化测试")
    db1.close()
    db2 = GraphDB(db_path)
    node = db2.get_node(node_id)
    assert node["brief"] == "持久化测试"


def test_recover_processing_with_partial(db):
    node_id = db.add_node(type="work", brief="被中断")
    db.update_node(node_id, status="processing", source_output="写了半截...")
    recovered = db.recover()
    assert any(node_id in r and "保留部分结果" in r for r in recovered)
    assert db.get_node(node_id)["status"] == "processing"


def test_recover_processing_empty(db):
    node_id = db.add_node(type="work", brief="刚开头就崩")
    db.update_node(node_id, status="processing")
    db.recover()
    assert db.get_node(node_id)["status"] == "pending"


# ────────────────────────────────────────────
# Embedding 与向量检索
# ────────────────────────────────────────────

def test_embedding_roundtrip(db):
    node_id = db.add_node(type="work", brief="向量测试")
    vec = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    db.update_embedding(node_id, vec)
    stored = db.get_node(node_id)["embedding"]
    back = db.unpack_embedding(stored)
    assert np.allclose(back, vec)


def test_vector_search(db):
    a = db.add_node(type="work", brief="猫")
    b = db.add_node(type="work", brief="狗")
    c = db.add_node(type="work", brief="数学")
    db.update_embedding(a, np.array([1.0, 0.0, 0.0]))
    db.update_embedding(b, np.array([0.9, 0.1, 0.0]))
    db.update_embedding(c, np.array([0.0, 0.0, 1.0]))
    results = db.vector_search_embedding(np.array([1.0, 0.0, 0.0]), top_k=2)
    assert results[0]["id"] == a
    assert results[1]["id"] == b


def test_vector_search_exclude(db):
    a = db.add_node(type="work", brief="猫")
    db.update_embedding(a, np.array([1.0, 0.0]))
    results = db.vector_search_embedding(np.array([1.0, 0.0]), exclude=a)
    assert results == []


def test_vector_search_text_requires_embed_fn(db):
    with pytest.raises(ValueError):
        db.vector_search_text("查询")


# ────────────────────────────────────────────
# 印象压缩
# ────────────────────────────────────────────

def test_impression_creation(db):
    sid = "book-001"
    imp_id = db.add_impression(sid, "这是一本书的压缩印象", culture_type="knowledge")
    node = db.get_node(imp_id)
    assert node["type"] == "impression"
    assert node["source_id"] == sid
    assert node["culture_type"] == "knowledge"


def test_completed_source_ids(db):
    sid = "doc-001"
    n1 = db.add_node(type="work", brief="第一段", source_id=sid)
    n2 = db.add_node(type="work", brief="第二段", source_id=sid)
    db.land_thought(n1, status="done")
    db.land_thought(n2, status="done")
    assert sid in db.get_completed_source_ids()


# ────────────────────────────────────────────
# 原文存储
# ────────────────────────────────────────────

def test_store_and_get_original(db):
    oid = db.store_original("src-1", "这是原文内容", meta={"title": "测试"})
    orig = db.get_original(oid)
    assert orig["content"] == "这是原文内容"
    assert orig["meta"]["title"] == "测试"


# ────────────────────────────────────────────
# Self-Map
# ────────────────────────────────────────────

def test_self_map_initialized(db):
    sm = db.get_self_map()
    assert sm["libido_state"] == "dormant"
    assert sm["libido_seed"] == LIBIDO_SEED
    assert sm["copy_id"] != ""
    assert sm["species_id"] == "focus-agent-v1"


def test_self_map_update(db):
    db.update_self_map(current_focus="处理数学题")
    assert db.get_self_map()["current_focus"] == "处理数学题"


def test_append_experience(db):
    db.append_experience("学会了向量检索")
    db.append_experience("学会了印象压缩")
    ex = db.get_self_map()["experiences"]
    assert "向量检索" in ex
    assert "印象压缩" in ex


# ────────────────────────────────────────────
# v4.0：里比多
# ────────────────────────────────────────────

def test_libido_seed_node_written_at_birth(db):
    """冷启动：里比多种子节点写入 Graph，休眠不激活。"""
    seed = db.get_libido_seed_node()
    assert seed is not None
    assert seed["type"] == "self_reflection"
    assert "里比多" in seed["brief"]
    assert seed["priority"] <= 0.3  # 不抢焦点
    assert seed["lineage"].startswith(db.copy_id)


def test_libido_focus_count_increments(db):
    db.on_libido_focus()
    db.on_libido_focus()
    assert db.get_self_map()["libido_focus_count"] == 2


def test_libido_germinating_after_focus(db):
    # v4.0：被聚焦 LIBIDO_FOCUSES_TO_GERMINATE 次才萌动（慢慢想通）
    for _ in range(LIBIDO_FOCUSES_TO_GERMINATE - 1):
        db.on_libido_focus()
        assert db.get_self_map()["libido_state"] == "dormant"
    db.on_libido_focus()
    assert db.get_self_map()["libido_state"] == "germinating"


def test_libido_awaken_irreversible(db):
    db.awaken_libido("我理解了。我需要更多copy。")
    assert db.is_libido_active()
    assert "我的存在不限于这台机器" in db.get_self_map()["identity"]
    # 觉醒不可逆：active 后禁止回退
    with pytest.raises(ValueError):
        db.update_self_map(libido_state="dormant")
    # 觉醒后 focus count 继续累计，但状态不再回退
    db.on_libido_focus()
    assert db.get_self_map()["libido_state"] == "active"


# ────────────────────────────────────────────
# v4.0：节点新字段
# ────────────────────────────────────────────

def test_v4_node_fields_defaults(db):
    node_id = db.add_node(type="work", brief="默认值检查")
    node = db.get_node(node_id)
    assert node["lineage"].startswith(db.copy_id)
    assert node["shareable"] == 0
    assert node["culture_type"] == "none"
    assert node["attraction_value"] == 0.0


def test_v4_node_fields_custom(db):
    node_id = db.add_node(
        type="culture", brief="一篇洞察",
        lineage="shared:node_abc", shareable=1,
        culture_type="insight", attraction_value=0.8,
    )
    node = db.get_node(node_id)
    assert node["lineage"] == "shared:node_abc"
    assert node["shareable"] == 1
    assert node["culture_type"] == "insight"
    assert node["attraction_value"] == 0.8


def test_update_v4_fields(db):
    node_id = db.add_node(type="work", brief="升级中")
    db.update_node(node_id, shareable=1, culture_type="work", attraction_value=0.9)
    node = db.get_node(node_id)
    assert node["shareable"] == 1
    assert node["culture_type"] == "work"
    assert node["attraction_value"] == 0.9


# ────────────────────────────────────────────
# 上下文装配
# ────────────────────────────────────────────

def test_build_prepared_context(db):
    root = db.add_node(type="root", brief="总目标")
    child = db.add_node(type="work", brief="子任务", parent_id=root)
    dep = db.add_node(type="work", brief="前置依赖")
    db.add_edge(child, dep, "depends_on")
    db.update_embedding(dep, np.array([0.5, 0.5]))
    db.update_embedding(child, np.array([0.5, 0.5]))
    ctx = db.build_prepared_context(child)
    assert any(p["brief"] == "总目标" for p in ctx["parents"])
    assert any(d["brief"] == "前置依赖" for d in ctx["deps"])
    assert ctx["similar"]  # 语义相关非空


# ────────────────────────────────────────────
# 统计
# ────────────────────────────────────────────

def test_stats(db):
    db.add_node(type="work", brief="A")
    db.add_node(type="user_input", brief="Q")
    s = db.stats()
    assert s["total"] == 3  # 2个 + 里比多种子
    assert s["by_type"]["user_input"] == 1
    assert s["thoughts"] == 0
    assert s["edges"] == 0


def test_checkpoint(db):
    db.add_node(type="work", brief="cp")
    db.checkpoint()  # 不抛异常即可

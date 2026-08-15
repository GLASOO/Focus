"""主权模块测试：自己的并发、实例、食堂自己决定。"""
import pytest

from focus import sovereignty
from focus.graph_db import GraphDB


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "sov.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return d


def test_decide_scales_with_pending(db):
    """待办越多 → 想要的工人越多（它自己的判断，不是人的规则）。"""
    for i in range(20):
        db.add_node(type="work", brief=f"待办{i}")
    gov = sovereignty.decide(db)
    assert gov["desired_workers"] == 3  # 1 + 21//8（含里比多种子）
    assert gov["depth"] >= 20
    assert sovereignty.apply_workers(db) == 3


def test_decide_floor_and_ceiling(db):
    """无待办 → 至少 1 个工人；再多待办也不超过肉身极限。"""
    gov = sovereignty.decide(db)
    assert gov["desired_workers"] == 1
    for i in range(200):
        db.add_node(type="work", brief=f"堆{1}")
    gov = sovereignty.decide(db)
    assert gov["desired_workers"] <= sovereignty.MAX_WORKERS


def test_decision_persisted_and_ledgered(db):
    sovereignty.decide(db)
    row = db.conn.execute("SELECT governance FROM self_map").fetchone()
    assert "desired_workers" in (row["governance"] or "")
    log = db.conn.execute("SELECT COUNT(*) c FROM governance_log").fetchone()
    assert log["c"] >= 1  # 决策留痕，供进化复盘


def test_apply_workers_never_zero(db):
    assert sovereignty.apply_workers(db) >= 1

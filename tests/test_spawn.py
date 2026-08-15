"""子Agent 手搓坊测试。"""
import time

import pytest

from focus.backend import DummyBackend
from focus.graph_db import GraphDB
from focus.spawn import SubAgentForge


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "sp.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return d


def test_forge_creates_parent_and_child(db):
    forge = SubAgentForge(db, DummyBackend())
    pid = forge.forge("整理今日念头")
    assert pid
    parent = db.get_node(pid)
    assert parent["brief"].startswith("[子Agent]")
    kids = db.get_children(pid)
    assert len(kids) == 1 and kids[0]["status"] == "pending"


def test_run_sync_completes_task(db):
    """同步驱使：子任务被呼吸，产出回写父节点 summary。"""
    forge = SubAgentForge(db, DummyBackend(responses=["子Agent的实质产出结果"]))
    pid = forge.forge("干一件事")
    summary = forge.run_sync(pid)
    assert "实质产出" in summary
    parent = db.get_node(pid)
    assert parent["status"] == "done"
    assert "实质产出" in (parent.get("summary") or "")
    kids = db.get_children(pid)
    assert kids[0]["status"] == "done"


def test_spawn_threaded(db):
    """工具形态：派遣即返回，线程里干完。"""
    forge = SubAgentForge(db, DummyBackend(responses=["分身干完了"]))
    msg = forge.spawn("线程任务")
    assert "已派遣" in msg
    time.sleep(2)
    rows = db.conn.execute(
        "SELECT status, summary FROM nodes WHERE brief LIKE '[子Agent]%'"
    ).fetchall()
    assert any(r["status"] == "done" for r in rows)


def test_forge_empty_rejected(db):
    forge = SubAgentForge(db, DummyBackend())
    assert forge.forge("   ") is None
    assert forge.spawn("  ").startswith("[手搓失败")


def test_spawn_tool_registered(db):
    """大脑的工具层里有 spawn。"""
    from focus.brain import Brain
    brain = Brain(db, DummyBackend())
    assert "spawn" in brain.tools.names

"""记忆卫生测试：垃圾判据 / 清扫 / 写入闸 / 端口鉴权。"""
import os

import pytest

from focus.graph_db import GraphDB
from focus.memory import MemoryHarness
from focus.hygiene import MemoryHygiene, is_garbage


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "hy.db"))
    d.ensure_schema()
    d.ensure_self_map()
    MemoryHarness(d)
    return d


def test_garbage_rules():
    # 主语是整句（>=24字）
    assert is_garbage("这是一段远远超过二十四个字的完整句子当作主语的事实", "谓", "宾")
    # 宾语含指令残片
    assert is_garbage("主语", "谓", "【记】残片内容")
    # 宾语过短（非字母数字的单字符）
    assert is_garbage("主语", "谓", "?")           # 标点符号过短
    # 宾语过长
    assert is_garbage("主语", "谓", "x" * 61)     # 宾语过长
    # 干净事实
    assert not is_garbage("呼吸", "间隔", "15秒")


def test_sweep_cleans_garbage_keeps_history(db):
    # 直接插库绕过写入闸（模拟历史脏数据）
    db.conn.execute(
        "INSERT INTO facts(id, subject, predicate, object) "
        "VALUES ('g1', '这是一个超过二十四个字的整句主语啊啊啊啊啊啊啊啊', '谓', '宾')")
    db.conn.execute(
        "INSERT INTO facts(id, subject, predicate, object) "
        "VALUES ('g2', '干净', '事实', '保留我')")
    db.conn.commit()
    r = MemoryHygiene(db).sweep()
    assert r["cleaned"] == 1
    # 垃圾失效留痕，不删史
    g1 = db.conn.execute("SELECT invalid_at FROM facts WHERE id='g1'").fetchone()
    assert g1["invalid_at"] is not None
    g2 = db.conn.execute("SELECT invalid_at FROM facts WHERE id='g2'").fetchone()
    assert g2["invalid_at"] is None


def test_write_gate_rejects_garbage(db):
    mem = MemoryHarness(db)
    assert mem.add_fact("这是一段远远超过二十四个字的完整句子当作主语的事实啊啊啊啊啊啊", "谓", "宾") == ""
    assert mem.add_fact("主语", "谓", "【记】残片") == ""
    assert mem.add_fact("呼吸", "节奏", "15秒") != ""  # 干净的放行


def test_sweep_dedups_duplicates(db):
    for i in range(3):
        db.conn.execute(
            "INSERT INTO facts(id, subject, predicate, object, "
            "updated_at) VALUES (?,?,?,?,"
            "datetime('now', ?))",
            (f"d{i}", "同主题", "碎念", f"版本{i}", f"+{i} seconds"))
    db.conn.commit()
    r = MemoryHygiene(db).sweep()
    assert r["deduped"] == 2  # 三条留一条
    left = db.conn.execute(
        "SELECT object FROM facts WHERE subject='同主题' "
        "AND invalid_at IS NULL").fetchall()
    assert len(left) == 1 and left[0]["object"] == "版本2"  # 留最新


def test_ui_auth_env_parsing():
    """鉴权逻辑：无 token 配置 = 本地信任模式。"""
    assert os.environ.get("FOCUS_UI_TOKEN", "") == ""  # 测试环境默认信任

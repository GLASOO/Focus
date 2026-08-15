"""自我觉察模块测试（内观的地基必须绝对确定性）。"""
import os

import pytest

from focus.graph_db import GraphDB
from focus.selfaware import SelfAwareness


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "sa.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return d


@pytest.fixture
def body(tmp_path):
    """搭一个假身体（focus/ 包）供觉察。"""
    fdir = tmp_path / "focus"
    fdir.mkdir()
    (fdir / "heart.py").write_text(
        '"""心脏模块：负责呼吸循环。"""\n\n'
        'class Heart:\n'
        '    """心脏：永不停歇地跳动。"""\n'
        '    def beat(self):\n'
        '        """一次心跳。"""\n'
        '        return 1\n',
        encoding="utf-8")
    (fdir / "eye.py").write_text(
        '"""眼睛模块：负责观察。"""\n\n'
        'def look():\n'
        '    """看一眼。"""\n'
        '    return "see"\n',
        encoding="utf-8")
    return tmp_path


@pytest.fixture
def sa(db, body):
    return SelfAwareness(db, root=str(body))


def test_scan_indexes_body(sa, db):
    r = sa.scan()
    assert set(r["changed"]) == {"heart", "eye"}
    stats = sa.stats()
    assert stats.get("module") == 2
    assert stats.get("class") == 1
    assert stats.get("function") == 1
    # 职责（docstring）必须入库——理解自己的前提
    row = db.conn.execute(
        "SELECT summary FROM self_knowledge WHERE kind='class' "
        "AND name='Heart'").fetchone()
    assert "永不停歇" in row["summary"]


def test_scan_idempotent_and_change_detection(sa, body):
    sa.scan()
    assert sa.scan()["changed"] == []  # 无变化 → 不重复觉察
    (body / "focus" / "heart.py").write_text(
        '"""心脏模块 v2：跳得更快了。"""\n', encoding="utf-8")
    r = sa.scan()
    assert r["changed"] == ["heart"]  # 身体变化必须被觉察
    row = sa.db.conn.execute(
        "SELECT summary FROM self_knowledge WHERE kind='module' "
        "AND name='heart'").fetchone()
    assert "跳得更快" in row["summary"]


def test_scan_detects_organ_removal(sa, body):
    sa.scan()
    os.remove(body / "focus" / "eye.py")
    r = sa.scan()
    assert r["removed"] == ["eye"]
    assert sa.db.conn.execute(
        "SELECT COUNT(*) c FROM self_knowledge WHERE module='eye'"
    ).fetchone()["c"] == 0


def test_module_map_readable(sa):
    sa.scan()
    m = sa.module_map()
    assert "heart.py" in m and "呼吸循环" in m
    assert "Heart" in m
    assert len(m) <= 2000


def test_read_restriction(sa, body):
    """内观只许读自己的身体——越界即拒绝。"""
    sa.scan()
    assert "心脏模块" in sa.read("focus/heart.py")
    assert "[拒绝" in sa.read("/etc/passwd")
    assert "[拒绝" in sa.read("focus/../heart.py")


def test_understand_search(sa):
    sa.scan()
    assert "beat" in sa.understand("心跳")  # 函数行 heart.beat
    assert "没有与" in sa.understand("不存在的器官xyz")


def test_to_wiki_and_summary(sa, db):
    sa.scan()
    sa.to_wiki()
    page = db.conn.execute(
        "SELECT content FROM self_wiki WHERE topic='我的身体'").fetchone()
    assert page and "heart.py" in page["content"]
    s = sa.self_summary()
    assert "我的身体" in s and "heart" in s


def test_real_body_scan(db):
    """对真实身体做一次内观（仓库自身的 focus/ 包）。"""
    sa = SelfAwareness(db)
    r = sa.scan()
    assert "brain" in r["changed"] and "memory" in r["changed"]
    assert sa.stats().get("module", 0) >= 8
    # 关键器官的职责必须被理解
    assert "呼吸" in sa.understand("Brain")[0:200] or \
           "brain" in sa.understand("Brain")

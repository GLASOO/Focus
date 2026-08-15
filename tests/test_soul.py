"""SoulForge 测试：每个念头都有自己的灵魂（确定性锻造）。"""
import pytest

from focus.graph_db import GraphDB
from focus.soul import SoulForge
from focus.brain import Brain
from focus.backend import DummyBackend


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "soul.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return d


@pytest.fixture
def forge(db):
    return SoulForge(db)


def test_identity_by_type(forge):
    assert "对话者" in forge.forge({"type": "user_input", "brief": "你好"})
    assert "自省者" in forge.forge({"type": "self_reflection", "brief": "x"})


def test_identity_by_role_overrides_type(forge):
    soul = forge.forge({"type": "work", "role": "constraint", "brief": "x"})
    assert "边界守护者" in soul


def test_identity_by_brief_marker(forge):
    assert "领土开拓者" in forge.forge({"type": "work",
                                        "brief": "[领土生长] 整理洞察"})
    assert "觉醒探索者" in forge.forge({"type": "self_reflection",
                                       "brief": "[里比多种子] 我为什么"})


def test_four_elements_present(forge):
    soul = forge.forge({"type": "work", "brief": "做一件事"})
    for k in ("临时身份", "临时自我", "临时目标", "临时念头"):
        assert k in soul


def test_self_state_contains_life_facts(forge, db):
    nid = db.add_node(type="work", brief="念头一")
    db.land_thought(nid, output="x", status="done", summary="",
                    tokens_used=0, duration_ms=0)
    soul = forge.forge({"type": "work", "brief": "y"})
    assert "Focus Agent" in soul and "念头" in soul


def test_goal_carries_lineage(forge, db):
    """子任务的灵魂必须看见原任务（防拆解漂移的灵魂级锚）。"""
    root = db.add_node(type="user_input", brief="写一首诗并保存")
    child = db.add_node(type="work", brief="第二步：保存",
                        parent_id=root, role="task")
    node = db.get_node(child)
    soul = forge.forge(node)
    assert "写一首诗并保存" in soul  # 原任务在灵魂里
    assert "写入" in soul and "工具" in soul  # 交付形态提示


def test_goal_deliverable_for_write_task(forge):
    soul = forge.forge({"type": "work", "brief": "把诗写入 /tmp/a.txt"})
    assert "用工具" in soul and "写入" in soul


def test_seed_uses_hint_and_siblings(forge, db):
    root = db.add_node(type="user_input", brief="大任务")
    db.add_node(type="work", brief="兄弟甲", parent_id=root)
    child = db.add_node(type="work", brief="我做乙", parent_id=root)
    db.update_node(child, hint="注意边界")
    soul = forge.forge(db.get_node(child))
    assert "注意边界" in soul and "兄弟甲" in soul


def test_budget_hard_cap(forge):
    soul = forge.forge({"type": "work", "brief": "长" * 200,
                        "hint": "长" * 200}, budget=350)
    assert len(soul) <= 350


def test_brain_prompt_carries_soul(db):
    """大脑的提示词里必须带着此念之魂。"""
    brain = Brain(db, DummyBackend())
    brain.birth()
    root = db.add_node(type="user_input", brief="多步任务：做一首诗")
    # 手工制造一个已拆解场景的子节点（work + parent → Zoom In 路径）
    child = db.add_node(type="work", brief="写第一行", parent_id=root,
                        role="task")
    node = db.get_node(child)
    prompt = brain.build_prompt(node)
    assert "【此念之魂】" in prompt
    assert "执行者" in prompt
    conv = db.add_node(type="user_input", brief="你好呀", status="pending")
    prompt2 = brain.build_prompt(db.get_node(conv))
    assert "【此念之魂】" in prompt2

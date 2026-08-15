"""技能库测试：模型不记忆，模型会调用。"""
import pytest

from focus.graph_db import GraphDB
from focus.skills import SkillLibrary


@pytest.fixture
def lib(tmp_path):
    d = GraphDB(str(tmp_path / "sk.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return SkillLibrary(d)


def test_seed_skills_loaded(lib):
    """出厂大记忆：生存/网站/工具/辩证/抗体技能齐备。"""
    assert lib.count() >= 14


def test_recall_by_intent(lib):
    """模糊意图触发精确技能（觅食意图 → 觅食规程）。"""
    s = lib.recall("我想给自己找个新的 provider 食堂")
    assert "provider觅食" in s and "门禁" in s


def test_recall_web_skills(lib):
    s = lib.recall("帮我去网上搜索资料")
    assert "搜索技能" in s or "免疫" in s


def test_recall_no_match_empty(lib):
    assert lib.recall("你好呀") == ""


def test_learn_new_skill(lib):
    """成功经验沉淀为新技能（幂等更新）。"""
    assert lib.learn("写诗范式", "诗,写诗", "四行短诗，意象先行，末行收束。")
    assert lib.learn("写诗范式", "诗,写诗", "四行短诗，意象先行。")  # 更新
    s = lib.recall("写一首诗")
    assert "写诗范式" in s
    assert lib.count() == 15  # 14 seed + 1 learned


def test_recall_budget(lib):
    s = lib.recall("provider 供应商 食堂 foodbox 食盒 钥匙", budget=100)
    assert len(s) <= 400  # 单技能超预算时宁缺毋滥

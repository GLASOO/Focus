"""自我进化模块 v1 测试（全确定性，DummyBackend 驱动）。"""
import pytest

from focus import config
from focus.backend import DummyBackend
from focus.evolution import (EvolutionEngine, parse_proposal, validate,
                             PARAM_SPACE)
from focus.graph_db import GraphDB


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "evo.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return d


@pytest.fixture
def eng(db):
    """quick 模式：2 探针，省时间。"""
    return EvolutionEngine(db, DummyBackend(responses=["（探针回答，有实质内容。）"]),
                           quick=True)


def test_parse_proposal_basic():
    props = parse_proposal("思考...\n【调】DREAM_EVERY_SEC|300|梦太频繁\n无关行")
    assert props == [("DREAM_EVERY_SEC", 300.0, "梦太频繁")]


def test_parse_proposal_fullwidth_pipe():
    props = parse_proposal("【调】DREAM_BATCH｜20｜全角竖线也要认")
    assert props and props[0][0] == "DREAM_BATCH" and props[0][1] == 20.0


def test_parse_proposal_space_separator():
    """实测 0.8B：【调】PARAM|0.85 理由（竖线漏写，空格分隔）。"""
    props = parse_proposal("【调】IDLE_INTROSPECT_MAX_RATIO|0.85 场景复杂度高")
    assert props == [("IDLE_INTROSPECT_MAX_RATIO", 0.85, "场景复杂度高")]


def test_parse_proposal_malformed_silent():
    assert parse_proposal("【调】缺少分隔") == []
    assert parse_proposal("【调】A|不是数字|理由") == []


def test_validate_whitelist_and_bounds():
    assert validate("DREAM_EVERY_SEC", 300.0) is None
    assert "不在进化域" in validate("NOT_A_PARAM", 1.0)
    lo, hi, _ = PARAM_SPACE["DREAM_EVERY_SEC"]
    assert "越界" in validate("DREAM_EVERY_SEC", hi + 1)
    assert "越界" in validate("DREAM_EVERY_SEC", lo - 1)


def test_cycle_applies_when_gate_passes(eng, db):
    """提案合法且门禁不回归 → 应用，config 被改写，历史留痕。"""
    eng.backend = DummyBackend(
        responses=["【调】DREAM_EVERY_SEC|300|测试进化"]
        + ["（探针回答，有实质内容。）"] * 10)
    old = float(config.DREAM_EVERY_SEC)
    try:
        r = eng.cycle()
        assert r["step"] == "applied", r
        assert float(config.DREAM_EVERY_SEC) == 300.0
        hist = eng.history()
        assert hist[0]["status"] == "applied"
        # 重放：新引擎启动即恢复 override
        eng2 = EvolutionEngine(db, DummyBackend(), quick=True)
        assert float(config.DREAM_EVERY_SEC) == 300.0
    finally:
        config.DREAM_EVERY_SEC = old


def test_cycle_rejects_out_of_bounds(eng):
    eng.backend = DummyBackend(
        responses=["【调】DREAM_EVERY_SEC|999999|越界提案"])
    r = eng.cycle()
    assert r["step"] == "validate" and "越界" in r["result"]
    assert eng.history()[0]["status"] == "rejected"


def test_cycle_rejects_unknown_param(eng):
    eng.backend = DummyBackend(responses=["【调】EVIL_PARAM|1|注入尝试"])
    r = eng.cycle()
    assert r["step"] == "validate" and "不在进化域" in r["result"]


def test_cycle_rolls_back_on_regression(eng, db):
    """门禁回归 → 回滚 + 记为 regressed（教训供下次 solicitation 引用）。"""
    old = float(config.DREAM_EVERY_SEC)

    class RiggedBackend(DummyBackend):
        def __init__(self):
            super().__init__(responses=[])
            self.calls = 0

        def generate(self, prompt, **kw):
            self.calls += 1
            if self.calls == 1:
                return ("【调】DREAM_EVERY_SEC|300|会变更好", "stop")
            # before 探针全过，after 探针全崩（空洞）
            if self.calls <= 3:
                return ("这是 before 阶段的实质回答。", "stop")
            return ("", "stop")

    eng.backend = RiggedBackend()
    try:
        r = eng.cycle()
        assert r["step"] == "regressed", r
        assert float(config.DREAM_EVERY_SEC) == old, "必须回滚"
        assert eng.history()[0]["status"] == "regressed"
    finally:
        config.DREAM_EVERY_SEC = old


def test_no_valid_proposal(eng):
    eng.backend = DummyBackend(responses=["我没有建议。"])
    r = eng.cycle()
    assert r["result"] == "无有效提案"

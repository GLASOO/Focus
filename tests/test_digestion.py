"""消化系统测试：胃口/分量/餐账/餐桌卫生。"""
import os

import pytest

from focus import digestion
from focus.graph_db import GraphDB


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "dig.db"))
    d.ensure_schema()
    return d


def test_appetite_env_override(monkeypatch):
    monkeypatch.setenv("FOCUS_APPETITE_MB", "3000")
    assert digestion.appetite_bytes() == 3000 * 1024 * 1024


def test_appetite_bounded_by_total(monkeypatch):
    """胃口不许超过总内存 25%（16G 机器 ≤4G）。"""
    monkeypatch.delenv("FOCUS_APPETITE_MB", raising=False)
    total = digestion.mem_total_bytes()
    if total:  # 真实机器上才测
        assert digestion.appetite_bytes() <= total * 0.25 + 1


def test_can_digest_rejects_giant(monkeypatch):
    """100MB 预算吃不下 120MB（100×1.2）的食物；5GB 预算可以。"""
    monkeypatch.setenv("FOCUS_APPETITE_MB", "100")
    assert digestion.can_digest(100 * 1024**2) is False
    monkeypatch.setenv("FOCUS_APPETITE_MB", "5000")
    assert digestion.can_digest(1024**3) is True


def test_meal_ledger_and_avoidance(db):
    for _ in range(3):
        digestion.record_meal(db, "毒模型", "sick", "门禁未过")
    assert digestion.is_avoided(db, "毒模型") is True
    digestion.record_meal(db, "好模型", "ok")
    assert digestion.is_avoided(db, "好模型") is False
    assert digestion.is_avoided(db, "没吃过") is False


def test_hygiene_no_lms_graceful(monkeypatch):
    """lms 不可用 → 静默容错，不崩。"""
    monkeypatch.setattr(digestion, "_lms", lambda args, timeout=8.0: None)
    r = digestion.hygiene()
    assert r["cleaned"] == 0


def test_hygiene_dedups_instances(monkeypatch, db):
    """同名模型 ×3 → 保留主实例，卸载 2 个。"""
    fake_loaded = [
        {"modelKey": "qwen3.5-0.8b"},
        {"modelKey": "qwen3.5-0.8b:2"},
        {"modelKey": "qwen3.5-0.8b:3"},
    ]
    monkeypatch.setattr(digestion, "_lms",
                        lambda args, timeout=8.0: fake_loaded)
    unloaded = []

    class R:
        returncode = 0

    monkeypatch.setattr(digestion.subprocess, "run",
                        lambda *a, **k: unloaded.append(a[0]) or R())
    r = digestion.hygiene(db)
    assert r["cleaned"] == 2

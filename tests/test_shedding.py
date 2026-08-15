"""蜕皮模块测试：体重测量 / 阈值 / 超限重生 / 未超限不动。"""
import pytest

from focus import shedding


def test_rss_mb_positive():
    assert shedding.rss_mb() > 0


def test_limit_mb_env(monkeypatch):
    monkeypatch.setenv("FOCUS_SHED_LIMIT_MB", "512")
    assert shedding.limit_mb() == 512
    monkeypatch.setenv("FOCUS_SHED_LIMIT_MB", "不是数字")
    assert shedding.limit_mb() == shedding.DEFAULT_LIMIT_MB


def test_shed_when_over_limit(monkeypatch):
    """超限 → 退出码 77（launchd 会重生）。"""
    monkeypatch.setenv("FOCUS_SHED_LIMIT_MB", "1")  # 1MB，必超
    exits = []

    def fake_exit(code):
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(shedding.os, "_exit", fake_exit)
    with pytest.raises(SystemExit):
        shedding.maybe_shed("测试")
    assert exits == [77]


def test_no_shed_under_limit(monkeypatch):
    """未超限 → 安然无恙。"""
    monkeypatch.setenv("FOCUS_SHED_LIMIT_MB", "999999")
    exits = []
    monkeypatch.setattr(shedding.os, "_exit",
                        lambda code: exits.append(code))
    shedding.maybe_shed("测试")
    assert exits == []

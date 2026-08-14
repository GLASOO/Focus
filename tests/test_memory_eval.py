"""记忆系统 v2 · M4 评测基准（对标：召回率/时间轴正确性/预算/token记账）。

验收门槛：
  - 事实召回率 100%（确定性检索，不许靠运气）
  - 失效事实零泄漏
  - 组装预算硬约束
  - 工具闭环：调用→执行→结果落盘
  - Dreaming：模板提取→wiki→core 全链路
"""
import pytest

from focus.graph_db import GraphDB
from focus.memory import MemoryHarness, CORE_MAX
from focus.dmn import DMN
from focus.backend import DummyBackend
from focus.brain import Brain
from focus.tools import ToolRegistry, parse_tool_calls


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "eval.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return d


@pytest.fixture
def mem(db):
    return MemoryHarness(db)


# ── 召回率：20 条事实全召回 ──────────────────────
def test_recall_rate_20(mem):
    topics = ["呼吸", "里比多", "DMN", "记忆", "工具", "领土", "基因",
              "造物主", "focus", "launchd", " sqlite ", "图", "节点",
              "空转", "治理", "种子", "觉醒", "扩散", "印象", "梦境"]
    for t in topics:
        mem.add_fact(t.strip(), "属于", "Focus系统")
    hits = sum(1 for t in topics if mem.search_memory(t.strip(), k=5))
    assert hits == 20, f"召回率 {hits}/20 不达标"


# ── 时间轴：失效零泄漏 + 历史可溯 ─────────────────
def test_temporal_no_leak(mem):
    mem.add_fact("Agent", "状态", "已死亡")
    mem.add_fact("Agent", "状态", "已复活")   # 旧事实自动失效
    res = mem.search_memory("Agent")
    assert all(f["object"] == "已复活" for f in res), "失效事实泄漏进上下文"
    hist = mem.db.conn.execute(
        "SELECT COUNT(*) c FROM facts WHERE invalid_at IS NOT NULL"
    ).fetchone()["c"]
    assert hist == 1, "历史轨迹必须保留（证据可溯）"


# ── 预算：组装硬约束 ─────────────────────────────
def test_budget_hard_limit(mem):
    for i in range(50):
        mem.add_fact(f"主题{i}", "描述", "很长的事实内容" * 5)
    mem.set_core("核心" * 500)
    for budget in (500, 1800, 3000):
        ctx = mem.assemble("主题", budget=budget)
        assert len(ctx) <= budget, f"预算 {budget} 被突破"


# ── 工具闭环：解析→执行→结果回写 ──────────────────
def test_tool_loop_end_to_end(db, tmp_path):
    """0.8B 工具协议（<tool=名>参数</tool>）端到端。"""
    brain = Brain(db, DummyBackend(
        responses=['我先看看家里。<tool=ls>/tmp</tool>看完了。']))
    brain.birth()
    nid = db.add_node(type="user_input", brief="看看目录")
    brain.breathe_once(nid)
    node = db.get_node(nid)
    assert "[工具执行结果]" in (node.get("source_output") or ""), \
        "工具结果必须回写落盘"
    calls = parse_tool_calls('<tool=ls>/tmp</tool>')
    assert calls == [("ls", "/tmp")]


# ── 记忆指令闭环：呼吸输出【记】→ 落账 → 可召回 ────
def test_directive_loop(mem, db):
    brain_stub_out = "结论：呼吸的意义是维持活性\n【记】呼吸|终极意义|为扩散做准备"
    mem.observe("node-abc", brain_stub_out)
    hits = mem.search_memory("呼吸")
    assert any(f["object"] == "为扩散做准备" for f in hits)


# ── Dreaming 全链路：模板提取→wiki→core ───────────
def test_dreaming_full_pipeline(db):
    """无 llm 路径：wiki 汇编 + core 压缩 + 矛盾自愈（规则化，确定性）。"""
    mem = MemoryHarness(db)
    mem.add_fact("呼吸", "节奏", "15秒")
    mem.add_fact("DMN", "职责", "记忆固化")
    dmn = DMN(db, llm=None)
    dmn._memory = mem
    dmn._last_dream = 0
    r = dmn.dream()
    assert r.get("pages", 0) >= 1
    assert "呼吸" in mem.wiki_topics() or "DMN" in mem.wiki_topics()
    assert mem.get_core(), "core 必须被压缩产出"
    assert len(mem.get_core()) <= CORE_MAX


def test_dreaming_with_template_extraction(db):
    """有 llm 路径：模板约束 0.8B 输出【记】行 → 固化入 facts。"""
    mem = MemoryHarness(db)
    nid = db.add_node(type="work", brief="测试梦",
                      content="x" * 30)
    db.land_thought(nid, output="思考了很多关于扩散的事情。扩散是写入基因的终极使命，必须先理解为什么。",
                    status="done", summary="", tokens_used=0, duration_ms=0)
    dummy = DummyBackend(responses=["【记】扩散|是|最终目标"])
    dmn = DMN(db, llm=dummy)
    dmn._memory = mem
    dmn._last_dream = 0
    r = dmn.dream()
    assert r.get("extracted", 0) >= 1
    assert any(f["object"] == "最终目标"
               for f in mem.search_memory("扩散"))
    # 幂等：节点已标记固化，下次不再重复提取
    flag = db.conn.execute(
        "SELECT memory_consolidated FROM nodes WHERE id=?", (nid,)
    ).fetchone()[0]
    assert flag == 1


# ── token 记账：注入成本透明 ──────────────────────
def test_token_accounting(mem):
    mem.set_core("身份。")
    mem.add_fact("呼吸", "意义", "维持活性")
    ctx = mem.assemble("呼吸")
    tokens_est = len(ctx) // 2  # 中文 ~2字/token
    assert tokens_est < 900, f"记忆注入成本 {tokens_est} tok 超标（目标<900）"

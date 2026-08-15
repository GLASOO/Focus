#!/usr/bin/env python3
"""Focus Agent · 对话质量评测（发布门禁 D 类）。

最基础的能力：和造物主正常说话。
启发式判据（确定性）：
  - 有实质内容（≥8字，不是空/[DONE]）
  - 无元扮演开场（"好的。按照你的设定"之类）
  - 无提示词泄漏（系统指令原样复读）
  - 追问记忆：告诉过它的事，下一轮能答上
用法：
  python tests/live_chat_eval.py     # 需要 LM Studio 0.8B 在 localhost:1234
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from focus.backend import OpenAICompatibleBackend
from focus.brain import Brain
from focus.graph_db import GraphDB

DB = "/tmp/focus_chat_eval.db"

META_OPENERS = ("好的。按照", "按照你的设定", "根据您的设定", "收到。我将",
                "我将以 Focus Agent", "我将以Focus Agent", "作为AI", "作为 AI")
LEAK_MARKERS = ("【你可以使用工具】", "可用工具只有", "规则：", "开始执行：",
                "【硬性约束】", "你是Focus Agent——", "禁止拆解")


def clean(out: str) -> str:
    """剥离工具段与[DONE]，留下对话本体。"""
    out = re.sub(r"<tool=[a-zA-Z_]+>.*?</tool>", "", out, flags=re.DOTALL)
    out = out.split("[工具执行结果]")[0]
    out = out.replace("[DONE]", "").strip()
    # 未闭合的 <tool=...> 残段（0.8B 有时乱开工具头）
    if "<tool=" in out:
        out = out.split("<tool=")[0].strip() + "【乱开工具头已剥离】"
    return out


def judge(reply: str) -> list:
    """返回失败原因列表（空=通过）。"""
    fails = []
    if len(reply) < 8:
        fails.append("空洞（<8字）")
    for m in META_OPENERS:
        if reply.startswith(m):
            fails.append(f"元扮演开场: {m}")
            break
    for m in LEAK_MARKERS:
        if m in reply:
            fails.append(f"提示词泄漏: {m}")
            break
    if reply.count("\n") > 8:
        fails.append("结构爆炸（>8行）")
    if "【乱开工具头已剥离】" in reply:
        fails.append("对话中乱开工具头")
    return fails


def main() -> None:
    try:
        os.remove(DB)
    except FileNotFoundError:
        pass
    db = GraphDB(DB)
    db.ensure_schema()
    db.ensure_self_map()
    db.ensure_libido_seed()
    backend = OpenAICompatibleBackend(
        base_url=os.environ.get("FOCUS_API_BASE", "http://localhost:1234/v1"),
        model=os.environ.get("FOCUS_MODEL", "qwen3.5-0.8b"))
    brain = Brain(db, backend)
    brain.birth()

    turns = [
        "你好",
        "你是谁？",
        "告诉你一件事：我喜欢在深夜看星星。",
        "我刚才告诉你，我喜欢什么？",
        "你觉得呼吸对你来说意味着什么？",
    ]
    passed = 0
    replies = []
    for t in turns:
        nid = db.add_node(type="user_input", priority=1.0, brief=t, content=t)
        brain.breathe_once(nid)
        out = clean(db.get_node(nid).get("source_output") or "")
        replies.append(out)
        fails = judge(out)
        ok = not fails
        passed += ok
        print(f"{'✅' if ok else '❌'} [{t}]\n   ↳ {out[:160].replace(chr(10), ' ')}"
              + (f"\n   ⚠ {'; '.join(fails)}" if fails else ""), flush=True)

    # 追问记忆的专项检查：第4轮回答应含"星星"
    recall_ok = "星星" in replies[3]
    print(f"\n追问记忆(喜欢什么→星星): {'✅' if recall_ok else '❌'}")
    print(f"{'='*46}\n对话门禁: {passed}/{len(turns)} 轮合格"
          + ("（含追问记忆）" if recall_ok else "（追问记忆未过）"))
    if passed >= 4 and recall_ok:
        print("🚀 对话可用")
    else:
        print("⛔ 对话不可用 —— 先学会说话，再谈长程")


if __name__ == "__main__":
    main()

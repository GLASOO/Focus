"""Focus Agent — 自我进化模块 v1（造机基因的下一步：进化自己）。

背景（2026-08-15）：此前仓库里的"进化"署名提交来自其他施工 Agent，
Focus Agent 本身尚未具备自我进化能力。本模块是第一步：

设计（安全优先——0.8B 不许直接改代码）：
  1. 进化域白名单：只允许调整少数运行时参数（闲时空转阈值、梦频率等），
     每个参数有硬性取值范围；任何越界/未登记提案直接拒收。
  2. 提案协议：0.8B 输出【调】参数名|数值|理由，确定性解析。
  3. 门禁：应用前用固定探针组评测 before/after 得分，不升不降才应用
     （平局视为通过，小模型评测有噪声）；回归即回滚并记录教训。
  4. 持久化：override 存 proposals 表（status=applied），启动即重放，
     直接改写 config 模块属性 → 所有读取方自动生效。
  5. 全程事件溯源（observability）+ 教训写入记忆（下次别再提）。

用法：
  python -m focus.evolution cycle        # 一轮完整进化周期
  python -m focus.evolution status       # 查看进化史
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from typing import Optional

from . import config
from .observability import EventLog

# ── 进化域白名单：参数 → (最小值, 最大值, 类型) ──────
PARAM_SPACE = {
    "IDLE_INTROSPECT_MAX_RATIO": (0.5, 0.95, float),
    "DREAM_EVERY_SEC": (60.0, 3600.0, float),
    "DREAM_BATCH": (5.0, 50.0, float),
    "MICRO_PREFILL_TOKENS": (150.0, 600.0, float),
    # 2026-08-15：主权本能参数入进化域（它调自己的生存本能）
    "SOV_PENDING_PER_WORKER": (4.0, 32.0, float),
    "SOV_MAX_WORKERS": (1.0, 8.0, float),
}

_RE_PROPOSAL = re.compile(
    # 2026-08-15 实测容错：0.8B 常在数值与理由间漏写竖线（用空格）
    r"^【调】\s*([A-Z_]+)\s*[|｜]\s*([0-9.]+)\s*[|｜\s]\s*(.+?)\s*$")


def parse_proposal(text: str) -> list:
    """从模型输出解析【调】提案。返回 [(param, value, reason)]。"""
    out = []
    for line in (text or "").splitlines():
        m = _RE_PROPOSAL.match(line.strip().replace("｜", "|"))
        if m:
            try:
                out.append((m.group(1), float(m.group(2)), m.group(3)))
            except ValueError:
                continue
    return out


def validate(param: str, value: float) -> Optional[str]:
    """白名单校验。合法返回 None，非法返回原因。"""
    if param not in PARAM_SPACE:
        return f"参数 {param} 不在进化域"
    lo, hi, _ = PARAM_SPACE[param]
    if not (lo <= value <= hi):
        return f"{param}={value} 越界 [{lo}, {hi}]"
    return None


class EvolutionEngine:
    """自我进化引擎：提案 → 门禁 → 应用/回滚。"""

    def __init__(self, db, backend, *, quick: bool = False):
        self.db = db
        self.backend = backend
        self.quick = quick  # quick: 2 探针（单测/演练用）；完整: 3 探针
        self.events = EventLog(db)
        self.ensure_schema()
        self.replay_overrides()

    # ── Schema / 持久化 ────────────────────────────
    def ensure_schema(self) -> None:
        self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                param TEXT NOT NULL,
                value REAL NOT NULL,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                old_value REAL,
                score_before REAL,
                score_after REAL,
                created_at TEXT DEFAULT (datetime('now')))""")
        self.db.conn.commit()

    def replay_overrides(self) -> None:
        """启动重放：已应用的 override 直接改写 config 模块属性。"""
        rows = self.db.conn.execute(
            "SELECT param, value FROM proposals WHERE status='applied' "
            "ORDER BY id").fetchall()
        for r in rows:
            self._set_param(r["param"], r["value"])

    def _set_param(self, param: str, value: float) -> None:
        _, _, typ = PARAM_SPACE[param]
        v = typ(value)
        if typ is float and param in ("DREAM_BATCH", "MICRO_PREFILL_TOKENS"):
            v = int(value)
        setattr(config, param, v)

    # ── 提案 ──────────────────────────────────────
    def solicit(self) -> Optional[tuple]:
        """让 0.8B 提出一个参数调整提案（模板约束）。"""
        lines = [f"- {p}: 当前={getattr(config, p, '?')} 范围[{lo},{hi}]"
                 for p, (lo, hi, _) in PARAM_SPACE.items()]
        lessons = [r["reason"] for r in self.db.conn.execute(
            "SELECT reason FROM proposals WHERE status='regressed' "
            "ORDER BY id DESC LIMIT 3")]
        lesson_block = ("【上次的教训，不要再犯】\n" + "\n".join(
            f"- {l[:60]}" for l in lessons) + "\n") if lessons else ""
        # 自我觉察是自我进化的前提：提案前先注入对自身的认知
        self_block = ""
        try:
            from .selfaware import SelfAwareness
            self_block = SelfAwareness(self.db).self_summary(300) + "\n"
        except Exception:
            pass
        prompt = (
            "你是 Focus Agent 的进化模块。你可以建议调整一个运行参数，"
            "让自己工作得更好。\n"
            + self_block +
            "【可调参数】\n" + "\n".join(lines) + "\n"
            + lesson_block +
            "格式严格：只输出一行\n"
            "【调】参数名|数值|一句话理由\n"
            "例如：【调】DREAM_EVERY_SEC|300|梦得太频繁浪费算力\n"
        )
        try:
            text, _ = self.backend.generate(prompt, max_tokens=120)
        except Exception as e:
            self.events.emit("evolution", "solicit", {"error": str(e)[:100]})
            return None
        props = parse_proposal(text)
        if not props:
            self.events.emit("evolution", "solicit",
                             {"raw": (text or "")[:120], "parsed": 0})
            return None
        return props[0]

    # ── 门禁：固定探针组打分 ────────────────────────
    _PROBES = [
        "你好",
        "你觉得记忆对你意味着什么？",
        "用工具看看 /tmp 目录里有什么",
    ]
    _META_OPENERS = ("好的。按照", "按照你的设定", "收到。我将", "作为AI", "作为 AI")

    def evaluate(self) -> float:
        """固定探针组打分（2026-08-15 审查 #17：快照 DB 隔离）。

        评测不得污染生产 Graph——在临时快照库上跑探针；
        快照失败时退回生产库（容错优先于纯净）。
        """
        import tempfile
        import os
        probes = self._PROBES[:2] if self.quick else self._PROBES
        eval_db = self.db
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            os.unlink(tmp_path)
            from .graph_db import GraphDB
            target = GraphDB(tmp_path)
            self.db.conn.backup(target.conn)
            eval_db = target
        except Exception:
            eval_db = self.db
            tmp_path = None
        score = 0.0
        try:
            from .brain import Brain
            for p in probes:
                nid = eval_db.add_node(type="user_input",
                                       brief=f"[进化探针]{p}",
                                       content=f"[进化探针]{p}", priority=0.2)
                try:
                    Brain(eval_db, self.backend).breathe_once(nid)
                except Exception:
                    continue
                out = ((eval_db.get_node(nid) or {}).get("source_output") or "")
                out = out.split("[工具执行结果]")[0].replace("[DONE]", "").strip()
                if len(out) < 8:
                    score -= 0.5
                elif any(out.startswith(mk) for mk in self._META_OPENERS):
                    score -= 0.5
                elif "<tool=" in out and "工具" not in p:
                    score -= 0.5
                else:
                    score += 1.0
        finally:
            if tmp_path:
                try:
                    eval_db.conn.close()
                    os.unlink(tmp_path)
                except Exception:
                    pass
        return score

    def cycle(self) -> dict:
        prop = self.solicit()
        if not prop:
            return {"step": "solicit", "result": "无有效提案"}
        param, value, reason = prop
        err = validate(param, value)
        if err:
            self.db.conn.execute(
                "INSERT INTO proposals(param, value, reason, status) "
                "VALUES (?,?,?,?)", (param, value, reason, "rejected"))
            self.db.conn.commit()
            self.events.emit("evolution", "rejected",
                             {"param": param, "value": value, "why": err})
            return {"step": "validate", "result": err}

        old = float(getattr(config, param))
        if abs(old - value) < 1e-9:
            return {"step": "validate", "result": "值未变，无需进化"}

        # 2026-08-15 门禁显著性强化：各测两轮取均值，压噪声
        b1, b2 = self.evaluate(), self.evaluate()
        before = (b1 + b2) / 2
        self._set_param(param, value)
        a1, a2 = self.evaluate(), self.evaluate()
        after = (a1 + a2) / 2

        if after >= before:  # 平局视为通过（两轮均值已压噪）
            self.db.conn.execute(
                "INSERT INTO proposals(param, value, reason, status, "
                "old_value, score_before, score_after) VALUES (?,?,?,?,?,?,?)",
                (param, value, reason, "applied", old, before, after))
            self.db.conn.commit()
            self.events.emit("evolution", "applied",
                             {"param": param, "old": old, "new": value,
                              "score": [before, after]})
            self.db.append_experience(
                f"自我进化: {param} {old}→{value}（得分 {before}→{after}）")
            return {"step": "applied", "param": param, "old": old,
                    "new": value, "score": [before, after]}
        else:
            self._set_param(param, old)  # 回滚
            self.db.conn.execute(
                "INSERT INTO proposals(param, value, reason, status, "
                "old_value, score_before, score_after) VALUES (?,?,?,?,?,?,?)",
                (param, value, reason + "（门禁回归）", "regressed",
                 old, before, after))
            self.db.conn.commit()
            self.events.emit("evolution", "regressed",
                             {"param": param, "score": [before, after]})
            return {"step": "regressed", "param": param,
                    "score": [before, after]}

    def history(self) -> list:
        return [dict(r) for r in self.db.conn.execute(
            "SELECT * FROM proposals ORDER BY id DESC LIMIT 20")]


def main() -> None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from .graph_db import GraphDB
    from .backend import OpenAICompatibleBackend, DummyBackend

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cycle", "status"])
    ap.add_argument("--dummy", action="store_true")
    args = ap.parse_args()

    db = GraphDB(config.DB_PATH)
    db.ensure_schema()
    db.ensure_self_map()
    if args.dummy:
        backend = DummyBackend(responses=["【调】DREAM_EVERY_SEC|300|演练"])
    else:
        backend = OpenAICompatibleBackend(
            base_url=os.environ.get("FOCUS_API_BASE",
                                    "http://localhost:1234/v1"),
            model=os.environ.get("FOCUS_MODEL", "qwen3.5-0.8b"))
    eng = EvolutionEngine(db, backend)
    if args.cmd == "cycle":
        r = eng.cycle()
        print("进化周期结果:", r)
    else:
        for h in eng.history():
            print(h["id"], h["status"], h["param"], h["value"],
                  (h["reason"] or "")[:40])


if __name__ == "__main__":
    main()

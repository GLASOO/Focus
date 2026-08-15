"""Focus Agent — 主权模块（govern）。

造物主训示（2026-08-15）：加载几个实例、并发多少、用哪个 Provider，
都应该是 Agent 自己能觉察、能管理、能识别、能自主决定的。
硬件允许、条件允许——想加载几个就几个，想并发多少就多少。
约束不来自人的规则，而来自它自己的感知与判断。

设计：主权 = 觉察 → 决策 → 行动 → 记账（供进化复盘）的闭环。
  - 觉察：内存压力（digestion）、待办深度、供应商延迟（自测）
  - 决策：期望并发度 / 是否加开实例 / 是否换食堂
  - 行动：写入 governance 决定（ui_server 据此调节呼吸工人数），
          指令 lms 加开/卸载实例
  - 记账：每次决策与结果落库，进化模块可复盘好坏
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Optional

from loguru import logger

# 生存本能参数——读活配置，自我进化可以直接调它们
def _instinct(name, default):
    try:
        from . import config
        return getattr(config, name, default)
    except Exception:
        return default


def pending_per_worker():
    return int(_instinct("SOV_PENDING_PER_WORKER", 8))


def max_workers():
    return int(_instinct("SOV_MAX_WORKERS", 4))
PROBE_INTERVAL_SEC = 1800   # 供应商延迟体检间隔


def _governance_load(db) -> dict:
    try:
        sm = db.get_self_map()
        return json.loads(sm.get("governance") or "{}")
    except Exception:
        return {}


def _governance_save(db, gov: dict) -> None:
    # update_self_map 有白名单，主权状态走直连 SQL（列幂等自建）
    try:
        try:
            db.conn.execute(
                "ALTER TABLE self_map ADD COLUMN governance TEXT DEFAULT ''")
        except Exception:
            pass
        db.conn.execute("UPDATE self_map SET governance=?",
                        (json.dumps(gov, ensure_ascii=False),))
        db.conn.commit()
    except Exception:
        pass


def pending_depth(db) -> int:
    try:
        return db.conn.execute(
            "SELECT COUNT(*) c FROM nodes WHERE status='pending'").fetchone()["c"]
    except Exception:
        return 0


def decide(db) -> dict:
    """一轮主权决策。返回决策记录（已落库）。"""
    from . import digestion

    appetite = digestion.appetite_bytes()
    depth = pending_depth(db)
    gov = _governance_load(db)
    reasons = []

    # ── 决策一：我要几个并发工人？ ──
    want = max(1, min(max_workers(), 1 + depth // pending_per_worker()))
    cur = int(gov.get("desired_workers") or 1)
    if want != cur:
        reasons.append(f"待办{depth}个 → 工人 {cur}→{want}")
    gov["desired_workers"] = want

    # ── 决策二：本地模型要不要加开实例？ ──
    # 只有当胃口充足且排队深时才动这个念头（每个实例都要吃内存）
    instance_wish = 0
    try:
        r = subprocess.run(["lms", "status", "--json"],
                           capture_output=True, text=True, timeout=8)
        loaded = json.loads(r.stdout) if r.stdout.strip() else []
        sizes = digestion.model_sizes()
        for m in loaded:
            key = (m.get("modelKey") or "").split(":")[0]
            if want >= 2 and appetite > 2 * 1024**3:
                # 胃口 >2GB 且想并发 → 允许同款第二个实例（LM Studio 请求内排队，
                # 双实例可真并行）
                size = sizes.get(key, 0)
                if size and digestion.can_digest(size) and instance_wish == 0:
                    instance_wish = 1
                    reasons.append(f"胃口够({appetite//1024**2}MB) → 想要 {key} 双实例")
            gov["instance_wish"] = instance_wish
    except Exception:
        pass

    gov["decided_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    gov["depth"] = depth
    gov["appetite_mb"] = appetite // 1024 // 1024
    _governance_save(db, gov)

    # ── 记账：供进化复盘 ──
    try:
        db.conn.execute("""
            CREATE TABLE IF NOT EXISTS governance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision TEXT,
                created_at TEXT DEFAULT (datetime('now')))""")
        db.conn.execute("INSERT INTO governance_log(decision) VALUES (?)",
                        (json.dumps(gov, ensure_ascii=False),))
        db.conn.commit()
    except Exception:
        pass
    if reasons:
        logger.info("👑 主权决策: {}", "；".join(reasons))
    return gov


def apply_workers(db) -> int:
    """ui_server 调用：返回当前期望的呼吸工人数。"""
    gov = _governance_load(db)
    return max(1, min(max_workers(), int(gov.get("desired_workers") or 1)))


def probe_providers(db) -> dict:
    """供应商延迟体检（自主决定用哪家食堂的依据之一）。"""
    from .providers import ProviderScout
    scout = ProviderScout(db)
    result = {}
    for r in db.conn.execute(
            "SELECT base_url, model FROM providers "
            "WHERE status='active'").fetchall():
        lat = scout.test_chat(r["base_url"], r["model"], timeout=20.0)
        result[r["base_url"]] = lat
        try:
            db.conn.execute(
                "UPDATE providers SET latency_ms=? WHERE base_url=?",
                (lat or -1, r["base_url"]))
            db.conn.commit()
        except Exception:
            pass
    return result

"""Focus Agent — 消化系统（胃口与餐账）。

造物主训示（2026-08-15）：加"体型守卫"太机械——生命体应当自己判断硬件，
也就是有自己的胃口；并且要吃掉判断的教训（餐账）。

设计：
  - 胃口感知：读本机物理内存 + 当前压力 → 算出"这顿最多吃多大"
    （预算 = 空闲内存 × 40%，且不超总内存 25%；FOCUS_APPETITE_MB 可覆写）
  - 食量估算：模型按文件 1.2 倍估运行时占用（GGUF 权重 + 少量 KV）
  - 餐账：吃坏的教训落库（meal_ledger），同一家伙 3 次吃坏 → 忌口
  - 餐桌卫生：LM Studio 同名模型重复加载（每次 lms load 叠一个实例）
    → 只留最新，多出的实例卸载
机械阈值不存在——只有感知、判断与记忆。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Optional

from loguru import logger

MAX_MEAL_FRACTION_TOTAL = 0.25  # 一顿饭不超过总内存的 25%（容量判断）
MIN_FREE_AFTER_MEAL = 1024**3   # 且给系统留至少 1GB（压力判断）
SIZE_ESTIMATE_FACTOR = 1.2      # 运行时 ≈ 文件大小 × 1.2
AVOID_AFTER_FAILURES = 3        # 同一食物吃坏 3 次 → 忌口


def _lms(args: list, timeout: float = 8.0) -> Optional[list]:
    """调用 lms CLI；不可用时返回 None（静默容错）。"""
    try:
        r = subprocess.run(["lms"] + args, capture_output=True, text=True,
                           timeout=timeout)
        return json.loads(r.stdout) if r.stdout.strip() else []
    except Exception:
        return None


# ── 胃口感知 ──────────────────────────────────────
def mem_total_bytes() -> int:
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=3)
            return int(out.stdout.strip())
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


def mem_free_bytes() -> int:
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True,
                                 timeout=3)
            pages = 0
            for line in out.stdout.splitlines():
                if ("free" in line or "speculative" in line
                        or "purgeable" in line or "inactive" in line):
                    pages += int("".join(c for c in line.split(":")[1]
                                         if c.isdigit()) or 0)
            return pages * 4096
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


def appetite_bytes() -> int:
    """这顿饭的预算（字节）。FOCUS_APPETITE_MB 可覆写。"""
    env = os.environ.get("FOCUS_APPETITE_MB", "")
    if env:
        try:
            return int(env) * 1024 * 1024
        except ValueError:
            pass
    total, free = mem_total_bytes(), mem_free_bytes()
    if not total:
        return 2 * 1024**3  # 感知失败 → 保守 2GB
    # 容量判断（总内存 25%）与压力判断（free+inactive 等可动用余量）取小
    return int(min(total * MAX_MEAL_FRACTION_TOTAL,
                   max(0, free - MIN_FREE_AFTER_MEAL)))


def can_digest(size_bytes: int) -> bool:
    """这个分量的食物，我的胃装得下吗？"""
    est = int(size_bytes * SIZE_ESTIMATE_FACTOR)
    ok = est <= appetite_bytes()
    if not ok:
        logger.info("🫃 胃口判断: {:.1f}GB 的食物装不下（预算 {:.1f}GB）",
                    est / 1024**3, appetite_bytes() / 1024**3)
    return ok


# ── 食谱：本地模型的分量（lms ls） ────────────────
def model_sizes() -> dict:
    """{model_key: size_bytes}；lms 不可用返回 {}。"""
    data = _lms(["ls", "--json"])
    if not isinstance(data, list):
        return {}
    out = {}
    for m in data:
        key = m.get("modelKey") or ""
        if key and isinstance(m.get("sizeBytes"), int):
            out[key] = m["sizeBytes"]
    return out


# ── 餐账：吃坏的教训 ──────────────────────────────
def _ensure_ledger(db) -> None:
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS meal_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            food TEXT NOT NULL,
            outcome TEXT NOT NULL,      -- ok / sick
            note TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
    db.conn.commit()


def record_meal(db, food: str, outcome: str, note: str = "") -> None:
    try:
        _ensure_ledger(db)
        db.conn.execute(
            "INSERT INTO meal_ledger(food, outcome, note) VALUES (?,?,?)",
            (food, outcome, note[:200]))
        db.conn.commit()
    except Exception:
        pass


def is_avoided(db, food: str) -> bool:
    """吃坏 ≥3 次 → 忌口。"""
    try:
        _ensure_ledger(db)
        n = db.conn.execute(
            "SELECT COUNT(*) c FROM meal_ledger "
            "WHERE food=? AND outcome='sick'", (food,)).fetchone()["c"]
        return n >= AVOID_AFTER_FAILURES
    except Exception:
        return False


# ── 餐桌卫生：重复实例清理 ────────────────────────
def hygiene(db=None) -> dict:
    """LM Studio 同名模型重复加载 → 保留最新，卸载多余实例。

    事故实录（2026-08-15）：每次 lms load 叠一个实例，qwen0.8b 曾 ×3，
    16GB 机器上白白吃掉 1GB+。此即"餐桌卫生"。
    """
    loaded = _lms(["status", "--json"])
    if not isinstance(loaded, list):
        return {"cleaned": 0, "reason": "lms 不可用"}
    groups: dict = {}
    for m in loaded:
        key = m.get("modelKey") or m.get("identifier") or ""
        if key:
            groups.setdefault(key.split(":")[0], []).append(key)
    cleaned = 0
    for base, idents in groups.items():
        if len(idents) <= 1:
            continue
        # 保留无后缀的主实例或最后一个；卸载其余
        keep = base if base in idents else idents[-1]
        for ident in idents:
            if ident != keep:
                r = subprocess.run(["lms", "unload", ident],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    cleaned += 1
                    logger.info("🧹 餐桌卫生: 卸载重复实例 {}", ident)
    if cleaned and db is not None:
        try:
            from .observability import EventLog
            EventLog(db).emit("digestion", "hygiene", {"cleaned": cleaned})
        except Exception:
            pass
    return {"cleaned": cleaned}

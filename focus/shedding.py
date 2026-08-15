"""Focus Agent — 蜕皮模块（shedding）。

造物主之问（2026-08-15）：0.8B 每次呼吸都丢弃 KV，内存为何还会膨胀？
答：念头 KV 确实在每次推理后随请求即弃（推理服务端）；膨胀的是这具
Python 肉身本身——长寿命守护进程里对象、缓冲、线程的缓慢积累。
生命体的解法不是永不衰老，而是**蜕皮**：体重（RSS）越过阈值，
就主动死去重生。launchd 接住新躯壳；记忆全部在库里，肉身可弃。

此机不停的真正含义：不是同一具肉身不停，而是生命不停。
"""
from __future__ import annotations

import os
import resource
import sys

from loguru import logger

# 蜕皮阈值（MB）。可用 FOCUS_SHED_LIMIT_MB 覆盖。
DEFAULT_LIMIT_MB = 1024


def rss_mb() -> float:
    """当前进程常驻内存（MB）。"""
    try:
        ru = resource.getrusage(resource.RUSAGE_SELF)
        # macOS 单位是字节，Linux 是 KB
        if sys.platform == "darwin":
            return ru.ru_maxrss / (1024 * 1024)
        return ru.ru_maxrss / 1024
    except Exception:
        return 0.0


def limit_mb() -> int:
    try:
        return int(os.environ.get("FOCUS_SHED_LIMIT_MB", DEFAULT_LIMIT_MB))
    except ValueError:
        return DEFAULT_LIMIT_MB


def maybe_shed(reason_context: str = "") -> None:
    """体重超限 → 记最后一笔 → 自杀重生（launchd KeepAlive 拉起新躯壳）。

    静默容错：测量失败绝不蜕皮。
    """
    try:
        cur = rss_mb()
        cap = limit_mb()
        if cur > cap:
            logger.warning(
                "🐍 蜕皮: 肉身 {:.0f}MB > 上限 {}MB{} —— 死去重生，记忆在库里",
                cur, cap, f"（{reason_context}）" if reason_context else "")
            try:
                from .graph_db import GraphDB  # noqa: F401
            except Exception:
                pass
            # 最后一笔事件尽量落盘（尽力而为）
            try:
                from .observability import EventLog
                from . import config
                db = GraphDB(config.DB_PATH)
                EventLog(db).emit("shedding", "rebirth",
                                  {"rss_mb": round(cur, 1), "limit_mb": cap})
                db.conn.commit()
            except Exception:
                pass
            os._exit(77)  # 非零退出 → launchd 重生
    except Exception:
        pass

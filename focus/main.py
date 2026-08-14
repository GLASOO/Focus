#!/usr/bin/env python3
"""Focus Agent — 主入口（实施手册 §14 启动序列）

启动序列：
  GraphDB.ensure_schema / ensure_self_map / load
  → Brain.birth()
  → DMN 后台线程
  → 信号处理（优雅退出）
  → textual UI

用法：
  python -m focus.main                                   # LM Studio 本地 0.8B
  FOCUS_BACKEND=openai FOCUS_API_BASE=https://token.sensenova.cn/v1 \
    FOCUS_API_KEY=<key> FOCUS_MODEL=deepseek-v4-flash \
    python -m focus.main                                  # sensenova 云端大模型
  FOCUS_BACKEND=dummy python -m focus.main               # 无模型跑通
  FOCUS_DB=/tmp/f.db python -m focus.main                # 指定数据库
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from . import config
from .backend import create_backend
from .brain import Brain
from .dmn import DMN
from .graph_db import GraphDB
from .ui import FocusUI

logger.remove()
logger.add(sys.stderr, level=os.environ.get("FOCUS_LOG", "INFO"),
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")


def main() -> None:
    # 确保数据目录
    os.makedirs(config.DATA_DIR, exist_ok=True)

    db = GraphDB(config.DB_PATH)
    if config.BACKEND == "openai":
        backend = create_backend(
            "openai",
            base_url=config.API_BASE,
            api_key=config.API_KEY,
            model=config.API_MODEL,
        )
    else:
        backend = create_backend(config.BACKEND, model_path=config.MODEL_PATH)
    brain = Brain(db, backend)
    dmn = DMN(db)

    # 优雅退出
    stop_event = threading.Event()

    def _signal(sig, frame):
        logger.info("收到信号 {}, 优雅退出...", sig)
        stop_event.set()
        brain.stop()
        dmn.stop()

    signal.signal(signal.SIGINT, _signal)
    signal.signal(signal.SIGTERM, _signal)

    # UI（TTY 双窗口 / 非 TTY 纯日志）
    ui = FocusUI(db, brain, dmn)
    ui.start()

    # DMN 后台巡逻
    dmn.start()

    # 呼吸循环（主线程）
    try:
        brain.run()
    except KeyboardInterrupt:
        pass
    finally:
        dmn.stop()
        brain.backend.unload()
        db.close()
        ui.stop()
        logger.info("Focus Agent 退出。数据已持久化于 {}", config.DB_PATH)


if __name__ == "__main__":
    main()

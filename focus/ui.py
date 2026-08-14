"""Focus Agent — 双窗口 CLI（实施手册 §13 + 任务书）

基于 textual 的双面板：
  左：Graph 状态（节点/待处理/统计）
  右：念头流（实时生成输出）

非交互模式（无 TTY）自动降级为日志输出。
"""

from __future__ import annotations

import os
import sys

from loguru import logger

from . import config
from .graph_db import GraphDB


class FocusUI:
    """UI 壳：TTY 用 textual 双窗口，否则纯日志。"""

    def __init__(self, db: GraphDB, brain=None, dmn=None):
        self.db = db
        self.brain = brain
        self.dmn = dmn
        self._app = None

    def start(self) -> None:
        if sys.stdin.isatty() and os.environ.get("FOCUS_NO_UI") != "1":
            try:
                from textual.app import App
                from textual.containers import Horizontal
                from textual.widgets import Footer, Header, Static
            except ImportError:
                logger.warning("textual 不可用，降级纯日志")
                return
            self._app = FocusApp(self.db, self.brain, self.dmn)
            # 非阻塞启动（主线程继续跑呼吸循环）
            import threading
            threading.Thread(target=self._app.run, daemon=True).start()
            logger.info("🖥️ textual UI 启动")
        else:
            logger.info("非 TTY 环境，纯日志模式")

    def stop(self) -> None:
        if self._app:
            try:
                self._app.exit()
            except Exception:
                pass


class FocusApp:
    """textual 双窗口应用。"""

    def __init__(self, db: GraphDB, brain=None, dmn=None):
        self.db = db
        self.brain = brain
        self.dmn = dmn
        from textual.app import App
        from textual.containers import Horizontal
        from textual.widgets import Footer, Header, Static

        class _App(App):
            CSS = """
            Screen { layout: horizontal; }
            #left { width: 45%; border: solid green; }
            #right { width: 55%; border: solid blue; }
            """

            def compose(self):
                yield Header()
                with Horizontal():
                    yield Static("", id="left")
                    yield Static("", id="right")
                yield Footer()

            def on_mount(self):
                self.set_interval(1.0, self._refresh)

            def _refresh(self):
                left = self.query_one("#left", Static)
                right = self.query_one("#right", Static)
                left.update(self._left_text())
                right.update(self._right_text())

            def _left_text(self):
                s = self.db.stats()
                lines = [
                    "📊 GRAPH",
                    f"nodes={s['total']} edges={s['edges']} thoughts={s['thoughts']}",
                    "--- pending ---",
                ]
                for r in self.db.conn.execute(
                    "SELECT brief, priority, type FROM nodes WHERE status='pending' "
                    "ORDER BY priority DESC LIMIT 12"
                ):
                    lines.append(f"  [{r['priority']:.1f}] {r['type'][:8]} {r['brief'][:30]}")
                return "\n".join(lines)

            def _right_text(self):
                lines = ["🧠 THOUGHTS"]
                for r in self.db.conn.execute(
                    "SELECT node_id, status, created_at FROM thought_log "
                    "ORDER BY id DESC LIMIT 12"
                ):
                    lines.append(f"  {r['created_at'][11:19]} {r['node_id'][:8]} {r['status']}")
                if self.brain:
                    st = self.brain.stats
                    lines.append(f"--- brain: done={st.done} corrupt={st.corrupted} "
                                 f"thoughts={st.thoughts} ---")
                if self.dmn:
                    lines.append(f"--- dmn rounds={self.dmn.rounds} ---")
                return "\n".join(lines)

        self.app_cls = _App

    def run(self) -> None:
        self.app_cls().run()

    def exit(self) -> None:
        self.app_cls().exit()

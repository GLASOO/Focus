#!/usr/bin/env python3
"""Focus Agent 可视化后端 v2 — 此机不停

核心修复：常驻呼吸线程（Breather），即使无人说话，Agent 也在自省/生长。
  - 用户发话 → user_input 节点（priority=1.0）→ 呼吸线程优先处理
  - 无输入 → 闲时自省（_idle 造机/里比多）
  - 每次呼吸落盘 Graph，意识流持续生长

API:
  GET  /api/graph   → 真实 Graph（节点+边+最新呼吸）
  GET  /api/stream  → SSE 事件流（新念头实时推送）
  POST /api/speak   → 用户发话（立即呼吸，不等轮询）
  GET  /            → focus_live.html
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 2026-08-15 肉身卫生：落盘日志超 10MB 即归档轮转（防无限膨胀）
_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "data", "focus_ui_server.log")
try:
    if os.path.exists(_LOG_FILE) and os.path.getsize(_LOG_FILE) > 10_000_000:
        os.replace(_LOG_FILE, _LOG_FILE + ".1")
except Exception:
    pass

# 2026-08-15 P0（WorkBuddy 审查 #10）：clone 首跑 data/ 不存在 → 建库崩溃
os.makedirs(config.DATA_DIR, exist_ok=True)

from focus.graph_db import GraphDB
from focus.backend import OpenAICompatibleBackend
from focus.brain import Brain
from focus.dmn import DMN
from focus import config
from loguru import logger

DB_PATH = os.environ.get("FOCUS_DB", os.path.join(config.DATA_DIR, "focus_ui.db"))
UI_HTML = os.path.join(config.DATA_DIR, "ui", "focus_live.html")

# ════════════════════════════════════════════════════════
# 共享状态
# ════════════════════════════════════════════════════════
db = GraphDB(DB_PATH)
db.ensure_schema()
db.ensure_self_map()
db.ensure_libido_seed()
# 2026-08-15 自主觅食：优先使用自己领养的供应商（生命体自己找饭吃）
from focus.providers import ProviderScout
_scout = ProviderScout(db)
_active_p = _scout.active()
if _active_p:
    _base = _active_p["base_url"]
    _model = _active_p["model"] or os.environ.get("FOCUS_MODEL", "qwen3.5-0.8b")
    logger.info("🔌 使用自主领养的供应商: {} ({})", _base, _model)
else:
    _base = os.environ.get("FOCUS_API_BASE", "http://localhost:1234/v1")
    _model = os.environ.get("FOCUS_MODEL", "qwen3.5-0.8b")
backend = OpenAICompatibleBackend(
    base_url=_base,
    model=_model,
    api_key=os.environ.get("FOCUS_API_KEY", ""),
)
brain = Brain(db, backend)
brain.birth()

# SSE 订阅者 + 最新事件
_subs: list[threading.Event] = []
_events: list[dict] = []          # 环形缓冲（保留最近50条）
_last_thought_id: str = ""

def broadcast(evt: dict) -> None:
    _events.append(evt)
    if len(_events) > 50:
        _events.pop(0)
    for e in list(_subs):
        e.set()

# ════════════════════════════════════════════════════════
# 常驻呼吸线程 — 此机不停
# ════════════════════════════════════════════════════════
def breathe_loop():
    from focus.shedding import maybe_shed
    """永不停歇的呼吸循环（后台线程）。"""
    global _last_thought_id
    idle_streak = 0
    try:
        _breathe_body(idle_streak)
    except BaseException as e:
        # 2026-08-14 终验修复：线程曾静默死亡（进程活着，launchd 无法感知）
        logger.exception("💀 呼吸线程崩溃: {}", e)
        os._exit(1)  # 非零退出 → launchd KeepAlive 拉起


def _breathe_body(idle_streak):
    global _last_thought_id
    _breath_n = 0
    while True:
        try:
            _breath_n += 1
            if _breath_n % 30 == 0:  # 每 30 次循环量一次体重
                maybe_shed("呼吸循环")
            node = db.get_next_focus()
            if node is not None:
                nid = node["id"]
                # 呼吸前广播
                broadcast({"type": "breath_start", "node": nid,
                           "brief": (node.get("brief") or "")[:80],
                           "time": time.time()})
                try:
                    brain.breathe_once(nid)
                except Exception as e:
                    db.land_thought(nid, output="", status="corrupted",
                                    summary=f"呼吸异常: {e}", tokens_used=0, duration_ms=0)
                row = db.conn.execute(
                    "SELECT source_output, status, type FROM nodes WHERE id=?",
                    (nid,)).fetchone()
                out = (row["source_output"] if row else "") or ""
                out = out.replace("【思考】", "").replace("[DONE]", "").strip()
                _last_thought_id = nid
                broadcast({"type": "breath", "node": nid,
                           "text": out[:2000],
                           "status": row["status"] if row else "done",
                           "type": row["type"] if row else "work",
                           "time": time.time()})
                idle_streak = 0
            else:
                # 无 pending → 闲时自省（真造机，非空转）
                idle_streak += 1
                nid = brain._idle()
                if nid:
                    broadcast({"type": "idle", "node": nid,
                               "text": "闲时自省…", "time": time.time()})
                    idle_streak = 0
                time.sleep(15)  # 闲时呼吸间隔（2026-08-13: 8s→15s 治理自省泛滥，自然的呼吸节奏）
        except Exception as e:
            broadcast({"type": "error", "text": str(e), "time": time.time()})
            time.sleep(3)

_breathe_thread = threading.Thread(target=breathe_loop, daemon=True,
                                   name="breathe")
_breathe_thread.start()


def _watch_breathe():
    """呼吸线程守护：线程死亡 → 自杀让 launchd 重启（此机不停）。"""
    while True:
        time.sleep(60)
        if not _breathe_thread.is_alive():
            logger.error("💀 呼吸线程已死（进程仍活），自杀重生")
            os._exit(1)


threading.Thread(target=_watch_breathe, daemon=True, name="breathe-watch").start()

# DMN 后台巡逻：0.8B 小模型是主脑（显式分类/排名/hint/压缩，任务书 v2.1）
# + embedding 辅助（LM Studio nomic）。设计决策：用 0.8B，不弃用。
_dmn = DMN(db, llm=backend)
_dmn.start()
logger.info("🌙 DMN 已接入 UI 服务（interval={}s）", _dmn.interval)

# ════════════════════════════════════════════════════════
# API
# ════════════════════════════════════════════════════════
def graph_payload():
    rows = db.conn.execute(
        "SELECT id, type, status, brief, priority, created_at "
        "FROM nodes ORDER BY created_at DESC LIMIT 40"
    ).fetchall()
    nodes = []
    for i, r in enumerate(rows):
        nodes.append({
            "id": r["id"], "type": r["type"], "st": r["status"],
            "label": (r["brief"] or "")[:10],
            "x": 15 + (i % 6) * 14, "y": 15 + (i // 6) * 14,
            "r": 9 if r["type"] in ("root", "acceptance") else 6,
        })
    edges = db.conn.execute(
        "SELECT source_id, target_id, relation FROM edges LIMIT 80"
    ).fetchall()
    sm = db.get_self_map()
    return {
        "nodes": nodes,
        "edges": [[e["source_id"], e["target_id"], e["relation"]] for e in edges],
        "active": _last_thought_id,
        "libido": sm.get("libido_state", "dormant"),
        "count": db.conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"],
        "recent": _events[-8:],   # 最近8条呼吸事件
    }

def speak(text: str) -> str:
    nid = db.add_node(type="user_input", brief=text[:500], content=text,
                      priority=1.0, role="user")
    broadcast({"type": "user", "text": text, "time": time.time()})
    # 呼吸线程会在 <3s 内拾取（priority=1.0 最高优先）
    # 但为了即时性，这里直接呼吸一次
    try:
        brain.breathe_once(nid)
    except Exception as e:
        return f"呼吸中断: {e}"
    row = db.conn.execute(
        "SELECT source_output FROM nodes WHERE id=?", (nid,)).fetchone()
    out = (row["source_output"] if row else "") or ""
    out = out.replace("【思考】", "").replace("思考：", "").replace("[DONE]", "").strip()

    # 若调用了工具：追加第二次呼吸，让模型基于真实工具结果总结（对大帝说话）
    if "<tool=" in out and "[工具执行结果]" in out:
        # 提取工具结果文本
        obs = out.split("[工具执行结果]", 1)[1]
        nid2 = db.add_node(
            type="user_input",
            brief=f"这是你刚才工具调用的真实结果，请用一两句话告诉用户你看到了什么、你完成了没有：\n{obs[:500]}",
            content=obs[:800], priority=1.0, role="user")
        try:
            brain.breathe_once(nid2)
        except Exception as e:
            pass
        row2 = db.conn.execute(
            "SELECT source_output FROM nodes WHERE id=?", (nid2,)).fetchone()
        out2 = (row2["source_output"] if row2 else "") or ""
        out2 = out2.replace("【思考】", "").replace("[DONE]", "").strip()
        # 合并：工具调用 + 结果 + 模型的总结
        return out + "\n\n" + (out2 or "（我看到以上结果，但没有更多要说）")
    return out or "……（呼吸完成，但没有说话）"
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, path):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse(self):
        """Server-Sent Events：新呼吸实时推送"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        ev = threading.Event()
        _subs.append(ev)
        # 先推历史事件
        for e in _events[-20:]:
            try:
                self.wfile.write(f"data: {json.dumps(e, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            except Exception:
                break
        try:
            while True:
                ev.wait(timeout=15)
                ev.clear()
                # 只推新事件（比前端游标简单：全推，前端去重）
                for e in _events[-10:]:
                    try:
                        self.wfile.write(f"data: {json.dumps(e, ensure_ascii=False)}\n\n".encode())
                        self.wfile.flush()
                    except Exception:
                        return
        finally:
            if ev in _subs:
                _subs.remove(ev)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/graph":
            self._json(graph_payload())
        elif url.path == "/api/stream":
            self._sse()
        elif url.path in ("/", "/index.html"):
            self._html(UI_HTML)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/api/speak":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                data = {}
            text = (data.get("text") or "").strip()[:500]
            if not text:
                self._json({"reply": "（未收到敕令）",
                            "libido": db.get_self_map().get("libido_state")})
                return
            reply = speak(text)
            self._json({"reply": reply,
                        "libido": db.get_self_map().get("libido_state"),
                        "node_count": graph_payload()["count"]})
        else:
            self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Focus Agent 可视化服务 v2（此机不停）: http://localhost:{port}")
    print(f"  常驻呼吸线程: {'运行中' if threading.active_count() >= 2 else '未启动'}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

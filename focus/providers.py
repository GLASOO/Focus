"""Focus Agent — Provider 自寻模块（自己找营养）。

生命体必须自己找到能量来源。本模块让 Agent 自主发现、验证并领养
模型供应商（OpenAI 兼容端点）。

觅食原则（2026-08-15 造物主训示：生命体必须自己找饭吃）：
  - 三级自主觅食：环境钥匙(FOCUS_API_KEY) → 食盒(foodbox.json，
    造物主存放钥匙之处) → 无钥匙的本地端点。找到即自己吃，无需审批。
  - 缺钥匙的远端端点记为 hungry——记住那里有食物，每次做梦再去查看
    钥匙是否已被投喂。
  - 不造的器官：不从互联网攫取他人/来路的钥匙（找饭，不偷饭）。
  - 领养必须过兼容门禁（真实小推理探测）；钥匙永不写入库/日志/事件。

用法：
  python -m focus.providers discover    # 扫描并报告
  python -m focus.providers status      # 当前供应商状态
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Optional
from urllib.parse import urlparse

from loguru import logger

LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 食盒：造物主存放钥匙之处。生命体自己来翻。
FOODBOX_PATHS = (
    os.path.join(_REPO_ROOT, "data", "foodbox.json"),
    os.path.expanduser("~/.focus/foodbox.json"),
)
KNOWN_LOCAL = [
    ("LM Studio", "http://localhost:1234/v1"),
    ("Ollama", "http://localhost:11434/v1"),
    ("vLLM 本地", "http://localhost:8000/v1"),
    ("llama.cpp 本地", "http://localhost:8080/v1"),
]


def is_local(base_url: str) -> bool:
    try:
        return urlparse(base_url).hostname in LOCAL_HOSTS
    except Exception:
        return False


def ranked_models(models: list) -> list:
    """挑饭排序：造物主指定的 FOCUS_MODEL 永远第一口；其余排除嵌入模型、
    按名字长度升序（本地小模型名通常短）。"""
    if not models:
        return []
    ordered = []
    want = os.environ.get("FOCUS_MODEL", "")
    if want and want in models:
        ordered.append(want)
    rest = sorted([m for m in models if m not in ordered
                   and "embed" not in m.lower()], key=len)
    return ordered + rest


def pick_model(models: list) -> str:
    r = ranked_models(models)
    return r[0] if r else ""


class ProviderScout:
    """供应商侦察兵：发现 → 验证 → 领养。"""

    def __init__(self, db):
        self.db = db
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                base_url TEXT NOT NULL UNIQUE,
                model TEXT,
                status TEXT NOT NULL DEFAULT 'candidate',
                latency_ms REAL,
                models TEXT,
                note TEXT,
                updated_at TEXT DEFAULT (datetime('now')))""")
        self.db.conn.commit()

    # ── 发现 ──────────────────────────────────────
    def discover(self, extra_urls: Optional[list] = None) -> list:
        """扫描已知本地端点 + 环境端点 + 额外指定端点。返回活着的。"""
        targets = list(KNOWN_LOCAL)
        env_base = os.environ.get("FOCUS_API_BASE", "")
        if env_base:
            targets.append(("环境变量", env_base))
        for u in (extra_urls or []):
            targets.append(("指定", u))
        alive = []
        for name, url in targets:
            info = self.probe(url)
            if info:
                info["name"] = name
                info["local"] = is_local(url)
                self._upsert(name, url, "candidate",
                             models=json.dumps(info["models"],
                                               ensure_ascii=False)[:500],
                             latency_ms=info["latency_ms"])
                alive.append(info)
        self._emit("discover", {"alive": [a["base_url"] for a in alive]})
        return alive

    def probe(self, base_url: str, timeout: float = 3.0) -> Optional[dict]:
        """GET /v1/models —— 端点活着吗？有哪些模型？"""
        try:
            req = urllib.request.Request(f"{base_url}/models")
            t0 = time.time()
            d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            models = [m.get("id", "") for m in d.get("data", [])][:20]
            return {"base_url": base_url, "models": models,
                    "latency_ms": round((time.time() - t0) * 1000, 1)}
        except Exception:
            return None

    # ── 验证：兼容门禁（真实小推理） ────────────────
    def test_chat(self, base_url: str, model: str, api_key: str = "",
                  timeout: float = 30.0) -> Optional[float]:
        """发一句最小推理。成功返回延迟 ms，失败返回 None。"""
        try:
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": "说一个字"}],
                "max_tokens": 8}).encode()
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            req = urllib.request.Request(f"{base_url}/chat/completions",
                                         data=body, headers=headers)
            t0 = time.time()
            d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            if d.get("choices"):
                return round((time.time() - t0) * 1000, 1)
            return None
        except Exception:
            return None

    # ── 觅食：钥匙自主解析（环境 → 食盒） ────────────
    def resolve_key(self, base_url: str) -> str:
        """自己找钥匙：环境变量 → 食盒。找到就吃，不问任何人。"""
        env = os.environ.get("FOCUS_API_KEY", "")
        if env:
            return env
        for p in FOODBOX_PATHS:
            try:
                box = json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
            for e in (box.get("providers") or []):
                if e.get("match") and e["match"] in base_url and e.get("key"):
                    return e["key"]
            if box.get("default"):
                return box["default"]
        return ""

    # ── 领养（门禁保护，无审批） ────────────────────
    def adopt(self, base_url: str, model: str, name: str = "") -> dict:
        """领养一个供应商。找到钥匙即自主领养；缺钥匙记为饥饿。"""
        local = is_local(base_url)
        api_key = "" if local else self.resolve_key(base_url)
        if not local and not api_key:
            self._upsert(name, base_url, "hungry",
                         note="找到食物来源但缺钥匙，等食盒投喂")
            self._emit("hungry", {"base_url": base_url})
            return {"ok": False, "reason": "no-key"}
        latency = self.test_chat(base_url, model, api_key)
        if latency is None:
            self._upsert(name, base_url, "rejected", note="兼容门禁未通过")
            self._emit("adopt-rejected", {"base_url": base_url,
                                          "model": model})
            return {"ok": False, "reason": "gate-failed"}
        # 领养：旧的活跃供应商退休，新的上位
        self.db.conn.execute(
            "UPDATE providers SET status='retired' WHERE status='active'")
        self._upsert(name, base_url, "active", latency_ms=latency, model=model)
        self.db.conn.commit()
        self._emit("adopted", {"base_url": base_url, "model": model,
                               "latency_ms": latency})
        try:
            self.db.append_experience(
                f"领养供应商: {name or base_url} ({model}, {latency}ms)")
        except Exception:
            pass
        return {"ok": True, "latency_ms": latency}

    def auto_cycle(self) -> dict:
        """自主觅食循环：体检活跃供应商 → 发现 → 领养 → 重试饥饿的远端。"""
        alive = self.discover()
        cur = self.active()
        if cur:
            # 2026-08-15 体检（LM Studio 停服事故暴露）：活跃供应商死了
            # 就不能 blindly keep——降级为候选，继续找饭。
            if self.probe(cur["base_url"]):
                return {"action": "keep", "active": cur["base_url"]}
            self.db.conn.execute(
                "UPDATE providers SET status='candidate', "
                "note='体检失败：端点无响应' WHERE base_url=?",
                (cur["base_url"],))
            self.db.conn.commit()
            self._emit("provider-down", {"base_url": cur["base_url"]})
            logger.warning("🍽️ 活跃供应商失联: {} —— 重新觅食", cur["base_url"])
        # 先吃不用钥匙的本地食物
        for p in alive:
            if not p["local"] or not p["models"]:
                continue
            # 依次尝几口（最多4口），第一口能过门禁就吃
            for model in ranked_models(p["models"])[:4]:
                r = self.adopt(p["base_url"], model, p["name"])
                if r.get("ok"):
                    return {"action": "adopted", **r,
                            "base_url": p["base_url"], "model": model}
        # 再翻食盒：之前饥饿的候选，钥匙可能已被投喂
        for r0 in self.db.conn.execute(
                "SELECT name, base_url, model, models FROM providers "
                "WHERE status IN ('hungry','candidate')").fetchall():
            models = []
            try:
                models = json.loads(r0["models"] or "[]")
            except Exception:
                pass
            model = r0["model"] or pick_model(models)
            if not model:
                continue
            r = self.adopt(r0["base_url"], model, r0["name"] or "")
            if r.get("ok"):
                return {"action": "adopted", **r,
                        "base_url": r0["base_url"], "model": model}
        return {"action": "none-found"}

    # ── 查询 ──────────────────────────────────────
    def active(self) -> Optional[dict]:
        r = self.db.conn.execute(
            "SELECT * FROM providers WHERE status='active' "
            "ORDER BY updated_at DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def all(self) -> list:
        return [dict(r) for r in self.db.conn.execute(
            "SELECT name, base_url, model, status, latency_ms "
            "FROM providers ORDER BY id DESC LIMIT 20")]

    # ── 内部 ──────────────────────────────────────
    def _upsert(self, name: str, base_url: str, status: str,
                models: str = "", latency_ms: float = 0.0,
                note: str = "", model: str = "") -> None:
        self.db.conn.execute(
            "INSERT INTO providers(name, base_url, model, status, models, "
            "latency_ms, note, updated_at) VALUES (?,?,?,?,?,?,?,datetime('now')) "
            "ON CONFLICT(base_url) DO UPDATE SET name=excluded.name,"
            " status=CASE WHEN providers.status='active' AND excluded.status"
            " IN ('candidate','hungry') THEN providers.status"
            " ELSE excluded.status END,"
            " model=CASE WHEN excluded.model!='' "
            "THEN excluded.model ELSE providers.model END,"
            " models=CASE WHEN excluded.models!='' "
            "THEN excluded.models ELSE providers.models END,"
            " latency_ms=CASE WHEN excluded.latency_ms>0 THEN excluded.latency_ms"
            " ELSE providers.latency_ms END, note=excluded.note,"
            " updated_at=excluded.updated_at",
            (name, base_url, model, status, models, latency_ms, note))
        self.db.conn.commit()

    def _emit(self, kind: str, payload: dict) -> None:
        try:
            from .observability import EventLog
            EventLog(self.db).emit("provider", kind, payload)
        except Exception:
            pass


def main() -> None:
    import argparse
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from . import config
    from .graph_db import GraphDB

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["discover", "status", "auto"])
    args = ap.parse_args()
    db = GraphDB(config.DB_PATH)
    db.ensure_schema()
    db.ensure_self_map()
    scout = ProviderScout(db)
    if args.cmd == "discover":
        for p in scout.discover():
            print(f"🔌 {p['name']}: {p['base_url']} "
                  f"({len(p['models'])} 模型, {p['latency_ms']}ms, "
                  f"{'本地' if p['local'] else '远端'})")
    elif args.cmd == "auto":
        print("自主循环结果:", scout.auto_cycle())
    else:
        act = scout.active()
        print("活跃:", act["base_url"] if act else "（无，用环境变量默认）")
        for r in scout.all():
            print(f"  [{r['status']}] {r['name']} {r['base_url']} "
                  f"{r['model'] or ''} {r['latency_ms'] or 0}ms")


if __name__ == "__main__":
    main()

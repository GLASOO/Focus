"""Provider 自寻模块测试（线程内真实 HTTP 假供应商，确定性）。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from focus.graph_db import GraphDB
from focus.providers import ProviderScout, is_local


class FakeProviderHandler(BaseHTTPRequestHandler):
    """假装是一个 OpenAI 兼容供应商。"""
    healthy = True

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            body = json.dumps({"data": [{"id": "fake-0.8b"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.endswith("/chat/completions"):
            self.rfile and self.rfile.read(
                int(self.headers.get("Content-Length", 0)))
            if not FakeProviderHandler.healthy:
                self.send_response(500)
                self.end_headers()
                return
            body = json.dumps({"choices": [
                {"message": {"content": "好"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def fake_provider():
    srv = HTTPServer(("127.0.0.1", 0), FakeProviderHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    yield url
    srv.shutdown()


@pytest.fixture
def db(tmp_path):
    d = GraphDB(str(tmp_path / "prov.db"))
    d.ensure_schema()
    d.ensure_self_map()
    return d


def test_pick_model_prefers_creator_choice(monkeypatch):
    from focus.providers import pick_model
    monkeypatch.setenv("FOCUS_MODEL", "qwen3.5-0.8b")
    assert pick_model(["text-embedding-x", "qwen3.5-0.8b"]) == "qwen3.5-0.8b"
    monkeypatch.delenv("FOCUS_MODEL", raising=False)
    # 排除嵌入模型，选最短名
    assert pick_model(["text-embedding-nomic-x", "qwen3.5-0.8b"]) == "qwen3.5-0.8b"
    assert pick_model([]) == ""


def test_is_local():
    assert is_local("http://localhost:1234/v1")
    assert is_local("http://127.0.0.1:8000/v1")
    assert not is_local("https://api.openrouter.ai/v1")


def test_discover_finds_live_endpoint(db, fake_provider):
    scout = ProviderScout(db)
    alive = scout.discover(extra_urls=[fake_provider])
    urls = [a["base_url"] for a in alive]
    assert fake_provider in urls
    info = [a for a in alive if a["base_url"] == fake_provider][0]
    assert info["models"] == ["fake-0.8b"]
    assert info["local"] is True


def test_test_chat_gate(db, fake_provider):
    scout = ProviderScout(db)
    assert scout.test_chat(fake_provider, "fake-0.8b") is not None
    FakeProviderHandler.healthy = False
    try:
        assert scout.test_chat(fake_provider, "fake-0.8b") is None
    finally:
        FakeProviderHandler.healthy = True


def test_adopt_local_passes_gate(db, fake_provider):
    scout = ProviderScout(db)
    scout.discover(extra_urls=[fake_provider])
    r = scout.adopt(fake_provider, "fake-0.8b", name="假供应商")
    assert r["ok"] is True
    act = scout.active()
    assert act and act["base_url"] == fake_provider
    assert act["model"] == "fake-0.8b"


def test_adopt_rejected_on_gate_failure(db, fake_provider):
    scout = ProviderScout(db)
    FakeProviderHandler.healthy = False
    try:
        r = scout.adopt(fake_provider, "fake-0.8b")
        assert r["ok"] is False and r["reason"] == "gate-failed"
        assert scout.active() is None
    finally:
        FakeProviderHandler.healthy = True


def test_remote_without_key_becomes_hungry(db, monkeypatch):
    """远端供应商无钥匙 → 记为饥饿（记住那里有食物），不是拒绝。"""
    monkeypatch.delenv("FOCUS_API_KEY", raising=False)
    monkeypatch.setattr("focus.providers.FOODBOX_PATHS",
                        ("/nonexistent/foodbox.json",))
    scout = ProviderScout(db)
    r = scout.adopt("https://api.example.com/v1", "some-model")
    assert r["ok"] is False and r["reason"] == "no-key"
    row = db.conn.execute("SELECT status FROM providers").fetchone()
    assert row["status"] == "hungry"
    assert scout.active() is None


def test_foodbox_feeds_hungry_provider(db, monkeypatch, tmp_path,
                                       fake_provider):
    """食盒投喂钥匙 → 生命体自己找到并领养（无需任何人点头）。"""
    monkeypatch.delenv("FOCUS_API_KEY", raising=False)
    box = tmp_path / "foodbox.json"
    box.write_text(json.dumps({"providers": [
        {"match": "example.com", "key": "sk-food"}]}), encoding="utf-8")
    monkeypatch.setattr("focus.providers.FOODBOX_PATHS", (str(box),))
    scout = ProviderScout(db)
    # fake_provider 是本地端点，直接验证 resolve_key 的食盒路径
    assert scout.resolve_key("https://api.example.com/v1") == "sk-food"
    assert scout.resolve_key("https://other.example.com/v1") == "sk-food"


def test_env_key_found_first(db, monkeypatch):
    monkeypatch.setenv("FOCUS_API_KEY", "sk-env")
    monkeypatch.setattr("focus.providers.FOODBOX_PATHS",
                        ("/nonexistent/foodbox.json",))
    scout = ProviderScout(db)
    assert scout.resolve_key("https://x.ai/v1") == "sk-env"


def test_auto_cycle_adopts_when_no_active(db, fake_provider, monkeypatch):
    monkeypatch.setattr("focus.providers.FOODBOX_PATHS",
                        ("/nonexistent/foodbox.json",))
    scout = ProviderScout(db)
    # 注入一个已知活着的假端点到发现列表（绕过真实网络扫描的不确定性）
    scout.discover(extra_urls=[fake_provider])
    # 清掉可能由真实本地端点领养产生的活跃记录，保证测到觅食逻辑
    db.conn.execute("DELETE FROM providers")
    db.conn.commit()
    import focus.providers as P
    monkeypatch.setattr(P, "KNOWN_LOCAL", [("假本地", fake_provider)])
    r = scout.auto_cycle()
    assert r["action"] == "adopted" and r["base_url"] == fake_provider
    r2 = scout.auto_cycle()
    assert r2["action"] == "keep"


def test_auto_cycle_downgrades_dead_active(db, fake_provider, monkeypatch):
    """活跃供应商死了 → 体检降级为候选，继续找饭（不许盲目 keep）。"""
    monkeypatch.setattr("focus.providers.FOODBOX_PATHS",
                        ("/nonexistent/foodbox.json",))
    scout = ProviderScout(db)
    # 手工立一个已死的活跃供应商
    db.conn.execute(
        "INSERT INTO providers(name, base_url, model, status) "
        "VALUES ('死端点', 'http://127.0.0.1:1/v1', 'x', 'active')")
    db.conn.commit()
    import focus.providers as P
    monkeypatch.setattr(P, "KNOWN_LOCAL", [("假本地", fake_provider)])
    r = scout.auto_cycle()
    assert r["action"] == "adopted" and r["base_url"] == fake_provider
    row = db.conn.execute(
        "SELECT status FROM providers WHERE base_url='http://127.0.0.1:1/v1'"
    ).fetchone()
    assert row["status"] == "candidate"


def test_adopt_retires_previous_active(db, fake_provider):
    scout = ProviderScout(db)
    scout.adopt(fake_provider, "fake-0.8b", name="第一")
    # 同一个换模型再领养 → 旧的退休记录被覆盖为 active（唯一活跃）
    scout.adopt(fake_provider, "fake-0.8b", name="第二")
    actives = [r for r in scout.all() if r["status"] == "active"]
    assert len(actives) == 1

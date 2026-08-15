#!/usr/bin/env python3
"""自主觅食闭环实战演示（能力一：自主寻找并配置新 Provider）。

全程在隔离库上演练真实闭环：
  1. 起一个本地假食堂（OpenAI 兼容端点，带钥匙）
  2. 往食盒投喂钥匙
  3. 把食堂登记为候选（模拟发现）
  4. Agent 自主觅食：找钥匙 → 门禁验证 → 领养
  5. 断掉当前食堂 → Agent 体检发现 → 自动切换

运行：python scripts/demo_self_forage.py
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from focus.graph_db import GraphDB
from focus.providers import ProviderScout


class Canteen(BaseHTTPRequestHandler):
    """一家有钥匙的食堂。"""
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            body = json.dumps({"data": [{"id": "canteen-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps({"choices": [{"message": {"content": "好"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def main():
    srv = HTTPServer(("127.0.0.1", 0), Canteen)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    # 用远端语义演练：假装它是需要钥匙的远端食堂
    import focus.providers as P
    P.LOCAL_HOSTS = ("localhost",)  # 127.0.0.1 此刻按"远端"对待

    tmp = tempfile.mkdtemp()
    db = GraphDB(os.path.join(tmp, "forage.db"))
    db.ensure_schema()
    db.ensure_self_map()

    # 1. 食盒投喂钥匙（造物主的唯一动作）
    box = os.path.join(tmp, "foodbox.json")
    with open(box, "w") as f:
        json.dump({"providers": [{"match": "127.0.0.1", "key": "sk-demo"}]}, f)
    P.FOODBOX_PATHS = (box,)

    # 2. 登记为候选（发现）
    scout = ProviderScout(db)
    db.conn.execute(
        "INSERT INTO providers(name, base_url, status, models) "
        "VALUES ('演示食堂', ?, 'candidate', ?)",
        (url, json.dumps(["canteen-model"])))
    db.conn.commit()
    print(f"① 发现新食堂: {url}")
    print("② 食盒已投喂钥匙: sk-demo")

    # 3. 自主觅食循环
    r = scout.auto_cycle()
    print(f"③ 自主觅食结果: {r['action']} → {r.get('base_url')} "
          f"({r.get('model')})")
    assert r["action"] == "adopted", "闭环失败"
    act = scout.active()
    assert act and act["base_url"] == url
    print("④ 已自主领养为活跃供应商 ✅")

    # 4. 当前食堂死掉 → 体检降级 + 重新觅食（切换能力）
    db.conn.execute("UPDATE providers SET status='active', "
                    "base_url='http://127.0.0.1:9/v1' WHERE rowid=("
                    "SELECT MIN(rowid) FROM providers)")
    srv.shutdown()
    srv2 = HTTPServer(("127.0.0.1", 0), Canteen)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    url2 = f"http://127.0.0.1:{srv2.server_address[1]}/v1"
    db.conn.execute(
        "INSERT INTO providers(name, base_url, status, models) "
        "VALUES ('备用餐馆', ?, 'candidate', ?)",
        (url2, json.dumps(["canteen-model"])))
    db.conn.commit()
    r2 = scout.auto_cycle()
    print(f"⑤ 食堂死亡后的自主切换: {r2['action']} → {r2.get('base_url')}")
    assert r2["action"] in ("adopted", "switched"), "切换失败"
    print("⑥ 闭环完成：发现→钥匙→验证→领养→故障→切换，全程自主 ✅")
    srv2.shutdown()


if __name__ == "__main__":
    main()

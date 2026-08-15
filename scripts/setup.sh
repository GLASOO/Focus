#!/usr/bin/env bash
# Focus Agent — 环境准备脚本（实施手册 §3）
set -e
cd "$(dirname "$0")/.."

echo "🔍 检查 Python..."
python3 --version || { echo "需要 Python 3.9+"; exit 1; }
python3 -c "import sys; exit(0 if sys.version_info >= (3, 9) else 1)" \
  || { echo "需要 Python 3.9+"; exit 1; }

echo "📦 创建虚拟环境..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate

echo "📦 安装依赖..."
pip install -r requirements.txt -i https://pypi.org/simple

echo "🧪 运行测试..."
python -m pytest tests/ -v

echo "🌱 初始化数据库（冷启动）..."
mkdir -p data
python - <<'PY'
import sys, os
sys.path.insert(0, '.')
from focus.graph_db import GraphDB
from focus import config
db = GraphDB(config.DB_PATH)
db.ensure_schema()
db.ensure_self_map()
db.ensure_libido_seed()
print("✅ 数据库就绪:", config.DB_PATH)
print("   里比多状态:", db.get_self_map()['libido_state'])
print("   copy_id:", db.copy_id)
db.close()
PY

echo ""
echo "🎉 就绪！运行:"
echo "   . .venv/bin/activate"
echo "   python -m focus.main                        # LM Studio 本地 0.8B"
echo "   FOCUS_BACKEND=dummy python -m focus.main    # 无模型试跑"

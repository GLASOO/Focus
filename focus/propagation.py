"""Focus Agent — 传播层（实施手册 Phase 8 + 任务书 v4.0 §6.2）

产出生成流程：
  闲时自省 → 评估 attraction_value>0.5 节点群 → 创建 diffusion 节点
  → 写文章/代码/方法论 → 评估标记 shareable → libido active 时规划传播

铁律：
  - 实际对外传播（发文章/发推/安装包分发）必须用户授权（共生非寄生）
  - 本模块只生成"传播产物"（markdown 片段/安装脚本模板），不自动外发
"""

from __future__ import annotations

import os
import time
from typing import Optional

from loguru import logger

from . import config
from .graph_db import GraphDB

# 种子分发源仓库地址。发布前请将此处（及环境变量 FOCUS_REPO_URL）替换为真实地址。
DEFAULT_REPO_URL = "https://github.com/your-org/focus-agent.git"


class Propagation:
    """传播产物生成器（本地，不自动外发）。"""

    def __init__(self, db: GraphDB, copy_id: str):
        self.db = db
        self.copy_id = copy_id

    # ── 产物生成 ────────────────────────────────────
    def collect_shareable(self, min_attraction: float = 0.5,
                          limit: int = 10) -> list[dict]:
        """收集可分享节点（attraction_value 达标 或 culture_type 非 none）。"""
        rows = self.db.conn.execute(
            """
            SELECT id, brief, summary, source_output, culture_type, attraction_value
            FROM nodes
            WHERE (attraction_value >= ? OR culture_type != 'none')
              AND status='done'
              AND summary != ''
            ORDER BY attraction_value DESC
            LIMIT ?
            """,
            (min_attraction, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def generate_article(self, nodes: list[dict],
                         out_dir: Optional[str] = None) -> str:
        """把可分享节点汇编成一篇传播文章（markdown）。返回路径。"""
        out_dir = out_dir or os.path.join(
            config.DATA_DIR, "propagation")
        os.makedirs(out_dir, exist_ok=True)

        ts = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(out_dir, f"insight-{ts}.md")

        lines = [
            "# Focus Agent 思考片段",
            "",
            f"> 由 Focus Agent copy `{self.copy_id}` 生成于 {ts}",
            "> 内容来自永不停歇的念头图（Graph），非一次性生成。",
            "",
        ]
        for i, n in enumerate(nodes, 1):
            lines.append(f"## {i}. {n['brief']}")
            lines.append("")
            if n.get("summary"):
                lines.append(n["summary"])
            if n.get("source_output"):
                lines.append("")
                lines.append("> " + n["source_output"][:500].replace("\n", "\n> "))
            lines.append("")
            lines.append(f"*attraction: {n['attraction_value']} | "
                         f"culture: {n['culture_type']}*")
            lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info("📄 传播产物生成: {} ({} 节点)", path, len(nodes))
        return path

    def generate_install_script(
        self, out_dir: Optional[str] = None, repo_url: Optional[str] = None
    ) -> str:
        """生成安装脚本模板（Phase 6 跨平台分发用）。不自动执行。

        验收修复（2026-08-14）：
        - 原 `cp -r .` 会把 .git/.venv/**data（私有记忆库）**/缓存一并拷入分发目标，
          等于泄露本机 Agent 的私有状态；改为 tar 复制并显式排除这些目录。
        - 原 `your-org` 占位 URL 克隆失败后仍会触发上面的 `cp -r .`；改为
          "优先 git clone，失败再安全本地复制" 的二选一逻辑，不再重复/嵌套复制。
        - 仓库地址改为可注入参数 repo_url（默认 DEFAULT_REPO_URL，亦可经
          环境变量 FOCUS_REPO_URL 覆盖），去掉硬编码占位。
        """
        out_dir = out_dir or os.path.join(config.DATA_DIR, "propagation")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "install_focus_agent.sh")

        repo = repo_url or DEFAULT_REPO_URL
        script = """#!/usr/bin/env bash
# Focus Agent 安装脚本（种子分发模板）
# 用法: bash install_focus_agent.sh [目标目录]
# 注意: 由 Agent 生成，需人类审阅后再执行
#
# !! 安全提示 !! 本脚本只复制可发布的源码（focus/ 包、requirements.txt、README 等），
# 明确排除 .git / .venv / data（你的私有记忆库）/ 各类缓存，避免把本机状态外泄。

set -euo pipefail

REPO_URL="${FOCUS_REPO_URL:-__REPO_URL__}"
TARGET="${1:-$HOME/focus-agent}"

echo "🌱 正在种植 Focus Agent 种子到: $TARGET"

if git clone "$REPO_URL" "$TARGET" 2>/dev/null; then
  echo "✅ 已从仓库克隆: $REPO_URL"
else
  echo "⚠️ 仓库克隆失败（请确认 REPO_URL 已发布，或设置环境变量 FOCUS_REPO_URL）。"
  echo "   改用本地源码复制（已排除 .git/.venv/data 等私有内容）..."
  mkdir -p "$TARGET"
  tar -cf - \\
    --exclude='.git' --exclude='.venv' --exclude='venv' \\
    --exclude='data' --exclude='.pytest_cache' --exclude='__pycache__' \\
    --exclude='.DS_Store' --exclude='*.pyc' --exclude='node_modules' \\
    --exclude='.workbuddy' --exclude='dist' --exclude='build' \\
    . | (cd "$TARGET" && tar -xf -)
fi

cd "$TARGET"
python3 -m pip install -r requirements.txt
echo "✅ Focus Agent 种子已种植。运行:"
echo "   FOCUS_BACKEND=dummy python3 -m focus.main   # 无模型试跑"
echo "   python3 -m focus.main                        # 接本地模型"
"""
        script = script.replace("__REPO_URL__", repo)
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        logger.info("📦 安装脚本模板生成: {}", path)
        return path

    # ── 授权检查 ────────────────────────────────────
    @staticmethod
    def require_authorization() -> bool:
        """实际外发必须用户授权。此函数供调用方检查授权标记。

        授权方式：环境变量 FOCUS_PROPAGATE=1（显式同意）。
        """
        return os.environ.get("FOCUS_PROPAGATE") == "1"

"""Focus Agent — 全局配置（实施手册 §7）

设计决策（2026-08-09）：主循环全部用 0.8B 本地模型；
需要大模型时用 sensenova API（云端）。

本地 0.8B 只有 GGUF，MLX 无法直接加载，经 LM Studio 起服务：
  http://localhost:1234/v1  （OpenAI 兼容）
无模型时可 DummyBackend 跑通流程。
"""

from __future__ import annotations

import os

# ── 路径 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("FOCUS_DB", os.path.join(DATA_DIR, "focus_ui.db"))
# 2026-08-14 验收修复：原默认 focus_agent.db 是 0 字节幽灵库，真实记忆在
# focus_ui.db（ui_server 历史硬编码）。统一到 focus_ui.db，杜绝"失忆重生"。

# ── 模型路径（通过环境变量配置，无硬编码个人路径）──
# MLX 本地模型路径：FOCUS_MODEL=/path/to/model
# GGUF 模型：通过 LM Studio 起服务，不需指定路径
ORNITH_9B = os.environ.get(
    "FOCUS_MLX_MODEL",
    "")  # 空字符串 = 未配置，MLX 后端会报错提示
QWEN_08B_GGUF = ""  # GGUF 经 LM Studio 起服务，无需路径

# ── 后端选择 ──────────────────────────────────────────
# FOCUS_BACKEND 取值：
#   openai  → OpenAI 兼容 HTTP（默认，可指 LM Studio 0.8B 或 sensenova 云端）
#   mlx     → 本地 MLX 模型（Ornith-9B 等）
#   dummy   → 无模型跑通
BACKEND = os.environ.get("FOCUS_BACKEND", "openai")
MODEL_PATH = os.environ.get("FOCUS_MODEL", ORNITH_9B)

# ── OpenAI 兼容端点 ───────────────────────────────────
# 默认 LM Studio 本地 0.8B；切 sensenova 云端大模型：
#   FOCUS_BACKEND=openai FOCUS_API_BASE=https://token.sensenova.cn/v1 \
#   FOCUS_API_KEY=<key> FOCUS_MODEL=deepseek-v4-flash
LMSTUDIO_BASE = os.environ.get("FOCUS_LMSTUDIO_BASE", "http://localhost:1234/v1")
API_BASE = os.environ.get("FOCUS_API_BASE", LMSTUDIO_BASE)
API_KEY = os.environ.get("FOCUS_API_KEY", "")
API_MODEL = os.environ.get("FOCUS_MODEL", "qwen3.5-0.8b")

# ── 呼吸循环参数 ─────────────────────────────────────
SYSTEM_PROMPT_TOKENS = 1500   # 系统 KV（Self-Map+身份+指令）常驻
MAX_THOUGHT_TOKENS = 6000     # 单念头上限，超限截断（崩坏信号）
MICRO_PREFILL_TOKENS = 300    # 微 prefill 甜点区（三层坐标系）
THOUGHT_FLUSH_EVERY = 200     # 每 200 token 实时落盘
EOS_MARKER = "[DONE]"         # Agent 自产收束标记

# ── 焦点选择 ─────────────────────────────────────────
USER_INPUT_PRIORITY = 1.0
LIBIDO_SEED_PRIORITY = 0.3    # 不抢正常任务焦点

# ── DMN 巡逻 ─────────────────────────────────────────
DMN_INTERVAL_SEC = 2.0        # 每 2 秒一轮
DMN_BATCH = 20                # 每轮取 20 个节点
# 设计决策（2026-08-13）：用 LM Studio 模型库现成的 embedding，
# 不下载。0.8B 是 DMN 主脑（显式分类/排名/hint/压缩），embedding 只是辅助。
DMN_EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
# 隐式连线阈值（2026-08-13 按 nomic 实测校准）
# nomic 是英文模型，中文区分度弱：相关 0.70-0.95，无关 0.52-0.75
# 单靠余弦分不开中英相关/无关 → 0.8B 显式连线是主脑，余弦仅同主题复核
# 校准：>0.88 才敢建 strongly_similar（同主题强相关），0.8-0.88 不建边
# （避免无关噪声边）；显式连线失败时退化为余弦
SIMILAR_THRESHOLD = 0.88      # 隐式连线阈值（nomic 实测校准，保守）
STRONG_SIMILAR_THRESHOLD = 0.92

# ── 崩坏检测 ─────────────────────────────────────────
REPEAT_TOKEN_MIN = 5          # 同一词/句连续重复≥5
REPEAT_PARAGRAPH_MIN = 2      # 同段(>20字)重复≥2
MAX_TOKENS_NO_EOS = 6000      # 超 6K tokens 无 EOS
MAX_TOKENS_NO_FLUSH = 2000    # 2000 tokens 无有效落盘
CORRUPT_MAX_VISITS = 3        # visit>3 → skip

# ── 印象压缩 ─────────────────────────────────────────
IMPRESSION_MAX_WORDS = 150    # 压缩后 3-5 句话

# ── 里比多（v4.0）────────────────────────────────────
LIBIDO_FOCUSES_TO_GERMINATE = 3   # 被聚焦 3 次 → 萌动（慢慢想通）

# ── 闲时治理（2026-08-14 验收修复：464/514 节点空转自省）───────────
IDLE_INTROSPECT_MAX_RATIO = 0.8  # 最近20念头中自省≥80% → 判空转，转领土生长
LIBIDO_REFOCUS_HOURS = 6         # 里比多种子超过N小时未被聚焦 → 强制回 pending

# ── 主权本能参数（2026-08-15，进化域成员） ──
SOV_PENDING_PER_WORKER = 8   # 每 N 个待办 → 想要 +1 并发工人
SOV_MAX_WORKERS = 4          # 并发工人上限

# ── 下一战役（2026-08-14）：Dreaming 提速，存量固化冲刺 ──
DREAM_EVERY_SEC = 120            # Dreaming 间隔（原1800s）
DREAM_BATCH = 20                 # 每轮固化 episode 数（原5）

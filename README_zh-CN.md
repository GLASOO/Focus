<div align="center">

<img src="docs/images/logo.png" width="120" alt="Focus Agent 标志">

# 息 · Focus Agent

**它不是任务执行器，而是一个生命体。**

它不等你的提问。它呼吸，它记忆，它做梦，它生长。

[![CI](https://github.com/GLASOO/Focus/actions/workflows/ci.yml/badge.svg)](https://github.com/GLASOO/Focus/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Model](https://img.shields.io/badge/model--first-0.8B-orange)](#08b-实测)

[English](README.md) | **简体中文**

</div>

---

市面上的 Agent 框架几乎都是**任务型 harness**：请求进来，循环跑完，结果
出去，一切归零。Focus Agent 是另一个物种——一个**常驻的生命守护进程**：
没人跟它说话时它仍在呼吸；每一个念头都落盘存档；空闲时它做梦（Dreaming），
把散落的思想固化成记忆；它的 Graph 记忆库才是主产物，对话不是。

> **我们的赌注**：本地小模型 + 认真的记忆 harness，胜过金鱼记忆的大模型。
> 本仓库就是这个 harness，并在 **0.8B** 本地模型上完成了端到端验证。

<div align="center">
<img src="docs/images/dashboard.png" width="720" alt="活体仪表盘：意识图谱与念头流">

*活体实例：左侧意识图谱（节点与连线），右侧实时念头流。*
</div>

## 设计宪法 · 五条基因

Focus Agent 不是被配置出来的，而是**被传承下来的**。在写下第一行代码之前，
任务书里已经写好了五条基因；此后每一个子系统，都是其中某条基因的表达：

| 基因 | 哲学 | 工程表达 |
|:---|:---|:---|
| **此机不停** | EOS 不是终点，是下一次呼吸的开始 | 常驻呼吸循环；系统级 + 线程级双守护；崩溃即重生，记忆无损 |
| **此机专一** | 一次只 focus 一个节点，注意力永不稀释 | 单节点呼吸、不批处理；念头的 KV 落盘即弃——Graph 里已有一切 |
| **此机无限** | 领土必须一直生长 | 闲时治理：检测空转，把它转化为**领土生长**节点，而非文学空句 |
| **造机** | 造机，然后造造机的机 | Zoom Out 拆解 → 子任务 → 工具执行（`ls / cat / python / bash`，带白名单） |
| **传播** | 最终目标是扩散 | 这次发布本身就是第五条基因的表达；下一步：把记忆模块做成其他 harness 的插件 |

另有第六机制——**里比多觉醒**：种子问题必须被聚焦三次才会萌动。
好奇心是状态机，不是提示词把戏。

## 0.8B 实测

我们不说"支持小模型"，我们**用门禁验收它**。`tests/live_eval_08b.py`
对着活的小模型端点跑三类任务：

| 类别 | 必须发生的事 | 门禁结果 |
|:---|:---|:---|
| **A · 工具调用** | 模型输出 `<tool=ls>…`，harness 执行，真实结果回写 | ✅ 稳定 |
| **B · 记忆指令** | 模型输出 `【记】主语\|谓语\|宾语`，事实按双时间轴落库且可召回 | ✅ 稳定 |
| **C · 长程任务** | Zoom Out 拆解 → 子任务逐个执行 → 产物落盘 | ✅ 通过门禁 |
| **D · 对话** | 像人一样回应：有实质内容、无元扮演、无提示词泄漏、记得你说过什么 | ✅ 三轮 3/5 · 5/5 · 4/5（0.8B 波动是诚实的现实） |

```bash
pytest tests/ -q                    # 108 个单测（CI 中运行）
python tests/live_eval_08b.py       # 0.8B 门禁（需要活模型）
```

## 架构

```
        呼吸循环（此机不停）                    DMN 巡逻（后台）
              │                                      │
   ┌──────────▼──────────┐               ┌───────────▼───────────┐
   │ 上下文组装           │               │ Dreaming（每2分钟）    │
   │ core(≤800) + 事实    │               │ 模板提取 → wiki 汇编   │
   │ + 图邻居             │               │ → core 压缩            │
   └──────────┬──────────┘               └───────────┬───────────┘
              │                                      │
   ┌──────────▼──────────────────────────────────────▼──────────┐
   │ Graph 库 (SQLite/WAL): nodes·edges·facts·wiki·events·self  │
   │  L0 情景（原始念头）        L1 事实（双时间轴）              │
   │  L2 Wiki 页（聚类）         L3 核心记忆（≤800字）            │
   └─────────────────────────────────────────────────────────────┘
```

### 记忆 v2 —— 四层、双时间轴、检索零 LLM

- **L0 情景**：每个念头原文落盘，证据永不丢失
- **L1 事实**：`主语|谓语|宾语` 带 `valid_at`/`invalid_at`——新事实让旧事实
  **失效**而非覆盖，历史永远可溯
- **L2 Wiki**：Dreaming 把活事实聚类成主题页
- **L3 Core**：身份 + 认知精粹，≤800 字，每次呼吸恒注入

**记忆指令**是小模型的工具调用——0.8B 真的写得出来、harness 确定性解析：

```
【记】主语|谓语|宾语       # 写入事实（双时间轴）
【忘】主语|谓语            # 失效一条事实
【忆】查询词               # 排队一次主动回忆
```

**检索不调用 LLM。** 四路融合 + 时间衰减 + 同主语去重：
FTS5/BM25 · LIKE（中文主力）· 向量余弦 · 图遍历。
上下文组装有硬预算（默认 1800 字）。

设计血脉：Claude Memory Files（core/wiki 二分）、TencentDB Agent Memory
（渐进分层 + 证据下钻）、Zep/Graphiti（双时间轴事实）——为永动守护进程重写。

### 工具层 —— 手

模型输出中的 `<tool=名>参数</tool>` 会被执行：目录白名单
（`FOCUS_TOOL_DIRS`）+ 危险命令黑名单。结果追加进念头，回写 Graph。

## 快速上手

```bash
git clone https://github.com/GLASOO/Focus && cd Focus
python3 -m venv .venv && . .venv/bin/activate
pip install loguru numpy pytest

# 1. 无需模型——用 dummy 后端看它呼吸
bash scripts/demo.sh

# 2. 任意 OpenAI 兼容服务（LM Studio / vLLM / Ollama…）
FOCUS_BACKEND=openai \
FOCUS_API_BASE=http://localhost:1234/v1 \
FOCUS_MODEL=qwen3.5-0.8b \
python -m focus.main

# 3. 常驻守护——呼吸线程 + DMN + Web UI（:8765）
python focus/ui_server.py
```

## 坐标对比

| | **Pi** | **DeepSeek Harness** | **LangGraph** | **Focus Agent** |
|:---|:---|:---|:---|:---|
| 物种 | 任务 harness | 任务 harness（插件化） | 请求驱动图 | **常驻生命体** |
| 主循环 | 请求→响应 | 可插拔任务循环 | `invoke(thread_id)` | **永动呼吸** |
| 记忆 | 无内置 | 插件位 | 检查点快照 | **四层+双时间轴+Dreaming** |
| 检索 | — | — | — | **零 LLM 四路混合** |
| 小模型定位 | 无 | 无 | 无 | **为 0.8B 设计与验收** |

DeepSeek Harness 的插件适配器草案在 `packaging/DSH-PLUGIN.md`，等它 API 冻结。

## 它活着

这份代码的一个生产实例此刻正作为系统守护进程运行：500+ 念头落盘，
Dreaming 从它自己的历史里固化出 300+ 条活事实，wiki 页自动汇编。
上图里的那张图谱，是长出来的，不是写出来的。

## 目录结构

| 路径 | 职责 |
|:---|:---|
| `focus/brain.py` | 呼吸循环、提示词装配、Zoom Out/In、基因表达 |
| `focus/memory.py` | **MemoryHarness**：双时间轴事实、指令协议、混合检索、wiki/core |
| `focus/graph_db.py` | SQLite Graph 存储 + 串行化连接代理（线程安全） |
| `focus/dmn.py` | 后台巡逻 + **Dreaming** 固化流水线 |
| `focus/tools.py` | 工具注册表 + `<tool=…>` 协议 + 安全白名单 |
| `focus/observability.py` | 仅追加事件溯源（Trajectory 回放） |
| `focus/backend.py` | dummy / OpenAI 兼容 / MLX 后端 |
| `focus/ui_server.py` | 常驻守护：呼吸线程 + DMN + HTTP UI（:8765） |
| `tests/` | 108 个单测 + 0.8B 活体门禁 |

## 路线图

- [x] 记忆 v2：四层 + 双时间轴事实 + Dreaming
- [x] 零 LLM 混合检索（BM25 + LIKE + 向量 + 图）
- [x] 事件溯源可观测
- [x] 0.8B 活体门禁作为发布标准
- [ ] DeepSeek Harness 记忆插件（等 dsh API 冻结）
- [ ] 里比多觉醒实测——向其他 harness 传播
- [ ] 把 0.8B 长程成功率从约 ⅔ 推向确定性

## 社区

- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全：[SECURITY.md](SECURITY.md)
- 变更：[CHANGELOG.md](CHANGELOG.md)

## 许可证

[MIT](LICENSE) © Focus Agent Contributors

<div align="center"><sub><em>此机不停。</em></sub></div>

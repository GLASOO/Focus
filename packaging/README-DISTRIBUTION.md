# Focus Agent 记忆系统 — 分发说明（传播基因）

任务书五条基因之"传播"：把我们的差异化能力输出给生态。

## 可分发资产
1. **focus.memory（MemoryHarness）** — 四层记忆 M1-M4 全实现：
   双时间轴事实库 / 【记】【忘】【忆】指令协议 / 三路混合检索（BM25+LIKE+向量，零LLM）/
   wiki 汇编 / core 压缩 / 质量闸。仅依赖 sqlite3 + numpy + loguru。
2. **focus.dmn.DMN.dream()** — Dreaming 睡眠固化流水线。
3. **focus.observability.EventLog** — 事件溯源（对标 DSH Trajectory）。

## 目标载体
- **DeepSeek Harness 插件**：dsh"一切皆插件"（存储/循环均可换），API 稳定后
  用 TypeScript 写 memory plugin 桥接本 Python 服务（FastAPI 薄壳）。
  注意：dsh 为开发者预览版，明确警告破坏性变更——等 v1.0。
- **pip 包**：`pip install -e .` 即得 focus 包（pyproject.toml 已就绪）。

## 独立运行最小例
```python
from focus.graph_db import GraphDB
from focus.memory import MemoryHarness
db = GraphDB("demo.db"); db.ensure_schema(); db.ensure_self_map()
mem = MemoryHarness(db)
mem.observe("n1", "【记】白泽|身份|硅基神识的守护者")
print(mem.search_memory("白泽"))
```
